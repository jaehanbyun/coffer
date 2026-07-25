package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"sort"
	"time"

	distribution "github.com/distribution/distribution/v3"
	"github.com/distribution/distribution/v3/registry/storage"
	storagedriver "github.com/distribution/distribution/v3/registry/storage/driver"
	"github.com/distribution/distribution/v3/registry/storage/driver/filesystem"
	"github.com/distribution/reference"
	digest "github.com/opencontainers/go-digest"
	v1 "github.com/opencontainers/image-spec/specs-go/v1"
)

const (
	evidenceSchema       = "coffer.distribution-storage-scan/v1"
	s3EvidenceSchema     = "coffer.distribution-storage-scan/v2"
	distributionVersion  = "v3.1.1"
	distributionRevision = "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
	enumeratorName       = "distribution.storage.RepositoryEnumerator+ManifestEnumerator"
	maxPageSize          = 1000
)

type referenceFact struct {
	Digest    string `json:"digest"`
	MediaType string `json:"media_type"`
	Size      int64  `json:"size"`
}

type manifestFact struct {
	ContentDigest    string          `json:"content_digest"`
	EnumeratedDigest string          `json:"enumerated_digest"`
	MediaType        string          `json:"media_type"`
	References       []referenceFact `json:"references"`
	Repository       string          `json:"repository"`
	Size             int64           `json:"size"`
	Tagged           bool            `json:"tagged"`
}

func (fact manifestFact) key() string {
	return fact.Repository + "@" + fact.EnumeratedDigest
}

type page struct {
	After    *string        `json:"after"`
	Items    []manifestFact `json:"items"`
	Next     *string        `json:"next"`
	Sequence int            `json:"sequence"`
}

type summary struct {
	PageCount        int    `json:"page_count"`
	RecordCount      int    `json:"record_count"`
	RepositoryCount  int    `json:"repository_count"`
	RepositorySHA256 string `json:"repository_sha256"`
	SHA256           string `json:"sha256"`
}

type scanEvidence struct {
	Pages        []page   `json:"pages"`
	Phase        string   `json:"phase"`
	Repositories []string `json:"repositories"`
	Summary      summary  `json:"summary"`
}

type evidence struct {
	DistributionVersion string           `json:"distribution_version"`
	Enumerator          string           `json:"enumerator"`
	Backend             *backendEvidence `json:"backend,omitempty"`
	PageSize            int              `json:"page_size"`
	Scans               []scanEvidence   `json:"scans"`
	Schema              string           `json:"schema"`
}

func referenceFacts(descriptors []v1.Descriptor) ([]referenceFact, error) {
	byDigest := make(map[string]referenceFact, len(descriptors))
	for _, descriptor := range descriptors {
		fact := referenceFact{
			Digest:    descriptor.Digest.String(),
			MediaType: descriptor.MediaType,
			Size:      descriptor.Size,
		}
		if err := descriptor.Digest.Validate(); err != nil {
			return nil, fmt.Errorf("invalid reference digest: %w", err)
		}
		if descriptor.Digest.Algorithm() != digest.SHA256 {
			return nil, errors.New("non-sha256 reference digest")
		}
		if descriptor.Size < 0 || descriptor.MediaType == "" {
			return nil, errors.New("invalid reference size or media type")
		}
		if previous, ok := byDigest[fact.Digest]; ok && previous != fact {
			return nil, errors.New("conflicting reference facts")
		}
		byDigest[fact.Digest] = fact
	}
	facts := make([]referenceFact, 0, len(byDigest))
	for _, fact := range byDigest {
		facts = append(facts, fact)
	}
	sort.Slice(facts, func(i, j int) bool {
		return facts[i].Digest < facts[j].Digest
	})
	return facts, nil
}

type scanResult struct {
	Repositories []string
	Facts        []manifestFact
}

func namespaceFromDriver(ctx context.Context, driver storagedriver.StorageDriver) (distribution.Namespace, error) {
	namespace, err := storage.NewRegistry(ctx, driver)
	if err != nil {
		return nil, fmt.Errorf("construct registry namespace: %w", err)
	}
	return namespace, nil
}

func scan(ctx context.Context, namespace distribution.Namespace) (scanResult, error) {
	repositoryEnumerator, ok := namespace.(distribution.RepositoryEnumerator)
	if !ok {
		return scanResult{}, errors.New("namespace lacks repository enumeration")
	}

	var repositoryNames []string
	if err := repositoryEnumerator.Enumerate(ctx, func(name string) error {
		repositoryNames = append(repositoryNames, name)
		return nil
	}); err != nil {
		return scanResult{}, fmt.Errorf("enumerate repositories: %w", err)
	}
	sort.Strings(repositoryNames)
	for index := 1; index < len(repositoryNames); index++ {
		if repositoryNames[index-1] == repositoryNames[index] {
			return scanResult{}, errors.New("repository enumeration returned a duplicate")
		}
	}

	var facts []manifestFact
	for _, repositoryName := range repositoryNames {
		named, err := reference.WithName(repositoryName)
		if err != nil {
			return scanResult{}, fmt.Errorf("invalid repository name: %w", err)
		}
		repository, err := namespace.Repository(ctx, named)
		if err != nil {
			return scanResult{}, fmt.Errorf("open repository: %w", err)
		}
		manifestService, err := repository.Manifests(ctx)
		if err != nil {
			return scanResult{}, fmt.Errorf("open manifest service: %w", err)
		}
		manifestEnumerator, ok := manifestService.(distribution.ManifestEnumerator)
		if !ok {
			return scanResult{}, errors.New("manifest service lacks revision enumeration")
		}
		var revisions []digest.Digest
		if err := manifestEnumerator.Enumerate(ctx, func(revision digest.Digest) error {
			revisions = append(revisions, revision)
			return nil
		}); err != nil {
			return scanResult{}, fmt.Errorf("enumerate manifest revisions: %w", err)
		}
		sort.Slice(revisions, func(i, j int) bool {
			return revisions[i].String() < revisions[j].String()
		})
		for _, revision := range revisions {
			if err := revision.Validate(); err != nil || revision.Algorithm() != digest.SHA256 {
				return scanResult{}, errors.New("manifest revision is not canonical sha256")
			}
			manifest, err := manifestService.Get(ctx, revision)
			if err != nil {
				return scanResult{}, fmt.Errorf("load manifest revision: %w", err)
			}
			mediaType, payload, err := manifest.Payload()
			if err != nil {
				return scanResult{}, fmt.Errorf("read manifest payload: %w", err)
			}
			contentDigest := digest.FromBytes(payload)
			if contentDigest != revision {
				return scanResult{}, errors.New("manifest payload digest differs from revision link")
			}
			references, err := referenceFacts(manifest.References())
			if err != nil {
				return scanResult{}, err
			}
			tags, err := repository.Tags(ctx).Lookup(ctx, v1.Descriptor{Digest: revision})
			if err != nil {
				return scanResult{}, fmt.Errorf("look up manifest tags: %w", err)
			}
			facts = append(facts, manifestFact{
				ContentDigest:    contentDigest.String(),
				EnumeratedDigest: revision.String(),
				MediaType:        mediaType,
				References:       references,
				Repository:       repositoryName,
				Size:             int64(len(payload)),
				Tagged:           len(tags) > 0,
			})
		}
	}
	sort.Slice(facts, func(i, j int) bool {
		return facts[i].key() < facts[j].key()
	})
	return scanResult{Repositories: repositoryNames, Facts: facts}, nil
}

func checksum(facts []manifestFact) (string, error) {
	hash := sha256.New()
	for _, fact := range facts {
		encoded, err := json.Marshal(fact)
		if err != nil {
			return "", fmt.Errorf("encode manifest fact: %w", err)
		}
		if _, err := hash.Write(append(encoded, '\n')); err != nil {
			return "", fmt.Errorf("hash manifest fact: %w", err)
		}
	}
	return "sha256:" + hex.EncodeToString(hash.Sum(nil)), nil
}

func repositoryChecksum(repositories []string) string {
	hash := sha256.New()
	for _, repository := range repositories {
		_, _ = hash.Write([]byte(repository + "\n"))
	}
	return "sha256:" + hex.EncodeToString(hash.Sum(nil))
}

func evidenceScan(phase string, result scanResult, pageSize int) (scanEvidence, error) {
	facts := result.Facts
	pages := make([]page, 0, (len(facts)+pageSize-1)/pageSize)
	var after *string
	for offset := 0; offset < len(facts); offset += pageSize {
		end := min(offset+pageSize, len(facts))
		items := append([]manifestFact(nil), facts[offset:end]...)
		var next *string
		lastKey := items[len(items)-1].key()
		if end < len(facts) {
			next = &lastKey
		}
		pages = append(pages, page{
			After:    after,
			Items:    items,
			Next:     next,
			Sequence: len(pages),
		})
		afterKey := lastKey
		after = &afterKey
	}
	digest, err := checksum(facts)
	if err != nil {
		return scanEvidence{}, err
	}
	return scanEvidence{
		Pages:        pages,
		Phase:        phase,
		Repositories: result.Repositories,
		Summary: summary{
			PageCount:        len(pages),
			RecordCount:      len(facts),
			RepositoryCount:  len(result.Repositories),
			RepositorySHA256: repositoryChecksum(result.Repositories),
			SHA256:           digest,
		},
	}, nil
}

func run(
	ctx context.Context,
	namespace distribution.Namespace,
	pageSize int,
	backend *backendEvidence,
) error {
	startFacts, err := scan(ctx, namespace)
	if err != nil {
		return fmt.Errorf("start scan: %w", err)
	}
	endFacts, err := scan(ctx, namespace)
	if err != nil {
		return fmt.Errorf("end scan: %w", err)
	}
	start, err := evidenceScan("start", startFacts, pageSize)
	if err != nil {
		return err
	}
	end, err := evidenceScan("end", endFacts, pageSize)
	if err != nil {
		return err
	}
	schema := evidenceSchema
	if backend != nil {
		schema = s3EvidenceSchema
	}
	result := evidence{
		DistributionVersion: distributionVersion,
		Enumerator:          enumeratorName,
		Backend:             backend,
		PageSize:            pageSize,
		Scans:               []scanEvidence{start, end},
		Schema:              schema,
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(result); err != nil {
		return fmt.Errorf("write evidence: %w", err)
	}
	return nil
}

func main() {
	root := flag.String("root", "", "read-only Distribution filesystem root")
	configPath := flag.String("config", "", "owner-only Distribution S3 configuration")
	expectedVersion := flag.String("expected-distribution-version", "", "exact Distribution release")
	expectedConfigSHA256 := flag.String("expected-config-sha256", "", "sha256:<hex> of the configuration")
	pageSize := flag.Int("page-size", maxPageSize, "bounded evidence page size")
	scanTimeout := flag.Duration("scan-timeout", 10*time.Minute, "finite total scan timeout")
	flag.Parse()
	if (*root == "") == (*configPath == "") ||
		*pageSize < 1 ||
		*pageSize > maxPageSize ||
		*scanTimeout < time.Second ||
		*scanTimeout > time.Hour ||
		flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "inventory enumeration failed: invalid arguments")
		os.Exit(2)
	}

	ctx, cancel := context.WithTimeout(context.Background(), *scanTimeout)
	defer cancel()
	var namespace distribution.Namespace
	var backend *backendEvidence
	var err error
	if *root != "" {
		if *expectedVersion != "" || *expectedConfigSHA256 != "" {
			fmt.Fprintln(os.Stderr, "inventory enumeration failed: invalid arguments")
			os.Exit(2)
		}
		driver := filesystem.New(filesystem.DriverParameters{
			RootDirectory: *root,
			MaxThreads:    25,
		})
		namespace, err = namespaceFromDriver(ctx, driver)
	} else {
		namespace, backend, err = s3Namespace(
			ctx,
			*configPath,
			*expectedVersion,
			*expectedConfigSHA256,
		)
	}
	if err != nil {
		if errors.Is(err, errS3ConfigRefused) {
			fmt.Fprintln(os.Stderr, "inventory enumeration failed: s3 configuration refused")
		} else {
			fmt.Fprintln(os.Stderr, "inventory enumeration failed: storage unavailable")
		}
		os.Exit(1)
	}
	if err := run(ctx, namespace, *pageSize, backend); err != nil {
		fmt.Fprintln(os.Stderr, "inventory enumeration failed: bounded scan unavailable")
		os.Exit(1)
	}
}

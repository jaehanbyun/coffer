package driver

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"syscall"
	"time"
)

const (
	InvocationSchema = "coffer.raw-oci-invocation/v1"
	CredentialSchema = "coffer.raw-oci-credential/v1"
	ReadinessSchema  = "coffer.upstream-readiness/v1"
	TargetClass      = "disposable-stage6-pilot"

	maxInvocationBytes = int64(64 << 10)
	maxCredentialBytes = int64(64 << 10)
	maxReadinessBytes  = int64(1 << 20)
	maxCABytes         = int64(1 << 20)
)

var (
	sha256Pattern   = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	revisionPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)
	versionPattern  = regexp.MustCompile(`^v[0-9]+\.[0-9]+\.[0-9]+$`)
)

type invocationDocument struct {
	BaseURL          string `json:"base_url"`
	CAFile           string `json:"ca_file"`
	ChunkBytes       int64  `json:"chunk_bytes"`
	CredentialFile   string `json:"credential_file"`
	LengthBytes      int64  `json:"length_bytes"`
	ManifestFile     string `json:"manifest_file"`
	ManifestMedia    string `json:"manifest_media_type"`
	MaxAttempts      int    `json:"max_attempts"`
	OffsetBytes      int64  `json:"offset_bytes"`
	Operation        string `json:"operation"`
	OutputFile       string `json:"output_file"`
	ReadinessFile    string `json:"readiness_file"`
	ReadinessSHA256  string `json:"readiness_sha256"`
	Reference        string `json:"reference"`
	Repository       string `json:"repository"`
	Schema           string `json:"schema"`
	Seed             string `json:"seed"`
	SizeBytes        int64  `json:"size_bytes"`
	SourceRepository string `json:"source_repository"`
	TargetClass      string `json:"target_class"`
	TimeoutSeconds   int64  `json:"timeout_seconds"`
}

type credentialDocument struct {
	Password string `json:"password"`
	Schema   string `json:"schema"`
	Username string `json:"username"`
}

type distributionReadiness struct {
	Baseline              string   `json:"baseline"`
	LatestStable          string   `json:"latest_stable"`
	PublishedAt           *string  `json:"published_at"`
	Reasons               []string `json:"reasons"`
	Revision              string   `json:"revision"`
	Status                string   `json:"status"`
	URL                   *string  `json:"url"`
	VerifiedReleaseCommit bool     `json:"verified_release_commit"`
}

type cephReadiness struct {
	Baseline            string   `json:"baseline"`
	FixInLatestStable   bool     `json:"fix_in_latest_stable"`
	FixMergeRevision    string   `json:"fix_merge_revision"`
	FixMergedToTentacle bool     `json:"fix_merged_to_tentacle"`
	FixPullRequest      int      `json:"fix_pull_request"`
	LatestStable        string   `json:"latest_stable"`
	Reasons             []string `json:"reasons"`
	Revision            string   `json:"revision"`
	Status              string   `json:"status"`
}

type readinessDocument struct {
	Ceph         cephReadiness         `json:"ceph"`
	Distribution distributionReadiness `json:"distribution"`
	Schema       string                `json:"schema"`
	Status       string                `json:"status"`
}

type loadedInvocation struct {
	chunkBytes       int64
	client           *Client
	content          *Content
	lengthBytes      int64
	manifest         []byte
	manifestDigest   string
	manifestMedia    string
	offsetBytes      int64
	operation        string
	outputFile       string
	reference        string
	repository       string
	sourceRepository string
	timeout          time.Duration
}

func zero(payload []byte) {
	for index := range payload {
		payload[index] = 0
	}
}

func readOwnerOnly(path string, maximum int64) ([]byte, error) {
	if !filepath.IsAbs(path) || maximum < 1 {
		return nil, newFailure(FailureProtocol)
	}
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, newFailure(FailureProtocol)
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() ||
		info.Mode().Perm() != 0o600 || info.Size() <= 0 ||
		info.Size() > maximum {
		return nil, newFailure(FailureProtocol)
	}
	if runtime.GOOS != "windows" {
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || int(stat.Uid) != os.Geteuid() || stat.Nlink != 1 {
			return nil, newFailure(FailureProtocol)
		}
	}
	payload, err := io.ReadAll(io.LimitReader(file, maximum+1))
	if err != nil || len(payload) == 0 || int64(len(payload)) > maximum ||
		bytes.IndexByte(payload, 0) >= 0 {
		zero(payload)
		return nil, newFailure(FailureProtocol)
	}
	return payload, nil
}

func decodeExact(payload []byte, destination any) error {
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return newFailure(FailureProtocol)
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return newFailure(FailureProtocol)
	}
	return nil
}

func validateAbsoluteDistinct(paths ...string) error {
	seen := make(map[string]bool, len(paths))
	for _, path := range paths {
		if !filepath.IsAbs(path) {
			return newFailure(FailureProtocol)
		}
		cleaned := filepath.Clean(path)
		if seen[cleaned] {
			return newFailure(FailureProtocol)
		}
		seen[cleaned] = true
	}
	return nil
}

func versionParts(value string) ([3]int, error) {
	var parts [3]int
	count, err := fmt.Sscanf(
		value,
		"v%d.%d.%d",
		&parts[0],
		&parts[1],
		&parts[2],
	)
	if err != nil || count != 3 || !versionPattern.MatchString(value) {
		return parts, newFailure(FailureProtocol)
	}
	return parts, nil
}

func versionGreater(value string, baseline string) bool {
	current, currentErr := versionParts(value)
	previous, previousErr := versionParts(baseline)
	if currentErr != nil || previousErr != nil {
		return false
	}
	for index := range current {
		if current[index] != previous[index] {
			return current[index] > previous[index]
		}
	}
	return false
}

func validateReadiness(payload []byte, expectedDigest string) error {
	actual := sha256.Sum256(payload)
	if !sha256Pattern.MatchString(expectedDigest) ||
		expectedDigest != "sha256:"+hex.EncodeToString(actual[:]) {
		return newFailure(FailureProtocol)
	}
	var document readinessDocument
	if err := decodeExact(payload, &document); err != nil {
		return err
	}
	if document.Schema != ReadinessSchema ||
		document.Status != "candidate-qualified" ||
		document.Distribution.Status != "candidate-qualified" ||
		document.Ceph.Status != "candidate-qualified" ||
		!document.Distribution.VerifiedReleaseCommit ||
		!document.Ceph.FixMergedToTentacle ||
		!document.Ceph.FixInLatestStable ||
		document.Distribution.Reasons == nil ||
		document.Ceph.Reasons == nil ||
		len(document.Distribution.Reasons) != 0 ||
		len(document.Ceph.Reasons) != 0 ||
		document.Distribution.Baseline != "v3.1.1" ||
		document.Ceph.Baseline != "v20.2.2" ||
		document.Ceph.FixPullRequest != 69277 ||
		document.Ceph.FixMergeRevision !=
			"c6fc9801f55e24152f0e934b2ddc3e5cda33d63e" ||
		!versionGreater(
			document.Distribution.LatestStable,
			document.Distribution.Baseline,
		) ||
		!versionGreater(
			document.Ceph.LatestStable,
			document.Ceph.Baseline,
		) ||
		document.Ceph.LatestStable[:6] != "v20.2." ||
		!revisionPattern.MatchString(document.Distribution.Revision) ||
		!revisionPattern.MatchString(document.Ceph.Revision) ||
		!revisionPattern.MatchString(document.Ceph.FixMergeRevision) ||
		document.Distribution.PublishedAt == nil ||
		*document.Distribution.PublishedAt == "" ||
		document.Distribution.URL == nil ||
		*document.Distribution.URL == "" {
		return newFailure(FailureProtocol)
	}
	return nil
}

func loadCertPool(payload []byte) (*x509.CertPool, error) {
	roots := x509.NewCertPool()
	remaining := bytes.TrimSpace(payload)
	count := 0
	for len(remaining) > 0 {
		if !bytes.HasPrefix(remaining, []byte("-----BEGIN CERTIFICATE-----")) {
			return nil, newFailure(FailureProtocol)
		}
		block, rest := pem.Decode(remaining)
		if block == nil || block.Type != "CERTIFICATE" ||
			len(block.Headers) != 0 {
			return nil, newFailure(FailureProtocol)
		}
		certificate, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			return nil, newFailure(FailureProtocol)
		}
		roots.AddCert(certificate)
		count++
		remaining = bytes.TrimSpace(rest)
	}
	if count == 0 {
		return nil, newFailure(FailureProtocol)
	}
	return roots, nil
}

func isManifestOperation(operation string) bool {
	return operation == "manifest-publish" ||
		operation == "manifest-head" ||
		operation == "manifest-get"
}

func validateInvocationOperation(invocation invocationDocument) error {
	if invocation.Schema != InvocationSchema ||
		invocation.TargetClass != TargetClass ||
		invocation.MaxAttempts < 1 || invocation.MaxAttempts > 8 ||
		invocation.TimeoutSeconds < 1 || invocation.TimeoutSeconds > 3*60*60 {
		return newFailure(FailureProtocol)
	}
	if isManifestOperation(invocation.Operation) {
		if invocation.ManifestFile == "" ||
			(invocation.ManifestMedia != OCIImageManifest &&
				invocation.ManifestMedia != OCIImageIndex) ||
			(!tagPattern.MatchString(invocation.Reference) &&
				!sha256Pattern.MatchString(invocation.Reference)) ||
			invocation.Seed != "" || invocation.SizeBytes != 0 ||
			invocation.ChunkBytes != 0 || invocation.OffsetBytes != 0 ||
			invocation.LengthBytes != 0 ||
			invocation.SourceRepository != "" {
			return newFailure(FailureProtocol)
		}
		return nil
	}
	if invocation.ManifestFile != "" || invocation.ManifestMedia != "" ||
		invocation.Reference != "" ||
		len(invocation.Seed) == 0 || len(invocation.Seed) > 256 ||
		hasControl(invocation.Seed) ||
		invocation.SizeBytes < 0 || invocation.SizeBytes > MaxBlobBytes {
		return newFailure(FailureProtocol)
	}
	switch invocation.Operation {
	case "blob-monolithic":
		if invocation.ChunkBytes != 0 || invocation.OffsetBytes != 0 ||
			invocation.LengthBytes != 0 ||
			invocation.SourceRepository != "" {
			return newFailure(FailureProtocol)
		}
	case "blob-resumable":
		if invocation.ChunkBytes < 1 ||
			invocation.ChunkBytes > MaxChunkBytes ||
			invocation.OffsetBytes != 0 || invocation.LengthBytes != 0 ||
			invocation.SourceRepository != "" {
			return newFailure(FailureProtocol)
		}
	case "blob-head":
		if invocation.ChunkBytes != 0 || invocation.OffsetBytes != 0 ||
			invocation.LengthBytes != 0 ||
			invocation.SourceRepository != "" {
			return newFailure(FailureProtocol)
		}
	case "blob-read-full":
		if invocation.ChunkBytes != 0 || invocation.OffsetBytes != 0 ||
			invocation.LengthBytes != invocation.SizeBytes ||
			invocation.SourceRepository != "" {
			return newFailure(FailureProtocol)
		}
	case "blob-read-range":
		if invocation.ChunkBytes != 0 || invocation.OffsetBytes < 0 ||
			invocation.LengthBytes < 1 ||
			invocation.OffsetBytes > invocation.SizeBytes ||
			invocation.LengthBytes >
				invocation.SizeBytes-invocation.OffsetBytes ||
			invocation.SourceRepository != "" {
			return newFailure(FailureProtocol)
		}
	case "blob-cross-mount":
		if invocation.ChunkBytes != 0 || invocation.OffsetBytes != 0 ||
			invocation.LengthBytes != 0 ||
			invocation.SourceRepository == "" {
			return newFailure(FailureProtocol)
		}
	default:
		return newFailure(FailureProtocol)
	}
	return nil
}

func loadInvocation(path string) (*loadedInvocation, error) {
	invocationPayload, err := readOwnerOnly(path, maxInvocationBytes)
	if err != nil {
		return nil, err
	}
	defer zero(invocationPayload)
	var invocation invocationDocument
	if err := decodeExact(invocationPayload, &invocation); err != nil {
		return nil, err
	}
	if err := validateInvocationOperation(invocation); err != nil {
		return nil, newFailure(FailureProtocol)
	}
	if _, err := repositoryScope(invocation.Repository); err != nil {
		return nil, err
	}
	if invocation.SourceRepository != "" {
		if _, err := repositoryProject(invocation.SourceRepository); err != nil {
			return nil, err
		}
	}
	paths := []string{
		path,
		invocation.CAFile,
		invocation.CredentialFile,
		invocation.ReadinessFile,
		invocation.OutputFile,
	}
	if invocation.ManifestFile != "" {
		paths = append(paths, invocation.ManifestFile)
	}
	if err := validateAbsoluteDistinct(paths...); err != nil {
		return nil, err
	}
	if err := validateOutputDestination(invocation.OutputFile); err != nil {
		return nil, err
	}

	readinessPayload, err := readOwnerOnly(
		invocation.ReadinessFile,
		maxReadinessBytes,
	)
	if err != nil {
		return nil, err
	}
	defer zero(readinessPayload)
	if err := validateReadiness(
		readinessPayload,
		invocation.ReadinessSHA256,
	); err != nil {
		return nil, err
	}

	caPayload, err := readOwnerOnly(invocation.CAFile, maxCABytes)
	if err != nil {
		return nil, err
	}
	defer zero(caPayload)
	roots, err := loadCertPool(caPayload)
	if err != nil {
		return nil, err
	}

	credentialPayload, err := readOwnerOnly(
		invocation.CredentialFile,
		maxCredentialBytes,
	)
	if err != nil {
		return nil, err
	}
	defer zero(credentialPayload)
	var credential credentialDocument
	if err := decodeExact(credentialPayload, &credential); err != nil {
		return nil, err
	}
	if credential.Schema != CredentialSchema || credential.Username == "" ||
		credential.Password == "" || hasControl(credential.Username) ||
		hasControl(credential.Password) {
		return nil, newFailure(FailureAuthentication)
	}
	var content *Content
	var manifest []byte
	var manifestDigest string
	if isManifestOperation(invocation.Operation) {
		manifestPayload, readErr := readOwnerOnly(
			invocation.ManifestFile,
			MaxManifestBytes,
		)
		if readErr != nil {
			return nil, readErr
		}
		defer zero(manifestPayload)
		manifestDigest, err = validateManifest(
			invocation.Reference,
			invocation.ManifestMedia,
			manifestPayload,
		)
		if err != nil {
			return nil, err
		}
		manifest = append([]byte(nil), manifestPayload...)
	} else {
		content, err = NewContent(
			[]byte(invocation.Seed),
			invocation.SizeBytes,
		)
		if err != nil {
			return nil, err
		}
	}
	client, err := NewClient(Config{
		BaseURL: invocation.BaseURL,
		CredentialProvider: func(context.Context) (string, string, error) {
			return credential.Username, credential.Password, nil
		},
		MaxAttempts:    invocation.MaxAttempts,
		RequestTimeout: time.Duration(invocation.TimeoutSeconds) * time.Second,
		RootCAs:        roots,
	})
	if err != nil {
		return nil, err
	}
	return &loadedInvocation{
		chunkBytes:       invocation.ChunkBytes,
		client:           client,
		content:          content,
		lengthBytes:      invocation.LengthBytes,
		manifest:         manifest,
		manifestDigest:   manifestDigest,
		manifestMedia:    invocation.ManifestMedia,
		offsetBytes:      invocation.OffsetBytes,
		operation:        invocation.Operation,
		outputFile:       invocation.OutputFile,
		reference:        invocation.Reference,
		repository:       invocation.Repository,
		sourceRepository: invocation.SourceRepository,
		timeout:          time.Duration(invocation.TimeoutSeconds) * time.Second,
	}, nil
}

func ExecuteInvocation(ctx context.Context, path string) error {
	loaded, err := loadInvocation(path)
	if err != nil {
		return err
	}
	defer loaded.client.CloseIdleConnections()
	defer zero(loaded.manifest)
	runContext, cancel := context.WithTimeout(ctx, loaded.timeout)
	defer cancel()
	switch loaded.operation {
	case "blob-monolithic":
		err = loaded.client.UploadMonolithic(
			runContext,
			loaded.repository,
			loaded.content,
		)
	case "blob-resumable":
		err = loaded.client.UploadChunked(
			runContext,
			loaded.repository,
			loaded.content,
			loaded.chunkBytes,
		)
	case "blob-head":
		err = loaded.client.HeadBlob(
			runContext,
			loaded.repository,
			loaded.content,
		)
	case "blob-read-full":
		err = loaded.client.ReadBlob(
			runContext,
			loaded.repository,
			loaded.content,
			0,
			loaded.content.Size(),
		)
	case "blob-read-range":
		err = loaded.client.ReadBlob(
			runContext,
			loaded.repository,
			loaded.content,
			loaded.offsetBytes,
			loaded.lengthBytes,
		)
	case "blob-cross-mount":
		_, err = loaded.client.MountBlob(
			runContext,
			loaded.repository,
			loaded.sourceRepository,
			loaded.content,
		)
	case "manifest-publish":
		_, err = loaded.client.PublishManifest(
			runContext,
			loaded.repository,
			loaded.reference,
			loaded.manifestMedia,
			loaded.manifest,
		)
	case "manifest-head":
		err = loaded.client.HeadManifest(
			runContext,
			loaded.repository,
			loaded.reference,
			loaded.manifestMedia,
			loaded.manifestDigest,
			int64(len(loaded.manifest)),
		)
	case "manifest-get":
		err = loaded.client.GetManifest(
			runContext,
			loaded.repository,
			loaded.reference,
			loaded.manifestMedia,
			loaded.manifest,
		)
	default:
		err = newFailure(FailureProtocol)
	}
	outputErr := WriteCanonical(
		loaded.outputFile,
		loaded.client.Recorder().Snapshot(),
	)
	if err != nil {
		return err
	}
	return outputErr
}

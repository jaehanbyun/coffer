package control

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"syscall"
	"time"

	rawdriver "github.com/jaehanbyun/coffer/poc/load-soak/driver"
)

const (
	InvocationSchema = "coffer.control-load-invocation/v1"
	CredentialSchema = "coffer.control-load-credential/v1"
	ExecutionSchema  = "coffer.control-load-execution/v1"
	TargetClass      = "disposable-stage6-pilot"

	maxInvocationBytes = int64(128 << 10)
	maxCredentialBytes = int64(64 << 10)
	maxReadinessBytes  = int64(1 << 20)
	maxCABytes         = int64(1 << 20)
	maxExecutableBytes = int64(256 << 20)
)

type manifestSource struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}

type invocationDocument struct {
	CAFile           string           `json:"ca_file"`
	ContractSHA256   string           `json:"contract_sha256"`
	ControlBase      string           `json:"control_base"`
	CredentialFile   string           `json:"credential_file"`
	ExecutableSHA256 string           `json:"executable_sha256"`
	ExpectedQuota    int              `json:"expected_quota"`
	ExpectedSuccess  int              `json:"expected_success"`
	IdentityBase     string           `json:"identity_base"`
	ManifestSources  []manifestSource `json:"manifest_sources"`
	MaxConcurrency   int              `json:"max_concurrency"`
	OutputFile       string           `json:"output_file"`
	ReadinessFile    string           `json:"readiness_file"`
	ReadinessSHA256  string           `json:"readiness_sha256"`
	RegistryBase     string           `json:"registry_base"`
	Repository       string           `json:"repository"`
	Schema           string           `json:"schema"`
	Service          string           `json:"service"`
	TargetClass      string           `json:"target_class"`
	TimeoutSeconds   int64            `json:"timeout_seconds"`
}

type credentialDocument struct {
	ApplicationCredentialID     string `json:"application_credential_id"`
	ApplicationCredentialSecret string `json:"application_credential_secret"`
	Schema                      string `json:"schema"`
}

type Execution struct {
	ContractSHA256   string   `json:"contract_sha256"`
	ExecutableSHA256 string   `json:"executable_sha256"`
	ManifestSHA256   string   `json:"manifest_set_sha256"`
	ReadinessSHA256  string   `json:"readiness_sha256"`
	Schema           string   `json:"schema"`
	Snapshot         Snapshot `json:"snapshot"`
}

type loadedInvocation struct {
	client            *Client
	contractSHA256    string
	credential        *credentialDocument
	executableSHA256  string
	expectedQuota     int
	expectedSuccess   int
	manifestSetSHA256 string
	manifests         [][]byte
	outputFile        string
	readinessSHA256   string
	timeout           time.Duration
}

func zero(payload []byte) {
	for index := range payload {
		payload[index] = 0
	}
}

func decodeExact(payload []byte, destination any) error {
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return fail(FailureProtocol)
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return fail(FailureProtocol)
	}
	return nil
}

func validateInvocation(document invocationDocument) error {
	if document.Schema != InvocationSchema ||
		document.TargetClass != TargetClass ||
		!digestPattern.MatchString(document.ContractSHA256) ||
		!digestPattern.MatchString(document.ExecutableSHA256) ||
		document.TimeoutSeconds < 1 ||
		document.TimeoutSeconds > 10*60 ||
		document.MaxConcurrency < 2 ||
		document.MaxConcurrency > 64 ||
		len(document.ManifestSources) < 2 ||
		len(document.ManifestSources) > document.MaxConcurrency ||
		document.ExpectedSuccess < 1 ||
		document.ExpectedQuota < 1 ||
		document.ExpectedSuccess+document.ExpectedQuota !=
			len(document.ManifestSources) {
		return fail(FailureProtocol)
	}
	for _, source := range document.ManifestSources {
		if source.Path == "" || !digestPattern.MatchString(source.SHA256) {
			return fail(FailureProtocol)
		}
	}
	return nil
}

func executableDigest() (string, error) {
	path, err := os.Executable()
	if err != nil {
		return "", fail(FailureProtocol)
	}
	path, err = filepath.EvalSymlinks(path)
	if err != nil || !filepath.IsAbs(path) {
		return "", fail(FailureProtocol)
	}
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return "", fail(FailureProtocol)
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() ||
		info.Mode().Perm()&0o111 == 0 ||
		info.Size() < 1 || info.Size() > maxExecutableBytes {
		return "", fail(FailureProtocol)
	}
	digest := sha256.New()
	written, err := io.Copy(digest, io.LimitReader(file, maxExecutableBytes+1))
	if err != nil || written != info.Size() {
		return "", fail(FailureProtocol)
	}
	return "sha256:" + hex.EncodeToString(digest.Sum(nil)), nil
}

func manifestSetDigest(digests []string) (string, error) {
	payload, err := json.Marshal(digests)
	if err != nil {
		return "", fail(FailureProtocol)
	}
	sum := sha256.Sum256(payload)
	return "sha256:" + hex.EncodeToString(sum[:]), nil
}

func translateShared(err error) error {
	if err == nil {
		return nil
	}
	return fail(FailureProtocol)
}

func loadInvocation(path string) (*loadedInvocation, error) {
	invocationPayload, err := rawdriver.ReadOwnerOnly(
		path,
		maxInvocationBytes,
	)
	if err != nil {
		return nil, translateShared(err)
	}
	defer zero(invocationPayload)
	var document invocationDocument
	if err := decodeExact(invocationPayload, &document); err != nil {
		return nil, err
	}
	if err := validateInvocation(document); err != nil {
		return nil, err
	}

	paths := []string{
		path,
		document.CAFile,
		document.CredentialFile,
		document.ReadinessFile,
		document.OutputFile,
	}
	for _, source := range document.ManifestSources {
		paths = append(paths, source.Path)
	}
	if err := rawdriver.ValidateAbsoluteDistinct(paths...); err != nil {
		return nil, translateShared(err)
	}
	if err := rawdriver.ValidateOutputDestination(
		document.OutputFile,
	); err != nil {
		return nil, translateShared(err)
	}
	if _, err := os.Lstat(document.OutputFile); err == nil ||
		!os.IsNotExist(err) {
		return nil, fail(FailureProtocol)
	}

	actualExecutableSHA256, err := executableDigest()
	if err != nil || actualExecutableSHA256 != document.ExecutableSHA256 {
		return nil, fail(FailureProtocol)
	}

	readinessPayload, err := rawdriver.ReadOwnerOnly(
		document.ReadinessFile,
		maxReadinessBytes,
	)
	if err != nil {
		return nil, translateShared(err)
	}
	defer zero(readinessPayload)
	if err := rawdriver.ValidateQualifiedReadiness(
		readinessPayload,
		document.ReadinessSHA256,
	); err != nil {
		return nil, translateShared(err)
	}

	caPayload, err := rawdriver.ReadOwnerOnly(document.CAFile, maxCABytes)
	if err != nil {
		return nil, translateShared(err)
	}
	defer zero(caPayload)
	roots, err := rawdriver.LoadCertPool(caPayload)
	if err != nil {
		return nil, translateShared(err)
	}

	credentialPayload, err := rawdriver.ReadOwnerOnly(
		document.CredentialFile,
		maxCredentialBytes,
	)
	if err != nil {
		return nil, translateShared(err)
	}
	defer zero(credentialPayload)
	credential := &credentialDocument{}
	if err := decodeExact(credentialPayload, credential); err != nil {
		return nil, err
	}
	if credential.Schema != CredentialSchema ||
		credential.ApplicationCredentialID == "" ||
		credential.ApplicationCredentialSecret == "" {
		return nil, fail(FailureAuthentication)
	}

	manifests := make([][]byte, 0, len(document.ManifestSources))
	manifestDigests := make([]string, 0, len(document.ManifestSources))
	cleanupManifests := true
	defer func() {
		if cleanupManifests {
			for _, manifest := range manifests {
				zero(manifest)
			}
		}
	}()
	seenDigests := make(map[string]bool, len(document.ManifestSources))
	for _, source := range document.ManifestSources {
		payload, readErr := rawdriver.ReadOwnerOnly(
			source.Path,
			maxManifestBytes,
		)
		if readErr != nil {
			return nil, translateShared(readErr)
		}
		sum := sha256.Sum256(payload)
		actual := "sha256:" + hex.EncodeToString(sum[:])
		if actual != source.SHA256 || !json.Valid(payload) ||
			seenDigests[actual] {
			zero(payload)
			return nil, fail(FailureProtocol)
		}
		seenDigests[actual] = true
		manifestDigests = append(manifestDigests, actual)
		manifests = append(manifests, payload)
	}
	setDigest, err := manifestSetDigest(manifestDigests)
	if err != nil {
		return nil, err
	}

	client, err := New(Config{
		ControlBase:    document.ControlBase,
		IdentityBase:   document.IdentityBase,
		RegistryBase:   document.RegistryBase,
		Repository:     document.Repository,
		Service:        document.Service,
		Roots:          roots,
		Timeout:        time.Duration(document.TimeoutSeconds) * time.Second,
		MaxConcurrency: document.MaxConcurrency,
		CredentialProvider: func(context.Context) (Credential, error) {
			return Credential{
				ID:     credential.ApplicationCredentialID,
				Secret: credential.ApplicationCredentialSecret,
			}, nil
		},
	})
	if err != nil {
		return nil, err
	}
	cleanupManifests = false
	return &loadedInvocation{
		client:            client,
		contractSHA256:    document.ContractSHA256,
		credential:        credential,
		executableSHA256:  document.ExecutableSHA256,
		expectedQuota:     document.ExpectedQuota,
		expectedSuccess:   document.ExpectedSuccess,
		manifestSetSHA256: setDigest,
		manifests:         manifests,
		outputFile:        document.OutputFile,
		readinessSHA256:   document.ReadinessSHA256,
		timeout:           time.Duration(document.TimeoutSeconds) * time.Second,
	}, nil
}

func (loaded *loadedInvocation) close() {
	loaded.client.Close()
	loaded.credential.ApplicationCredentialID = ""
	loaded.credential.ApplicationCredentialSecret = ""
	for _, manifest := range loaded.manifests {
		zero(manifest)
	}
}

// ExecuteInvocation runs one fully bound Stage 6 control/token/quota slice.
func ExecuteInvocation(ctx context.Context, path string) error {
	loaded, err := loadInvocation(path)
	if err != nil {
		return err
	}
	defer loaded.close()
	runContext, cancel := context.WithTimeout(ctx, loaded.timeout)
	defer cancel()

	keystoneToken, err := loaded.client.KeystoneToken(runContext)
	if err != nil {
		return err
	}
	if err := loaded.client.ProbeControl(runContext, keystoneToken); err != nil {
		return err
	}
	keystoneToken = ""
	registryToken, err := loaded.client.RegistryToken(runContext)
	if err != nil {
		return err
	}
	if err := loaded.client.QuotaContention(
		runContext,
		registryToken,
		loaded.manifests,
		loaded.expectedSuccess,
		loaded.expectedQuota,
	); err != nil {
		return err
	}
	registryToken = ""
	return translateShared(rawdriver.WriteCanonicalValue(
		loaded.outputFile,
		Execution{
			ContractSHA256:   loaded.contractSHA256,
			ExecutableSHA256: loaded.executableSHA256,
			ManifestSHA256:   loaded.manifestSetSHA256,
			ReadinessSHA256:  loaded.readinessSHA256,
			Schema:           ExecutionSchema,
			Snapshot:         loaded.client.Snapshot(),
		},
	))
}

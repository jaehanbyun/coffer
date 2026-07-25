package main

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"runtime"
	"runtime/debug"
	"sort"
	"strings"
	"syscall"

	distribution "github.com/distribution/distribution/v3"
	"github.com/distribution/distribution/v3/configuration"
	"github.com/distribution/distribution/v3/registry/storage"
	"github.com/distribution/distribution/v3/registry/storage/driver/factory"
	_ "github.com/distribution/distribution/v3/registry/storage/driver/s3-aws"
)

const maximumConfigurationBytes = 1024 * 1024

var errS3ConfigRefused = errors.New("s3 configuration refused")

var ambientCredentialVariables = map[string]struct{}{
	"AWS_ACCESS_KEY_ID":                      {},
	"AWS_CONFIG_FILE":                        {},
	"AWS_CONTAINER_AUTHORIZATION_TOKEN":      {},
	"AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE": {},
	"AWS_CONTAINER_CREDENTIALS_FULL_URI":     {},
	"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": {},
	"AWS_DEFAULT_PROFILE":                    {},
	"AWS_EC2_METADATA_DISABLED":              {},
	"AWS_PROFILE":                            {},
	"AWS_ROLE_ARN":                           {},
	"AWS_ROLE_SESSION_NAME":                  {},
	"AWS_SECRET_ACCESS_KEY":                  {},
	"AWS_SESSION_TOKEN":                      {},
	"AWS_SHARED_CREDENTIALS_FILE":            {},
	"AWS_WEB_IDENTITY_TOKEN_FILE":            {},
}

type s3Configuration struct {
	ConfigSHA256   string
	StorageType    string
	BucketSHA256   string
	RootSHA256     string
	EndpointSHA256 string
	Parameters     map[string]any
}

type backendEvidence struct {
	Type                 string `json:"type"`
	DistributionRevision string `json:"distribution_revision"`
	ModuleGraphSHA256    string `json:"module_graph_sha256"`
	HelperSHA256         string `json:"helper_sha256"`
	ConfigSHA256         string `json:"config_sha256"`
	StorageType          string `json:"storage_type"`
	EndpointSHA256       string `json:"endpoint_sha256"`
	BucketSHA256         string `json:"bucket_sha256"`
	RootSHA256           string `json:"root_sha256"`
}

func refuseS3Config() error {
	return errS3ConfigRefused
}

func rejectAmbientConfiguration(environment []string) error {
	for _, entry := range environment {
		name, _, _ := strings.Cut(entry, "=")
		if strings.HasPrefix(name, "REGISTRY_") {
			return refuseS3Config()
		}
		if _, forbidden := ambientCredentialVariables[name]; forbidden {
			return refuseS3Config()
		}
	}
	return nil
}

func ownerOnlyConfiguration(path string) ([]byte, error) {
	file, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, refuseS3Config()
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil ||
		!info.Mode().IsRegular() ||
		info.Mode().Perm() != 0o600 ||
		info.Size() <= 0 ||
		info.Size() > maximumConfigurationBytes {
		return nil, refuseS3Config()
	}
	if runtime.GOOS != "windows" {
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || int(stat.Uid) != os.Geteuid() || stat.Nlink != 1 {
			return nil, refuseS3Config()
		}
	}
	content, err := io.ReadAll(io.LimitReader(file, maximumConfigurationBytes+1))
	if err != nil || len(content) == 0 || len(content) > maximumConfigurationBytes {
		return nil, refuseS3Config()
	}
	return content, nil
}

func exactString(parameters map[string]any, key string) (string, error) {
	value, ok := parameters[key]
	if !ok {
		return "", refuseS3Config()
	}
	result, ok := value.(string)
	if !ok || strings.TrimSpace(result) == "" {
		return "", refuseS3Config()
	}
	return result, nil
}

func exactBool(parameters map[string]any, key string, fallback bool) (bool, error) {
	value, ok := parameters[key]
	if !ok {
		return fallback, nil
	}
	result, ok := value.(bool)
	if !ok {
		return false, refuseS3Config()
	}
	return result, nil
}

func hashNonSecret(value string) string {
	digest := sha256.Sum256([]byte(value))
	return fmt.Sprintf("sha256:%x", digest)
}

func moduleGraphSHA256() (string, error) {
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return "", refuseS3Config()
	}
	lines := []string{
		"go=" + info.GoVersion,
		"main=" + info.Main.Path + "@" + info.Main.Version + "=" + info.Main.Sum,
	}
	distributionFound := false
	for _, dependency := range info.Deps {
		module := dependency
		if dependency.Replace != nil {
			module = dependency.Replace
		}
		lines = append(
			lines,
			module.Path+"@"+module.Version+"="+module.Sum,
		)
		if module.Path == "github.com/distribution/distribution/v3" &&
			module.Version == distributionVersion &&
			module.Sum != "" {
			distributionFound = true
		}
	}
	if !distributionFound {
		return "", refuseS3Config()
	}
	sort.Strings(lines)
	return hashNonSecret(strings.Join(lines, "\n") + "\n"), nil
}

func helperSHA256() (string, error) {
	path, err := os.Executable()
	if err != nil {
		return "", refuseS3Config()
	}
	file, err := os.Open(path)
	if err != nil {
		return "", refuseS3Config()
	}
	defer file.Close()
	checksum := sha256.New()
	if _, err := io.Copy(checksum, file); err != nil {
		return "", refuseS3Config()
	}
	return fmt.Sprintf("sha256:%x", checksum.Sum(nil)), nil
}

func (config s3Configuration) backendEvidence() (*backendEvidence, error) {
	moduleDigest, err := moduleGraphSHA256()
	if err != nil {
		return nil, err
	}
	helperDigest, err := helperSHA256()
	if err != nil {
		return nil, err
	}
	return &backendEvidence{
		Type:                 "s3",
		DistributionRevision: distributionRevision,
		ModuleGraphSHA256:    moduleDigest,
		HelperSHA256:         helperDigest,
		ConfigSHA256:         config.ConfigSHA256,
		StorageType:          config.StorageType,
		EndpointSHA256:       config.EndpointSHA256,
		BucketSHA256:         config.BucketSHA256,
		RootSHA256:           config.RootSHA256,
	}, nil
}

func parseS3Configuration(
	path string,
	expectedVersion string,
	expectedDigest string,
	environment []string,
) (s3Configuration, error) {
	var result s3Configuration
	if expectedVersion != distributionVersion ||
		len(expectedDigest) != len("sha256:")+sha256.Size*2 ||
		!strings.HasPrefix(expectedDigest, "sha256:") {
		return result, refuseS3Config()
	}
	if err := rejectAmbientConfiguration(environment); err != nil {
		return result, err
	}
	content, err := ownerOnlyConfiguration(path)
	if err != nil {
		return result, err
	}
	actualDigest := hashNonSecret(string(content))
	if actualDigest != expectedDigest {
		return result, refuseS3Config()
	}

	config, err := configuration.Parse(strings.NewReader(string(content)))
	if err != nil {
		return result, refuseS3Config()
	}
	driverTypes := make([]string, 0, 1)
	for name := range config.Storage {
		switch name {
		case "maintenance", "cache", "delete", "redirect", "tag":
		default:
			driverTypes = append(driverTypes, name)
		}
	}
	if len(driverTypes) != 1 ||
		(driverTypes[0] != "s3" && driverTypes[0] != "s3aws") ||
		len(config.Middleware) != 0 ||
		config.Proxy.RemoteURL != "" ||
		config.Proxy.Username != "" ||
		config.Proxy.Password != "" ||
		config.Proxy.Exec != nil ||
		config.Proxy.TTL != nil ||
		config.Proxy.CacheWriteTimeout != nil {
		return result, refuseS3Config()
	}

	parameters := map[string]any(config.Storage[driverTypes[0]])
	accessKey, err := exactString(parameters, "accesskey")
	if err != nil {
		return result, err
	}
	secretKey, err := exactString(parameters, "secretkey")
	if err != nil {
		return result, err
	}
	if accessKey == secretKey {
		return result, refuseS3Config()
	}
	region, err := exactString(parameters, "region")
	if err != nil {
		return result, err
	}
	bucket, err := exactString(parameters, "bucket")
	if err != nil {
		return result, err
	}
	rootDirectory, err := exactString(parameters, "rootdirectory")
	if err != nil || rootDirectory == "/" {
		return result, refuseS3Config()
	}
	endpoint, err := exactString(parameters, "regionendpoint")
	if err != nil {
		return result, err
	}
	parsedEndpoint, err := url.Parse(endpoint)
	if err != nil ||
		parsedEndpoint.Scheme != "https" ||
		parsedEndpoint.Host == "" ||
		parsedEndpoint.User != nil ||
		parsedEndpoint.RawQuery != "" ||
		parsedEndpoint.Fragment != "" {
		return result, refuseS3Config()
	}
	secure, err := exactBool(parameters, "secure", true)
	if err != nil || !secure {
		return result, refuseS3Config()
	}
	skipVerify, err := exactBool(parameters, "skipverify", false)
	if err != nil || skipVerify {
		return result, refuseS3Config()
	}
	v4Auth, err := exactBool(parameters, "v4auth", true)
	if err != nil || !v4Auth {
		return result, refuseS3Config()
	}
	forcePathStyle, err := exactBool(parameters, "forcepathstyle", false)
	if err != nil || !forcePathStyle {
		return result, refuseS3Config()
	}
	if logLevel, present := parameters["loglevel"]; present {
		if logLevel != false && logLevel != "off" {
			return result, refuseS3Config()
		}
	}

	result = s3Configuration{
		ConfigSHA256:   actualDigest,
		StorageType:    driverTypes[0],
		BucketSHA256:   hashNonSecret(bucket),
		RootSHA256:     hashNonSecret(rootDirectory),
		EndpointSHA256: hashNonSecret(parsedEndpoint.String()),
		Parameters:     parameters,
	}
	_ = region
	return result, nil
}

func s3Namespace(
	ctx context.Context,
	path string,
	expectedVersion string,
	expectedDigest string,
) (distribution.Namespace, *backendEvidence, error) {
	config, err := parseS3Configuration(
		path,
		expectedVersion,
		expectedDigest,
		os.Environ(),
	)
	if err != nil {
		return nil, nil, err
	}
	provenance, err := config.backendEvidence()
	if err != nil {
		return nil, nil, err
	}
	driver, err := factory.Create(ctx, config.StorageType, config.Parameters)
	if err != nil {
		return nil, nil, fmt.Errorf("construct exact S3 driver: %w", err)
	}
	namespace, err := storage.NewRegistry(ctx, driver)
	if err != nil {
		return nil, nil, fmt.Errorf("construct exact S3 namespace: %w", err)
	}
	return namespace, provenance, nil
}

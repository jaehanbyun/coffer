package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const validS3Configuration = `version: 0.1
storage:
  delete:
    enabled: false
  redirect:
    disable: true
  s3:
    accesskey: COFFERFIXTUREACCESS
    secretkey: coffer-fixture-secret-material
    region: us-east-1
    regionendpoint: https://rgw.example.invalid:8443
    bucket: coffer-cutover-fixture
    rootdirectory: /distribution
    secure: true
    skipverify: false
    v4auth: true
    forcepathstyle: true
http:
  addr: :5000
`

func writeOwnerConfig(t *testing.T, content string) (string, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yml")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return path, hashNonSecret(content)
}

func parseFixture(t *testing.T, content string) (s3Configuration, error) {
	t.Helper()
	path, digest := writeOwnerConfig(t, content)
	return parseS3Configuration(path, distributionVersion, digest, nil)
}

func TestParseExactS3Configuration(t *testing.T) {
	config, err := parseFixture(t, validS3Configuration)
	if err != nil {
		t.Fatal(err)
	}

	if config.StorageType != "s3" {
		t.Fatalf("unexpected storage type %q", config.StorageType)
	}
	if config.ConfigSHA256 != hashNonSecret(validS3Configuration) {
		t.Fatal("configuration digest mismatch")
	}
	for _, digest := range []string{
		config.BucketSHA256,
		config.RootSHA256,
		config.EndpointSHA256,
	} {
		if !strings.HasPrefix(digest, "sha256:") || len(digest) != 71 {
			t.Fatalf("invalid non-secret digest %q", digest)
		}
	}
	encoded := fmt.Sprintf(
		"%s %s %s %s %s",
		config.ConfigSHA256,
		config.StorageType,
		config.BucketSHA256,
		config.RootSHA256,
		config.EndpointSHA256,
	)
	for _, secret := range []string{
		"COFFERFIXTUREACCESS",
		"coffer-fixture-secret-material",
		"coffer-cutover-fixture",
		"rgw.example.invalid",
	} {
		if strings.Contains(encoded, secret) {
			t.Fatalf("non-secret evidence contains %q", secret)
		}
	}
}

func TestConfigurationVersionAndDigestMustBeExact(t *testing.T) {
	path, digest := writeOwnerConfig(t, validS3Configuration)
	for _, test := range []struct {
		version string
		digest  string
	}{
		{"v3.1.0", digest},
		{distributionVersion, "sha256:" + strings.Repeat("0", 64)},
		{"", digest},
		{distributionVersion, ""},
	} {
		_, err := parseS3Configuration(path, test.version, test.digest, nil)
		if !errors.Is(err, errS3ConfigRefused) {
			t.Fatalf("unexpected result for %#v: %v", test, err)
		}
	}
}

func TestConfigurationMustBeOwnerOnlyRegularSingleLink(t *testing.T) {
	path, digest := writeOwnerConfig(t, validS3Configuration)
	if err := os.Chmod(path, 0o640); err != nil {
		t.Fatal(err)
	}
	if _, err := parseS3Configuration(
		path,
		distributionVersion,
		digest,
		nil,
	); !errors.Is(err, errS3ConfigRefused) {
		t.Fatalf("unsafe mode was accepted: %v", err)
	}

	path, digest = writeOwnerConfig(t, validS3Configuration)
	link := path + ".hardlink"
	if err := os.Link(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := parseS3Configuration(
		path,
		distributionVersion,
		digest,
		nil,
	); !errors.Is(err, errS3ConfigRefused) {
		t.Fatalf("hard-linked config was accepted: %v", err)
	}

	path, digest = writeOwnerConfig(t, validS3Configuration)
	symlink := path + ".symlink"
	if err := os.Symlink(path, symlink); err != nil {
		t.Fatal(err)
	}
	if _, err := parseS3Configuration(
		symlink,
		distributionVersion,
		digest,
		nil,
	); !errors.Is(err, errS3ConfigRefused) {
		t.Fatalf("symlink config was accepted: %v", err)
	}
}

func TestAmbientRegistryAndCloudCredentialConfigurationIsRefused(t *testing.T) {
	path, digest := writeOwnerConfig(t, validS3Configuration)
	for _, environment := range [][]string{
		{"REGISTRY_STORAGE_S3_BUCKET=other"},
		{"REGISTRY_LOG_LEVEL=debug"},
		{"AWS_ACCESS_KEY_ID=ambient"},
		{"AWS_PROFILE=ambient"},
		{"AWS_WEB_IDENTITY_TOKEN_FILE=/tmp/token"},
	} {
		_, err := parseS3Configuration(
			path,
			distributionVersion,
			digest,
			environment,
		)
		if !errors.Is(err, errS3ConfigRefused) {
			t.Fatalf("ambient environment was accepted: %v", environment)
		}
	}
}

func TestOnlyS3WithoutMiddlewareOrProxyIsAccepted(t *testing.T) {
	replacements := []string{
		strings.Replace(
			validS3Configuration,
			"  s3:\n",
			"  filesystem:\n    rootdirectory: /registry\n  s3:\n",
			1,
		),
		strings.Replace(
			validS3Configuration,
			"http:\n",
			"middleware:\n  storage:\n    - name: redirect\n      options: {}\nhttp:\n",
			1,
		),
		validS3Configuration + "proxy:\n  remoteurl: https://upstream.invalid\n",
	}
	for _, content := range replacements {
		if _, err := parseFixture(t, content); !errors.Is(err, errS3ConfigRefused) {
			t.Fatalf("unsupported registry configuration was accepted: %v", err)
		}
	}
}

func TestS3TLSAndExplicitCredentialBoundary(t *testing.T) {
	replacements := map[string]string{
		"missing access key": strings.Replace(
			validS3Configuration,
			"    accesskey: COFFERFIXTUREACCESS\n",
			"",
			1,
		),
		"identical credentials": strings.Replace(
			validS3Configuration,
			"    secretkey: coffer-fixture-secret-material\n",
			"    secretkey: COFFERFIXTUREACCESS\n",
			1,
		),
		"insecure endpoint": strings.Replace(
			validS3Configuration,
			"https://rgw.example.invalid:8443",
			"http://rgw.example.invalid:8080",
			1,
		),
		"skip verify": strings.Replace(
			validS3Configuration,
			"    skipverify: false",
			"    skipverify: true",
			1,
		),
		"insecure flag": strings.Replace(
			validS3Configuration,
			"    secure: true",
			"    secure: false",
			1,
		),
		"no path style": strings.Replace(
			validS3Configuration,
			"    forcepathstyle: true",
			"    forcepathstyle: false",
			1,
		),
		"root bucket": strings.Replace(
			validS3Configuration,
			"    rootdirectory: /distribution",
			"    rootdirectory: /",
			1,
		),
		"debug logging": strings.Replace(
			validS3Configuration,
			"    forcepathstyle: true",
			"    forcepathstyle: true\n    loglevel: debugwithhttpbody",
			1,
		),
	}
	for label, content := range replacements {
		if _, err := parseFixture(t, content); !errors.Is(err, errS3ConfigRefused) {
			t.Fatalf("%s was accepted: %v", label, err)
		}
	}
}

func TestConfigurationFailuresUseOneFixedError(t *testing.T) {
	path, _ := writeOwnerConfig(t, "not: [valid")
	_, err := parseS3Configuration(
		path,
		distributionVersion,
		"sha256:"+strings.Repeat("0", 64),
		nil,
	)
	if !errors.Is(err, errS3ConfigRefused) {
		t.Fatalf("invalid config did not use fixed refusal: %v", err)
	}
	if err.Error() != "s3 configuration refused" {
		t.Fatalf("configuration failure exposed details: %q", err)
	}
}

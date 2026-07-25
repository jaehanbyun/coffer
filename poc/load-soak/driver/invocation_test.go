package driver

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

type invocationFixture struct {
	ca         string
	credential string
	directory  string
	invocation string
	output     string
	readiness  string
}

func stringPointer(value string) *string {
	return &value
}

func qualifiedReadiness() readinessDocument {
	return readinessDocument{
		Schema: ReadinessSchema,
		Status: "candidate-qualified",
		Distribution: distributionReadiness{
			Baseline:              "v3.1.1",
			LatestStable:          "v3.1.2",
			PublishedAt:           stringPointer("2026-07-25T00:00:00Z"),
			Reasons:               []string{},
			Revision:              strings.Repeat("d", 40),
			Status:                "candidate-qualified",
			URL:                   stringPointer("https://github.com/distribution/distribution/releases/tag/v3.1.2"),
			VerifiedReleaseCommit: true,
		},
		Ceph: cephReadiness{
			Baseline:            "v20.2.2",
			FixInLatestStable:   true,
			FixMergeRevision:    "c6fc9801f55e24152f0e934b2ddc3e5cda33d63e",
			FixMergedToTentacle: true,
			FixPullRequest:      69277,
			LatestStable:        "v20.2.3",
			Reasons:             []string{},
			Revision:            strings.Repeat("e", 40),
			Status:              "candidate-qualified",
		},
	}
}

func writeOwnerFile(t *testing.T, path string, payload []byte) {
	t.Helper()
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
}

func marshalDocument(t *testing.T, value any) []byte {
	t.Helper()
	payload, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	return append(payload, '\n')
}

func createInvocationFixture(
	t *testing.T,
	server *httptest.Server,
	readiness readinessDocument,
	mutate func(*invocationDocument),
) invocationFixture {
	t.Helper()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	result := invocationFixture{
		ca:         filepath.Join(directory, "ca.pem"),
		credential: filepath.Join(directory, "credential.json"),
		directory:  directory,
		invocation: filepath.Join(directory, "invocation.json"),
		output:     filepath.Join(directory, "result.json"),
		readiness:  filepath.Join(directory, "readiness.json"),
	}
	certificate := pem.EncodeToMemory(&pem.Block{
		Type:  "CERTIFICATE",
		Bytes: server.Certificate().Raw,
	})
	writeOwnerFile(t, result.ca, certificate)
	writeOwnerFile(t, result.credential, marshalDocument(t, credentialDocument{
		Password: testPassword,
		Schema:   CredentialSchema,
		Username: testUsername,
	}))
	readinessPayload := marshalDocument(t, readiness)
	writeOwnerFile(t, result.readiness, readinessPayload)
	readinessDigest := sha256.Sum256(readinessPayload)
	invocation := invocationDocument{
		BaseURL:         server.URL,
		CAFile:          result.ca,
		ChunkBytes:      0,
		CredentialFile:  result.credential,
		MaxAttempts:     4,
		Operation:       "blob-monolithic",
		OutputFile:      result.output,
		ReadinessFile:   result.readiness,
		ReadinessSHA256: "sha256:" + hex.EncodeToString(readinessDigest[:]),
		Repository:      testRepository,
		Schema:          InvocationSchema,
		Seed:            "cli-seed",
		SizeBytes:       1024,
		TargetClass:     TargetClass,
		TimeoutSeconds:  5,
	}
	if mutate != nil {
		mutate(&invocation)
	}
	writeOwnerFile(t, result.invocation, marshalDocument(t, invocation))
	return result
}

func rewriteInvocation(
	t *testing.T,
	path string,
	mutate func(*invocationDocument),
) {
	t.Helper()
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var document invocationDocument
	if err := json.Unmarshal(payload, &document); err != nil {
		t.Fatal(err)
	}
	mutate(&document)
	writeOwnerFile(t, path, marshalDocument(t, document))
}

func TestOwnerOnlyInvocationExecutesAndWritesCanonicalResult(t *testing.T) {
	expectedContent := mustContent(t, "cli-seed", 1024)
	expectedDigest, err := expectedContent.Digest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var server *httptest.Server
	var completed atomic.Int64
	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/auth/token" {
			serveToken(t, response, request)
			return
		}
		if request.Header.Get("Authorization") != "Bearer "+testToken {
			writeChallenge(response, server.URL)
			return
		}
		payload, readErr := io.ReadAll(request.Body)
		if readErr != nil {
			t.Error(readErr)
			response.WriteHeader(http.StatusInternalServerError)
			return
		}
		actual := sha256.Sum256(payload)
		if request.URL.Query().Get("digest") != expectedDigest ||
			"sha256:"+hex.EncodeToString(actual[:]) != expectedDigest {
			t.Error("invocation payload changed")
			response.WriteHeader(http.StatusBadRequest)
			return
		}
		completed.Add(1)
		response.Header().Set("Docker-Content-Digest", expectedDigest)
		response.WriteHeader(http.StatusCreated)
	})
	server = startTLSServer(t, handler)
	fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)

	if err := ExecuteInvocation(context.Background(), fixture.invocation); err != nil {
		t.Fatalf("invocation failed: %v", err)
	}
	if completed.Load() != 1 {
		t.Fatalf("operation count changed: %d", completed.Load())
	}
	payload, err := os.ReadFile(fixture.output)
	if err != nil {
		t.Fatal(err)
	}
	var snapshot Snapshot
	if err := json.Unmarshal(payload, &snapshot); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(fixture.output)
	if err != nil {
		t.Fatal(err)
	}
	if snapshot.Schema != ResultSchema || len(snapshot.Operations) != 1 ||
		snapshot.Operations[0].Result != string(ResultSuccess) ||
		info.Mode().Perm() != 0o600 || payload[len(payload)-1] != '\n' {
		t.Fatalf("canonical result changed: %#v mode=%o", snapshot, info.Mode().Perm())
	}
	for _, forbidden := range []string{
		testPassword,
		testToken,
		testRepository,
		"cli-seed",
		server.URL,
	} {
		if strings.Contains(string(payload), forbidden) {
			t.Fatalf("result retained forbidden input")
		}
	}
	entries, err := os.ReadDir(fixture.directory)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 5 {
		t.Fatalf("temporary residue changed: %d entries", len(entries))
	}
}

func TestReadinessAndOutputPreflightRunBeforeNetwork(t *testing.T) {
	for _, mode := range []string{"blocked", "hash", "unsafe-output"} {
		t.Run(mode, func(t *testing.T) {
			var requests atomic.Int64
			server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
				requests.Add(1)
			}))
			readiness := qualifiedReadiness()
			if mode == "blocked" {
				readiness.Status = "blocked"
			}
			fixture := createInvocationFixture(
				t,
				server,
				readiness,
				func(document *invocationDocument) {
					if mode == "hash" {
						document.ReadinessSHA256 = "sha256:" + strings.Repeat("0", 64)
					}
				},
			)
			if mode == "unsafe-output" {
				if err := os.Chmod(fixture.directory, 0o755); err != nil {
					t.Fatal(err)
				}
			}
			err := ExecuteInvocation(context.Background(), fixture.invocation)
			if failureKind(err) != FailureProtocol || requests.Load() != 0 {
				t.Fatalf(
					"preflight was not fail closed: kind=%s requests=%d",
					failureKind(err),
					requests.Load(),
				)
			}
			if _, statErr := os.Stat(fixture.output); !os.IsNotExist(statErr) {
				t.Fatalf("failed preflight wrote output: %v", statErr)
			}
		})
	}
}

func TestEveryInputMustBeOwnerOnlyRegularSingleLink(t *testing.T) {
	for _, target := range []string{"invocation", "ca", "credential", "readiness"} {
		t.Run(target, func(t *testing.T) {
			server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
				t.Fatal("unsafe input reached network")
			}))
			fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
			path := map[string]string{
				"invocation": fixture.invocation,
				"ca":         fixture.ca,
				"credential": fixture.credential,
				"readiness":  fixture.readiness,
			}[target]
			if err := os.Chmod(path, 0o640); err != nil {
				t.Fatal(err)
			}
			if err := ExecuteInvocation(context.Background(), fixture.invocation); failureKind(err) != FailureProtocol {
				t.Fatalf("unsafe %s input was accepted: %v", target, err)
			}
		})
	}

	t.Run("symlink", func(t *testing.T) {
		server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
			t.Fatal("symlink input reached network")
		}))
		fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
		link := filepath.Join(fixture.directory, "readiness-link.json")
		if err := os.Symlink(fixture.readiness, link); err != nil {
			t.Fatal(err)
		}
		var document invocationDocument
		payload, err := os.ReadFile(fixture.invocation)
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(payload, &document); err != nil {
			t.Fatal(err)
		}
		document.ReadinessFile = link
		writeOwnerFile(t, fixture.invocation, marshalDocument(t, document))
		if err := ExecuteInvocation(context.Background(), fixture.invocation); failureKind(err) != FailureProtocol {
			t.Fatalf("symlink input was accepted: %v", err)
		}
	})

	t.Run("hardlink", func(t *testing.T) {
		server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
			t.Fatal("hardlink input reached network")
		}))
		fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
		link := filepath.Join(fixture.directory, "credential-link.json")
		if err := os.Link(fixture.credential, link); err != nil {
			t.Fatal(err)
		}
		var document invocationDocument
		payload, err := os.ReadFile(fixture.invocation)
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(payload, &document); err != nil {
			t.Fatal(err)
		}
		document.CredentialFile = link
		writeOwnerFile(t, fixture.invocation, marshalDocument(t, document))
		if err := ExecuteInvocation(context.Background(), fixture.invocation); failureKind(err) != FailureProtocol {
			t.Fatalf("hardlink input was accepted: %v", err)
		}
	})
}

func TestReadinessContractCannotBeWeakened(t *testing.T) {
	tests := map[string]func(*readinessDocument){
		"distribution-status": func(value *readinessDocument) {
			value.Distribution.Status = "candidate-released"
		},
		"ceph-fix": func(value *readinessDocument) {
			value.Ceph.FixInLatestStable = false
		},
		"distribution-baseline": func(value *readinessDocument) {
			value.Distribution.LatestStable = value.Distribution.Baseline
		},
		"ceph-series": func(value *readinessDocument) {
			value.Ceph.LatestStable = "v21.1.0"
		},
		"reasons-null": func(value *readinessDocument) {
			value.Distribution.Reasons = nil
		},
		"revision": func(value *readinessDocument) {
			value.Ceph.Revision = "not-a-revision"
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			document := qualifiedReadiness()
			mutate(&document)
			payload := marshalDocument(t, document)
			checksum := sha256.Sum256(payload)
			err := validateReadiness(
				payload,
				"sha256:"+hex.EncodeToString(checksum[:]),
			)
			if failureKind(err) != FailureProtocol {
				t.Fatalf("weakened readiness was accepted: %v", err)
			}
		})
	}
}

func TestInvocationRejectsUnknownFieldsAndPathAliasing(t *testing.T) {
	server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Fatal("invalid invocation reached network")
	}))
	fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
	payload, err := os.ReadFile(fixture.invocation)
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]any
	if err := json.Unmarshal(payload, &document); err != nil {
		t.Fatal(err)
	}
	document["raw_token"] = "forbidden"
	writeOwnerFile(t, fixture.invocation, marshalDocument(t, document))
	if err := ExecuteInvocation(context.Background(), fixture.invocation); failureKind(err) != FailureProtocol {
		t.Fatalf("unknown invocation field was accepted: %v", err)
	}

	delete(document, "raw_token")
	document["output_file"] = fixture.credential
	writeOwnerFile(t, fixture.invocation, marshalDocument(t, document))
	if err := ExecuteInvocation(context.Background(), fixture.invocation); failureKind(err) != FailureProtocol {
		t.Fatalf("input/output alias was accepted: %v", err)
	}
}

func TestInvocationExposesManifestBlobRangeAndCrossMount(t *testing.T) {
	t.Run("manifest-get", func(t *testing.T) {
		payload := manifestPayload(t, OCIImageManifest)
		sum := sha256.Sum256(payload)
		digest := "sha256:" + hex.EncodeToString(sum[:])
		var server *httptest.Server
		handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
			if request.URL.Path == "/auth/token" {
				serveToken(t, response, request)
				return
			}
			if request.Header.Get("Authorization") != "Bearer "+testToken {
				writeChallenge(response, server.URL)
				return
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set("Content-Type", OCIImageManifest)
			response.Header().Set("Content-Length", fmt.Sprintf("%d", len(payload)))
			response.WriteHeader(http.StatusOK)
			_, _ = response.Write(payload)
		})
		server = startTLSServer(t, handler)
		fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
		manifestPath := filepath.Join(fixture.directory, "manifest.json")
		writeOwnerFile(t, manifestPath, payload)
		rewriteInvocation(t, fixture.invocation, func(document *invocationDocument) {
			document.Operation = "manifest-get"
			document.ManifestFile = manifestPath
			document.ManifestMedia = OCIImageManifest
			document.Reference = "load-test"
			document.Seed = ""
			document.SizeBytes = 0
		})

		if err := ExecuteInvocation(context.Background(), fixture.invocation); err != nil {
			t.Fatalf("manifest invocation failed: %v", err)
		}
		resultPayload, err := os.ReadFile(fixture.output)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(resultPayload), `"operation":"manifest-read"`) {
			t.Fatal("manifest invocation result changed")
		}
	})

	t.Run("blob-range", func(t *testing.T) {
		content := mustContent(t, "cli-seed", 1024)
		digest, err := content.Digest(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		reader, err := content.NewRangeReader(7, 17)
		if err != nil {
			t.Fatal(err)
		}
		expected, err := io.ReadAll(reader)
		if err != nil {
			t.Fatal(err)
		}
		var server *httptest.Server
		handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
			if request.URL.Path == "/auth/token" {
				serveToken(t, response, request)
				return
			}
			if request.Header.Get("Authorization") != "Bearer "+testToken {
				writeChallenge(response, server.URL)
				return
			}
			if request.Header.Get("Range") != "bytes=7-23" {
				t.Fatal("invocation range changed")
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set("Content-Length", "17")
			response.Header().Set("Content-Range", "bytes 7-23/1024")
			response.WriteHeader(http.StatusPartialContent)
			_, _ = response.Write(expected)
		})
		server = startTLSServer(t, handler)
		fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
		rewriteInvocation(t, fixture.invocation, func(document *invocationDocument) {
			document.Operation = "blob-read-range"
			document.OffsetBytes = 7
			document.LengthBytes = 17
		})

		if err := ExecuteInvocation(context.Background(), fixture.invocation); err != nil {
			t.Fatalf("blob-range invocation failed: %v", err)
		}
	})

	t.Run("cross-mount", func(t *testing.T) {
		content := mustContent(t, "cli-seed", 1024)
		digest, err := content.Digest(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		var server *httptest.Server
		handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
			if request.URL.Path == "/auth/token" {
				mountToken(t, response, request)
				return
			}
			if request.Header.Get("Authorization") != "Bearer "+testToken {
				mountChallenge(response, server.URL)
				return
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set(
				"Location",
				"/v2/"+mountDestination+"/blobs/"+digest,
			)
			response.WriteHeader(http.StatusCreated)
		})
		server = startTLSServer(t, handler)
		fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
		rewriteInvocation(t, fixture.invocation, func(document *invocationDocument) {
			document.Operation = "blob-cross-mount"
			document.Repository = mountDestination
			document.SourceRepository = mountSource
		})

		if err := ExecuteInvocation(context.Background(), fixture.invocation); err != nil {
			t.Fatalf("cross-mount invocation failed: %v", err)
		}
	})

	t.Run("artifact", func(t *testing.T) {
		payload := artifactPayload(t)
		index := referrersResponse(t, payload)
		var server *httptest.Server
		handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
			if request.URL.Path == "/auth/token" {
				serveToken(t, response, request)
				return
			}
			if request.Header.Get("Authorization") != "Bearer "+testToken {
				writeChallenge(response, server.URL)
				return
			}
			if request.Method == http.MethodPut {
				serveArtifactPublish(t, response, request, payload, "sbom")
				return
			}
			response.Header().Set("Content-Type", OCIImageIndex)
			response.Header().Set("OCI-Filters-Applied", "artifactType")
			_, _ = response.Write(index)
		})
		server = startTLSServer(t, handler)
		fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
		manifestPath := filepath.Join(fixture.directory, "artifact.json")
		writeOwnerFile(t, manifestPath, payload)
		rewriteInvocation(t, fixture.invocation, func(document *invocationDocument) {
			document.Operation = "artifact"
			document.ManifestFile = manifestPath
			document.ManifestMedia = OCIImageManifest
			document.Reference = "sbom"
			document.Seed = ""
			document.SizeBytes = 0
		})

		if err := ExecuteInvocation(context.Background(), fixture.invocation); err != nil {
			t.Fatalf("artifact invocation failed: %v", err)
		}
		resultPayload, err := os.ReadFile(fixture.output)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(resultPayload), `"operation":"artifact"`) {
			t.Fatal("artifact invocation result changed")
		}
	})

	t.Run("abandoned-upload", func(t *testing.T) {
		var server *httptest.Server
		var started atomic.Int64
		handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
			if request.URL.Path == "/auth/token" {
				serveToken(t, response, request)
				return
			}
			if request.Header.Get("Authorization") != "Bearer "+testToken {
				writeChallenge(response, server.URL)
				return
			}
			switch request.Method {
			case http.MethodPost:
				identity := started.Add(1)
				response.Header().Set(
					"Location",
					fmt.Sprintf(
						"/v2/%s/blobs/uploads/invocation-%d",
						testRepository,
						identity,
					),
				)
				response.Header().Set("Range", "0-0")
				response.WriteHeader(http.StatusAccepted)
			case http.MethodPatch:
				_, _ = io.Copy(io.Discard, request.Body)
				response.Header().Set("Location", request.URL.String())
				response.Header().Set("Range", "0-15")
				response.WriteHeader(http.StatusAccepted)
			case http.MethodDelete:
				response.WriteHeader(http.StatusNoContent)
			default:
				t.Fatalf("unexpected request: %s", request.Method)
			}
		})
		server = startTLSServer(t, handler)
		fixture := createInvocationFixture(t, server, qualifiedReadiness(), nil)
		rewriteInvocation(t, fixture.invocation, func(document *invocationDocument) {
			document.Operation = "abandoned-upload"
			document.ChunkBytes = 16
			document.LengthBytes = 16
		})

		if err := ExecuteInvocation(context.Background(), fixture.invocation); err != nil {
			t.Fatalf("abandoned-upload invocation failed: %v", err)
		}
	})
}

func TestInvocationOperationFieldsAreExact(t *testing.T) {
	base := invocationDocument{
		MaxAttempts:    4,
		Operation:      "blob-monolithic",
		Repository:     testRepository,
		Schema:         InvocationSchema,
		Seed:           "seed",
		SizeBytes:      32,
		TargetClass:    TargetClass,
		TimeoutSeconds: 30,
	}
	valid := []invocationDocument{
		base,
		func() invocationDocument {
			value := base
			value.Operation = "blob-resumable"
			value.ChunkBytes = 4
			return value
		}(),
		func() invocationDocument {
			value := base
			value.Operation = "blob-head"
			return value
		}(),
		func() invocationDocument {
			value := base
			value.Operation = "blob-read-full"
			value.LengthBytes = value.SizeBytes
			return value
		}(),
		func() invocationDocument {
			value := base
			value.Operation = "blob-read-range"
			value.OffsetBytes = 1
			value.LengthBytes = 8
			return value
		}(),
		func() invocationDocument {
			value := base
			value.Operation = "blob-cross-mount"
			value.SourceRepository = mountSource
			return value
		}(),
		func() invocationDocument {
			value := base
			value.Operation = "abandoned-upload"
			value.ChunkBytes = 4
			value.LengthBytes = 16
			return value
		}(),
	}
	for _, operation := range []string{
		"manifest-publish",
		"manifest-head",
		"manifest-get",
		"artifact",
	} {
		value := base
		value.Operation = operation
		value.ManifestFile = "/owner/manifest.json"
		value.ManifestMedia = OCIImageManifest
		value.Reference = "tag"
		value.Seed = ""
		value.SizeBytes = 0
		valid = append(valid, value)
	}
	for _, document := range valid {
		if err := validateInvocationOperation(document); err != nil {
			t.Fatalf("valid %s operation rejected: %v", document.Operation, err)
		}
	}
	for _, mutate := range []func(*invocationDocument){
		func(value *invocationDocument) { value.Operation = "unknown" },
		func(value *invocationDocument) { value.OffsetBytes = 1 },
		func(value *invocationDocument) { value.ManifestFile = "/mixed" },
		func(value *invocationDocument) { value.SourceRepository = mountSource },
	} {
		document := base
		mutate(&document)
		if err := validateInvocationOperation(document); failureKind(err) != FailureProtocol {
			t.Fatalf("invalid operation fields accepted: %#v", document)
		}
	}
}

package control

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type invocationFixture struct {
	ca         string
	credential string
	directory  string
	invocation string
	manifests  []string
	output     string
	readiness  string
}

func ownerFile(t *testing.T, path string, payload []byte) {
	t.Helper()
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
}

func documentBytes(t *testing.T, value any) []byte {
	t.Helper()
	payload, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	return append(payload, '\n')
}

func qualifiedReadinessDocument() map[string]any {
	return map[string]any{
		"ceph": map[string]any{
			"baseline":               "v20.2.2",
			"fix_in_latest_stable":   true,
			"fix_merge_revision":     "c6fc9801f55e24152f0e934b2ddc3e5cda33d63e",
			"fix_merged_to_tentacle": true,
			"fix_pull_request":       69277,
			"latest_stable":          "v20.2.3",
			"reasons":                []string{},
			"revision":               strings.Repeat("e", 40),
			"status":                 "candidate-qualified",
		},
		"distribution": map[string]any{
			"baseline":                "v3.1.1",
			"latest_stable":           "v3.1.2",
			"published_at":            "2026-07-25T00:00:00Z",
			"reasons":                 []string{},
			"revision":                strings.Repeat("d", 40),
			"status":                  "candidate-qualified",
			"url":                     "https://github.com/distribution/distribution/releases/tag/v3.1.2",
			"verified_release_commit": true,
		},
		"schema": "coffer.upstream-readiness/v1",
		"status": "candidate-qualified",
	}
}

func fileSHA256(payload []byte) string {
	sum := sha256.Sum256(payload)
	return "sha256:" + hex.EncodeToString(sum[:])
}

func invocationValue(t *testing.T, path string) invocationDocument {
	t.Helper()
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var document invocationDocument
	if err := json.Unmarshal(payload, &document); err != nil {
		t.Fatal(err)
	}
	return document
}

func rewriteInvocation(
	t *testing.T,
	path string,
	mutate func(*invocationDocument),
) {
	t.Helper()
	document := invocationValue(t, path)
	mutate(&document)
	ownerFile(t, path, documentBytes(t, document))
}

func createControlInvocationFixture(
	t *testing.T,
	serverURL string,
	certificate []byte,
) invocationFixture {
	t.Helper()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	fixture := invocationFixture{
		ca:         filepath.Join(directory, "ca.pem"),
		credential: filepath.Join(directory, "credential.json"),
		directory:  directory,
		invocation: filepath.Join(directory, "invocation.json"),
		output:     filepath.Join(directory, "result.json"),
		readiness:  filepath.Join(directory, "readiness.json"),
	}
	ownerFile(t, fixture.ca, pem.EncodeToMemory(&pem.Block{
		Type: "CERTIFICATE", Bytes: certificate,
	}))
	ownerFile(t, fixture.credential, documentBytes(t, credentialDocument{
		ApplicationCredentialID:     "fixture-application-credential-id",
		ApplicationCredentialSecret: "fixture-secret",
		Schema:                      CredentialSchema,
	}))
	readinessPayload := documentBytes(t, qualifiedReadinessDocument())
	ownerFile(t, fixture.readiness, readinessPayload)

	sources := make([]manifestSource, 0, 4)
	for index, payload := range manifests() {
		path := filepath.Join(
			directory,
			"manifest-"+string(rune('0'+index))+".json",
		)
		ownerFile(t, path, payload)
		fixture.manifests = append(fixture.manifests, path)
		sources = append(sources, manifestSource{
			Path: path, SHA256: fileSHA256(payload),
		})
	}
	binarySHA256, err := executableDigest()
	if err != nil {
		t.Fatalf("executable digest: %v", err)
	}
	invocation := invocationDocument{
		CAFile:           fixture.ca,
		ContractSHA256:   "sha256:" + strings.Repeat("c", 64),
		ControlBase:      serverURL,
		CredentialFile:   fixture.credential,
		ExecutableSHA256: binarySHA256,
		ExpectedQuota:    2,
		ExpectedSuccess:  2,
		IdentityBase:     serverURL,
		ManifestSources:  sources,
		MaxConcurrency:   8,
		OutputFile:       fixture.output,
		ReadinessFile:    fixture.readiness,
		ReadinessSHA256:  fileSHA256(readinessPayload),
		RegistryBase:     serverURL,
		Repository:       "p/123e4567-e89b-12d3-a456-426614174000/load",
		Schema:           InvocationSchema,
		Service:          "registry.stage6.example",
		TargetClass:      TargetClass,
		TimeoutSeconds:   5,
	}
	ownerFile(t, fixture.invocation, documentBytes(t, invocation))
	return fixture
}

func TestOwnerOnlyControlInvocationWritesCanonicalSecretSafeResult(
	t *testing.T,
) {
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	fixture := createControlInvocationFixture(
		t,
		server.URL,
		server.Certificate().Raw,
	)

	if err := ExecuteInvocation(
		context.Background(),
		fixture.invocation,
	); err != nil {
		t.Fatalf("execute invocation: %v", err)
	}
	payload, err := os.ReadFile(fixture.output)
	if err != nil {
		t.Fatal(err)
	}
	var execution Execution
	if err := json.Unmarshal(payload, &execution); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(fixture.output)
	if err != nil {
		t.Fatal(err)
	}
	if execution.Schema != ExecutionSchema ||
		execution.ContractSHA256 != "sha256:"+strings.Repeat("c", 64) ||
		execution.ExecutableSHA256 == "" ||
		execution.ManifestSHA256 == "" ||
		execution.ReadinessSHA256 == "" ||
		execution.Snapshot.Schema != "coffer.control-load-driver/v1" ||
		len(execution.Snapshot.Results) != 3 ||
		info.Mode().Perm() != 0o600 ||
		payload[len(payload)-1] != '\n' {
		t.Fatalf(
			"execution result changed: %#v mode=%o",
			execution,
			info.Mode().Perm(),
		)
	}
	expected := []Result{
		{Operation: "control", Result: "success", Count: 2},
		{Operation: "quota-contention", Result: "success", Count: 1},
		{Operation: "token", Result: "success", Count: 1},
	}
	for index := range expected {
		if execution.Snapshot.Results[index] != expected[index] {
			t.Fatalf("unexpected aggregate: %#v", execution.Snapshot.Results)
		}
	}
	for _, forbidden := range []string{
		"fixture-secret",
		"token-value",
		"123e4567",
		server.URL,
		string(manifests()[0]),
		fixture.directory,
	} {
		if strings.Contains(string(payload), forbidden) {
			t.Fatalf("result retained forbidden input")
		}
	}
	entries, err := os.ReadDir(fixture.directory)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 9 {
		t.Fatalf("temporary residue changed: %d entries", len(entries))
	}
}

func TestControlInvocationPreflightFailsBeforeNetwork(t *testing.T) {
	for _, name := range []string{
		"blocked-readiness",
		"readiness-hash",
		"binary-hash",
		"credential-unknown",
		"manifest-hash",
		"duplicate-manifest",
		"existing-output",
		"unsafe-output",
	} {
		t.Run(name, func(t *testing.T) {
			state := &testServerState{}
			server := testServer(t, state)
			defer server.Close()
			fixture := createControlInvocationFixture(
				t,
				server.URL,
				server.Certificate().Raw,
			)
			switch name {
			case "blocked-readiness":
				document := qualifiedReadinessDocument()
				document["status"] = "blocked"
				payload := documentBytes(t, document)
				ownerFile(t, fixture.readiness, payload)
				rewriteInvocation(
					t,
					fixture.invocation,
					func(value *invocationDocument) {
						value.ReadinessSHA256 = fileSHA256(payload)
					},
				)
			case "readiness-hash":
				rewriteInvocation(
					t,
					fixture.invocation,
					func(value *invocationDocument) {
						value.ReadinessSHA256 =
							"sha256:" + strings.Repeat("0", 64)
					},
				)
			case "binary-hash":
				rewriteInvocation(
					t,
					fixture.invocation,
					func(value *invocationDocument) {
						value.ExecutableSHA256 =
							"sha256:" + strings.Repeat("0", 64)
					},
				)
			case "credential-unknown":
				ownerFile(
					t,
					fixture.credential,
					[]byte(
						`{"application_credential_id":"fixture-application-credential-id",`+
							`"application_credential_secret":"fixture-secret",`+
							`"raw_token":"forbidden",`+
							`"schema":"coffer.control-load-credential/v1"}`+
							"\n",
					),
				)
			case "manifest-hash":
				rewriteInvocation(
					t,
					fixture.invocation,
					func(value *invocationDocument) {
						value.ManifestSources[0].SHA256 =
							"sha256:" + strings.Repeat("0", 64)
					},
				)
			case "duplicate-manifest":
				duplicate := filepath.Join(
					fixture.directory,
					"duplicate.json",
				)
				payload, err := os.ReadFile(fixture.manifests[0])
				if err != nil {
					t.Fatal(err)
				}
				ownerFile(t, duplicate, payload)
				rewriteInvocation(
					t,
					fixture.invocation,
					func(value *invocationDocument) {
						value.ManifestSources[1] = manifestSource{
							Path: duplicate, SHA256: fileSHA256(payload),
						}
					},
				)
			case "existing-output":
				ownerFile(t, fixture.output, []byte("{}\n"))
			case "unsafe-output":
				if err := os.Chmod(fixture.directory, 0o755); err != nil {
					t.Fatal(err)
				}
			}
			err := ExecuteInvocation(context.Background(), fixture.invocation)
			state.mu.Lock()
			requests := state.requests
			state.mu.Unlock()
			if FailureOf(err) != FailureProtocol || requests != 0 {
				t.Fatalf(
					"preflight escaped: failure=%s requests=%d",
					FailureOf(err),
					requests,
				)
			}
			if name == "existing-output" {
				payload, readErr := os.ReadFile(fixture.output)
				if readErr != nil || string(payload) != "{}\n" {
					t.Fatalf("preflight changed existing output")
				}
			} else if _, statErr := os.Stat(
				fixture.output,
			); !os.IsNotExist(statErr) {
				t.Fatalf("preflight wrote output: %v", statErr)
			}
		})
	}
}

func TestControlInvocationInputsAreOwnerOnlyAndDistinct(t *testing.T) {
	for _, target := range []string{
		"invocation",
		"ca",
		"credential",
		"readiness",
		"manifest",
	} {
		t.Run(target, func(t *testing.T) {
			state := &testServerState{}
			server := testServer(t, state)
			defer server.Close()
			fixture := createControlInvocationFixture(
				t,
				server.URL,
				server.Certificate().Raw,
			)
			path := map[string]string{
				"invocation": fixture.invocation,
				"ca":         fixture.ca,
				"credential": fixture.credential,
				"readiness":  fixture.readiness,
				"manifest":   fixture.manifests[0],
			}[target]
			if err := os.Chmod(path, 0o640); err != nil {
				t.Fatal(err)
			}
			if err := ExecuteInvocation(
				context.Background(),
				fixture.invocation,
			); FailureOf(err) != FailureProtocol {
				t.Fatalf("unsafe %s accepted: %v", target, err)
			}
		})
	}

	t.Run("symlink", func(t *testing.T) {
		state := &testServerState{}
		server := testServer(t, state)
		defer server.Close()
		fixture := createControlInvocationFixture(
			t,
			server.URL,
			server.Certificate().Raw,
		)
		link := filepath.Join(fixture.directory, "manifest-link.json")
		if err := os.Symlink(fixture.manifests[0], link); err != nil {
			t.Fatal(err)
		}
		rewriteInvocation(
			t,
			fixture.invocation,
			func(value *invocationDocument) {
				value.ManifestSources[0].Path = link
			},
		)
		if err := ExecuteInvocation(
			context.Background(),
			fixture.invocation,
		); FailureOf(err) != FailureProtocol {
			t.Fatalf("symlink accepted: %v", err)
		}
	})

	t.Run("hardlink", func(t *testing.T) {
		state := &testServerState{}
		server := testServer(t, state)
		defer server.Close()
		fixture := createControlInvocationFixture(
			t,
			server.URL,
			server.Certificate().Raw,
		)
		link := filepath.Join(fixture.directory, "credential-link.json")
		if err := os.Link(fixture.credential, link); err != nil {
			t.Fatal(err)
		}
		rewriteInvocation(
			t,
			fixture.invocation,
			func(value *invocationDocument) {
				value.CredentialFile = link
			},
		)
		if err := ExecuteInvocation(
			context.Background(),
			fixture.invocation,
		); FailureOf(err) != FailureProtocol {
			t.Fatalf("hardlink accepted: %v", err)
		}
	})

	t.Run("alias", func(t *testing.T) {
		state := &testServerState{}
		server := testServer(t, state)
		defer server.Close()
		fixture := createControlInvocationFixture(
			t,
			server.URL,
			server.Certificate().Raw,
		)
		rewriteInvocation(
			t,
			fixture.invocation,
			func(value *invocationDocument) {
				value.OutputFile = value.CredentialFile
			},
		)
		if err := ExecuteInvocation(
			context.Background(),
			fixture.invocation,
		); FailureOf(err) != FailureProtocol {
			t.Fatalf("path alias accepted: %v", err)
		}
	})

	t.Run("output-hardlink", func(t *testing.T) {
		state := &testServerState{}
		server := testServer(t, state)
		defer server.Close()
		fixture := createControlInvocationFixture(
			t,
			server.URL,
			server.Certificate().Raw,
		)
		ownerFile(t, fixture.output, []byte("{}\n"))
		link := filepath.Join(fixture.directory, "result-link.json")
		if err := os.Link(fixture.output, link); err != nil {
			t.Fatal(err)
		}
		if err := ExecuteInvocation(
			context.Background(),
			fixture.invocation,
		); FailureOf(err) != FailureProtocol {
			t.Fatalf("hard-linked output accepted: %v", err)
		}
	})
}

func TestControlInvocationRejectsUnknownFields(t *testing.T) {
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	fixture := createControlInvocationFixture(
		t,
		server.URL,
		server.Certificate().Raw,
	)
	payload, err := os.ReadFile(fixture.invocation)
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]any
	if err := json.Unmarshal(payload, &document); err != nil {
		t.Fatal(err)
	}
	document["raw_token"] = "forbidden"
	ownerFile(t, fixture.invocation, documentBytes(t, document))
	if err := ExecuteInvocation(
		context.Background(),
		fixture.invocation,
	); FailureOf(err) != FailureProtocol {
		t.Fatalf("unknown field accepted: %v", err)
	}
}

func TestControlInvocationFailureCleansAndWritesNoResult(t *testing.T) {
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	fixture := createControlInvocationFixture(
		t,
		server.URL,
		server.Certificate().Raw,
	)
	rewriteInvocation(
		t,
		fixture.invocation,
		func(value *invocationDocument) {
			value.ExpectedSuccess = 1
			value.ExpectedQuota = 3
		},
	)
	err := ExecuteInvocation(context.Background(), fixture.invocation)
	if FailureOf(err) != FailureQuota {
		t.Fatalf("quota mismatch changed: %v", err)
	}
	state.mu.Lock()
	deletes := state.deletes
	state.mu.Unlock()
	if deletes != 2 {
		t.Fatalf("failure skipped cleanup: %d", deletes)
	}
	if _, statErr := os.Stat(fixture.output); !os.IsNotExist(statErr) {
		t.Fatalf("failure wrote output: %v", statErr)
	}
}

func TestControlInvocationCancellationWritesNoResult(t *testing.T) {
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	fixture := createControlInvocationFixture(
		t,
		server.URL,
		server.Certificate().Raw,
	)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := ExecuteInvocation(ctx, fixture.invocation)
	if FailureOf(err) != FailureCancellation {
		t.Fatalf("cancellation changed: %v", err)
	}
	if _, statErr := os.Stat(fixture.output); !os.IsNotExist(statErr) {
		t.Fatalf("cancellation wrote output: %v", statErr)
	}
}

func TestQuotaContentionRefusesDuplicateManifestPayload(t *testing.T) {
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	client := clientFor(t, server)
	duplicate := manifests()[0]
	err := client.QuotaContention(
		context.Background(),
		"registry-token-value",
		[][]byte{duplicate, duplicate},
		1,
		1,
	)
	if FailureOf(err) != FailureProtocol {
		t.Fatalf("duplicate manifests accepted: %v", err)
	}
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.deletes != 0 || state.tokenObserved {
		t.Fatalf("duplicate manifests reached registry: %#v", state)
	}
}

package control

import (
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

type testServerState struct {
	mu             sync.Mutex
	deletes        int
	requests       int
	secretObserved bool
	tokenObserved  bool
	cleanupFailure bool
}

func testServer(t *testing.T, state *testServerState) *httptest.Server {
	t.Helper()
	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		state.mu.Lock()
		state.requests++
		state.mu.Unlock()
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Errorf("read body: %v", err)
			return
		}
		switch {
		case request.Method == http.MethodPost &&
			request.URL.Path == "/v3/auth/tokens":
			state.mu.Lock()
			state.secretObserved = strings.Contains(string(body), "fixture-secret")
			state.mu.Unlock()
			response.Header().Set("X-Subject-Token", "keystone-token-value")
			response.Header().Set("Content-Type", "application/json")
			response.WriteHeader(http.StatusCreated)
			_, _ = response.Write([]byte(`{"token":{"expires_at":"future"}}`))
		case request.Method == http.MethodGet &&
			request.URL.Path == "/v1/repositories":
			if request.Header.Get("X-Auth-Token") != "keystone-token-value" {
				response.WriteHeader(http.StatusUnauthorized)
				return
			}
			response.Header().Set("Content-Type", "application/json")
			_, _ = response.Write([]byte(`{"repositories":[]}`))
		case request.Method == http.MethodGet &&
			request.URL.Path == "/auth/token":
			if request.URL.Query().Get("service") != "registry.stage6.example" ||
				!strings.HasPrefix(
					request.URL.Query().Get("scope"),
					"repository:p/123e4567-e89b-12d3-a456-426614174000/load:",
				) {
				response.WriteHeader(http.StatusBadRequest)
				return
			}
			state.mu.Lock()
			state.secretObserved = state.secretObserved &&
				strings.Contains(request.Header.Get("Authorization"), "Basic ")
			state.mu.Unlock()
			response.Header().Set("Content-Type", "application/json")
			_, _ = response.Write([]byte(`{"token":"registry-token-value"}`))
		case request.Method == http.MethodPut &&
			strings.Contains(request.URL.Path, "/manifests/coffer-quota-"):
			if request.Header.Get("Authorization") !=
				"Bearer registry-token-value" {
				response.WriteHeader(http.StatusUnauthorized)
				return
			}
			state.mu.Lock()
			state.tokenObserved = true
			state.mu.Unlock()
			index := request.URL.Path[len(request.URL.Path)-1]
			if index == '2' || index == '3' {
				response.WriteHeader(http.StatusTooManyRequests)
				return
			}
			sum := sha256.Sum256(body)
			response.Header().Set(
				"Docker-Content-Digest",
				"sha256:"+hex.EncodeToString(sum[:]),
			)
			response.WriteHeader(http.StatusCreated)
		case request.Method == http.MethodDelete &&
			strings.Contains(request.URL.Path, "/manifests/sha256:"):
			state.mu.Lock()
			state.deletes++
			failure := state.cleanupFailure
			state.mu.Unlock()
			if failure {
				response.WriteHeader(http.StatusInternalServerError)
			} else {
				response.WriteHeader(http.StatusAccepted)
			}
		default:
			response.WriteHeader(http.StatusNotFound)
		}
	})
	return httptest.NewTLSServer(handler)
}

func clientFor(t *testing.T, server *httptest.Server) *Client {
	t.Helper()
	roots := x509.NewCertPool()
	roots.AddCert(server.Certificate())
	client, err := New(Config{
		ControlBase:    server.URL,
		IdentityBase:   server.URL,
		RegistryBase:   server.URL,
		Repository:     "p/123e4567-e89b-12d3-a456-426614174000/load",
		Service:        "registry.stage6.example",
		Roots:          roots,
		Timeout:        2 * time.Second,
		MaxConcurrency: 8,
		CredentialProvider: func(context.Context) (Credential, error) {
			return Credential{
				ID:     "fixture-application-credential-id",
				Secret: "fixture-secret",
			}, nil
		},
	})
	if err != nil {
		t.Fatalf("new client: %v", err)
	}
	t.Cleanup(client.Close)
	return client
}

func manifests() [][]byte {
	result := make([][]byte, 4)
	for index := range result {
		result[index] = []byte(
			`{"schemaVersion":2,"annotations":{"coffer.index":"` +
				string(rune('0'+index)) + `"}}`,
		)
	}
	return result
}

func TestControlTokenAndQuotaContentionOverVerifiedTLS(t *testing.T) {
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	client := clientFor(t, server)

	keystoneToken, err := client.KeystoneToken(context.Background())
	if err != nil {
		t.Fatalf("Keystone token: %v", err)
	}
	if err := client.ProbeControl(context.Background(), keystoneToken); err != nil {
		t.Fatalf("control probe: %v", err)
	}
	registryToken, err := client.RegistryToken(context.Background())
	if err != nil {
		t.Fatalf("registry token: %v", err)
	}
	if err := client.QuotaContention(
		context.Background(), registryToken, manifests(), 2, 2,
	); err != nil {
		t.Fatalf("quota contention: %v", err)
	}

	state.mu.Lock()
	if !state.secretObserved || !state.tokenObserved || state.deletes != 2 {
		t.Fatalf("unexpected server state: %#v", state)
	}
	state.mu.Unlock()
	snapshot := client.Snapshot()
	payload, err := json.Marshal(snapshot)
	if err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	if strings.Contains(string(payload), "fixture-secret") ||
		strings.Contains(string(payload), "token-value") ||
		strings.Contains(string(payload), "123e4567") {
		t.Fatalf("snapshot retained identity or secret: %s", payload)
	}
	if len(snapshot.Results) != 3 {
		t.Fatalf("unexpected results: %#v", snapshot.Results)
	}
}

func TestUntrustedTLSAndRedirectFailClosed(t *testing.T) {
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	client, err := New(Config{
		ControlBase: server.URL, IdentityBase: server.URL,
		RegistryBase: server.URL,
		Repository:   "p/123e4567-e89b-12d3-a456-426614174000/load",
		Service:      "registry.stage6.example", Roots: x509.NewCertPool(),
		Timeout: time.Second, MaxConcurrency: 2,
		CredentialProvider: func(context.Context) (Credential, error) {
			return Credential{ID: "id", Secret: "secret"}, nil
		},
	})
	if err != nil {
		t.Fatalf("new client: %v", err)
	}
	defer client.Close()
	_, err = client.KeystoneToken(context.Background())
	if FailureOf(err) != FailureDependency {
		t.Fatalf("untrusted TLS was not dependency failure: %v", err)
	}

	redirect := httptest.NewTLSServer(http.HandlerFunc(
		func(response http.ResponseWriter, request *http.Request) {
			http.Redirect(response, request, server.URL, http.StatusFound)
		},
	))
	defer redirect.Close()
	redirectClient := clientFor(t, redirect)
	_, err = redirectClient.KeystoneToken(context.Background())
	if FailureOf(err) != FailureProtocol {
		t.Fatalf("redirect was not refused: %v", err)
	}
}

func TestQuotaMismatchAndCleanupFailureAreSeparated(t *testing.T) {
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	client := clientFor(t, server)

	err := client.QuotaContention(
		context.Background(), "registry-token-value", manifests(), 1, 3,
	)
	if FailureOf(err) != FailureQuota {
		t.Fatalf("quota mismatch not separated: %v", err)
	}
	state.mu.Lock()
	if state.deletes != 2 {
		t.Fatalf("quota mismatch skipped cleanup: %d", state.deletes)
	}
	state.cleanupFailure = true
	state.mu.Unlock()
	err = client.QuotaContention(
		context.Background(), "registry-token-value", manifests(), 2, 2,
	)
	if FailureOf(err) != FailureCleanup {
		t.Fatalf("cleanup failure not separated: %v", err)
	}
}

func TestCancellationAndConfigurationRefusals(t *testing.T) {
	if _, err := New(Config{}); FailureOf(err) != FailureProtocol {
		t.Fatalf("empty configuration accepted: %v", err)
	}
	state := &testServerState{}
	server := testServer(t, state)
	defer server.Close()
	client := clientFor(t, server)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := client.KeystoneToken(ctx)
	if FailureOf(err) != FailureCancellation {
		t.Fatalf("cancellation not separated: %v", err)
	}
	err = client.QuotaContention(
		ctx, "registry-token-value", manifests(), 2, 2,
	)
	if FailureOf(err) != FailureCancellation {
		t.Fatalf("quota cancellation not separated: %v", err)
	}
}

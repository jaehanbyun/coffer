package driver

import (
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const (
	testRepository = "p/123e4567-e89b-12d3-a456-426614174000/demo"
	testUsername   = "member"
	testPassword   = "owner-only-password"
	testToken      = "finite-registry-token"
)

func testScope() string {
	return "repository:" + testRepository + ":pull,push"
}

func startTLSServer(t *testing.T, handler http.Handler) *httptest.Server {
	t.Helper()
	server := httptest.NewUnstartedServer(handler)
	server.Config.ErrorLog = log.New(io.Discard, "", 0)
	server.StartTLS()
	t.Cleanup(server.Close)
	return server
}

func rootsFor(server *httptest.Server) *x509.CertPool {
	roots := x509.NewCertPool()
	roots.AddCert(server.Certificate())
	return roots
}

func clientFor(
	t *testing.T,
	server *httptest.Server,
	update func(*Config),
) *Client {
	t.Helper()
	config := Config{
		BaseURL: server.URL + "/",
		CredentialProvider: func(context.Context) (string, string, error) {
			return testUsername, testPassword, nil
		},
		MaxAttempts:      4,
		RequestTimeout:   2 * time.Second,
		RetryDelayCap:    time.Millisecond,
		RootCAs:          rootsFor(server),
		MaxResponseBytes: 4096,
	}
	if update != nil {
		update(&config)
	}
	client, err := NewClient(config)
	if err != nil {
		t.Fatalf("NewClient failed: %v", err)
	}
	client.sleep = func(ctx context.Context, _ time.Duration) error {
		return ctx.Err()
	}
	t.Cleanup(client.CloseIdleConnections)
	return client
}

func writeChallenge(response http.ResponseWriter, serverURL string) {
	response.Header().Set(
		"WWW-Authenticate",
		fmt.Sprintf(
			`Bearer realm="%s/auth/token",service="coffer",scope="%s"`,
			serverURL,
			testScope(),
		),
	)
	response.WriteHeader(http.StatusUnauthorized)
}

func TestBearerChallengeParserAcceptsExactCofferShape(t *testing.T) {
	realm := "https://registry.example/auth/token"
	header := fmt.Sprintf(
		`Bearer realm="%s",service="coffer",scope="%s"`,
		realm,
		testScope(),
	)
	parsed, err := parseChallenge(header)
	if err != nil {
		t.Fatalf("challenge rejected: %v", err)
	}
	if parsed.realm.String() != realm || parsed.service != "coffer" ||
		parsed.scope != testScope() {
		t.Fatalf("challenge changed: %#v", parsed)
	}
}

func serveToken(t *testing.T, response http.ResponseWriter, request *http.Request) {
	t.Helper()
	username, password, ok := request.BasicAuth()
	if !ok || username != testUsername || password != testPassword {
		t.Fatalf("token request credentials changed")
	}
	if request.URL.Query().Get("service") != "coffer" ||
		request.URL.Query().Get("scope") != testScope() {
		t.Fatalf("token request query changed: %s", request.URL.RawQuery)
	}
	response.Header().Set("Content-Type", "application/json")
	_, _ = io.WriteString(
		response,
		`{"expires_in":60,"issued_at":"2026-07-25T00:00:00Z","token":"`+
			testToken+`"}`,
	)
}

func mustContent(t *testing.T, seed string, size int64) *Content {
	t.Helper()
	content, err := NewContent([]byte(seed), size)
	if err != nil {
		t.Fatalf("NewContent failed: %v", err)
	}
	return content
}

func TestDeterministicContentIsReplayableAndBounded(t *testing.T) {
	content := mustContent(t, "same-seed", 8193)
	first, err := io.ReadAll(content.NewReader())
	if err != nil {
		t.Fatal(err)
	}
	second, err := io.ReadAll(content.NewReader())
	if err != nil {
		t.Fatal(err)
	}
	if string(first) != string(second) || int64(len(first)) != content.Size() {
		t.Fatal("deterministic stream changed")
	}
	digest, err := content.Digest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	expected := fmt.Sprintf("sha256:%x", sha256.Sum256(first))
	if digest != expected {
		t.Fatalf("digest changed: %s != %s", digest, expected)
	}
	for _, size := range []int64{-1, MaxBlobBytes + 1} {
		if _, err := NewContent([]byte("seed"), size); failureKind(err) != FailureProtocol {
			t.Fatalf("size %d was not refused: %v", size, err)
		}
	}
	if _, err := NewContent(nil, 1); failureKind(err) != FailureProtocol {
		t.Fatalf("empty seed was not refused: %v", err)
	}
}

func TestContentDigestHonorsCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := mustContent(t, "cancel", 1<<20).Digest(ctx)
	if failureKind(err) != FailureCancelled {
		t.Fatalf("unexpected failure: %v", err)
	}
}

func TestMonolithicUploadAuthenticatesRetriesAndRecords(t *testing.T) {
	content := mustContent(t, "monolithic", 4097)
	digest, err := content.Digest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var server *httptest.Server
	var authorized atomic.Int64
	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/auth/token":
			serveToken(t, response, request)
		case "/v2/" + testRepository + "/blobs/uploads/":
			if request.Header.Get("Authorization") != "Bearer "+testToken {
				writeChallenge(response, server.URL)
				return
			}
			if authorized.Add(1) == 1 {
				response.Header().Set("Retry-After", "0")
				response.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			body, readErr := io.ReadAll(request.Body)
			if readErr != nil {
				t.Fatal(readErr)
			}
			if int64(len(body)) != content.Size() ||
				request.Header.Get("Content-Type") != "application/octet-stream" ||
				request.URL.Query().Get("digest") != digest {
				t.Fatal("monolithic request changed")
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set(
				"Location",
				"/v2/"+testRepository+"/blobs/"+digest,
			)
			response.WriteHeader(http.StatusCreated)
		default:
			t.Fatalf("unexpected path: %s", request.URL.Path)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	if err := client.UploadMonolithic(context.Background(), testRepository, content); err != nil {
		t.Fatalf("upload failed: %v", err)
	}
	snapshot := client.Recorder().Snapshot()
	if len(snapshot.Operations) != 1 {
		t.Fatalf("unexpected results: %#v", snapshot.Operations)
	}
	result := snapshot.Operations[0]
	if result.Operation != "blob-monolithic" || result.Result != "success" ||
		result.Attempts != 3 || result.Retries != 2 ||
		result.TransferredByte < uint64(content.Size()) ||
		result.DigestChecks != 1 {
		t.Fatalf("unexpected operation result: %#v", result)
	}
	payload, err := MarshalCanonical(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(payload), testPassword) ||
		strings.Contains(string(payload), testToken) ||
		strings.Contains(string(payload), testRepository) {
		t.Fatal("retained result contains an identity or credential")
	}
}

func TestChunkedUploadMaintainsLocationRangeAndDigest(t *testing.T) {
	content := mustContent(t, "chunked", 10)
	digest, err := content.Digest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var server *httptest.Server
	var uploaded []byte
	var patches int
	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/auth/token" {
			serveToken(t, response, request)
			return
		}
		if request.Header.Get("Authorization") != "Bearer "+testToken {
			writeChallenge(response, server.URL)
			return
		}
		switch {
		case request.Method == http.MethodPost &&
			request.URL.Path == "/v2/"+testRepository+"/blobs/uploads/":
			response.Header().Set(
				"Location",
				"/v2/"+testRepository+"/blobs/uploads/upload-1?state=opaque",
			)
			response.Header().Set("Range", "bytes=0-0")
			response.WriteHeader(http.StatusAccepted)
		case request.Method == http.MethodPatch &&
			request.URL.Path == "/v2/"+testRepository+"/blobs/uploads/upload-1":
			body, readErr := io.ReadAll(request.Body)
			if readErr != nil {
				t.Fatal(readErr)
			}
			expectedRange := fmt.Sprintf("%d-%d", len(uploaded), len(uploaded)+len(body)-1)
			if request.Header.Get("Content-Range") != expectedRange ||
				request.URL.Query().Get("state") != "opaque" {
				t.Fatal("chunk continuity changed")
			}
			uploaded = append(uploaded, body...)
			patches++
			response.Header().Set(
				"Location",
				"/v2/"+testRepository+"/blobs/uploads/upload-1?state=opaque",
			)
			response.Header().Set("Range", fmt.Sprintf("0-%d", len(uploaded)-1))
			response.WriteHeader(http.StatusAccepted)
		case request.Method == http.MethodPut &&
			request.URL.Path == "/v2/"+testRepository+"/blobs/uploads/upload-1":
			if request.URL.Query().Get("state") != "opaque" ||
				request.URL.Query().Get("digest") != digest {
				t.Fatal("finalize query changed")
			}
			actual := fmt.Sprintf("sha256:%x", sha256.Sum256(uploaded))
			if actual != digest {
				t.Fatal("uploaded digest changed")
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set("Location", "/v2/"+testRepository+"/blobs/"+digest)
			response.WriteHeader(http.StatusCreated)
		default:
			t.Fatalf("unexpected request: %s %s", request.Method, request.URL)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	if err := client.UploadChunked(context.Background(), testRepository, content, 4); err != nil {
		t.Fatalf("chunked upload failed: %v", err)
	}
	if patches != 3 || string(uploaded) == "" {
		t.Fatalf("chunk count changed: %d", patches)
	}
	result := client.Recorder().Snapshot().Operations[0]
	if result.Operation != "blob-resumable" || result.Result != "success" ||
		result.TransferredByte != 10 || result.DigestChecks != 1 {
		t.Fatalf("unexpected operation result: %#v", result)
	}
}

func TestChunkPatchAmbiguityReconcilesCommittedOrPriorRange(t *testing.T) {
	for _, committedBeforeFailure := range []bool{false, true} {
		name := "prior"
		if committedBeforeFailure {
			name = "committed"
		}
		t.Run(name, func(t *testing.T) {
			content := mustContent(t, "resume-"+name, 8)
			digest, err := content.Digest(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			var server *httptest.Server
			var uploaded []byte
			var patches atomic.Int64
			var statuses atomic.Int64
			firstFailure := true
			handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
				if request.URL.Path == "/auth/token" {
					serveToken(t, response, request)
					return
				}
				if request.Header.Get("Authorization") != "Bearer "+testToken {
					writeChallenge(response, server.URL)
					return
				}
				location := "/v2/" + testRepository + "/blobs/uploads/upload-1"
				switch request.Method {
				case http.MethodPost:
					response.Header().Set("Location", location)
					response.Header().Set("Range", "bytes=0-0")
					response.WriteHeader(http.StatusAccepted)
				case http.MethodPatch:
					body, readErr := io.ReadAll(request.Body)
					if readErr != nil {
						t.Error(readErr)
						response.WriteHeader(http.StatusInternalServerError)
						return
					}
					patches.Add(1)
					if firstFailure {
						firstFailure = false
						if committedBeforeFailure {
							uploaded = append(uploaded, body...)
						}
						response.Header().Set("Retry-After", "0")
						response.WriteHeader(http.StatusServiceUnavailable)
						return
					}
					expectedStart := len(uploaded)
					if request.Header.Get("Content-Range") !=
						fmt.Sprintf("%d-%d", expectedStart, expectedStart+len(body)-1) {
						t.Error("replayed chunk offset changed")
						response.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
						return
					}
					uploaded = append(uploaded, body...)
					response.Header().Set("Location", location)
					response.Header().Set("Range", fmt.Sprintf("0-%d", len(uploaded)-1))
					response.WriteHeader(http.StatusAccepted)
				case http.MethodGet:
					statuses.Add(1)
					response.Header().Set("Location", location)
					if len(uploaded) == 0 {
						response.Header().Set("Range", "bytes=0-0")
					} else {
						response.Header().Set(
							"Range",
							fmt.Sprintf("bytes=0-%d", len(uploaded)-1),
						)
					}
					response.WriteHeader(http.StatusNoContent)
				case http.MethodPut:
					actual := fmt.Sprintf("sha256:%x", sha256.Sum256(uploaded))
					if actual != digest || request.URL.Query().Get("digest") != digest {
						t.Error("resumed upload digest changed")
						response.WriteHeader(http.StatusBadRequest)
						return
					}
					response.Header().Set("Docker-Content-Digest", digest)
					response.WriteHeader(http.StatusCreated)
				default:
					t.Errorf("unexpected method: %s", request.Method)
					response.WriteHeader(http.StatusMethodNotAllowed)
				}
			})
			server = startTLSServer(t, handler)
			client := clientFor(t, server, nil)

			if err := client.UploadChunked(
				context.Background(),
				testRepository,
				content,
				4,
			); err != nil {
				t.Fatalf("resumable upload failed: %v", err)
			}
			expectedPatches := int64(3)
			if committedBeforeFailure {
				expectedPatches = 2
			}
			if patches.Load() != expectedPatches || statuses.Load() != 1 ||
				int64(len(uploaded)) != content.Size() {
				t.Fatalf(
					"recovery changed: patches=%d statuses=%d bytes=%d",
					patches.Load(),
					statuses.Load(),
					len(uploaded),
				)
			}
		})
	}
}

func TestChunkStatusDriftAndExhaustionFailClosed(t *testing.T) {
	for _, mode := range []string{"drift-range", "drift-location", "exhausted"} {
		t.Run(mode, func(t *testing.T) {
			var server *httptest.Server
			var statuses atomic.Int64
			handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
				if request.URL.Path == "/auth/token" {
					serveToken(t, response, request)
					return
				}
				if request.Header.Get("Authorization") != "Bearer "+testToken {
					writeChallenge(response, server.URL)
					return
				}
				location := "/v2/" + testRepository + "/blobs/uploads/upload-1"
				switch request.Method {
				case http.MethodPost:
					response.Header().Set("Location", location)
					response.Header().Set("Range", "bytes=0-0")
					response.WriteHeader(http.StatusAccepted)
				case http.MethodPatch:
					response.Header().Set("Retry-After", "0")
					response.WriteHeader(http.StatusBadGateway)
				case http.MethodGet:
					statuses.Add(1)
					if mode == "exhausted" {
						response.Header().Set("Retry-After", "0")
						response.WriteHeader(http.StatusServiceUnavailable)
						return
					}
					if mode == "drift-location" {
						response.Header().Set(
							"Location",
							"https://example.invalid/v2/other/blobs/uploads/id",
						)
						response.Header().Set("Range", "bytes=0-0")
					} else {
						response.Header().Set("Location", location)
						response.Header().Set("Range", "bytes=0-2")
					}
					response.WriteHeader(http.StatusNoContent)
				default:
					t.Errorf("unexpected method: %s", request.Method)
					response.WriteHeader(http.StatusMethodNotAllowed)
				}
			})
			server = startTLSServer(t, handler)
			client := clientFor(t, server, func(config *Config) {
				config.MaxAttempts = 3
			})

			err := client.UploadChunked(
				context.Background(),
				testRepository,
				mustContent(t, "status-"+mode, 8),
				4,
			)
			expected := FailureProtocol
			expectedStatuses := int64(1)
			if mode == "exhausted" {
				expected = FailureRetryExhausted
				expectedStatuses = 3
			}
			if failureKind(err) != expected || statuses.Load() != expectedStatuses {
				t.Fatalf(
					"status failure changed: kind=%s statuses=%d",
					failureKind(err),
					statuses.Load(),
				)
			}
		})
	}
}

func TestChunkPatchTransportLossUsesStatusBeforeContinuing(t *testing.T) {
	content := mustContent(t, "transport-loss", 8)
	digest, err := content.Digest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var server *httptest.Server
	var uploaded []byte
	var lost atomic.Bool
	var statuses atomic.Int64
	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/auth/token" {
			serveToken(t, response, request)
			return
		}
		if request.Header.Get("Authorization") != "Bearer "+testToken {
			writeChallenge(response, server.URL)
			return
		}
		location := "/v2/" + testRepository + "/blobs/uploads/upload-1"
		switch request.Method {
		case http.MethodPost:
			response.Header().Set("Location", location)
			response.Header().Set("Range", "bytes=0-0")
			response.WriteHeader(http.StatusAccepted)
		case http.MethodPatch:
			body, readErr := io.ReadAll(request.Body)
			if readErr != nil {
				t.Error(readErr)
				return
			}
			uploaded = append(uploaded, body...)
			if lost.CompareAndSwap(false, true) {
				hijacker, ok := response.(http.Hijacker)
				if !ok {
					t.Error("test server cannot model transport loss")
					return
				}
				connection, _, hijackErr := hijacker.Hijack()
				if hijackErr != nil {
					t.Error(hijackErr)
					return
				}
				_ = connection.Close()
				return
			}
			response.Header().Set("Location", location)
			response.Header().Set("Range", fmt.Sprintf("0-%d", len(uploaded)-1))
			response.WriteHeader(http.StatusAccepted)
		case http.MethodGet:
			statuses.Add(1)
			response.Header().Set("Location", location)
			response.Header().Set("Range", fmt.Sprintf("bytes=0-%d", len(uploaded)-1))
			response.WriteHeader(http.StatusNoContent)
		case http.MethodPut:
			actual := fmt.Sprintf("sha256:%x", sha256.Sum256(uploaded))
			if actual != digest {
				t.Error("transport-loss recovery duplicated data")
				response.WriteHeader(http.StatusBadRequest)
				return
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.WriteHeader(http.StatusCreated)
		default:
			t.Errorf("unexpected method: %s", request.Method)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	if err := client.UploadChunked(
		context.Background(),
		testRepository,
		content,
		4,
	); err != nil {
		t.Fatalf("transport-loss recovery failed: %v", err)
	}
	if statuses.Load() != 1 || int64(len(uploaded)) != content.Size() {
		t.Fatalf("transport-loss recovery changed: statuses=%d bytes=%d", statuses.Load(), len(uploaded))
	}
}

func TestChunkStatusQueryHonorsCancellation(t *testing.T) {
	var server *httptest.Server
	statusStarted := make(chan struct{}, 1)
	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/auth/token" {
			serveToken(t, response, request)
			return
		}
		if request.Header.Get("Authorization") != "Bearer "+testToken {
			writeChallenge(response, server.URL)
			return
		}
		location := "/v2/" + testRepository + "/blobs/uploads/upload-1"
		switch request.Method {
		case http.MethodPost:
			response.Header().Set("Location", location)
			response.Header().Set("Range", "bytes=0-0")
			response.WriteHeader(http.StatusAccepted)
		case http.MethodPatch:
			response.WriteHeader(http.StatusServiceUnavailable)
		case http.MethodGet:
			statusStarted <- struct{}{}
			<-request.Context().Done()
		default:
			t.Errorf("unexpected method: %s", request.Method)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)
	ctx, cancel := context.WithCancel(context.Background())
	content := mustContent(t, "status-cancel", 8)
	result := make(chan error, 1)
	go func() {
		result <- client.UploadChunked(
			ctx,
			testRepository,
			content,
			4,
		)
	}()
	<-statusStarted
	cancel()
	if err := <-result; failureKind(err) != FailureCancelled {
		t.Fatalf("status cancellation changed: %v", err)
	}
}

func TestConcurrentMonolithicOperationsRemainBounded(t *testing.T) {
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
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Error(err)
			response.WriteHeader(http.StatusInternalServerError)
			return
		}
		digest := fmt.Sprintf("sha256:%x", sha256.Sum256(body))
		if request.URL.Query().Get("digest") != digest {
			t.Error("concurrent digest changed")
			response.WriteHeader(http.StatusBadRequest)
			return
		}
		completed.Add(1)
		response.Header().Set("Docker-Content-Digest", digest)
		response.WriteHeader(http.StatusCreated)
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)
	const workers = 8
	contents := make([]*Content, workers)
	for index := range contents {
		contents[index] = mustContent(t, fmt.Sprintf("worker-%d", index), 1024)
	}
	failures := make(chan error, workers)
	for index := 0; index < workers; index++ {
		go func(worker int) {
			failures <- client.UploadMonolithic(
				context.Background(),
				testRepository,
				contents[worker],
			)
		}(index)
	}
	for index := 0; index < workers; index++ {
		if err := <-failures; err != nil {
			t.Fatalf("concurrent upload failed: %v", err)
		}
	}
	if completed.Load() != workers {
		t.Fatalf("completed operations changed: %d", completed.Load())
	}
	result := client.Recorder().Snapshot().Operations[0]
	if result.Count != workers || result.DigestChecks != workers ||
		result.TransferredByte < workers*1024 {
		t.Fatalf("concurrent aggregate changed: %#v", result)
	}
}

func TestCrossOriginAndTraversalLocationsAreRefused(t *testing.T) {
	tests := []string{
		"https://example.invalid/v2/" + testRepository + "/blobs/uploads/id",
		"/v2/" + testRepository + "/blobs/uploads/../other",
	}
	for _, location := range tests {
		t.Run(location, func(t *testing.T) {
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
				response.Header().Set("Location", location)
				response.Header().Set("Range", "bytes=0-0")
				response.WriteHeader(http.StatusAccepted)
			})
			server = startTLSServer(t, handler)
			client := clientFor(t, server, nil)
			err := client.UploadChunked(
				context.Background(),
				testRepository,
				mustContent(t, "location", 8),
				4,
			)
			if failureKind(err) != FailureProtocol {
				t.Fatalf("unexpected failure: %v", err)
			}
		})
	}
}

func TestUntrustedTLSIsNeverBypassed(t *testing.T) {
	var requests atomic.Int64
	server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		requests.Add(1)
	}))
	client := clientFor(t, server, func(config *Config) {
		config.RootCAs = x509.NewCertPool()
		config.MaxAttempts = 1
	})
	err := client.UploadMonolithic(
		context.Background(),
		testRepository,
		mustContent(t, "tls", 8),
	)
	if failureKind(err) != FailureDependency || requests.Load() != 0 {
		t.Fatalf("TLS was not fail closed: kind=%s requests=%d", failureKind(err), requests.Load())
	}
}

func TestCancelledOperationDoesNotReachServer(t *testing.T) {
	var requests atomic.Int64
	server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		requests.Add(1)
	}))
	client := clientFor(t, server, nil)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := client.UploadMonolithic(ctx, testRepository, mustContent(t, "cancel", 8))
	if failureKind(err) != FailureCancelled || requests.Load() != 0 {
		t.Fatalf("cancellation changed: kind=%s requests=%d", failureKind(err), requests.Load())
	}
	result := client.Recorder().Snapshot().Operations[0]
	if result.Result != string(FailureCancelled) || result.Attempts != 0 {
		t.Fatalf("cancelled result changed: %#v", result)
	}
}

func TestRetryableStatusExhaustionIsFinite(t *testing.T) {
	var server *httptest.Server
	var requests atomic.Int64
	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/auth/token" {
			serveToken(t, response, request)
			return
		}
		requests.Add(1)
		if request.Header.Get("Authorization") != "Bearer "+testToken {
			writeChallenge(response, server.URL)
			return
		}
		response.Header().Set("Retry-After", "0")
		response.WriteHeader(http.StatusBadGateway)
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, func(config *Config) {
		config.MaxAttempts = 3
	})
	err := client.UploadMonolithic(
		context.Background(),
		testRepository,
		mustContent(t, "retry", 8),
	)
	if failureKind(err) != FailureRetryExhausted || requests.Load() != 3 {
		t.Fatalf("retry bound changed: kind=%s requests=%d", failureKind(err), requests.Load())
	}
	result := client.Recorder().Snapshot().Operations[0]
	if result.Attempts != 3 || result.Result != string(FailureRetryExhausted) {
		t.Fatalf("retry result changed: %#v", result)
	}
}

func TestOversizedResponseAndMalformedChallengeFailClosed(t *testing.T) {
	t.Run("response", func(t *testing.T) {
		server := startTLSServer(t, http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
			response.WriteHeader(http.StatusInternalServerError)
			_, _ = io.WriteString(response, strings.Repeat("x", 33))
		}))
		client := clientFor(t, server, func(config *Config) {
			config.MaxResponseBytes = 32
			config.MaxAttempts = 1
		})
		err := client.UploadMonolithic(
			context.Background(),
			testRepository,
			mustContent(t, "bounded", 8),
		)
		if failureKind(err) != FailureProtocol {
			t.Fatalf("oversized response was accepted: %v", err)
		}
	})
	t.Run("challenge", func(t *testing.T) {
		server := startTLSServer(t, http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
			response.Header().Set(
				"WWW-Authenticate",
				`Bearer realm="https://example.invalid/auth/token",service="coffer",scope="wrong"`,
			)
			response.WriteHeader(http.StatusUnauthorized)
		}))
		client := clientFor(t, server, func(config *Config) {
			config.MaxAttempts = 1
		})
		err := client.UploadMonolithic(
			context.Background(),
			testRepository,
			mustContent(t, "challenge", 8),
		)
		if failureKind(err) != FailureAuthentication {
			t.Fatalf("malformed challenge was accepted: %v", err)
		}
	})
}

func TestClientConfigurationAndRepositoryAreStrict(t *testing.T) {
	credentials := func(context.Context) (string, string, error) {
		return "user", "password", nil
	}
	for _, config := range []Config{
		{BaseURL: "http://registry.example", RootCAs: x509.NewCertPool(), CredentialProvider: credentials},
		{BaseURL: "https://registry.example/path", RootCAs: x509.NewCertPool(), CredentialProvider: credentials},
		{BaseURL: "https://registry.example", CredentialProvider: credentials},
		{BaseURL: "https://registry.example", RootCAs: x509.NewCertPool()},
	} {
		if _, err := NewClient(config); failureKind(err) != FailureProtocol {
			t.Fatalf("unsafe configuration accepted: %#v", config)
		}
	}
	server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Fatal("invalid repository reached server")
	}))
	client := clientFor(t, server, nil)
	err := client.UploadMonolithic(
		context.Background(),
		"p/project/../other",
		mustContent(t, "repo", 8),
	)
	if failureKind(err) != FailureProtocol {
		t.Fatalf("invalid repository accepted: %v", err)
	}
}

func TestCanonicalResultIsSortedOwnerOnlyAndAtomic(t *testing.T) {
	current := time.Unix(100, 0)
	recorder := newRecorder(func() time.Time { return current })
	recorder.observe(observation{
		operation:      "blob-resumable",
		result:         FailureProtocol,
		latency:        6 * time.Second,
		attempts:       2,
		transferred:    4,
		logicalSuccess: false,
	})
	recorder.observe(observation{
		operation:      "blob-monolithic",
		result:         ResultSuccess,
		latency:        9 * time.Millisecond,
		attempts:       1,
		transferred:    8,
		digestChecks:   1,
		logicalSuccess: true,
	})
	current = current.Add(7 * time.Second)
	snapshot := recorder.Snapshot()
	if snapshot.DurationMilliseconds != 7000 ||
		len(snapshot.Operations) != 2 ||
		snapshot.Operations[0].Operation != "blob-monolithic" ||
		snapshot.Operations[1].Operation != "blob-resumable" {
		t.Fatalf("snapshot ordering changed: %#v", snapshot)
	}
	payload, err := MarshalCanonical(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	if payload[len(payload)-1] != '\n' || json.Valid(payload[:len(payload)-1]) == false {
		t.Fatal("canonical JSON changed")
	}
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "result.json")
	if err := WriteCanonical(path, snapshot); err != nil {
		t.Fatal(err)
	}
	written, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(written) != string(payload) || info.Mode().Perm() != 0o600 {
		t.Fatal("owner-only canonical output changed")
	}
	link := filepath.Join(directory, "link.json")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if failureKind(WriteCanonical(link, snapshot)) != FailureProtocol {
		t.Fatal("symlink output was accepted")
	}
}

func TestDriverErrorsNeverIncludeServerOrCredentialText(t *testing.T) {
	credentialError := errors.New("secret-bearing-provider-error")
	server := startTLSServer(t, http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		response.Header().Set(
			"WWW-Authenticate",
			fmt.Sprintf(
				`Bearer realm="%s/auth/token",service="coffer",scope="%s"`,
				"https://"+request.Host,
				testScope(),
			),
		)
		response.WriteHeader(http.StatusUnauthorized)
	}))
	client := clientFor(t, server, func(config *Config) {
		config.CredentialProvider = func(context.Context) (string, string, error) {
			return "", "", credentialError
		}
		config.MaxAttempts = 1
	})
	err := client.UploadMonolithic(
		context.Background(),
		testRepository,
		mustContent(t, "secret", 8),
	)
	if failureKind(err) != FailureAuthentication ||
		strings.Contains(err.Error(), credentialError.Error()) ||
		strings.Contains(err.Error(), testRepository) {
		t.Fatalf("failure text leaked details: %v", err)
	}
}

package driver

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
)

func manifestPayload(t *testing.T, mediaType string) []byte {
	t.Helper()
	var document map[string]any
	if mediaType == OCIImageManifest {
		document = map[string]any{
			"schemaVersion": 2,
			"mediaType":     mediaType,
			"config": map[string]any{
				"mediaType": "application/vnd.oci.image.config.v1+json",
				"digest":    "sha256:" + strings.Repeat("1", 64),
				"size":      2,
			},
			"layers": []any{},
		}
	} else {
		document = map[string]any{
			"schemaVersion": 2,
			"mediaType":     mediaType,
			"manifests": []any{
				map[string]any{
					"mediaType": OCIImageManifest,
					"digest":    "sha256:" + strings.Repeat("2", 64),
					"size":      256,
				},
			},
		}
	}
	payload, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	return payload
}

func TestManifestPublishHeadAndGetAreDigestExact(t *testing.T) {
	payload := manifestPayload(t, OCIImageManifest)
	sum := sha256.Sum256(payload)
	digest := "sha256:" + hex.EncodeToString(sum[:])
	reference := "load-test"
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
		expectedPath := "/v2/" + testRepository + "/manifests/" + reference
		if request.URL.Path != expectedPath {
			t.Fatalf("manifest path changed: %s", request.URL.Path)
		}
		switch request.Method {
		case http.MethodPut:
			body, err := io.ReadAll(request.Body)
			if err != nil {
				t.Fatal(err)
			}
			if string(body) != string(payload) ||
				request.Header.Get("Content-Type") != OCIImageManifest {
				t.Fatal("manifest publish body changed")
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set("Location", expectedPath)
			response.WriteHeader(http.StatusCreated)
		case http.MethodHead:
			if request.Header.Get("Accept") != OCIImageManifest {
				t.Fatal("manifest HEAD accept changed")
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set("Content-Type", OCIImageManifest)
			response.Header().Set("Content-Length", strconv.Itoa(len(payload)))
			response.WriteHeader(http.StatusOK)
		case http.MethodGet:
			if request.Header.Get("Accept") != OCIImageManifest {
				t.Fatal("manifest GET accept changed")
			}
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set("Content-Type", OCIImageManifest)
			response.Header().Set("Content-Length", strconv.Itoa(len(payload)))
			response.WriteHeader(http.StatusOK)
			_, _ = response.Write(payload)
		default:
			t.Fatalf("unexpected method: %s", request.Method)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	published, err := client.PublishManifest(
		context.Background(),
		testRepository,
		reference,
		OCIImageManifest,
		payload,
	)
	if err != nil || published != digest {
		t.Fatalf("manifest publish failed: digest=%s error=%v", published, err)
	}
	if err := client.HeadManifest(
		context.Background(),
		testRepository,
		reference,
		OCIImageManifest,
		digest,
		int64(len(payload)),
	); err != nil {
		t.Fatalf("manifest HEAD failed: %v", err)
	}
	if err := client.GetManifest(
		context.Background(),
		testRepository,
		reference,
		OCIImageManifest,
		payload,
	); err != nil {
		t.Fatalf("manifest GET failed: %v", err)
	}

	results := client.Recorder().Snapshot().Operations
	if len(results) != 2 ||
		results[0].Operation != "manifest-publish" ||
		results[0].DigestChecks != 1 ||
		results[1].Operation != "manifest-read" ||
		results[1].Count != 2 ||
		results[1].DigestChecks != 2 ||
		results[1].TransferredByte != uint64(len(payload)) {
		t.Fatalf("manifest aggregate changed: %#v", results)
	}
}

func TestBlobHeadFullAndRangeReadsVerifyLocalBytes(t *testing.T) {
	content := mustContent(t, "blob-read", 65)
	digest, err := content.Digest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	full, err := io.ReadAll(content.NewReader())
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
		if request.URL.Path != "/v2/"+testRepository+"/blobs/"+digest {
			t.Fatalf("blob path changed: %s", request.URL.Path)
		}
		response.Header().Set("Docker-Content-Digest", digest)
		switch request.Method {
		case http.MethodHead:
			response.Header().Set("Content-Length", strconv.Itoa(len(full)))
			response.WriteHeader(http.StatusOK)
		case http.MethodGet:
			value := full
			status := http.StatusOK
			if requested := request.Header.Get("Range"); requested != "" {
				if requested != "bytes=7-39" {
					t.Fatalf("range changed: %s", requested)
				}
				value = full[7:40]
				status = http.StatusPartialContent
				response.Header().Set(
					"Content-Range",
					fmt.Sprintf("bytes 7-39/%d", len(full)),
				)
			}
			response.Header().Set("Content-Length", strconv.Itoa(len(value)))
			response.WriteHeader(status)
			_, _ = response.Write(value)
		default:
			t.Fatalf("unexpected method: %s", request.Method)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	if err := client.HeadBlob(context.Background(), testRepository, content); err != nil {
		t.Fatalf("blob HEAD failed: %v", err)
	}
	if err := client.ReadBlob(
		context.Background(),
		testRepository,
		content,
		0,
		content.Size(),
	); err != nil {
		t.Fatalf("full blob GET failed: %v", err)
	}
	if err := client.ReadBlob(
		context.Background(),
		testRepository,
		content,
		7,
		33,
	); err != nil {
		t.Fatalf("range blob GET failed: %v", err)
	}

	result := client.Recorder().Snapshot().Operations[0]
	if result.Operation != "blob-read" || result.Count != 3 ||
		result.DigestChecks != 3 ||
		result.TransferredByte != uint64(content.Size()+33) {
		t.Fatalf("blob aggregate changed: %#v", result)
	}
}

func TestDeterministicRangeReaderMatchesFullStream(t *testing.T) {
	content := mustContent(t, "range-alignment", 129)
	full, err := io.ReadAll(content.NewReader())
	if err != nil {
		t.Fatal(err)
	}
	for _, window := range [][2]int64{
		{0, 1},
		{1, 31},
		{31, 34},
		{32, 32},
		{63, 65},
		{129, 0},
	} {
		reader, err := content.NewRangeReader(window[0], window[1])
		if err != nil {
			t.Fatal(err)
		}
		value, err := io.ReadAll(reader)
		if err != nil {
			t.Fatal(err)
		}
		if string(value) != string(full[window[0]:window[0]+window[1]]) {
			t.Fatalf("range %v changed", window)
		}
	}
	if _, err := content.NewRangeReader(128, 2); failureKind(err) != FailureProtocol {
		t.Fatalf("invalid range was accepted: %v", err)
	}
}

func TestManifestAndBlobIntegrityDriftFailsClosed(t *testing.T) {
	for _, mode := range []string{
		"manifest-body",
		"manifest-location",
		"blob-range",
		"blob-body",
		"redirect",
	} {
		t.Run(mode, func(t *testing.T) {
			payload := manifestPayload(t, OCIImageManifest)
			content := mustContent(t, "integrity-"+mode, 32)
			contentDigest, err := content.Digest(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			full, err := io.ReadAll(content.NewReader())
			if err != nil {
				t.Fatal(err)
			}
			var server *httptest.Server
			var requests atomic.Int64
			handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
				if request.URL.Path == "/auth/token" {
					serveToken(t, response, request)
					return
				}
				if request.Header.Get("Authorization") != "Bearer "+testToken {
					writeChallenge(response, server.URL)
					return
				}
				requests.Add(1)
				if mode == "redirect" {
					response.Header().Set("Location", "https://example.invalid/blob")
					response.WriteHeader(http.StatusTemporaryRedirect)
					return
				}
				if strings.Contains(request.URL.Path, "/manifests/") {
					sum := sha256.Sum256(payload)
					digest := "sha256:" + hex.EncodeToString(sum[:])
					response.Header().Set("Docker-Content-Digest", digest)
					response.Header().Set("Content-Type", OCIImageManifest)
					if request.Method == http.MethodPut {
						if _, err := io.Copy(io.Discard, request.Body); err != nil {
							t.Error(err)
							response.WriteHeader(http.StatusInternalServerError)
							return
						}
						if mode == "manifest-location" {
							response.Header().Set(
								"Location",
								"https://example.invalid/v2/other/manifests/tag",
							)
						} else {
							response.Header().Set("Location", request.URL.Path)
						}
						response.WriteHeader(http.StatusCreated)
						return
					}
					response.Header().Set("Content-Length", strconv.Itoa(len(payload)))
					response.WriteHeader(http.StatusOK)
					changed := append([]byte(nil), payload...)
					changed[len(changed)-2] ^= 1
					_, _ = response.Write(changed)
					return
				}
				response.Header().Set("Docker-Content-Digest", contentDigest)
				response.Header().Set("Content-Length", "8")
				value := append([]byte(nil), full[4:12]...)
				if mode == "blob-range" {
					response.Header().Set("Content-Range", "bytes 3-10/32")
				} else {
					response.Header().Set("Content-Range", "bytes 4-11/32")
				}
				if mode == "blob-body" {
					value[0] ^= 1
				}
				response.WriteHeader(http.StatusPartialContent)
				_, _ = response.Write(value)
			})
			server = startTLSServer(t, handler)
			client := clientFor(t, server, nil)

			var operationErr error
			switch mode {
			case "manifest-body":
				operationErr = client.GetManifest(
					context.Background(),
					testRepository,
					"tag",
					OCIImageManifest,
					payload,
				)
			case "manifest-location":
				_, operationErr = client.PublishManifest(
					context.Background(),
					testRepository,
					"tag",
					OCIImageManifest,
					payload,
				)
			default:
				operationErr = client.ReadBlob(
					context.Background(),
					testRepository,
					content,
					4,
					8,
				)
			}
			expected := FailureDigest
			if mode == "manifest-location" || mode == "blob-range" ||
				mode == "redirect" {
				expected = FailureProtocol
			}
			if failureKind(operationErr) != expected || requests.Load() != 1 {
				t.Fatalf(
					"integrity failure changed: kind=%s requests=%d",
					failureKind(operationErr),
					requests.Load(),
				)
			}
		})
	}
}

func TestBlobReadCancellationStopsStreaming(t *testing.T) {
	content := mustContent(t, "cancel-stream", 64)
	digest, err := content.Digest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	full, err := io.ReadAll(content.NewReader())
	if err != nil {
		t.Fatal(err)
	}
	var server *httptest.Server
	started := make(chan struct{}, 1)
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
		response.Header().Set("Content-Length", "64")
		response.WriteHeader(http.StatusOK)
		_, _ = response.Write(full[:1])
		if flusher, ok := response.(http.Flusher); ok {
			flusher.Flush()
		}
		started <- struct{}{}
		<-request.Context().Done()
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)
	ctx, cancel := context.WithCancel(context.Background())
	result := make(chan error, 1)
	go func() {
		result <- client.ReadBlob(
			ctx,
			testRepository,
			content,
			0,
			content.Size(),
		)
	}()
	<-started
	cancel()
	if err := <-result; failureKind(err) != FailureCancelled {
		t.Fatalf("stream cancellation changed: %v", err)
	}
}

func TestManifestValidationFailsBeforeNetwork(t *testing.T) {
	var requests atomic.Int64
	server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		requests.Add(1)
	}))
	client := clientFor(t, server, nil)
	valid := manifestPayload(t, OCIImageManifest)
	for _, test := range []struct {
		reference string
		mediaType string
		payload   []byte
	}{
		{"../other", OCIImageManifest, valid},
		{"tag", "application/json", valid},
		{"tag", OCIImageManifest, []byte(`{}`)},
		{"sha256:" + strings.Repeat("0", 64), OCIImageManifest, valid},
	} {
		if _, err := client.PublishManifest(
			context.Background(),
			testRepository,
			test.reference,
			test.mediaType,
			test.payload,
		); err == nil {
			t.Fatalf("invalid manifest accepted: %#v", test)
		}
	}
	if requests.Load() != 0 {
		t.Fatalf("invalid manifest reached network: %d", requests.Load())
	}
}

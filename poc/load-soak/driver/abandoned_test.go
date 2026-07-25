package driver

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestAbandonedUploadShapeCreatesPartialAndCancelsBoth(t *testing.T) {
	content := mustContent(t, "abandoned", 64)
	var server *httptest.Server
	var started atomic.Int64
	var patched atomic.Int64
	var deleted atomic.Int64
	offsets := make(map[string]int)
	handler := http.HandlerFunc(func(
		response http.ResponseWriter,
		request *http.Request,
	) {
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
					"/v2/%s/blobs/uploads/partial-%d?state=opaque-%d",
					testRepository,
					identity,
					identity,
				),
			)
			response.Header().Set("Range", "0-0")
			response.WriteHeader(http.StatusAccepted)
		case http.MethodPatch:
			body, err := io.ReadAll(request.Body)
			offset := offsets[request.URL.Path]
			expectedLength := 16
			if offset == 32 {
				expectedLength = 8
			}
			if err != nil || len(body) != expectedLength ||
				request.Header.Get("Content-Range") !=
					fmt.Sprintf(
						"%d-%d",
						offset,
						offset+expectedLength-1,
					) ||
				request.Header.Get("Content-Type") !=
					"application/octet-stream" {
				t.Fatalf("partial patch changed: %v", err)
			}
			offsets[request.URL.Path] += len(body)
			patched.Add(1)
			response.Header().Set("Location", request.URL.String())
			response.Header().Set(
				"Range",
				fmt.Sprintf("0-%d", offsets[request.URL.Path]-1),
			)
			response.WriteHeader(http.StatusAccepted)
		case http.MethodDelete:
			if !strings.HasPrefix(
				request.URL.Path,
				"/v2/"+testRepository+"/blobs/uploads/partial-",
			) || !strings.HasPrefix(
				request.URL.Query().Get("state"),
				"opaque-",
			) {
				t.Fatalf("cleanup identity changed: %s", request.URL)
			}
			deleted.Add(1)
			response.WriteHeader(http.StatusNoContent)
		default:
			t.Fatalf("unexpected request: %s %s", request.Method, request.URL)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	if err := client.ExerciseAbandonedUploads(
		context.Background(),
		testRepository,
		content,
		40,
		16,
	); err != nil {
		t.Fatalf("abandoned-upload exercise failed: %v", err)
	}
	if started.Load() != abandonedUploadCount ||
		patched.Load() != abandonedUploadCount*3 ||
		deleted.Load() != abandonedUploadCount {
		t.Fatalf(
			"lifecycle changed: started=%d patched=%d deleted=%d",
			started.Load(),
			patched.Load(),
			deleted.Load(),
		)
	}
	result := client.Recorder().Snapshot().Operations[0]
	if result.Operation != "abandoned-upload" ||
		result.Result != string(ResultSuccess) ||
		result.TransferredByte != 80 {
		t.Fatalf("retained result changed: %#v", result)
	}
}

func TestAbandonedUploadFailureStillCancelsEveryOwnedUpload(t *testing.T) {
	content := mustContent(t, "abandoned-failure", 64)
	var server *httptest.Server
	var started atomic.Int64
	var patched atomic.Int64
	var deleted atomic.Int64
	handler := http.HandlerFunc(func(
		response http.ResponseWriter,
		request *http.Request,
	) {
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
					"/v2/%s/blobs/uploads/failing-%d",
					testRepository,
					identity,
				),
			)
			response.Header().Set("Range", "bytes=0-0")
			response.WriteHeader(http.StatusAccepted)
		case http.MethodPatch:
			current := patched.Add(1)
			if current == 2 {
				response.WriteHeader(http.StatusForbidden)
				return
			}
			_, _ = io.Copy(io.Discard, request.Body)
			response.Header().Set("Location", request.URL.String())
			response.Header().Set("Range", "bytes=0-15")
			response.WriteHeader(http.StatusAccepted)
		case http.MethodDelete:
			deleted.Add(1)
			response.WriteHeader(http.StatusAccepted)
		default:
			t.Fatalf("unexpected request: %s %s", request.Method, request.URL)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	err := client.ExerciseAbandonedUploads(
		context.Background(),
		testRepository,
		content,
		16,
		16,
	)
	if failureKind(err) != FailurePolicy ||
		started.Load() != abandonedUploadCount ||
		deleted.Load() != abandonedUploadCount {
		t.Fatalf(
			"failure cleanup changed: started=%d deleted=%d error=%v",
			started.Load(),
			deleted.Load(),
			err,
		)
	}
	result := client.Recorder().Snapshot().Operations[0]
	if result.Result != string(FailurePolicy) {
		t.Fatalf("failure result changed: %#v", result)
	}
}

func TestAbandonedUploadInvalidShapeDoesNotReachNetwork(t *testing.T) {
	var requests atomic.Int64
	server := startTLSServer(t, http.HandlerFunc(func(
		http.ResponseWriter,
		*http.Request,
	) {
		requests.Add(1)
	}))
	client := clientFor(t, server, nil)
	content := mustContent(t, "invalid-abandoned", 16)
	for _, partial := range []int64{0, 16, 17, MaxChunkBytes + 1} {
		if err := client.ExerciseAbandonedUploads(
			context.Background(),
			testRepository,
			content,
			partial,
			8,
		); failureKind(err) != FailureProtocol {
			t.Fatalf("invalid partial size accepted: %d %v", partial, err)
		}
	}
	if requests.Load() != 0 {
		t.Fatalf("invalid shape reached network: %d", requests.Load())
	}
}

func TestAbandonedUploadMalformedStartStillCleansKnownLocation(t *testing.T) {
	var server *httptest.Server
	var deleted atomic.Int64
	handler := http.HandlerFunc(func(
		response http.ResponseWriter,
		request *http.Request,
	) {
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
			response.Header().Set(
				"Location",
				"/v2/"+testRepository+"/blobs/uploads/malformed-range",
			)
			response.Header().Set("Range", "0-9")
			response.WriteHeader(http.StatusAccepted)
		case http.MethodDelete:
			deleted.Add(1)
			response.WriteHeader(http.StatusNoContent)
		default:
			t.Fatalf("unexpected request: %s", request.Method)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	err := client.ExerciseAbandonedUploads(
		context.Background(),
		testRepository,
		mustContent(t, "malformed-start", 64),
		16,
		16,
	)
	if failureKind(err) != FailureProtocol || deleted.Load() != 1 {
		t.Fatalf(
			"known malformed upload was not cleaned: deleted=%d error=%v",
			deleted.Load(),
			err,
		)
	}
}

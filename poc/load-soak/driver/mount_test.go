package driver

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sync/atomic"
	"testing"
)

const (
	mountSource      = "p/123e4567-e89b-12d3-a456-426614174000/source"
	mountDestination = "p/123e4567-e89b-12d3-a456-426614174000/destination"
)

func mountToken(
	t *testing.T,
	response http.ResponseWriter,
	request *http.Request,
) {
	t.Helper()
	username, password, ok := request.BasicAuth()
	if !ok || username != testUsername || password != testPassword {
		t.Fatal("mount token credentials changed")
	}
	expectedScopes := []string{
		"repository:" + mountDestination + ":pull,push",
		"repository:" + mountSource + ":pull",
	}
	if request.URL.Query().Get("service") != "coffer" ||
		!reflect.DeepEqual(request.URL.Query()["scope"], expectedScopes) {
		t.Fatalf("mount token scopes changed: %#v", request.URL.Query())
	}
	response.Header().Set("Content-Type", "application/json")
	_, _ = io.WriteString(response, `{"token":"`+testToken+`"}`)
}

func mountChallenge(response http.ResponseWriter, serverURL string) {
	response.Header().Set(
		"WWW-Authenticate",
		`Bearer realm="`+serverURL+`/auth/token",service="coffer",scope="repository:`+
			mountDestination+`:pull,push"`,
	)
	response.WriteHeader(http.StatusUnauthorized)
}

func TestSameProjectCrossMountUsesBothExactScopes(t *testing.T) {
	content := mustContent(t, "cross-mount", 32)
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
		if request.Method != http.MethodPost ||
			request.URL.Path != "/v2/"+mountDestination+"/blobs/uploads/" ||
			request.URL.Query().Get("mount") != digest ||
			request.URL.Query().Get("from") != mountSource {
			t.Fatalf("mount request changed: %s %s", request.Method, request.URL)
		}
		response.Header().Set("Docker-Content-Digest", digest)
		response.Header().Set(
			"Location",
			"/v2/"+mountDestination+"/blobs/"+digest,
		)
		response.WriteHeader(http.StatusCreated)
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	mounted, err := client.MountBlob(
		context.Background(),
		mountDestination,
		mountSource,
		content,
	)
	if err != nil || !mounted {
		t.Fatalf("mount failed: mounted=%t error=%v", mounted, err)
	}
	result := client.Recorder().Snapshot().Operations[0]
	if result.Operation != "blob-cross-mount" ||
		result.Result != string(ResultSuccess) ||
		result.DigestChecks != 1 {
		t.Fatalf("mount result changed: %#v", result)
	}
}

func TestCrossMountFallbackIsCancelledWithoutResidue(t *testing.T) {
	content := mustContent(t, "cross-mount-fallback", 32)
	digest, err := content.Digest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var server *httptest.Server
	var deleted atomic.Int64
	location := "/v2/" + mountDestination + "/blobs/uploads/fallback?state=opaque"
	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/auth/token" {
			mountToken(t, response, request)
			return
		}
		if request.Header.Get("Authorization") != "Bearer "+testToken {
			mountChallenge(response, server.URL)
			return
		}
		switch request.Method {
		case http.MethodPost:
			if request.URL.Query().Get("mount") != digest {
				t.Fatal("fallback digest changed")
			}
			response.Header().Set("Location", location)
			response.Header().Set("Range", "bytes=0-0")
			response.WriteHeader(http.StatusAccepted)
		case http.MethodDelete:
			if request.URL.Path !=
				"/v2/"+mountDestination+"/blobs/uploads/fallback" ||
				request.URL.Query().Get("state") != "opaque" {
				t.Fatalf("fallback cleanup changed: %s", request.URL)
			}
			deleted.Add(1)
			response.WriteHeader(http.StatusNoContent)
		default:
			t.Fatalf("unexpected method: %s", request.Method)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	mounted, err := client.MountBlob(
		context.Background(),
		mountDestination,
		mountSource,
		content,
	)
	if err != nil || mounted || deleted.Load() != 1 {
		t.Fatalf(
			"fallback cleanup failed: mounted=%t deleted=%d error=%v",
			mounted,
			deleted.Load(),
			err,
		)
	}
	result := client.Recorder().Snapshot().Operations[0]
	if result.Result != string(ResultFallback) ||
		result.DigestChecks != 0 {
		t.Fatalf("fallback result changed: %#v", result)
	}
}

func TestCrossProjectOrNonCanonicalMountFailsBeforeNetwork(t *testing.T) {
	var requests atomic.Int64
	server := startTLSServer(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		requests.Add(1)
	}))
	client := clientFor(t, server, nil)
	content := mustContent(t, "cross-project", 8)
	for _, source := range []string{
		"p/223e4567-e89b-12d3-a456-426614174000/source",
		"source",
		mountDestination,
	} {
		if _, err := client.MountBlob(
			context.Background(),
			mountDestination,
			source,
			content,
		); err == nil {
			t.Fatalf("unsafe mount accepted: %s", source)
		}
	}
	if requests.Load() != 0 {
		t.Fatalf("unsafe mount reached network: %d", requests.Load())
	}
}

func TestCrossMountFallbackCleanupFailureIsNotAccepted(t *testing.T) {
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
		if request.Method == http.MethodPost {
			response.Header().Set(
				"Location",
				"/v2/"+mountDestination+"/blobs/uploads/fallback",
			)
			response.Header().Set("Range", "0-0")
			response.WriteHeader(http.StatusAccepted)
			return
		}
		response.WriteHeader(http.StatusForbidden)
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	mounted, err := client.MountBlob(
		context.Background(),
		mountDestination,
		mountSource,
		mustContent(t, "cleanup-failure", 8),
	)
	if mounted || failureKind(err) != FailurePolicy {
		t.Fatalf("cleanup failure was accepted: mounted=%t error=%v", mounted, err)
	}
}

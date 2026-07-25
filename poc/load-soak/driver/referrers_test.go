package driver

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

const (
	testArtifactType  = "application/vnd.example.sbom.v1"
	testSubjectDigest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)

func artifactPayload(t *testing.T) []byte {
	t.Helper()
	payload, err := json.Marshal(artifactManifest{
		Annotations: map[string]string{
			"org.opencontainers.image.created": "2026-07-25T00:00:00Z",
		},
		ArtifactType: testArtifactType,
		Config: artifactDescriptor{
			Digest:    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
			MediaType: "application/vnd.oci.empty.v1+json",
			Size:      2,
		},
		Layers: []artifactDescriptor{{
			Digest:    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
			MediaType: "application/vnd.oci.empty.v1+json",
			Size:      2,
		}},
		MediaType:     OCIImageManifest,
		SchemaVersion: 2,
		Subject: &artifactDescriptor{
			Digest:    testSubjectDigest,
			MediaType: OCIImageManifest,
			Size:      512,
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	return payload
}

func referrersResponse(
	t *testing.T,
	payload []byte,
) []byte {
	t.Helper()
	_, descriptor, err := validateArtifactManifest(payload)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(descriptor)
	if err != nil {
		t.Fatal(err)
	}
	index, err := json.Marshal(referrersIndex{
		Manifests:     []json.RawMessage{raw},
		MediaType:     OCIImageIndex,
		SchemaVersion: 2,
	})
	if err != nil {
		t.Fatal(err)
	}
	return index
}

func serveArtifactPublish(
	t *testing.T,
	response http.ResponseWriter,
	request *http.Request,
	payload []byte,
	reference string,
) {
	t.Helper()
	body, err := io.ReadAll(request.Body)
	if err != nil || string(body) != string(payload) ||
		request.Header.Get("Content-Type") != OCIImageManifest {
		t.Fatalf("artifact publish changed: %v", err)
	}
	digest := expectedDigestReference(payload)
	response.Header().Set("Docker-Content-Digest", digest)
	response.Header().Set(
		"Location",
		"/v2/"+testRepository+"/manifests/"+reference,
	)
	response.WriteHeader(http.StatusCreated)
}

func TestArtifactPublishDiscoversExactNativeReferrer(t *testing.T) {
	payload := artifactPayload(t)
	index := referrersResponse(t, payload)
	var server *httptest.Server
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
		switch {
		case request.Method == http.MethodPut &&
			request.URL.Path ==
				"/v2/"+testRepository+"/manifests/sbom":
			serveArtifactPublish(t, response, request, payload, "sbom")
		case request.Method == http.MethodGet &&
			request.URL.Path ==
				"/v2/"+testRepository+"/referrers/"+testSubjectDigest:
			if request.URL.Query().Get("artifactType") != testArtifactType ||
				request.Header.Get("Accept") != OCIImageIndex {
				t.Fatal("native referrers request changed")
			}
			response.Header().Set("Content-Type", OCIImageIndex)
			response.Header().Set("OCI-Filters-Applied", "artifactType")
			_, _ = response.Write(index)
		default:
			t.Fatalf("unexpected request: %s %s", request.Method, request.URL)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	disposition, err := client.PublishArtifactAndDiscover(
		context.Background(),
		testRepository,
		"sbom",
		payload,
	)
	if err != nil || disposition != ReferrersNative {
		t.Fatalf("native discovery failed: %s %v", disposition, err)
	}
	results := client.Recorder().Snapshot().Operations
	if len(results) != 2 {
		t.Fatalf("operation count changed: %#v", results)
	}
	for _, result := range results {
		if result.Result != string(ResultSuccess) ||
			(result.Operation != "artifact" &&
				result.Operation != "manifest-publish") {
			t.Fatalf("native result changed: %#v", result)
		}
	}
}

func TestArtifactPublishCreatesAndVerifiesFallbackTag(t *testing.T) {
	payload := artifactPayload(t)
	fallbackTag := "sha256-" + strings.TrimPrefix(
		testSubjectDigest,
		"sha256:",
	)
	var storedFallback []byte
	var fallbackPuts atomic.Int64
	var server *httptest.Server
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
		switch {
		case request.Method == http.MethodPut &&
			request.URL.Path ==
				"/v2/"+testRepository+"/manifests/sbom":
			serveArtifactPublish(t, response, request, payload, "sbom")
		case request.Method == http.MethodGet &&
			request.URL.Path ==
				"/v2/"+testRepository+"/referrers/"+testSubjectDigest:
			response.WriteHeader(http.StatusNotFound)
		case request.Method == http.MethodGet &&
			request.URL.Path ==
				"/v2/"+testRepository+"/manifests/"+fallbackTag:
			if storedFallback == nil {
				response.WriteHeader(http.StatusNotFound)
				return
			}
			response.Header().Set("Content-Type", OCIImageIndex)
			response.Header().Set(
				"Docker-Content-Digest",
				expectedDigestReference(storedFallback),
			)
			_, _ = response.Write(storedFallback)
		case request.Method == http.MethodPut &&
			request.URL.Path ==
				"/v2/"+testRepository+"/manifests/"+fallbackTag:
			if request.Header.Get("Content-Type") != OCIImageIndex {
				t.Fatal("fallback media type changed")
			}
			storedFallback, _ = io.ReadAll(request.Body)
			digest := expectedDigestReference(storedFallback)
			response.Header().Set("Docker-Content-Digest", digest)
			response.Header().Set(
				"Location",
				"/v2/"+testRepository+"/manifests/"+fallbackTag,
			)
			fallbackPuts.Add(1)
			response.WriteHeader(http.StatusCreated)
		default:
			t.Fatalf("unexpected request: %s %s", request.Method, request.URL)
		}
	})
	server = startTLSServer(t, handler)
	client := clientFor(t, server, nil)

	disposition, err := client.PublishArtifactAndDiscover(
		context.Background(),
		testRepository,
		"sbom",
		payload,
	)
	if err != nil || disposition != ReferrersFallbackTag ||
		fallbackPuts.Load() != 1 {
		t.Fatalf(
			"fallback discovery failed: %s puts=%d error=%v",
			disposition,
			fallbackPuts.Load(),
			err,
		)
	}
	snapshot := client.Recorder().Snapshot()
	foundFallback := false
	for _, result := range snapshot.Operations {
		if result.Operation == "artifact" {
			foundFallback = result.Result == string(ResultFallback)
		}
	}
	if !foundFallback {
		t.Fatalf("fallback was not distinguished: %#v", snapshot.Operations)
	}
	canonical, err := MarshalCanonical(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(canonical), testSubjectDigest) ||
		strings.Contains(string(canonical), fallbackTag) ||
		strings.Contains(string(canonical), "sbom") {
		t.Fatal("retained result contains subject, tag, or reference")
	}
}

func TestArtifactReferrersMismatchAndInvalidInputFailClosed(t *testing.T) {
	payload := artifactPayload(t)
	index := referrersResponse(t, payload)
	index = []byte(strings.Replace(
		string(index),
		expectedDigestReference(payload),
		"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
		1,
	))
	var server *httptest.Server
	var requests atomic.Int64
	handler := http.HandlerFunc(func(
		response http.ResponseWriter,
		request *http.Request,
	) {
		requests.Add(1)
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
	client := clientFor(t, server, nil)

	if _, err := client.PublishArtifactAndDiscover(
		context.Background(),
		testRepository,
		"sbom",
		payload,
	); failureKind(err) != FailureDigest {
		t.Fatalf("mismatched descriptor was accepted: %v", err)
	}
	beforeInvalid := requests.Load()
	var invalid map[string]any
	if err := json.Unmarshal(payload, &invalid); err != nil {
		t.Fatal(err)
	}
	delete(invalid, "subject")
	invalidPayload, err := json.Marshal(invalid)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.PublishArtifactAndDiscover(
		context.Background(),
		testRepository,
		"invalid",
		invalidPayload,
	); failureKind(err) != FailureProtocol {
		t.Fatalf("subject-free artifact was accepted: %v", err)
	}
	if requests.Load() != beforeInvalid {
		t.Fatal("invalid artifact reached network")
	}
}

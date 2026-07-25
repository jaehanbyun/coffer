package driver

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"net/url"
	"reflect"
)

const maxReferrerDescriptors = 1024

type artifactDescriptor struct {
	Digest    string `json:"digest"`
	MediaType string `json:"mediaType"`
	Size      int64  `json:"size"`
}

type artifactManifest struct {
	Annotations   map[string]string    `json:"annotations,omitempty"`
	ArtifactType  string               `json:"artifactType"`
	Config        artifactDescriptor   `json:"config"`
	Layers        []artifactDescriptor `json:"layers"`
	MediaType     string               `json:"mediaType"`
	SchemaVersion int                  `json:"schemaVersion"`
	Subject       *artifactDescriptor  `json:"subject"`
}

type referrerDescriptor struct {
	Annotations  map[string]string `json:"annotations,omitempty"`
	ArtifactType string            `json:"artifactType"`
	Digest       string            `json:"digest"`
	MediaType    string            `json:"mediaType"`
	Size         int64             `json:"size"`
}

type referrersIndex struct {
	Manifests     []json.RawMessage `json:"manifests"`
	MediaType     string            `json:"mediaType"`
	SchemaVersion int               `json:"schemaVersion"`
}

type referrersDisposition string

const (
	ReferrersNative      referrersDisposition = "native"
	ReferrersFallbackTag referrersDisposition = "fallback-tag"
)

func validMediaType(value string) bool {
	if value == "" || len(value) > 255 || hasControl(value) {
		return false
	}
	parsed, parameters, err := mime.ParseMediaType(value)
	return err == nil && parsed == value && len(parameters) == 0
}

func validAnnotations(values map[string]string) bool {
	if len(values) > 64 {
		return false
	}
	total := 0
	for key, value := range values {
		total += len(key) + len(value)
		if key == "" || len(key) > 255 || len(value) > 4096 ||
			hasControl(key) || hasControl(value) {
			return false
		}
	}
	return total <= 64<<10
}

func validArtifactDescriptor(value artifactDescriptor) bool {
	return validMediaType(value.MediaType) &&
		sha256Pattern.MatchString(value.Digest) &&
		value.Size >= 0 && value.Size <= MaxBlobBytes
}

func validateArtifactManifest(
	payload []byte,
) (artifactManifest, referrerDescriptor, error) {
	var manifest artifactManifest
	if len(payload) == 0 || int64(len(payload)) > MaxManifestBytes {
		return manifest, referrerDescriptor{}, newFailure(FailureProtocol)
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&manifest); err != nil ||
		decoder.Decode(&struct{}{}) != io.EOF ||
		manifest.SchemaVersion != 2 ||
		manifest.MediaType != OCIImageManifest ||
		!validMediaType(manifest.ArtifactType) ||
		manifest.Subject == nil ||
		!validArtifactDescriptor(*manifest.Subject) ||
		!validArtifactDescriptor(manifest.Config) ||
		len(manifest.Layers) == 0 || len(manifest.Layers) > 64 ||
		!validAnnotations(manifest.Annotations) {
		return artifactManifest{}, referrerDescriptor{},
			newFailure(FailureProtocol)
	}
	for _, layer := range manifest.Layers {
		if !validArtifactDescriptor(layer) {
			return artifactManifest{}, referrerDescriptor{},
				newFailure(FailureProtocol)
		}
	}
	return manifest, referrerDescriptor{
		Annotations:  manifest.Annotations,
		ArtifactType: manifest.ArtifactType,
		Digest:       expectedDigestReference(payload),
		MediaType:    OCIImageManifest,
		Size:         int64(len(payload)),
	}, nil
}

func (c *Client) referrersURL(
	repository string,
	subjectDigest string,
	artifactType string,
) (*url.URL, error) {
	if _, err := repositoryScope(repository); err != nil {
		return nil, err
	}
	if !sha256Pattern.MatchString(subjectDigest) ||
		!validMediaType(artifactType) {
		return nil, newFailure(FailureProtocol)
	}
	target := c.baseURL.ResolveReference(&url.URL{
		Path: "/v2/" + repository + "/referrers/" + subjectDigest,
	})
	query := target.Query()
	query.Set("artifactType", artifactType)
	target.RawQuery = query.Encode()
	return target, nil
}

func decodeReferrersIndex(
	payload []byte,
	expected referrerDescriptor,
) (referrersIndex, bool, error) {
	var index referrersIndex
	if len(payload) == 0 || int64(len(payload)) > MaxManifestBytes {
		return index, false, newFailure(FailureProtocol)
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&index); err != nil ||
		decoder.Decode(&struct{}{}) != io.EOF ||
		index.SchemaVersion != 2 ||
		index.MediaType != OCIImageIndex ||
		index.Manifests == nil ||
		len(index.Manifests) > maxReferrerDescriptors {
		return referrersIndex{}, false, newFailure(FailureProtocol)
	}
	found := false
	for _, raw := range index.Manifests {
		var descriptor referrerDescriptor
		descriptorDecoder := json.NewDecoder(bytes.NewReader(raw))
		descriptorDecoder.DisallowUnknownFields()
		if err := descriptorDecoder.Decode(&descriptor); err != nil ||
			descriptorDecoder.Decode(&struct{}{}) != io.EOF ||
			!validArtifactDescriptor(artifactDescriptor{
				Digest:    descriptor.Digest,
				MediaType: descriptor.MediaType,
				Size:      descriptor.Size,
			}) ||
			!validMediaType(descriptor.ArtifactType) ||
			!validAnnotations(descriptor.Annotations) {
			return referrersIndex{}, false, newFailure(FailureProtocol)
		}
		if descriptor.Digest == expected.Digest {
			if found || !reflect.DeepEqual(descriptor, expected) {
				return referrersIndex{}, false, newFailure(FailureDigest)
			}
			found = true
		}
	}
	return index, found, nil
}

func (c *Client) getReferrersIndex(
	ctx context.Context,
	scope string,
	target *url.URL,
	expected referrerDescriptor,
	requireFilter bool,
) (referrersIndex, bool, bool, int, error) {
	result, err := c.perform(
		ctx,
		scope,
		func(authorization string) (*http.Request, *byteCounter, error) {
			request, requestErr := newRequest(
				ctx,
				http.MethodGet,
				target,
				nil,
				0,
				authorization,
			)
			if requestErr == nil {
				request.Header.Set("Accept", OCIImageIndex)
			}
			return request, nil, requestErr
		},
		map[int]bool{
			http.StatusOK:       true,
			http.StatusNotFound: true,
		},
		true,
	)
	if err != nil {
		return referrersIndex{}, false, false, result.attempts, err
	}
	if result.response.StatusCode == http.StatusNotFound {
		err = consumeBounded(result.response.Body, c.maxResponseBytes)
		return referrersIndex{}, false, false, result.attempts, err
	}
	if result.response.Header.Get("Content-Type") != OCIImageIndex ||
		(requireFilter &&
			result.response.Header.Get("OCI-Filters-Applied") !=
				"artifactType") ||
		(!requireFilter &&
			result.response.Header.Get("OCI-Filters-Applied") != "") {
		_ = consumeBounded(result.response.Body, c.maxResponseBytes)
		return referrersIndex{}, false, true, result.attempts,
			newFailure(FailureProtocol)
	}
	payload, err := readBounded(result.response.Body, MaxManifestBytes)
	if err != nil {
		return referrersIndex{}, false, true, result.attempts, err
	}
	if !requireFilter &&
		result.response.Header.Get("Docker-Content-Digest") !=
			expectedDigestReference(payload) {
		return referrersIndex{}, false, true, result.attempts,
			newFailure(FailureDigest)
	}
	index, found, err := decodeReferrersIndex(payload, expected)
	return index, found, true, result.attempts, err
}

func fallbackReferrersTag(subjectDigest string) (string, error) {
	if !sha256Pattern.MatchString(subjectDigest) {
		return "", newFailure(FailureProtocol)
	}
	return "sha256-" + subjectDigest[len("sha256:"):], nil
}

func encodeReferrersIndex(
	index referrersIndex,
	expected referrerDescriptor,
	found bool,
) ([]byte, error) {
	if !found {
		raw, err := json.Marshal(expected)
		if err != nil {
			return nil, newFailure(FailureProtocol)
		}
		index.Manifests = append(index.Manifests, raw)
	}
	if len(index.Manifests) > maxReferrerDescriptors {
		return nil, newFailure(FailureProtocol)
	}
	payload, err := json.Marshal(index)
	if err != nil || int64(len(payload)) > MaxManifestBytes {
		return nil, newFailure(FailureProtocol)
	}
	return payload, nil
}

func (c *Client) PublishArtifactAndDiscover(
	ctx context.Context,
	repository string,
	reference string,
	payload []byte,
) (referrersDisposition, error) {
	started := c.now()
	resultKind := FailureProtocol
	attempts := 0
	digestChecks := uint64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "artifact",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       attempts,
			digestChecks:   digestChecks,
			logicalSuccess: success,
		})
	}()
	manifest, expected, err := validateArtifactManifest(payload)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	artifactDigest, err := c.PublishManifest(
		ctx,
		repository,
		reference,
		OCIImageManifest,
		payload,
	)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	if artifactDigest != expected.Digest {
		resultKind = FailureDigest
		return "", newFailure(FailureDigest)
	}
	scope, err := repositoryScope(repository)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	nativeTarget, err := c.referrersURL(
		repository,
		manifest.Subject.Digest,
		manifest.ArtifactType,
	)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	_, found, exists, requestAttempts, err := c.getReferrersIndex(
		ctx,
		scope,
		nativeTarget,
		expected,
		true,
	)
	attempts += requestAttempts
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	if exists {
		if !found {
			resultKind = FailureDigest
			return "", newFailure(FailureDigest)
		}
		digestChecks = 1
		success = true
		resultKind = ResultSuccess
		return ReferrersNative, nil
	}

	fallbackTag, err := fallbackReferrersTag(manifest.Subject.Digest)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	fallbackTarget, err := c.manifestURL(repository, fallbackTag)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	index, found, exists, requestAttempts, err := c.getReferrersIndex(
		ctx,
		scope,
		fallbackTarget,
		expected,
		false,
	)
	attempts += requestAttempts
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	if !exists {
		index = referrersIndex{
			Manifests:     []json.RawMessage{},
			MediaType:     OCIImageIndex,
			SchemaVersion: 2,
		}
	}
	if !found {
		fallbackPayload, encodeErr := encodeReferrersIndex(
			index,
			expected,
			false,
		)
		if encodeErr != nil {
			resultKind = failureKind(encodeErr)
			return "", encodeErr
		}
		if _, err = c.PublishManifest(
			ctx,
			repository,
			fallbackTag,
			OCIImageIndex,
			fallbackPayload,
		); err != nil {
			resultKind = failureKind(err)
			return "", err
		}
		_, found, exists, requestAttempts, err = c.getReferrersIndex(
			ctx,
			scope,
			fallbackTarget,
			expected,
			false,
		)
		attempts += requestAttempts
		if err != nil {
			resultKind = failureKind(err)
			return "", err
		}
	}
	if !exists || !found {
		resultKind = FailureDigest
		return "", newFailure(FailureDigest)
	}
	digestChecks = 1
	resultKind = ResultFallback
	return ReferrersFallbackTag, nil
}

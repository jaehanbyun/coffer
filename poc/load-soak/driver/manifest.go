package driver

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
)

const (
	OCIImageManifest = "application/vnd.oci.image.manifest.v1+json"
	OCIImageIndex    = "application/vnd.oci.image.index.v1+json"
	MaxManifestBytes = int64(4 << 20)
)

var tagPattern = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$`)

func validateManifest(
	reference string,
	mediaType string,
	payload []byte,
) (string, error) {
	if !tagPattern.MatchString(reference) &&
		!sha256Pattern.MatchString(reference) {
		return "", newFailure(FailureProtocol)
	}
	if mediaType != OCIImageManifest && mediaType != OCIImageIndex {
		return "", newFailure(FailureProtocol)
	}
	if len(payload) == 0 || int64(len(payload)) > MaxManifestBytes ||
		!json.Valid(payload) {
		return "", newFailure(FailureProtocol)
	}
	var envelope struct {
		MediaType     string `json:"mediaType"`
		SchemaVersion int    `json:"schemaVersion"`
	}
	if err := json.Unmarshal(payload, &envelope); err != nil ||
		envelope.SchemaVersion != 2 || envelope.MediaType != mediaType {
		return "", newFailure(FailureProtocol)
	}
	digest := sha256.Sum256(payload)
	canonical := "sha256:" + hex.EncodeToString(digest[:])
	if sha256Pattern.MatchString(reference) && reference != canonical {
		return "", newFailure(FailureDigest)
	}
	return canonical, nil
}

func (c *Client) manifestURL(
	repository string,
	reference string,
) (*url.URL, error) {
	if _, err := repositoryScope(repository); err != nil {
		return nil, err
	}
	if !tagPattern.MatchString(reference) &&
		!sha256Pattern.MatchString(reference) {
		return nil, newFailure(FailureProtocol)
	}
	return c.baseURL.ResolveReference(&url.URL{
		Path: "/v2/" + repository + "/manifests/" + reference,
	}), nil
}

func (c *Client) blobURL(repository string, digest string) (*url.URL, error) {
	if _, err := repositoryScope(repository); err != nil {
		return nil, err
	}
	if !sha256Pattern.MatchString(digest) {
		return nil, newFailure(FailureProtocol)
	}
	return c.baseURL.ResolveReference(&url.URL{
		Path: "/v2/" + repository + "/blobs/" + digest,
	}), nil
}

func (c *Client) validateManifestLocation(
	repository string,
	reference string,
	value string,
) error {
	if len(value) == 0 || len(value) > maxChallengeBytes {
		return newFailure(FailureProtocol)
	}
	location, err := url.Parse(value)
	if err != nil {
		return newFailure(FailureProtocol)
	}
	location = c.baseURL.ResolveReference(location)
	expectedPath := "/v2/" + repository + "/manifests/" + reference
	if !sameOrigin(c.baseURL, location) || location.User != nil ||
		location.Fragment != "" || location.RawQuery != "" ||
		location.Path != expectedPath {
		return newFailure(FailureProtocol)
	}
	return nil
}

func (c *Client) PublishManifest(
	ctx context.Context,
	repository string,
	reference string,
	mediaType string,
	payload []byte,
) (string, error) {
	started := c.now()
	resultKind := FailureProtocol
	attempts := 0
	transferred := int64(0)
	digestChecks := uint64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "manifest-publish",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       attempts,
			transferred:    transferred,
			digestChecks:   digestChecks,
			logicalSuccess: success,
		})
	}()
	digest, err := validateManifest(reference, mediaType, payload)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	payload = append([]byte(nil), payload...)
	scope, err := repositoryScope(repository)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	target, err := c.manifestURL(repository, reference)
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	result, err := c.perform(
		ctx,
		scope,
		func(authorization string) (*http.Request, *byteCounter, error) {
			counter := &byteCounter{}
			body := &countedReader{
				reader:  bytes.NewReader(payload),
				counter: counter,
			}
			request, requestErr := newRequest(
				ctx,
				http.MethodPut,
				target,
				body,
				int64(len(payload)),
				authorization,
			)
			if requestErr == nil {
				request.Header.Set("Content-Type", mediaType)
			}
			return request, counter, requestErr
		},
		map[int]bool{http.StatusCreated: true},
		true,
	)
	attempts = result.attempts
	transferred = result.transferred
	if err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	if err := consumeBounded(result.response.Body, c.maxResponseBytes); err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	if result.response.Header.Get("Docker-Content-Digest") != digest {
		resultKind = FailureDigest
		return "", newFailure(FailureDigest)
	}
	if err := c.validateManifestLocation(
		repository,
		reference,
		result.response.Header.Get("Location"),
	); err != nil {
		resultKind = failureKind(err)
		return "", err
	}
	digestChecks = 1
	success = true
	resultKind = ResultSuccess
	return digest, nil
}

func (c *Client) HeadManifest(
	ctx context.Context,
	repository string,
	reference string,
	expectedMediaType string,
	expectedDigest string,
	expectedSize int64,
) error {
	return c.readManifest(
		ctx,
		http.MethodHead,
		repository,
		reference,
		expectedMediaType,
		expectedDigest,
		expectedSize,
		nil,
	)
}

func (c *Client) GetManifest(
	ctx context.Context,
	repository string,
	reference string,
	expectedMediaType string,
	expectedPayload []byte,
) error {
	digest, err := validateManifest(
		expectedDigestReference(expectedPayload),
		expectedMediaType,
		expectedPayload,
	)
	if err != nil {
		c.recorder.observe(observation{
			operation: "manifest-read",
			result:    failureKind(err),
		})
		return err
	}
	expectedPayload = append([]byte(nil), expectedPayload...)
	return c.readManifest(
		ctx,
		http.MethodGet,
		repository,
		reference,
		expectedMediaType,
		digest,
		int64(len(expectedPayload)),
		expectedPayload,
	)
}

func expectedDigestReference(payload []byte) string {
	digest := sha256.Sum256(payload)
	return "sha256:" + hex.EncodeToString(digest[:])
}

func (c *Client) readManifest(
	ctx context.Context,
	method string,
	repository string,
	reference string,
	expectedMediaType string,
	expectedDigest string,
	expectedSize int64,
	expectedPayload []byte,
) error {
	started := c.now()
	resultKind := FailureProtocol
	attempts := 0
	transferred := int64(0)
	digestChecks := uint64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "manifest-read",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       attempts,
			transferred:    transferred,
			digestChecks:   digestChecks,
			logicalSuccess: success,
		})
	}()
	if method != http.MethodHead && method != http.MethodGet ||
		(expectedMediaType != OCIImageManifest &&
			expectedMediaType != OCIImageIndex) ||
		!sha256Pattern.MatchString(expectedDigest) ||
		expectedSize < 1 || expectedSize > MaxManifestBytes ||
		(method == http.MethodGet &&
			int64(len(expectedPayload)) != expectedSize) ||
		(sha256Pattern.MatchString(reference) &&
			reference != expectedDigest) {
		return newFailure(FailureProtocol)
	}
	scope, err := repositoryScope(repository)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	target, err := c.manifestURL(repository, reference)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	result, err := c.perform(
		ctx,
		scope,
		func(authorization string) (*http.Request, *byteCounter, error) {
			request, requestErr := newRequest(
				ctx,
				method,
				target,
				nil,
				0,
				authorization,
			)
			if requestErr == nil {
				request.Header.Set("Accept", expectedMediaType)
			}
			return request, nil, requestErr
		},
		map[int]bool{http.StatusOK: true},
		true,
	)
	attempts = result.attempts
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	if result.response.Header.Get("Docker-Content-Digest") != expectedDigest {
		_ = consumeBounded(result.response.Body, c.maxResponseBytes)
		resultKind = FailureDigest
		return newFailure(FailureDigest)
	}
	if result.response.Header.Get("Content-Type") != expectedMediaType ||
		result.response.ContentLength != expectedSize {
		_ = consumeBounded(result.response.Body, c.maxResponseBytes)
		resultKind = FailureProtocol
		return newFailure(FailureProtocol)
	}
	if method == http.MethodHead {
		if err := consumeBounded(result.response.Body, c.maxResponseBytes); err != nil {
			resultKind = failureKind(err)
			return err
		}
	} else {
		transferred, err = compareExact(
			ctx,
			result.response.Body,
			bytes.NewReader(expectedPayload),
			expectedSize,
		)
		if err != nil {
			resultKind = failureKind(err)
			return err
		}
	}
	digestChecks = 1
	success = true
	resultKind = ResultSuccess
	return nil
}

func (c *Client) HeadBlob(
	ctx context.Context,
	repository string,
	content *Content,
) error {
	started := c.now()
	resultKind := FailureProtocol
	attempts := 0
	digestChecks := uint64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "blob-read",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       attempts,
			digestChecks:   digestChecks,
			logicalSuccess: success,
		})
	}()
	if content == nil {
		return newFailure(FailureProtocol)
	}
	digest, err := content.Digest(ctx)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	scope, err := repositoryScope(repository)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	target, err := c.blobURL(repository, digest)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	result, err := c.perform(
		ctx,
		scope,
		func(authorization string) (*http.Request, *byteCounter, error) {
			request, requestErr := newRequest(
				ctx,
				http.MethodHead,
				target,
				nil,
				0,
				authorization,
			)
			return request, nil, requestErr
		},
		map[int]bool{http.StatusOK: true},
		true,
	)
	attempts = result.attempts
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	if err := consumeBounded(result.response.Body, c.maxResponseBytes); err != nil {
		resultKind = failureKind(err)
		return err
	}
	if result.response.Header.Get("Docker-Content-Digest") != digest {
		resultKind = FailureDigest
		return newFailure(FailureDigest)
	}
	if result.response.ContentLength != content.Size() {
		resultKind = FailureProtocol
		return newFailure(FailureProtocol)
	}
	digestChecks = 1
	success = true
	resultKind = ResultSuccess
	return nil
}

func (c *Client) ReadBlob(
	ctx context.Context,
	repository string,
	content *Content,
	offset int64,
	length int64,
) error {
	started := c.now()
	resultKind := FailureProtocol
	attempts := 0
	transferred := int64(0)
	digestChecks := uint64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "blob-read",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       attempts,
			transferred:    transferred,
			digestChecks:   digestChecks,
			logicalSuccess: success,
		})
	}()
	if content == nil || offset < 0 || length < 0 ||
		offset > content.Size() || length > content.Size()-offset ||
		(length == 0 && content.Size() != 0) {
		return newFailure(FailureProtocol)
	}
	expected, err := content.NewRangeReader(offset, length)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	digest, err := content.Digest(ctx)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	scope, err := repositoryScope(repository)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	target, err := c.blobURL(repository, digest)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	full := offset == 0 && length == content.Size()
	status := http.StatusPartialContent
	if full {
		status = http.StatusOK
	}
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
			if requestErr == nil && !full {
				request.Header.Set(
					"Range",
					fmt.Sprintf("bytes=%d-%d", offset, offset+length-1),
				)
			}
			return request, nil, requestErr
		},
		map[int]bool{status: true},
		true,
	)
	attempts = result.attempts
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	if result.response.Header.Get("Docker-Content-Digest") != digest {
		_ = consumeBounded(result.response.Body, c.maxResponseBytes)
		resultKind = FailureDigest
		return newFailure(FailureDigest)
	}
	if result.response.ContentLength != length {
		_ = consumeBounded(result.response.Body, c.maxResponseBytes)
		resultKind = FailureProtocol
		return newFailure(FailureProtocol)
	}
	if full {
		if result.response.Header.Get("Content-Range") != "" {
			_ = consumeBounded(result.response.Body, c.maxResponseBytes)
			resultKind = FailureProtocol
			return newFailure(FailureProtocol)
		}
	} else {
		expectedRange := fmt.Sprintf(
			"bytes %d-%d/%d",
			offset,
			offset+length-1,
			content.Size(),
		)
		if result.response.Header.Get("Content-Range") != expectedRange {
			_ = consumeBounded(result.response.Body, c.maxResponseBytes)
			resultKind = FailureProtocol
			return newFailure(FailureProtocol)
		}
	}
	transferred, err = compareExact(
		ctx,
		result.response.Body,
		expected,
		length,
	)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	digestChecks = 1
	success = true
	resultKind = ResultSuccess
	return nil
}

func compareExact(
	ctx context.Context,
	actual io.ReadCloser,
	expected io.Reader,
	length int64,
) (int64, error) {
	defer actual.Close()
	actualBuffer := make([]byte, 32*1024)
	expectedBuffer := make([]byte, len(actualBuffer))
	remaining := length
	transferred := int64(0)
	for remaining > 0 {
		if err := ctx.Err(); err != nil {
			return transferred, newFailure(FailureCancelled)
		}
		size := int64(len(actualBuffer))
		if remaining < size {
			size = remaining
		}
		actualCount, actualErr := io.ReadFull(actual, actualBuffer[:size])
		transferred += int64(actualCount)
		if actualErr != nil {
			if ctx.Err() != nil {
				return transferred, newFailure(FailureCancelled)
			}
			return transferred, newFailure(FailureDigest)
		}
		expectedCount, expectedErr := io.ReadFull(
			expected,
			expectedBuffer[:size],
		)
		if expectedErr != nil || expectedCount != actualCount ||
			!bytes.Equal(
				actualBuffer[:actualCount],
				expectedBuffer[:expectedCount],
			) {
			return transferred, newFailure(FailureDigest)
		}
		remaining -= int64(actualCount)
	}
	var extra [1]byte
	if count, err := actual.Read(extra[:]); count != 0 || !errors.Is(err, io.EOF) {
		if ctx.Err() != nil {
			return transferred, newFailure(FailureCancelled)
		}
		return transferred, newFailure(FailureDigest)
	}
	if count, err := expected.Read(extra[:]); count != 0 || !errors.Is(err, io.EOF) {
		return transferred, newFailure(FailureProtocol)
	}
	return transferred, nil
}

package driver

import (
	"context"
	"net/http"
	"regexp"
	"strings"
)

var projectIDPattern = regexp.MustCompile(
	`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`,
)

func repositoryProject(repository string) (string, error) {
	if _, err := repositoryScope(repository); err != nil {
		return "", err
	}
	parts := strings.Split(repository, "/")
	if len(parts) < 3 || parts[0] != "p" ||
		!projectIDPattern.MatchString(parts[1]) {
		return "", newFailure(FailureProtocol)
	}
	return parts[1], nil
}

func (c *Client) cancelUpload(
	ctx context.Context,
	challengeScope string,
	tokenScopes []string,
	location string,
	repository string,
) (int, error) {
	target, err := c.resolveUploadLocation(repository, location)
	if err != nil {
		return 0, err
	}
	result, err := c.performScopes(
		ctx,
		challengeScope,
		tokenScopes,
		func(authorization string) (*http.Request, *byteCounter, error) {
			request, requestErr := newRequest(
				ctx,
				http.MethodDelete,
				target,
				nil,
				0,
				authorization,
			)
			return request, nil, requestErr
		},
		map[int]bool{
			http.StatusAccepted:  true,
			http.StatusNoContent: true,
		},
		true,
	)
	if err != nil {
		return result.attempts, err
	}
	return result.attempts, consumeBounded(
		result.response.Body,
		c.maxResponseBytes,
	)
}

func (c *Client) MountBlob(
	ctx context.Context,
	destinationRepository string,
	sourceRepository string,
	content *Content,
) (bool, error) {
	started := c.now()
	resultKind := FailureProtocol
	attempts := 0
	digestChecks := uint64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "blob-cross-mount",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       attempts,
			digestChecks:   digestChecks,
			logicalSuccess: success,
		})
	}()
	if content == nil || destinationRepository == sourceRepository {
		return false, newFailure(FailureProtocol)
	}
	destinationProject, err := repositoryProject(destinationRepository)
	if err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	sourceProject, err := repositoryProject(sourceRepository)
	if err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	if destinationProject != sourceProject {
		return false, newFailure(FailurePolicy)
	}
	digest, err := content.Digest(ctx)
	if err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	destinationScope, err := repositoryScope(destinationRepository)
	if err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	sourceScope := "repository:" + sourceRepository + ":pull"
	tokenScopes := []string{destinationScope, sourceScope}
	target, err := c.uploadURL(destinationRepository)
	if err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	query := target.Query()
	query.Set("mount", digest)
	query.Set("from", sourceRepository)
	target.RawQuery = query.Encode()
	result, err := c.performScopes(
		ctx,
		destinationScope,
		tokenScopes,
		func(authorization string) (*http.Request, *byteCounter, error) {
			request, requestErr := newRequest(
				ctx,
				http.MethodPost,
				target,
				nil,
				0,
				authorization,
			)
			return request, nil, requestErr
		},
		map[int]bool{
			http.StatusCreated:  true,
			http.StatusAccepted: true,
		},
		false,
	)
	attempts = result.attempts
	if err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	if err := consumeBounded(result.response.Body, c.maxResponseBytes); err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	if result.response.StatusCode == http.StatusCreated {
		if result.response.Header.Get("Docker-Content-Digest") != digest {
			resultKind = FailureDigest
			return false, newFailure(FailureDigest)
		}
		if err := c.validateBlobLocation(
			destinationRepository,
			digest,
			result.response.Header.Get("Location"),
		); err != nil {
			resultKind = failureKind(err)
			return false, err
		}
		digestChecks = 1
		success = true
		resultKind = ResultSuccess
		return true, nil
	}
	if _, err := matchUploadRange(
		result.response.Header.Get("Range"),
		0,
	); err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	cancelAttempts, err := c.cancelUpload(
		ctx,
		destinationScope,
		tokenScopes,
		result.response.Header.Get("Location"),
		destinationRepository,
	)
	attempts += cancelAttempts
	if err != nil {
		resultKind = failureKind(err)
		return false, err
	}
	resultKind = ResultFallback
	return false, nil
}

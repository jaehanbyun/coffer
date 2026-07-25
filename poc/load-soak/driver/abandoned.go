package driver

import (
	"context"
	"io"
	"net/http"
	"net/url"
	"time"
)

const abandonedUploadCount = 2

type ownedPartialUpload struct {
	location *url.URL
}

func (c *Client) startPartialUpload(
	ctx context.Context,
	scope string,
	repository string,
) (ownedPartialUpload, int, error) {
	target, err := c.uploadURL(repository)
	if err != nil {
		return ownedPartialUpload{}, 0, err
	}
	result, err := c.perform(
		ctx,
		scope,
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
		map[int]bool{http.StatusAccepted: true},
		false,
	)
	if err != nil {
		return ownedPartialUpload{}, result.attempts, err
	}
	location, locationErr := c.resolveUploadLocation(
		repository,
		result.response.Header.Get("Location"),
	)
	upload := ownedPartialUpload{location: location}
	var rangeErr error
	if _, err := matchUploadRange(
		result.response.Header.Get("Range"),
		0,
	); err != nil {
		rangeErr = err
	}
	if err := consumeBounded(
		result.response.Body,
		c.maxResponseBytes,
	); err != nil {
		return upload, result.attempts, err
	}
	if locationErr != nil {
		return ownedPartialUpload{}, result.attempts, locationErr
	}
	if rangeErr != nil {
		return upload, result.attempts, rangeErr
	}
	return upload, result.attempts, nil
}

func (c *Client) cancelOwnedUploads(
	scope string,
	repository string,
	uploads []ownedPartialUpload,
) (int, error) {
	cleanupContext, cancel := context.WithTimeout(
		context.Background(),
		30*time.Second,
	)
	defer cancel()
	attempts := 0
	var cleanupError error
	for _, upload := range uploads {
		currentAttempts, err := c.cancelUpload(
			cleanupContext,
			scope,
			[]string{scope},
			upload.location.String(),
			repository,
		)
		attempts += currentAttempts
		if err != nil {
			cleanupError = err
		}
	}
	return attempts, cleanupError
}

func (c *Client) ExerciseAbandonedUploads(
	ctx context.Context,
	repository string,
	content *Content,
	partialBytes int64,
	chunkBytes int64,
) error {
	started := c.now()
	resultKind := FailureProtocol
	attempts := 0
	transferred := int64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "abandoned-upload",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       attempts,
			transferred:    transferred,
			logicalSuccess: success,
		})
	}()
	if content == nil || partialBytes < 1 ||
		partialBytes > MaxBlobBytes ||
		chunkBytes < 1 || chunkBytes > MaxChunkBytes ||
		partialBytes >= content.Size() {
		return newFailure(FailureProtocol)
	}
	scope, err := repositoryScope(repository)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	uploads := make([]ownedPartialUpload, 0, abandonedUploadCount)
	var operationError error
uploadLoop:
	for index := 0; index < abandonedUploadCount; index++ {
		upload, startAttempts, startErr := c.startPartialUpload(
			ctx,
			scope,
			repository,
		)
		attempts += startAttempts
		duplicate := false
		if upload.location != nil {
			for _, existing := range uploads {
				if existing.location.String() == upload.location.String() {
					duplicate = true
					break
				}
			}
			if !duplicate {
				uploads = append(uploads, upload)
			}
		}
		if startErr != nil {
			operationError = startErr
			break
		}
		if duplicate {
			operationError = newFailure(FailureProtocol)
			break
		}
		offset := int64(0)
		currentLocation := upload.location
		for offset < partialBytes {
			length := chunkBytes
			if remaining := partialBytes - offset; remaining < length {
				length = remaining
			}
			reader, rangeErr := content.NewRangeReader(offset, length)
			if rangeErr != nil {
				operationError = rangeErr
				break uploadLoop
			}
			chunk, readErr := io.ReadAll(reader)
			if readErr != nil || int64(len(chunk)) != length {
				operationError = newFailure(FailureProtocol)
				break uploadLoop
			}
			result, patchErr := c.uploadChunk(
				ctx,
				scope,
				repository,
				currentLocation,
				chunk,
				offset,
			)
			attempts += result.attempts
			transferred += result.transferred
			if patchErr != nil {
				operationError = patchErr
				break uploadLoop
			}
			currentLocation = result.location
			uploads[len(uploads)-1].location = currentLocation
			offset += length
		}
	}
	cleanupAttempts, cleanupError := c.cancelOwnedUploads(
		scope,
		repository,
		uploads,
	)
	attempts += cleanupAttempts
	if cleanupError != nil {
		resultKind = failureKind(cleanupError)
		return cleanupError
	}
	if operationError != nil {
		resultKind = failureKind(operationError)
		return operationError
	}
	if len(uploads) != abandonedUploadCount {
		return newFailure(FailureProtocol)
	}
	success = true
	resultKind = ResultSuccess
	return nil
}

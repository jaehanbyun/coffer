package driver

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	defaultAttempts       = 4
	defaultResponseBytes  = int64(1 << 20)
	maxChallengeBytes     = 4096
	maxTokenResponseBytes = int64(64 << 10)
	maxTokenBytes         = 8192
)

type Failure string

const (
	ResultSuccess         Failure = "success"
	FailureAuthentication Failure = "authentication"
	FailureCancelled      Failure = "cancelled"
	FailureDependency     Failure = "dependency"
	FailureDigest         Failure = "digest-mismatch"
	FailureNotFound       Failure = "not-found"
	FailurePolicy         Failure = "policy"
	FailureProtocol       Failure = "protocol"
	FailureQuota          Failure = "quota"
	FailureRetryExhausted Failure = "retry-exhausted"
)

type DriverError struct {
	Kind Failure
}

func (e *DriverError) Error() string {
	return "raw OCI driver: " + string(e.Kind)
}

func newFailure(kind Failure) *DriverError {
	return &DriverError{Kind: kind}
}

func failureKind(err error) Failure {
	var failure *DriverError
	if errors.As(err, &failure) {
		return failure.Kind
	}
	return FailureProtocol
}

type CredentialProvider func(context.Context) (username string, password string, err error)

type Config struct {
	BaseURL            string
	CredentialProvider CredentialProvider
	MaxAttempts        int
	MaxResponseBytes   int64
	Recorder           *Recorder
	RequestTimeout     time.Duration
	RetryDelayCap      time.Duration
	RootCAs            *x509.CertPool
}

type Client struct {
	baseURL            *url.URL
	credentialProvider CredentialProvider
	httpClient         *http.Client
	maxAttempts        int
	maxResponseBytes   int64
	now                func() time.Time
	recorder           *Recorder
	retryDelayCap      time.Duration
	sleep              func(context.Context, time.Duration) error
	tokenMu            sync.Mutex
	tokens             map[string]string
}

var repositoryPattern = regexp.MustCompile(
	`^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$`,
)

func NewClient(config Config) (*Client, error) {
	baseURL, err := url.Parse(config.BaseURL)
	if err != nil || baseURL.Scheme != "https" || baseURL.Host == "" ||
		baseURL.User != nil || (baseURL.Path != "" && baseURL.Path != "/") ||
		baseURL.Opaque != "" || baseURL.RawPath != "" || baseURL.RawQuery != "" ||
		baseURL.Fragment != "" || config.RootCAs == nil ||
		config.CredentialProvider == nil {
		return nil, newFailure(FailureProtocol)
	}
	baseURL.Path = ""
	attempts := config.MaxAttempts
	if attempts == 0 {
		attempts = defaultAttempts
	}
	responseBytes := config.MaxResponseBytes
	if responseBytes == 0 {
		responseBytes = defaultResponseBytes
	}
	timeout := config.RequestTimeout
	if timeout == 0 {
		timeout = 30 * time.Second
	}
	retryCap := config.RetryDelayCap
	if retryCap == 0 {
		retryCap = time.Second
	}
	if attempts < 1 || attempts > 8 || responseBytes < 1 ||
		responseBytes > 16<<20 || timeout <= 0 || timeout > 10*time.Minute ||
		retryCap < 0 || retryCap > 30*time.Second {
		return nil, newFailure(FailureProtocol)
	}
	transport := &http.Transport{
		ForceAttemptHTTP2: true,
		TLSClientConfig: &tls.Config{
			MinVersion: tls.VersionTLS12,
			RootCAs:    config.RootCAs.Clone(),
		},
	}
	recorder := config.Recorder
	if recorder == nil {
		recorder = NewRecorder()
	}
	client := &Client{
		baseURL:            baseURL,
		credentialProvider: config.CredentialProvider,
		httpClient: &http.Client{
			Transport: transport,
			Timeout:   timeout,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		maxAttempts:      attempts,
		maxResponseBytes: responseBytes,
		now:              time.Now,
		recorder:         recorder,
		retryDelayCap:    retryCap,
		sleep:            sleepContext,
		tokens:           make(map[string]string),
	}
	return client, nil
}

func (c *Client) Recorder() *Recorder {
	return c.recorder
}

func (c *Client) CloseIdleConnections() {
	c.httpClient.CloseIdleConnections()
}

func sleepContext(ctx context.Context, duration time.Duration) error {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

type byteCounter struct {
	value atomic.Int64
}

type countedReader struct {
	reader  io.Reader
	counter *byteCounter
}

func (r *countedReader) Read(destination []byte) (int, error) {
	count, err := r.reader.Read(destination)
	r.counter.value.Add(int64(count))
	return count, err
}

type requestFactory func(authorization string) (*http.Request, *byteCounter, error)

type requestResult struct {
	attempts    int
	response    *http.Response
	transferred int64
}

func (c *Client) perform(
	ctx context.Context,
	scope string,
	factory requestFactory,
	accepted map[int]bool,
	allowRetry bool,
) (requestResult, error) {
	var result requestResult
	authorization := c.cachedAuthorization(scope)
	challengeUsed := false
	for attempt := 1; attempt <= c.maxAttempts; attempt++ {
		if err := ctx.Err(); err != nil {
			return result, newFailure(FailureCancelled)
		}
		request, counter, err := factory(authorization)
		if err != nil {
			return result, newFailure(FailureProtocol)
		}
		response, requestErr := c.httpClient.Do(request)
		result.attempts = attempt
		if counter != nil {
			result.transferred += counter.value.Load()
		}
		if requestErr != nil {
			if ctx.Err() != nil {
				return result, newFailure(FailureCancelled)
			}
			if !allowRetry || attempt == c.maxAttempts {
				return result, newFailure(FailureDependency)
			}
			if err := c.sleep(ctx, 0); err != nil {
				return result, newFailure(FailureCancelled)
			}
			continue
		}
		if accepted[response.StatusCode] {
			result.response = response
			return result, nil
		}
		if response.StatusCode == http.StatusUnauthorized && !challengeUsed {
			if err := consumeBounded(response.Body, c.maxResponseBytes); err != nil {
				return result, err
			}
			token, err := c.acquireToken(ctx, response.Header.Get("WWW-Authenticate"), scope)
			if err != nil {
				return result, err
			}
			authorization = "Bearer " + token
			c.cacheAuthorization(scope, authorization)
			challengeUsed = true
			continue
		}
		if isRetryable(response.StatusCode) {
			delay, err := retryDelay(response.Header.Get("Retry-After"), c.retryDelayCap)
			if consumeErr := consumeBounded(response.Body, c.maxResponseBytes); consumeErr != nil {
				return result, consumeErr
			}
			if err != nil {
				return result, err
			}
			if !allowRetry {
				return result, newFailure(FailureDependency)
			}
			if attempt == c.maxAttempts {
				return result, newFailure(FailureRetryExhausted)
			}
			if err := c.sleep(ctx, delay); err != nil {
				return result, newFailure(FailureCancelled)
			}
			continue
		}
		status := response.StatusCode
		if err := consumeBounded(response.Body, c.maxResponseBytes); err != nil {
			return result, err
		}
		return result, statusFailure(status)
	}
	return result, newFailure(FailureRetryExhausted)
}

func (c *Client) cachedAuthorization(scope string) string {
	c.tokenMu.Lock()
	defer c.tokenMu.Unlock()
	return c.tokens[scope]
}

func (c *Client) cacheAuthorization(scope string, authorization string) {
	c.tokenMu.Lock()
	defer c.tokenMu.Unlock()
	c.tokens[scope] = authorization
}

func isRetryable(status int) bool {
	return status == http.StatusBadGateway ||
		status == http.StatusServiceUnavailable ||
		status == http.StatusGatewayTimeout
}

func statusFailure(status int) error {
	switch status {
	case http.StatusUnauthorized:
		return newFailure(FailureAuthentication)
	case http.StatusForbidden:
		return newFailure(FailurePolicy)
	case http.StatusNotFound:
		return newFailure(FailureNotFound)
	case http.StatusTooManyRequests:
		return newFailure(FailureQuota)
	default:
		return newFailure(FailureProtocol)
	}
}

func retryDelay(value string, cap time.Duration) (time.Duration, error) {
	if value == "" {
		return 0, nil
	}
	seconds, err := strconv.ParseUint(value, 10, 16)
	if err != nil {
		return 0, newFailure(FailureProtocol)
	}
	delay := time.Duration(seconds) * time.Second
	if delay > cap {
		delay = cap
	}
	return delay, nil
}

func consumeBounded(body io.ReadCloser, limit int64) error {
	defer body.Close()
	count, err := io.Copy(io.Discard, io.LimitReader(body, limit+1))
	if err != nil {
		return newFailure(FailureDependency)
	}
	if count > limit {
		return newFailure(FailureProtocol)
	}
	return nil
}

type challenge struct {
	realm   *url.URL
	service string
	scope   string
}

func (c *Client) acquireToken(
	ctx context.Context,
	header string,
	expectedScope string,
) (string, error) {
	parsed, err := parseChallenge(header)
	if err != nil || parsed.scope != expectedScope ||
		!sameOrigin(c.baseURL, parsed.realm) {
		return "", newFailure(FailureAuthentication)
	}
	username, password, err := c.credentialProvider(ctx)
	if err != nil || username == "" || password == "" ||
		hasControl(username) || hasControl(password) {
		return "", newFailure(FailureAuthentication)
	}
	tokenURL := *parsed.realm
	query := tokenURL.Query()
	query.Set("service", parsed.service)
	query.Set("scope", parsed.scope)
	tokenURL.RawQuery = query.Encode()
	for attempt := 1; attempt <= c.maxAttempts; attempt++ {
		request, err := http.NewRequestWithContext(ctx, http.MethodGet, tokenURL.String(), nil)
		if err != nil {
			return "", newFailure(FailureProtocol)
		}
		request.SetBasicAuth(username, password)
		request.Header.Set("Accept", "application/json")
		response, requestErr := c.httpClient.Do(request)
		if requestErr != nil {
			if ctx.Err() != nil {
				return "", newFailure(FailureCancelled)
			}
			if attempt == c.maxAttempts {
				return "", newFailure(FailureDependency)
			}
			continue
		}
		if isRetryable(response.StatusCode) {
			delay, delayErr := retryDelay(response.Header.Get("Retry-After"), c.retryDelayCap)
			if consumeErr := consumeBounded(response.Body, maxTokenResponseBytes); consumeErr != nil {
				return "", consumeErr
			}
			if delayErr != nil {
				return "", delayErr
			}
			if attempt == c.maxAttempts {
				return "", newFailure(FailureRetryExhausted)
			}
			if err := c.sleep(ctx, delay); err != nil {
				return "", newFailure(FailureCancelled)
			}
			continue
		}
		if response.StatusCode != http.StatusOK {
			_ = consumeBounded(response.Body, maxTokenResponseBytes)
			return "", newFailure(FailureAuthentication)
		}
		payload, readErr := readBounded(response.Body, maxTokenResponseBytes)
		if readErr != nil {
			return "", readErr
		}
		var document struct {
			AccessToken string `json:"access_token"`
			ExpiresIn   int64  `json:"expires_in"`
			IssuedAt    string `json:"issued_at"`
			Token       string `json:"token"`
		}
		decoder := json.NewDecoder(bytes.NewReader(payload))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&document); err != nil {
			return "", newFailure(FailureAuthentication)
		}
		if decoder.Decode(&struct{}{}) != io.EOF {
			return "", newFailure(FailureAuthentication)
		}
		token := document.Token
		if token == "" {
			token = document.AccessToken
		}
		if token == "" || len(token) > maxTokenBytes || hasControl(token) ||
			strings.ContainsAny(token, " \t") {
			return "", newFailure(FailureAuthentication)
		}
		return token, nil
	}
	return "", newFailure(FailureRetryExhausted)
}

func readBounded(body io.ReadCloser, limit int64) ([]byte, error) {
	defer body.Close()
	payload, err := io.ReadAll(io.LimitReader(body, limit+1))
	if err != nil {
		return nil, newFailure(FailureDependency)
	}
	if int64(len(payload)) > limit {
		return nil, newFailure(FailureProtocol)
	}
	return payload, nil
}

func parseChallenge(value string) (challenge, error) {
	var parsed challenge
	if len(value) == 0 || len(value) > maxChallengeBytes ||
		!strings.HasPrefix(value, "Bearer ") {
		return parsed, newFailure(FailureAuthentication)
	}
	parameters, err := splitChallengeParameters(
		strings.TrimPrefix(value, "Bearer "),
	)
	if err != nil {
		return parsed, err
	}
	seen := make(map[string]bool)
	for _, raw := range parameters {
		key, encoded, found := strings.Cut(strings.TrimSpace(raw), "=")
		if !found || seen[key] || (key != "realm" && key != "service" && key != "scope") ||
			len(encoded) < 2 || encoded[0] != '"' || encoded[len(encoded)-1] != '"' {
			return parsed, newFailure(FailureAuthentication)
		}
		decoded, err := strconv.Unquote(encoded)
		if err != nil || decoded == "" || hasControl(decoded) {
			return parsed, newFailure(FailureAuthentication)
		}
		seen[key] = true
		switch key {
		case "realm":
			parsed.realm, err = url.Parse(decoded)
			if err != nil {
				return challenge{}, newFailure(FailureAuthentication)
			}
		case "service":
			parsed.service = decoded
		case "scope":
			parsed.scope = decoded
		}
	}
	if parsed.realm == nil || parsed.realm.Scheme != "https" ||
		parsed.realm.Host == "" || parsed.realm.User != nil ||
		parsed.realm.RawQuery != "" || parsed.realm.Fragment != "" ||
		parsed.service == "" ||
		parsed.scope == "" {
		return challenge{}, newFailure(FailureAuthentication)
	}
	return parsed, nil
}

func splitChallengeParameters(value string) ([]string, error) {
	var parameters []string
	start := 0
	quoted := false
	escaped := false
	for index := 0; index < len(value); index++ {
		character := value[index]
		if escaped {
			escaped = false
			continue
		}
		if quoted && character == '\\' {
			escaped = true
			continue
		}
		if character == '"' {
			quoted = !quoted
			continue
		}
		if character == ',' && !quoted {
			if index == start {
				return nil, newFailure(FailureAuthentication)
			}
			parameters = append(parameters, value[start:index])
			start = index + 1
		}
	}
	if quoted || escaped || start == len(value) {
		return nil, newFailure(FailureAuthentication)
	}
	parameters = append(parameters, value[start:])
	return parameters, nil
}

func hasControl(value string) bool {
	for _, character := range value {
		if character < 0x20 || character == 0x7f {
			return true
		}
	}
	return false
}

func sameOrigin(first *url.URL, second *url.URL) bool {
	return strings.EqualFold(first.Scheme, second.Scheme) &&
		strings.EqualFold(first.Host, second.Host)
}

func repositoryScope(repository string) (string, error) {
	if len(repository) == 0 || len(repository) > 255 ||
		!repositoryPattern.MatchString(repository) {
		return "", newFailure(FailureProtocol)
	}
	return "repository:" + repository + ":pull,push", nil
}

func (c *Client) uploadURL(repository string) (*url.URL, error) {
	if _, err := repositoryScope(repository); err != nil {
		return nil, err
	}
	reference := &url.URL{Path: "/v2/" + repository + "/blobs/uploads/"}
	return c.baseURL.ResolveReference(reference), nil
}

func (c *Client) resolveUploadLocation(repository string, value string) (*url.URL, error) {
	if len(value) == 0 || len(value) > maxChallengeBytes {
		return nil, newFailure(FailureProtocol)
	}
	location, err := url.Parse(value)
	if err != nil {
		return nil, newFailure(FailureProtocol)
	}
	location = c.baseURL.ResolveReference(location)
	prefix := "/v2/" + repository + "/blobs/uploads/"
	if !sameOrigin(c.baseURL, location) || location.User != nil ||
		location.Fragment != "" || !strings.HasPrefix(location.Path, prefix) ||
		hasDotSegment(location.Path) {
		return nil, newFailure(FailureProtocol)
	}
	return location, nil
}

func hasDotSegment(value string) bool {
	for _, segment := range strings.Split(value, "/") {
		if segment == "." || segment == ".." {
			return true
		}
	}
	return false
}

func (c *Client) validateBlobLocation(
	repository string,
	digest string,
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
	expectedPath := "/v2/" + repository + "/blobs/" + digest
	if !sameOrigin(c.baseURL, location) || location.User != nil ||
		location.Fragment != "" || location.RawQuery != "" ||
		location.Path != expectedPath {
		return newFailure(FailureProtocol)
	}
	return nil
}

func matchUploadRange(value string, offsets ...int64) (int64, error) {
	if strings.HasPrefix(value, "bytes=") {
		value = strings.TrimPrefix(value, "bytes=")
	}
	start, end, found := strings.Cut(value, "-")
	if !found || start != "0" || end == "" {
		return 0, newFailure(FailureProtocol)
	}
	last, err := strconv.ParseInt(end, 10, 64)
	if err != nil || last < 0 {
		return 0, newFailure(FailureProtocol)
	}
	var matched []int64
	for _, offset := range offsets {
		if offset < 0 {
			return 0, newFailure(FailureProtocol)
		}
		expectedLast := offset - 1
		if offset == 0 {
			expectedLast = 0
		}
		if last == expectedLast {
			matched = append(matched, offset)
		}
	}
	if len(matched) != 1 {
		return 0, newFailure(FailureProtocol)
	}
	return matched[0], nil
}

func newRequest(
	ctx context.Context,
	method string,
	target *url.URL,
	body io.Reader,
	contentLength int64,
	authorization string,
) (*http.Request, error) {
	request, err := http.NewRequestWithContext(ctx, method, target.String(), body)
	if err != nil {
		return nil, err
	}
	request.ContentLength = contentLength
	request.Header.Set("Accept", "application/json")
	if authorization != "" {
		request.Header.Set("Authorization", authorization)
	}
	return request, nil
}

type chunkResult struct {
	attempts    int
	location    *url.URL
	transferred int64
}

func (c *Client) queryUploadStatus(
	ctx context.Context,
	scope string,
	repository string,
	location *url.URL,
	priorOffset int64,
	committedOffset int64,
) (chunkResult, int64, error) {
	result, err := c.perform(
		ctx,
		scope,
		func(authorization string) (*http.Request, *byteCounter, error) {
			request, requestErr := newRequest(
				ctx,
				http.MethodGet,
				location,
				nil,
				0,
				authorization,
			)
			return request, nil, requestErr
		},
		map[int]bool{http.StatusNoContent: true},
		true,
	)
	status := chunkResult{attempts: result.attempts}
	if err != nil {
		return status, 0, err
	}
	if err := consumeBounded(result.response.Body, c.maxResponseBytes); err != nil {
		return status, 0, err
	}
	status.location, err = c.resolveUploadLocation(
		repository,
		result.response.Header.Get("Location"),
	)
	if err != nil {
		return status, 0, err
	}
	offset, err := matchUploadRange(
		result.response.Header.Get("Range"),
		priorOffset,
		committedOffset,
	)
	if err != nil {
		return status, 0, err
	}
	return status, offset, nil
}

func (c *Client) uploadChunk(
	ctx context.Context,
	scope string,
	repository string,
	location *url.URL,
	chunk []byte,
	offset int64,
) (chunkResult, error) {
	var total chunkResult
	committedOffset := offset + int64(len(chunk))
	currentLocation := location
	for cycle := 0; cycle < c.maxAttempts; cycle++ {
		result, err := c.perform(
			ctx,
			scope,
			func(authorization string) (*http.Request, *byteCounter, error) {
				counter := &byteCounter{}
				body := &countedReader{
					reader:  bytes.NewReader(chunk),
					counter: counter,
				}
				request, requestErr := newRequest(
					ctx,
					http.MethodPatch,
					currentLocation,
					body,
					int64(len(chunk)),
					authorization,
				)
				if requestErr == nil {
					request.Header.Set("Content-Type", "application/octet-stream")
					request.Header.Set(
						"Content-Range",
						fmt.Sprintf("%d-%d", offset, committedOffset-1),
					)
				}
				return request, counter, requestErr
			},
			map[int]bool{http.StatusAccepted: true},
			false,
		)
		total.attempts += result.attempts
		total.transferred += result.transferred
		if err == nil {
			if err := consumeBounded(result.response.Body, c.maxResponseBytes); err != nil {
				return total, err
			}
			if _, err := matchUploadRange(
				result.response.Header.Get("Range"),
				committedOffset,
			); err != nil {
				return total, err
			}
			total.location, err = c.resolveUploadLocation(
				repository,
				result.response.Header.Get("Location"),
			)
			return total, err
		}
		if failureKind(err) != FailureDependency {
			return total, err
		}
		status, remoteOffset, statusErr := c.queryUploadStatus(
			ctx,
			scope,
			repository,
			currentLocation,
			offset,
			committedOffset,
		)
		total.attempts += status.attempts
		if statusErr != nil {
			return total, statusErr
		}
		currentLocation = status.location
		if remoteOffset == committedOffset {
			total.location = currentLocation
			return total, nil
		}
		if remoteOffset != offset {
			return total, newFailure(FailureProtocol)
		}
	}
	return total, newFailure(FailureRetryExhausted)
}

func (c *Client) UploadMonolithic(
	ctx context.Context,
	repository string,
	content *Content,
) error {
	started := c.now()
	resultKind := FailureProtocol
	attempts := 0
	transferred := int64(0)
	digestChecks := uint64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "blob-monolithic",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       attempts,
			transferred:    transferred,
			digestChecks:   digestChecks,
			logicalSuccess: success,
		})
	}()
	if content == nil {
		return newFailure(FailureProtocol)
	}
	scope, err := repositoryScope(repository)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	digest, err := content.Digest(ctx)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	target, err := c.uploadURL(repository)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	query := target.Query()
	query.Set("digest", digest)
	target.RawQuery = query.Encode()
	requestResult, err := c.perform(ctx, scope, func(authorization string) (*http.Request, *byteCounter, error) {
		counter := &byteCounter{}
		body := &countedReader{reader: content.NewReader(), counter: counter}
		request, requestErr := newRequest(
			ctx,
			http.MethodPost,
			target,
			body,
			content.Size(),
			authorization,
		)
		if requestErr == nil {
			request.Header.Set("Content-Type", "application/octet-stream")
		}
		return request, counter, requestErr
	}, map[int]bool{http.StatusCreated: true}, true)
	attempts = requestResult.attempts
	transferred = requestResult.transferred
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	defer requestResult.response.Body.Close()
	if err := consumeBounded(requestResult.response.Body, c.maxResponseBytes); err != nil {
		resultKind = failureKind(err)
		return err
	}
	if requestResult.response.Header.Get("Docker-Content-Digest") != digest {
		resultKind = FailureDigest
		return newFailure(FailureDigest)
	}
	if location := requestResult.response.Header.Get("Location"); location != "" {
		if err := c.validateBlobLocation(repository, digest, location); err != nil {
			resultKind = failureKind(err)
			return err
		}
	}
	digestChecks = 1
	success = true
	resultKind = ResultSuccess
	return nil
}

func (c *Client) UploadChunked(
	ctx context.Context,
	repository string,
	content *Content,
	chunkSize int64,
) error {
	started := c.now()
	resultKind := FailureProtocol
	totalAttempts := 0
	transferred := int64(0)
	digestChecks := uint64(0)
	success := false
	defer func() {
		c.recorder.observe(observation{
			operation:      "blob-resumable",
			result:         resultKind,
			latency:        c.now().Sub(started),
			attempts:       totalAttempts,
			transferred:    transferred,
			digestChecks:   digestChecks,
			logicalSuccess: success,
		})
	}()
	if content == nil || chunkSize < 1 || chunkSize > MaxChunkBytes {
		return newFailure(FailureProtocol)
	}
	scope, err := repositoryScope(repository)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	digest, err := content.Digest(ctx)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	target, err := c.uploadURL(repository)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	startResult, err := c.perform(ctx, scope, func(authorization string) (*http.Request, *byteCounter, error) {
		request, requestErr := newRequest(ctx, http.MethodPost, target, nil, 0, authorization)
		return request, nil, requestErr
	}, map[int]bool{http.StatusAccepted: true}, false)
	totalAttempts += startResult.attempts
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	if err := consumeBounded(startResult.response.Body, c.maxResponseBytes); err != nil {
		resultKind = failureKind(err)
		return err
	}
	if _, err := matchUploadRange(
		startResult.response.Header.Get("Range"),
		0,
	); err != nil {
		resultKind = failureKind(err)
		return err
	}
	location, err := c.resolveUploadLocation(
		repository,
		startResult.response.Header.Get("Location"),
	)
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	reader := content.NewReader()
	offset := int64(0)
	for offset < content.Size() {
		length := chunkSize
		if remaining := content.Size() - offset; remaining < length {
			length = remaining
		}
		chunk := make([]byte, length)
		if _, err := io.ReadFull(reader, chunk); err != nil {
			resultKind = FailureProtocol
			return newFailure(FailureProtocol)
		}
		patchResult, err := c.uploadChunk(
			ctx,
			scope,
			repository,
			location,
			chunk,
			offset,
		)
		totalAttempts += patchResult.attempts
		transferred += patchResult.transferred
		if err != nil {
			resultKind = failureKind(err)
			return err
		}
		location = patchResult.location
		offset += int64(len(chunk))
	}
	finalURL := *location
	query := finalURL.Query()
	query.Set("digest", digest)
	finalURL.RawQuery = query.Encode()
	finalResult, err := c.perform(ctx, scope, func(authorization string) (*http.Request, *byteCounter, error) {
		request, requestErr := newRequest(
			ctx,
			http.MethodPut,
			&finalURL,
			nil,
			0,
			authorization,
		)
		return request, nil, requestErr
	}, map[int]bool{http.StatusCreated: true}, true)
	totalAttempts += finalResult.attempts
	if err != nil {
		resultKind = failureKind(err)
		return err
	}
	if err := consumeBounded(finalResult.response.Body, c.maxResponseBytes); err != nil {
		resultKind = failureKind(err)
		return err
	}
	if finalResult.response.Header.Get("Docker-Content-Digest") != digest {
		resultKind = FailureDigest
		return newFailure(FailureDigest)
	}
	if location := finalResult.response.Header.Get("Location"); location != "" {
		if err := c.validateBlobLocation(repository, digest, location); err != nil {
			resultKind = failureKind(err)
			return err
		}
	}
	digestChecks = 1
	success = true
	resultKind = ResultSuccess
	return nil
}

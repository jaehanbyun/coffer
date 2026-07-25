package control

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	maxResponseBytes = int64(1 << 20)
	maxManifestBytes = 4 << 20
)

var (
	repositoryPattern = regexp.MustCompile(
		`^p/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-` +
			`[0-9a-f]{4}-[0-9a-f]{12}/` +
			`[a-z0-9]+(?:[._-][a-z0-9]+)*` +
			`(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$`,
	)
	servicePattern = regexp.MustCompile(`^[a-z0-9][a-z0-9.-]{0,252}$`)
	digestPattern  = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
)

type Failure string

const (
	FailureAuthentication Failure = "authentication"
	FailureCancellation   Failure = "cancellation"
	FailureCleanup        Failure = "cleanup"
	FailureDependency     Failure = "dependency"
	FailureProtocol       Failure = "protocol"
	FailureQuota          Failure = "quota"
)

type Error struct {
	Failure Failure
}

func (e *Error) Error() string {
	return "control load operation failed"
}

func fail(kind Failure) error {
	return &Error{Failure: kind}
}

func FailureOf(err error) Failure {
	var target *Error
	if errors.As(err, &target) {
		return target.Failure
	}
	return FailureDependency
}

type Credential struct {
	ID     string
	Secret string
}

type CredentialProvider func(context.Context) (Credential, error)

type Config struct {
	ControlBase        string
	IdentityBase       string
	RegistryBase       string
	Repository         string
	Service            string
	Roots              *x509.CertPool
	Timeout            time.Duration
	MaxConcurrency     int
	CredentialProvider CredentialProvider
}

type Result struct {
	Operation string `json:"operation"`
	Result    string `json:"result"`
	Count     int    `json:"count"`
}

type Snapshot struct {
	Schema               string   `json:"schema"`
	DurationMilliseconds int64    `json:"duration_milliseconds"`
	Results              []Result `json:"results"`
}

type recorder struct {
	started time.Time
	mu      sync.Mutex
	counts  map[string]int
}

func newRecorder() *recorder {
	return &recorder{
		started: time.Now(),
		counts:  make(map[string]int),
	}
}

func (r *recorder) observe(operation, result string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.counts[operation+"\x00"+result]++
}

func (r *recorder) snapshot() Snapshot {
	r.mu.Lock()
	defer r.mu.Unlock()
	results := make([]Result, 0, len(r.counts))
	for key, count := range r.counts {
		parts := strings.SplitN(key, "\x00", 2)
		results = append(results, Result{
			Operation: parts[0],
			Result:    parts[1],
			Count:     count,
		})
	}
	sort.Slice(results, func(i, j int) bool {
		if results[i].Operation == results[j].Operation {
			return results[i].Result < results[j].Result
		}
		return results[i].Operation < results[j].Operation
	})
	return Snapshot{
		Schema:               "coffer.control-load-driver/v1",
		DurationMilliseconds: max(0, time.Since(r.started).Milliseconds()),
		Results:              results,
	}
}

type Client struct {
	control     *url.URL
	identity    *url.URL
	registry    *url.URL
	repository  string
	service     string
	timeout     time.Duration
	concurrency int
	credentials CredentialProvider
	http        *http.Client
	recorder    *recorder
}

func parseBase(value string) (*url.URL, error) {
	parsed, err := url.Parse(value)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" ||
		parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" ||
		(parsed.Path != "" && parsed.Path != "/") {
		return nil, fail(FailureProtocol)
	}
	parsed.Path = ""
	return parsed, nil
}

func New(config Config) (*Client, error) {
	control, err := parseBase(config.ControlBase)
	if err != nil {
		return nil, err
	}
	identity, err := parseBase(config.IdentityBase)
	if err != nil {
		return nil, err
	}
	registry, err := parseBase(config.RegistryBase)
	if err != nil {
		return nil, err
	}
	if config.Roots == nil || config.Timeout < time.Second ||
		config.Timeout > 10*time.Minute ||
		config.MaxConcurrency < 1 || config.MaxConcurrency > 64 ||
		config.CredentialProvider == nil ||
		!repositoryPattern.MatchString(config.Repository) ||
		!servicePattern.MatchString(config.Service) {
		return nil, fail(FailureProtocol)
	}
	transport := &http.Transport{
		Proxy:                 nil,
		TLSClientConfig:       &tls.Config{RootCAs: config.Roots, MinVersion: tls.VersionTLS12},
		DisableCompression:    true,
		MaxIdleConns:          config.MaxConcurrency + 3,
		MaxIdleConnsPerHost:   config.MaxConcurrency + 3,
		ResponseHeaderTimeout: config.Timeout,
	}
	client := &http.Client{
		Transport: transport,
		Timeout:   config.Timeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	return &Client{
		control: control, identity: identity, registry: registry,
		repository: config.Repository, service: config.Service,
		timeout: config.Timeout, concurrency: config.MaxConcurrency,
		credentials: config.CredentialProvider, http: client,
		recorder: newRecorder(),
	}, nil
}

func (c *Client) Close() {
	if transport, ok := c.http.Transport.(*http.Transport); ok {
		transport.CloseIdleConnections()
	}
}

func (c *Client) Snapshot() Snapshot {
	return c.recorder.snapshot()
}

func (c *Client) credential(ctx context.Context) (Credential, error) {
	credential, err := c.credentials(ctx)
	if err != nil || credential.ID == "" || credential.Secret == "" ||
		len(credential.ID) > 256 || len(credential.Secret) > 8192 ||
		strings.ContainsAny(credential.ID+credential.Secret, "\r\n\x00") {
		return Credential{}, fail(FailureAuthentication)
	}
	return credential, nil
}

func endpoint(base *url.URL, path string, query url.Values) string {
	result := *base
	result.Path = path
	result.RawQuery = query.Encode()
	return result.String()
}

func bounded(response *http.Response) ([]byte, error) {
	defer response.Body.Close()
	payload, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil || int64(len(payload)) > maxResponseBytes {
		return nil, fail(FailureProtocol)
	}
	return payload, nil
}

func (c *Client) do(request *http.Request) (*http.Response, error) {
	response, err := c.http.Do(request)
	if err != nil {
		if request.Context().Err() != nil {
			return nil, fail(FailureCancellation)
		}
		return nil, fail(FailureDependency)
	}
	if response.StatusCode >= 300 && response.StatusCode < 400 {
		response.Body.Close()
		return nil, fail(FailureProtocol)
	}
	return response, nil
}

func (c *Client) KeystoneToken(ctx context.Context) (string, error) {
	credential, err := c.credential(ctx)
	if err != nil {
		c.recorder.observe("control", "authentication")
		return "", err
	}
	document := map[string]any{
		"auth": map[string]any{
			"identity": map[string]any{
				"methods": []string{"application_credential"},
				"application_credential": map[string]string{
					"id": credential.ID, "secret": credential.Secret,
				},
			},
		},
	}
	payload, err := json.Marshal(document)
	credential = Credential{}
	if err != nil {
		return "", fail(FailureProtocol)
	}
	defer func() {
		for index := range payload {
			payload[index] = 0
		}
	}()
	request, err := http.NewRequestWithContext(
		ctx, http.MethodPost,
		endpoint(c.identity, "/v3/auth/tokens", nil),
		bytes.NewReader(payload),
	)
	if err != nil {
		return "", fail(FailureProtocol)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json")
	response, err := c.do(request)
	if err != nil {
		c.recorder.observe("control", string(FailureOf(err)))
		return "", err
	}
	body, readErr := bounded(response)
	if readErr != nil || response.StatusCode != http.StatusCreated ||
		len(body) == 0 {
		c.recorder.observe("control", "protocol")
		return "", fail(FailureProtocol)
	}
	token := response.Header.Get("X-Subject-Token")
	if token == "" || len(token) > 16384 ||
		strings.ContainsAny(token, "\r\n\x00") {
		c.recorder.observe("control", "protocol")
		return "", fail(FailureProtocol)
	}
	c.recorder.observe("control", "success")
	return token, nil
}

func (c *Client) ProbeControl(ctx context.Context, token string) error {
	if token == "" || strings.ContainsAny(token, "\r\n\x00") {
		return fail(FailureAuthentication)
	}
	request, err := http.NewRequestWithContext(
		ctx, http.MethodGet,
		endpoint(c.control, "/v1/repositories", nil),
		nil,
	)
	if err != nil {
		return fail(FailureProtocol)
	}
	request.Header.Set("X-Auth-Token", token)
	request.Header.Set("Accept", "application/json")
	response, err := c.do(request)
	if err != nil {
		c.recorder.observe("control", string(FailureOf(err)))
		return err
	}
	payload, readErr := bounded(response)
	var document struct {
		Repositories []json.RawMessage `json:"repositories"`
	}
	if readErr != nil || response.StatusCode != http.StatusOK ||
		json.Unmarshal(payload, &document) != nil ||
		document.Repositories == nil {
		c.recorder.observe("control", "protocol")
		return fail(FailureProtocol)
	}
	c.recorder.observe("control", "success")
	return nil
}

func (c *Client) RegistryToken(ctx context.Context) (string, error) {
	credential, err := c.credential(ctx)
	if err != nil {
		c.recorder.observe("token", "authentication")
		return "", err
	}
	query := url.Values{
		"service": {c.service},
		"scope":   {"repository:" + c.repository + ":pull,push"},
	}
	request, err := http.NewRequestWithContext(
		ctx, http.MethodGet,
		endpoint(c.registry, "/auth/token", query),
		nil,
	)
	if err != nil {
		return "", fail(FailureProtocol)
	}
	basic := base64.StdEncoding.EncodeToString(
		[]byte(credential.ID + ":" + credential.Secret),
	)
	credential = Credential{}
	request.Header.Set("Authorization", "Basic "+basic)
	request.Header.Set("Accept", "application/json")
	response, err := c.do(request)
	if err != nil {
		c.recorder.observe("token", string(FailureOf(err)))
		return "", err
	}
	payload, readErr := bounded(response)
	var document struct {
		Token string `json:"token"`
	}
	if readErr != nil || response.StatusCode != http.StatusOK ||
		json.Unmarshal(payload, &document) != nil ||
		document.Token == "" || len(document.Token) > 16384 ||
		strings.ContainsAny(document.Token, "\r\n\x00") {
		c.recorder.observe("token", "protocol")
		return "", fail(FailureProtocol)
	}
	c.recorder.observe("token", "success")
	return document.Token, nil
}

type quotaResult struct {
	digest string
	status int
	err    error
}

func manifestDigest(payload []byte) string {
	sum := sha256.Sum256(payload)
	return "sha256:" + hex.EncodeToString(sum[:])
}

func (c *Client) putManifest(
	ctx context.Context,
	token string,
	index int,
	payload []byte,
) quotaResult {
	if len(payload) == 0 || len(payload) > maxManifestBytes ||
		!json.Valid(payload) {
		return quotaResult{err: fail(FailureProtocol)}
	}
	path := fmt.Sprintf(
		"/v2/%s/manifests/coffer-quota-%d",
		c.repository,
		index,
	)
	request, err := http.NewRequestWithContext(
		ctx, http.MethodPut, endpoint(c.registry, path, nil),
		bytes.NewReader(payload),
	)
	if err != nil {
		return quotaResult{err: fail(FailureProtocol)}
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("Content-Type", "application/vnd.oci.image.manifest.v1+json")
	response, err := c.do(request)
	if err != nil {
		return quotaResult{err: err}
	}
	body, readErr := bounded(response)
	if readErr != nil || len(body) != 0 {
		return quotaResult{err: fail(FailureProtocol)}
	}
	if response.StatusCode == http.StatusTooManyRequests {
		return quotaResult{status: response.StatusCode}
	}
	expected := manifestDigest(payload)
	if response.StatusCode != http.StatusCreated ||
		response.Header.Get("Docker-Content-Digest") != expected ||
		!digestPattern.MatchString(expected) {
		return quotaResult{err: fail(FailureProtocol)}
	}
	return quotaResult{digest: expected, status: response.StatusCode}
}

func (c *Client) cleanup(
	ctx context.Context,
	token string,
	digests map[string]struct{},
) error {
	for digest := range digests {
		path := fmt.Sprintf("/v2/%s/manifests/%s", c.repository, digest)
		request, err := http.NewRequestWithContext(
			ctx, http.MethodDelete, endpoint(c.registry, path, nil), nil,
		)
		if err != nil {
			return fail(FailureCleanup)
		}
		request.Header.Set("Authorization", "Bearer "+token)
		response, err := c.do(request)
		if err != nil {
			return fail(FailureCleanup)
		}
		payload, readErr := bounded(response)
		if readErr != nil || len(payload) != 0 ||
			(response.StatusCode != http.StatusAccepted &&
				response.StatusCode != http.StatusNotFound) {
			return fail(FailureCleanup)
		}
	}
	return nil
}

func (c *Client) QuotaContention(
	ctx context.Context,
	token string,
	manifests [][]byte,
	expectedSuccess int,
	expectedQuota int,
) error {
	if token == "" || len(manifests) < 2 ||
		len(manifests) > c.concurrency ||
		expectedSuccess < 1 || expectedQuota < 1 ||
		expectedSuccess+expectedQuota != len(manifests) {
		return fail(FailureProtocol)
	}
	results := make(chan quotaResult, len(manifests))
	var group sync.WaitGroup
	for index, manifest := range manifests {
		group.Add(1)
		go func(index int, manifest []byte) {
			defer group.Done()
			results <- c.putManifest(ctx, token, index, manifest)
		}(index, manifest)
	}
	group.Wait()
	close(results)
	successes := 0
	quotas := 0
	digests := make(map[string]struct{})
	var primary error
	for result := range results {
		if result.err != nil && primary == nil {
			primary = result.err
		}
		switch result.status {
		case http.StatusCreated:
			successes++
			digests[result.digest] = struct{}{}
		case http.StatusTooManyRequests:
			quotas++
		}
	}
	cleanupCtx, cancel := context.WithTimeout(context.Background(), c.timeout)
	defer cancel()
	if err := c.cleanup(cleanupCtx, token, digests); err != nil {
		c.recorder.observe("quota-contention", "cleanup")
		return err
	}
	if ctx.Err() != nil {
		c.recorder.observe("quota-contention", "cancellation")
		return fail(FailureCancellation)
	}
	if primary != nil {
		c.recorder.observe(
			"quota-contention",
			string(FailureOf(primary)),
		)
		return primary
	}
	if successes != expectedSuccess || quotas != expectedQuota {
		c.recorder.observe("quota-contention", "quota")
		return fail(FailureQuota)
	}
	c.recorder.observe("quota-contention", "success")
	return nil
}

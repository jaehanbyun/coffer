package driver

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
)

const ResultSchema = "coffer.raw-oci-driver/v1"

var latencyBuckets = []struct {
	label string
	limit time.Duration
}{
	{"le-10ms", 10 * time.Millisecond},
	{"le-25ms", 25 * time.Millisecond},
	{"le-50ms", 50 * time.Millisecond},
	{"le-100ms", 100 * time.Millisecond},
	{"le-250ms", 250 * time.Millisecond},
	{"le-500ms", 500 * time.Millisecond},
	{"le-1000ms", time.Second},
	{"le-2000ms", 2 * time.Second},
	{"le-5000ms", 5 * time.Second},
	{"gt-5000ms", 0},
}

type observation struct {
	operation      string
	result         Failure
	latency        time.Duration
	attempts       int
	transferred    int64
	digestChecks   uint64
	logicalSuccess bool
}

type aggregate struct {
	attempts     uint64
	count        uint64
	digestChecks uint64
	latency      [10]uint64
	retries      uint64
	transferred  uint64
}

type Recorder struct {
	mu      sync.Mutex
	now     func() time.Time
	started time.Time
	values  map[string]*aggregate
}

func NewRecorder() *Recorder {
	return newRecorder(time.Now)
}

func newRecorder(now func() time.Time) *Recorder {
	return &Recorder{
		now:     now,
		started: now(),
		values:  make(map[string]*aggregate),
	}
}

func (r *Recorder) observe(value observation) {
	if r == nil {
		return
	}
	result := string(value.result)
	if value.logicalSuccess {
		result = string(ResultSuccess)
	}
	key := value.operation + "\x00" + result
	r.mu.Lock()
	defer r.mu.Unlock()
	item := r.values[key]
	if item == nil {
		item = &aggregate{}
		r.values[key] = item
	}
	item.count++
	if value.attempts > 0 {
		item.attempts += uint64(value.attempts)
		if value.attempts > 1 {
			item.retries += uint64(value.attempts - 1)
		}
	}
	if value.transferred > 0 {
		item.transferred += uint64(value.transferred)
	}
	item.digestChecks += value.digestChecks
	item.latency[bucketIndex(value.latency)]++
}

func bucketIndex(value time.Duration) int {
	for index, bucket := range latencyBuckets {
		if bucket.limit == 0 || value <= bucket.limit {
			return index
		}
	}
	return len(latencyBuckets) - 1
}

type Bucket struct {
	Count uint64 `json:"count"`
	Name  string `json:"name"`
}

type OperationResult struct {
	Attempts        uint64   `json:"attempts"`
	Count           uint64   `json:"count"`
	DigestChecks    uint64   `json:"digest_checks"`
	LatencyBuckets  []Bucket `json:"latency_buckets"`
	Operation       string   `json:"operation"`
	Result          string   `json:"result"`
	Retries         uint64   `json:"retries"`
	TransferredByte uint64   `json:"transferred_bytes"`
}

type Snapshot struct {
	DurationMilliseconds int64             `json:"duration_milliseconds"`
	Operations           []OperationResult `json:"operations"`
	Schema               string            `json:"schema"`
}

func (r *Recorder) Snapshot() Snapshot {
	r.mu.Lock()
	defer r.mu.Unlock()
	operations := make([]OperationResult, 0, len(r.values))
	keys := make([]string, 0, len(r.values))
	for key := range r.values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		value := r.values[key]
		separator := 0
		for separator < len(key) && key[separator] != 0 {
			separator++
		}
		buckets := make([]Bucket, len(latencyBuckets))
		for index, bucket := range latencyBuckets {
			buckets[index] = Bucket{Name: bucket.label, Count: value.latency[index]}
		}
		operations = append(operations, OperationResult{
			Attempts:        value.attempts,
			Count:           value.count,
			DigestChecks:    value.digestChecks,
			LatencyBuckets:  buckets,
			Operation:       key[:separator],
			Result:          key[separator+1:],
			Retries:         value.retries,
			TransferredByte: value.transferred,
		})
	}
	duration := r.now().Sub(r.started)
	if duration < 0 {
		duration = 0
	}
	return Snapshot{
		DurationMilliseconds: duration.Milliseconds(),
		Operations:           operations,
		Schema:               ResultSchema,
	}
}

func MarshalCanonical(snapshot Snapshot) ([]byte, error) {
	payload, err := json.Marshal(snapshot)
	if err != nil {
		return nil, newFailure(FailureProtocol)
	}
	return append(payload, '\n'), nil
}

func WriteCanonical(path string, snapshot Snapshot) error {
	directory := filepath.Dir(path)
	info, err := os.Lstat(directory)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 ||
		info.Mode().Perm()&0o077 != 0 {
		return newFailure(FailureProtocol)
	}
	if existing, statErr := os.Lstat(path); statErr == nil {
		if !existing.Mode().IsRegular() || existing.Mode().Perm()&0o077 != 0 {
			return newFailure(FailureProtocol)
		}
	} else if !os.IsNotExist(statErr) {
		return newFailure(FailureProtocol)
	}
	payload, err := MarshalCanonical(snapshot)
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(directory, "."+filepath.Base(path)+".")
	if err != nil {
		return newFailure(FailureProtocol)
	}
	temporary := file.Name()
	cleanup := true
	defer func() {
		_ = file.Close()
		if cleanup {
			_ = os.Remove(temporary)
		}
	}()
	if err := file.Chmod(0o600); err != nil {
		return newFailure(FailureProtocol)
	}
	if _, err := file.Write(payload); err != nil {
		return newFailure(FailureProtocol)
	}
	if err := file.Sync(); err != nil {
		return newFailure(FailureProtocol)
	}
	if err := file.Close(); err != nil {
		return newFailure(FailureProtocol)
	}
	if err := os.Rename(temporary, path); err != nil {
		return newFailure(FailureProtocol)
	}
	cleanup = false
	directoryHandle, err := os.Open(directory)
	if err != nil {
		return newFailure(FailureProtocol)
	}
	defer directoryHandle.Close()
	if err := directoryHandle.Sync(); err != nil {
		return newFailure(FailureProtocol)
	}
	return nil
}

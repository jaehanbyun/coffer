package driver

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"hash"
	"io"
)

const (
	MaxBlobBytes  int64 = 256 << 20
	MaxChunkBytes int64 = 16 << 20
)

// Content describes a bounded deterministic byte stream. It retains only its
// seed in memory and can create independent readers for request retries.
type Content struct {
	seed []byte
	size int64
}

func NewContent(seed []byte, size int64) (*Content, error) {
	if len(seed) == 0 || len(seed) > 256 || size < 0 || size > MaxBlobBytes {
		return nil, newFailure(FailureProtocol)
	}
	return &Content{seed: append([]byte(nil), seed...), size: size}, nil
}

func (c *Content) Size() int64 {
	return c.size
}

func (c *Content) NewReader() io.Reader {
	reader, _ := c.NewRangeReader(0, c.size)
	return reader
}

func (c *Content) NewRangeReader(offset int64, length int64) (io.Reader, error) {
	if offset < 0 || length < 0 || offset > c.size ||
		length > c.size-offset {
		return nil, newFailure(FailureProtocol)
	}
	return &deterministicReader{
		seed:       c.seed,
		remaining:  length,
		blockIndex: uint64(offset / sha256.Size),
		blockStart: int(offset % sha256.Size),
	}, nil
}

func (c *Content) Digest(ctx context.Context) (string, error) {
	checksum := sha256.New()
	if err := copyWithContext(ctx, checksum, c.NewReader()); err != nil {
		if errors.Is(err, context.Canceled) ||
			errors.Is(err, context.DeadlineExceeded) {
			return "", newFailure(FailureCancelled)
		}
		return "", newFailure(FailureProtocol)
	}
	return "sha256:" + hex.EncodeToString(checksum.Sum(nil)), nil
}

func copyWithContext(ctx context.Context, destination hash.Hash, source io.Reader) error {
	buffer := make([]byte, 32*1024)
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		count, err := source.Read(buffer)
		if count > 0 {
			if _, writeErr := destination.Write(buffer[:count]); writeErr != nil {
				return writeErr
			}
		}
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
	}
}

type deterministicReader struct {
	seed       []byte
	remaining  int64
	block      [sha256.Size]byte
	blockIndex uint64
	blockStart int
	blockReady bool
}

func (r *deterministicReader) Read(destination []byte) (int, error) {
	if r.remaining == 0 {
		return 0, io.EOF
	}
	if int64(len(destination)) > r.remaining {
		destination = destination[:r.remaining]
	}
	written := 0
	for written < len(destination) {
		if !r.blockReady || r.blockStart == len(r.block) {
			checksum := sha256.New()
			_, _ = checksum.Write(r.seed)
			var encoded [8]byte
			binary.BigEndian.PutUint64(encoded[:], r.blockIndex)
			_, _ = checksum.Write(encoded[:])
			copy(r.block[:], checksum.Sum(nil))
			r.blockIndex++
			if r.blockStart == len(r.block) {
				r.blockStart = 0
			}
			r.blockReady = true
		}
		count := copy(destination[written:], r.block[r.blockStart:])
		written += count
		r.blockStart += count
		r.remaining -= int64(count)
	}
	return written, nil
}

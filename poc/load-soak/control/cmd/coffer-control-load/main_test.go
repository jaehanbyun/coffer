package main

import (
	"bytes"
	"context"
	"strings"
	"testing"
)

func TestCommandAcceptsOnlyOneInvocationArgument(t *testing.T) {
	for _, arguments := range [][]string{
		nil,
		{"--invocation", "/tmp/example", "unexpected"},
		{"--unknown"},
	} {
		var stdout bytes.Buffer
		var stderr bytes.Buffer
		if code := run(
			context.Background(),
			arguments,
			&stdout,
			&stderr,
		); code != 2 {
			t.Fatalf("unexpected exit code: %d", code)
		}
		if stdout.Len() != 0 ||
			stderr.String() !=
				"control load driver failed: invalid arguments\n" {
			t.Fatalf(
				"argument output changed: %q %q",
				stdout.String(),
				stderr.String(),
			)
		}
	}
}

func TestCommandFailureIsFixedAndDoesNotEchoPath(t *testing.T) {
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	path := "/missing/owner-only/invocation.json"
	code := run(
		context.Background(),
		[]string{"--invocation", path},
		&stdout,
		&stderr,
	)
	if code != 1 || stdout.Len() != 0 ||
		stderr.String() !=
			"control load driver failed: execution unavailable\n" ||
		strings.Contains(stderr.String(), path) {
		t.Fatalf(
			"failure output changed: code=%d stdout=%q stderr=%q",
			code,
			stdout.String(),
			stderr.String(),
		)
	}
}

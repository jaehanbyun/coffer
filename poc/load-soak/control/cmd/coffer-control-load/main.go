package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/jaehanbyun/coffer/poc/load-soak/control"
)

func run(
	ctx context.Context,
	arguments []string,
	stdout io.Writer,
	stderr io.Writer,
) int {
	flags := flag.NewFlagSet("coffer-control-load", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	invocation := flags.String(
		"invocation",
		"",
		"absolute owner-only invocation file",
	)
	if err := flags.Parse(arguments); err != nil ||
		*invocation == "" || flags.NArg() != 0 {
		_, _ = fmt.Fprintln(
			stderr,
			"control load driver failed: invalid arguments",
		)
		return 2
	}
	if err := control.ExecuteInvocation(ctx, *invocation); err != nil {
		_, _ = fmt.Fprintln(
			stderr,
			"control load driver failed: execution unavailable",
		)
		return 1
	}
	_, _ = fmt.Fprintln(stdout, "control load driver completed")
	return 0
}

func main() {
	os.Exit(run(context.Background(), os.Args[1:], os.Stdout, os.Stderr))
}

package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"

	driver "github.com/jaehanbyun/coffer/poc/load-soak/driver"
)

func run(
	ctx context.Context,
	arguments []string,
	stdout io.Writer,
	stderr io.Writer,
) int {
	flags := flag.NewFlagSet("coffer-raw-oci-driver", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	invocation := flags.String(
		"invocation",
		"",
		"absolute owner-only invocation file",
	)
	if err := flags.Parse(arguments); err != nil ||
		*invocation == "" || flags.NArg() != 0 {
		_, _ = fmt.Fprintln(stderr, "raw OCI driver failed: invalid arguments")
		return 2
	}
	if err := driver.ExecuteInvocation(ctx, *invocation); err != nil {
		_, _ = fmt.Fprintln(stderr, "raw OCI driver failed: execution unavailable")
		return 1
	}
	_, _ = fmt.Fprintln(stdout, "raw OCI driver completed")
	return 0
}

func main() {
	os.Exit(run(context.Background(), os.Args[1:], os.Stdout, os.Stderr))
}

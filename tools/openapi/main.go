// Command openapi writes the HTTP API's OpenAPI description, from the
// module's Go types, to cmd/carbon-cost/web/openapi.json:
//
//	go run ./tools/openapi
package main

import (
	"fmt"
	"os"

	"github.com/majidkabir/carbon-cost/internal/apidoc"
)

func main() {
	b, err := apidoc.Generate(".", "1")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := os.WriteFile("cmd/carbon-cost/web/openapi.json", b, 0o644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

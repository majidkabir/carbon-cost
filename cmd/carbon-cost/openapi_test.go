package main

import (
	"bytes"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/majidkabir/carbon-cost/internal/apidoc"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// The served OpenAPI description is the one the Go types give: run
// "go run ./tools/openapi" after changing a request or response type.
func TestOpenAPIUpToDate(t *testing.T) {
	b, err := apidoc.Generate("../..", "1")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(b, openAPI) {
		t.Error("cmd/carbon-cost/web/openapi.json is out of date: run go run ./tools/openapi")
	}
	c, err := calculator(&sootcase.Client{})
	if err == nil {
		rec := httptest.NewRecorder()
		Handler(c, "none").ServeHTTP(rec, httptest.NewRequest("GET", "/v1/openapi.json", nil))
		if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"openapi": "3.1.0"`) {
			t.Errorf("GET /v1/openapi.json: %d", rec.Code)
		}
	}
}

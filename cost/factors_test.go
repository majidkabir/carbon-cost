package cost

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"github.com/majidkabir/carbon-cost/sootcase"
)

// A request whose client has gone away still reads the factors for the
// others, and what it read is kept.
func TestFactorsOfGoneClient(t *testing.T) {
	var reads atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reads.Add(1)
		w.Write([]byte(`{"grid_note":"g"}`))
	}))
	defer srv.Close()
	c := sootcase.Client{BaseURL: srv.URL}
	gone, cancel := context.WithCancel(context.Background())
	cancel()
	if f, ok := factorsOf(gone, c); !ok || f.GridNote != "g" {
		t.Fatalf("gone client: got %+v, %v; want the factors", f, ok)
	}
	if f, ok := factorsOf(context.Background(), c); !ok || f.GridNote != "g" || reads.Load() != 1 {
		t.Fatalf("next request: got %+v, %v after %d reads; want the kept factors after 1", f, ok, reads.Load())
	}
}

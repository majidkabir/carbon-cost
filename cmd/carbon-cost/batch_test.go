package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/majidkabir/carbon-cost/sootcase"
)

// fakeRoute answers Sootcase's calculate with 100 km in Germany, Hamburg
// to Berlin.
func fakeRoute(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/calculate" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.Write([]byte(`{"legs":[{"distance_km":100,"ttw_kg":80,"wtw_kg":100,"country_km":{"DE":100},"path":[[53.55,9.99],[52.52,13.40]]}],"ttw_kg":80,"wtw_kg":100}`))
	}))
}

func TestBatchHandler(t *testing.T) {
	fake := fakeRoute(t)
	defer fake.Close()
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, "none")
	trip := `{"from": {"code": "DEHAM"}, "to": {"code": "DEBER"}, "date": "2026-11-03", "cargo_kg": 20000, "truck": {"max_mass_kg": 40000, "axles": 5, "euro": 6, "co2_class": %d}}`
	body := `{"trips": [` + strings.Replace(trip, "%d", "1", 1) + `, ` + strings.Replace(trip, "%d", "9", 1) + `]}`
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost/batch", strings.NewReader(body)))
	if rec.Code != 200 {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
	var out BatchResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	// DE: 100 km x (0.155 + 0.023 + 0.012 + 0.158) EUR = 34.80 EUR of toll.
	if len(out.Results) != 2 || out.Results[0].Result == nil || out.Results[0].Result.TotalEUR < 34.8 || !out.Results[0].Result.Complete {
		t.Errorf("trip 1: %+v", out.Results)
	}
	if out.Results[1].Result != nil || !strings.Contains(out.Results[1].Error, "co2_class") {
		t.Errorf("trip 2: %+v", out.Results[1])
	}
	for _, tc := range []struct{ body, want string }{
		{`{"trips": []}`, "give 1 to 100"},
		{`{"trips": [{"nope": 1}]}`, "bad JSON"},
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost/batch", strings.NewReader(tc.body)))
		if rec.Code != 400 || !strings.Contains(rec.Body.String(), tc.want) {
			t.Errorf("%s: %d %s", tc.body, rec.Code, rec.Body.String())
		}
	}
}

func TestCalcCSV(t *testing.T) {
	fake := fakeRoute(t)
	defer fake.Close()
	in := filepath.Join(t.TempDir(), "trips.csv")
	os.WriteFile(in, []byte("from,to,date,co2-class\nDEHAM,DEBER,2026-11-03,1\nDEHAM,DEBER,2026-11-03,9\nDEHAM,,2026-11-03,1\n"), 0o644)
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	r, w, _ := os.Pipe()
	stdout := os.Stdout
	os.Stdout = w
	err = calcCSV(c, []string{"-cargo-kg", "20000", "-csv", in}, in)
	w.Close()
	os.Stdout = stdout
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(r)
	lines := strings.Split(strings.TrimSpace(string(b)), "\n")
	if len(lines) != 4 || !strings.HasPrefix(lines[0], "from,to,date,co2-class,trip_date,distance_km,country_km,total_eur") {
		t.Fatalf("output:\n%s", b)
	}
	if !strings.Contains(lines[1], ",DE=100.0,") || !strings.Contains(lines[1], ",true,") {
		t.Errorf("row 1: %s", lines[1])
	}
	if !strings.Contains(lines[2], "co2_class") {
		t.Errorf("row 2 (class 9): %s", lines[2])
	}
	if !strings.Contains(lines[3], "-to") {
		t.Errorf("row 3 (no destination): %s", lines[3])
	}
}

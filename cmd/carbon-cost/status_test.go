package main

import (
	"bytes"
	"context"
	"encoding/csv"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/majidkabir/carbon-cost/sootcase"
)

// Sootcase dropping the connection on a shipment's own route is a bad
// gateway, as on the trip's, not the caller's bad request.
func TestShipmentSootcaseFailureIs502(t *testing.T) {
	var calls int32
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/factors" {
			http.NotFound(w, r)
			return
		}
		if atomic.AddInt32(&calls, 1) > 1 {
			c, _, _ := w.(http.Hijacker).Hijack()
			c.Close()
			return
		}
		var s sootcase.Shipment
		json.NewDecoder(r.Body).Decode(&s)
		var res sootcase.Result
		for range s.Legs {
			res.Legs = append(res.Legs, sootcase.LegResult{DistanceKm: 100, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"DE": 100}, Path: [][2]float64{{9, 52}, {10, 52}}})
		}
		json.NewEncoder(w).Encode(res)
	}))
	defer fake.Close()
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, DefaultTiles)
	body := `{"date":"2026-11-03","truck":{"max_mass_kg":40000,"axles":5,"euro":6,"co2_class":1},"stops":[{"code":"DEHAM"},{"code":"DEBRE"},{"code":"DEFRA"}],` +
		`"shipments":[{"id":"A","weight_kg":10000,"from":0,"to":2},{"id":"B","weight_kg":5000,"from":1,"to":2}]}`
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost", strings.NewReader(body)))
	if rec.Code != http.StatusBadGateway {
		t.Errorf("HTTP %d %s; want 502", rec.Code, rec.Body.String())
	}
	// fx.EUR would rescale every euro amount: refused.
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost", strings.NewReader(`{"country_km":{"DE":100},"cargo_kg":10000,"truck":{"max_mass_kg":40000,"axles":5,"euro":6,"co2_class":1},"fx":{"EUR":2}}`)))
	if rec.Code != http.StatusBadRequest || !strings.Contains(rec.Body.String(), "fx.EUR") {
		t.Errorf("fx.EUR: HTTP %d %s; want 400", rec.Code, rec.Body.String())
	}
}

// A result that can't be written as JSON is a 500 with a message, not an
// empty 200.
func TestWriteJSONNotFinite(t *testing.T) {
	rec := httptest.NewRecorder()
	writeJSON(rec, http.StatusOK, map[string]float64{"total_eur": math.Inf(1)})
	if rec.Code != http.StatusInternalServerError || !strings.Contains(rec.Body.String(), "error") {
		t.Errorf("HTTP %d %q", rec.Code, rec.Body.String())
	}
}

// A body is one JSON object: more after it is refused, and one over the
// limit is 413.
func TestRequestBody(t *testing.T) {
	c, err := calculator(&sootcase.Client{BaseURL: "http://127.0.0.1:1"})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, DefaultTiles)
	trip := `{"country_km":{"DE":100},"cargo_kg":10000,"truck":{"max_mass_kg":40000,"axles":5,"euro":6,"co2_class":1}}`
	for _, tc := range []struct {
		name, body string
		want       int
	}{
		{"one object", trip + "\n", http.StatusOK},
		{"two objects", trip + trip, http.StatusBadRequest},
		{"too big", trip + strings.Repeat(" ", 8<<20), http.StatusRequestEntityTooLarge},
		{"no euro", strings.Replace(trip, `"euro":6,`, "", 1), http.StatusBadRequest},
		{"huge cargo", strings.Replace(trip, `"cargo_kg":10000`, `"cargo_kg":1e308`, 1), http.StatusBadRequest},
		{"huge kWh", strings.Replace(strings.Replace(trip, `"co2_class":1`, `"co2_class":5`, 1), `"cargo_kg":10000`, `"cargo_kg":10000,"electricity_kwh":1e308`, 1), http.StatusBadRequest},
		{"huge trips per year", strings.Replace(trip, `"cargo_kg":10000`, `"cargo_kg":10000,"trips_per_year":1e308,"compare_co2_classes":[5]`, 1), http.StatusBadRequest},
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost", strings.NewReader(tc.body)))
		if rec.Code != tc.want {
			t.Errorf("%s: HTTP %d %.200s; want %d", tc.name, rec.Code, rec.Body.String(), tc.want)
		}
	}
}

// calc -csv takes -shipment-rows (it isn't a trip's flag).
func TestCalcCSVShipmentRows(t *testing.T) {
	f := filepath.Join(t.TempDir(), "trips.csv")
	if err := os.WriteFile(f, []byte("country-km,cargo-kg,mass-kg,axles,euro,co2-class,date\n\"DE=100\",10000,40000,5,6,1,2026-11-03\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := calc([]string{"-csv", f, "-shipment-rows"}); err != nil {
		t.Fatal(err)
	}
}

// The CSV endpoints answer 413 for a body over their limit too.
func TestCSVBodyTooBig(t *testing.T) {
	c, err := calculator(&sootcase.Client{BaseURL: "http://127.0.0.1:1"})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, DefaultTiles)
	body := "country-km,cargo-kg\n" + strings.Repeat("\"DE=1\",1\n", 2<<20)
	for _, path := range []string{"/v1/carbon-cost/csv", "/v1/carbon-cost/report"} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("POST", path, strings.NewReader(body)))
		if rec.Code != http.StatusRequestEntityTooLarge {
			t.Errorf("%s: HTTP %d %.200s; want 413", path, rec.Code, rec.Body.String())
		}
	}
}

// A priced CSV row says when its fuel cost leaves litres out (diesel
// bought in Serbia has no price here), and the report counts such rows.
func TestCSVFuelComplete(t *testing.T) {
	c, err := calculator(&sootcase.Client{BaseURL: "http://127.0.0.1:1"})
	if err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	in := "country-km,cargo-kg,mass-kg,axles,euro,co2-class,date,fx\n\"DE=300,RS=300\",10000,40000,5,6,1,2026-11-03,RSD=117\n"
	if _, err := priceCSV(context.Background(), c.Calculate, nil, strings.NewReader(in), &out, calcFlagNames(), 0, false); err != nil {
		t.Fatal(err)
	}
	rows, _ := csv.NewReader(strings.NewReader(out.String())).ReadAll()
	if col := slices.Index(rows[0], "fuel_complete"); col < 0 || rows[1][col] != "false" {
		t.Fatalf("fuel_complete: %v", rows)
	}
	var rep bytes.Buffer
	if err := summarize([]io.Reader{strings.NewReader(out.String())}, &rep, nil); err != nil {
		t.Fatal(err)
	}
	r, _ := csv.NewReader(strings.NewReader(rep.String())).ReadAll()
	if col := slices.Index(r[0], "fuel_incomplete"); col < 0 || r[1][col] != "1" {
		t.Errorf("report: %v", r)
	}
}

package main

import (
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
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

package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/majidkabir/carbon-cost/sootcase"
)

func TestHandler(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/places" {
			if r.URL.Query().Get("q") != "hamb" || r.URL.Query().Get("limit") != "8" {
				w.WriteHeader(http.StatusTeapot)
				return
			}
			w.Write([]byte(`{"places":[{"id":"locode:DEHAM","code":"DEHAM","kinds":["port"],"name":"Hamburg","country":"DE","lat":53.55,"lon":9.99}]}`))
			return
		}
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(`{"error":"leg 1 from: unknown location \"XXXXX\""}`))
	}))
	defer fake.Close()
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, DefaultTiles)
	for _, tc := range []struct {
		method, path, body string
		status             int
		want               string
	}{
		{"GET", "/healthz", "", 200, "ok"},
		{"GET", "/", "", 200, "v1/carbon-cost"},
		{"GET", "/v1/rates", "", 200, `"country": "DK"`},
		{"GET", "/", "", 200, `const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";`},
		{"GET", "/leaflet/leaflet.js", "", 200, "Leaflet"},
		{"GET", "/v1/places?q=hamb", "", 200, `"code": "DEHAM"`},
		{"GET", "/v1/places?q=h", "", 200, `"places": []`},
		{"GET", "/v1/places?q=other", "", 502, "HTTP 418"},
		{"POST", "/v1/carbon-cost", `{"nope": 1}`, 400, "bad JSON"},
		{"POST", "/v1/carbon-cost", `{"cargo_kg": 1, "truck": {"max_mass_kg": 40000, "axles": 5, "euro": 6, "co2_class": 9}}`, 400, "co2_class"},
		{"POST", "/v1/carbon-cost", `{"from": {"code": "XXXXX"}, "to": {"code": "DEHAM"}, "cargo_kg": 1, "truck": {"max_mass_kg": 40000, "axles": 5, "euro": 6, "co2_class": 1}}`, 400, "unknown location"},
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body)))
		if rec.Code != tc.status || !strings.Contains(rec.Body.String(), tc.want) {
			t.Errorf("%s %s: %d %s; want %d containing %q", tc.method, tc.path, rec.Code, rec.Body.String(), tc.status, tc.want)
		}
	}
}

func TestFlagsParsing(t *testing.T) {
	if l, err := location("55.68, 12.57"); err != nil || l.Lat != 55.68 || l.Lon != 12.57 {
		t.Errorf("lat,lon: %+v %v", l, err)
	}
	if l, _ := location("dkcph"); l.Code != "DKCPH" {
		t.Errorf("code: %+v", l)
	}
	if _, err := location("91,0"); err == nil {
		t.Error("lat 91: want an error")
	}
	m, err := byCountry("dk=1, DE=0.9")
	if err != nil || m["DK"] != 1 || m["DE"] != 0.9 {
		t.Errorf("byCountry: %v %v", m, err)
	}
	if _, err := byCountry("DE"); err == nil {
		t.Error("DE without a number: want an error")
	}
}

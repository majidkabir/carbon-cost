package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/majidkabir/carbon-cost/cost"
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
		{"GET", "/v1/rates/dk/dk-2026-01-01.orct.json", "", 200, `"orct": "0.3"`},
		{"GET", "/v1/rates/dk/nope.orct.json", "", 404, "no such dataset"},
		{"GET", "/", "", 200, `const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";`},
		{"GET", "/leaflet/leaflet.js", "", 200, "Leaflet"},
		{"GET", "/v1/places?q=hamb", "", 200, `"code": "DEHAM"`},
		{"GET", "/v1/places?q=h", "", 200, `"places": []`},
		// One character, two bytes: still too short (minLength counts characters).
		{"GET", "/v1/places?q=%C3%98", "", 200, `"places": []`},
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
	m, err := byCountry("dk=1, DE=0.9", false)
	if err != nil || m["DK"] != 1 || m["DE"] != 0.9 {
		t.Errorf("byCountry: %v %v", m, err)
	}
	if _, err := byCountry("DE", false); err == nil {
		t.Error("DE without a number: want an error")
	}
}

// Sootcase limiting or refusing this server isn't the caller's fault.
func TestHandlerSootcaseStatus(t *testing.T) {
	status := 0
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		w.Write([]byte(`{"error":"x"}`))
	}))
	defer fake.Close()
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, "none")
	body := `{"from": {"code": "DKCPH"}, "to": {"code": "DEHAM"}, "cargo_kg": 1, "truck": {"max_mass_kg": 40000, "axles": 5, "euro": 6, "co2_class": 1}}`
	for in, want := range map[int]int{400: 400, 422: 400, 401: 502, 403: 502, 429: 503, 500: 502} {
		status = in
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost", strings.NewReader(body)))
		if rec.Code != want {
			t.Errorf("sootcase %d: got %d, want %d", in, rec.Code, want)
		}
	}
}

// A request or a batch's trip that fails by a bug is a 500 or that
// trip's error, not a dropped connection or a stopped server.
func TestPanicsRecovered(t *testing.T) {
	h := recovered(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { panic("boom") }))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/v1/x", nil))
	if rec.Code != 500 || !strings.Contains(rec.Body.String(), "internal error: boom") {
		t.Errorf("handler: %d %s", rec.Code, rec.Body.String())
	}
	out := priceAll(context.Background(), func(_ context.Context, r cost.Request) (cost.Response, error) {
		if r.CargoKg == 2 {
			panic("boom")
		}
		return cost.Response{}, nil
	}, []cost.Request{{CargoKg: 1}, {CargoKg: 2}})
	if out[0].Result == nil || !strings.Contains(out[1].Error, "internal error: boom") {
		t.Errorf("batch: %+v", out)
	}
}

// Every dataset /v1/rates lists is there at /v1/rates/{cc}/{file}, used
// as the API description says (file: the name after the country folder).
func TestRatesAsDocumented(t *testing.T) {
	c, err := calculator(&sootcase.Client{BaseURL: "http://127.0.0.1:1"})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, DefaultTiles)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/v1/rates", nil))
	var list []struct {
		Country string `json:"country"`
		File    string `json:"file"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &list); err != nil || len(list) == 0 {
		t.Fatalf("%v: %.200s", err, rec.Body.String())
	}
	for _, d := range list {
		cc, name, _ := strings.Cut(d.File, "/")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("GET", "/v1/rates/"+cc+"/"+name, nil))
		if rec.Code != 200 {
			t.Errorf("%s (%s): GET /v1/rates/%s/%s: %d", d.File, d.Country, cc, name, rec.Code)
		}
	}
}

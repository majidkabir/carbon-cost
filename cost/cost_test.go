package cost

import (
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// cphHam is Copenhagen -> Hamburg via Rødby-Puttgarden as Sootcase would
// return it: 140 km in DK, 19 km ferry, 141 km in DE.
var cphHam = sootcase.Result{TTWKg: 250, WTWKg: 300, Legs: []sootcase.LegResult{{
	DistanceKm: 300, TTWKg: 250, WTWKg: 300,
	RouteParts: map[string]float64{"ferry": 19},
	CountryKm:  map[string]float64{"DK": 140, "DE": 141},
	Parts:      []sootcase.Part{{Kind: "ferry", DistanceKm: 19, TTWKg: 30, WTWKg: 36}},
}}}

var truck40 = rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}

func all(t *testing.T) []rates.Table {
	t.Helper()
	tbs, err := rates.All()
	if err != nil {
		t.Fatal(err)
	}
	return tbs
}

func line(r Response, charge, country, comp string) (Line, bool) {
	for _, l := range r.Lines {
		if l.Charge == charge && l.Country == country && l.Component == comp {
			return l, true
		}
	}
	return Line{}, false
}

// Worked by hand, 40 t, 5 axles, Euro VI, CO2 class 1, 3 Nov 2026, EUA
// at 75 EUR/t:
//
//	DK 140 km x (0.44 + 0.60 + 0.06) DKK = 61.60 + 84.00 + 8.40 = 154.00 DKK
//	DE 141 km x (0.155 + 0.023 + 0.012 + 0.158) EUR
//	   = 21.855 + 3.243 + 1.692 + 22.278 = 49.068 EUR
//	ferry 30 kg CO2e x 100% x 75 EUR/t = 2.25 EUR
func TestPrice_CopenhagenHamburg(t *testing.T) {
	req := Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75}
	r, err := Price(cphHam, all(t), req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		charge, country, comp string
		amount, eur           float64
		carbon                bool
	}{
		{RoadToll, "DK", rates.Infrastructure, 61.60, 8.26, false},
		{RoadToll, "DK", rates.CO2, 84.00, 11.26, true},
		{RoadToll, "DK", rates.AirNoise, 8.40, 1.13, false},
		{RoadToll, "DE", rates.Infrastructure, 21.86, 21.86, false},
		{RoadToll, "DE", rates.Air, 3.24, 3.24, false},
		{RoadToll, "DE", rates.Noise, 1.69, 1.69, false},
		{RoadToll, "DE", rates.CO2, 22.28, 22.28, true},
		{FerryETS, "", "", 2.25, 2.25, true},
	} {
		l, ok := line(r, tc.charge, tc.country, tc.comp)
		if !ok {
			t.Errorf("no %s %s %s line", tc.charge, tc.country, tc.comp)
			continue
		}
		if l.Amount != tc.amount || l.AmountEUR != tc.eur || l.Carbon != tc.carbon {
			t.Errorf("%s %s %s: %v %s = EUR %v (carbon %v), want %v = EUR %v (%v)",
				tc.charge, tc.country, tc.comp, l.Amount, l.Currency, l.AmountEUR, l.Carbon, tc.amount, tc.eur, tc.carbon)
		}
	}
	if len(r.Lines) != 8 {
		t.Errorf("%d lines, want 8", len(r.Lines))
	}
	if r.CarbonEUR != 35.79 || math.Abs(r.TotalEUR-71.97) > 1e-9 {
		t.Errorf("total EUR %v, carbon EUR %v; want 71.97 and 35.79", r.TotalEUR, r.CarbonEUR)
	}
	if r.FerryKm != 19 || r.CountryKm["DK"] != 140 || len(r.Sources) < 3 || len(r.NoRates) != 0 {
		t.Errorf("response %+v", r)
	}
}

func TestPrice_Options(t *testing.T) {
	tbs := all(t)
	nov26 := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)

	// Tolled share, environmental zone km, no EUA price.
	r, err := Price(cphHam, tbs, Request{CargoKg: 1, Truck: truck40, TolledShare: map[string]float64{"DE": 0.5},
		EnvZoneKm: map[string]float64{"DK": 4}}, nov26)
	if err != nil {
		t.Fatal(err)
	}
	if l, _ := line(r, RoadToll, "DE", rates.CO2); l.Km != 70.5 {
		t.Errorf("DE tolled km %v, want 70.5", l.Km)
	}
	if l, ok := line(r, RoadToll, "DK", rates.EnvZoneSurcharge); !ok || l.Amount != 2.20 {
		t.Errorf("DK zone surcharge %+v, want 4 km x 0.55 = 2.20 DKK", l)
	}
	if _, ok := line(r, FerryETS, "", ""); ok || !hasNote(r, "eua_eur_per_t") {
		t.Errorf("no EUA price: want no ferry line and a note, got %v", r.Notes)
	}

	// A zero-emission truck in 2026: DK class 5 rate, DE exempt.
	zev := truck40
	zev.CO2Class = 5
	r, err = Price(cphHam, tbs, Request{CargoKg: 1, Truck: zev}, nov26)
	if err != nil {
		t.Fatal(err)
	}
	if l, _ := line(r, RoadToll, "DK", rates.Infrastructure); l.Rate != 0.11 {
		t.Errorf("DK class 5 infrastructure %v, want 0.11", l.Rate)
	}
	if _, ok := line(r, RoadToll, "DE", rates.Infrastructure); ok || !hasNote(r, "30 June 2031") {
		t.Errorf("DE zero-emission: want exempt, got lines %v notes %v", r.Lines, r.Notes)
	}

	// 2028: ETS2 on the road fuel; no DK table yet.
	r, err = Price(cphHam, tbs, Request{CargoKg: 1, Truck: truck40, ETS2EurPerT: 45}, time.Date(2028, 3, 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if l, ok := line(r, ETS2, "", ""); !ok || l.TonnesCO2 != 0.22 || l.Amount != 9.90 {
		t.Errorf("ETS2 %+v, want 0.22 t x 45 = 9.90 EUR", l)
	}
	if len(r.NoRates) != 1 || r.NoRates[0] != "DK" {
		t.Errorf("no rates %v, want DK", r.NoRates)
	}

	// A 2025 ferry crossing: 70% of emissions under the ETS.
	r, _ = Price(cphHam, tbs, Request{CargoKg: 1, Truck: truck40, EUAEurPerT: 100}, time.Date(2025, 5, 1, 0, 0, 0, 0, time.UTC))
	if l, _ := line(r, FerryETS, "", ""); l.Amount != 2.10 {
		t.Errorf("2025 ferry ETS %v, want 0.03 t x 70%% x 100 = 2.10", l.Amount)
	}

	// No country split from an old Sootcase.
	old := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300}}}
	if _, err := Price(old, tbs, Request{CargoKg: 1, Truck: truck40}, nov26); err == nil || !strings.Contains(err.Error(), "v0.9.0") {
		t.Errorf("want an error naming the Sootcase version, got %v", err)
	}
	// Bad input.
	if _, err := Price(cphHam, tbs, Request{CargoKg: 1, Truck: truck40, TolledShare: map[string]float64{"DE": 2}}, nov26); err == nil {
		t.Error("tolled_share 2: want an error")
	}
}

func hasNote(r Response, s string) bool {
	for _, n := range r.Notes {
		if strings.Contains(n, s) {
			return true
		}
	}
	return false
}

func TestCalculate_CallsSootcase(t *testing.T) {
	var got sootcase.Shipment
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/calculate" || r.URL.Query().Get("country_km") != "true" || r.Header.Get("Authorization") != "Bearer k" {
			http.Error(w, `{"error":"bad request to fake"}`, http.StatusBadRequest)
			return
		}
		_ = json.NewDecoder(r.Body).Decode(&got)
		_ = json.NewEncoder(w).Encode(cphHam)
	}))
	defer srv.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL, APIKey: "k"}, Tables: all(t),
		Now: func() time.Time { return time.Date(2026, 11, 3, 15, 0, 0, 0, time.UTC) }}
	r, err := c.Calculate(context.Background(), Request{From: sootcase.Location{Code: "DKCPH"}, To: sootcase.Location{Code: "DEHAM"},
		CargoKg: 20000, Truck: truck40})
	if err != nil {
		t.Fatal(err)
	}
	if r.Date != "2026-11-03" || len(r.Lines) != 7 {
		t.Errorf("date %s, %d lines", r.Date, len(r.Lines))
	}
	if len(got.Legs) != 1 || got.Legs[0].VehicleType != DefaultVehicleType || got.WeightKg != 20000 || got.AddRoadLegs == nil || *got.AddRoadLegs {
		t.Errorf("sent %+v", got)
	}
	c.Sootcase.APIKey = ""
	if _, err := c.Calculate(context.Background(), Request{CargoKg: 1, Truck: truck40}); err == nil || !strings.Contains(err.Error(), "HTTP 400") {
		t.Errorf("want Sootcase's 400 passed on, got %v", err)
	}
}

// Worked by hand from TestPrice_CopenhagenHamburg (class 1: EUR 71.97):
//
//	class 4: DK 140 km x (0.22 + 0.30 + 0.06) DKK = EUR 4.13 + 5.63 + 1.13
//	         DE 141 km x (0.155 + 0.023 + 0.012 + 0.079) = EUR 21.86 + 3.24 + 1.69 + 11.14
//	         ferry EUR 2.25; total 51.07, tolls 48.82, saving 20.90
//	class 5: DK 140 km x (0.11 + 0 + 0.02) DKK = EUR 2.06 + 0 + 0.38; DE exempt
//	         ferry EUR 2.25; total 4.69, tolls 2.44, saving 67.28
func TestPrice_Compare(t *testing.T) {
	req := Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75, CompareCO2Classes: []int{1, 4, 5}, TripsPerYear: 200}
	r, err := Price(cphHam, all(t), req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	want := []Comparison{
		{CO2Class: 1, TollEUR: 69.72, TotalEUR: 71.97, CarbonEUR: 35.79},
		{CO2Class: 4, TollEUR: 48.82, TotalEUR: 51.07, CarbonEUR: 19.02, SavingEUR: 20.90, SavingPerYearEUR: 4180},
		{CO2Class: 5, TollEUR: 2.44, TotalEUR: 4.69, CarbonEUR: 2.25, SavingEUR: 67.28, SavingPerYearEUR: 13456},
	}
	if len(r.Compare) != len(want) {
		t.Fatalf("compare %+v", r.Compare)
	}
	for i, w := range want {
		if r.Compare[i] != w {
			t.Errorf("class %d: got %+v, want %+v", w.CO2Class, r.Compare[i], w)
		}
	}
	// The requested truck's own lines are unchanged by the comparison.
	if r.TotalEUR != 71.97 || len(r.Lines) != 8 {
		t.Errorf("total %v with %d lines", r.TotalEUR, len(r.Lines))
	}

	// From 2028 a zero-emission truck pays no ETS2; diesel classes do.
	// Class 1 carbon: DE toll CO2 part 22.28 + ETS2 0.22 t x 45 = 9.90.
	r, err = Price(cphHam, all(t), Request{CargoKg: 1, Truck: truck40, ETS2EurPerT: 45, CompareCO2Classes: []int{1, 5}},
		time.Date(2028, 3, 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if r.Compare[0].CarbonEUR != 32.18 || r.Compare[1].CarbonEUR != 0 {
		t.Errorf("2028 carbon: class 1 %v, class 5 %v; want 32.18 and 0", r.Compare[0].CarbonEUR, r.Compare[1].CarbonEUR)
	}
	if _, err := Price(cphHam, all(t), Request{CargoKg: 1, Truck: truck40, CompareCO2Classes: []int{6}}, time.Now()); err == nil {
		t.Error("class 6: want an error")
	}
}

// Regional tolls are priced on Sootcase's region_km; country_km keeps the
// whole country.
func TestPrice_Regions(t *testing.T) {
	src := []rates.Source{{Title: "test", URL: "https://example.org"}}
	regional := func(region string, rate, co2 float64) rates.Table {
		return rates.Table{Country: "BE", Region: region, Currency: "EUR", ValidFrom: "2026-01-01", Name: region, Law: region + " law",
			Sources: src, MinKg: 3501, Rows: []rates.Row{{Component: "toll", Rate: rate}, {Component: rates.CO2, Rate: co2}}}
	}
	tbs := []rates.Table{regional("BE-VLG", 0.2, 0.05), regional("BE-WAL", 0.17, 0)}
	trip := sootcase.Result{TTWKg: 100, Legs: []sootcase.LegResult{{DistanceKm: 150,
		CountryKm: map[string]float64{"BE": 100, "FR": 50},
		RegionKm:  map[string]float64{"BE-VLG": 60, "BE-WAL": 38, "BE-BRU": 2}}}}
	nov26 := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)

	r, err := Price(trip, tbs, Request{CargoKg: 1, Truck: truck40, TolledShare: map[string]float64{"BE-WAL": 0.5}}, nov26)
	if err != nil {
		t.Fatal(err)
	}
	// VLG 60 km x (0.20 + 0.05) = 12 + 3; WAL 19 km x 0.17 = 3.23.
	for _, tc := range []struct {
		region, comp string
		km, amount   float64
	}{
		{"BE-VLG", "toll", 60, 12}, {"BE-VLG", rates.CO2, 60, 3}, {"BE-WAL", "toll", 19, 3.23},
	} {
		var found bool
		for _, l := range r.Lines {
			if l.Region == tc.region && l.Component == tc.comp {
				found = true
				if l.Country != "BE" || l.Km != tc.km || l.Amount != tc.amount {
					t.Errorf("%s %s: %+v, want %v km, %v EUR", tc.region, tc.comp, l, tc.km, tc.amount)
				}
			}
		}
		if !found {
			t.Errorf("no %s %s line", tc.region, tc.comp)
		}
	}
	if r.CountryKm["BE"] != 100 || r.RegionKm["BE-VLG"] != 60 || r.CarbonEUR != 3 {
		t.Errorf("country_km %v, region_km %v, carbon %v", r.CountryKm, r.RegionKm, r.CarbonEUR)
	}
	// Brussels has no table here, France none at all.
	if strings.Join(r.NoRates, ",") != "BE-BRU,FR" {
		t.Errorf("no_rates %v, want BE-BRU,FR", r.NoRates)
	}

	// A country-wide tolled_share applies to all its regions.
	r, _ = Price(trip, tbs, Request{CargoKg: 1, Truck: truck40, TolledShare: map[string]float64{"BE": 0.5}}, nov26)
	for _, l := range r.Lines {
		if l.Region == "BE-VLG" && l.Km != 30 {
			t.Errorf("BE share 0.5: VLG km %v, want 30", l.Km)
		}
	}

	// An older Sootcase without region_km: Belgium can't be split.
	old := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{"BE": 100}}}}
	r, err = Price(old, tbs, Request{CargoKg: 1, Truck: truck40}, nov26)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Lines) != 0 || strings.Join(r.NoRates, ",") != "BE" || !hasNote(r, "region_km") {
		t.Errorf("no region_km: lines %v, no_rates %v, notes %v", r.Lines, r.NoRates, r.Notes)
	}
}

// Copenhagen-Hamburg over Rødby-Puttgarden with the ferries' own MRV
// data, worked by hand: MRV 2025 136.53 g CO2e/t·nm x (15 t truck + 20 t
// cargo) x 18.976 km / 1.852 = 10.246 nm -> 0.04896 t x 75 EUR = 3.67 EUR
// (against 0.030 t x 75 = 2.25 EUR from the fixture's default part).
func TestPrice_FerryMRV(t *testing.T) {
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	trip := cphHam
	trip.Legs = []sootcase.LegResult{cphHam.Legs[0]}
	trip.Legs[0].RouteParts = map[string]float64{"ferry": 18.976}
	trip.Legs[0].Path = [][2]float64{{12.57, 55.68}, {11.355, 54.66}, {11.2276, 54.5001}, {9.99, 53.55}}
	nov26 := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)
	tr := truck40
	tr.TareKg = 15000

	r, err := PriceWith(trip, all(t), &fd, Request{CargoKg: 20000, Truck: tr, EUAEurPerT: 75}, nov26)
	if err != nil {
		t.Fatal(err)
	}
	l, ok := line(r, FerryETS, "", "")
	if !ok || l.TonnesCO2 != 0.049 || l.Amount != 3.67 || !strings.Contains(l.Source, "EU MRV 2025") || r.FerryCrossing != "Rødby–Puttgarden" {
		t.Errorf("ferry line %+v, crossing %q", l, r.FerryCrossing)
	}
	if !hasNote(r, "Baltic Whale") {
		t.Errorf("want the note on the ferry without MRV data, got %v", r.Notes)
	}

	// No tare: the default part, and a note saying what tare would do.
	r, _ = PriceWith(trip, all(t), &fd, Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75}, nov26)
	if l, _ := line(r, FerryETS, "", ""); l.Amount != 2.25 || !hasNote(r, "tare_kg") {
		t.Errorf("no tare: %+v, notes %v", l, r.Notes)
	}
	// An unknown crossing: the default part.
	trip.Legs[0].Path = [][2]float64{{10.0, 57.5}, {10.5, 58.0}}
	r, _ = PriceWith(trip, all(t), &fd, Request{CargoKg: 20000, Truck: tr, EUAEurPerT: 75}, nov26)
	if l, _ := line(r, FerryETS, "", ""); l.Amount != 2.25 || r.FerryCrossing != "" || !hasNote(r, "isn't one") {
		t.Errorf("unknown crossing: %+v, notes %v", l, r.Notes)
	}
}

package cost

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/roads"
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
		// BEHG: the DE road km's share of the road fuel, 0.11 t x EUR 65.
		{FuelCO2, "DE", rates.CO2, 7.18, 7.18, true},
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
	if len(r.Lines) != 9 {
		t.Errorf("%d lines, want 9", len(r.Lines))
	}
	if r.CarbonEUR != 42.97 || math.Abs(r.TotalEUR-79.15) > 1e-9 {
		t.Errorf("total EUR %v, carbon EUR %v; want 79.15 and 42.97", r.TotalEUR, r.CarbonEUR)
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
	if r.Date != "2026-11-03" || len(r.Lines) != 8 {
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

// Worked by hand from TestPrice_CopenhagenHamburg (class 1: EUR 79.15):
//
//	class 4: DK 140 km x (0.22 + 0.30 + 0.06) DKK = EUR 4.13 + 5.63 + 1.13
//	         DE 141 km x (0.155 + 0.023 + 0.012 + 0.079) = EUR 21.86 + 3.24 + 1.69 + 11.14
//	         ferry EUR 2.25, fuel CO2 EUR 7.18; total 58.25, tolls 48.82, saving 20.90
//	class 5: DK 140 km x (0.11 + 0 + 0.02) DKK = EUR 2.06 + 0 + 0.38; DE exempt
//	         ferry EUR 2.25, no road fuel; total 4.69, tolls 2.44, saving 74.46
func TestPrice_Compare(t *testing.T) {
	req := Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75, CompareCO2Classes: []int{1, 4, 5}, TripsPerYear: 200}
	r, err := Price(cphHam, all(t), req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	want := []Comparison{
		{CO2Class: 1, TollEUR: 69.72, TotalEUR: 79.15, CarbonEUR: 42.97},
		{CO2Class: 4, TollEUR: 48.82, TotalEUR: 58.25, CarbonEUR: 26.2, SavingEUR: 20.90, SavingPerYearEUR: 4180},
		{CO2Class: 5, TollEUR: 2.44, TotalEUR: 4.69, CarbonEUR: 2.25, SavingEUR: 74.46, SavingPerYearEUR: 14892},
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
	if r.TotalEUR != 79.15 || len(r.Lines) != 9 {
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

// A Belgian trip on the real Viapass tables, by hand (>32 t Euro VI,
// class 1): VLG 60 km x 0.285 = 17.10; WAL 38 km x 0.205 = 7.79;
// BRU 2 km, half on the motorway: 1 x 0.171 + 1 x 0.271 = 0.17 + 0.27.
func TestPrice_Belgium(t *testing.T) {
	trip := sootcase.Result{TTWKg: 100, Legs: []sootcase.LegResult{{DistanceKm: 100,
		CountryKm: map[string]float64{"BE": 100},
		RegionKm:  map[string]float64{"BE-VLG": 60, "BE-WAL": 38, "BE-BRU": 2}}}}
	r, err := Price(trip, all(t), Request{CargoKg: 1, Truck: truck40, MotorwayShare: map[string]float64{"BE-BRU": 0.5}},
		time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]float64{}
	for _, l := range r.Lines {
		got[l.Region+"/"+l.Road] = l.Amount
	}
	want := map[string]float64{"BE-VLG/": 17.10, "BE-WAL/": 7.79, "BE-BRU/motorway": 0.17, "BE-BRU/other": 0.27}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s: %v, want %v (all %v)", k, got[k], v, got)
		}
	}
	if len(r.Lines) != 4 || r.TotalEUR != 25.33 || len(r.NoRates) != 0 {
		t.Errorf("%d lines, total %v, no_rates %v", len(r.Lines), r.TotalEUR, r.NoRates)
	}
	// Without motorway_share: Brussels at the non-motorway rate, with a note.
	r, _ = Price(trip, all(t), Request{CargoKg: 1, Truck: truck40}, time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC))
	for _, l := range r.Lines {
		if l.Region == "BE-BRU" && (l.Road != "other" || l.Km != 2) {
			t.Errorf("no share: Brussels line %+v", l)
		}
	}
	if !hasNote(r, "motorway_share.BE-BRU") {
		t.Errorf("notes %v", r.Notes)
	}
}

// Kufstein -> Brenner (A 12, A 13), 40 t, 5 axles, Euro VI, class 1, as a
// route through the section ends. The eight A 13 sections from Innsbruck/
// Amras to the border (§ 4 lit. h, j-p) charge, by day:
// 4.6574 + 2.2142 + 4.0924 + 4.4283 + 13.9721 + 11.2387 + 10.0858 + 1.9943
// = 52.6832 EUR; at night the § 5 amounts, 105.3664 EUR. Their km pay no
// per-km infrastructure; the A 12 stretch pays it +25% (§ 3).
func TestPrice_AustriaSections(t *testing.T) {
	pts := [][2]float64{{12.1870, 47.6070}, {12.1756, 47.5965}, {12.1408, 47.5675}, {12.0941, 47.5333}, {12.0572, 47.4950},
		{12.0235, 47.4838}, {11.8842, 47.4411}, {11.8032, 47.4028}, {11.7016, 47.3577}, {11.6792, 47.3307}, {11.5838, 47.2998},
		{11.5015, 47.2739}, {11.4764, 47.2710}, {11.4385, 47.2606}, {11.4202, 47.2547}, {11.3905, 47.2396}, {11.3934, 47.2276}, {11.4030, 47.2082},
		{11.3982, 47.1841}, {11.4497, 47.1195}, {11.4801, 47.0615}, {11.5065, 47.0152}, {11.5080, 47.0030}}
	var km float64
	for i := 0; i+1 < len(pts); i++ {
		km += haversine(pts[i][1], pts[i][0], pts[i+1][1], pts[i+1][0])
	}
	trip := sootcase.Result{TTWKg: 100, Legs: []sootcase.LegResult{{DistanceKm: km, CountryKm: map[string]float64{"AT": km}, Path: pts}}}
	nov26 := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	price := func(night bool) Response {
		r, err := Price(trip, all(t), Request{CargoKg: 1, Truck: truck40, Night: night}, nov26)
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	sum := func(r Response) (sections float64, n int, infraKm, a12 float64) {
		for _, l := range r.Lines {
			switch {
			case l.RateUnit == "EUR/section":
				sections += l.Amount
				n++
			case l.Component == rates.Infrastructure && l.Section == "":
				infraKm = l.Km
			case l.Section != "":
				a12 = l.Km
			}
		}
		return
	}
	s, n, infraKm, a12 := sum(price(false))
	if n != 8 || math.Abs(s-52.68) > 0.02 {
		t.Errorf("day: %d sections, EUR %.2f; want 8, 52.68", n, s)
	}
	secKm := 0.0
	for i := 14; i+1 < len(pts); i++ {
		secKm += haversine(pts[i][1], pts[i][0], pts[i+1][1], pts[i+1][0])
	}
	if math.Abs(infraKm-(km-secKm)) > 0.01 || math.Abs(a12-(km-secKm)) > 0.01 {
		t.Errorf("per-km infrastructure on %.1f km, A 12 surcharge on %.1f km; want both %.1f (total %.1f, sections %.1f)", infraKm, a12, km-secKm, km, secKm)
	}
	if s, _, _, _ := sum(price(true)); math.Abs(s-105.37) > 0.02 {
		t.Errorf("night: EUR %.2f, want 105.37", s)
	}
	// Air/noise and CO2 still per km on the whole Austrian distance.
	for _, l := range price(false).Lines {
		if l.Component == rates.CO2 && math.Abs(l.Km-km) > 0.01 {
			t.Errorf("CO2 on %.1f km, want %.1f", l.Km, km)
		}
	}
}

// Basel - Chiasso style trip: 280 km in Switzerland, 40 t Euro VI. LSVA is
// 2.39 Rappen per tonne-km (SVAV Art. 8): 0.0239 x 40 x 280 = CHF 267.68.
func TestSwitzerland(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"CH": 280, "LI": 20}}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	req := Request{CargoKg: 20000, Truck: truck40, FX: map[string]float64{"CHF": 0.93}}
	r, err := Price(trip, all(t), req, date)
	if err != nil {
		t.Fatal(err)
	}
	var ch, li Line
	for _, l := range r.Lines {
		switch l.Country {
		case "CH":
			ch = l
		case "LI":
			li = l
		}
	}
	if ch.Amount != 267.68 || ch.Tonnes != 40 || ch.Rate != 0.0239 || ch.RateUnit != "CHF/tkm" || ch.AmountEUR != 287.83 {
		t.Errorf("CH line %+v", ch)
	}
	if li.Amount != 19.12 {
		t.Errorf("LI line %+v", li)
	}
	// Euro V pays category 1, and the weight counts up to 40 t.
	heavy := req
	heavy.Truck = rates.Truck{MaxMassKg: 44000, Axles: 5, Euro: 5, CO2Class: 1}
	r, _ = Price(trip, all(t), heavy, date)
	for _, l := range r.Lines {
		if l.Country == "CH" && (l.Amount != round2(0.0326*40*280) || l.Tonnes != 40) {
			t.Errorf("Euro V 44 t: %+v", l)
		}
	}
	// Electric trucks are exempt.
	zev := req
	zev.Truck.CO2Class = 5
	if r, _ := Price(trip, all(t), zev, date); len(r.Lines) != 0 {
		t.Errorf("electric truck: %+v", r.Lines)
	}
	// Without fx the ECB rates are used, with a note; without either, an error.
	noFX := req
	noFX.FX = nil
	if _, err := Price(trip, all(t), noFX, date); err == nil || !strings.Contains(err.Error(), "fx.CHF") {
		t.Errorf("want an error asking for fx.CHF, got %v", err)
	}
	noFX.ecb.Date, noFX.ecb.PerEUR = "2026-11-03", map[string]float64{"CHF": 0.9312}
	r, err = Price(trip, all(t), noFX, date)
	if err != nil || !strings.Contains(strings.Join(r.Notes, " "), "0.9312 CHF per euro (ECB euro foreign exchange reference rates, 2026-11-03)") {
		t.Errorf("ECB rate note: %v %v", err, r.Notes)
	}
}

// Prague - Brno style: 200 km in Czechia, 40 t, 5 axles, Euro VI, CO2
// class 1: 5.9644 CZK/km on motorways (NV 240/2014 Annex 1 as of 2026).
// Then Poland, 300 km of A/S roads for 12 t+ min. EURO 5: 0.56 PLN/km.
func TestCzechiaPoland(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 500, CountryKm: map[string]float64{"CZ": 200, "PL": 300}}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	req := Request{CargoKg: 20000, Truck: truck40, FX: map[string]float64{"CZK": 24.3, "PLN": 4.25}}
	r, err := Price(trip, all(t), req, date)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]Line{}
	for _, l := range r.Lines {
		if l.Km > 0 {
			got[l.Country+"/"+l.Road] = l
		}
	}
	if l := got["CZ/motorway"]; l.Rate != 5.9644 || l.Amount != 1192.88 || l.Carbon {
		t.Errorf("CZ motorway %+v", l)
	}
	if l := got["PL/motorway"]; l.Rate != 0.56 || l.Amount != 168 || l.AmountEUR != 39.53 {
		t.Errorf("PL motorway %+v", l)
	}
	// Class I roads and a 3-axle 12 t+ CO2 class 4 truck: 2.0300 CZK/km.
	req.MotorwayShare = map[string]float64{"CZ": 0}
	req.Truck = rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 4}
	r, _ = Price(trip, all(t), req, date)
	for _, l := range r.Lines {
		if l.Country == "CZ" && l.Km > 0 && (l.Road != "other" || l.Rate != 2.0300) {
			t.Errorf("CZ class I road %+v", l)
		}
	}
	// A 10 t Euro III truck in Poland pays 0.70 PLN/km on A/S roads.
	req.Truck = rates.Truck{MaxMassKg: 10000, Axles: 2, Euro: 3, CO2Class: 1}
	r, _ = Price(trip, all(t), req, date)
	for _, l := range r.Lines {
		if l.Country == "PL" && l.Road == "motorway" && l.Rate != 0.70 {
			t.Errorf("PL 10 t Euro III %+v", l)
		}
	}
}

// Sofia - Plovdiv style: 130 km of Bulgarian motorway, 40 t, 5 axles.
// ПМС № 64/2026: Euro VI, CO2 class 1 pays 0.14 infrastructure + 0.07 CO2
// EUR/km; CO2 class 4, 0.14 + 0.03; zero-emission, 0.14 only.
func TestBulgaria(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 130, CountryKm: map[string]float64{"BG": 130}}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		truck         rates.Truck
		total, carbon float64
	}{
		{truck40, 27.3, 9.1},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 4}, 22.1, 3.9},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, 18.2, 0},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 5, CO2Class: 1}, 33.8, 9.1},
		{rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 18.2, 6.5},
		{rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 3, CO2Class: 1}, 14.3, 5.2},
	} {
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.total) > 0.005 || math.Abs(r.CarbonEUR-tc.carbon) > 0.005 {
			t.Errorf("%+v: total %.2f carbon %.2f, want %.2f and %.2f", tc.truck, r.TotalEUR, r.CarbonEUR, tc.total, tc.carbon)
		}
	}
}

// Unec - Postojna - Razdrto on the A1: two DarsGo sections, 11.375 and
// 9.56 km, both interurban and in the rail surcharge's tier a. A 5-axle
// (R4) Euro VI truck, CO2 class 1, pays per section its infrastructure
// price (3.156462 + 2.652116 EUR), the rail surcharge 0.040179 EUR/km and
// the external-cost charge 0.010 EUR/km on the official lengths.
func TestSlovenia(t *testing.T) {
	path := [][2]float64{{14.30, 45.83}, {14.2876, 45.8248}, {14.24, 45.79}, {14.1985, 45.7605}, {14.13, 45.76}, {14.075, 45.7593}, {14.07, 45.7592}}
	var dist float64
	for i := 1; i < len(path); i++ {
		dist += haversine(path[i-1][1], path[i-1][0], path[i][1], path[i][0])
	}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: dist, CountryKm: map[string]float64{"SI": dist}, Path: path}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40}, date)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]float64{}
	for _, l := range r.Lines {
		got[l.Component] += l.Amount
	}

	want := map[string]float64{
		"infrastructure": round2(3.156462) + round2(2.652116),
		"rail_surcharge": round2(11.375*0.040179) + round2(9.56*0.040179),
		"air_noise":      round2(11.375*0.010) + round2(9.56*0.010),
	}
	for k, v := range want {
		if math.Abs(got[k]-v) > 0.001 {
			t.Errorf("%s: %.2f, want %.2f (lines %+v)", k, got[k], v, r.Lines)
		}
	}
	if len(r.Lines) != 6 {
		t.Errorf("want 2 sections x 3 charges, got %d lines: %+v", len(r.Lines), r.Lines)
	}
	// A zero-emission truck pays the CO2 class 5 price and the zev rate.
	zev := truck40
	zev.CO2Class = 5
	r, _ = Price(trip, all(t), Request{CargoKg: 20000, Truck: zev}, date)
	var air float64
	for _, l := range r.Lines {
		if l.Component == "air_noise" {
			air += l.Amount
		}
	}
	if math.Abs(air-(round2(11.375*0.004)+round2(9.56*0.004))) > 0.001 {
		t.Errorf("zev external cost %.2f", air)
	}
	// A route that only crosses Slovenia elsewhere passes no section.
	off := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 10, CountryKm: map[string]float64{"SI": 10}, Path: [][2]float64{{14.9, 45.5}, {14.95, 45.52}}}}}
	r, _ = Price(off, all(t), Request{CargoKg: 1, Truck: truck40}, date)
	if len(r.Lines) != 0 || !strings.Contains(strings.Join(r.Notes, " "), "passes none of the tolled sections") {
		t.Errorf("off-network: %+v %v", r.Lines, r.Notes)
	}
}

// Bratislava - Žilina style: 200 km of Slovak motorway. NV 418/2024 Annex
// 5: a 5-axle Euro VI truck, CO2 class 1, pays 0.2677 EUR/km, of which
// 0.0240 CO2 and 0.0021 air (Annex 3); CO2 class 4, 0.2459 with 0.0040
// CO2; zero-emission, 0.2419 with no CO2.
func TestSlovakia(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 200, CountryKm: map[string]float64{"SK": 200}}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		truck         rates.Truck
		total, carbon float64
	}{
		{truck40, 53.54, 4.8},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 4}, 49.18, 0.8},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, 48.38, 0},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 5, CO2Class: 2}, 59.02, 8},
		{rates.Truck{MaxMassKg: 10000, Axles: 2, Euro: 3, CO2Class: 1}, 30.4, 5.6},
	} {
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.total) > 0.011 || math.Abs(r.CarbonEUR-tc.carbon) > 0.011 {
			t.Errorf("%+v: total %.2f carbon %.2f, want %.2f and %.2f", tc.truck, r.TotalEUR, r.CarbonEUR, tc.total, tc.carbon)
		}
	}
}

// Hungary, 200 km of expressway at 400 HUF/EUR: J5 EURO VI is
// 170.94/1.27 HUF infrastructure, the air and noise mix of 3.4 and 0.8
// eurocent, and 8.0 eurocent CO2 per km (25/2013 NFM § 1, annex 2).
func TestHungary(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 200, CountryKm: map[string]float64{"HU": 200}}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		truck         rates.Truck
		total, carbon float64
	}{
		{truck40, 84.84, 15.54},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 4}, 76.08, 7.77},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, 68.31, 0},
		{rates.Truck{MaxMassKg: 10000, Axles: 2, Euro: 3, CO2Class: 1}, 43.85, 7.77},
		{rates.Truck{MaxMassKg: 32000, Axles: 4, Euro: 5, CO2Class: 2}, 84.44, 13.02},
	} {
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, FX: map[string]float64{"HUF": 400}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.total) > 0.011 || math.Abs(r.CarbonEUR-tc.carbon) > 0.011 {
			t.Errorf("%+v: total %.2f carbon %.2f, want %.2f and %.2f", tc.truck, r.TotalEUR, r.CarbonEUR, tc.total, tc.carbon)
		}
	}
}

// Romania, 200 km at 5 RON/EUR: 12 t and over on motorways, EURO VI,
// 0.48 lei/km with 21% VAT (OMTI 959/2026).
func TestRomania(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 200, CountryKm: map[string]float64{"RO": 200}}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		truck rates.Truck
		total float64
	}{
		{truck40, 15.87},
		{rates.Truck{MaxMassKg: 10000, Axles: 2, Euro: 3, CO2Class: 1}, 12.23},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, 3.97},
	} {
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, FX: map[string]float64{"RON": 5}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.total) > 0.011 {
			t.Errorf("%+v: total %.2f, want %.2f", tc.truck, r.TotalEUR, tc.total)
		}
	}
	// Road classes from the route: 100 km motorway, 50 km national, 50
	// km local (untolled): 100 * 0.48/1.21 + 50 * 0.24/1.21 lei.
	req := Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"RON": 5}, roadKm: map[string]roads.Km{"RO": {Motorway: 100, National: 50, Local: 50}}}
	r, err := Price(trip, all(t), req, date)
	if err != nil {
		t.Fatal(err)
	}
	if math.Abs(r.TotalEUR-9.92) > 0.011 {
		t.Errorf("by route: total %.2f, want 9.92: %v", r.TotalEUR, r.Notes)
	}
}

// Croatia: Zagreb (Lučko) to Split on the A1, group IV, 83.70 EUR with
// 25% VAT; group III 55.20; the open station Bregana, group IV 3.30.
func TestCroatia(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	trip := func(path [][2]float64) sootcase.Result {
		return sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 400, CountryKm: map[string]float64{"HR": 400}, Path: path}}}
	}
	a1 := [][2]float64{{15.90, 45.80}, {15.88428, 45.74893}, {15.54862, 45.51211}, {16.57112, 43.59581}, {16.60, 43.55}}
	for _, tc := range []struct {
		path  [][2]float64
		truck rates.Truck
		total float64
	}{
		{a1, truck40, 66.96},
		{a1, rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}, 44.16},
		{[][2]float64{{15.69, 45.84}, {15.70462, 45.8393}, {15.72, 45.84}}, truck40, 2.64},
		{[][2]float64{{16.0, 46.5}, {16.1, 46.6}}, truck40, 0},
	} {
		r, err := Price(trip(tc.path), all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.total) > 0.011 {
			t.Errorf("%v %+v: total %.2f, want %.2f: %v", tc.path[1], tc.truck, r.TotalEUR, tc.total, r.Notes)
		}
	}
}

// Hungary with road classes from the route: 100 km of expressway, half
// of it suburban by its toll sections: J5 EURO VI air and noise 13.21
// HUF/km suburban, 3.11 interurban (3.4 and 0.8 eurocent at 388.60).
func TestHungarySuburban(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{"HU": 100}}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	req := Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"HUF": 400},
		roadKm: map[string]roads.Km{"HU": {Motorway: 100, MotorwayKnown: 100, MotorwaySub: 50}}}
	r, err := Price(trip, all(t), req, date)
	if err != nil {
		t.Fatal(err)
	}
	var sub, inter float64
	for _, l := range r.Lines {
		if l.Component == rates.AirNoise {
			switch l.Area {
			case rates.Suburban:
				sub = l.Km
			case rates.Interurban:
				inter = l.Km
			}
		}
	}
	if math.Abs(sub-50) > 0.01 || math.Abs(inter-50) > 0.01 {
		t.Errorf("suburban %.2f km, interurban %.2f km, want 50 and 50", sub, inter)
	}
	// 100 km: 170.94/1.27 + 50%*13.21 + 50%*3.11 + 31.09 HUF/km.
	if want := (134.5984 + 8.16 + 31.09) * 100 / 400; math.Abs(r.TotalEUR-want) > 0.02 {
		t.Errorf("total %.2f, want %.2f", r.TotalEUR, want)
	}
}

// Storebælt: a 16.5 m truck (10-20 m) pays 1,020 DKK with VAT, 816
// without; on a Storebælt Erhverv agreement EURO VI gets 13% off; over 20
// m 1,224. Øresund: 1,324 DKK, or 580 with ØresundBUSINESS.
func TestDanishBridges(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	storebaelt := [][2]float64{{11.0, 55.34}, {11.10876, 55.34993}, {11.2, 55.36}}
	oresund := [][2]float64{{12.65, 55.62}, {12.84879, 55.57047}, {13.0, 55.56}}
	bridge := func(r Response) float64 {
		for _, l := range r.Lines {
			if l.Component == rates.Toll && strings.Contains(l.Section, "bridge") {
				return l.Amount
			}
		}
		return 0
	}
	for _, tc := range []struct {
		path  [][2]float64
		truck rates.Truck
		etc   bool
		want  float64
	}{
		{storebaelt, truck40, false, 816},
		{storebaelt, truck40, true, 709.92},
		{storebaelt, rates.Truck{MaxMassKg: 60000, Axles: 7, Euro: 6, CO2Class: 1, LengthM: 25.25}, false, 1224},
		{storebaelt, rates.Truck{MaxMassKg: 12000, Axles: 2, Euro: 5, CO2Class: 1, LengthM: 9}, true, 516},
		{oresund, truck40, false, 1324},
		{oresund, truck40, true, 580},
		{[][2]float64{{9.0, 55.0}, {9.1, 55.1}}, truck40, false, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 30, CountryKm: map[string]float64{"DK": 30}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, ETC: tc.etc}, date)
		if err != nil {
			t.Fatal(err)
		}
		if got := bridge(r); math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%v %+v etc %v: bridge %.2f DKK, want %.2f: %v", tc.path[1], tc.truck, tc.etc, got, tc.want, r.Notes)
		}
	}
}

// Croatia with ENC: Zagreb-Split, EURO VI, 21.74% + 7% off 66.96; the
// Istrian Y from Umag to Pula, group IV, 31.40 EUR with VAT (25.12
// without), 30% off with ENC PLUS.
func TestCroatiaDiscounts(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	trip := func(path [][2]float64) sootcase.Result {
		return sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 400, CountryKm: map[string]float64{"HR": 400}, Path: path}}}
	}
	a1 := [][2]float64{{15.90, 45.80}, {15.88428, 45.74893}, {15.54862, 45.51211}, {16.57112, 43.59581}, {16.60, 43.55}}
	istria := [][2]float64{{13.60, 45.43}, {13.61752, 45.42442}, {13.80706, 45.11216}, {13.88653, 44.90411}, {13.86, 44.87}}
	for _, tc := range []struct {
		path  [][2]float64
		etc   bool
		total float64
	}{
		{a1, true, 66.96 * (1 - 0.2874)},
		{istria, false, 25.12},
		{istria, true, 25.12 * 0.7},
	} {
		r, err := Price(trip(tc.path), all(t), Request{CargoKg: 1000, Truck: truck40, ETC: tc.etc}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.total) > 0.011 {
			t.Errorf("%v etc %v: total %.2f, want %.2f: %v", tc.path[1], tc.etc, r.TotalEUR, tc.total, r.Notes)
		}
	}
}

// Serbia: Beograd to Niš jug, category 4, 60.50 EUR; Dimitrovgrad to
// Beograd 93.00; category 3 Beograd to Niš jug 30.50.
func TestSerbia(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	trip := func(path [][2]float64) sootcase.Result {
		return sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"RS": 300}, Path: path}}}
	}
	bgNis := [][2]float64{{20.60, 44.70}, {20.61189, 44.66423}, {21.81577, 43.32747}, {21.85, 43.30}}
	dimBg := [][2]float64{{22.75, 43.01}, {22.73643, 43.02192}, {21.9, 43.35}, {20.61189, 44.66423}, {20.60, 44.70}}
	for _, tc := range []struct {
		path  [][2]float64
		truck rates.Truck
		total float64
	}{
		{bgNis, truck40, 60.5},
		{dimBg, truck40, 93},
		{bgNis, rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 30.5},
	} {
		r, err := Price(trip(tc.path), all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.total) > 0.011 {
			t.Errorf("%v %+v: total %.2f, want %.2f: %v", tc.path[1], tc.truck, r.TotalEUR, tc.total, r.Notes)
		}
	}
}

// France, chained: Allaines to Ambérieu on APRR, class 4, 190.70 EUR
// with VAT (158.92 without); class 3 143.00 (119.17).
func TestFrance(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 470, CountryKm: map[string]float64{"FR": 470},
		Path: [][2]float64{{1.80, 48.25}, {1.84618, 48.20516}, {5.31252, 45.97777}, {5.35, 45.95}}}}}
	for _, tc := range []struct {
		truck rates.Truck
		total float64
	}{
		{truck40, 158.92},
		{rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 119.17},
	} {
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.total) > 0.011 {
			t.Errorf("%+v: total %.2f, want %.2f: %v %v", tc.truck, r.TotalEUR, tc.total, r.Lines, r.Notes)
		}
	}
}

// A toll booth on an exit the route only drives past (R, 0.1 km off the
// road) has a short priced pair to the barrier B; taking it would leave
// B's long ticket to N unused.
func TestChainBoothBeside(t *testing.T) {
	at := func(lon float64) []rates.Place { return []rates.Place{{Name: "p", Lat: 45, Lon: lon}} }
	sys := rates.TollSystem{Chain: true, Groups: []rates.Group{{Name: "4", MinKg: 3501}},
		Stations: []rates.Station{{Name: "R", Points: []rates.Place{{Name: "p", Lat: 45.001, Lon: 0.0}}}, {Name: "B", Points: at(0.02)},
			{Name: "P", Points: at(0.3)}, {Name: "N", Points: at(2.0)}},
		Prices: map[string]map[string]float64{"R|B": {"4": 2.25}, "P|N": {"4": 39.25}, "B|N": {"4": 52.17}}}
	route := [][2]float64{{-0.1, 45}, {2.1, 45}}
	got := chainUses(sys, newTrack(route), truck40, false)
	if len(got) != 1 || got[0].entry != "B" || got[0].exit != "N" {
		t.Errorf("got %+v, want one ticket B-N", got)
	}
	// Where two networks meet, the next ticket starts at the other
	// network's station at the same place (P2 beside P).
	sys.Stations = append(sys.Stations, rates.Station{Name: "P2", Points: at(0.3)})
	sys.Prices = map[string]map[string]float64{"B|P": {"4": 5}, "P2|N": {"4": 30}}
	got = chainUses(sys, newTrack(route), truck40, false)
	if len(got) != 2 || got[0].entry != "B" || got[0].exit != "P" || got[1].entry != "P2" || got[1].exit != "N" {
		t.Errorf("got %+v, want B-P, P2-N", got)
	}
	// A barrier across the road (X) and an exit's booth beside it (Y) at
	// the same place: a trip driving through takes its ticket at X.
	sys.Stations = []rates.Station{{Name: "Y", Points: []rates.Place{{Name: "p", Lat: 45.002, Lon: 0.4999}}}, {Name: "X", Points: at(0.5)}, {Name: "N", Points: at(2.0)}}
	sys.Prices = map[string]map[string]float64{"Y|N": {"4": 36}, "X|N": {"4": 42}}
	got = chainUses(sys, newTrack(route), truck40, false)
	if len(got) != 1 || got[0].entry != "X" {
		t.Errorf("got %+v, want X-N", got)
	}
	// A barrier priced on its own (Z|Z) pays when passed outside a
	// ticket, not inside one.
	sys.Stations = append(sys.Stations, rates.Station{Name: "Z", Points: at(1.0)}, rates.Station{Name: "W", Points: at(2.08)})
	sys.Prices["Z|Z"] = map[string]float64{"4": 12.4}
	sys.Prices["W|W"] = map[string]float64{"4": 5}
	got = chainUses(sys, newTrack(route), truck40, false)
	if len(got) != 2 || got[0].entry != "X" || got[1].entry != "W" || got[1].exit != "W" {
		t.Errorf("got %+v, want X-N and W-W", got)
	}
}

func TestAlpineTunnels(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	frejus := [][2]float64{{6.60, 45.20}, {6.67415, 45.19439}, {6.70, 45.15}}
	montBlanc := [][2]float64{{6.85, 45.92}, {6.86072, 45.90100}, {6.90, 45.85}}
	for _, tc := range []struct {
		path  [][2]float64
		name  string
		truck rates.Truck
		want  float64
	}{
		{frejus, "Fréjus", truck40, 337.33},
		{frejus, "Fréjus", rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 167.92},
		{montBlanc, "Mont Blanc", truck40, 337.33},
	} {
		path := tc.path
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 12, CountryKm: map[string]float64{"FR": 12}, Path: path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, tc.name) {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%s %+v: %.2f, want %.2f: %v", tc.name, tc.truck, got, tc.want, r.Lines)
		}
	}
}

// Atlandes prices its two A63 barriers by EURO class; the pairs of the
// other French operators fall back on classes 3 and 4.
func TestAtlandesEuro(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	path := [][2]float64{{-0.86, 44.40}, {-0.8603, 44.3470}, {-1.1803, 43.8351}, {-1.19, 43.80}}
	for _, tc := range []struct {
		truck rates.Truck
		want  float64
	}{
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, 2 * 21.50 / 1.2},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 3, CO2Class: 1}, 2 * 23.40 / 1.2},
		{rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 4, CO2Class: 1}, 2 * 17.80 / 1.2},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 70, CountryKm: map[string]float64{"FR": 70}, Path: path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Atlandes") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%+v: %.2f, want %.2f: %v", tc.truck, got, tc.want, r.Lines)
		}
	}
}

// Latvia's road user charge is time-based: one day's rate per trip,
// whatever the km.
func TestLatviaPerDay(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		truck rates.Truck
		want  float64
	}{
		{truck40, 22},
		{rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 5, CO2Class: 1}, 19},
		{rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}, 10},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, 0},
	} {
		for _, km := range []float64{20, 300} {
			trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: km, CountryKm: map[string]float64{"LV": km}}}}
			r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
			if err != nil {
				t.Fatal(err)
			}
			got := 0.0
			for _, l := range r.Lines {
				if l.Country == "LV" {
					got += l.Amount
					if l.RateUnit != "EUR/day" {
						t.Errorf("rate unit %q", l.RateUnit)
					}
				}
			}
			if got != tc.want {
				t.Errorf("%+v, %.0f km: %.2f, want %.2f: %v", tc.truck, km, got, tc.want, r.Lines)
			}
		}
	}
}

// Estonia, Sweden and Luxembourg count the combination's axles; Lithuania the motor
// vehicle's.
func TestEstoniaLithuaniaPerDay(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		cc    string
		truck rates.Truck
		want  float64
	}{
		{"EE", truck40, 22},
		{"EE", rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, 10},
		{"EE", rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 4, CO2Class: 1}, 16},
		{"EE", rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 3, CO2Class: 1}, 13},
		{"LT", truck40, 23},
		{"LT", rates.Truck{MaxMassKg: 40000, Axles: 5, MotorAxles: 2, Euro: 6, CO2Class: 1}, 13},
		{"LT", rates.Truck{MaxMassKg: 32000, Axles: 4, MotorAxles: 4, Euro: 5, CO2Class: 1}, 25},
		{"LT", rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 0, CO2Class: 1}, 29},
		{"SE", truck40, 147},
		{"SE", rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, 45},
		{"SE", rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 5, CO2Class: 1}, 90},
		{"SE", rates.Truck{MaxMassKg: 11990, Axles: 2, Euro: 5, CO2Class: 1}, 0},
		{"LU", truck40, 13},
		{"LU", rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 4, CO2Class: 1}, 9},
		{"LU", rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, 4},
		{"GB", truck40, 9.67},
		{"GB", rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 5, CO2Class: 1}, 4.18},
		{"GB", rates.Truck{MaxMassKg: 44000, Axles: 6, Euro: 6, CO2Class: 5}, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 150, CountryKm: map[string]float64{tc.cc: 150}}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, FX: map[string]float64{"SEK": 11, "GBP": 0.87}}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == tc.cc {
				got += l.Amount
			}
		}
		if got != tc.want {
			t.Errorf("%s %+v: %.2f, want %.2f: %v", tc.cc, tc.truck, got, tc.want, r.Lines)
		}
	}
}

// Norway's toll stations: priced per passage in the charged direction,
// once per hour-rule group.
func TestNorwayTollPoints(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	sandvikenSE := [][2]float64{{5.3110, 60.4190}, {5.3150, 60.4170}}
	straumeNE := [][2]float64{{5.2697, 60.3220}, {5.2723, 60.3232}}
	reverse := func(p [][2]float64) [][2]float64 { return [][2]float64{p[1], p[0]} }
	for _, tc := range []struct {
		name string
		path [][2]float64
		want float64
	}{
		{"Sandviken, charged direction", sandvikenSE, 88},
		{"Sandviken, other direction", reverse(sandvikenSE), 0},
		{"Sandviken and Straume, one hour-rule group", append(append([][2]float64{}, sandvikenSE...), straumeNE...), 88},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 20, CountryKm: map[string]float64{"NO": 20}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"NOK": 11.7}}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "NO" {
				got += l.Amount
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// Ireland's toll plazas: PPP roads by axles (excluding VAT), the M50 by
// weight, at the tag price for trucks paying by tag.
func TestIrelandPlazas(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	m1 := [][2]float64{{-6.3303, 53.6500}, {-6.3303, 53.6750}}
	m50 := [][2]float64{{-6.3785, 53.3600}, {-6.3785, 53.3800}}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		etc   bool
		want  float64
	}{
		{"M1, 5 axles", m1, truck40, false, 6.10},
		{"M1, 2 axles", m1, rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, false, 4.80},
		{"M50 unregistered", m50, truck40, false, 7.8},
		{"M50 tag", m50, truck40, true, 6.5},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 3, CountryKm: map[string]float64{"IE": 3}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, ETC: tc.etc}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "IE" {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 1e-9 {
			t.Errorf("%s: %.4f, want %.4f: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

// Sweden's bridge charges: per passage at the charging station, any
// direction, on top of the daily vägavgift.
func TestSwedishBridges(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	sundsvall := [][2]float64{{17.3480, 62.3800}, {17.3560, 62.3840}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"SE": 1}, Path: sundsvall}}}
	r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"SEK": 11}}, date)
	if err != nil {
		t.Fatal(err)
	}
	var bridge, day float64
	for _, l := range r.Lines {
		switch {
		case l.Section == "Sundsvallsbron":
			bridge += l.Amount
		case l.Country == "SE":
			day += l.Amount
		}
	}
	if bridge != 20 || day != 147 {
		t.Errorf("bridge %.2f, day %.2f, want 20 and 147: %v", bridge, day, r.Lines)
	}
}

// North Macedonia's toll stations charge per passage in the direction of
// their carriageway: Sopot southbound only.
func TestNorthMacedonia(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	south := [][2]float64{{21.7430, 41.7830}, {21.7466, 41.7686}}
	north := [][2]float64{south[1], south[0]}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		want  float64
	}{
		{"Sopot southbound, 5 axles", south, truck40, 5.50},
		{"Sopot southbound, 3 axles", south, rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}, 4.00},
		{"Sopot northbound", north, truck40, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 2, CountryKm: map[string]float64{"MK": 2}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "MK" {
				got += l.Amount
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

// Montenegro: the motorway from entry to exit station, and the Sozina
// tunnel per passage.
func TestMontenegro(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	motorway := [][2]float64{{19.2990, 42.4700}, {19.2990, 42.4750}, {19.4600, 42.6440}, {19.5442, 42.7510}, {19.5442, 42.7540}}
	sozina := [][2]float64{{19.0520, 42.1980}, {19.0520, 42.2030}}
	for _, tc := range []struct {
		name string
		path [][2]float64
		want float64
	}{
		{"Smokovac–Mateševo", motorway, 17},
		{"Sozina", sozina, 18},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 40, CountryKm: map[string]float64{"ME": 40}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "ME" {
				got += l.Amount
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

// Greece: open toll stations per passage, excluding VAT; a station mapped
// as several booths pays once.
func TestGreece(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name string
		path [][2]float64
		want float64
	}{
		{"Elefsina", [][2]float64{{23.4900, 38.0400}, {23.5010, 38.0445}}, 7.18},
		{"Spathovouni southbound", [][2]float64{{22.8100, 37.8390}, {22.8060, 37.8330}}, 8.43},
		{"Rio–Antirrio bridge, 5 axles", [][2]float64{{21.7600, 38.3300}, {21.7720, 38.3380}}, 41.05},
		// Egnatia Odos, front station Malgara: 4+ axles EUR 4.10 with VAT.
		{"Egnatia Odos, Malgara", [][2]float64{{22.6900, 40.6024}, {22.7100, 40.6024}}, 3.31},
		// Attiki Odos eastbound past five entry booths: one toll, category
		// 6 EUR 10.10 with VAT.
		{"Attiki Odos eastbound", [][2]float64{{23.7000, 38.0718}, {23.711567, 38.070172}, {23.734474, 38.066044}, {23.772411, 38.056347}, {23.785653, 38.048344}, {23.7950, 38.0450}}, 8.15},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"GR": 1}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "GR" {
				got += l.Amount
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

func TestTurkeyBridges(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	two := rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}
	cross := func(lon, lat float64) [][2]float64 {
		return [][2]float64{{lon - 0.003, lat - 0.002}, {lon + 0.003, lat + 0.002}}
	}
	for _, tc := range []struct {
		name  string
		truck rates.Truck
		path  [][2]float64
		want  float64
	}{
		{"Yavuz Sultan Selim, 5 axles", truck40, cross(29.11176, 41.20308), 11.50},
		{"Yavuz Sultan Selim, 2 axles", two, cross(29.11176, 41.20308), 2.42},
		{"Osmangazi, 5 axles", truck40, cross(29.51602, 40.75600), 49.17},
		{"1915 Çanakkale bridge to Gelibolu Güney, 5 axles", truck40, [][2]float64{{26.6600, 40.3200}, {26.6095, 40.3535}, {26.6154, 40.3665}}, 48.75},
		{"Malkara to the 1915 Çanakkale bridge, 5 axles", truck40, [][2]float64{{27.0453, 40.8656}, {26.8631, 40.5865}, {26.6095, 40.3535}, {26.6600, 40.3200}}, 61.75},
		{"Gebze over the Osmangazi bridge to Bursa Kuzey, 5 axles", truck40, [][2]float64{{29.5200, 40.7800}, {29.5160, 40.7560}, {29.5002, 40.7165}, {29.4754, 40.6963}, {29.0865, 40.3195}}, 65.42},
		{"Kuzey Çevre Uskumruköy over the bridge to Riva, 5 axles (bridge in the ticket)", truck40, [][2]float64{{29.0279, 41.2349}, {29.1117, 41.2030}, {29.2025, 41.1921}}, 16.42},
		{"Anadolu Otoyolu Çamlıca to Gebze, 5 axles", truck40, [][2]float64{{29.1725, 40.9922}, {29.3157, 40.9539}, {29.4743, 40.8043}}, 1.92},
		{"no bridge", truck40, cross(29.2, 41.0), 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"TR": 1}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, FX: map[string]float64{"TRY": 50}}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "TR" {
				got += l.AmountEUR
				if len(l.Sources) == 0 || l.Sources[0].URL == "" {
					t.Errorf("%s: line %q has no source links", tc.name, l.Section)
				}
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

func TestSwedishCongestionTax(t *testing.T) {
	sto := [][2]float64{{18.1034, 59.3130}, {18.1034, 59.3140}, {18.1034, 59.3150}}                   // through Danvikstull
	gbg := [][2]float64{{11.9941, 57.7190}, {11.99404, 57.7199}, {11.9839, 57.7238}, {11.98, 57.725}} // Marieholmsleden then Ringömotet
	for _, tc := range []struct {
		name, day, at string
		path          [][2]float64
		cc            string
		want          float64
	}{
		{"Stockholm high season rush hour", "2026-11-05", "08:00", sto, "SE", 4.09}, // 45 SEK
		{"Stockholm low season midday", "2026-12-08", "12:00", sto, "SE", 1.0},      // 11 SEK
		{"Stockholm at night", "2026-11-05", "22:00", sto, "SE", 0},
		{"Stockholm on a Saturday", "2026-11-07", "08:00", sto, "SE", 0},
		{"Stockholm without a time", "2026-11-05", "", sto, "SE", 0},
		{"Göteborg two stations within the hour", "2026-11-05", "07:30", gbg, "SE", 2.0}, // 22 SEK once
		{"Göteborg in July", "2026-07-02", "07:30", gbg, "SE", 0},
	} {
		date, _ := time.Parse(time.DateOnly, tc.day)
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"SE": 1}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, Time: tc.at, FX: map[string]float64{"SEK": 11}}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Source, "trängselskatt") {
				got += l.AmountEUR
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

func TestPortugalLancos(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name string
		path [][2]float64
		want float64
	}{
		{"A1 Condeixa / Coimbra Sul, 5 axles", [][2]float64{{-8.4950, 40.1590}, {-8.494294, 40.161573}, {-8.4935, 40.1640}}, 0.98},
		{"Ponte Vasco da Gama northbound", [][2]float64{{-9.0300, 38.7520}, {-9.036765, 38.757609}, {-9.0430, 38.7630}}, 13.40},
		{"Ponte Vasco da Gama southbound", [][2]float64{{-9.0430, 38.7630}, {-9.036765, 38.757609}, {-9.0300, 38.7520}}, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"PT": 1}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "PT" {
				got += l.AmountEUR
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

func TestSpainSEITT(t *testing.T) {
	path := [][2]float64{{-3.8940, 40.2140}, {-3.8940, 40.2120}, {-3.8605, 40.1030}, {-3.8675, 39.9565}, {-3.8675, 39.9500}} // AP-41 Serranillos to Villaseca
	for _, tc := range []struct {
		name, at string
		etc      bool
		want     float64
	}{
		{"cash at 10:00", "10:00", false, 6.82},
		{"Vía-T at 10:00", "10:00", true, 6.16},
		{"at night", "03:00", false, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"ES": 1}, Path: path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, Time: tc.at, ETC: tc.etc}, time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "ES" {
				got += l.AmountEUR
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// The departure time and the km along the route tell when each station
// is reached.
func TestPassageTimes(t *testing.T) {
	sum := func(r Response, src string) float64 {
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Source, src) {
				got += l.AmountEUR
			}
		}
		return got
	}
	run := func(tbs []rates.Table, cc string, path [][2]float64, req Request) Response {
		t.Helper()
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{cc: 1}, Path: path}}}
		req.CargoKg, req.Truck = 1000, truck40
		r, err := Price(trip, tbs, req, time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	fx := map[string]float64{"SEK": 11}
	// Danvikstull ~35 km after the start: leaving 06:35 it is reached about
	// 07:05 at 70 km/h, 45 SEK in high season (30 at 06:35).
	sto := [][2]float64{{18.1034, 59.0}, {18.1034, 59.3130}, {18.1034, 59.3150}}
	if got := sum(run(all(t), "SE", sto, Request{Time: "06:35", FX: fx}), "trängselskatt"); got != 4.09 {
		t.Errorf("Stockholm reached at 07:05: %.2f, want 4.09", got)
	}
	// Göteborg: Marieholmsleden about 06:58 (16 SEK), Ringömotet about
	// 07:01 at 20 km/h (22 SEK): within 60 minutes, the highest once.
	gbg := [][2]float64{{11.9941, 57.7190}, {11.99404, 57.7199}, {11.9839, 57.7238}, {11.98, 57.725}}
	if got := sum(run(all(t), "SE", gbg, Request{Time: "06:58", AvgSpeedKmh: 20, FX: fx}), "trängselskatt"); got != 2.0 {
		t.Errorf("Göteborg 16 then 22 within the hour: %.2f, want 2.00", got)
	}
	// A toll station free at night.
	src := []rates.Source{{Title: "test", URL: "https://example.org"}}
	tb := rates.Table{Country: "XX", Currency: "EUR", ValidFrom: "2026-01-01", Name: "test", Law: "test law", Sources: src,
		TollPoints: []rates.TollPoint{{Name: "night-free", Lat: 50, Lon: 10, Rate: 5, FreeHours: []string{"22:00", "05:59"}}}}
	path := [][2]float64{{10, 49.99}, {10, 50.01}}
	for at, want := range map[string]float64{"12:00": 5, "23:30": 0, "": 5} {
		if got := sum(run([]rates.Table{tb}, "XX", path, Request{Time: at}), "test law"); got != want {
			t.Errorf("free hours at %q: %.2f, want %.2f", at, got, want)
		}
	}
	// Two versions of one station, each in force for part of the table's time.
	tb.TollPoints = []rates.TollPoint{
		{Name: "old", Lat: 50, Lon: 10, Rate: 4, ValidTo: "2026-11-04"},
		{Name: "new", Lat: 50, Lon: 10, Rate: 6, ValidFrom: "2026-11-05"},
	}
	if got := sum(run([]rates.Table{tb}, "XX", path, Request{}), "test law"); got != 6 {
		t.Errorf("versioned station on 2026-11-05: %.2f, want 6", got)
	}
}

// Square tariffs are priced per direction: Kuzey Marmara's İzmit Kuzey to
// İzmit Doğu (class 4) is 105 TL, the other way 120 TL (with KDV).
func TestDirectedPrices(t *testing.T) {
	north, east := [2]float64{29.998845, 40.791116}, [2]float64{30.052139, 40.784959}
	for _, tc := range []struct {
		name string
		path [][2]float64
		want float64
	}{
		{"İzmit Kuzey to İzmit Doğu", [][2]float64{north, east}, 1.75}, // 87.5 TRY at 50
		{"İzmit Doğu to İzmit Kuzey", [][2]float64{east, north}, 2.00}, // 100
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"TR": 1}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"TRY": 50}}, time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "TR" {
				got += l.AmountEUR
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

// The Dutch charge: 22.3% off from September to December 2026, then the
// 2027 indexed amounts (Staatscourant 2026, 33659): EURO 6 over 32 t,
// CO2 class 1, 0.092 + 0.020 + 0.094 = 0.206 EUR/km; class 5 0.040.
func TestNetherlands2027(t *testing.T) {
	for _, tc := range []struct {
		day   string
		class int
		want  float64
	}{
		{"2026-11-10", 1, 15.6}, // 0.069 + 0.016 + 0.071 (Staatscourant 2026, 18058)
		{"2027-01-01", 1, 20.6},
		{"2027-06-01", 5, 4.0},
	} {
		date, _ := time.Parse(time.DateOnly, tc.day)
		tr := truck40
		tr.CO2Class = tc.class
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{"NL": 100}}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tr}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if l.Country == "NL" {
				got += l.AmountEUR
			}
		}
		if math.Abs(got-tc.want) > 0.005 {
			t.Errorf("%s class %d: %.2f, want %.2f: %v", tc.day, tc.class, got, tc.want, r.Lines)
		}
	}
}

// Driving time to elapsed time under Regulation 561/2006: a 45-minute
// break after 4.5 hours, an 11-hour rest after 9.
func TestWithRest(t *testing.T) {
	for _, tc := range []struct{ d, want float64 }{
		{0, 0}, {4, 4}, {4.5, 4.5}, {5, 5.75}, {9, 9.75}, {10, 9 + 0.75 + 11 + 1}, {18, 20.75 + 9.75}, {20, 2*20.75 + 2},
	} {
		if got := withRest(tc.d); math.Abs(got-tc.want) > 1e-9 {
			t.Errorf("withRest(%g) = %g, want %g", tc.d, got, tc.want)
		}
	}
}

// Days of a time-based charge by passage times: Sweden counts calendar
// days, Estonia 24-hour periods.
func TestTripDays(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	tb := func(cc string) rates.Table {
		x, ok := rates.Find(all(t), cc, date)
		if !ok {
			t.Fatal(cc)
		}
		return x
	}
	se, ee, lv := tb("SE"), tb("EE"), tb("LV")
	for _, tc := range []struct {
		name  string
		tb    rates.Table
		req   Request
		spans [][2]float64
		want  int
	}{
		{"no time", se, Request{}, [][2]float64{{0, 700}}, 1},
		{"SE same day", se, Request{Time: "08:00"}, [][2]float64{{0, 700}}, 1},
		{"SE past midnight", se, Request{Time: "20:00"}, [][2]float64{{0, 700}}, 2},
		{"SE with rests", se, Request{Time: "08:00", DriverRest: true}, [][2]float64{{0, 700}}, 2},
		{"SE out and back in", se, Request{Time: "08:00"}, [][2]float64{{0, 100}, {1200, 1300}}, 2},
		{"EE within 24 h", ee, Request{Time: "20:00"}, [][2]float64{{0, 700}}, 1},
		{"EE over 24 h", ee, Request{Time: "20:00"}, [][2]float64{{0, 1800}}, 2},
		{"LV: day not known", lv, Request{Time: "20:00"}, [][2]float64{{0, 1800}}, 1},
	} {
		req := tc.req
		req.spans = map[string][][2]float64{tc.tb.Country: tc.spans}
		if got, note := tripDays(tc.tb, tc.tb.Country, req, date); got != tc.want {
			t.Errorf("%s: %d days, want %d (%s)", tc.name, got, tc.want, note)
		}
	}
}

func TestSpans(t *testing.T) {
	runs := []Run{{Kind: "road", Country: "SE", Km: 100}, {Kind: "road", Country: "NO", Km: 50}, {Kind: "ferry", Km: 20}, {Kind: "road", Country: "SE", Km: 30}}
	got := Spans(runs)
	if fmt.Sprint(got["SE"]) != "[[0 100] [170 200]]" || fmt.Sprint(got["NO"]) != "[[100 150]]" {
		t.Errorf("%v", got)
	}
}

// The provenance names the tables, their files and the exchange rates.
func TestProvenance(t *testing.T) {
	date := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)
	res := cphHam
	res.Warnings = []string{"gap between legs"}
	r, err := PriceWith(res, all(t), nil, Request{CargoKg: 20000, Truck: truck40, Time: "08:00"}, date)
	if err != nil {
		t.Fatal(err)
	}
	p := r.Provenance
	files := map[string]bool{}
	for _, tb := range p.Tables {
		files[tb.Area+" "+tb.File] = true
	}
	if !files["DK dk-2026-01-01.json"] || !files["DE de-2024-07-01.json"] {
		t.Errorf("tables %+v", p.Tables)
	}
	if len(p.FX) != 1 || !strings.Contains(p.FX[0], "DKK: 7.46038") {
		t.Errorf("fx %v", p.FX)
	}
	if len(p.Assumed) != 1 || !strings.HasPrefix(p.Assumed[0], "avg_speed_kmh: 70") {
		t.Errorf("assumed %v", p.Assumed)
	}
	if !slices.Contains(r.Notes, "Sootcase: gap between legs") {
		t.Errorf("notes %v", r.Notes)
	}
}

// A Swedish transit of 1,200 km from 18:00: at 70 km/h the trip is in
// Sweden on two calendar days.
func TestSwedenTwoDays(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1200, CountryKm: map[string]float64{"SE": 1200}}}}
	req := Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"SEK": 11}, Time: "18:00"}
	req.spans = map[string][][2]float64{"SE": {{0, 1200}}}
	r, err := Price(trip, all(t), req, date)
	if err != nil {
		t.Fatal(err)
	}
	l, ok := line(r, RoadToll, "SE", rates.Infrastructure)
	if !ok {
		for _, x := range r.Lines {
			if x.Country == "SE" {
				l, ok = x, true
			}
		}
	}
	if !ok || l.Days != 2 || l.Amount != 294 {
		t.Errorf("%+v", r.Lines)
	}
}

// The hour rule lasts the group's minutes: reached two hours later (at
// 5 km/h), Straume pays again.
func TestNorwayHourRuleTimed(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	path := [][2]float64{{5.3110, 60.4190}, {5.3150, 60.4170}, {5.2697, 60.3220}, {5.2723, 60.3232}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 20, CountryKm: map[string]float64{"NO": 20}, Path: path}}}
	count := func(req Request) int {
		r, err := Price(trip, all(t), req, date)
		if err != nil {
			t.Fatal(err)
		}
		n := 0
		for _, l := range r.Lines {
			if l.Country == "NO" {
				n++
			}
		}
		return n
	}
	req := Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"NOK": 11.7}, Time: "08:00"}
	if n := count(req); n != 1 {
		t.Errorf("at 70 km/h: %d passages paid, want 1", n)
	}
	req.AvgSpeedKmh = 5
	if n := count(req); n != 2 {
		t.Errorf("at 5 km/h: %d passages paid, want 2", n)
	}
}

// Passage times are local where the station is: 23:30 leaving Portugal
// is 00:30 in Spain, and the day counts by the local date.
func TestPassageZones(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	req := Request{Time: "23:30", origin: "PT"}
	if at, _ := passage(req, date, 0, "ES"); at.Format("2006-01-02 15:04") != "2026-11-05 00:30" {
		t.Errorf("ES: %v", at)
	}
	if at, _ := passage(req, date, 0, "PT"); at.Format("2006-01-02 15:04") != "2026-11-04 23:30" {
		t.Errorf("PT: %v", at)
	}
	// From Denmark at 23:00, an hour on is midnight in Sweden but 23:00 in
	// Britain: one calendar day there, two in Sweden.
	dk := Request{Time: "23:00", origin: "DK", spans: map[string][][2]float64{"SE": {{0, 70}}, "GB": {{0, 70}}}}
	tbs := all(t)
	se, _ := rates.Find(tbs, "SE", date)
	gb, _ := rates.Find(tbs, "GB", date)
	if n, _ := tripDays(se, "SE", dk, date); n != 2 {
		t.Errorf("SE: %d days", n)
	}
	if n, _ := tripDays(gb, "GB", dk, date); n != 1 {
		t.Errorf("GB: %d days", n)
	}
}

func TestPrice_FuelCountry(t *testing.T) {
	d := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)
	// All fuel bought in Germany: the whole road fuel at the 2026 price.
	r, err := Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "DE"}, d)
	if err != nil {
		t.Fatal(err)
	}
	l, ok := line(r, FuelCO2, "DE", rates.CO2)
	if !ok || l.Rate != 65 || l.Km != 0 || l.TonnesCO2 <= 0.11 {
		t.Errorf("fuel line %+v", l)
	}
	// Bought in Denmark (no per-tonne price here): no fuel line.
	r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "DK"}, d)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := line(r, FuelCO2, "DK", rates.CO2); ok {
		t.Error("DK fuel line")
	}
	// The 2024 and 2025 prices are fixed in BEHG § 10 (2).
	for y, want := range map[int]float64{2024: 45, 2025: 55} {
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "DE"}, time.Date(y, 6, 1, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "DE", rates.CO2); !ok || l.Rate != want {
			t.Errorf("%d: %+v", y, l)
		}
	}
	// Ireland's carbon tax on auto-diesel: EUR 71 per tonne from 8 October
	// 2025, 63.50 before.
	for d, want := range map[string]float64{"2026-11-03": 71, "2025-06-01": 63.5} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "IE"}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "IE", rates.CO2); !ok || l.Rate != want {
			t.Errorf("IE %s: %+v", d, l)
		}
	}
	// Portugal's adicionamento: the portarias of 2024 (each in force the next
	// working day), 67.395 in 2025, 70.0405 in 2026.
	for d, want := range map[string]float64{"2024-08-23": 56.246, "2024-08-26": 68.368, "2024-09-13": 74.429,
		"2024-09-16": 81, "2025-06-01": 67.395, "2026-11-03": 70.0405} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "PT"}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "PT", rates.CO2); !ok || l.Rate != want {
			t.Errorf("PT %s: %+v", d, l)
		}
	}
	// Austria's NEHG certificate value: 45 in 2024, 55 from 2025 (the
	// ministry's 55 for 2026 and 2027).
	for d, want := range map[string]float64{"2024-06-01": 45, "2025-06-01": 55, "2026-11-03": 55} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "AT"}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "AT", rates.CO2); !ok || l.Rate != want {
			t.Errorf("AT %s: %+v", d, l)
		}
	}
	// Slovenia's okoljska dajatev on diesel: 17.3 under the Uredba, 30.85 from
	// 10 September 2024, the 2026 sklepi (0, 25.90, 30.85 from 2 June, 0 from
	// 28 July to 14 December).
	for d, want := range map[string]float64{"2024-06-01": 17.3, "2025-06-01": 30.85, "2026-04-01": 0,
		"2026-05-20": 25.9, "2026-06-02": 30.85, "2026-11-03": 0, "2026-12-15": 30.85} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "SI"}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "SI", rates.CO2); !ok || l.Rate != want || (want == 0 && l.Amount != 0) {
			t.Errorf("SI %s: %+v", d, l)
		}
	}
	if _, err := Price(cphHam, all(t), Request{CargoKg: 1, Truck: truck40, FuelCountry: "de"}, d); err == nil {
		t.Error("lower-case fuel_country accepted")
	}
}

// Tunnels and bridges charged per passage (crossings tables), each in the
// direction it charges, on 5 November 2026.
func TestTunnelsAndBridges(t *testing.T) {
	fx := map[string]float64{"GBP": 0.84, "CHF": 0.95}
	run := func(path [][2]float64, req Request) (float64, int) {
		t.Helper()
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"ZZ": 1}, Path: path}}}
		req.CargoKg, req.Truck, req.FX = 1000, truck40, fx
		r, err := Price(trip, all(t), req, time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var eur float64
		n := 0
		for _, l := range r.Lines {
			if l.Charge == RoadToll {
				eur += l.AmountEUR
				n++
			}
		}
		return math.Round(eur*100) / 100, n
	}
	for _, tc := range []struct {
		name string
		path [][2]float64
		req  Request
		eur  float64
	}{
		// Dartford, class D: GBP 8.40 (pre-pay 7.20), 6am to 10pm.
		{"Dartford tunnels northbound", [][2]float64{{0.2517, 51.4593}, {0.2626, 51.4702}}, Request{}, 10.0},
		{"Dartford bridge southbound", [][2]float64{{0.2667, 51.4768}, {0.258914, 51.464813}, {0.2458, 51.4548}}, Request{ETC: true}, 8.57},
		{"Dartford at night", [][2]float64{{0.2517, 51.4593}, {0.2626, 51.4702}}, Request{Time: "23:00"}, 0},
		// Tyne Tunnels, class 3: GBP 5.00 (permit 4.50), each bore its way.
		{"Tyne Tunnel northbound", [][2]float64{{-1.4827, 54.9791}, {-1.486078, 54.984689}, {-1.4843, 54.9906}}, Request{}, 5.95},
		{"New Tyne Tunnel southbound", [][2]float64{{-1.4844, 54.9918}, {-1.484379, 54.988309}, {-1.4850, 54.9848}, {-1.4821, 54.9788}}, Request{ETC: true}, 5.36},
		// Westerscheldetunnel, category 4 (over 12 m): EUR 25, T-Tag 15.
		{"Westerscheldetunnel", [][2]float64{{3.7557, 51.43}, {3.7557, 51.45}}, Request{}, 25},
		{"Westerscheldetunnel T-Tag", [][2]float64{{3.7557, 51.45}, {3.7557, 51.43}}, Request{ETC: true}, 15},
		// Liefkenshoektunnel, category 2 by day: EUR 25 cash, 17.60 OBU;
		// 22:00-06:00 8.00 and 4.40.
		{"Liefkenshoektunnel", [][2]float64{{4.2895, 51.28}, {4.2895, 51.293}}, Request{}, 25},
		{"Liefkenshoektunnel OBU", [][2]float64{{4.2895, 51.293}, {4.2895, 51.28}}, Request{ETC: true}, 17.6},
		{"Liefkenshoektunnel at night", [][2]float64{{4.2895, 51.28}, {4.2895, 51.293}}, Request{Time: "23:00"}, 8},
		{"Liefkenshoektunnel OBU at night", [][2]float64{{4.2895, 51.28}, {4.2895, 51.293}}, Request{ETC: true, Time: "05:30"}, 4.4},
		{"Liefkenshoektunnel OBU at 06:30", [][2]float64{{4.2895, 51.28}, {4.2895, 51.293}}, Request{ETC: true, Time: "06:30"}, 17.6},
		// Herrentunnel, class D (4 axles or more): EUR 17.60.
		{"Herrentunnel", [][2]float64{{10.7594, 53.89}, {10.7594, 53.905}}, Request{}, 17.6},
		// Warnowtunnel, category 5 (4 axles or more): winter EUR 20.30,
		// "360 Tage" 17.07.
		{"Warnowtunnel", [][2]float64{{12.1076, 54.13}, {12.1076, 54.14}}, Request{}, 20.3},
		{"Warnowtunnel 360 Tage", [][2]float64{{12.1076, 54.14}, {12.1076, 54.13}}, Request{ETC: true}, 17.07},
		// Great St Bernard, class 4: southbound CHF 192.50 at the Swiss
		// plaza, northbound EUR 202 at the Italian one.
		{"Great St Bernard southbound", [][2]float64{{7.1937, 45.905}, {7.1932, 45.8985}, {7.1729, 45.8645}, {7.1615, 45.8513}, {7.1611, 45.845}}, Request{}, 202.63},
		{"Great St Bernard northbound", [][2]float64{{7.1611, 45.845}, {7.1615, 45.8513}, {7.1729, 45.8645}, {7.1932, 45.8985}, {7.1937, 45.905}}, Request{}, 202},
	} {
		if got, n := run(tc.path, tc.req); got != tc.eur || (tc.eur > 0 && n != 1) {
			t.Errorf("%s: EUR %.2f in %d lines, want %.2f in one", tc.name, got, n, tc.eur)
		}
	}
	// Before 1 September 2025 the 2013 Order's GBP 6.00.
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"GB": 1}, Path: [][2]float64{{0.2517, 51.4593}, {0.2626, 51.4702}}}}}
	r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, FX: fx}, time.Date(2025, 6, 2, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	n := 0
	for _, l := range r.Lines {
		if l.Section == "Dartford Crossing" {
			n++
			if l.Amount != 6 || l.Currency != "GBP" {
				t.Errorf("Dartford in June 2025: %+v", l)
			}
		}
	}
	if n != 1 {
		t.Errorf("Dartford in June 2025: %d lines", n)
	}
}

// The AP-7 Málaga–Guadiaro (Ausol) troncal barriers, Pesados 2 (four
// axles or more), IVA divided out: San Pedro EUR 7.70 in the normal
// season, 10.35 in the special one (June to September).
func TestAusol(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 3, CountryKm: map[string]float64{"ES": 3}, Path: [][2]float64{{-5.03, 36.4995}, {-5.008749, 36.499382}, {-4.99, 36.4990}}}}}
	for d, want := range map[string]float64{"2026-11-05": 7.70, "2026-07-01": 10.35} {
		date, _ := time.Parse("2006-01-02", d)
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40}, date)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		n := 0
		for _, l := range r.Lines {
			if l.Section == "AP-7 San Pedro" {
				got += l.Amount
				n++
			}
		}
		if n != 1 || math.Abs(got*1.21-want) > 0.01 {
			t.Errorf("%s: EUR %.4f in %d lines, want %.2f/1.21", d, got, n, want)
		}
	}
}

// London's Congestion Charge: GBP 18 a day from 2 January 2026 (15
// before) for driving in the zone 07:00-18:00 on weekdays.
func TestCongestionCharge(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 6, CountryKm: map[string]float64{"GB": 6}, Path: [][2]float64{{-0.20, 51.513}, {-0.12, 51.513}, {-0.02, 51.513}}}}}
	for _, tc := range []struct {
		date, at string
		gbp      float64
	}{{"2026-11-11", "10:00", 18}, {"2026-11-11", "20:00", 0}, {"2026-11-14", "10:00", 0}, {"2025-06-04", "10:00", 15}, {"2026-12-29", "10:00", 0}} {
		d, _ := time.Parse("2006-01-02", tc.date)
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, Time: tc.at, FX: map[string]float64{"GBP": 0.84}}, d)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if l.Charge == AreaCharge {
				got += l.Amount
			}
		}
		if got != tc.gbp {
			t.Errorf("%s %s: GBP %v, want %v", tc.date, tc.at, got, tc.gbp)
		}
	}
}

// Romania's Danube bridges (OG 15/2002 Anexa nr. 3) until TollRo: the A2
// bridge at Cernavodă, category 4 (12 t, 4 axles or more): 133 lei with
// VAT, either way.
func TestRODanubeBridges(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 4, CountryKm: map[string]float64{"ZZ": 4}, Path: [][2]float64{{27.99, 44.3395}, {28.018083, 44.339525}, {28.05, 44.3396}}}}}
	for d, want := range map[string]float64{"2026-03-01": 133 / 1.21, "2026-11-01": 0} {
		date, _ := time.Parse("2006-01-02", d)
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"RON": 5.0}}, date)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if l.Section == "Danube bridge Fetești–Cernavodă" {
				got += l.Amount
			}
		}
		if math.Abs(got-want) > 0.01 {
			t.Errorf("%s: RON %.2f, want %.2f", d, got, want)
		}
	}
}

// The AP-6 from Villalba to Adanero, Pesados 2: EUR 35.40 in 2026 with
// 21% IVA, 34.15 in 2025 (the operator's sheets).
func TestAP6(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 70, CountryKm: map[string]float64{"ZZ": 70}, Path: [][2]float64{{-3.99, 40.62}, {-4.02933, 40.6426}, {-4.1962, 40.73107}, {-4.41318, 40.77253}, {-4.57387, 40.89945}, {-4.59013, 40.94729}, {-4.61, 40.99}}}}}
	for d, want := range map[string]float64{"2026-03-01": 35.40, "2025-03-01": 34.15} {
		date, _ := time.Parse("2006-01-02", d)
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40}, date)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.HasPrefix(l.Section, "AP-6/AP-51/AP-61") {
				got += l.Amount
			}
		}
		if math.Abs(got*1.21-want) > 0.01 {
			t.Errorf("%s: EUR %.2f with IVA, want %.2f (%+v)", d, got*1.21, want, r.Lines)
		}
	}
}

// The AP-71 León–Astorga, Pesados 2: EUR 10.10 by day, 5.05 at night
// (23:00 to 07:00), 21% IVA included.
func TestAP71(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 40, CountryKm: map[string]float64{"ZZ": 40}, Path: [][2]float64{{-5.62, 42.575}, {-5.639884, 42.57088}, {-5.74975, 42.527119}, {-5.894253, 42.452951}, {-6.017108, 42.439394}, {-6.06, 42.44}}}}}
	date := time.Date(2026, 3, 2, 0, 0, 0, 0, time.UTC)
	for at, want := range map[string]float64{"10:00": 10.10, "23:30": 5.05, "": 10.10} {
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, Time: at}, date)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.HasPrefix(l.Section, "AP-71") {
				got += l.Amount
			}
		}
		if math.Abs(got*1.21-want) > 0.01 {
			t.Errorf("%q: EUR %.2f with IVA, want %.2f", at, got*1.21, want)
		}
	}
}

// Italy's motorway tolls are an estimate: the km on toll motorways (OSM
// toll=yes) at Autostrade per l'Italia's plain-stretch rate, VAT
// included (class 5: EUR 0.19034/km from 1 January 2026).
func TestItalyEstimate(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	a1 := [][2]float64{{11.19187, 44.14234}, {11.19150, 44.13922}, {11.19156, 44.13688}, {11.19185, 44.13445}, {11.19230, 44.13252}, {11.19359, 44.12917}, {11.19467, 44.12720}, {11.19593, 44.12528}, {11.19760, 44.12325}, {11.20007, 44.12074}, {11.21426, 44.10865}, {11.21636, 44.10652}, {11.22021, 44.10219}, {11.22349, 44.09763}, {11.22840, 44.08950}, {11.23020, 44.08687}, {11.23555, 44.07763}, {11.23717, 44.07508}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 7, CountryKm: map[string]float64{"IT": 7}, Path: a1}}}
	r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40}, date)
	if err != nil {
		t.Fatal(err)
	}
	l, ok := line(r, RoadToll, "IT", rates.Toll)
	if !ok || l.Rate != 0.19034 || l.Km < 6 {
		t.Errorf("IT: %+v %v", l, r.Lines)
	}
	if !strings.Contains(l.Source, "Estimate") {
		t.Errorf("IT line not flagged as an estimate: %s", l.Source)
	}
}

// London's Low Emission Zone: lorries over 3.5 t below Euro VI pay GBP 100
// a day (Euro IV or V) or 300 (older), any hour; Euro VI pays nothing.
func TestLondonLEZ(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 6, CountryKm: map[string]float64{"GB": 6}, Path: [][2]float64{{-0.20, 51.513}, {-0.12, 51.513}, {-0.02, 51.513}}}}}
	d := time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	for euro, want := range map[int]float64{6: 0, 5: 100, 4: 100, 3: 300} {
		tr := truck40
		tr.Euro = euro
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tr, Time: "23:00", FX: map[string]float64{"GBP": 0.84}}, d)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if l.Section == "London Low Emission Zone" {
				got += l.Amount
			}
		}
		if got != want {
			t.Errorf("Euro %d: GBP %v, want %v", euro, got, want)
		}
	}
}

// The Blackwall and Silvertown tunnels: GBP 10.00 per HGV crossing from
// 7 April 2025, 10.50 from 21 September 2026, none from 22:00 to 06:00.
func TestThamesTunnels(t *testing.T) {
	// Through the middle of a Blackwall bore, along its heading (306.3°).
	h := 306.3 * math.Pi / 180
	lat, lon := 51.503838, -0.004038
	dl, dn := 0.002*math.Cos(h), 0.002*math.Sin(h)/math.Cos(lat*math.Pi/180)
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 0.6, CountryKm: map[string]float64{"GB": 0.6}, Path: [][2]float64{{lon - dn, lat - dl}, {lon, lat}, {lon + dn, lat + dl}}}}}
	for _, tc := range []struct {
		date, at string
		want     float64
	}{{"2026-10-01", "12:00", 10.50}, {"2026-10-01", "23:00", 0}, {"2025-06-01", "12:00", 10.00}, {"2025-03-01", "12:00", 0}} {
		d, _ := time.Parse("2006-01-02", tc.date)
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, Time: tc.at, FX: map[string]float64{"GBP": 0.84}}, d)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Blackwall and Silvertown") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.001 {
			t.Errorf("%s %s: GBP %v, want %v: %v", tc.date, tc.at, got, tc.want, r.Lines)
		}
	}
}

// AP-66 (Aucalsa), from the Ministry's tolls in force, either way:
// Campomanes–León, Pesados 2, EUR 15.05 in 2026 (IVA included).
func TestAP66(t *testing.T) {
	path := [][2]float64{{-5.8189854, 43.1135722}, {-5.8896348, 42.9073625}, {-5.7867426, 42.7830472}, {-5.6681621, 42.5789112}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 78, CountryKm: map[string]float64{"ES": 78}, Path: path}}}
	for _, tc := range []struct {
		date string
		want float64
	}{{"2026-06-01", 15.05}} {
		d, _ := time.Parse("2006-01-02", tc.date)
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40}, d)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.HasPrefix(l.Section, "AP-66") {
				got += l.Amount
			}
		}
		if math.Abs(got*1.21-tc.want) > 0.01 {
			t.Errorf("%s: %v ex IVA (x1.21 = %v), want %v incl.: %v", tc.date, got, got*1.21, tc.want, r.Lines)
		}
	}
}

// AP-46: one barrier (Casabermeja), Pesados 2 EUR 8.70 in the low season,
// 11.35 in the high season (May-October, weekends, Easter), free for
// trucks 22:00-08:00 (2026, IVA included).
func TestAP46(t *testing.T) {
	path := [][2]float64{{-4.4575, 36.93}, {-4.45791, 36.90258}, {-4.4583, 36.875}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 6, CountryKm: map[string]float64{"ES": 6}, Path: path}}}
	for _, tc := range []struct {
		date, at string
		want     float64
	}{{"2026-11-13", "12:00", 8.70}, {"2026-11-14", "12:00", 11.35}, {"2026-07-01", "12:00", 11.35}, {"2026-04-01", "12:00", 11.35}, {"2026-11-13", "23:00", 0}} {
		d, _ := time.Parse("2006-01-02", tc.date)
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, Time: tc.at}, d)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Casabermeja") {
				got += l.Amount
			}
		}
		if math.Abs(got*1.21-tc.want) > 0.01 {
			t.Errorf("%s %s: %v x1.21 = %v, want %v: %v", tc.date, tc.at, got, got*1.21, tc.want, r.Lines)
		}
	}
}

// Warnowtunnel in summer (1 May - 31 October): category 5 EUR 23.00;
// the "360 Tage" price (17.07) holds all year.
func TestWarnowSummer(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"DE": 1}, Path: [][2]float64{{12.1076, 54.13}, {12.1076, 54.14}}}}}
	for _, tc := range []struct {
		etc  bool
		want float64
	}{{false, 23}, {true, 17.07}} {
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, ETC: tc.etc}, time.Date(2027, 7, 1, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Warnow") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.001 {
			t.Errorf("etc %v: %v, want %v: %v", tc.etc, got, tc.want, r.Lines)
		}
	}
}

// M6 Toll, class 5 (three axles or more), excluding VAT: all three zones
// GBP 20.90 (17.42), two 18.20 (15.17), within zone 2 15.70 (13.08),
// within zone 3 nothing; breeze 18.20 (15.17) for all three.
func TestM6Toll(t *testing.T) {
	n := [][2]float64{{-1.7296, 52.5200}, {-1.729643, 52.529124}, {-1.729678, 52.54144}, {-1.74938, 52.557982}, {-1.796744, 52.595927},
		{-1.822424, 52.643702}, {-1.881197, 52.650629}, {-1.966462, 52.662794}, {-2.033988, 52.670872}, {-2.064168, 52.664986}, {-2.0750, 52.6700}}
	rev := func(p [][2]float64) [][2]float64 {
		r := slices.Clone(p)
		slices.Reverse(r)
		return r
	}
	for _, tc := range []struct {
		name string
		path [][2]float64
		etc  bool
		want float64
	}{
		{"M6(S) to M6(N)", n, false, 17.42},
		{"M6(S) to M6(N), breeze", n, true, 15.17},
		{"T3 to M6(N)", n[4:], false, 15.17},
		{"T3 to T6", n[4:7], false, 13.08},
		{"T7 to M6(N)", n[8:], false, 0},
		{"southbound against the northbound stations' heading", rev(n[4:7]), false, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"GB": 50}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, ETC: tc.etc, FX: map[string]float64{"GBP": 0.84}}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "M6 Toll") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// Bosnia and Herzegovina's A1, class IV, KM with VAT: from 1 November
// 2026 (JP Autoceste FBiH's price list) Sarajevo sjever–Zenica sjever 32.0
// either way (EUR 13.98 without VAT), Sarajevo zapad–Tarčin 11.5 (5.03),
// the Svilaj barrier 5.7 (2.49); in 2025 (decree SN 63/24) 28.0 (12.24).
func TestBosniaA1(t *testing.T) {
	sz := [][2]float64{{18.3300, 43.9050}, {18.321171, 43.911507}, {18.251882, 43.970949}, {18.166477, 44.001398}, {18.110811, 44.080897},
		{18.107402, 44.097542}, {18.100574, 44.124616}, {17.98448, 44.131606}, {17.969721, 44.18181}, {17.901, 44.237}, {17.8950, 44.2450}}
	rev := func(p [][2]float64) [][2]float64 {
		r := slices.Clone(p)
		slices.Reverse(r)
		return r
	}
	for _, tc := range []struct {
		name, date string
		path       [][2]float64
		want       float64
	}{
		{"Sarajevo sjever to Zenica sjever", "2026-11-20", sz, 13.98},
		{"Zenica sjever to Sarajevo sjever", "2026-11-20", rev(sz), 13.98},
		{"Sarajevo zapad to Tarčin", "2026-11-20", [][2]float64{{18.2200, 43.8720}, {18.212609, 43.868922}, {18.143133, 43.866182}, {18.086035, 43.793065}, {18.0800, 43.7850}}, 5.03},
		{"Svilaj", "2026-11-20", [][2]float64{{18.2900, 45.1000}, {18.284385, 45.090308}, {18.2800, 45.0800}}, 2.49},
		{"Sarajevo sjever to Zenica sjever in 2025", "2025-06-02", sz, 12.24},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 60, CountryKm: map[string]float64{"BA": 60}, Path: tc.path}}}
		d, _ := time.Parse("2006-01-02", tc.date)
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40}, d)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "A1") || strings.Contains(l.Section, "|") || l.Country == "BA" {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// Republika Srpska, class IV: Čatrnja–Prnjavor KM 35 with VAT (EUR 15.30
// without), either way; Laktaši–Jakupovci 5 (2.19).
func TestRepublikaSrpska(t *testing.T) {
	cp := [][2]float64{{17.1900, 45.1100}, {17.193283, 45.100624}, {17.223614, 45.045062}, {17.276936, 44.958706}, {17.404083, 44.870197}, {17.684223, 44.852395}, {17.7000, 44.8500}}
	rev := slices.Clone(cp)
	slices.Reverse(rev)
	for _, tc := range []struct {
		name string
		path [][2]float64
		want float64
	}{
		{"Čatrnja to Prnjavor", cp, 15.30},
		{"Prnjavor to Čatrnja", rev, 15.30},
		{"Laktaši to Jakupovci", [][2]float64{{17.3300, 44.9200}, {17.325387, 44.9155}, {17.285689, 44.891804}, {17.2800, 44.8850}}, 2.19},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 60, CountryKm: map[string]float64{"BA": 60}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.Currency == "EUR" && l.Country == "BA" {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

// Albania's A1 (Rruga e Kombit): one plaza, class 5 (four axles or more)
// EUR 22.50 with VAT (18.75 without), either way.
func TestAlbaniaA1(t *testing.T) {
	for _, path := range [][][2]float64{{{20.3000, 42.0400}, {20.31435, 42.048682}, {20.3300, 42.0550}}, {{20.3300, 42.0550}, {20.31435, 42.048682}, {20.3000, 42.0400}}} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 3, CountryKm: map[string]float64{"AL": 3}, Path: path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Rruga e Kombit") {
				got += l.Amount
			}
		}
		if math.Abs(got-18.75) > 0.001 {
			t.Errorf("%v: %v, want 18.75: %v", path, got, r.Lines)
		}
	}
}

// Moldova's vignette for trucks not registered there: over 10 t, EUR 11 a
// day (one day for a trip).
func TestMoldovaVignette(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 180, CountryKm: map[string]float64{"MD": 180}, Path: [][2]float64{{28.0, 47.0}, {28.8, 47.0}}}}}
	r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	var got float64
	for _, l := range r.Lines {
		if l.Country == "MD" {
			got += l.Amount
		}
	}
	if got != 11 {
		t.Errorf("Moldova: %v, want 11: %v", got, r.Lines)
	}
}

// Catalonia's C-16, category 4 excluding IVA: the Túnel del Cadí 31.50; Sant
// Vicenç de Castellet 4.22 on a weekday, 7.09 at the weekend; les Fonts
// 3.21 on a weekday with Via-T, else 5.83.
func TestCataloniaC16(t *testing.T) {
	cross := func(lat, lon float64) [][2]float64 {
		return [][2]float64{{lon - 0.002, lat - 0.002}, {lon, lat}, {lon + 0.002, lat + 0.002}}
	}
	for _, tc := range []struct {
		name, date string
		path       [][2]float64
		etc        bool
		want       float64
	}{
		{"Cadí", "2026-11-19", cross(42.340173, 1.839159), false, 31.50},
		{"Sant Vicenç weekday", "2026-11-19", cross(41.651767, 1.864713), false, 4.22},
		{"Sant Vicenç Saturday", "2026-11-21", cross(41.651767, 1.864713), false, 7.09},
		{"les Fonts weekday Via-T", "2026-11-19", cross(41.517896, 2.030133), true, 3.21},
		{"les Fonts weekday cash", "2026-11-19", cross(41.517896, 2.030133), false, 5.83},
		{"les Fonts Sunday Via-T", "2026-11-22", cross(41.517896, 2.030133), true, 5.83},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"ES": 1}, Path: tc.path}}}
		d, _ := time.Parse("2006-01-02", tc.date)
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, ETC: tc.etc}, d)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.HasPrefix(l.Section, "C-16") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

// Bridges and tunnels added from the operators' pages: the Humber Bridge
// (3+ axles GBP 15), the Tamar Bridge (4+ axles GBP 16.50 eastbound only),
// the Mersey Gateway (over 12 t GBP 9.60), the Kiltunnel (EUR 5) and the
// AP-15 Marcilla barrier (Pesados II EUR 5.45 with IVA, 4.50 without).
func TestMoreCrossings(t *testing.T) {
	fx := map[string]float64{"GBP": 0.84}
	cross := func(lat, lon, dlat, dlon float64) [][2]float64 {
		return [][2]float64{{lon - dlon, lat - dlat}, {lon, lat}, {lon + dlon, lat + dlat}}
	}
	for _, tc := range []struct {
		name, country string
		path          [][2]float64
		want          float64
	}{
		{"Humber Bridge", "GB", cross(53.706846, -0.450058, 0.004, 0), 15},
		{"Tamar Bridge eastbound", "GB", cross(50.408203, -4.203564, 0, 0.004), 16.5},
		{"Tamar Bridge westbound", "GB", cross(50.408203, -4.203564, 0, -0.004), 0},
		{"Mersey Gateway Bridge", "GB", cross(53.352052, -2.712029, 0.003, 0.003), 9.6},
		{"Kiltunnel", "NL", cross(51.7726, 4.638273, 0.002, 0.002), 5},
		{"AP-15 Marcilla", "ES", cross(42.331205, -1.726227, 0.003, 0), 4.5},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{tc.country: 1}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, FX: fx}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.Rate > 0 && strings.Contains(l.RateUnit, "/passage") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

// Liefkenshoektunnel in 2027: OBU EUR 17.95 by day; untimed, a note
// that it's cheaper at night.
func TestLiefkenshoek2027(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"BE": 1}, Path: [][2]float64{{4.2895, 51.28}, {4.2895, 51.293}}}}}
	r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, ETC: true}, time.Date(2027, 3, 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	var got float64
	for _, l := range r.Lines {
		if strings.Contains(l.Section, "Liefkenshoek") {
			got += l.Amount
		}
	}
	if math.Abs(got-17.95) > 0.001 || !slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "Liefkenshoektunnel is cheaper from 22:00 to 06:00") }) {
		t.Errorf("%v, want 17.95 and a night note: %v %v", got, r.Lines, r.Notes)
	}
}

// AP-7 Alicante–Cartagena: a through trip passes two barriers, Pesados 2
// EUR 6.50 each in the low season (13.00, as the table's 724–763), 7.20 in
// the high season (June-September, Semana Santa), IVA included.
func TestAP7AlicanteCartagena(t *testing.T) {
	path := [][2]float64{{-0.80, 38.05}, {-0.782622, 38.008606}, {-0.741711, 37.920565}, {-0.76, 37.88}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 20, CountryKm: map[string]float64{"ES": 20}, Path: path}}}
	for _, tc := range []struct {
		date string
		want float64
	}{{"2026-11-13", 13.00}, {"2026-07-01", 14.40}, {"2026-03-28", 14.40}, {"2025-11-13", 12.40}} {
		d, _ := time.Parse("2006-01-02", tc.date)
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40}, d)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Montesinos") || strings.Contains(l.Section, "Zenia") {
				got += l.Amount
			}
		}
		if math.Abs(got*1.21-tc.want) > 0.02 {
			t.Errorf("%s: %v x1.21 = %v, want %v: %v", tc.date, got, got*1.21, tc.want, r.Lines)
		}
	}
}

// Gipuzkoa's N-I/A-15 canon (Bidegi 2026, VAT included): Pesados 2 from
// the Navarra border at Etzegarate to Lasarte-Oria 13.31 either way (11.00
// without VAT; 80% for a EURO 6 truck with a TAG), Olaberria to
// Ikaztegieta 3.23 (Pesados 1: 2.54), the A-15 from the Navarra border to
// Astigarraga 8.28. The paths run through the stretches' middles.
func TestGipuzkoaNIA15(t *testing.T) {
	north := [][2]float64{{-2.233752, 42.975276}, {-2.235671, 43.012005}, {-2.229985, 43.025091}, {-2.219160, 43.031472}, {-2.216272, 43.039493}, {-2.206366, 43.045757}, {-2.188690, 43.047709}, {-2.174213, 43.052941}, {-2.159260, 43.074206}, {-2.127150, 43.089336}, {-2.102954, 43.100584}, {-2.091125, 43.114395}, {-2.083447, 43.127762}, {-2.069501, 43.136957}, {-2.068657, 43.153665}, {-2.066286, 43.164239}, {-2.058001, 43.174967}, {-2.051309, 43.187986}, {-2.040521, 43.198132}, {-2.024312, 43.215077}, {-2.025480, 43.222605}, {-2.027607, 43.241979}, {-2.017673, 43.263306}}
	south := [][2]float64{{-2.017812, 43.263330}, {-2.030182, 43.241861}, {-2.025647, 43.222582}, {-2.027362, 43.213530}, {-2.040011, 43.198988}, {-2.051435, 43.188000}, {-2.058161, 43.174990}, {-2.066461, 43.164237}, {-2.068833, 43.153639}, {-2.069601, 43.137008}, {-2.083516, 43.127849}, {-2.092500, 43.115031}, {-2.103085, 43.100680}, {-2.127228, 43.089478}, {-2.159432, 43.074276}, {-2.174328, 43.052991}, {-2.188775, 43.047828}, {-2.206470, 43.045867}, {-2.216406, 43.039528}, {-2.219277, 43.031533}, {-2.230111, 43.025170}, {-2.235800, 43.011995}, {-2.238156, 42.972238}}
	a15 := [][2]float64{{-1.953008, 43.107744}, {-2.006100, 43.160423}, {-2.024312, 43.215077}, {-2.025480, 43.222605}, {-2.015596, 43.227869}, {-2.002537, 43.235253}, {-1.995401, 43.252420}, {-1.972676, 43.261736}, {-1.957261, 43.268486}, {-1.959252, 43.276115}}
	light := rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		etc   bool
		want  float64
	}{
		{"Etzegarate to Lasarte-Oria", north, truck40, false, 11.0},
		{"Etzegarate to Lasarte-Oria, EURO 6 with a TAG", north, truck40, true, 8.8},
		{"Lasarte-Oria to Etzegarate", south, truck40, false, 11.0},
		{"Olaberria to Ikaztegieta", north[4:10], truck40, false, 3.23 / 1.21},
		{"Olaberria to Ikaztegieta, Pesados 1", north[4:10], light, false, 2.54 / 1.21},
		{"A-15 Navarra border to Astigarraga", a15, truck40, false, 8.28 / 1.21},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"ES": 50}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 5000, Truck: tc.truck, ETC: tc.etc}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "N-I/A-15") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

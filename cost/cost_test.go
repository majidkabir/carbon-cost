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
	got := chainUses(sys, route, truck40, false)
	if len(got) != 1 || got[0].entry != "B" || got[0].exit != "N" {
		t.Errorf("got %+v, want one ticket B-N", got)
	}
	// Where two networks meet, the next ticket starts at the other
	// network's station at the same place (P2 beside P).
	sys.Stations = append(sys.Stations, rates.Station{Name: "P2", Points: at(0.3)})
	sys.Prices = map[string]map[string]float64{"B|P": {"4": 5}, "P2|N": {"4": 30}}
	got = chainUses(sys, route, truck40, false)
	if len(got) != 2 || got[0].entry != "B" || got[0].exit != "P" || got[1].entry != "P2" || got[1].exit != "N" {
		t.Errorf("got %+v, want B-P, P2-N", got)
	}
	// A barrier across the road (X) and an exit's booth beside it (Y) at
	// the same place: a trip driving through takes its ticket at X.
	sys.Stations = []rates.Station{{Name: "Y", Points: []rates.Place{{Name: "p", Lat: 45.002, Lon: 0.4999}}}, {Name: "X", Points: at(0.5)}, {Name: "N", Points: at(2.0)}}
	sys.Prices = map[string]map[string]float64{"Y|N": {"4": 36}, "X|N": {"4": 42}}
	got = chainUses(sys, route, truck40, false)
	if len(got) != 1 || got[0].entry != "X" {
		t.Errorf("got %+v, want X-N", got)
	}
	// A barrier priced on its own (Z|Z) pays when passed outside a
	// ticket, not inside one.
	sys.Stations = append(sys.Stations, rates.Station{Name: "Z", Points: at(1.0)}, rates.Station{Name: "W", Points: at(2.08)})
	sys.Prices["Z|Z"] = map[string]float64{"4": 12.4}
	sys.Prices["W|W"] = map[string]float64{"4": 5}
	got = chainUses(sys, route, truck40, false)
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
			}
		}
		if got != tc.want {
			t.Errorf("%s: %.2f, want %.2f: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

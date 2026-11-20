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
	"sync"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/carbon-cost/tariffs"
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

var (
	setOnce sync.Once
	theSet  *tariffs.Set
	setErr  error
)

func all(t *testing.T) *tariffs.Set {
	t.Helper()
	setOnce.Do(func() { theSet, setErr = tariffs.Load() })
	if setErr != nil {
		t.Fatal(setErr)
	}
	return theSet
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
		// CO2-afgift: the DK road km's share, 0.1096 t / 2.67 kg per
		// litre = 41.05 l x DKK 2.284.
		{FuelCO2, "DK", rates.CO2, 93.76, 12.57, true},
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
	if len(r.Lines) != 10 {
		t.Errorf("%d lines, want 10", len(r.Lines))
	}
	if r.CarbonEUR != 55.54 || math.Abs(r.TotalEUR-91.72) > 1e-9 {
		t.Errorf("total EUR %v, carbon EUR %v; want 91.72 and 55.54", r.TotalEUR, r.CarbonEUR)
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
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL, APIKey: "k"}, Tariffs: all(t),
		Now: func() time.Time { return time.Date(2026, 11, 3, 15, 0, 0, 0, time.UTC) }}
	r, err := c.Calculate(context.Background(), Request{From: sootcase.Location{Code: "DKCPH"}, To: sootcase.Location{Code: "DEHAM"},
		CargoKg: 20000, Truck: truck40})
	if err != nil {
		t.Fatal(err)
	}
	if r.Date != "2026-11-03" || len(r.Lines) != 9 {
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

// Worked by hand from TestPrice_CopenhagenHamburg (class 1: EUR 91.72):
//
//	class 4: DK 140 km x (0.22 + 0.30 + 0.06) DKK = EUR 4.13 + 5.63 + 1.13
//	         DE 141 km x (0.155 + 0.023 + 0.012 + 0.079) = EUR 21.86 + 3.24 + 1.69 + 11.14
//	         ferry EUR 2.25, fuel CO2 EUR 7.18 + 12.57; total 70.82, tolls 48.82, saving 20.90
//	class 5: DK 140 km x (0.11 + 0 + 0.02) DKK = EUR 2.06 + 0 + 0.38; DE exempt
//	         ferry EUR 2.25, no road fuel; total 4.69, tolls 2.44, saving 87.03
func TestPrice_Compare(t *testing.T) {
	req := Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75, CompareCO2Classes: []int{1, 4, 5}, TripsPerYear: 200}
	r, err := Price(cphHam, all(t), req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	want := []Comparison{
		{CO2Class: 1, TollEUR: 69.72, TotalEUR: 91.72, CarbonEUR: 55.54},
		{CO2Class: 4, TollEUR: 48.82, TotalEUR: 70.82, CarbonEUR: 38.77, SavingEUR: 20.90, SavingPerYearEUR: 4180},
		{CO2Class: 5, TollEUR: 2.44, TotalEUR: 4.69, CarbonEUR: 2.25, SavingEUR: 87.03, SavingPerYearEUR: 17406},
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
	if r.TotalEUR != 91.72 || len(r.Lines) != 10 {
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

// Ferry ETS by law: Køge-Rønne is under the Bornholm derogation
// (Implementing Decision (EU) 2023/2895), Esbjerg-Nordby's ferries are
// under 5,000 GT, and a trip over two crossings gets a line for each.
func TestPrice_FerryETSByLaw(t *testing.T) {
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	nov26 := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)
	trip := func(path [][2]float64, parts ...sootcase.Part) sootcase.Result {
		var km, ttw float64
		for _, p := range parts {
			km += p.DistanceKm
			ttw += p.TTWKg
		}
		return sootcase.Result{TTWKg: 100 + ttw, Legs: []sootcase.LegResult{{DistanceKm: 200, TTWKg: 100 + ttw,
			RouteParts: map[string]float64{"ferry": km}, CountryKm: map[string]float64{"DK": 200 - km}, Path: path, Parts: parts}}}
	}
	req := Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75}
	ferryLines := func(r Response) []Line {
		var out []Line
		for _, l := range r.Lines {
			if l.Charge == FerryETS {
				out = append(out, l)
			}
		}
		return out
	}
	// Køge-Rønne: no ETS cost.
	koge := [][2]float64{{12.15, 55.46}, {12.19494, 55.456}, {14.69132, 55.09977}, {14.70, 55.10}}
	r, _ := PriceWith(trip(koge, sootcase.Part{Kind: "ferry", DistanceKm: 165, TTWKg: 300}), all(t), &fd, req, nov26)
	if ls := ferryLines(r); len(ls) != 0 || !hasNote(r, "2023/2895") || r.FerryCrossing != "Køge–Rønne" {
		t.Errorf("Køge-Rønne: lines %+v, crossing %q, notes %v", ls, r.FerryCrossing, r.Notes)
	}
	// Ystad-Rønne with the truck's tare: its ships' (Express 1 and
	// Express 5, as Bornholmslinjen names them) MRV data for 2025.
	tare := req
	tare.Truck.TareKg = 15000
	ystad := [][2]float64{{13.80, 55.43}, {13.824636, 55.425923}, {14.691324, 55.099769}, {14.70, 55.10}}
	r, _ = PriceWith(trip(ystad, sootcase.Part{Kind: "ferry", DistanceKm: 68, TTWKg: 120}), all(t), &fd, tare, nov26)
	if ls := ferryLines(r); len(ls) != 1 || ls[0].Section != "Ystad–Rønne" || !strings.Contains(ls[0].Source, "EU MRV 2025") ||
		!strings.Contains(ls[0].Source, "EXPRESS 1, EXPRESS 5") {
		t.Errorf("Ystad-Rønne: %+v", ls)
	}
	// Dover-Calais: a port outside the EU, half the emissions (40 kg x
	// 0.5 x 75 EUR/t, without the tare: Sootcase's part).
	dover := [][2]float64{{1.30, 51.13}, {1.332393, 51.123741}, {1.857771, 50.967324}, {1.88, 50.96}}
	r, _ = PriceWith(trip(dover, sootcase.Part{Kind: "ferry", DistanceKm: 40, TTWKg: 40}), all(t), &fd, req, nov26)
	if ls := ferryLines(r); len(ls) != 1 || ls[0].Section != "Dover–Calais" || ls[0].Amount != 1.5 {
		t.Errorf("Dover-Calais: %+v, notes %v", ls, r.Notes)
	}
	// Belfast-Cairnryan: no EU ETS (two UK ports); the UK ETS on half its
	// emissions with uka_gbp_per_t (30 kg x 0.5 x 50 GBP/t = GBP 0.75).
	nir := [][2]float64{{-5.90, 54.63}, {-5.879398, 54.636557}, {-5.036792, 54.985017}, {-5.03, 54.99}}
	uk := req
	uk.UKAGbpPerT = 50
	uk.FX = map[string]float64{"GBP": 0.85}
	r, err = PriceWith(trip(nir, sootcase.Part{Kind: "ferry", DistanceKm: 60, TTWKg: 30}), all(t), &fd, uk, nov26)
	if err != nil {
		t.Fatal(err)
	}
	var ukl []Line
	for _, l := range r.Lines {
		if l.Charge == FerryUKETS {
			ukl = append(ukl, l)
		}
	}
	if ls := ferryLines(r); len(ls) != 0 || len(ukl) != 1 || ukl[0].Currency != "GBP" || ukl[0].Amount != 0.75 || !strings.Contains(ukl[0].Source, "para 15(1)(a)") {
		t.Errorf("Belfast-Cairnryan: EU %+v, UK %+v, notes %v", ls, ukl, r.Notes)
	}
	// Esbjerg-Nordby: ships under 5,000 GT.
	fano := [][2]float64{{8.46, 55.47}, {8.44007, 55.46088}, {8.40845, 55.45018}, {8.40, 55.45}}
	r, _ = PriceWith(trip(fano, sootcase.Part{Kind: "ferry", DistanceKm: 2.3, TTWKg: 4}), all(t), &fd, req, nov26)
	if ls := ferryLines(r); len(ls) != 0 || !hasNote(r, "under 5000 GT") {
		t.Errorf("Esbjerg-Nordby: lines %+v, notes %v", ls, r.Notes)
	}
	// Rødby-Puttgarden and Helsingør-Helsingborg: a line each, at the
	// default parts' emissions (no tare): 30 kg and 8 kg x 75 EUR/t.
	both := [][2]float64{{10.9, 54.2}, {11.2276, 54.5001}, {11.355, 54.66}, {12.3, 55.6}, {12.61414, 56.03305}, {12.69152, 56.04331}, {12.8, 56.1}}
	r, _ = PriceWith(trip(both, sootcase.Part{Kind: "ferry", DistanceKm: 19, TTWKg: 30}, sootcase.Part{Kind: "ferry", DistanceKm: 4.5, TTWKg: 8}), all(t), &fd, req, nov26)
	ls := ferryLines(r)
	if len(ls) != 2 || ls[0].Section != "Rødby–Puttgarden" || ls[0].Amount != 2.25 || ls[1].Section != "Helsingør–Helsingborg" || ls[1].Amount != 0.6 {
		t.Errorf("two crossings: %+v", ls)
	}
	if r.FerryCrossing != "Rødby–Puttgarden, Helsingør–Helsingborg" {
		t.Errorf("crossings %q", r.FerryCrossing)
	}
	// A route passing near Esbjerg's terminals but crossing elsewhere
	// isn't taken for Esbjerg-Nordby: the part's length doesn't fit.
	near := [][2]float64{{8.46, 55.47}, {8.44007, 55.46088}, {8.42, 55.452}, {9.9, 57.6}, {8.0, 58.1}}
	r, _ = PriceWith(trip(near, sootcase.Part{Kind: "ferry", DistanceKm: 130, TTWKg: 200}), all(t), &fd, req, nov26)
	if ls := ferryLines(r); len(ls) != 1 || ls[0].Amount != 15 || r.FerryCrossing != "" {
		t.Errorf("near Esbjerg: %+v, crossing %q", ls, r.FerryCrossing)
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

// Serbia, from the decision (Službeni glasnik 57/2026): Beograd to Niš jug,
// category 4, 7080 RSD; Dimitrovgrad to Beograd 10830; category 3 Beograd
// to Niš jug 3540; Smederevo to Niš jug, a pair Putevi Srbije's price list
// doesn't print, 5680. At the NBS's middle rate of the day (117.6013).
func TestSerbia(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	trip := func(path [][2]float64) sootcase.Result {
		return sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"RS": 300}, Path: path}}}
	}
	bgNis := [][2]float64{{20.60, 44.70}, {20.61189, 44.66423}, {21.81577, 43.32747}, {21.85, 43.30}}
	dimBg := [][2]float64{{22.75, 43.01}, {22.73643, 43.02192}, {21.9, 43.35}, {20.61189, 44.66423}, {20.60, 44.70}}
	smNis := [][2]float64{{20.95, 44.60}, {20.95723, 44.58996}, {21.81577, 43.32747}, {21.85, 43.30}}
	for _, tc := range []struct {
		path  [][2]float64
		truck rates.Truck
		rsd   float64
	}{
		{bgNis, truck40, 7080},
		{dimBg, truck40, 10830},
		{bgNis, rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 3540},
		{smNis, truck40, 5680},
	} {
		r, err := Price(trip(tc.path), all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		if want := math.Round(tc.rsd/117.6013*100) / 100; math.Abs(r.TotalEUR-want) > 0.011 {
			t.Errorf("%v %+v: total %.2f, want %.2f: %v", tc.path[1], tc.truck, r.TotalEUR, want, r.Notes)
		}
	}
}

// Serbia's past tolls in RSD, from the decision's tables in Službeni
// glasnik: Beograd to Niš jug, category 4, 6130 RSD from 1 January 2024
// (119/2023), 6760 from 10 July 2024 (58/2024, kept by 107/2024 from 10
// January 2025), 7040 from 10 July 2025 (58/2025; category 3 3520), 7080
// from 1 January 2026 (120/2025).
func TestSerbiaGazette(t *testing.T) {
	bgNis := [][2]float64{{20.60, 44.70}, {20.61189, 44.66423}, {21.81577, 43.32747}, {21.85, 43.30}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"RS": 300}, Path: bgNis}}}
	for _, tc := range []struct {
		date  string
		truck rates.Truck
		want  float64
	}{
		{"2024-03-01", truck40, 6130},
		{"2024-09-01", truck40, 6760},
		{"2025-03-01", truck40, 6760},
		{"2026-03-01", truck40, 7080},
		{"2025-09-01", truck40, 7040},
		{"2025-09-01", rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 3520},
	} {
		date, _ := time.Parse(time.DateOnly, tc.date)
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, FX: map[string]float64{"RSD": 1}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.TotalEUR-tc.want) > 0.011 {
			t.Errorf("%s %+v: %.2f RSD, want %.2f: %v %v", tc.date, tc.truck, r.TotalEUR, tc.want, r.Lines, r.Notes)
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

// The Maurice-Lemaire tunnel (APRR, barrier at Lusse) and the Puymorens
// tunnel (ASF): class 3 (two axles) 19.00 and 26.40 EUR with VAT, class 4
// 31.90 and 43.50 (APRR's TML sheet of 1 February 2026, ASF's guide of 1
// June 2026); priced without the 20% VAT.
func TestFrenchTunnels(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	lusse := [][2]float64{{7.05, 48.29}, {7.08457, 48.29216}, {7.12, 48.27}}
	puymorens := [][2]float64{{1.80, 42.56}, {1.82396, 42.53961}, {1.85, 42.52}}
	rigid := rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}
	for _, tc := range []struct {
		path  [][2]float64
		name  string
		truck rates.Truck
		want  float64
	}{
		{lusse, "Lusse", truck40, 31.90 / 1.2},
		{lusse, "Lusse", rigid, 19.00 / 1.2},
		{puymorens, "Puymorens", truck40, 43.50 / 1.2},
		{puymorens, "Puymorens", rigid, 26.40 / 1.2},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 20, CountryKm: map[string]float64{"FR": 20}, Path: tc.path}}}
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
	if !files["DK dk/dk-2026-01-01.orct.json"] || !files["DE de/de-2024-07-01.orct.json"] {
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
	// Bought in Denmark: the CO2 tax per litre (2.284 DKK in 2026) on the
	// road fuel's litres, the CO2 at 2.67 kg per litre, or as given.
	r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "DK"}, d)
	if err != nil {
		t.Fatal(err)
	}
	l, ok = line(r, FuelCO2, "DK", rates.CO2)
	if !ok || l.Rate != 2.284 || l.RateUnit != "DKK/l" || l.TonnesCO2 != 0 || math.Abs(l.Litres-l.Amount/2.284) > 0.01 || l.Litres < 40 {
		t.Errorf("DK fuel line %+v", l)
	}
	r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "DK", DieselL: 100}, d)
	if err != nil {
		t.Fatal(err)
	}
	if l, ok := line(r, FuelCO2, "DK", rates.CO2); !ok || l.Litres != 100 || math.Abs(l.Amount-228.4) > 0.01 {
		t.Errorf("DK fuel line with diesel_l %+v", l)
	}
	// 51.9 øre in 2024, 226.1 in 2025 (the archived table).
	for d, want := range map[string]float64{"2024-06-01": 0.519, "2025-06-01": 2.261} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "DK", DieselL: 100}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "DK", rates.CO2); !ok || l.Rate != want {
			t.Errorf("DK %s: %+v", d, l)
		}
	}
	// Norway's CO2-avgift on mineral oil per litre: NOK 3.79 in 2025, 4.42 in
	// 2026 but 3.09 on road diesel from 1 May to 31 August.
	for d, want := range map[string]float64{"2024-06-01": 3.17, "2025-06-01": 3.79, "2026-06-01": 3.09, "2026-11-03": 4.42} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "NO", DieselL: 100, FX: map[string]float64{"NOK": 11.5}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "NO", rates.CO2); !ok || l.Rate != want || l.RateUnit != "NOK/l" {
			t.Errorf("NO %s: %+v", d, l)
		}
	}
	// Finland's hiilidioksidivero on diesel oil: EUR 0.1978 per litre in 2024
	// and 2025, 0.1812 from 2026.
	for d, want := range map[string]float64{"2024-06-01": 0.1978, "2025-12-31": 0.1978, "2026-11-03": 0.1812} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "FI", DieselL: 100}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "FI", rates.CO2); !ok || l.Rate != want || l.RateUnit != "EUR/l" || math.Abs(l.AmountEUR-100*want) > 0.01 {
			t.Errorf("FI %s: %+v", d, l)
		}
	}
	// Lithuania's CO2 component of the excise on gas oils: EUR 53.6 per
	// 1,000 litres from 2025, none before.
	for d, want := range map[string]float64{"2025-06-01": 0.0536, "2026-11-03": 0.0536} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "LT", DieselL: 1000}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "LT", rates.CO2); !ok || l.Rate != want || math.Abs(l.AmountEUR-53.6) > 0.01 {
			t.Errorf("LT %s: %+v", d, l)
		}
	}
	r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "LT"}, time.Date(2024, 6, 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := line(r, FuelCO2, "LT", rates.CO2); ok {
		t.Error("LT fuel line in 2024")
	}
	// Poland's opłata emisyjna on diesel oil: PLN 80 per 1,000 litres
	// (Prawo ochrony środowiska art. 321f pkt 2), a fixed fee per litre.
	for _, d := range []string{"2024-06-01", "2026-11-03"} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "PL", DieselL: 1000, FX: map[string]float64{"PLN": 4.25}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "PL", rates.CO2); !ok || l.Rate != 0.08 || l.RateUnit != "PLN/l" || math.Abs(l.Amount-80) > 0.01 || math.Abs(l.AmountEUR-80/4.25) > 0.01 {
			t.Errorf("PL %s: %+v", d, l)
		}
	}
	// Luxembourg's taxe CO2 on gas oil motor fuel: EUR 120.86, 132.55 and
	// 144.60 per 1,000 litres in 2024, 2025 and 2026.
	for d, want := range map[string]float64{"2024-06-01": 0.12086, "2025-06-01": 0.13255, "2026-11-03": 0.1446} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "LU", DieselL: 1000}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "LU", rates.CO2); !ok || l.Rate != want || math.Abs(l.AmountEUR-1000*want) > 0.01 {
			t.Errorf("LU %s: %+v", d, l)
		}
	}
	// Iceland's kolefnisgjald on gas and diesel oil: ISK 13.45, 21.40 and
	// 28.30 per litre in 2024, 2025 and 2026.
	for d, want := range map[string]float64{"2024-06-01": 13.45, "2025-06-01": 21.4, "2026-11-03": 28.3} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "IS", DieselL: 100, FX: map[string]float64{"ISK": 140}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "IS", rates.CO2); !ok || l.Rate != want || l.RateUnit != "ISK/l" || math.Abs(l.Amount-100*want) > 0.01 || math.Abs(l.AmountEUR-100*want/140) > 0.01 {
			t.Errorf("IS %s: %+v", d, l)
		}
	}
	// Sweden's koldioxidskatt on diesel per litre: SEK 2.811 in 2025, cut to
	// 0.411 from 1 July to 30 November 2026.
	for d, want := range map[string]float64{"2025-06-01": 2.811, "2026-11-03": 0.411, "2026-12-15": 2.811, "2024-06-01": 2.723} {
		date, _ := time.Parse("2006-01-02", d)
		r, err = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: truck40, FuelCountry: "SE", DieselL: 100, FX: map[string]float64{"SEK": 11}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, FuelCO2, "SE", rates.CO2); !ok || l.Rate != want || l.RateUnit != "SEK/l" || math.Abs(l.Amount-100*want) > 0.01 {
			t.Errorf("SE %s: %+v", d, l)
		}
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

// Italy by concession: km on Autostrada del Brennero's A22 south of
// Bolzano at its 2026 mountain rate from its tariff PDF (class 5 0.18378,
// VAT and ANAS quotas included: the A22 is a mountain stretch from the
// Brenner to Affi), km on ASPI's A1 at ASPI's 2026 rate (0.19034); the A22
// line names the operator.
func TestItalyOperators(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	a1 := [][2]float64{{11.19187, 44.14234}, {11.19150, 44.13922}, {11.19156, 44.13688}, {11.19185, 44.13445}, {11.19230, 44.13252}, {11.19359, 44.12917}, {11.19467, 44.12720}, {11.19593, 44.12528}, {11.19760, 44.12325}, {11.20007, 44.12074}, {11.21426, 44.10865}, {11.21636, 44.10652}, {11.22021, 44.10219}, {11.22349, 44.09763}, {11.22840, 44.08950}, {11.23020, 44.08687}, {11.23555, 44.07763}, {11.23717, 44.07508}}
	a22 := [][2]float64{{11.23365, 46.27388}, {11.23330, 46.27256}, {11.23269, 46.27110}, {11.22905, 46.26516}, {11.22814, 46.26390}, {11.22080, 46.25646}, {11.21933, 46.25522}, {11.21460, 46.25186}, {11.21032, 46.24804}, {11.20789, 46.24664}, {11.19945, 46.24312}, {11.17430, 46.23473}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{
		{DistanceKm: 7, CountryKm: map[string]float64{"IT": 7}, Path: a1},
		{DistanceKm: 6.6, CountryKm: map[string]float64{"IT": 6.6}, Path: a22},
	}}
	rx, err := roads.Default()
	if err != nil {
		t.Fatal(err)
	}
	rk := RoadKm(rx, []Run{{Kind: "road", Country: "IT", Points: a1}, {Kind: "road", Country: "IT", Points: a22}})
	r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, roadKm: rk}, date)
	if err != nil {
		t.Fatal(err)
	}
	got := map[float64]float64{}
	for _, l := range r.Lines {
		if l.Charge == RoadToll && l.Country == "IT" && l.Component == rates.Toll {
			got[l.Rate] += l.Km
			if l.Rate == 0.18378 && !strings.Contains(l.Section, "Autostrada del Brennero") {
				t.Errorf("A22 line section %q", l.Section)
			}
		}
	}
	if got[0.19034] < 6 || got[0.18378] < 5 || len(got) != 2 {
		t.Errorf("IT km by rate %v, lines %v", got, r.Lines)
	}
}

// Italy: the Superstrada Pedemontana Veneta at its own rate (class 5 EUR
// 0.43824/km, from Autostrade per l'Italia's toll calculator file), and the
// open A9 and A12 Roma-Civitavecchia's km at 0 (they're charged at their
// barriers; these paths pass none).
func TestItalyOpenSystemsAndSPV(t *testing.T) {
	date := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	spv := [][2]float64{{11.42126, 45.64400}, {11.41409, 45.64137}, {11.40974, 45.63931}, {11.40688, 45.63772}, {11.40447, 45.63620}, {11.40094, 45.63365}, {11.39801, 45.63112}, {11.39582, 45.62890}, {11.39427, 45.62713}, {11.39202, 45.62416}, {11.38972, 45.62026}, {11.38785, 45.61563}, {11.38471, 45.60472}}
	a9 := [][2]float64{{9.04862, 45.77229}, {9.04486, 45.75946}, {9.04371, 45.75673}, {9.04177, 45.75372}, {9.03770, 45.74871}}
	// The carriageways OSM tags toll=no that the Roma Nord and Roma Sud
	// barriers charge (tools/tables/browser/it-aspi-routes.txt), and the
	// A24's before the Roma Est barrier, which charges a fixed toll.
	d18 := [][2]float64{{12.60621, 42.14118}, {12.60455, 42.13872}, {12.58287, 42.10178}, {12.58177, 42.10038}, {12.56149, 42.08463}, {12.55999, 42.08362}, {12.54203, 42.07549}, {12.54038, 42.07437}, {12.53832, 42.07257}, {12.53691, 42.07081}, {12.53630, 42.06974}, {12.53544, 42.06766}, {12.53516, 42.06638}, {12.52728, 41.99400}, {12.52667, 41.98915}, {12.52621, 41.98700}}
	d19 := [][2]float64{{12.65002, 41.83416}, {12.62672, 41.84261}, {12.60342, 41.85105}}
	a24 := [][2]float64{{12.69094, 41.92513}, {12.68637, 41.92410}, {12.66565, 41.91876}, {12.66368, 41.91842}, {12.66112, 41.91834}, {12.65836, 41.91870}, {12.65537, 41.91964}, {12.65327, 41.92079}}
	// Free stretches at the end of a closed system whose barrier or end
	// station charges their km (the same file), tagged toll=no in OSM.
	a14dir := [][2]float64{{12.15469, 44.42778}, {12.14623, 44.42302}, {12.13483, 44.41722}, {12.11308, 44.41340}, {12.06803, 44.39981}, {12.06595, 44.39960}, {12.06237, 44.39982}, {12.01765, 44.40738}, {12.01403, 44.40765}, {12.01048, 44.40752}, {11.97964, 44.40471}, {11.97467, 44.40397}, {11.95481, 44.39765}, {11.90840, 44.38739}}
	a26 := [][2]float64{{8.52587, 45.87515}, {8.53100, 45.87514}, {8.53448, 45.87434}, {8.53769, 45.87240}, {8.53955, 45.86962}, {8.54021, 45.86715}, {8.54044, 45.86472}, {8.54000, 45.86101}, {8.53882, 45.85841}, {8.53501, 45.85291}, {8.53422, 45.85082}, {8.53389, 45.84883}, {8.53425, 45.84529}, {8.53698, 45.83832}, {8.53741, 45.83571}, {8.53732, 45.83201}, {8.53528, 45.81102}, {8.53401, 45.80918}, {8.53040, 45.80608}, {8.52890, 45.80421}, {8.52816, 45.80239}}
	a4 := [][2]float64{{7.96377, 45.23950}, {7.94828, 45.23385}, {7.89636, 45.21258}, {7.84918, 45.19210}, {7.71771, 45.12662}, {7.71468, 45.12426}, {7.71131, 45.11932}}
	a1 := [][2]float64{{14.32052, 40.84595}, {14.31728, 40.84753}, {14.31627, 40.84938}, {14.31656, 40.85080}, {14.31835, 40.85379}, {14.31827, 40.85640}, {14.32146, 40.86867}, {14.32133, 40.87060}, {14.32037, 40.87505}, {14.31759, 40.88641}, {14.31749, 40.88860}, {14.32774, 40.95543}, {14.32782, 40.95822}, {14.32650, 40.97333}}
	teramo := [][2]float64{{13.71677, 42.59674}, {13.71396, 42.59985}, {13.71346, 42.60339}, {13.71463, 42.60623}, {13.71807, 42.60906}, {13.72154, 42.61020}, {13.72448, 42.61041}, {13.72767, 42.60996}, {13.73647, 42.60737}, {13.74015, 42.60702}, {13.74501, 42.60752}, {13.74855, 42.60865}, {13.75310, 42.61139}, {13.75587, 42.61436}, {13.75735, 42.61728}, {13.75767, 42.61922}, {13.75727, 42.62163}, {13.75495, 42.62588}, {13.74640, 42.63498}, {13.73632, 42.64166}, {13.72554, 42.65267}, {13.72363, 42.65562}, {13.72321, 42.65793}, {13.72394, 42.65995}, {13.72756, 42.66319}, {13.72954, 42.66586}, {13.73237, 42.66733}, {13.73665, 42.66755}}
	a34 := [][2]float64{{13.43648, 45.86547}, {13.45741, 45.87684}, {13.46058, 45.87977}, {13.47062, 45.89087}, {13.47317, 45.89288}, {13.49408, 45.90069}, {13.50052, 45.90187}, {13.52317, 45.90112}, {13.53671, 45.90317}, {13.58469, 45.90476}, {13.58887, 45.90610}, {13.60216, 45.91533}, {13.60761, 45.91774}}
	// The A22 south of the Brennero barrier, its mountain stretch.
	a22 := [][2]float64{{11.44990, 46.87999}, {11.47687, 46.87052}, {11.47977, 46.86963}}
	// ASPI's mountain stretches (tools/tables/browser/it-aspi-mountain.txt):
	// the A1 by Barberino di Mugello and the A7 by Serravalle Scrivia.
	a1mtn := [][2]float64{{11.20924, 43.95354}, {11.20977, 43.95267}, {11.21134, 43.95075}, {11.22037, 43.94238}, {11.22179, 43.94060}, {11.22251, 43.93942}, {11.22348, 43.93703}, {11.22381, 43.93490}, {11.22375, 43.93269}, {11.22313, 43.93011}, {11.22255, 43.92879}, {11.22163, 43.92722}, {11.21938, 43.92454}, {11.20941, 43.91389}, {11.19523, 43.89908}, {11.19330, 43.89730}, {11.19117, 43.89573}}
	a7 := [][2]float64{{8.89839, 44.69257}, {8.90021, 44.69038}, {8.90053, 44.68985}, {8.90168, 44.68653}, {8.90417, 44.68312}, {8.90426, 44.68227}, {8.90388, 44.68111}, {8.90383, 44.68035}, {8.90507, 44.67652}, {8.90513, 44.67577}, {8.90500, 44.67431}, {8.90573, 44.67163}, {8.90609, 44.67073}, {8.90745, 44.66836}, {8.90986, 44.66581}}
	a12 := [][2]float64{{12.28999, 41.82963}, {12.28507, 41.83467}, {12.26513, 41.85301}, {12.26402, 41.85459}, {12.26339, 41.85611}, {12.26261, 41.86195}, {12.26184, 41.86383}, {12.26045, 41.86552}, {12.24939, 41.87728}, {12.24812, 41.87827}, {12.24663, 41.87896}, {12.23873, 41.88112}}
	rx, err := roads.Default()
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name, op string
		path     [][2]float64
		km, rate float64
	}{{"SPV", "Superstrada Pedemontana Veneta S.p.A.|SPV", spv, 5.4, 0.43824},
		{"A9", "Autostrade per l'Italia S.p.A.|A9", a9, 2.7, 0},
		{"A12 Roma-Civitavecchia", "Autostrade per l'Italia S.p.A.|A12|Roma-Civitavecchia", a12, 7.3, 0},
		{"A1dir to the Roma Nord barrier", "Autostrade per l'Italia S.p.A.|A1dir", d18, 19, 0.19034},
		{"A1dir to the Roma Sud barrier", "Autostrade per l'Italia S.p.A.|A1dir", d19, 4.2, 0.19034},
		{"A14dir to the Ravenna barrier", "Autostrade per l'Italia S.p.A.|A14dir", a14dir, 20.5, 0.19034},
		{"A26 to the Lago Maggiore station", "Autostrade per l'Italia S.p.A.|A26|Lago Maggiore", a26, 9, 0.22437},
		{"A4 Torino to the Rondissone barrier", "SATAP S.p.A.|A4", a4, 23.8, 0.33006},
		{"A1 Napoli to the Napoli Nord barrier", "Autostrade per l'Italia S.p.A.|A1", a1, 14.3, 0.19034},
		{"A24 from the Teramo barrier", "Strada dei Parchi S.p.A.|A24", teramo, 12.3, 0.25161},
		{"A34 from the Villesse barrier", "Società Autostrade Alto Adriatico S.p.A.|A34", a34, 15.2, 0.18898},
		{"A22 Brennero-Affi", "Autostrada del Brennero S.p.A.|A22|Brennero-Affi", a22, 2.4, 0.18378},
		{"A1 Bologna-Calenzano, mountain", "Autostrade per l'Italia S.p.A.|A1|mountain", a1mtn, 7.2, 0.22437},
		{"A7 Serravalle-Genova, mountain", "Autostrade per l'Italia S.p.A.|A7", a7, 3, 0.22437}} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: tc.km, CountryKm: map[string]float64{"IT": tc.km}, Path: tc.path}}}
		rk := RoadKm(rx, []Run{{Kind: "road", Country: "IT", Points: tc.path}})
		if rk["IT"].MotorwayOp[tc.op] < tc.km-0.5 {
			t.Errorf("%s: the roads data puts %v on %s", tc.name, rk["IT"].MotorwayOp, tc.op)
		}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, roadKm: rk}, date)
		if err != nil {
			t.Fatal(err)
		}
		var km, amount float64
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.Country == "IT" {
				amount += l.Amount
				if l.Component == rates.Toll && l.Rate == tc.rate {
					km += l.Km
				}
			}
		}
		if (tc.rate > 0 && km < tc.km-0.5) || math.Abs(amount-tc.rate*km) > 0.05 {
			t.Errorf("%s: %.2f km at %v, EUR %.2f: %v", tc.name, km, tc.rate, amount, r.Lines)
		}
	}
	// The A24 before the Roma Est barrier is free: the barrier charges it.
	if rk := RoadKm(rx, []Run{{Kind: "road", Country: "IT", Points: a24}}); rk["IT"].MotorwayOp["Strada dei Parchi S.p.A.|A24"] > 0.5 {
		t.Errorf("A24 before the Roma Est barrier: %v", rk["IT"].MotorwayOp)
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
// the Mersey Gateway (over 12 t GBP 9.60), the Kiltunnel (EUR 5), the
// AP-15 Marcilla barrier (Pesados II EUR 5.45 with IVA, 4.50 without) and
// the Túnel d'Envalira (more than two axles EUR 20.30).
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
		{"Túnel d'Envalira (5 axles)", "AD", cross(42.549016, 1.697136, 0.001, 0.003), 20.3},
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

// The AP-53 (Ministry of Transport's tolls in force 2026, IVA included):
// Pesados 2 from Santiago to Alto de Santo Domingo 7.25, Ribadulla to
// Silleda 2.45 (Pesados 1: 2.05). The paths run through the stretches' middles,
// Milan's ring roads: a fixed toll at each barrier (Milano Serravalle,
// 2026, VAT included), class 5: Terrazzano 8.40, Vimercate 4.90, Sesto San
// Giovanni 6.30; class B at Terrazzano 3.60. The paths cross each barrier.
func TestMilanBarriers(t *testing.T) {
	light := rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		want  float64
	}{
		{"Terrazzano", [][2]float64{{9.0585, 45.5370}, {9.058708, 45.541038}, {9.0589, 45.5450}}, truck40, 8.40},
		{"Terrazzano, class B", [][2]float64{{9.0585, 45.5370}, {9.058708, 45.541038}, {9.0589, 45.5450}}, light, 3.60},
		// Milano Serravalle's Vimercate barrier is the A51's toll gate at Agrate Brianza (km 19.5).
		{"Vimercate (Agrate Brianza)", [][2]float64{{9.3315, 45.5585}, {9.33303, 45.561395}, {9.3345, 45.5645}}, truck40, 4.90},
		{"not at Vimercate Sud", [][2]float64{{9.3600, 45.6040}, {9.357957, 45.608418}, {9.3560, 45.6120}}, truck40, 0},
		{"Sesto San Giovanni", [][2]float64{{9.2590, 45.5510}, {9.263721, 45.55137}, {9.2680, 45.5517}}, truck40, 6.30},
		// SITAF's A32 (2026): Avigliana 15.90 and Salbertrand 21.70 for class 5.
		{"A32 Avigliana", [][2]float64{{7.3990, 45.0960}, {7.393959, 45.094598}, {7.3890, 45.0930}}, truck40, 15.90},
		{"A32 Avigliana, class B", [][2]float64{{7.3990, 45.0960}, {7.393959, 45.094598}, {7.3890, 45.0930}}, light, 6.50},
		{"A32 Salbertrand", [][2]float64{{6.8710, 45.0600}, {6.866239, 45.058245}, {6.8610, 45.0565}}, truck40, 21.70},
		// Autostrade per l'Italia's form (2026): A8 Milano Nord 4.60, A9 Como
		// Grandate 6.00, Tangenziale di Torino Bruere 2.80 and Trofarello 4.90.
		{"A8 Milano Nord", [][2]float64{{9.0650, 45.5450}, {9.06089, 45.54788}, {9.0570, 45.5505}}, truck40, 4.60},
		{"A9 Como Grandate", [][2]float64{{9.0480, 45.7700}, {9.04939, 45.77392}, {9.0505, 45.7780}}, truck40, 6.00},
		{"A9 Como Grandate, class B", [][2]float64{{9.0480, 45.7700}, {9.04939, 45.77392}, {9.0505, 45.7780}}, light, 2.50},
		{"A55 Bruere", [][2]float64{{7.5390, 45.0790}, {7.54072, 45.08232}, {7.5425, 45.0855}}, truck40, 2.80},
		{"A55 Trofarello", [][2]float64{{7.7330, 44.9650}, {7.73692, 44.96596}, {7.7410, 44.9670}}, truck40, 4.90},
		// The Tangenziale's Settimo Torinese toll, collected at the A5's Torino Nord barrier.
		{"A5 Torino Nord", [][2]float64{{7.7330, 45.1440}, {7.73537, 45.14557}, {7.7380, 45.1470}}, truck40, 3.40},
		// The A21's open Torino-Villanova stretch, collected at the Villanova barrier.
		{"A21 Villanova", [][2]float64{{7.9180, 44.9535}, {7.92318, 44.95303}, {7.9280, 44.9525}}, truck40, 2.90},
		{"A12 Roma Ovest", [][2]float64{{12.2290, 41.8880}, {12.22674, 41.89122}, {12.2245, 41.8945}}, truck40, 6.20},
		{"A12 Aurelia", [][2]float64{{11.8250, 42.0560}, {11.82428, 42.05929}, {11.8235, 42.0625}}, truck40, 6.20},
		{"A3 Napoli Sud", [][2]float64{{14.3240, 40.8435}, {14.32797, 40.84184}, {14.3315, 40.8405}}, truck40, 6.10},
		{"A3 Nocera", [][2]float64{{14.6380, 40.7375}, {14.64118, 40.73637}, {14.6445, 40.7352}}, truck40, 6.10},
		{"A12 Tarquinia", [][2]float64{{11.7250, 42.2600}, {11.72785, 42.25695}, {11.7305, 42.2540}}, truck40, 2.90},
		// Closed-system barriers: the form's toll to the next station less
		// the stations' km apart at the motorway's rate (Milano Sud-Lodi
		// 6.20 = 3.65 + 13.4 km x 0.19034, to the cent).
		{"A1 Milano Sud", [][2]float64{{9.3070, 45.3520}, {9.30982, 45.34934}, {9.3125, 45.3465}}, truck40, 3.65},
		{"A7 Milano Ovest", [][2]float64{{9.1405, 45.3925}, {9.13876, 45.38911}, {9.1370, 45.3858}}, truck40, 2.61},
		{"A4 Milano Ghisolfa", [][2]float64{{9.0570, 45.5122}, {9.06107, 45.51246}, {9.0650, 45.5127}}, truck40, 3.25},
		{"A4 Milano Est", [][2]float64{{9.2645, 45.5560}, {9.26845, 45.5562}, {9.2725, 45.5564}}, truck40, 2.70},
		{"A24 Roma Est", [][2]float64{{12.6995, 41.9258}, {12.70355, 41.92609}, {12.7075, 41.9263}}, truck40, 4.17},
		{"A27 Venezia", [][2]float64{{12.2830, 45.5730}, {12.28397, 45.57661}, {12.2850, 45.5800}}, truck40, 5.20},
		{"A16 Napoli Est", [][2]float64{{14.4670, 40.9155}, {14.47088, 40.91625}, {14.4750, 40.9170}}, truck40, 4.03},
		{"A22 Brennero", [][2]float64{{11.4335, 46.8880}, {11.4348, 46.88512}, {11.4360, 46.8820}}, truck40, 3.08},
		{"A6 Barriera di Torino", [][2]float64{{7.7480, 44.8570}, {7.74864, 44.85416}, {7.7493, 44.8512}}, truck40, 7.18},
		{"A23 Ugovizza-Tarvisio", [][2]float64{{13.4770, 46.5068}, {13.48088, 46.50684}, {13.4850, 46.5069}}, truck40, 3.43},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"IT": 1}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 5000, Truck: tc.truck}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "barrier") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v", tc.name, got, tc.want, r.Lines)
		}
	}
}

// Sicily's A18 and A20 (Consorzio per le Autostrade Siciliane, 2026, VAT
// included): class 5 Messina Sud to Catania Nord 10.90, Roccalumera to
// Taormina 2.50; Messina Nord to Buonfornello 25.40 (class B 10.60). The
// paths run through the stretches' middles, 300 m either side.
func TestSicilyCAS(t *testing.T) {
	a18 := [][2]float64{{15.461201, 38.044921}, {15.458766, 38.043023}, {15.456331, 38.041125}, {15.344244, 37.919489}, {15.343013, 37.916972}, {15.341782, 37.914455}, {15.278043, 37.852218}, {15.275704, 37.850251}, {15.273365, 37.848284}, {15.227383, 37.816307}, {15.223973, 37.816156}, {15.220563, 37.816005}, {15.176798, 37.754306}, {15.175536, 37.751799}, {15.174274, 37.749292}, {15.149866, 37.665170}, {15.149818, 37.662472}, {15.149770, 37.659774}, {15.129159, 37.592785}, {15.127933, 37.590268}, {15.126707, 37.587751}}
	a20 := [][2]float64{{15.439733, 38.238439}, {15.437347, 38.236498}, {15.434961, 38.234557}, {15.354123, 38.206561}, {15.350694, 38.206425}, {15.347265, 38.206289}, {15.235198, 38.173109}, {15.232061, 38.172016}, {15.228924, 38.170923}, {15.134192, 38.131526}, {15.131453, 38.129902}, {15.128714, 38.128278}, {15.047919, 38.140198}, {15.045154, 38.141795}, {15.042389, 38.143392}, {14.914704, 38.162152}, {14.911525, 38.161137}, {14.908346, 38.160122}, {14.760235, 38.147045}, {14.757270, 38.145688}, {14.754305, 38.144331}, {14.671075, 38.080634}, {14.668021, 38.079409}, {14.664967, 38.078184}, {14.479104, 38.025716}, {14.475703, 38.026035}, {14.472302, 38.026354}, {14.281184, 37.999666}, {14.277864, 37.999009}, {14.274544, 37.998352}, {14.176502, 38.008834}, {14.173109, 38.009195}, {14.169716, 38.009556}, {14.044759, 38.020992}, {14.042308, 38.022876}, {14.039857, 38.024760}, {13.915626, 37.997239}, {13.912521, 37.996103}, {13.909416, 37.994967}}
	light := rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		want  float64
	}{
		{"A18 Messina Sud to Catania Nord", a18, truck40, 10.90},
		{"A18 Roccalumera to Taormina", a18[3:6], truck40, 2.50},
		{"A20 Messina Nord to Buonfornello", a20, truck40, 25.40},
		{"A20 Messina Nord to Buonfornello, class B", a20, light, 10.60},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{"IT": 100}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 5000, Truck: tc.truck}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "A18") || strings.Contains(l.Section, "A20") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// 300 m either side along each stretch.
func TestAP53(t *testing.T) {
	south := [][2]float64{{-8.482406, 42.805564}, {-8.483561, 42.803003}, {-8.484716, 42.800442}, {-8.387161, 42.747675}, {-8.383600, 42.747013}, {-8.380039, 42.746351}, {-8.292354, 42.717730}, {-8.288770, 42.718319}, {-8.285186, 42.718908}, {-8.200645, 42.693912}, {-8.197127, 42.693141}, {-8.193609, 42.692370}, {-8.142676, 42.660453}, {-8.141011, 42.658049}, {-8.139346, 42.655645}, {-8.119122, 42.629105}, {-8.116951, 42.626931}, {-8.114780, 42.624757}, {-8.091521, 42.599924}, {-8.088980, 42.597980}, {-8.086439, 42.596036}}
	light := rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		want  float64
	}{
		{"Santiago to Alto de Santo Domingo", south, truck40, 7.25 / 1.21},
		{"Ribadulla to Silleda", south[3:9], truck40, 2.45 / 1.21},
		{"Ribadulla to Silleda, Pesados 1", south[3:9], light, 2.05 / 1.21},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"ES": 50}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 5000, Truck: tc.truck}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "AP-53") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// The Madrid radials (SEITT 2026, IVA included): Pesados 2 on the R-3 from
// Madrid (M-40) to the A-3 6.75 cash, 6.10 by tag; on the R-4 from Ocaña
// to the M-50 12.45 (Pesados 1: 8.55); free from 00:00 to 06:00. The paths
// run through the stretches' middles, 300 m either side.
func TestMadridRadials(t *testing.T) {
	r3 := [][2]float64{{-3.599630, 40.411303}, {-3.596233, 40.410537}, {-3.592836, 40.409771}, {-3.562146, 40.396273}, {-3.559129, 40.394859}, {-3.556112, 40.393445}, {-3.510685, 40.396264}, {-3.507412, 40.395232}, {-3.504139, 40.394200}, {-3.455450, 40.369220}, {-3.454187, 40.366700}, {-3.452924, 40.364180}, {-3.415941, 40.302374}, {-3.413827, 40.300211}, {-3.411713, 40.298048}}
	r4 := [][2]float64{{-3.604535, 39.992369}, {-3.605629, 39.994933}, {-3.606723, 39.997497}, {-3.670797, 40.063714}, {-3.671269, 40.066388}, {-3.671741, 40.069062}, {-3.669699, 40.148545}, {-3.670571, 40.151159}, {-3.671443, 40.153773}, {-3.746915, 40.217522}, {-3.746289, 40.220177}, {-3.745663, 40.222832}}
	light := rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}
	day := time.Date(2026, 11, 20, 12, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		etc   bool
		at    time.Time
		want  float64
	}{
		{"R-3 Madrid to the A-3", r3, truck40, false, day, 6.75 / 1.21},
		{"R-3 Madrid to the A-3 by tag", r3, truck40, true, day, 6.10 / 1.21},
		{"R-4 Ocaña to the M-50", r4, truck40, false, day, 12.45 / 1.21},
		{"R-4 Ocaña to the M-50, Pesados 1", r4, light, false, day, 8.55 / 1.21},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"ES": 50}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 5000, Truck: tc.truck, ETC: tc.etc}, tc.at)
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "R-3") || strings.Contains(l.Section, "R-4") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// The Basque AP-8 and AP-1 (Bidegi's 2026 sheet, VAT included): Pesados 2
// from Bilbao's western access to Zarautz's main plaza 30.38, Eibar to
// Etxabarri-Ibiña 20.06, Donostia's eastern plaza to Behobia 6.53. The paths
// run through the stretches' middles, 300 m either side.
func TestBasqueAP8(t *testing.T) {
	west := [][2]float64{{-2.757602, 43.231056}, {-2.753926, 43.230732}, {-2.750250, 43.230408}, {-2.697674, 43.202532}, {-2.695202, 43.200524}, {-2.692730, 43.198516}, {-2.623820, 43.178233}, {-2.620696, 43.176787}, {-2.617572, 43.175341}, {-2.561651, 43.167017}, {-2.557970, 43.167285}, {-2.554289, 43.167553}, {-2.483254, 43.181026}, {-2.479566, 43.181242}, {-2.475878, 43.181458}, {-2.417722, 43.206361}, {-2.416493, 43.208906}, {-2.415264, 43.211451}, {-2.372888, 43.263420}, {-2.371645, 43.265962}, {-2.370402, 43.268504}, {-2.304752, 43.269726}, {-2.302003, 43.267917}, {-2.299254, 43.266108}, {-2.221993, 43.286451}, {-2.218878, 43.284990}, {-2.215763, 43.283529}, {-2.140817, 43.283048}, {-2.137112, 43.283114}, {-2.133407, 43.283180}}
	ap1 := [][2]float64{{-2.426363, 43.165485}, {-2.426807, 43.162807}, {-2.427251, 43.160129}, {-2.430458, 43.113112}, {-2.432498, 43.110862}, {-2.434538, 43.108612}, {-2.445981, 43.080167}, {-2.448950, 43.078562}, {-2.451919, 43.076957}, {-2.494423, 43.049804}, {-2.496983, 43.047860}, {-2.499543, 43.045916}, {-2.616823, 42.958657}, {-2.620022, 42.957316}, {-2.623221, 42.955975}}
	east := [][2]float64{{-1.874903, 43.309746}, {-1.872776, 43.311956}, {-1.870649, 43.314166}, {-1.848480, 43.318197}, {-1.844964, 43.317341}, {-1.841448, 43.316485}, {-1.809770, 43.327081}, {-1.806285, 43.328004}, {-1.802800, 43.328927}, {-1.769906, 43.334811}, {-1.766743, 43.336221}, {-1.763580, 43.337631}}
	for _, tc := range []struct {
		name string
		path [][2]float64
		want float64
	}{
		{"Bilbao to Zarautz's main plaza", west, 30.38 / 1.21},
		{"Eibar to Etxabarri-Ibiña", ap1, 20.06 / 1.21},
		{"Donostia to Behobia", east, 6.53 / 1.21},
		// AP-636 Beasain to Bergara: 0.86 + 1.64 + 3.17 at its three gantries.
		{"AP-636 Beasain to Bergara", [][2]float64{{-2.2200, 43.0420}, {-2.233916, 43.047667}, {-2.299179, 43.077171}, {-2.339413, 43.084813}, {-2.3700, 43.0900}}, (0.86 + 1.64 + 3.17) / 1.21},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"ES": 50}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 5000, Truck: truck40}, time.Date(2026, 11, 20, 12, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "AP-8") || strings.Contains(l.Section, "AP-636") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// The AP-68 (Ministry of Transport's tolls in force 2026, IVA included):
// Pesados 2 from Bilbao to Zaragoza 84.15, 58.91 by tag (Zambrana–Tudela);
// Haro to Alfaro 28.10, by tag 5.06 (Pesados 1: 24.30, by tag 8.77);
// Ziorraga to Altube free for heavy vehicles. The path runs through the
// stretches' middles, 300 m either side.
func TestAP68(t *testing.T) {
	p := [][2]float64{{-2.910133, 43.219166}, {-2.906930, 43.217813}, {-2.903727, 43.216460}, {-2.900159, 43.178148}, {-2.903125, 43.176536}, {-2.906091, 43.174924}, {-2.937658, 43.153550}, {-2.938306, 43.150894}, {-2.938954, 43.148238}, {-2.918714, 43.077277}, {-2.920448, 43.074895}, {-2.922182, 43.072513}, {-2.876349, 42.992571}, {-2.873750, 42.990657}, {-2.871151, 42.988743}, {-2.897810, 42.899867}, {-2.896648, 42.897307}, {-2.895486, 42.894747}, {-2.900719, 42.764742}, {-2.901458, 42.762099}, {-2.902197, 42.759456}, {-2.892642, 42.696324}, {-2.891723, 42.693712}, {-2.890804, 42.691100}, {-2.854282, 42.622689}, {-2.854487, 42.619995}, {-2.854692, 42.617301}, {-2.762885, 42.520334}, {-2.760692, 42.518174}, {-2.758499, 42.516014}, {-2.605333, 42.464346}, {-2.602663, 42.462503}, {-2.599993, 42.460660}, {-2.488247, 42.431668}, {-2.484593, 42.431607}, {-2.480939, 42.431546}, {-2.378028, 42.453267}, {-2.374662, 42.452213}, {-2.371296, 42.451159}, {-2.317049, 42.448142}, {-2.314114, 42.446533}, {-2.311179, 42.444924}, {-2.196857, 42.390163}, {-2.193433, 42.389223}, {-2.190009, 42.388283}, {-2.025006, 42.338241}, {-2.021823, 42.336921}, {-2.018640, 42.335601}, {-1.885621, 42.214127}, {-1.882387, 42.212885}, {-1.879153, 42.211643}, {-1.742787, 42.120982}, {-1.740435, 42.118924}, {-1.738083, 42.116866}, {-1.681983, 42.052433}, {-1.678510, 42.051640}, {-1.675037, 42.050847}, {-1.493458, 41.927496}, {-1.490593, 41.925842}, {-1.487728, 41.924188}, {-1.258049, 41.793055}, {-1.255943, 41.790861}, {-1.253837, 41.788667}, {-1.139145, 41.776793}, {-1.135548, 41.777080}, {-1.131951, 41.777367}, {-1.022835, 41.727282}, {-1.019740, 41.725888}, {-1.016645, 41.724494}}
	light := rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		etc   bool
		want  float64
	}{
		{"Bilbao to Zaragoza", p, truck40, false, 84.15 / 1.21},
		{"Bilbao to Zaragoza by tag", p, truck40, true, 58.91 / 1.21},
		{"Haro to Alfaro", p[27:51], truck40, false, 28.10 / 1.21},
		{"Haro to Alfaro by tag", p[27:51], truck40, true, 5.06 / 1.21},
		{"Haro to Alfaro by tag, Pesados 1", p[27:51], light, true, 8.77 / 1.21},
		{"Ziorraga to Altube", p[12:15], truck40, false, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"ES": 50}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 5000, Truck: tc.truck, ETC: tc.etc}, time.Date(2026, 11, 20, 12, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "AP-68") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.006 {
			t.Errorf("%s: %v, want %v: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
}

// Iceland's kílómetragjald (Lög nr. 100/2025) on 100 km: the motor vehicle
// and the trailer each pay by their own gjaldþyngd, capped by axles (a
// 2-axle tractor at 18,000 kg: ISK 26.25 per km; a 3-axle semi-trailer at
// 24,000 kg: 33.79), the trailer at 60 % in 2026, 80 % in 2027, in full from
// 2030 (100 % in 2028-2029 too), a zero-emission truck and its trailer at
// 20 % in 2026-2029.
func TestIcelandKmFee(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{"IS": 100}}}}
	tr := rates.Truck{MaxMassKg: 40000, Axles: 5, MotorAxles: 2, MotorMassKg: 19000, TrailerMassKg: 35000, Euro: 6, CO2Class: 1}
	sum := func(r Response) (float64, int) {
		s, n := 0.0, 0
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.Country == "IS" {
				s, n = s+l.Amount, n+1
			}
		}
		return math.Round(s*100) / 100, n
	}
	for _, c := range []struct {
		date string
		co2  int
		want float64
	}{
		{"2026-11-04", 1, 2625 + 2027.4}, {"2027-06-01", 1, 2625 + 2703.2}, {"2029-06-01", 1, 2625 + 3379}, {"2030-06-01", 1, 2625 + 3379},
		{"2026-11-04", 5, 525 + 675.8}, {"2030-06-01", 5, 2625 + 3379},
	} {
		date, _ := time.Parse("2006-01-02", c.date)
		tc := tr
		tc.CO2Class = c.co2
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: tc, FX: map[string]float64{"ISK": 140}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if got, n := sum(r); got != c.want || n != 2 {
			t.Errorf("%s co2 class %d: %v in %d lines, want %v; %+v %v", c.date, c.co2, got, n, c.want, r.Lines, r.Notes)
		}
	}
	// A solo truck of 18 t: no trailer line. Without the vehicles' own masses
	// the fee isn't priced, and the note says what to give.
	solo := rates.Truck{MaxMassKg: 18000, Axles: 2, MotorAxles: 2, MotorMassKg: 18000, Euro: 6, CO2Class: 1}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	r, err := Price(trip, all(t), Request{CargoKg: 8000, Truck: solo, FX: map[string]float64{"ISK": 140}}, date)
	if err != nil {
		t.Fatal(err)
	}
	if got, n := sum(r); got != 2625 || n != 1 {
		t.Errorf("solo truck: %v in %d lines; %+v", got, n, r.Lines)
	}
	r, err = Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, FX: map[string]float64{"ISK": 140}}, date)
	if err != nil {
		t.Fatal(err)
	}
	if got, _ := sum(r); got != 0 || !strings.Contains(strings.Join(r.Notes, " "), "truck.motor_mass_kg") {
		t.Errorf("without masses: %v; %v", got, r.Notes)
	}
	// 2025, Lög nr. 87/2004: each vehicle of 10 t or more by its own mass,
	// no maximum by axles: 19 t ISK 7.05, 35 t 17.84 per km; a 9 t truck none.
	d25 := time.Date(2025, 6, 1, 0, 0, 0, 0, time.UTC)
	if r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: tr, FX: map[string]float64{"ISK": 140}}, d25); err != nil {
		t.Fatal(err)
	} else if got, n := sum(r); got != 705+1784 || n != 2 {
		t.Errorf("2025: %v in %d lines; %+v %v", got, n, r.Lines, r.Notes)
	}
	light := rates.Truck{MaxMassKg: 9000, Axles: 2, MotorAxles: 2, MotorMassKg: 9000, Euro: 6, CO2Class: 1}
	if r, err := Price(trip, all(t), Request{CargoKg: 3000, Truck: light, FX: map[string]float64{"ISK": 140}}, d25); err != nil {
		t.Fatal(err)
	} else if got, _ := sum(r); got != 0 {
		t.Errorf("2025, 9 t: %v; %+v %v", got, r.Lines, r.Notes)
	}
	if err := (rates.Truck{MaxMassKg: 40000, Axles: 5, MotorMassKg: 19000, Euro: 6, CO2Class: 1}).Validate(); err == nil {
		t.Error("motor_mass_kg without motor_axles accepted")
	}
}

// Belarus's BelToll from 1 September 2026 (Mintrans resolution No. 42):
// EUR 0.121, 0.152 and 0.182 per km for 2, 3 and 4+ axles (trailers
// included); 100 km on toll roads.
func TestBelarus(t *testing.T) {
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{"BY": 100}}}}
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	for _, c := range []struct {
		truck rates.Truck
		want  float64
	}{{truck40, 18.2}, {rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 12.1}, {rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}, 15.2}} {
		r, err := Price(trip, all(t), Request{CargoKg: 8000, Truck: c.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, RoadToll, "BY", rates.Toll); !ok || l.Amount != c.want || l.Currency != "EUR" {
			t.Errorf("%d axles: %+v", c.truck.Axles, l)
		}
	}
	// Earlier tariffs, as BelToll announced them: 0.152 (from 1 June 2023),
	// 0.171 (20 September 2024), 0.176 (1 September 2025) for 4+ axles.
	for d, want := range map[string]float64{"2024-06-01": 15.2, "2025-01-01": 17.1, "2026-06-01": 17.6} {
		date, _ := time.Parse("2006-01-02", d)
		r, err := Price(trip, all(t), Request{CargoKg: 8000, Truck: truck40}, date)
		if err != nil {
			t.Fatal(err)
		}
		if l, ok := line(r, RoadToll, "BY", rates.Toll); !ok || l.Amount != want {
			t.Errorf("%s: %+v", d, l)
		}
	}
}

// Poland's A4 Katowice-Kraków: PLN at each of its two plazas, by the motor
// vehicle's axles and the trailer: a 2-axle tractor with a semi-trailer is
// category 3 (32), a 3-axle one category 4 (55); without motor_axles all 5
// axles count (55).
func TestPolandA4(t *testing.T) {
	path := [][2]float64{{19.10, 50.20}, {19.18585, 50.19675}, {19.40, 50.15}, {19.79135, 50.0832}, {19.85, 50.08}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 60, CountryKm: map[string]float64{"PL": 60}, Path: path}}}
	for _, c := range []struct {
		motor int
		want  float64
	}{{0, 110}, {2, 64}, {3, 110}} {
		tr := truck40
		tr.MotorAxles = c.motor
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: tr, FX: map[string]float64{"PLN": 1}}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "A4 ") {
				got += l.Amount
			}
		}
		if math.Abs(got-c.want) > 0.001 {
			t.Errorf("motor axles %d: %v, want %v: %+v", c.motor, got, c.want, r.Lines)
		}
	}
}

// Poland's A1 Rusocin-Toruń (AmberOne): a closed system, PLN 71 including
// VAT from Rusocin to Nowa Wieś for categories 2-4; Pelplin-Grudziądz 28.
func TestPolandA1(t *testing.T) {
	full := [][2]float64{{18.60, 54.24}, {18.61234, 54.22681}, {18.6943, 54.0997}, {18.6743, 54.0349}, {18.6429, 53.9302}, {18.6333, 53.7387},
		{18.6175, 53.6034}, {18.6176, 53.4740}, {18.6928, 53.4257}, {18.7078, 53.2900}, {18.7555, 53.0927}, {18.7376, 53.0356}, {18.7345, 53.0098}, {18.70, 52.98}}
	part := [][2]float64{{18.6409, 53.9329}, {18.6333, 53.7387}, {18.6175, 53.6034}, {18.6176, 53.4740}, {18.6928, 53.4257}, {18.70, 53.42}}
	for _, c := range []struct {
		path [][2]float64
		want float64
	}{{full, 71}, {part, 28}} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 150, CountryKm: map[string]float64{"PL": 150}, Path: c.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, FX: map[string]float64{"PLN": 1}}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "A1 Rusocin") {
				got += l.Amount
			}
		}
		if math.Abs(got-c.want) > 0.001 {
			t.Errorf("A1: %v, want %v: %+v", got, c.want, r.Lines)
		}
	}
}

// Poland's A2 Świecko-Konin (Autostrada Wielkopolska), Rzepin to Konin Modła:
// category 4 (5 axles counted, or a 3-axle tractor with a trailer) 535,
// category 3 (2-axle tractor with a semi-trailer) 364, category 2 (2-axle
// rigid) 253.
func TestPolandA2(t *testing.T) {
	path := [][2]float64{{14.80, 52.33}, {14.8736, 52.3328}, {14.9035, 52.3348}, {15.0874, 52.3252}, {15.5504, 52.3236}, {15.8728, 52.3291}, {16.1008, 52.3589},
		{16.5667, 52.3765}, {16.7318, 52.3506}, {16.7766, 52.3505}, {17.1212, 52.3199}, {17.1512, 52.3106}, {17.5300, 52.3159}, {17.8138, 52.2552}, {17.9515, 52.2219},
		{18.0199, 52.2054}, {18.2152, 52.1622}, {18.30, 52.15}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 250, CountryKm: map[string]float64{"PL": 250}, Path: path}}}
	for _, c := range []struct {
		tr   rates.Truck
		want float64
	}{
		{truck40, 535},
		{rates.Truck{MaxMassKg: 40000, Axles: 5, MotorAxles: 2, Euro: 6, CO2Class: 1}, 364},
		{rates.Truck{MaxMassKg: 40000, Axles: 6, MotorAxles: 3, Euro: 6, CO2Class: 1}, 535},
		{rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 253},
	} {
		r, err := Price(trip, all(t), Request{CargoKg: 8000, Truck: c.tr, FX: map[string]float64{"PLN": 1}}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "A2 Świecko") {
				got += l.Amount
			}
		}
		if math.Abs(got-c.want) > 0.001 {
			t.Errorf("A2 %+v: %v, want %v: %+v", c.tr, got, c.want, r.Lines)
		}
	}
}

// On the A2 the road classes count the concession as local road (the
// e-TOLL doesn't charge it): the note says so, naming the stretches.
func TestPolandLeftOutNote(t *testing.T) {
	path := [][2]float64{{15.0874, 52.3252}, {15.5504, 52.3236}, {15.8728, 52.3291}, {16.1008, 52.3589}}
	rx, err := roads.Default()
	if err != nil {
		t.Fatal(err)
	}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 70, CountryKm: map[string]float64{"PL": 70}, Path: path}}}
	rk := RoadKm(rx, []Run{{Kind: "road", Country: "PL", Points: path}})
	r, err := Price(trip, all(t), Request{CargoKg: 8000, Truck: truck40, FX: map[string]float64{"PLN": 4.3}, roadKm: rk, roadLeftOut: map[string][]string{"PL": rx.LeftOut("PL")}}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, n := range r.Notes {
		if strings.HasPrefix(n, "PL: by OpenStreetMap along the route") {
			if !strings.Contains(n, "including the motorways this toll leaves to their operators: A1 Rusocin-Toruń (AmberOne), A2 Świecko-Konin") {
				t.Errorf("note %q", n)
			}
			return
		}
	}
	t.Errorf("no road-class note for PL: %v", r.Notes)
}

// The A2's earlier price lists, Konin Modła-Świecko in categories 2, 3
// and 4: PLN 193, 274, 394 from 11 March 2024; 205, 292, 421 from 11 September 2024; 220, 316, 454 from 11
// March 2025; 229, 328, 478 from 11 September 2025; 247, 355, 520 from 11
// March 2026.
func TestPolandA2History(t *testing.T) {
	path := [][2]float64{{14.80, 52.33}, {14.8736, 52.3328}, {14.9035, 52.3348}, {15.0874, 52.3252}, {15.5504, 52.3236}, {15.8728, 52.3291}, {16.1008, 52.3589},
		{16.5667, 52.3765}, {16.7318, 52.3506}, {16.7766, 52.3505}, {17.1212, 52.3199}, {17.1512, 52.3106}, {17.5300, 52.3159}, {17.8138, 52.2552}, {17.9515, 52.2219},
		{18.0199, 52.2054}, {18.2152, 52.1622}, {18.30, 52.15}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 250, CountryKm: map[string]float64{"PL": 250}, Path: path}}}
	trucks := []rates.Truck{{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, {MaxMassKg: 40000, Axles: 5, MotorAxles: 2, Euro: 6, CO2Class: 1}, truck40}
	for d, want := range map[string][3]float64{"2024-06-01": {193, 274, 394}, "2024-12-01": {205, 292, 421}, "2025-06-01": {220, 316, 454}, "2025-12-01": {229, 328, 478}, "2026-06-01": {247, 355, 520}} {
		day, _ := time.Parse("2006-01-02", d)
		for i, tr := range trucks {
			r, err := Price(trip, all(t), Request{CargoKg: 8000, Truck: tr, FX: map[string]float64{"PLN": 1}}, day)
			if err != nil {
				t.Fatal(err)
			}
			var got float64
			for _, l := range r.Lines {
				if strings.Contains(l.Section, "A2 Świecko") {
					got += l.Amount
				}
			}
			if math.Abs(got-want[i]) > 0.001 {
				t.Errorf("A2 %s category %d: %v, want %v", d, i+2, got, want[i])
			}
		}
	}
}

// The Faroe Islands' Eysturoyartunnilin: DKK 800 between Streymoy and
// Eysturoy, DKK 200 between Strendur and Runavík (its two Eysturoy
// branches), once per trip through two branches.
func TestFaroeEysturoyartunnilin(t *testing.T) {
	streymoy, strendur, runavik := [2]float64{-6.78065, 62.04672}, [2]float64{-6.75575, 62.11292}, [2]float64{-6.73299, 62.11045}
	mid := map[string][2]float64{"S": {-6.783747, 62.075172}, "N": {-6.762666, 62.106337}, "R": {-6.737624, 62.101623}}
	rb := [2]float64{-6.75758, 62.09865}
	for _, c := range []struct {
		name string
		path [][2]float64
		want float64
	}{
		{"Streymoy-Strendur", [][2]float64{streymoy, mid["S"], rb, mid["N"], strendur}, 800},
		{"Strendur-Runavík", [][2]float64{strendur, mid["N"], rb, mid["R"], runavik}, 200},
		{"Runavík-Streymoy", [][2]float64{runavik, mid["R"], rb, mid["S"], streymoy}, 800},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 10, CountryKm: map[string]float64{"FO": 10}, Path: c.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: truck40, FX: map[string]float64{"DKK": 1}}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Eysturoyartunnilin") {
				got += l.Amount
			}
		}
		if math.Abs(got-c.want) > 0.001 {
			t.Errorf("%s: %v, want %v: %+v", c.name, got, c.want, r.Lines)
		}
	}
}

// Iceland's tunnel tolls: Vaðlaheiðargöng ISK 3,087 (3.5-7.5 t) / 6,505
// (7.5 t and over), Hornafjörður ISK 2,100 (to 7.5 t) / 4,500 (over 7.5 t).
func TestIcelandCrossings(t *testing.T) {
	for _, c := range []struct {
		name    string
		section string
		at      [2]float64
		massKg  int
		want    float64
	}{
		{"Vaðlaheiðargöng 40 t", "Vaðlaheiðargöng", [2]float64{-17.986043, 65.711112}, 40000, 6505},
		{"Vaðlaheiðargöng 7 t", "Vaðlaheiðargöng", [2]float64{-17.986043, 65.711112}, 7000, 3087},
		{"Hornafjörður 40 t", "Hornafjörður", [2]float64{-15.337318, 64.293665}, 40000, 4500},
		{"Hornafjörður 7.5 t", "Hornafjörður", [2]float64{-15.337318, 64.293665}, 7500, 2100},
	} {
		path := [][2]float64{{c.at[0] - 0.02, c.at[1]}, c.at, {c.at[0] + 0.02, c.at[1]}}
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 2, CountryKm: map[string]float64{"IS": 2}, Path: path}}}
		tr := truck40
		tr.MaxMassKg = c.massKg
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tr, FX: map[string]float64{"ISK": 1}}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got float64
		for _, l := range r.Lines {
			if strings.Contains(l.Section, c.section) {
				got += l.Amount
			}
		}
		if math.Abs(got-c.want) > 0.001 {
			t.Errorf("%s: %v, want %v: %+v", c.name, got, c.want, r.Lines)
		}
	}
}

// The A4 Katowice-Kraków's earlier price lists: a 2-axle tractor with a
// semi-trailer (category 3) and a 3-axle one with a trailer (category 4)
// at both plazas.
func TestPolandA4History(t *testing.T) {
	path := [][2]float64{{19.10, 50.20}, {19.18585, 50.19675}, {19.40, 50.15}, {19.79135, 50.0832}, {19.85, 50.08}}
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 60, CountryKm: map[string]float64{"PL": 60}, Path: path}}}
	for _, c := range []struct {
		day        time.Time
		cat3, cat4 float64
	}{
		{time.Date(2024, 1, 10, 0, 0, 0, 0, time.UTC), 54, 92}, // the tolls of 3 April 2023 (Stalexport's press release)
		{time.Date(2024, 2, 1, 0, 0, 0, 0, time.UTC), 54, 92},
		{time.Date(2024, 6, 1, 0, 0, 0, 0, time.UTC), 58, 98},
		{time.Date(2025, 6, 1, 0, 0, 0, 0, time.UTC), 60, 104},
	} {
		for motor, want := range map[int]float64{2: c.cat3, 3: c.cat4} {
			tr := truck40
			tr.MotorAxles = motor
			r, err := Price(trip, all(t), Request{CargoKg: 20000, Truck: tr, FX: map[string]float64{"PLN": 1}}, c.day)
			if err != nil {
				t.Fatal(err)
			}
			var got float64
			for _, l := range r.Lines {
				if strings.Contains(l.Section, "A4 ") {
					got += l.Amount
				}
			}
			if math.Abs(got-want) > 0.001 {
				t.Errorf("%s motor axles %d: %v, want %v", c.day.Format("2006-01-02"), motor, got, want)
			}
		}
	}
}

// The Felbertauerntunnel's toll plaza south of the tunnel, per passage
// either way, VAT included (Mauttarife from 1 January 2026): over 3.5 t
// with 2 axles 36 EUR, 3 axles 54, 4 or more 72.
func TestFelbertauern(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	path := [][2]float64{{12.50, 47.10}, {12.504675, 47.11759}, {12.51, 47.14}}
	for _, tc := range []struct {
		truck rates.Truck
		want  float64
	}{
		{rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 36},
		{rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}, 54},
		{truck40, 72},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 10, CountryKm: map[string]float64{"AT": 10}, Path: path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Felbertauern") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%+v: %.2f, want %.2f: %v", tc.truck, got, tc.want, r.Lines)
		}
	}
}

// Norway's national road ferries, 2026 AutoPASS-regulativ less 12% VAT:
// Halsa-Kanestraum is zone 6, 441 NOK for 14.51-17.5 m (16.5 m assumed),
// 579 over 22 m, 40% off with a business ferry account; Vangsnes to
// Dragsvik by way of Hella is one ticket, zone 6; Bodø-Moskenes zone 95,
// 2,252; Skipavik-Nesvik is free (no line); a road past both Molde-Vestnes
// quays that doesn't take the ferry pays nothing. Moss-Horten's own list:
// 1,371 NOK for 14.01-17.5 m, 959.70 with a Moss-Horten agreement. A
// zero-emission truck pays half, to the krone (Halsa 221, Moss-Horten
// 686), and the discounts apply on that (Moss-Horten's list: 480.20).
func TestNorwayFerries(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	join := func(parts ...[][2]float64) [][2]float64 {
		var out [][2]float64
		for _, p := range parts {
			out = append(out, p...)
		}
		return out
	}
	// The OpenStreetMap car ferry lines (ways 23112418, 14329891 and
	// 1375717924, 23212730 reversed, 43767530), with a road at each end.
	halsa := join([][2]float64{{8.10, 63.05}}, [][2]float64{{8.12524, 63.05325}, {8.12811, 63.05385}, {8.22562, 63.06815}, {8.22699, 63.06833}}, [][2]float64{{8.24, 63.075}})
	vangsnesDragsvik := join([][2]float64{{6.66, 61.17}},
		[][2]float64{{6.63755, 61.17512}, {6.63783, 61.17522}, {6.63808, 61.17537}, {6.63826, 61.17553}, {6.6383, 61.17566}, {6.63818, 61.17594}, {6.63797, 61.17621}, {6.63755, 61.17647}, {6.59353, 61.2015}, {6.59079, 61.20344}, {6.59017, 61.20432}, {6.58984, 61.20515}, {6.58993, 61.20597}, {6.59023, 61.20669}, {6.59069, 61.20718}, {6.59172, 61.20754}, {6.59284, 61.2077}, {6.5937, 61.20773}, {6.59588, 61.2077}, {6.59752, 61.20756}},
		[][2]float64{{6.59589, 61.20775}, {6.59414, 61.20803}, {6.59026, 61.20877}, {6.57677, 61.2122}, {6.56982, 61.21388}, {6.56691, 61.21452}}, [][2]float64{{6.55, 61.22}})
	bodoMoskenes := join([][2]float64{{14.40, 67.285}}, [][2]float64{{14.39369, 67.28836}, {14.39261, 67.28866}, {14.39181, 67.28881}, {14.39098, 67.28891}, {14.38976, 67.28891}, {14.38856, 67.28884}, {14.38634, 67.28853}, {14.37719, 67.28725}, {14.37163, 67.28645}, {14.36136, 67.28497}, {14.35574, 67.28408}, {14.33116, 67.27962}, {14.32825, 67.27915}, {14.32537, 67.2788}, {14.30855, 67.27708}, {14.30546, 67.27688}, {14.30156, 67.2767}, {14.29721, 67.27666}, {14.29068, 67.27666}, {14.28264, 67.27704}, {14.27765, 67.2776}, {14.2755, 67.27816}, {14.2736, 67.27888}, {14.2719, 67.27984}, {14.26999, 67.28159}, {14.2679, 67.28417}, {14.25785, 67.30903}, {14.25343, 67.31701}, {14.24799, 67.32387}, {14.23802, 67.33187}, {14.22667, 67.33713}, {14.21232, 67.34295}, {14.18444, 67.35251}, {14.16693, 67.35737}, {14.13202, 67.36626}, {14.10205, 67.37405}, {14.05235, 67.38659}, {14.00891, 67.39754}, {14.00368, 67.40001}, {14.00168, 67.40364}, {14.0035, 67.40863}, {14.00867, 67.4193}, {14.01117, 67.42902}, {14.01034, 67.43248}, {14.00742, 67.43489}, {14.00274, 67.4364}, {13.99454, 67.43845}, {13.98953, 67.44034}, {13.97811, 67.44584}, {13.85504, 67.50695}, {13.63384, 67.61182}, {13.27458, 67.78453}, {13.18915, 67.82872}, {13.08186, 67.87785}, {13.05361, 67.88966}, {13.04807, 67.89243}, {13.04288, 67.89505}, {13.0399, 67.89645}, {13.03903, 67.89722}, {13.03924, 67.89803}, {13.03973, 67.89871}, {13.04046, 67.89918}, {13.04188, 67.89957}, {13.0438, 67.89983}}, [][2]float64{{13.05, 67.905}})
	skipavikNesvik := join([][2]float64{{6.08, 59.25}}, [][2]float64{{6.09531, 59.25306}, {6.09585, 59.25309}, {6.09674, 59.25311}, {6.09761, 59.25309}, {6.09902, 59.25294}, {6.10162, 59.25274}, {6.10299, 59.25269}, {6.10513, 59.25268}, {6.10718, 59.25271}, {6.11123, 59.25306}, {6.14803, 59.25718}, {6.15267, 59.2578}, {6.15668, 59.25853}, {6.15842, 59.25888}, {6.15915, 59.2591}, {6.16006, 59.25944}, {6.16035, 59.25965}, {6.16051, 59.25993}, {6.16055, 59.26026}, {6.16043, 59.26043}, {6.16012, 59.26071}, {6.15925, 59.26154}}, [][2]float64{{6.165, 59.265}})
	mossHorten := join([][2]float64{{10.67, 59.435}}, [][2]float64{{10.65425, 59.42944}, {10.65393, 59.42782}, {10.65345, 59.42646}, {10.6526, 59.4252}, {10.65066, 59.42344}, {10.64779, 59.42152}, {10.64459, 59.41958}, {10.63775, 59.41641}, {10.62495, 59.41207}, {10.60398, 59.41068}, {10.58273, 59.41043}, {10.56147, 59.41019}, {10.54022, 59.40994}, {10.51896, 59.40969}, {10.50001, 59.41088}, {10.49088, 59.41213}, {10.48938, 59.41214}}, [][2]float64{{10.47, 59.41}}) // OSM way 228431771
	byRoad := [][2]float64{{7.18, 62.74}, {7.169748, 62.737084}, {7.30, 62.60}, {7.085033, 62.651616}, {7.0, 62.66}}
	ferry := func(r Response) (float64, int) {
		var sum float64
		var n int
		for _, l := range r.Lines {
			if l.Component == rates.Toll && strings.Contains(l.Section, " ferry: ") {
				sum += l.Amount
				n++
			}
		}
		return sum, n
	}
	long := truck40
	long.LengthM = 25.25
	zev := truck40
	zev.CO2Class = 5
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		etc   bool
		want  float64
		lines int
	}{
		{"Halsa-Kanestraum", halsa, truck40, false, 393.75, 1},
		{"Halsa-Kanestraum over 22 m", halsa, long, false, 516.96, 1},
		{"Halsa-Kanestraum, business account", halsa, truck40, true, 236.25, 1},
		{"Vangsnes-Hella-Dragsvik", vangsnesDragsvik, truck40, false, 393.75, 1},
		{"Bodø-Moskenes", bodoMoskenes, truck40, false, 2010.71, 1},
		{"Skipavik-Nesvik", skipavikNesvik, truck40, false, 0, 0}, // a 0 ticket adds no line
		{"by road past Molde and Furneset", byRoad, truck40, false, 0, 0},
		{"Moss-Horten", mossHorten, truck40, false, 1224.11, 1},
		{"Moss-Horten, agreement", mossHorten, truck40, true, 856.88, 1},
		{"Halsa-Kanestraum, zero-emission", halsa, zev, false, 197.32, 1},
		{"Halsa-Kanestraum, zero-emission, business account", halsa, zev, true, 118.39, 1},
		{"Moss-Horten, zero-emission", mossHorten, zev, false, 612.50, 1},
		{"Moss-Horten, zero-emission, agreement", mossHorten, zev, true, 428.75, 1},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 30, CountryKm: map[string]float64{"NO": 30}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, ETC: tc.etc, FX: map[string]float64{"NOK": 1}}, date)
		if err != nil {
			t.Fatal(err)
		}
		if got, n := ferry(r); math.Abs(got-tc.want) > 0.011 || n != tc.lines {
			t.Errorf("%s: %.2f NOK in %d lines, want %.2f in %d: %v", tc.name, got, n, tc.want, tc.lines, r.Notes)
		}
	}
}

// The Belgrade bypass from 1 April 2026: category 4 (four or more axles)
// pays per section, by direction, in RSD (Putevi Srbije's list: 340, 120,
// 120, 290, 480, 390, 130 from Batajnica to Bubanj Potok); three axles
// pay nothing, nor does a truck driving the other way past a point.
func TestBelgradeBypass(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	whole := [][2]float64{{20.26037, 44.874}, {20.259242, 44.872908}, {20.258114, 44.871816}, {20.251545, 44.825299}, {20.251937, 44.823972}, {20.252329, 44.822645}, {20.25855, 44.788923}, {20.259379, 44.787703}, {20.260208, 44.786483}, {20.301908, 44.751828}, {20.303378, 44.750971}, {20.304848, 44.750114}, {20.364598, 44.712395}, {20.366174, 44.71164}, {20.36775, 44.710885}, {20.446828, 44.719668}, {20.448605, 44.720141}, {20.450382, 44.720614}, {20.508692, 44.716821}, {20.510529, 44.716486}, {20.512366, 44.716151}}
	one := [][2]float64{{20.364598, 44.712395}, {20.366174, 44.71164}, {20.36775, 44.710885}}
	back := [][2]float64{{20.36775, 44.710885}, {20.366174, 44.71164}, {20.364598, 44.712395}}
	three := rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		want  float64
	}{
		{"Batajnica to Bubanj Potok", whole, truck40, 1870},
		{"Ostružnica to Orlovača", one, truck40, 480},
		{"three axles", one, three, 0},
		{"the other way past the point", back, truck40, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 40, CountryKm: map[string]float64{"RS": 40}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, ETC: true, FX: map[string]float64{"RSD": 1}}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Obilaznica") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%s: %.2f RSD, want %.2f: %v %v", tc.name, got, tc.want, r.Lines, r.Notes)
		}
	}
	// Without a rate given, the dinar is converted at the NBS's official
	// middle rate of the day (117.6013 on 4 November 2026; the ECB has none).
	trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 40, CountryKm: map[string]float64{"RS": 40}, Path: one}}}
	r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, ETC: true}, date)
	if err != nil {
		t.Fatal(err)
	}
	eur := 0.0
	for _, l := range r.Lines {
		if strings.Contains(l.Section, "Obilaznica") {
			eur += l.AmountEUR
		}
	}
	if want := math.Round(480/117.6013*100) / 100; eur != want || !strings.Contains(strings.Join(r.Provenance.FX, " "), "National Bank of Serbia") {
		t.Errorf("Ostružnica to Orlovača: %.2f EUR, want %.2f: %v", eur, want, r.Provenance.FX)
	}
}

// Jadrolinija's state ferry lines (2026 price lists, VAT 25% out): a goods
// vehicle up to 5 t of load capacity pays a flat fare, over 5 t a fare per
// tonne of it. Split-Supetar (line 631) has one price for the year: 9.80
// EUR per tonne, 7.84 net; Split-Stari Grad (line 635) 10.50 off-season
// and 13.40 in the season (29 May to 27 September), 8.40 and 10.72 net.
// The path runs through the stations' points out on OpenStreetMap's car
// ferry lines (ways 12307574 and 29500693).
func TestJadrolinija(t *testing.T) {
	split := [][2]float64{{16.440, 43.505}, {16.434624, 43.498295}}
	supetar := append(append([][2]float64{}, split...), [2]float64{16.551522, 43.389463}, [2]float64{16.555, 43.383})
	stariGrad := [][2]float64{{16.440, 43.505}, {16.434506, 43.500217}, {16.572899, 43.185182}, {16.58, 43.18}}
	big := truck40
	big.CapacityKg = 25000
	small := rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1, CapacityKg: 4500}
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		date  time.Time
		want  float64
	}{
		{"Split-Supetar, 25 t of capacity", supetar, big, time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC), 196.00},
		{"Split-Supetar, 25 t, summer", supetar, big, time.Date(2026, 7, 15, 0, 0, 0, 0, time.UTC), 196.00},
		{"Split-Supetar, 4.5 t of capacity", supetar, small, time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC), 36.56},
		{"Split-Stari Grad, 25 t, off-season", stariGrad, big, time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC), 210.00},
		{"Split-Stari Grad, 25 t, season", stariGrad, big, time.Date(2026, 7, 15, 0, 0, 0, 0, time.UTC), 268.00},
		{"no load capacity given", supetar, truck40, time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC), 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 30, CountryKm: map[string]float64{"HR": 30}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, tc.date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Jadrolinija") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%s: %.2f EUR, want %.2f: %v", tc.name, got, tc.want, r.Notes)
		}
		if tc.truck.CapacityKg == 0 && !strings.Contains(strings.Join(r.Notes, " "), "capacity_kg") {
			t.Errorf("%s: no note asks for truck.capacity_kg: %v", tc.name, r.Notes)
		}
	}
}

// CalMac's commercial vehicle single rates from 27 March 2026 (excluding
// VAT): Uig-Tarbert £50.14 plus £6.58 per 0.5 m, £267.28 at 16.5 m and £208.06 at 12 m; Wemyss
// Bay-Rothesay £175.56 at 16.5 m, as the table prints them. The path runs
// through the stations' points on OpenStreetMap's car ferry lines.
func TestCalMac(t *testing.T) {
	date := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC)
	uig := [][2]float64{{-6.36, 57.585}, {-6.373818, 57.58159}, {-6.792356, 57.894463}, {-6.80, 57.898}}
	wemyss := [][2]float64{{-4.89, 55.876}, {-4.898381, 55.874457}, {-5.050433, 55.842912}, {-5.055, 55.836}}
	rigid := truck40
	rigid.LengthM = 12
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		want  float64
	}{
		{"Uig-Tarbert, 16.5 m", uig, truck40, 267.28},
		{"Uig-Tarbert, 12 m", uig, rigid, 208.06},
		{"Wemyss Bay-Rothesay, 16.5 m", wemyss, truck40, 175.56},
		{"Uig-Lochmaddy, 16.5 m", [][2]float64{{-6.36, 57.585}, {-6.373818, 57.58159}, {-7.150063, 57.596799}, {-7.16, 57.60}}, truck40, 267.28},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 30, CountryKm: map[string]float64{"GB": 30}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, FX: map[string]float64{"GBP": 1}}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "CalMac") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%s: £%.2f, want £%.2f: %v", tc.name, got, tc.want, r.Notes)
		}
	}
}

// Estonia's state ferries (regulation nr 120, annex and § 6): a truck over
// 3.5 t pays 16 EUR on Virtsu-Kuivastu and 18 EUR on Rohuküla-Heltermaa,
// × 1.2 towards the islands on Fridays from 13:00 and back on Sundays from
// 13:00 (19.20 and 21.60); Sõru-Triigi 22 EUR. The path runs through the
// stations' points on OpenStreetMap's ferry lines.
func TestEstoniaFerries(t *testing.T) {
	toMuhu := [][2]float64{{23.51, 58.574}, {23.494629, 58.576471}, {23.409212, 58.573992}, {23.39, 58.573}}
	back := [][2]float64{{23.39, 58.573}, {23.409212, 58.573992}, {23.494629, 58.576471}, {23.51, 58.574}}
	toHiiumaa := [][2]float64{{23.43, 58.906}, {23.401957, 58.907899}, {23.056169, 58.867514}, {23.03, 58.865}}
	soru := [][2]float64{{22.73, 58.59}, {22.723359, 58.595062}, {22.523353, 58.687367}, {22.505, 58.70}}
	wed, fri, sun := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC), time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC), time.Date(2026, 11, 22, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name string
		path [][2]float64
		date time.Time
		at   string
		want float64
	}{
		{"Virtsu-Kuivastu, Wednesday", toMuhu, wed, "14:00", 16},
		{"Virtsu-Kuivastu, Friday 14:00", toMuhu, fri, "14:00", 19.2},
		{"Virtsu-Kuivastu, Friday 10:00", toMuhu, fri, "10:00", 16},
		{"Kuivastu-Virtsu, Friday 14:00", back, fri, "14:00", 16},
		{"Kuivastu-Virtsu, Sunday 14:00", back, sun, "14:00", 19.2},
		{"Rohuküla-Heltermaa, Friday 14:00", toHiiumaa, fri, "14:00", 21.6},
		{"Triigi-Sõru, Friday 14:00", soru, fri, "14:00", 22},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 30, CountryKm: map[string]float64{"EE": 30}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, Time: tc.at}, tc.date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Estonia's state ferries") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%s: %.2f EUR, want %.2f: %v", tc.name, got, tc.want, r.Notes)
		}
	}
}

// The Strait of Messina (Caronte & Tourist's commercial vehicle fares,
// November 2026): 15.51-16.50 m one way 165.60 EUR Messina-Villa San
// Giovanni and 224.30 back, plus 4.30 EUR per trip for the port company's
// services; 12 m (11.51-12.50) 141.60 and 197.40.
func TestMessina(t *testing.T) {
	date := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC)
	toCalabria := [][2]float64{{15.522, 38.130}, {15.529591, 38.136352}, {15.615476, 38.213285}, {15.635, 38.218}}
	toSicily := [][2]float64{{15.635, 38.218}, {15.615476, 38.213285}, {15.529591, 38.136352}, {15.522, 38.130}}
	rigid := truck40
	rigid.LengthM = 12
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		want  float64
	}{
		{"to Calabria, 16.5 m", toCalabria, truck40, 169.90},
		{"to Sicily, 16.5 m", toSicily, truck40, 228.60},
		{"to Calabria, 12 m", toCalabria, rigid, 145.90},
		{"to Sicily, 12 m", toSicily, rigid, 201.70},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 20, CountryKm: map[string]float64{"IT": 20}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Strait of Messina") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.want) > 0.011 {
			t.Errorf("%s: %.2f EUR, want %.2f: %v", tc.name, got, tc.want, r.Notes)
		}
	}
}

// Bornholmslinjen's freight prices (loaded, excluding VAT): 2026 Køge-Rønne
// 1,013 DKK for a semi-trailer to 17 m (1,078 in 2027), Ystad-Rønne 1,065
// DKK for a road train to 19 m, Rønne-Sassnitz 2,495 DKK; a 12 m rigid
// truck, a lorry over 10 m, 703 DKK on Køge-Rønne.
func TestBornholm(t *testing.T) {
	koge := [][2]float64{{12.19, 55.456}, {12.202263, 55.454895}, {14.625569, 55.087042}, {14.69, 55.10}}
	ystad := [][2]float64{{13.826, 55.427}, {13.801016, 55.395578}, {14.627326, 55.08976}, {14.69, 55.10}}
	sassnitz := [][2]float64{{14.69, 55.10}, {14.638178, 55.081728}, {13.591477, 54.480362}, {13.588, 54.484}}
	train := truck40
	train.LengthM = 18.75
	rigid := truck40
	rigid.LengthM = 12
	d26, d27 := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC), time.Date(2027, 3, 3, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		date  time.Time
		dkk   float64
	}{
		{"Køge-Rønne, semi-trailer, 2026", koge, truck40, d26, 1013},
		{"Køge-Rønne, semi-trailer, 2027", koge, truck40, d27, 1078},
		{"Køge-Rønne, 12 m lorry, 2026", koge, rigid, d26, 703},
		{"Ystad-Rønne, road train, 2026", ystad, train, d26, 1065},
		{"Rønne-Sassnitz, semi-trailer, 2026", sassnitz, truck40, d26, 2495},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"DK": 50}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, tc.date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Bornholmslinjen") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.dkk) > 0.011 {
			t.Errorf("%s: %.2f DKK, want %.0f: %v", tc.name, got, tc.dkk, r.Notes)
		}
	}
}

// TestScandlines prices Scandlines' crossings and Øresundslinjen's
// Helsingør–Helsingborg from their gross freight tariffs (loaded, by the
// metre up) and the month's surcharges per commencing metre (BAF and GIR;
// energy and green on Helsingør–Helsingborg; not the ETS surcharge), and
// a trip over both crossings at the transit ticket.
func TestScandlines(t *testing.T) {
	pr := [][2]float64{{11.22, 54.49}, {11.231603, 54.506517}, {11.34562, 54.650674}, {11.35, 54.66}}
	rg := [][2]float64{{12.10, 54.15}, {12.026699, 54.293513}, {11.927163, 54.569509}, {11.93, 54.58}}
	hh := [][2]float64{{12.61, 56.03}, {12.623761, 56.034108}, {12.685027, 56.040775}, {12.70, 56.045}}
	both := append(append(append([][2]float64{}, pr...), [2]float64{12.0, 55.3}, [2]float64{12.5, 55.9}), hh...)
	length := func(m float64) rates.Truck { tr := truck40; tr.LengthM = m; return tr }
	nov, jun := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC), time.Date(2026, 6, 15, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		date  time.Time
		eur   float64
	}{
		{"Puttgarden-Rødby, 16.5 m, November", pr, truck40, nov, 265.30 + 17*(1.64+0.88)},
		{"Puttgarden-Rødby, 16.5 m, June", pr, truck40, jun, 265.30 + 17*(1.38+0.88)},
		{"Puttgarden-Rødby, 16.5 m, January", pr, truck40, time.Date(2026, 1, 20, 0, 0, 0, 0, time.UTC), 265.30 + 17*(0.79+0.88)},
		{"Helsingør-Helsingborg, 16.5 m, January", hh, truck40, time.Date(2026, 1, 20, 0, 0, 0, 0, time.UTC), 169.30 + 17*(0.88+0.30)},
		{"Puttgarden-Rødby, road train", pr, length(18.75), nov, 297.60 + 19*(1.64+0.88)},
		{"Puttgarden-Rødby, 10 m", pr, length(10), nov, 156.10 + 10*(1.64+0.88)},
		{"Rostock-Gedser, 16.5 m", rg, truck40, nov, 236.20 + 17*(4.59+1.66)},
		{"Helsingør-Helsingborg, 16.5 m", hh, truck40, nov, 169.30 + 17*(1.18+0.45)},
		{"Puttgarden-Rødby and Helsingør-Helsingborg: transit", both, truck40, nov, 403.70 + 17*(1.64+0.88+1.18+0.45)},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 200, CountryKm: map[string]float64{"DK": 200}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, tc.date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Scandlines") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.eur) > 0.011 {
			t.Errorf("%s: %.2f EUR, want %.2f: %v", tc.name, got, tc.eur, r.Notes)
		}
	}
}

// TestElbfaehre prices the Elbe ferry Glückstadt-Wischhafen: the truck by
// length at the net fare plus the fuel surcharge, and the load per started
// 1,000 kg (ORCT unit t on load_kg in steps of 1,000 kg).
func TestElbfaehre(t *testing.T) {
	path := [][2]float64{{9.42, 53.80}, {9.398622, 53.793962}, {9.352505, 53.78884}, {9.33, 53.785}}
	length := func(m float64) rates.Truck { tr := truck40; tr.LengthM = m; return tr }
	day := func(s string) time.Time { d, _ := time.Parse(time.DateOnly, s); return d }
	for _, tc := range []struct {
		name  string
		truck rates.Truck
		cargo float64
		date  string
		eur   float64
	}{
		{"16.5 m, 20 t, November 2026", truck40, 20000, "2026-11-20", 37.82 + 2.40 + 20*1.26},
		{"road train, 20.5 t, November 2026", length(18.75), 20500, "2026-11-20", 39.08 + 4.20 + 2.40 + 21*1.26},
		{"16.5 m, 20 t, April 2026", truck40, 20000, "2026-04-01", 36.13 + 1.80 + 20*1.26},
		{"16.5 m, 20 t, before the fuel surcharge", truck40, 20000, "2026-03-01", 36.13 + 20*1.26},
		{"16.5 m, 999 kg, 2025", truck40, 999, "2025-06-01", 34.45 + 1*1.18},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"DE": 50}, Path: path}}}
		r, err := Price(trip, all(t), Request{CargoKg: tc.cargo, Truck: tc.truck}, day(tc.date))
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Elbfähre") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.eur) > 0.011 {
			t.Errorf("%s: %.2f EUR, want %.2f: %v", tc.name, got, tc.eur, r.Notes)
		}
	}
}

// TestPOLSCA prices POLSCA Baltic Ferries' crossings (Polferries and Unity
// Line) from the freight tariff (per unit to 9 m, per commenced metre over
// 9 m) and the BES per commenced metre in force on the day (not the ETS
// surcharge); Gdańsk–Karlshamn only from its opening.
func TestPOLSCA(t *testing.T) {
	sy := [][2]float64{{14.25, 53.90}, {14.235081, 54.075278}, {13.796019, 55.396026}, {13.83, 55.42}}
	st := [][2]float64{{14.25, 53.90}, {14.028139, 54.27659}, {13.14058, 55.33321}, {13.15, 55.37}}
	gn := [][2]float64{{18.68, 54.40}, {18.78442, 54.520945}, {18.058986, 58.83697}, {17.95, 58.90}}
	gk := [][2]float64{{18.68, 54.40}, {18.781135, 54.522891}, {14.904184, 56.07921}, {14.82, 56.16}}
	length := func(m float64) rates.Truck { tr := truck40; tr.LengthM = m; return tr }
	nov, apr, jun := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC), time.Date(2026, 4, 15, 0, 0, 0, 0, time.UTC), time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name  string
		path  [][2]float64
		truck rates.Truck
		date  time.Time
		eur   float64
	}{
		{"Świnoujście-Ystad, 16.5 m, November", sy, truck40, nov, 17 * (25 + 13.00)},
		{"Świnoujście-Ystad, 16.5 m, April", sy, truck40, apr, 17 * (25 + 10.30)},
		{"Świnoujście-Trelleborg, 16.5 m", st, truck40, nov, 17 * (25 + 13.00)},
		{"Świnoujście-Ystad, 7.5 m", sy, length(7.5), nov, 150 + 8*13.00},
		{"Świnoujście-Ystad, 6 m", sy, length(6), nov, 125 + 6*13.00},
		{"Gdańsk-Nynäshamn, 16.5 m", gn, truck40, nov, 17 * (39 + 25.80)},
		{"Gdańsk-Karlshamn, road train", gk, length(18.75), nov, 19 * (30 + 16.36)},
		{"Gdańsk-Karlshamn before it opened", gk, truck40, jun, 0},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"PL": 150, "SE": 150}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck, FX: map[string]float64{"PLN": 4.25, "SEK": 11}}, tc.date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "POLSCA") {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.eur) > 0.011 {
			t.Errorf("%s: %.2f EUR, want %.2f: %v", tc.name, got, tc.eur, r.Notes)
		}
	}
}

// TestDanishFerries prices Denmark's domestic car ferries by the truck's
// length, from each line's freight page (dk_ferries.py), without VAT:
// SAMSØLINJEN's price per started metre over 20 m, ALSLINJEN's,
// FANØLINJEN's and LANGELANDSLINJEN's prices less 25% VAT, MOLSLINJEN's
// without its ETS fee, Samsø Rederi's less the VAT it states.
func TestDanishFerries(t *testing.T) {
	kalundborg := [][2]float64{{11.10, 55.68}, {11.088593, 55.672809}, {10.650119, 55.810439}, {10.64, 55.80}}
	fynshav := [][2]float64{{10.09, 55.11}, {10.075224, 55.106418}, {9.989193, 55.000434}, {9.98, 54.99}}
	nordby := [][2]float64{{8.45, 55.47}, {8.434987, 55.457539}, {8.413289, 55.453699}, {8.40, 55.45}}
	tars := [][2]float64{{10.82, 54.93}, {10.840707, 54.934061}, {11.021733, 54.875419}, {11.03, 54.87}}
	aarhus := [][2]float64{{10.24, 56.15}, {10.256237, 56.15617}, {11.265266, 55.968235}, {11.30, 55.97}}
	ebeltoft := [][2]float64{{10.67, 56.16}, {10.661377, 56.151544}, {11.267878, 55.970718}, {11.30, 55.97}}
	hou := [][2]float64{{10.26, 55.91}, {10.34828, 55.92655}, {10.548473, 55.868734}, {10.55, 55.86}}
	aeroeskoebing := [][2]float64{{10.62, 55.06}, {10.615322, 55.053579}, {10.417527, 54.894893}, {10.41, 54.89}}
	faaborg := [][2]float64{{10.24, 55.09}, {10.232745, 55.051317}, {10.255098, 54.954831}, {10.26, 54.94}}
	soeby := [][2]float64{{10.26, 54.94}, {10.250415, 54.953796}, {9.992822, 54.99676}, {9.985, 54.994}}
	marstal := [][2]float64{{10.52, 54.855}, {10.521825, 54.860785}, {10.660906, 54.912043}, {10.70, 54.937}}
	length := func(m float64) rates.Truck { tr := truck40; tr.LengthM = m; return tr }
	d26, d27 := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC), time.Date(2027, 3, 3, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name, op string
		path     [][2]float64
		truck    rates.Truck
		date     time.Time
		dkk      float64
	}{
		{"Kalundborg-Ballen, semi-trailer, 2026", "SAMSØLINJEN", kalundborg, truck40, d26, 293},
		{"Kalundborg-Ballen, semi-trailer, 2027", "SAMSØLINJEN", kalundborg, truck40, d27, 300},
		{"Kalundborg-Ballen, 10 m lorry, 2026", "SAMSØLINJEN", kalundborg, length(10), d26, 191},
		{"Kalundborg-Ballen, 25.25 m, 2026", "SAMSØLINJEN", kalundborg, length(25.25), d26, 293 + 6*17},
		{"Bøjden-Fynshav, semi-trailer, 2026", "ALSLINJEN", fynshav, truck40, d26, 958 / 1.25},
		{"Bøjden-Fynshav, 12 m lorry, 2027", "ALSLINJEN", fynshav, length(12), d27, 721 / 1.25},
		{"Esbjerg-Nordby, semi-trailer", "FANØLINJEN", nordby, truck40, d26, 1625 / 1.25},
		{"Esbjerg-Nordby, road train", "FANØLINJEN", nordby, length(18.75), d26, 1805 / 1.25},
		{"Spodsbjerg-Tårs, semi-trailer", "LANGELANDSLINJEN", tars, truck40, d26, 1330 / 1.25},
		{"Spodsbjerg-Tårs, 25.25 m", "LANGELANDSLINJEN", tars, length(25.25), d26, 1993 / 1.25},
		{"Aarhus-Odden, semi-trailer", "MOLSLINJEN", aarhus, truck40, d26, 1500},
		{"Aarhus-Odden, 12 m lorry", "MOLSLINJEN", aarhus, length(12), d26, 1100},
		{"Ebeltoft-Odden, road train", "MOLSLINJEN", ebeltoft, length(18.75), d26, 1500},
		{"Hou-Sælvig, semi-trailer", "Samsø Rederi", hou, truck40, d26, 694.16 - 138.83},
		{"Svendborg-Ærøskøbing, semi-trailer", "Ærøfærgerne", aeroeskoebing, truck40, d26, 905 - 167.40},
		{"Svendborg-Ærøskøbing, 10 m lorry", "Ærøfærgerne", aeroeskoebing, length(10), d26, 588 - 104},
		{"Faaborg-Søby, 25.25 m", "Ærøfærgerne", faaborg, length(25.25), d26, 905 - 167.40 + 7*(35-7)},
		{"Søby-Fynshav, road train", "Ærøfærgerne", soeby, length(18.75), d26, 905 - 167.40},
		{"Marstal-Rudkøbing, semi-trailer, November", "ÆrøXpressen", marstal, truck40, d26, (1025 + 20) / 1.25},
		{"Marstal-Rudkøbing, 8 m lorry, May", "ÆrøXpressen", marstal, length(8), time.Date(2026, 5, 4, 0, 0, 0, 0, time.UTC), 575 / 1.25},
	} {
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 50, CountryKm: map[string]float64{"DK": 50}, Path: tc.path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: tc.truck}, tc.date)
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, tc.op) {
				got += l.Amount
			}
		}
		if math.Abs(got-tc.dkk) > 0.011 {
			t.Errorf("%s: %.2f DKK, want %.2f: %v", tc.name, got, tc.dkk, r.Notes)
		}
	}
}

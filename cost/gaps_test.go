package cost

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

func priceLeg(t *testing.T, cc string, km float64, path [][2]float64, req Request, date string) Response {
	t.Helper()
	d, _ := time.Parse(time.DateOnly, date)
	req.CargoKg, req.Truck = 10000, rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{cc: km}, Path: dense(path), RouteParts: map[string]float64{"road": km}}}}
	out, err := Price(res, all(t), req, d)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// An entry and exit the table doesn't pair leave the toll out of the
// total: the result isn't complete.
func TestUnpricedPairIsMissing(t *testing.T) {
	// Serbia's A1 from the BEŠKA booths to MARADIK's.
	out := priceLeg(t, "RS", 9, [][2]float64{{20.075, 45.155}, {20.09016, 45.13511}, {20.10304, 45.0994}, {20.115, 45.08}},
		Request{TolledShare: map[string]float64{"RS": 1}, FX: map[string]float64{"RSD": 117}}, "2026-11-20")
	if out.Complete || len(out.Missing) != 1 || out.Missing[0].Reason != "unpriced" {
		t.Fatalf("complete %v, missing %+v; want the RS toll missing as unpriced", out.Complete, out.Missing)
	}
}

// Skurubron's gantries take the bridge charge only, not Stockholm's
// congestion tax.
func TestSkurubronIsABridge(t *testing.T) {
	out := priceLeg(t, "SE", 3, [][2]float64{{18.205, 59.3138}, {18.245, 59.3138}},
		Request{Time: "07:30", FX: map[string]float64{"SEK": 11}}, "2026-11-19")
	var got []string
	for _, l := range out.Lines {
		if strings.Contains(l.Section, "Skurubron") {
			got = append(got, l.Section)
		}
	}
	if len(got) != 1 {
		t.Fatalf("Skurubron lines %q; want the bridge's only", got)
	}
}

// ferryTrip is a short road to port a, the ferry to port b (by way of
// via) and a short road on (lon, lat).
func ferryTrip(t *testing.T, date string, a, b [2]float64, ca, cb string, via ...[2]float64) Response {
	t.Helper()
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	hav := func(p, q [2]float64) float64 { return haversine(p[1], p[0], q[1], q[0]) }
	before, after := [2]float64{a[0] - 0.03, a[1]}, [2]float64{b[0] + 0.03, b[1]}
	r1, f, r2 := hav(before, a), hav(a, b), hav(b, after)
	sea := append(append([][2]float64{a}, via...), b)
	path := append(dense([][2]float64{before, a}), dense(sea)[1:]...)
	path = append(path, dense([][2]float64{b, after})[1:]...)
	leg := sootcase.LegResult{DistanceKm: r1 + f + r2, TTWKg: 60, WTWKg: 70, CountryKm: map[string]float64{ca: r1, cb: r2}, Path: path,
		RouteParts: map[string]float64{"road": r1 + r2, "ferry": f},
		Parts:      []sootcase.Part{{Kind: "road", DistanceKm: r1}, {Kind: "ferry", DistanceKm: f, TTWKg: 50, WTWKg: 60}, {Kind: "road", DistanceKm: r2}}}
	req := Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, EUAEurPerT: 80,
		FX: map[string]float64{"GBP": 0.84, "DKK": 7.46}}
	day, _ := time.Parse(time.DateOnly, date)
	out, err := PriceWith(sootcase.Result{Legs: []sootcase.LegResult{leg}}, all(t), &fd, req, day)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// A crossing this tool knows, but has no fare table for, is missing from
// the total; one it has a table for isn't.
func TestFareWithNoTableIsMissing(t *testing.T) {
	dover := ferryTrip(t, "2026-11-20", [2]float64{1.332393, 51.123741}, [2]float64{1.854074, 50.967206}, "GB", "FR")
	want := Missing{Area: "GB", Charge: FerryFare, Name: dover.FerryCrossing, Reason: "no_table"}
	if dover.Complete || !slices.ContainsFunc(dover.Missing, func(m Missing) bool { m.Text = ""; return m == want }) {
		t.Errorf("Dover–Calais: crossing %q, complete %v, missing %+v; want %+v", dover.FerryCrossing, dover.Complete, dover.Missing, want)
	}
	// By the fare table's stations, 0.5 km out on the line.
	rodby := ferryTrip(t, "2026-11-20", [2]float64{11.3522, 54.6556}, [2]float64{11.2275, 54.5003}, "DK", "DE", [2]float64{11.34562, 54.650674}, [2]float64{11.231603, 54.506517})
	for _, m := range rodby.Missing {
		if m.Charge == FerryFare {
			t.Errorf("Rødby–Puttgarden: crossing %q, missing %+v; want its Scandlines fare", rodby.FerryCrossing, m)
		}
	}
	fare := false
	for _, l := range rodby.Lines {
		fare = fare || l.Charge == FerryFare
	}
	if !fare {
		t.Errorf("Rødby–Puttgarden: no fare line")
	}
}

// A trip with no charges has "lines": [], as the schema says, not null.
func TestNoLinesIsEmptyList(t *testing.T) {
	// Ukraine, with the diesel given: no charges and no sources.
	out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: map[string]float64{"UA": 100}, Date: "2026-11-20",
		CargoKg: 10000, DieselL: 30, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}})
	if err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(out)
	if !strings.Contains(string(b), `"lines":[]`) {
		t.Errorf("UA 100 km: %s; want \"lines\":[]", b)
	}
	// Nothing the schema calls a list or an object is null.
	if strings.Contains(string(b), ":null") {
		t.Errorf("UA 100 km: a null in %s", b)
	}
}

// A per-km toll's km driven after midnight on its table's last day are
// priced at the next table's rates: NL from 23:30 on 31 December 2026,
// 35 km at 2026's rate and 65 km at 2027's.
func TestKmAfterMidnightUseTheNextTable(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"NL": 100}, RouteParts: map[string]float64{"road": 100}}}}
	req := Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Time: "23:30", AvgSpeedKmh: 70,
		spans: map[string][][2]float64{"NL": {{0, 100}}}}
	out, err := Price(res, all(t), req, time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	km := map[float64]float64{}
	for _, l := range out.Lines {
		if l.Country == "NL" && l.Component == "infrastructure" {
			km[l.Rate] += l.Km
		}
	}
	if math.Abs(km[0.069]-35) > 0.5 || math.Abs(km[0.092]-65) > 0.5 {
		t.Errorf("NL infrastructure km by rate %v; want 35 at 0.069 and 65 at 0.092", km)
	}
}

// The Strait of Messina's fares include the EU ETS: no ETS line on top.
func TestETSInTheFare(t *testing.T) {
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	// Catania, Messina Tremestieri, the ferry to Villa San Giovanni, north.
	path := dense([][2]float64{{15.20, 37.60}, {15.45, 38.05}, {15.52959, 38.13635}, {15.61548, 38.21328}, {15.70, 38.40}})
	res := sootcase.Result{TTWKg: 100, WTWKg: 120, Legs: []sootcase.LegResult{{DistanceKm: 90, TTWKg: 100, WTWKg: 120, Path: path,
		RouteParts: map[string]float64{"ferry": 11}, CountryKm: map[string]float64{"IT": 79},
		Parts: []sootcase.Part{{Kind: "ferry", DistanceKm: 11, TTWKg: 25, WTWKg: 30}}}}}
	req := Request{CargoKg: 20000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1, LengthM: 16.5}, EUAEurPerT: 75}
	out, err := PriceWith(res, all(t), &fd, req, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	fare, ets := 0, 0
	for _, l := range out.Lines {
		switch l.Charge {
		case FerryFare:
			fare++
		case FerryETS:
			ets++
		}
	}
	if fare != 1 || ets != 0 {
		t.Errorf("Messina: %d fare lines, %d ETS lines; want the fare alone", fare, ets)
	}
}

// Before a crossing's first table here, the trip doesn't pay nothing:
// the fare is missing, as "before_table". A charge that only began with
// its first table (charged_from) isn't.
func TestBeforeTheFirstTable(t *testing.T) {
	rodby := ferryTrip(t, "2025-06-01", [2]float64{11.3522, 54.6556}, [2]float64{11.2275, 54.5003}, "DK", "DE", [2]float64{11.34562, 54.650674}, [2]float64{11.231603, 54.506517})
	found := false
	for _, m := range rodby.Missing {
		found = found || m.Charge == FerryFare && m.Reason == "before_table" && m.Starts == "2026-01-01"
	}
	if rodby.Complete || !found {
		t.Errorf("Rødby–Puttgarden on 2025-06-01: complete %v, missing %+v; want the fare before_table from 2026-01-01", rodby.Complete, rodby.Missing)
	}
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"LT": 100}, RouteParts: map[string]float64{"road": 100}}}}
	lt, err := Price(res, all(t), Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, DieselL: 30, FuelCountry: "LT"},
		time.Date(2024, 6, 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, m := range lt.Missing {
		if m.Charge == FuelCO2 {
			t.Errorf("LT fuel CO2 in 2024, before it began: missing %+v", m)
		}
	}
}

// Sootcase failing on the routes asked for is still Sootcase failing (a
// bad gateway), not a bad request.
func TestRoutesKeepTheErrorsKind(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// No country_km: Sootcase's answer can't be priced.
		res := sootcase.Result{TTWKg: 100, WTWKg: 120, Legs: []sootcase.LegResult{{DistanceKm: 300, TTWKg: 100, WTWKg: 120,
			Path:         [][2]float64{{12.5, 55.6}, {10, 53.5}},
			Alternatives: []sootcase.LegResult{{ID: "alt1", DistanceKm: 320, TTWKg: 110, WTWKg: 130, Path: [][2]float64{{12.5, 55.6}, {10, 53.5}}}}}}}
		json.NewEncoder(w).Encode(res)
	}))
	defer srv.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL}, Tariffs: all(t)}
	_, err := c.Calculate(context.Background(), Request{From: sootcase.Location{Code: "DKCPH"}, To: sootcase.Location{Code: "DEHAM"}, Date: "2026-11-03",
		CargoKg: 20000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Alternatives: 2})
	var fe *sootcase.Failed
	if !errors.As(err, &fe) {
		t.Errorf("alternatives 2, Sootcase's answer unusable: %v; want a sootcase.Failed", err)
	}
}

// A region's km are split by day by when that region is driven: Wallonia
// from 23:00 to midnight, Flanders after it, on 31 December 2026.
func TestRegionKmByTheirOwnDay(t *testing.T) {
	leg := sootcase.LegResult{DistanceKm: 140, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"BE": 140},
		RegionKm: map[string]float64{"BE-WAL": 70, "BE-VLG": 70}, RouteParts: map[string]float64{"road": 140},
		CountrySections: []sootcase.CountrySection{{Country: "BE", FromKm: 0, ToKm: 140, Regions: []sootcase.RegionSection{
			{Region: "BE-WAL", FromKm: 0, ToKm: 70}, {Region: "BE-VLG", FromKm: 70, ToKm: 140}}}}}
	req := Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Time: "23:00", AvgSpeedKmh: 70,
		TolledShare: map[string]float64{"BE-WAL": 1, "BE-VLG": 1}, spans: map[string][][2]float64{"BE": {{0, 140}}}}
	out, err := Price(sootcase.Result{Legs: []sootcase.LegResult{leg}}, all(t), req, time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	km := map[string]float64{} // region and rate: km
	for _, l := range out.Lines {
		if l.Charge == RoadToll && l.Country == "BE" {
			km[fmt.Sprintf("%s %g", l.Region, l.Rate)] += l.Km
		}
	}
	// 2026's rate for Wallonia, 2027's for Flanders.
	if want := map[string]float64{"BE-WAL 0.205": 70, "BE-VLG 0.297": 70}; !maps.Equal(km, want) {
		t.Errorf("BE km by region and rate: %v; want %v", km, want)
	}
}

// Stockholm's congestion tax goes by the time of day: without a time it
// is missing, not left out unseen.
func TestCongestionNeedsTime(t *testing.T) {
	path := [][2]float64{{18.095, 59.3139}, {18.112, 59.3139}}
	out := priceLeg(t, "SE", 1, path, Request{FX: map[string]float64{"SEK": 11}}, "2026-11-24")
	if out.Complete || !slices.ContainsFunc(out.Missing, func(m Missing) bool { return m.Reason == "needs_time" }) {
		t.Errorf("through Danvikstull without time: complete %v, missing %+v; want needs_time", out.Complete, out.Missing)
	}
	timed := priceLeg(t, "SE", 1, path, Request{Time: "08:00", FX: map[string]float64{"SEK": 11}}, "2026-11-24")
	if !timed.Complete {
		t.Errorf("at 08:00: missing %+v", timed.Missing)
	}
}

// A toll area before its first table here: before_table, not no_table.
func TestTollBeforeTheFirstTable(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"DE": 100}, RouteParts: map[string]float64{"road": 100}}}}
	out, err := Price(res, all(t), Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}}, time.Date(2023, 11, 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if !slices.ContainsFunc(out.Missing, func(m Missing) bool { return m.Charge == RoadToll && m.Reason == "before_table" && m.Starts != "" }) {
		t.Errorf("DE on 2023-11-01: missing %+v; want its tolls before_table", out.Missing)
	}
}

// The A 12's +25% stays a line of its own when its km run past midnight
// (two days merged into one line): the base line is its rate × km.
func TestSurchargeLineOverMidnight(t *testing.T) {
	pts := [][2]float64{{12.187, 47.607}, {12.1756, 47.5965}, {12.1408, 47.5675}, {12.0941, 47.5333}, {12.0572, 47.495}, {12.0235, 47.4838},
		{11.8842, 47.4411}, {11.8032, 47.4028}, {11.7016, 47.3577}, {11.6792, 47.3307}, {11.5838, 47.2998}, {11.5015, 47.2739},
		{11.4764, 47.271}, {11.4385, 47.2606}, {11.4202, 47.2547}}
	var km float64
	for i := 0; i+1 < len(pts); i++ {
		km += haversine(pts[i][1], pts[i][0], pts[i+1][1], pts[i+1][0])
	}
	res := sootcase.Result{TTWKg: 100, Legs: []sootcase.LegResult{{DistanceKm: km, CountryKm: map[string]float64{"AT": km}, Path: pts}}}
	req := Request{CargoKg: 1, Truck: truck40, Time: "23:30", AvgSpeedKmh: 70, spans: map[string][][2]float64{"AT": {{0, km}}}}
	out, err := Price(res, all(t), req, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range out.Lines {
		if l.Component == rates.Infrastructure && math.Abs(l.Amount-l.Rate*l.Km) > 0.02 {
			t.Errorf("%q: EUR %.2f for %.2f km at %g; want rate × km", l.Section, l.Amount, l.Km, l.Rate)
		}
	}
}

// A vignette over two days counts its km once: Sweden's 140 km from
// 23:00, on two days.
func TestVignetteKmOnce(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 140, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"SE": 140}, RouteParts: map[string]float64{"road": 140}}}}
	req := Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Time: "23:00", AvgSpeedKmh: 70,
		FX: map[string]float64{"SEK": 11}, spans: map[string][][2]float64{"SE": {{0, 140}}}}
	out, err := Price(res, all(t), req, time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range out.Lines {
		if l.Country == "SE" && l.Charge == RoadToll && l.Days > 0 && l.Km != 140 {
			t.Errorf("SE vignette over %d days on %.1f km; want 140 km", l.Days, l.Km)
		}
	}
}

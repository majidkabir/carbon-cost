package cost

import (
	"context"
	"encoding/json"
	"errors"
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
	if dover.Complete || !slices.Contains(dover.Missing, want) {
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

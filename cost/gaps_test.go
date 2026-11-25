package cost

import (
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
func ferryTrip(t *testing.T, a, b [2]float64, ca, cb string, via ...[2]float64) Response {
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
	out, err := PriceWith(sootcase.Result{Legs: []sootcase.LegResult{leg}}, all(t), &fd, req, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// A crossing this tool knows, but has no fare table for, is missing from
// the total; one it has a table for isn't.
func TestFareWithNoTableIsMissing(t *testing.T) {
	dover := ferryTrip(t, [2]float64{1.332393, 51.123741}, [2]float64{1.854074, 50.967206}, "GB", "FR")
	want := Missing{Area: "GB", Charge: FerryFare, Name: dover.FerryCrossing, Reason: "no_table"}
	if dover.Complete || !slices.Contains(dover.Missing, want) {
		t.Errorf("Dover–Calais: crossing %q, complete %v, missing %+v; want %+v", dover.FerryCrossing, dover.Complete, dover.Missing, want)
	}
	// By the fare table's stations, 0.5 km out on the line.
	rodby := ferryTrip(t, [2]float64{11.3522, 54.6556}, [2]float64{11.2275, 54.5003}, "DK", "DE", [2]float64{11.34562, 54.650674}, [2]float64{11.231603, 54.506517})
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

package cost

import (
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// dense puts 50 points on each segment, as a routed path has.
func dense(pts [][2]float64) [][2]float64 {
	var out [][2]float64
	for i := 0; i+1 < len(pts); i++ {
		for k := 0; k < 50; k++ {
			f := float64(k) / 50
			out = append(out, [2]float64{pts[i][0] + f*(pts[i+1][0]-pts[i][0]), pts[i][1] + f*(pts[i+1][1]-pts[i][1])})
		}
	}
	return append(out, pts[len(pts)-1])
}

func reversed(p [][2]float64) [][2]float64 {
	out := make([][2]float64, len(p))
	for i := range p {
		out[i] = p[len(p)-1-i]
	}
	return out
}

// A bridge passed on the way out and again on the way back, on a trip
// of two legs, is charged both times.
func TestRoundTripPassesTwice(t *testing.T) {
	set := all(t)
	// Zealand over the Storebælt bridge to Funen.
	out := dense([][2]float64{{12.0, 55.45}, {11.2, 55.37}, {11.10879, 55.3498}, {10.87, 55.31}, {10.39, 55.40}})
	leg := func(p [][2]float64) sootcase.LegResult {
		return sootcase.LegResult{DistanceKm: 140, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"DK": 140}, Path: p, RouteParts: map[string]float64{}}
	}
	truck := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	date := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)
	count := func(r Response) int {
		n := 0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Storebælt") {
				n++
			}
		}
		return n
	}
	one, err := Price(sootcase.Result{Legs: []sootcase.LegResult{leg(out)}}, set,
		Request{Truck: truck, CargoKg: 10000, From: sootcase.Location{Code: "A"}, To: sootcase.Location{Code: "B"}}, date)
	if err != nil {
		t.Fatal(err)
	}
	two, err := Price(sootcase.Result{Legs: []sootcase.LegResult{leg(out), leg(reversed(out))}}, set,
		Request{Truck: truck, CargoKg: 10000, Stops: []sootcase.Location{{Code: "A"}, {Code: "B"}, {Code: "A"}}}, date)
	if err != nil {
		t.Fatal(err)
	}
	if count(one) != 1 || count(two) != 2 {
		t.Fatalf("Storebælt lines: one way %d, round trip %d; want 1 and 2", count(one), count(two))
	}
}

// storebaelt is a 140 km leg over the Storebælt bridge.
func storebaelt() sootcase.LegResult {
	p := dense([][2]float64{{12.0, 55.45}, {11.2, 55.37}, {11.10879, 55.3498}, {10.87, 55.31}, {10.39, 55.40}})
	return sootcase.LegResult{DistanceKm: 140, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"DK": 140}, Path: p, RouteParts: map[string]float64{}}
}

// A bridge reached after midnight on its table's last day pays the next
// version's toll; with no next version here, it is reported missing.
func TestPassedAfterTheTablesLastDay(t *testing.T) {
	set := all(t)
	truck := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	price := func(day string) Response {
		d, _ := time.Parse(time.DateOnly, day)
		r, err := Price(sootcase.Result{Legs: []sootcase.LegResult{storebaelt()}}, set,
			Request{Truck: truck, CargoKg: 10000, Date: day, Time: "23:30", From: sootcase.Location{Code: "A"}, To: sootcase.Location{Code: "B"}}, d)
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	r := price("2025-12-31")
	var bridge *Line
	for i, l := range r.Lines {
		if strings.Contains(l.Section, "Storebælt") {
			bridge = &r.Lines[i]
		}
	}
	if bridge == nil || !r.Complete {
		t.Fatalf("2025-12-31 23:30: Storebælt line %v, complete %v; want the 2026 toll", bridge, r.Complete)
	}
	used := false
	for _, tb := range r.Provenance.Tables {
		used = used || tb.File == "dk/dk-bridges-2026-01-01.orct.json"
	}
	if !used {
		t.Errorf("tables used %+v; want dk-bridges-2026", r.Provenance.Tables)
	}
	for _, d := range set.All {
		if _, ok := set.Version(d, "2027-01-01"); ok && d.Scheme == "dk-bridges" {
			t.Skip("dk-bridges has a 2027 version now")
		}
	}
	r = price("2026-12-31")
	if r.Complete || len(r.Missing) != 1 || r.Missing[0].Reason != "ended" {
		t.Fatalf("2026-12-31 23:30: complete %v, missing %+v; want the bridge missing, ended", r.Complete, r.Missing)
	}
}

// A ferry priced by the truck's load capacity, when the request doesn't
// give it, is reported missing, not left out of a complete total.
func TestFareNeedsCapacity(t *testing.T) {
	set := all(t)
	p := dense([][2]float64{{14.56, 45.10}, {14.493868, 45.019177}, {14.449625, 44.984412}, {14.40, 44.90}})
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 30, TTWKg: 10, WTWKg: 12, CountryKm: map[string]float64{"HR": 30}, Path: p, RouteParts: map[string]float64{}}}}
	price := func(capacity int) Response {
		truck := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1, CapacityKg: capacity}
		r, err := Price(res, set, Request{Truck: truck, CargoKg: 10000, From: sootcase.Location{Code: "A"}, To: sootcase.Location{Code: "B"}},
			time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	if r := price(0); r.Complete || len(r.Missing) == 0 || r.Missing[0].Reason != "needs_truck_field" || r.Missing[0].Charge != FerryFare {
		t.Errorf("no capacity_kg: complete %v, missing %+v; want the fare missing", r.Complete, r.Missing)
	}
	r := price(25000)
	if !r.Complete || r.TotalEUR == 0 {
		t.Errorf("capacity_kg 25000: complete %v, total %v", r.Complete, r.TotalEUR)
	}
	for _, n := range r.Notes {
		if strings.Contains(n, "for group .") {
			t.Errorf("note %q", n)
		}
	}
}

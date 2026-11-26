package cost

import (
	"context"
	"math"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/sootcase/pkg/borders"
)

// The truck's own path is priced instead of Sootcase's route: split at
// the stops, its km by country from the borders; the emissions stay
// Sootcase's.
func TestOwnPath(t *testing.T) {
	var calls []sootcase.Shipment
	var mu sync.Mutex
	fake := fakeLegs(t, &calls, &mu)
	defer fake.Close()
	ix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	c := Calculator{Sootcase: sootcase.Client{BaseURL: fake.URL}, Tariffs: all(t), Borders: ix}
	stop := func(i int) sootcase.Location { return sootcase.Location{Code: "S" + string(rune('0'+i))} }
	// Sootcase: S0 (9, 52) -> S1 (10, 52) -> S2 (11, 52), 100 km a leg.
	// Driven: a detour north on each leg.
	path := [][2]float64{{9, 52}, {9.5, 52.3}, {10, 52}, {10.5, 52.3}, {11, 52}}
	req := Request{Date: "2026-11-03", Truck: truck40, Stops: []sootcase.Location{stop(0), stop(1), stop(2)},
		Shipments: []Shipment{{ID: "A", WeightKg: 10000, To: 2}, {ID: "B", WeightKg: 10000, From: 1}}, Path: path}
	r, err := c.Calculate(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	leg := pathKm(path[:3])
	if len(r.Trip.Legs) != 2 || math.Abs(r.Trip.Legs[0].Km-leg) > 0.01 || math.Abs(r.Trip.Legs[1].Km-pathKm(path[2:])) > 0.01 {
		t.Fatalf("legs %+v, want %.3f km each", r.Trip.Legs, leg)
	}
	if math.Abs(r.DistanceKm-pathKm(path)) > 0.01 || math.Abs(r.CountryKm["DE"]-pathKm(path)) > 0.01 {
		t.Errorf("distance %v, country km %v, want %.3f in DE", r.DistanceKm, r.CountryKm, pathKm(path))
	}
	// The tonne-km stay on the shipments' own routes: A 200 km, B 100.
	if r.Shipments[0].DistanceKm != 200 || r.Shipments[1].DistanceKm != 100 {
		t.Errorf("shipments %+v", r.Shipments)
	}
	// Sootcase's emissions: 0.08 kg/tkm.
	if math.Abs(r.TTWKg-(0.08*10*200+0.08*10*100)) > 0.01 {
		t.Errorf("TTW %v", r.TTWKg)
	}
	if !strings.Contains(strings.Join(r.Notes, "\n"), "Route: the path given (5 points") {
		t.Errorf("notes %q", r.Notes)
	}
	if !strings.Contains(r.Trip.FuelBasis, "default") || math.Abs(r.Trip.RoadKm-pathKm(path)) > 0.01 {
		t.Errorf("trip %+v", r.Trip)
	}
}

// A path across a border splits by country.
func TestOwnPathCountries(t *testing.T) {
	ix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	// Almelo (NL) to Osnabrück (DE).
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 70, Path: [][2]float64{{6.6, 52.3}, {8.05, 52.28}}}}}
	path := [][2]float64{{6.6, 52.3}, {6.9, 52.25}, {7.2, 52.27}, {7.6, 52.3}, {8.05, 52.28}}
	notes := ownPath(ix, nil, &res, path)
	l := res.Legs[0]
	if l.CountryKm["NL"] < 5 || l.CountryKm["DE"] < 40 || math.Abs(l.CountryKm["NL"]+l.CountryKm["DE"]-pathKm(path)) > 0.01 {
		t.Errorf("country km %v", l.CountryKm)
	}
	if len(notes) != 1 {
		t.Errorf("notes %q", notes)
	}
	// Starting far from the first stop is noted.
	res = sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 70, Path: [][2]float64{{6.6, 52.3}, {8.05, 52.28}}}}}
	if notes := ownPath(ix, nil, &res, path[2:]); !strings.Contains(notes[0], "from stop 0") {
		t.Errorf("notes %q", notes)
	}
}

// Km by country with no route: per-km and per-day charges are priced,
// tolls at stations are missing, and the emissions are the diesel's.
func TestCountryKm(t *testing.T) {
	never := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("country_km called Sootcase")
	}))
	defer never.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: never.URL}, Tariffs: all(t)}
	req := Request{Date: "2026-11-03", Truck: truck40, CargoKg: 20000, LPer100Km: 30, CountryKm: map[string]float64{"DE": 300, "FR": 200}}
	r, err := c.Calculate(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	var deKm float64
	for _, l := range r.Lines {
		if l.Country == "DE" && l.Charge == RoadToll && l.Component == "infrastructure" {
			deKm += l.Km
		}
	}
	if deKm != 300 {
		t.Errorf("DE toll km %v, lines %+v", deKm, r.Lines)
	}
	if r.Complete || len(r.Missing) != 1 || r.Missing[0].Area != "FR" || r.Missing[0].Reason != "no_route" {
		t.Errorf("missing %+v", r.Missing)
	}
	if r.Trip.FuelL != 150 || r.TTWKg != round3(150*DieselKgCO2PerL) || r.WTWKg != round3(150*DieselKgCO2ePerLWTW) || r.DistanceKm != 500 {
		t.Errorf("trip %+v, TTW %v, WTW %v, km %v", r.Trip, r.TTWKg, r.WTWKg, r.DistanceKm)
	}
	if r.Provenance.Sootcase != "" {
		t.Errorf("sootcase %q", r.Provenance.Sootcase)
	}
	res := kmTrip(&Request{CargoKg: 1, CountryKm: map[string]float64{"BE-VLG": 60, "BE-WAL": 40, "NL": 10}})
	if l := res.Legs[0]; l.CountryKm["BE"] != 100 || l.RegionKm["BE-VLG"] != 60 || l.DistanceKm != 110 {
		t.Errorf("km trip %+v", l)
	}
	for _, bad := range []Request{
		{Truck: truck40, CargoKg: 1, CountryKm: map[string]float64{"DE": 1}, Path: [][2]float64{{9, 52}, {10, 52}}},
		{Truck: truck40, CargoKg: 1, CountryKm: map[string]float64{"DE": 1}, From: sootcase.Location{Code: "DEHAM"}},
		{Truck: truck40, CargoKg: 1, CountryKm: map[string]float64{"Germany": 1}},
		{Truck: truck40, CargoKg: 1, CountryKm: map[string]float64{"BE": 1, "BE-VLG": 1}},
		{Truck: truck40, CargoKg: 1, CountryKm: map[string]float64{"DE": -1}},
		{Truck: truck40, CargoKg: 1, Path: [][2]float64{{9, 52}, {200, 52}}},
		{Truck: truck40, CargoKg: 1, Path: [][2]float64{{9, 52}}},
	} {
		if err := check(bad); err == nil {
			t.Errorf("no error for %+v", bad)
		}
	}
}

// A ferry on the path is a ferry part with its own km: Sootcase's
// crossing's emissions by km, or none when Sootcase's route took none.
func TestOwnPathFerry(t *testing.T) {
	ix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	// Copenhagen - Rødby, ferry to Puttgarden, Lübeck - Hamburg.
	path := [][2]float64{{12.57, 55.68}, {11.9, 55.2}, {11.4, 54.7}, {11.3522, 54.6556}, {11.29, 54.58}, {11.2275, 54.5003},
		{10.69, 53.87}, {9.99, 53.55}}
	for _, soot := range []sootcase.LegResult{
		{DistanceKm: 300, TTWKg: 250, RouteParts: map[string]float64{"ferry": 20}, Path: [][2]float64{path[0], path[len(path)-1]},
			Parts: []sootcase.Part{{Kind: "ferry", DistanceKm: 20, TTWKg: 30, WTWKg: 36}}},
		{DistanceKm: 330, TTWKg: 250, Path: [][2]float64{path[0], path[len(path)-1]}}, // over the Great Belt and Jutland
	} {
		res := sootcase.Result{Legs: []sootcase.LegResult{soot}}
		notes := ownPath(ix, &fd, &res, path)
		l := res.Legs[0]
		fkm := l.RouteParts["ferry"]
		// The parts in the path's order: road, the ferry, road.
		if fkm < 18 || fkm > 20 || len(l.Parts) != 3 || l.Parts[1].Kind != "ferry" || l.Parts[1].DistanceKm != fkm || l.CountryKm["DK"] < 100 || l.CountryKm["DE"] < 100 ||
			math.Abs(l.CountryKm["DK"]+l.CountryKm["DE"]+fkm-l.DistanceKm) > 0.01 || math.Abs(l.Parts[0].DistanceKm+l.Parts[1].DistanceKm+l.Parts[2].DistanceKm-l.DistanceKm) > 0.01 {
			t.Fatalf("leg %+v", l)
		}
		if took := len(soot.Parts) > 0; took != (l.Parts[1].TTWKg > 0) || took == strings.Contains(strings.Join(notes, " "), "doesn't take") {
			t.Errorf("parts %+v, notes %q", l.Parts, notes)
		}
		if l.TTWKg != 250 {
			t.Errorf("TTW %v", l.TTWKg)
		}
	}
}

// Belgium's tolls are set by region: its km as one country can't be priced.
func TestCountryKmRegionalRefused(t *testing.T) {
	set := all(t)
	if err := checkRegional(set, map[string]float64{"BE": 100}); err == nil || !strings.Contains(err.Error(), "BE-VLG") {
		t.Errorf("BE: %v; want refused, naming its regions", err)
	}
	if err := checkRegional(set, map[string]float64{"BE-VLG": 60, "NL": 40}); err != nil {
		t.Errorf("BE-VLG, NL: %v", err)
	}
}

// One cargo from the first stop to the last: its tonne-km stay on
// Sootcase's route too, not the way driven.
func TestOwnPathOneCargo(t *testing.T) {
	var calls []sootcase.Shipment
	var mu sync.Mutex
	fake := fakeLegs(t, &calls, &mu)
	defer fake.Close()
	ix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	c := Calculator{Sootcase: sootcase.Client{BaseURL: fake.URL}, Tariffs: all(t), Borders: ix}
	path := [][2]float64{{9, 52}, {9.5, 52.3}, {10, 52}}
	r, err := c.Calculate(context.Background(), Request{Date: "2026-11-03", Truck: truck40, CargoKg: 10000,
		From: sootcase.Location{Code: "S0"}, To: sootcase.Location{Code: "S1"}, Path: path})
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Shipments) != 1 || r.Shipments[0].DistanceKm != 100 {
		t.Errorf("driven %.1f km: shipments %+v; want Sootcase's 100 km", pathKm(path), r.Shipments)
	}
}

// A path's regions are its own, in order: Flanders driven before
// midnight on 31 December 2025 is all at its 2025 table, Wallonia's km
// after it at 2026's (Ghent to Tournai from 23:28).
func TestOwnPathRegionsByDay(t *testing.T) {
	var calls []sootcase.Shipment
	var mu sync.Mutex
	fake := fakeLegs(t, &calls, &mu)
	defer fake.Close()
	ix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	c := Calculator{Sootcase: sootcase.Client{BaseURL: fake.URL}, Tariffs: all(t), Borders: ix}
	path := dense([][2]float64{{3.72, 51.05}, {3.62, 50.85}, {3.52, 50.72}, {3.39, 50.61}})
	r, err := c.Calculate(context.Background(), Request{Date: "2025-12-31", Time: "23:28", AvgSpeedKmh: 70, Truck: truck40, CargoKg: 10000,
		From: sootcase.Location{Code: "S0"}, To: sootcase.Location{Code: "S1"}, Path: path})
	if err != nil {
		t.Fatal(err)
	}
	if r.RegionKm["BE-VLG"] < 10 || r.RegionKm["BE-WAL"] < 10 {
		t.Fatalf("region km %v", r.RegionKm)
	}
	var vlg2026 bool
	for _, tb := range r.Provenance.Tables {
		vlg2026 = vlg2026 || strings.HasSuffix(tb.File, "be-vlg-2026-01-01.orct.json")
	}
	km := map[string]float64{}
	for _, l := range r.Lines {
		if l.Region != "" {
			km[l.Region] = math.Max(km[l.Region], l.Km)
		}
	}
	// Flanders' km, all before midnight: one table's line of all of them.
	if vlg2026 || math.Abs(km["BE-VLG"]-r.RegionKm["BE-VLG"]) > 0.5 {
		t.Errorf("Flanders: lines' km %v of %v, its 2026 table used: %v", km, r.RegionKm, vlg2026)
	}
}

// A ferry Sootcase's route takes that the ferry data doesn't know is a
// ferry on the path too, where the path goes its way (Kalundborg–Ballen):
// not road km.
func TestOwnPathUnknownFerry(t *testing.T) {
	ix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	route := [][2]float64{{11.20, 55.70}, {11.088, 55.679}, {10.646, 55.818}, {10.60, 55.83}}
	km := func(p [][2]float64) float64 { return pathKm(p) }
	road1, sea, road2 := km(route[:2]), km(route[1:3]), km(route[2:])
	soot := sootcase.LegResult{DistanceKm: road1 + sea + road2, TTWKg: 80, Path: route, RouteParts: map[string]float64{"ferry": sea, "road": road1 + road2},
		Parts: []sootcase.Part{{Kind: "road", DistanceKm: road1, TTWKg: 5}, {Kind: "ferry", DistanceKm: sea, TTWKg: 70}, {Kind: "road", DistanceKm: road2, TTWKg: 5}}}
	res := sootcase.Result{Legs: []sootcase.LegResult{soot}}
	path := dense(route)
	ownPath(ix, &fd, &res, path)
	l := res.Legs[0]
	if math.Abs(l.RouteParts["ferry"]-sea) > 1 || l.CountryKm["DK"] > road1+road2+1 {
		t.Errorf("ferry %.1f km (want %.1f), DK %.1f km (want %.1f)", l.RouteParts["ferry"], sea, l.CountryKm["DK"], road1+road2)
	}
	// The runs priced on the path have it too.
	var ferry float64
	for _, r := range legRuns(ix, &fd, l) {
		if r.Kind == "ferry" {
			ferry += r.Km
		}
	}
	if math.Abs(ferry-sea) > 1 {
		t.Errorf("runs: ferry %.1f km (want %.1f)", ferry, sea)
	}
}

// Sootcase's route over a ferry the ferry data doesn't know: the runs
// priced (and the map) have the ferry, not road in Denmark.
func TestRouteUnknownFerry(t *testing.T) {
	ix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	route := dense([][2]float64{{11.20, 55.70}, {11.088, 55.679}, {10.646, 55.818}, {10.60, 55.83}})
	road1, sea, road2 := pathKm(dense([][2]float64{{11.20, 55.70}, {11.088, 55.679}})), pathKm(dense([][2]float64{{11.088, 55.679}, {10.646, 55.818}})), pathKm(dense([][2]float64{{10.646, 55.818}, {10.60, 55.83}}))
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: road1 + sea + road2, TTWKg: 80, WTWKg: 96, Path: route,
		CountryKm: map[string]float64{"DK": road1 + road2}, RouteParts: map[string]float64{"ferry": sea, "road": road1 + road2},
		Parts: []sootcase.Part{{Kind: "road", DistanceKm: road1, TTWKg: 5}, {Kind: "ferry", DistanceKm: sea, TTWKg: 70}, {Kind: "road", DistanceKm: road2, TTWKg: 5}}}}}
	c := Calculator{Tariffs: all(t), Borders: ix, Ferries: &fd}
	req := Request{Date: "2026-11-03", Truck: truck40, CargoKg: 20000}
	out, err := c.priceRoute(res, &req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	var ferry, dk float64
	for _, r := range out.Route {
		switch r.Kind {
		case "ferry":
			ferry += r.Km
		case "road":
			dk += r.Km
		}
	}
	if math.Abs(ferry-sea) > 2 || dk > road1+road2+2 {
		t.Errorf("route: ferry %.1f km (want %.1f), road %.1f km (want %.1f)", ferry, sea, dk, road1+road2)
	}
}

// A path that doesn't take Sootcase's ferry, reaching its ports in the
// other order, is priced without it (and doesn't panic).
func TestOwnPathOtherWay(t *testing.T) {
	route := [][2]float64{{0, 0}, {0, 0.1}, {0, 0.5}, {0, 0.6}}
	r1, sea, r2 := pathKm(route[:2]), pathKm(route[1:3]), pathKm(route[2:])
	parts := []sootcase.Part{{Kind: "road", DistanceKm: r1}, {Kind: "ferry", DistanceKm: sea}, {Kind: "road", DistanceKm: r2}}
	path := [][2]float64{{0, 0.5}, {0.3, 0.4}, {0.3, 0.2}, {0, 0.1}}
	if s := sootFerrySpans(route, r1+sea+r2, parts, path); len(s) != 0 {
		t.Errorf("spans %v", s)
	}
}

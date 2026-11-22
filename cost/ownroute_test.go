package cost

import (
	"context"
	"math"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

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
		if fkm < 18 || fkm > 20 || len(l.Parts) != 1 || l.Parts[0].DistanceKm != fkm || l.CountryKm["DK"] < 100 || l.CountryKm["DE"] < 100 ||
			math.Abs(l.CountryKm["DK"]+l.CountryKm["DE"]+fkm-l.DistanceKm) > 0.01 {
			t.Fatalf("leg %+v", l)
		}
		if took := len(soot.Parts) > 0; took != (l.Parts[0].TTWKg > 0) || took == strings.Contains(strings.Join(notes, " "), "doesn't take") {
			t.Errorf("parts %+v, notes %q", l.Parts, notes)
		}
		if l.TTWKg != 250 {
			t.Errorf("TTW %v", l.TTWKg)
		}
	}
}

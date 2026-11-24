package cost

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// fakeAlternatives answers each leg with a 100 km primary route in
// Germany taking 4 hours and, when asked for alternatives, a 150 km one
// taking 1.5: German tolls make the primary the cheaper, the driver's
// time the other.
func fakeAlternatives(t *testing.T, queries *[]string, mu *sync.Mutex) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var s sootcase.Shipment
		json.NewDecoder(r.Body).Decode(&s)
		mu.Lock()
		*queries = append(*queries, r.URL.RawQuery)
		mu.Unlock()
		leg := func(km, h float64, roads ...string) sootcase.LegResult {
			ttw := 0.08 * s.WeightKg / 1000 * km
			return sootcase.LegResult{DistanceKm: km, DurationH: h, TTWKg: ttw, WTWKg: ttw * 1.25, CountryKm: map[string]float64{"DE": km},
				Path: [][2]float64{{9, 52}, {10, 52}}, Summary: &sootcase.RouteSummary{Roads: roads, Ferries: []sootcase.FerryUse{}}}
		}
		var res sootcase.Result
		for range s.Legs {
			l := leg(100, 4, "A7")
			if r.URL.Query().Get("alternatives") != "" {
				a := leg(150, 1.5, "A1", "A2")
				a.ID = "alt1"
				l.Alternatives = []sootcase.LegResult{a}
			}
			res.Legs = append(res.Legs, l)
			res.TTWKg += l.TTWKg
			res.WTWKg += l.WTWKg
		}
		json.NewEncoder(w).Encode(res)
	}))
}

func TestRoutes(t *testing.T) {
	var queries []string
	var mu sync.Mutex
	fake := fakeAlternatives(t, &queries, &mu)
	defer fake.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: fake.URL}, Tariffs: all(t)}
	base := Request{Date: "2026-11-03", Truck: truck40, CargoKg: 20000, From: sootcase.Location{Code: "DEHAM"}, To: sootcase.Location{Code: "DEMUC"}}

	r, err := c.Calculate(context.Background(), base)
	if err != nil || len(r.Routes) != 0 || strings.Contains(queries[0], "alternatives") {
		t.Fatalf("no alternatives asked: %v %d %q", err, len(r.Routes), queries[0])
	}
	req := base
	req.Alternatives = 3
	r, err = c.Calculate(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Routes) != 2 || r.Routes[0].ID != "primary" || !r.Routes[0].Chosen || r.Routes[1].ID != "alt1" || r.Routes[1].DistanceKm != 150 ||
		r.DistanceKm != 100 || r.Routes[1].Roads[0] != "A1" || r.Routes[1].DiffEUR <= 0 || !strings.Contains(queries[len(queries)-1], "alternatives=3") {
		t.Fatalf("routes %+v, distance %v, query %q", r.Routes, r.DistanceKm, queries[len(queries)-1])
	}
	if want := round2(r.Routes[1].WithFuelEUR - r.Routes[0].WithFuelEUR); r.Routes[1].DiffEUR != want {
		t.Errorf("diff %v, want %v", r.Routes[1].DiffEUR, want)
	}
	// An alternative by its id; cheapest asks for 3 routes by itself.
	req.Route = "alt1"
	if r, err = c.Calculate(context.Background(), req); err != nil || r.DistanceKm != 150 || !r.Routes[1].Chosen || r.Routes[0].Chosen {
		t.Fatalf("alt1: %v %v %+v", err, r.DistanceKm, r.Routes)
	}
	req = base
	req.Route = "cheapest"
	if r, err = c.Calculate(context.Background(), req); err != nil || r.DistanceKm != 100 || !r.Routes[0].Chosen || !strings.Contains(queries[len(queries)-1], "alternatives=3") {
		t.Fatalf("cheapest: %v %v %+v", err, r.DistanceKm, r.Routes)
	}
	// The driver's time makes the faster route the cheaper.
	req.DriverEURPerH, req.VehicleEURPerKm = 35, 0.4
	if r, err = c.Calculate(context.Background(), req); err != nil || r.DistanceKm != 150 || !r.Routes[1].Chosen || r.Routes[0].Hours != 4 || r.Trip.Hours != 1.5 ||
		r.DriverEUR != 52.5 || r.VehicleEUR != 60 || r.TripCostEUR != round2(r.WithFuelEUR+112.5) || r.Routes[1].DiffEUR >= 0 {
		t.Fatalf("cheapest with running costs: %v %v %+v %+v", err, r.DistanceKm, r.Trip, r.Routes)
	}
	if r.Shipments[0].TripCostEUR != r.TripCostEUR {
		t.Errorf("shipment trip cost %v, want %v", r.Shipments[0].TripCostEUR, r.TripCostEUR)
	}
	req.DriverEURPerH, req.VehicleEURPerKm = 0, 0
	req.Route = "alt9"
	if _, err = c.Calculate(context.Background(), req); err == nil || !strings.Contains(err.Error(), "primary, alt1") {
		t.Errorf("unknown route: %v", err)
	}
	// Avoiding ferries goes to Sootcase.
	req = base
	req.Ferry = "avoid"
	if _, err = c.Calculate(context.Background(), req); err != nil || !strings.Contains(queries[len(queries)-1], "avoid=ferries") {
		t.Errorf("avoid: %v %q", err, queries[len(queries)-1])
	}
	// A trip with stops: each leg's other route, the rest as the primary.
	req = Request{Date: "2026-11-03", Truck: truck40, CargoKg: 20000, Alternatives: 2,
		Stops: []sootcase.Location{{Code: "DEHAM"}, {Code: "DEFRA"}, {Code: "DEMUC"}}}
	if r, err = c.Calculate(context.Background(), req); err != nil || len(r.Routes) != 3 || r.Routes[1].ID != "leg1:alt1" || r.Routes[2].ID != "leg2:alt1" || r.Routes[1].DistanceKm != 250 {
		t.Fatalf("stops: %v %+v", err, r.Routes)
	}
	for _, bad := range []Request{{Alternatives: 6}, {Route: "fastest"}, {Ferry: "only"}, {Alternatives: 3, CountryKm: map[string]float64{"DE": 100}}, {DriverEURPerH: 900}, {VehicleEURPerKm: -1}} {
		bad.CargoKg, bad.From, bad.To = 1, base.From, base.To
		if err := check(bad); err == nil {
			t.Errorf("%+v: want an error", bad)
		}
	}
}

func TestTripHours(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 700}}}
	if h, b := tripHours(res, 700, Request{}); h != 10 || !strings.Contains(b, "70 km/h") {
		t.Errorf("by speed: %v %q", h, b)
	}
	res.Legs[0].DurationH = 8
	if h, b := tripHours(res, 700, Request{}); h != 8 || !strings.Contains(b, "Sootcase") {
		t.Errorf("Sootcase: %v %q", h, b)
	}
	// 10 hours' driving: 9 with a 45-minute break, an 11-hour rest, then 1.
	res.Legs[0].DurationH = 10
	if tr := tripOf(res, Request{DriverRest: true, Truck: truck40}); tr.Hours != 10 || tr.ElapsedH != 21.75 {
		t.Errorf("with rest: %+v", tr)
	}
}

func TestTruckRestrictions(t *testing.T) {
	var got []sootcase.Shipment
	var mu sync.Mutex
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var s sootcase.Shipment
		json.NewDecoder(r.Body).Decode(&s)
		mu.Lock()
		got = append(got, s)
		mu.Unlock()
		var res sootcase.Result
		for _, l := range s.Legs {
			lr := sootcase.LegResult{DistanceKm: 100, TTWKg: 160, WTWKg: 200, CountryKm: map[string]float64{"DE": 100}, Path: [][2]float64{{9, 52}, {10, 52}}}
			if l.Vehicle != nil {
				lr.Restrictions = map[string]any{"height_m": l.Vehicle.HeightM, "tunnel_code": l.Vehicle.TunnelCode,
					"routed_for": map[string]any{"height_m": 4, "width_m": 2.6, "tunnel_code": l.Vehicle.TunnelCode, "hazmat_no": true}, "excluded": []string{"truck", "hzd"}}
			}
			res.Legs = append(res.Legs, lr)
			res.TTWKg, res.WTWKg = res.TTWKg+160, res.WTWKg+200
		}
		json.NewEncoder(w).Encode(res)
	}))
	defer fake.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: fake.URL}, Tariffs: all(t)}
	req := Request{Date: "2026-11-03", Truck: truck40, CargoKg: 20000, From: sootcase.Location{Code: "DEHAM"}, To: sootcase.Location{Code: "DEMUC"}}
	// Without the truck's size or load, no vehicle goes to Sootcase.
	if r, err := c.Calculate(context.Background(), req); err != nil || got[0].Legs[0].Vehicle != nil || r.Trip.RoutedFor != nil {
		t.Fatalf("no vehicle: %v %+v", err, got[0].Legs[0].Vehicle)
	}
	req.Truck.HeightM, req.Truck.ADRTunnelCode, req.Truck.TareKg = 4.0, "D", 15000
	r, err := c.Calculate(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	v := got[len(got)-1].Legs[0].Vehicle
	if v == nil || v.HeightM != 4 || v.TunnelCode != "D" || !v.Hazmat || v.GrossWeightKg != 35000 || v.Axles != 5 || v.LengthM != 0 {
		t.Errorf("vehicle sent: %+v", v)
	}
	if r.Trip.RoutedFor["tunnel_code"] != "D" || r.Trip.RoutedFor["width_m"] != 2.6 || !slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "kept to roads the truck may drive") }) {
		t.Errorf("routed for: %+v %q", r.Trip.RoutedFor, r.Notes)
	}
	for _, bad := range []rates.Truck{{HeightM: 9}, {WidthM: 1}, {AxleLoadKg: 50000}, {ADRTunnelCode: "A"}, {ADRTunnelCode: "DE"}} {
		bad.MaxMassKg, bad.Axles, bad.Euro, bad.CO2Class = 40000, 5, 6, 1
		if err := check(Request{CargoKg: 1, Truck: bad}); err == nil {
			t.Errorf("%+v: want an error", bad)
		}
	}
}

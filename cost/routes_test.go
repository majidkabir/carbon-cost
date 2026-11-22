package cost

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/majidkabir/carbon-cost/sootcase"
)

// fakeAlternatives answers each leg with a 100 km primary route in
// Germany and, when asked for alternatives, a 150 km one: German tolls
// make the primary the cheaper.
func fakeAlternatives(t *testing.T, queries *[]string, mu *sync.Mutex) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var s sootcase.Shipment
		json.NewDecoder(r.Body).Decode(&s)
		mu.Lock()
		*queries = append(*queries, r.URL.RawQuery)
		mu.Unlock()
		leg := func(km float64, roads ...string) sootcase.LegResult {
			ttw := 0.08 * s.WeightKg / 1000 * km
			return sootcase.LegResult{DistanceKm: km, TTWKg: ttw, WTWKg: ttw * 1.25, CountryKm: map[string]float64{"DE": km},
				Path: [][2]float64{{9, 52}, {10, 52}}, Summary: &sootcase.RouteSummary{Roads: roads, Ferries: []sootcase.FerryUse{}}}
		}
		var res sootcase.Result
		for range s.Legs {
			l := leg(100, "A7")
			if r.URL.Query().Get("alternatives") != "" {
				a := leg(150, "A1", "A2")
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
	for _, bad := range []Request{{Alternatives: 6}, {Route: "fastest"}, {Ferry: "only"}, {Alternatives: 3, CountryKm: map[string]float64{"DE": 100}}} {
		bad.CargoKg, bad.From, bad.To = 1, base.From, base.To
		if err := check(bad); err == nil {
			t.Errorf("%+v: want an error", bad)
		}
	}
}

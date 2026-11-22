package cost

import (
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// The default diesel reproduces the Commission's VECTO figures for 5-LH
// (COM(2024) 313 Table 6): 632 g CO2/km at 2.6 t, 826 g/km at 19.2 t.
func TestVehicleGroup(t *testing.T) {
	for _, tc := range []struct {
		truck rates.Truck
		loadT float64
		group string
		g     float64
	}{
		{truck40, 2.6, "5-LH", 632},
		{truck40, 19.2, "5-LH", 826},
		{truck40, 0, "5-LH", 632 - 2.6*194/16.6},
		{rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}, 5, "9-LH", 843},
		{rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}, 5, "4-LH", 730},
		{rates.Truck{MaxMassKg: 12000, Axles: 2, Euro: 6, CO2Class: 1}, 1, "2 ", 627},
		{rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}, 1, "1 ", 610},
	} {
		g, v := vehicleGroup(tc.truck, tc.loadT)
		if !strings.HasPrefix(g, tc.group) || math.Abs(v-tc.g) > 1e-9 {
			t.Errorf("%+v with %v t: %s %v g/km, want %s %v", tc.truck, tc.loadT, g, v, tc.group, tc.g)
		}
	}
}

// The truck's diesel: the litres given, bought, or per 100 km, before
// the default; and the CO2 prices on fuel where it was bought.
func TestTripFuel(t *testing.T) {
	day := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)
	price := func(req Request) Response {
		t.Helper()
		req.Truck = truck40
		r, err := Price(cphHam, all(t), req, day)
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	fuel := func(r Response, cc string) Line {
		l, _ := line(r, FuelCO2, cc, rates.CO2)
		return l
	}
	r := price(Request{CargoKg: 20000, LPer100Km: 30})
	if r.Trip.FuelL != 84.3 || !strings.HasPrefix(r.Trip.FuelBasis, "l_per_100km: 30") {
		t.Errorf("30 l/100 km x 281 km: %+v", r.Trip)
	}
	r = price(Request{CargoKg: 20000, DieselL: 100, LPer100Km: 30})
	if r.Trip.FuelL != 100 || r.Trip.FuelBasis != "diesel_l (given)" {
		t.Errorf("diesel_l: %+v", r.Trip)
	}
	// 100 l bought: 75 in Germany, 25 in Denmark.
	r = price(Request{CargoKg: 20000, FuelPurchases: []FuelPurchase{{"DE", 75}, {"DK", 25}}})
	if r.Trip.FuelL != 100 || fuel(r, "DK").Litres != 25 || math.Abs(fuel(r, "DE").TonnesCO2-0.2) > 0.001 {
		t.Errorf("purchases: %+v, DK %+v, DE %+v", r.Trip, fuel(r, "DK"), fuel(r, "DE"))
	}
	if !hasNote(r, "fuel_purchases") {
		t.Errorf("notes %v", r.Notes)
	}
	// A zero-emission truck burns none.
	zev := truck40
	zev.CO2Class = 5
	r, _ = Price(cphHam, all(t), Request{CargoKg: 20000, Truck: zev}, day)
	if r.Trip.FuelL != 0 {
		t.Errorf("class 5: %+v", r.Trip)
	}
	for _, bad := range []Request{
		{CargoKg: 1, FuelPurchases: []FuelPurchase{{"de", 10}}},
		{CargoKg: 1, FuelPurchases: []FuelPurchase{{"DE", 10}}, FuelCountry: "DE"},
		{CargoKg: 1, LPer100Km: 120},
	} {
		bad.Truck = truck40
		if _, err := Price(cphHam, all(t), bad, day); err == nil {
			t.Errorf("%+v: want an error", bad)
		}
	}
}

// fakeLegs is a Sootcase that routes each leg 100 km in Germany per stop
// index apart (stop codes S0, S1...), at 0.08 kg TTW per tkm.
func fakeLegs(t *testing.T, calls *[]sootcase.Shipment, mu *sync.Mutex) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var s sootcase.Shipment
		if err := json.NewDecoder(r.Body).Decode(&s); err != nil {
			t.Error(err)
		}
		mu.Lock()
		*calls = append(*calls, s)
		mu.Unlock()
		var res sootcase.Result
		for _, l := range s.Legs {
			a, b := int(l.From.Code[1]-'0'), int(l.To.Code[1]-'0')
			km := 100 * math.Abs(float64(b-a))
			ttw := 0.08 * s.WeightKg / 1000 * km
			res.Legs = append(res.Legs, sootcase.LegResult{DistanceKm: km, TTWKg: ttw, WTWKg: ttw * 1.25, CountryKm: map[string]float64{"DE": km},
				Path: [][2]float64{{9 + float64(a), 52}, {9 + float64(b), 52}}})
			res.TTWKg += ttw
			res.WTWKg += ttw * 1.25
		}
		json.NewEncoder(w).Encode(res)
	}))
}

// A trip with stops and shipments: the truck pays the trip, each
// shipment its tonne-km share (EN ISO 14083), on its own route's km.
func TestTripShipments(t *testing.T) {
	var calls []sootcase.Shipment
	var mu sync.Mutex
	fake := fakeLegs(t, &calls, &mu)
	defer fake.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: fake.URL}, Tariffs: all(t)}
	stop := func(i int) sootcase.Location { return sootcase.Location{Code: "S" + string(rune('0'+i))} }
	// S0 -> S1 -> S2 -> S0: A (10 t) S0 to S2, B (10 t) S0 to S1, back
	// empty from S2 to S0 (200 km).
	req := Request{Date: "2026-11-03", Truck: truck40, Stops: []sootcase.Location{stop(0), stop(1), stop(2), stop(0)},
		Shipments: []Shipment{{ID: "A", WeightKg: 10000, To: 2}, {ID: "B", WeightKg: 10000, To: 1}}}
	r, err := c.Calculate(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	tr := r.Trip
	if len(tr.Legs) != 3 || tr.Legs[0].LoadKg != 20000 || tr.Legs[1].LoadKg != 10000 || tr.Legs[2].LoadKg != 0 || tr.EmptyKm != 200 || tr.RoadKm != 400 {
		t.Fatalf("trip %+v", tr)
	}
	// Fuel by leg load: 100 km at 20 t, 100 at 10 t, 200 empty.
	g := func(load float64) float64 { _, v := vehicleGroup(truck40, load); return v }
	want := (g(20)*100 + g(10)*100 + g(0)*200) / (DieselKgCO2PerL * 1000)
	if math.Abs(tr.FuelL-want) > 0.01 {
		t.Errorf("fuel %v, want %v", tr.FuelL, want)
	}
	// One Sootcase call for the trip at the heaviest load, and one for A's
	// own route S0 -> S2 (B's is the first leg).
	if len(calls) != 2 || calls[0].WeightKg != 20000 || len(calls[0].Legs) != 3 || calls[1].WeightKg != 10000 || calls[1].Legs[0].To.Code != "S2" {
		t.Errorf("calls %+v", calls)
	}
	// A: 10 t x 200 km, B: 10 t x 100 km.
	if len(r.Shipments) != 2 {
		t.Fatalf("shipments %+v", r.Shipments)
	}
	a, b := r.Shipments[0], r.Shipments[1]
	if a.ID != "A" || a.DistanceKm != 200 || a.TKm != 2000 || math.Abs(a.Share-2.0/3) > 1e-6 || b.TKm != 1000 || math.Abs(b.Share-1.0/3) > 1e-6 {
		t.Errorf("A %+v, B %+v", a, b)
	}
	if math.Abs(a.TotalEUR+b.TotalEUR-r.TotalEUR) > 0.011 || a.TTWKg != 160 || b.TTWKg != 80 || r.TTWKg != 240 {
		t.Errorf("A %v + B %v of %v; TTW %v %v %v", a.TotalEUR, b.TotalEUR, r.TotalEUR, a.TTWKg, b.TTWKg, r.TTWKg)
	}
	// The DE toll on all 400 km, the empty return included.
	if l, ok := line(r, RoadToll, "DE", rates.Infrastructure); !ok || l.Km != 400 {
		t.Errorf("DE toll %+v", l)
	}
	for _, bad := range []Request{
		{Truck: truck40, Stops: []sootcase.Location{stop(0), stop(1)}, Shipments: []Shipment{{WeightKg: 1, From: 1, To: 1}}},
		{Truck: truck40, Stops: []sootcase.Location{stop(0), stop(1)}, Shipments: []Shipment{{WeightKg: 1}}, CargoKg: 5},
		{Truck: truck40, Stops: []sootcase.Location{stop(0)}, CargoKg: 5},
		{Truck: truck40, Stops: []sootcase.Location{stop(0), stop(1)}, From: stop(0), CargoKg: 5},
		{Truck: truck40, Stops: []sootcase.Location{stop(0), stop(1), stop(2)}, Shipments: []Shipment{{ID: "x", WeightKg: 1}, {ID: "x", WeightKg: 1}}},
	} {
		if _, err := c.Calculate(context.Background(), bad); err == nil {
			t.Errorf("%+v: want an error", bad)
		}
	}
}

// A ferry the truck crosses empty: no cargo share of its emissions
// without the ships' MRV data, and a note saying so.
func TestFerryEmpty(t *testing.T) {
	// As Calculator.trip leaves it: the leg's emissions scaled to no load.
	empty := sootcase.Result{Legs: []sootcase.LegResult{{
		DistanceKm: 300, RouteParts: map[string]float64{"ferry": 19}, CountryKm: map[string]float64{"DK": 140, "DE": 141},
		Parts: []sootcase.Part{{Kind: "ferry", DistanceKm: 19}},
	}}}
	req := Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75, legLoadKg: []float64{0}}
	r, err := PriceWith(empty, all(t), nil, req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := line(r, FerryETS, "", ""); ok {
		t.Error("ferry ETS line for an empty crossing")
	}
	if !strings.Contains(strings.Join(r.Notes, "\n"), "crosses a crossing empty") {
		t.Errorf("notes %q", r.Notes)
	}
}

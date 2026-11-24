package cost

import (
	"context"
	"encoding/json"
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

// With the truck's diesel given, the trip's emissions are the litres'
// (primary data), shared by tonne-km; a ferry's are Sootcase's for the
// load on board, shared by weight among the shipments on it.
func TestPrimaryEmissions(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{
		{DistanceKm: 100, CountryKm: map[string]float64{"DE": 100}},
		{DistanceKm: 120, RouteParts: map[string]float64{"ferry": 20}, CountryKm: map[string]float64{"DE": 100},
			Parts: []sootcase.Part{{Kind: "ferry", DistanceKm: 20, TTWKg: 30, WTWKg: 36}}},
	}}
	req := Request{Truck: truck40, DieselL: 100, Stops: []sootcase.Location{{Code: "A"}, {Code: "B"}, {Code: "C"}},
		Shipments: []Shipment{{ID: "A", WeightKg: 10000, To: 2}, {ID: "B", WeightKg: 10000, From: 1}},
		legLoadKg: []float64{10000, 20000}, shipDistKm: []float64{220, 120}}
	r, err := PriceWith(res, all(t), nil, req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	// Road: 100 l x 2.67 = 267 kg TTW, 324 WTW; tkm A 2200, B 1200.
	// Ferry on leg 1: 30 kg TTW, A and B 10 t each, half each.
	if r.DataType != "primary" || r.TTWKg != 297 || r.WTWKg != 360 {
		t.Fatalf("%s %v %v: %s", r.DataType, r.TTWKg, r.WTWKg, r.EmissionsBasis)
	}
	a, b := r.Shipments[0], r.Shipments[1]
	if math.Abs(a.TTWKg-(267*2200/3400.0+15)) > 0.001 || math.Abs(b.TTWKg-(267*1200/3400.0+15)) > 0.001 {
		t.Errorf("A %v, B %v", a.TTWKg, b.TTWKg)
	}
	if math.Abs(a.IntensityG-round2(a.WTWKg*1000/2200)) > 0.01 || math.Abs(r.IntensityG-round2(360*1000/3400.0)) > 0.01 {
		t.Errorf("intensity %v %v", a.IntensityG, r.IntensityG)
	}
	if !strings.Contains(r.EmissionsBasis, "EN 16258") || !strings.Contains(r.EmissionsBasis, "ferries") {
		t.Errorf("basis %q", r.EmissionsBasis)
	}
	// The method and that the tool isn't certified, and never the line
	// Regulation (EU) 2026/1030 Art. 10(1) keeps for certified tools.
	js, _ := json.Marshal(r)
	if r.EmissionsStandard != "EN ISO 14083:2023" || !strings.HasPrefix(r.Certification, "Not certified") || strings.Contains(strings.ToLower(string(js)), "in accordance with regulation") {
		t.Errorf("standard %q, certification %q", r.EmissionsStandard, r.Certification)
	}
	// Without the diesel: Sootcase's, modelled, on the framework and
	// version it names.
	req.DieselL, req.shipTTW, req.shipWTW = 0, []float64{100, 50}, []float64{120, 60}
	res.Basis = &sootcase.Basis{Standard: "EN ISO 14083:2023", Framework: "GLEC Framework v3.3", Sootcase: "v0.17.0"}
	if r, _ := PriceWith(res, all(t), nil, req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)); r.EmissionsBasis != "Sootcase v0.17.0: GLEC Framework v3.3 default intensities x each shipment's tonne-km on its own route" {
		t.Errorf("modelled basis %q", r.EmissionsBasis)
	}
	res.Basis = nil
	if r, _ = PriceWith(res, all(t), nil, req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)); r.DataType != "modelled" || r.TTWKg != 150 || r.Shipments[0].TTWKg != 100 {
		t.Errorf("default: %s %v %+v", r.DataType, r.TTWKg, r.Shipments)
	}
}

// Each shipment's share by country and per 100 kg, for invoices and
// surcharge tables; the trip's per tonne-km.
func TestShipmentBreakdown(t *testing.T) {
	r, err := PriceWith(cphHam, all(t), nil, Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75}, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	s := r.Shipments[0]
	var sum float64
	for _, v := range s.ByCountry {
		sum += v
	}
	if math.Abs(sum-r.TotalEUR) > 0.02 || s.ByCountry["DE"] == 0 || s.ByCountry["DK"] == 0 {
		t.Errorf("by country %v of %v", s.ByCountry, r.TotalEUR)
	}
	if s.EURPer100Kg != round2(r.TotalEUR/200) || r.EURPerTkm != math.Round(r.TotalEUR/(20*300)*1e4)/1e4 {
		t.Errorf("per 100 kg %v, per tkm %v", s.EURPer100Kg, r.EURPerTkm)
	}
}

// A crossing whose one line publishes an ETS surcharge is priced at it:
// Scandlines' per commencing metre, at least 7; POLSCA's from each
// announcement; a crossing sailed by several lines stays on the ships'
// emissions, with a note.
func TestFerrySurcharge(t *testing.T) {
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
	tr.LengthM = 16.5
	// No EUA price needed: the line's surcharge, 17 commencing metres.
	r, err := PriceWith(trip, all(t), &fd, Request{CargoKg: 20000, Truck: tr}, nov26)
	if err != nil {
		t.Fatal(err)
	}
	l, ok := line(r, FerryETS, "", "")
	if !ok || l.Rate != 0.18 || l.RateUnit != "EUR/m" || l.Amount != 3.06 || !strings.Contains(l.Source, "Scandlines' ETS surcharge") {
		t.Errorf("Scandlines: %+v", l)
	}
	// An empty truck pays it too: it goes by the vehicle's length.
	if r, _ = PriceWith(trip, all(t), &fd, Request{CargoKg: 20000, Truck: tr, legLoadKg: []float64{0}}, nov26); !hasLine(r, FerryETS) {
		t.Errorf("empty: %+v", r.Lines)
	}
	s, ok := fd.ETSSurcharge("gdansk-karlshamn", time.Date(2026, 7, 20, 0, 0, 0, 0, time.UTC))
	if !ok || s.EURPerM != 5.4 || s.Metres(16.5) != 17 {
		t.Errorf("POLSCA Gdańsk–Karlshamn, July: %+v", s)
	}
	if s, ok = fd.ETSSurcharge("gdansk-karlshamn", time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC)); !ok || s.EURPerM != 5.99 {
		t.Errorf("POLSCA Gdańsk–Karlshamn, November: %+v", s)
	}
	if s, ok = fd.ETSSurcharge("klaipeda-kiel", nov26); !ok || s.EURPerM != 6.94 || s.Metres(16.5) != 16.5 || s.Operator != "DFDS" {
		t.Errorf("DFDS Klaipėda–Kiel: %+v", s)
	}
	// DFDS's month ended and not yet the next: none.
	if _, ok = fd.ETSSurcharge("klaipeda-kiel", time.Date(2027, 1, 5, 0, 0, 0, 0, time.UTC)); ok {
		t.Error("DFDS January 2027: want none")
	}
	if _, ok = fd.ETSSurcharge("dover-calais", nov26); !ok {
		t.Error("DFDS Dover–Calais: want its surcharge")
	}
}

func hasLine(r Response, charge string) bool {
	for _, l := range r.Lines {
		if l.Charge == charge {
			return true
		}
	}
	return false
}

func TestFerrySurchargeStena(t *testing.T) {
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	s, ok := fd.ETSSurcharge("gothenburg-kiel", time.Date(2026, 11, 10, 0, 0, 0, 0, time.UTC))
	if !ok || s.Operator != "Stena Line" || s.EURPerM != 4.67 || s.Metres(16.5) != 16.5 {
		t.Errorf("Stena Gothenburg–Kiel: %+v", s)
	}
}

// The diesel at the Weekly Oil Bulletin's prices, or at the truck's own;
// with_fuel_eur counts the CO2 prices on fuel once.
func TestFuelCost(t *testing.T) {
	day := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC)
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"DE": 200, "PL": 100}}}}
	req := Request{CargoKg: 20000, Truck: truck40, DieselL: 90, FX: map[string]float64{"PLN": 4.25}}
	r, err := PriceWith(res, all(t), nil, req, day)
	if err != nil {
		t.Fatal(err)
	}
	// Bought along the route: 60 l in Germany, 30 in Poland; the bulletin
	// of 16 November 2026: DE 1.8613, PL 1.3629 EUR/l without VAT.
	f := r.Fuel
	if f == nil || !f.Complete || len(f.ByCountry) != 2 || f.ByCountry[0].Country != "DE" || f.ByCountry[0].Litres != 60 ||
		f.ByCountry[0].EURPerL != 1.8613 || f.ByCountry[1].EURPerL != 1.3629 || !strings.HasPrefix(f.ByCountry[0].Price, "Weekly Oil Bulletin 2026-11-16") {
		t.Fatalf("fuel %+v", f)
	}
	if want := round2(60*1.8613 + 30*1.3629); f.EUR != want {
		t.Errorf("fuel EUR %v, want %v", f.EUR, want)
	}
	var co2 float64
	for _, l := range r.Lines {
		if l.Charge == FuelCO2 {
			co2 += l.AmountEUR
		}
	}
	if co2 == 0 || f.InPriceEUR != round2(co2) || r.WithFuelEUR != round2(r.TotalEUR+f.EUR-f.InPriceEUR) {
		t.Errorf("in price %v (co2 %v), with fuel %v, total %v", f.InPriceEUR, co2, r.WithFuelEUR, r.TotalEUR)
	}
	if r.Shipments[0].FuelEUR != f.EUR || r.Shipments[0].WithFuelEUR != r.WithFuelEUR {
		t.Errorf("shipment %+v", r.Shipments[0])
	}
	// The truck's own prices: one for all, Poland's over it.
	req.DieselEURPerL, req.DieselEURPerLByCountry = 1.5, map[string]float64{"PL": 1.2}
	r, _ = PriceWith(res, all(t), nil, req, day)
	if r.Fuel.EUR != round2(60*1.5+30*1.2) || r.Fuel.ByCountry[0].Price != "given" {
		t.Errorf("given: %+v", r.Fuel)
	}
	// Bought in Switzerland: no bulletin price; the Federal Statistical
	// Office's newest month, October 2026, CHF 2.41 with 8.1% VAT, at the
	// rate given.
	req.DieselEURPerL, req.DieselEURPerLByCountry, req.FuelCountry = 0, nil, "CH"
	req.FX["CHF"] = 0.93
	r, _ = PriceWith(res, all(t), nil, req, day)
	if want := round4(2.41 / 1.081 / 0.93); !r.Fuel.Complete || r.Fuel.ByCountry[0].EURPerL != want || !strings.Contains(r.Fuel.ByCountry[0].Price, "Federal Statistical Office") ||
		!slices.ContainsFunc(r.Notes, func(n string) bool {
			return strings.Contains(n, "CH CHF 2.4100 with 8.1% VAT (2026-10-01)") && strings.Contains(n, "newest there is")
		}) {
		t.Errorf("CH: %+v %q", r.Fuel, r.Notes)
	}
	// Bought in Serbia: no price anywhere.
	req.FuelCountry = "RS"
	r, _ = PriceWith(res, all(t), nil, req, day)
	if r.Fuel.Complete || len(r.Fuel.Unpriced) != 1 || r.Fuel.Unpriced[0] != "RS" || r.Fuel.EUR != 0 {
		t.Errorf("RS: %+v", r.Fuel)
	}
	if err := check(Request{CargoKg: 1, Stops: req.Stops, DieselEURPerLByCountry: map[string]float64{"pl": 1}}); err == nil {
		t.Error("lower-case country: want an error")
	}
}

func TestDieselRefunds(t *testing.T) {
	day := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC)
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"FR": 300}}}}
	req := Request{CargoKg: 20000, Truck: truck40, DieselL: 100}
	r, err := PriceWith(res, all(t), nil, req, day)
	if err != nil {
		t.Fatal(err)
	}
	p := r.Fuel.ByCountry[0].EURPerL
	if r.Fuel.RefundEUR != 0 || !slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "set diesel_refunds") }) {
		t.Errorf("not asked: %+v %q", r.Fuel, r.Notes)
	}
	// France refunds EUR 15.56/hl to trucks of 7.5 t or more (CIBS L.312-53).
	req.DieselRefunds = true
	if r, err = PriceWith(res, all(t), nil, req, day); err != nil || r.Fuel.RefundEUR != 15.56 || r.Fuel.ByCountry[0].RefundEURPerL != 0.1556 ||
		r.Fuel.EUR != round2(100*(p-0.1556)) || !strings.Contains(r.Fuel.ByCountry[0].Refund, "L.312-53") {
		t.Errorf("refund: %v %+v", err, r.Fuel)
	}
	small := req
	small.Truck.MaxMassKg, small.Truck.Axles = 7000, 2
	if r, err = PriceWith(res, all(t), nil, small, day); err != nil || r.Fuel.RefundEUR != 0 {
		t.Errorf("7 t truck: %v %+v", err, r.Fuel)
	}
	// Italy: the excise above EUR 403.22 per 1,000 l (0.6329 in the
	// bulletin of 16 November 2026), Euro V and VI only.
	it := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"IT": 300}}}}
	if r, err = PriceWith(it, all(t), nil, req, day); err != nil || r.Fuel.RefundEUR != 22.97 || !strings.Contains(r.Fuel.ByCountry[0].Refund, "24-ter") {
		t.Errorf("IT: %v %+v", err, r.Fuel)
	}
	old := req
	old.Truck.Euro = 4
	if r, err = PriceWith(it, all(t), nil, old, day); err != nil || r.Fuel.RefundEUR != 0 {
		t.Errorf("IT, Euro IV: %v %+v", err, r.Fuel)
	}
	// None before 2025 in the table.
	if r, err = PriceWith(res, all(t), nil, req, time.Date(2024, 6, 3, 0, 0, 0, 0, time.UTC)); err != nil || r.Fuel.RefundEUR != 0 {
		t.Errorf("2024: %v %+v", err, r.Fuel)
	}
}

func TestHungaryRefund(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, CountryKm: map[string]float64{"HU": 300}}}}
	req := Request{CargoKg: 20000, Truck: truck40, DieselL: 100, DieselRefunds: true, FX: map[string]float64{"HUF": 400}}
	// HUF 17 a litre in 2025 (NAV), at 400 forint to the euro.
	r, err := PriceWith(res, all(t), nil, req, time.Date(2025, 6, 4, 0, 0, 0, 0, time.UTC))
	if err != nil || r.Fuel.RefundEUR != 4.25 || r.Fuel.ByCountry[0].RefundEURPerL != 0.0425 {
		t.Errorf("2025: %v %+v", err, r.Fuel)
	}
	// Zero since 14 May 2026, the excise at the EU minimum.
	if r, err = PriceWith(res, all(t), nil, req, time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC)); err != nil || r.Fuel.RefundEUR != 0 ||
		!slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "HU refunds nothing") }) {
		t.Errorf("2026: %v %+v %q", err, r.Fuel, r.Notes)
	}
}

// Costs shared by loading-metre-km, emissions still by tonne-km.
func TestCostShareByLoadingMetres(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{
		{DistanceKm: 100, CountryKm: map[string]float64{"DE": 100}},
		{DistanceKm: 120, CountryKm: map[string]float64{"DE": 120}},
	}}
	// A: 10 t, 2 loading metres, 220 km; B: 10 t, 6 loading metres, 120 km.
	req := Request{Truck: truck40, DieselL: 100, Stops: []sootcase.Location{{Code: "A"}, {Code: "B"}, {Code: "C"}},
		Shipments: []Shipment{{ID: "A", WeightKg: 10000, To: 2, LoadingM: 2}, {ID: "B", WeightKg: 10000, From: 1, LoadingM: 6}},
		CostShareBy: "loading_m", legLoadKg: []float64{10000, 20000}, shipDistKm: []float64{220, 120}}
	if err := check(req); err != nil {
		t.Fatal(err)
	}
	r, err := PriceWith(res, all(t), nil, req, time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	a, b := r.Shipments[0], r.Shipments[1]
	// Costs: 440 and 720 loading-metre-km; emissions: 2,200 and 1,200 tkm.
	if math.Abs(a.Share-440.0/1160) > 1e-6 || math.Abs(b.TotalEUR-round2(r.TotalEUR*720/1160)) > 0.011 ||
		math.Abs(a.WTWKg-r.WTWKg*2200/3400) > 0.001 || a.TKm != 2200 {
		t.Errorf("A %+v, B %+v", a, b)
	}
	if !slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "loading-metre-km") && strings.Contains(n, "GLEC") }) {
		t.Errorf("notes %q", r.Notes)
	}
	// Without loading metres for each: an error.
	req.Shipments[1].LoadingM = 0
	if err := check(req); err == nil || !strings.Contains(err.Error(), "shipments[1]") {
		t.Errorf("missing loading_m: %v", err)
	}
	req.CostShareBy = "volume"
	if err := check(req); err == nil {
		t.Error("cost_share_by volume: want an error")
	}
}

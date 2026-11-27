package cost

import (
	"context"
	"math"
	"os"
	"reflect"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// TestInvariants prices a corpus of realistic requests and checks what
// must hold for any of them, whichever charge or input is involved:
//
//   - a note never asks for an input the request already gives;
//   - complete is true exactly when nothing is missing, and each missing
//     charge has a text and a reason Missing.Reason's doc names;
//   - with some litres unpriced, nothing compared with the energy counts
//     them as free (savings with it are null);
//   - the shipments' costs add up to the trip's, and a shipment carried
//     some km has emissions.
//
// A new kind of request or result goes in the corpus; a new class of
// mistake gets an invariant here.
func TestInvariants(t *testing.T) {
	var calls []sootcase.Shipment
	var mu sync.Mutex
	legs := fakeLegs(t, &calls, &mu)
	defer legs.Close()
	var queries []string
	alts := fakeAlternatives(t, &queries, &mu)
	defer alts.Close()
	set := all(t)
	byLegs := Calculator{Sootcase: sootcase.Client{BaseURL: legs.URL}, Tariffs: set}
	byAlts := Calculator{Sootcase: sootcase.Client{BaseURL: alts.URL}, Tariffs: set}
	noRoute := Calculator{Tariffs: set}
	day := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)
	s := func(i int) sootcase.Location { return sootcase.Location{Code: "S" + string(rune('0'+i))} }
	// Routes as Sootcase gives them, with their emissions.
	huRS := sootcase.Result{TTWKg: 960, WTWKg: 1200, Legs: []sootcase.LegResult{{DistanceKm: 600, TTWKg: 960, WTWKg: 1200, CountryKm: map[string]float64{"HU": 300, "RS": 300}}}}
	is := sootcase.Result{TTWKg: 80, WTWKg: 100, Legs: []sootcase.LegResult{{DistanceKm: 100, TTWKg: 80, WTWKg: 100, CountryKm: map[string]float64{"IS": 100}}}}
	cz := sootcase.Result{TTWKg: 6, WTWKg: 7.5, Legs: []sootcase.LegResult{{DistanceKm: 5, TTWKg: 6, WTWKg: 7.5, CountryKm: map[string]float64{"CZ": 5}, Path: [][2]float64{{16.6, 49.2}, {16.65, 49.2}}}}}

	type run struct {
		name string
		req  Request
		do   func(Request) (Response, error)
	}
	price := func(res sootcase.Result) func(Request) (Response, error) {
		return func(r Request) (Response, error) { return Price(res, set, r, day) }
	}
	calc := func(c Calculator) func(Request) (Response, error) {
		return func(r Request) (Response, error) { return c.Calculate(context.Background(), r) }
	}
	corpus := []run{
		{"cph-ham with time", Request{CargoKg: 20000, Truck: truck40, Time: "06:00", EUAEurPerT: 75}, price(cphHam)},
		{"cph-ham compare", Request{CargoKg: 20000, Truck: truck40, CompareCO2Classes: []int{1, 4, 5}, KWhPer100Km: 120, ElectricityEURPerKWh: 0.25, TripsPerYear: 100}, price(cphHam)},
		{"hu-rs diesel partly unpriced, compare", Request{CargoKg: 20000, Truck: truck40, CompareCO2Classes: []int{1, 5}, KWhPer100Km: 120, ElectricityEURPerKWh: 0.25, TripsPerYear: 100,
			FuelPurchases: []FuelPurchase{{Country: "HU", Litres: 90}, {Country: "RS", Litres: 90}}, FX: map[string]float64{"HUF": 385, "RSD": 117}}, price(huRS)},
		{"cz tolled_share", Request{CargoKg: 8000, Truck: truck40, TolledShare: map[string]float64{"CZ": 1}, FX: map[string]float64{"CZK": 25}}, price(cz)},
		{"cz motorway_share", Request{CargoKg: 8000, Truck: truck40, MotorwayShare: map[string]float64{"CZ": 0}, FX: map[string]float64{"CZK": 25}}, price(cz)},
		{"cz both shares", Request{CargoKg: 8000, Truck: truck40, MotorwayShare: map[string]float64{"CZ": 0.5}, TolledShare: map[string]float64{"CZ": 1}, FX: map[string]float64{"CZK": 25}}, price(cz)},
		{"km by country SE, time", Request{CountryKm: map[string]float64{"SE": 3200}, Date: "2026-10-01", Time: "08:00", CargoKg: 10000, DieselL: 900, Truck: truck40, FX: map[string]float64{"SEK": 11.5}}, calc(noRoute)},
		{"km by country DE PL", Request{CountryKm: map[string]float64{"DE": 290, "PL": 470}, Date: "2026-11-26", CargoKg: 10000, DieselL: 200, Truck: truck40, FX: map[string]float64{"PLN": 4.25}}, calc(noRoute)},
		{"km by country IT, diesel price", Request{CountryKm: map[string]float64{"IT": 620}, Date: "2026-11-26", CargoKg: 10000, DieselL: 200, DieselEURPerL: 1.4, Truck: truck40}, calc(noRoute)},
		{"stops and shipments", Request{Date: "2026-11-03", Truck: truck40, Stops: []sootcase.Location{s(0), s(1), s(2), s(0)},
			Shipments: []Shipment{{ID: "A", WeightKg: 10000, To: 2}, {ID: "B", WeightKg: 10000, To: 1}}}, calc(byLegs)},
		{"shipment round its start", Request{Date: "2026-11-03", Truck: truck40, Stops: []sootcase.Location{s(0), s(1), s(0)},
			Shipments: []Shipment{{ID: "A", WeightKg: 10000, To: 2}}}, calc(byLegs)},
		{"cheapest with running costs", Request{Date: "2026-11-03", Truck: truck40, CargoKg: 20000, From: sootcase.Location{Code: "DEHAM"}, To: sootcase.Location{Code: "DEMUC"},
			Route: "cheapest", DriverEURPerH: 35, VehicleEURPerKm: 0.4}, calc(byAlts)},
		{"ferry crossing, ets share given", Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75, FerryETSShare: 0.5}, price(cphHam)},
		{"Iceland, motor axles given", Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1, MotorAxles: 2}, FX: map[string]float64{"ISK": 140}}, price(is)},
		{"km by country AL", Request{CountryKm: map[string]float64{"AL": 300}, Date: "2026-11-26", CargoKg: 10000, DieselL: 100, Truck: truck40}, calc(noRoute)},
		{"km by country AT, compare", Request{CountryKm: map[string]float64{"AT": 300}, Date: "2027-01-15", CargoKg: 10000, DieselL: 100, Truck: truck40, CompareCO2Classes: []int{1, 5}, TripsPerYear: 200, KWhPer100Km: 120, ElectricityEURPerKWh: 0.25}, calc(noRoute)},
		{"cheapest, electric", Request{Date: "2026-11-03", Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}, CargoKg: 20000, From: sootcase.Location{Code: "DEHAM"}, To: sootcase.Location{Code: "DEMUC"}, Route: "cheapest"}, calc(byAlts)},
		{"cheapest, diesel partly unpriced", Request{Date: "2026-11-03", Truck: truck40, CargoKg: 20000, From: sootcase.Location{Code: "DEHAM"}, To: sootcase.Location{Code: "DEMUC"},
			Route: "cheapest", DriverEURPerH: 35, VehicleEURPerKm: 0.4, FuelPurchases: []FuelPurchase{{Country: "DE", Litres: 20}, {Country: "RS", Litres: 20}}, FX: map[string]float64{"RSD": 117}}, calc(byAlts)},
	}
	reasons := documentedReasons(t)
	for _, c := range corpus {
		r, err := c.do(c.req)
		if err != nil {
			t.Errorf("%s: %v", c.name, err)
			continue
		}
		for _, n := range r.Notes {
			if field, given := asksForGiven(n, c.req); given {
				t.Errorf("%s: a note asks for %s, which the request gives: %q", c.name, field, n)
			}
		}
		if r.Complete != (len(r.Missing) == 0) {
			t.Errorf("%s: complete %v with missing %+v", c.name, r.Complete, r.Missing)
		}
		for _, m := range r.Missing {
			if m.Text == "" || !reasons[m.Reason] {
				t.Errorf("%s: missing %+v: no text, or a reason Missing.Reason's doc doesn't name", c.name, m)
			}
		}
		// A note on an electric truck's trip speaks of its electricity.
		if c.req.Truck.CO2Class == 5 && r.Fuel == nil {
			for _, n := range r.Notes {
				if strings.Contains(n, "cheapest by") && strings.Contains(n, "diesel") {
					t.Errorf("%s: an electric truck's note speaks of diesel: %q", c.name, n)
				}
			}
		}
		for _, cmp := range r.Compare {
			if cmp.Complete && !r.Complete {
				t.Errorf("%s: class %d's comparison complete, the trip's result not (missing %+v)", c.name, cmp.CO2Class, r.Missing)
			}
		}
		if r.Fuel != nil && !r.Fuel.Complete {
			for _, cmp := range r.Compare {
				if cmp.SavingWithFuelEUR != nil {
					t.Errorf("%s: class %d's saving with fuel %v counts unpriced litres as free", c.name, cmp.CO2Class, *cmp.SavingWithFuelEUR)
				}
			}
			// Routes compare by their charges and running costs then.
			for _, o := range r.Routes {
				if want := round2(o.TotalEUR + o.runningEUR - r.Routes[0].TotalEUR - r.Routes[0].runningEUR); o.Error == "" && math.Abs(o.DiffEUR-want) > 0.011 {
					t.Errorf("%s: route %s diff %.2f, want %.2f (charges and running costs: some litres have no price)", c.name, o.ID, o.DiffEUR, want)
				}
			}
		}
		if len(r.Shipments) > 1 {
			var sum float64
			for _, sh := range r.Shipments {
				sum += sh.TotalEUR
			}
			if math.Abs(sum-r.TotalEUR) > 0.01*float64(len(r.Shipments)) {
				t.Errorf("%s: shipments' %.2f of the trip's %.2f", c.name, sum, r.TotalEUR)
			}
		}
		for _, sh := range r.Shipments {
			if sh.DistanceKm > 0 && r.Trip != nil && r.Trip.FuelL > 0 && sh.WTWKg <= 0 {
				t.Errorf("%s: shipment %s carried %.0f km with no emissions", c.name, sh.ID, sh.DistanceKm)
			}
		}
	}
}

// asksForGiven says whether note asks the user to give an input the
// request already gives, and which: any request field by its JSON name
// ("give time", "give ferry_ets_share", "give tolled_share.CZ"), or a
// truck's ("Give truck.motor_axles"), after a "give" in the same clause.
func asksForGiven(note string, req Request) (string, bool) {
	given := func(v reflect.Value, name, key string) bool {
		t := v.Type()
		for i := 0; i < t.NumField(); i++ {
			if strings.Split(t.Field(i).Tag.Get("json"), ",")[0] != name {
				continue
			}
			f := v.Field(i)
			if f.Kind() == reflect.Map && key != "" {
				return f.MapIndex(reflect.ValueOf(key)).IsValid()
			}
			return !f.IsZero()
		}
		return false
	}
	for _, clause := range regexp.MustCompile(`(?i)\bgive\b(?:[^.;]|\.\S)*`).FindAllString(note, -1) {
		for _, m := range regexp.MustCompile(`\b(truck\.)?([a-z]+(?:_[a-z0-9]+)*)(?:\.([A-Z]{2}(?:-[A-Z0-9]+)?))?\b`).FindAllStringSubmatch(clause, -1) {
			if m[1] != "" {
				if given(reflect.ValueOf(req.Truck), m[2], "") {
					return "truck." + m[2], true
				}
				continue
			}
			if (strings.Contains(m[2], "_") || m[2] == "time") && given(reflect.ValueOf(req), m[2], m[3]) {
				return strings.TrimSuffix(m[2]+"."+m[3], "."), true
			}
		}
	}
	return "", false
}

// documentedReasons are the reasons Missing.Reason's doc comment names.
func documentedReasons(t *testing.T) map[string]bool {
	src, err := os.ReadFile("cost.go")
	if err != nil {
		t.Fatal(err)
	}
	s := string(src)
	i := strings.Index(s, "// Reason is ")
	j := strings.Index(s[i:], "Reason string")
	out := map[string]bool{}
	for _, m := range regexp.MustCompile(`"([a-z_]+)"`).FindAllStringSubmatch(s[i:i+j], -1) {
		out[m[1]] = true
	}
	return out
}

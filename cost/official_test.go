package cost

import (
	"math"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// The governments' own toll calculators, read in Chrome (the captures in
// tools/tables/browser name the page and the day): the tolled km they
// route, priced here, give their total. Each case checks the rates and
// the way they are applied, not the route.
func TestOfficialCalculators(t *testing.T) {
	tr5 := rates.Truck{MaxMassKg: 40000, Axles: 5, MotorAxles: 2, Euro: 6, CO2Class: 1}
	for _, c := range []struct {
		name     string
		capture  string // tools/tables/browser
		country  string
		km       float64 // tolled km the calculator routes
		mwShare  float64 // its share on motorways
		truck    rates.Truck
		day      string
		currency string
		want     float64
	}{
		// myto.gov.cz route-based calculator, Praha-Brno: 182.97 km of D1,
		// CZK 1 091,31.
		{"CZ Praha-Brno", "cz-myto-calculator.txt", "CZ", 182.97, 1, tr5, "2026-11-25", "CZK", 1091.31},
	} {
		day, _ := time.Parse("2006-01-02", c.day)
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: c.km, CountryKm: map[string]float64{c.country: c.km}}}}
		r, err := Price(trip, all(t), Request{CargoKg: 8000, Truck: c.truck, MotorwayShare: map[string]float64{c.country: c.mwShare}, FX: map[string]float64{c.currency: 1}}, day)
		if err != nil {
			t.Fatal(c.name, err)
		}
		var got float64
		for _, l := range r.Lines {
			if l.Country == c.country && l.Charge == RoadToll {
				if l.Currency != c.currency {
					t.Errorf("%s: line in %s", c.name, l.Currency)
				}
				got += l.Amount
			}
		}
		if math.Abs(got-c.want) > 0.01 {
			t.Errorf("%s (%s): %.2f %s, the calculator says %.2f", c.name, c.capture, got, c.currency, c.want)
		}
	}
}

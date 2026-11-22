package cost

import (
	"fmt"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/fuel"
	"github.com/majidkabir/carbon-cost/rates"
)

// FuelCost is the trip's road diesel at a price: the truck's running
// cost, not a charge.
type FuelCost struct {
	// EUR is the litres priced, at their prices, without VAT.
	EUR    float64 `json:"eur"`
	Litres float64 `json:"litres"`
	// ByCountry is where the litres are bought (fuel_purchases,
	// fuel_country, or along the route by road km) and their price.
	ByCountry []FuelBought `json:"by_country"`
	// InPriceEUR is the CO2 prices on fuel (and, from 2028, ETS2) of the
	// litres priced: the diesel price already holds them, so
	// with_fuel_eur leaves them out of the charges.
	InPriceEUR float64 `json:"in_price_eur"`
	// Complete is false when some litres have no price (bought outside
	// the EU without a price given); Unpriced lists those countries.
	Complete bool     `json:"complete"`
	Unpriced []string `json:"unpriced,omitempty"`
}

// FuelBought is the litres bought in one country and their price.
type FuelBought struct {
	Country string  `json:"country"`
	Litres  float64 `json:"litres"`
	EURPerL float64 `json:"eur_per_l,omitempty"`
	EUR     float64 `json:"eur,omitempty"`
	// Price says where the price comes from: "given", or "Weekly Oil
	// Bulletin <date>".
	Price string `json:"price,omitempty"`
}

// fuelCost prices the trip's road diesel where it is bought: at the price
// given, else at the Weekly Oil Bulletin's national average of the
// trip's week, without VAT.
func fuelCost(out *Response, req Request, date time.Time) {
	if out.Trip == nil || out.Trip.FuelL <= 0 {
		return
	}
	b, latest, haveB := fuel.On(date)
	share := fuelShares(req, out.CountryKm)
	f := &FuelCost{Litres: out.Trip.FuelL, Complete: true}
	usedB, ets2InPrice := false, false
	priced := map[string]bool{}
	for _, cc := range sortedKeys(share) {
		l := out.Trip.FuelL * share[cc]
		if l <= 0 {
			continue
		}
		fb := FuelBought{Country: cc, Litres: round2(l)}
		switch {
		case req.DieselEURPerLByCountry[cc] > 0:
			fb.EURPerL, fb.Price = req.DieselEURPerLByCountry[cc], "given"
		case req.DieselEURPerL > 0:
			fb.EURPerL, fb.Price = req.DieselEURPerL, "given"
		case haveB && b.EURPerL[cc] > 0:
			fb.EURPerL, fb.Price = b.EURPerL[cc], "Weekly Oil Bulletin "+b.Date
			usedB = true
		}
		if fb.EURPerL > 0 {
			fb.EUR = round2(l * fb.EURPerL)
			f.EUR += l * fb.EURPerL
			priced[cc] = true
			// A price of a day ETS2 covers holds it: the trip's own day for a
			// price given, the bulletin's for its.
			if fb.Price == "given" && !date.Before(ETS2Start) || strings.HasPrefix(fb.Price, "Weekly") && b.Date >= ETS2Start.Format(time.DateOnly) {
				ets2InPrice = true
			}
		} else {
			f.Complete = false
			f.Unpriced = append(f.Unpriced, cc)
		}
		f.ByCountry = append(f.ByCountry, fb)
	}
	// The CO2 prices on fuel of the litres priced, and ETS2 where the price
	// holds it, are in the diesel price already.
	allPriced := f.Complete
	for _, l := range out.Lines {
		switch {
		case l.Charge == FuelCO2 && priced[l.Country]:
			f.InPriceEUR += l.AmountEUR
		case l.Charge == ETS2 && ets2InPrice && allPriced:
			f.InPriceEUR += l.AmountEUR
		}
	}
	f.EUR, f.InPriceEUR = round2(f.EUR), round2(f.InPriceEUR)
	out.Fuel = f
	out.WithFuelEUR = round2(out.TotalEUR + f.EUR - f.InPriceEUR)
	note := fmt.Sprintf("Fuel: %.1f l of diesel at EUR %.2f without VAT", f.Litres, f.EUR)
	if usedB {
		note += fmt.Sprintf("; prices: the EU's Weekly Oil Bulletin of %s, national average pump prices without VAT (fleet cards, bulk deals and professional diesel refunds are often lower: give diesel_eur_per_l, or diesel_eur_per_l_by_country, for yours)", b.Date)
		if latest {
			note += "; the trip's week has no bulletin in this release, so the latest is used"
		}
		addSource(out, rates.Source{Title: "European Commission: Weekly Oil Bulletin", URL: fuel.URL})
	}
	if f.InPriceEUR > 0 {
		note += fmt.Sprintf(". The diesel price holds the CO2 prices on fuel (EUR %.2f here), so with_fuel_eur counts them once", f.InPriceEUR)
	}
	if !f.Complete {
		note += fmt.Sprintf(". No price for the litres bought in %s (outside the bulletin's EU countries): give diesel_eur_per_l_by_country", strings.Join(f.Unpriced, ", "))
	}
	out.Notes = append(out.Notes, note+".")
}

// runningCost adds the truck's own running costs at the rates given: the
// driver per hour of the trip and the vehicle per road km.
func runningCost(out *Response, req Request) {
	if out.Trip == nil || req.DriverEURPerH <= 0 && req.VehicleEURPerKm <= 0 {
		return
	}
	out.DriverEUR = round2(out.Trip.Hours * req.DriverEURPerH)
	out.VehicleEUR = round2(out.Trip.RoadKm * req.VehicleEURPerKm)
	base := out.TotalEUR
	if out.Fuel != nil {
		base = out.WithFuelEUR
	}
	out.TripCostEUR = round2(base + out.DriverEUR + out.VehicleEUR)
	out.Notes = append(out.Notes, fmt.Sprintf("Trip cost: the charges, the diesel and the running costs given: the driver %.2f h x EUR %g (%s), the vehicle %.1f road km x EUR %g.",
		out.Trip.Hours, req.DriverEURPerH, out.Trip.HoursBasis, out.Trip.RoadKm, req.VehicleEURPerKm))
}

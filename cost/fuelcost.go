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

// ElectricityCost is an electric truck's energy for the trip at the price
// given, without VAT.
type ElectricityCost struct {
	KWh       float64 `json:"kwh"`
	Basis     string  `json:"basis"`
	EURPerKWh float64 `json:"eur_per_kwh"`
	EUR       float64 `json:"eur"`
}

// electricityCost prices a zero-emission truck's electricity: the kWh
// used (electricity_kwh), or kwh_per_100km over the road km, at
// electricity_eur_per_kwh. There is no default: give the truck's own.
func electricityCost(out *Response, req Request) {
	if out.Trip == nil || req.Truck.CO2Class != 5 && !req.noFuel {
		return
	}
	var e ElectricityCost
	switch {
	case req.ElectricityKWh > 0 && !req.noFuel:
		e.KWh, e.Basis = req.ElectricityKWh, "electricity_kwh (given)"
	case req.KWhPer100Km > 0:
		e.KWh, e.Basis = out.Trip.RoadKm*req.KWhPer100Km/100, fmt.Sprintf("kwh_per_100km: %g (given) x %.1f road km", req.KWhPer100Km, out.Trip.RoadKm)
	}
	if e.KWh <= 0 || req.ElectricityEURPerKWh <= 0 {
		if !req.noFuel {
			out.Notes = append(out.Notes, "Electricity: not priced; give electricity_kwh or kwh_per_100km, and electricity_eur_per_kwh, for the electric truck's energy.")
		}
		return
	}
	e.KWh, e.EURPerKWh = round2(e.KWh), req.ElectricityEURPerKWh
	e.EUR = round2(e.KWh * e.EURPerKWh)
	out.Electricity = &e
	out.WithFuelEUR = round2(out.TotalEUR + e.EUR)
	if !req.noFuel {
		out.Notes = append(out.Notes, fmt.Sprintf("Electricity: %.1f kWh (%s) at EUR %g per kWh without VAT: EUR %.2f.", e.KWh, e.Basis, e.EURPerKWh, e.EUR))
	}
}

// energyPriced: the truck's energy, diesel or electricity, has a price,
// so with_fuel_eur is set.
func energyPriced(out *Response) bool { return out.Fuel != nil || out.Electricity != nil }

// energyComplete: every litre or kWh has a price.
func energyComplete(out *Response) bool {
	return out.Fuel != nil && out.Fuel.Complete || out.Electricity != nil
}

// energyEUR is the truck's energy at its price.
func energyEUR(out *Response) float64 {
	switch {
	case out.Fuel != nil:
		return out.Fuel.EUR
	case out.Electricity != nil:
		return out.Electricity.EUR
	}
	return 0
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
	if energyPriced(out) {
		base = out.WithFuelEUR
	}
	out.TripCostEUR = round2(base + out.DriverEUR + out.VehicleEUR)
	var parts []string
	if req.DriverEURPerH > 0 {
		parts = append(parts, fmt.Sprintf("the driver %.2f h x EUR %g (%s)", out.Trip.Hours, req.DriverEURPerH, out.Trip.HoursBasis))
	}
	if req.VehicleEURPerKm > 0 {
		parts = append(parts, fmt.Sprintf("the vehicle %.1f road km x EUR %g", out.Trip.RoadKm, req.VehicleEURPerKm))
	}
	out.Notes = append(out.Notes, "Trip cost: the charges, the energy and the running costs given: "+strings.Join(parts, ", ")+".")
}

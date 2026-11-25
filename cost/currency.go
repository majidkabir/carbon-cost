package cost

import (
	"fmt"
	"regexp"
	"time"

	"github.com/majidkabir/carbon-cost/fx"
)

// InCurrency is the trip's amounts in another currency (Request.Currency),
// at the rate the charges in that currency are converted at: fx given,
// the ERM II central rate for DKK, else the ECB's reference rate of the
// trip's date (a national central bank's for RSD and ALL).
type InCurrency struct {
	// Currency is the request's currency, PerEUR its units per euro, and
	// Rate where that rate comes from (the ECB's of the day, a central
	// bank's, or given in fx).
	Currency string  `json:"currency"`
	PerEUR   float64 `json:"per_eur"`
	Rate     string  `json:"rate"`
	// Total, Carbon, WithFuel and TripCost are total_eur, carbon_eur,
	// with_fuel_eur and trip_cost_eur in the currency.
	Total    float64 `json:"total"`
	Carbon   float64 `json:"carbon"`
	WithFuel float64 `json:"with_fuel,omitempty"`
	TripCost float64 `json:"trip_cost,omitempty"`
}

var currencyCode = regexp.MustCompile(`^[A-Z]{3}$`)

// currencyRate is cur per euro, and where the rate comes from: as the
// charges in cur are converted.
func currencyRate(req Request, cur string, date time.Time) (float64, string, error) {
	if v := req.FX[cur]; v > 0 {
		return v, "request", nil
	}
	if cur == "DKK" {
		if req.DKKPerEUR > 0 {
			return req.DKKPerEUR, "request", nil
		}
		return DKKPerEUR, "ERM II central rate", nil
	}
	if v := req.ecb.PerEUR[cur]; v > 0 {
		return v, fmt.Sprintf("%s, %s", fx.Source, req.ecb.Date), nil
	}
	if v, day, src, ok := fx.NationalOnDate(cur, date); ok {
		return v, fmt.Sprintf("%s, %s", src, day), nil
	}
	return 0, "", fmt.Errorf("currency %s: no exchange rate; give fx.%s (%s per euro)", cur, cur, cur)
}

// convert gives the trip's totals, and each shipment's, in req.Currency.
func convert(out *Response, req Request, date time.Time) error {
	if req.Currency == "" || req.Currency == "EUR" {
		return nil
	}
	v, basis, err := currencyRate(req, req.Currency, date)
	if err != nil {
		return err
	}
	r := func(eur float64) float64 { return round2(eur * v) }
	c := &InCurrency{Currency: req.Currency, PerEUR: v, Rate: basis, Total: r(out.TotalEUR), Carbon: r(out.CarbonEUR)}
	if energyPriced(out) {
		c.WithFuel = r(out.WithFuelEUR)
	}
	if out.TripCostEUR > 0 {
		c.TripCost = r(out.TripCostEUR)
	}
	out.InCurrency = c
	for i := range out.Shipments {
		out.Shipments[i].TotalInCurrency = r(out.Shipments[i].TotalEUR)
	}
	out.Notes = append(out.Notes, fmt.Sprintf("In %s: %.2f, at %g %s per euro (%s).", req.Currency, c.Total, v, req.Currency, basis))
	return nil
}

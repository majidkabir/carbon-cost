package cost

import (
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/sootcase"
)

// RouteOption is one route of the trip, priced: Sootcase's primary or one
// of its alternatives.
type RouteOption struct {
	// ID is "primary", or the alternative's ("alt1"; "leg2:alt1" on a trip
	// with stops: the second leg's first other route).
	ID string `json:"id"`
	// Chosen is the route this answer prices.
	Chosen bool `json:"chosen,omitempty"`
	// Roads and Ferries tell it apart: its main roads (OSM refs) and the
	// ferries it takes, as Sootcase names them.
	Roads   []string `json:"roads,omitempty"`
	Ferries []string `json:"ferries,omitempty"`
	// DistanceKm, FerryKm and CountryKm are the route's km, its km on
	// ferries, and its km by country.
	DistanceKm float64            `json:"distance_km"`
	FerryKm    float64            `json:"ferry_km,omitempty"`
	CountryKm  map[string]float64 `json:"country_km"`
	// Hours is the trip's driving time on it (Trip.Hours).
	Hours float64 `json:"hours,omitempty"`
	// TotalEUR and CarbonEUR are its charges and their carbon part
	// (Response.TotalEUR, Response.CarbonEUR).
	TotalEUR  float64 `json:"total_eur"`
	CarbonEUR float64 `json:"carbon_eur"`
	// WithFuelEUR is the charges and the diesel (Response.WithFuelEUR);
	// TripCostEUR adds the running costs given.
	WithFuelEUR float64 `json:"with_fuel_eur,omitempty"`
	TripCostEUR float64 `json:"trip_cost_eur,omitempty"`
	// runningEUR is the driver's and the vehicle's cost in TripCostEUR.
	runningEUR float64
	// Complete is false when its total leaves out charges it meets
	// (Response.Complete).
	Complete bool `json:"complete"`
	// DiffEUR is its cost less the primary's: with_fuel_eur where every
	// route's diesel has a price, else total_eur, and the running costs
	// given (driver and vehicle).
	DiffEUR float64 `json:"diff_eur"`
	// Error says why it couldn't be priced.
	Error string `json:"error,omitempty"`
}

// MaxRoutes is the most routes a trip's alternatives are priced on.
const MaxRoutes = 10

type variant struct {
	id  string
	res sootcase.Result
}

// variants are the routes of a result with alternatives: the primary, and
// each leg's other routes with the rest of the trip as the primary.
func variants(res sootcase.Result) []variant {
	prim := res
	prim.Legs = make([]sootcase.LegResult, len(res.Legs))
	for i, l := range res.Legs {
		l.Alternatives = nil
		prim.Legs[i] = l
	}
	out := []variant{{"primary", prim}}
	for i, l := range res.Legs {
		for k, a := range l.Alternatives {
			if len(out) == MaxRoutes {
				return out
			}
			v := prim
			v.Legs = slices.Clone(prim.Legs)
			a.Alternatives = nil
			v.Legs[i] = a
			v.TTWKg, v.WTWKg = 0, 0
			for _, x := range v.Legs {
				v.TTWKg += x.TTWKg
				v.WTWKg += x.WTWKg
			}
			id := a.ID
			if id == "" {
				id = fmt.Sprintf("alt%d", k+1)
			}
			if len(res.Legs) > 1 {
				id = fmt.Sprintf("leg%d:%s", i+1, id)
			}
			out = append(out, variant{id, v})
		}
	}
	return out
}

// routeCost is what routes are compared by: the charges and the diesel,
// or the charges where a diesel price is missing on a route (withFuel
// false), and the running costs given.
func routeCost(o RouteOption, withFuel bool) float64 {
	base := o.TotalEUR
	if withFuel {
		base = o.WithFuelEUR
	}
	return base + o.runningEUR
}

// priceRoutes prices the trip on each of its routes and answers for the
// one asked for (req.Route), with routes listing them all.
func (c Calculator) priceRoutes(res sootcase.Result, req *Request, date time.Time) (Response, error) {
	vs := variants(res)
	opts := make([]RouteOption, len(vs))
	outs := make([]*Response, len(vs))
	reqs := make([]Request, len(vs))
	errs := make([]error, len(vs)) // kept for their kind (Sootcase failing: a bad gateway)
	for i, v := range vs {
		r := *req
		r.CompareCO2Classes = nil // the chosen one's comparison only
		out, err := c.priceRoute(v.res, &r, date)
		o := RouteOption{ID: v.id, CountryKm: map[string]float64{}}
		for _, l := range v.res.Legs {
			if l.Summary != nil {
				for _, rd := range l.Summary.Roads {
					if !slices.Contains(o.Roads, rd) {
						o.Roads = append(o.Roads, rd)
					}
				}
				for _, f := range l.Summary.Ferries {
					name := f.Name
					if name == "" {
						name = strings.Trim(f.From+"–"+f.To, "–")
					}
					o.Ferries = append(o.Ferries, name)
				}
			}
		}
		if err != nil {
			o.Error = err.Error()
			opts[i], errs[i] = o, err
			continue
		}
		o.DistanceKm, o.FerryKm, o.CountryKm = out.DistanceKm, out.FerryKm, out.CountryKm
		o.TotalEUR, o.CarbonEUR, o.WithFuelEUR, o.TripCostEUR, o.Complete = out.TotalEUR, out.CarbonEUR, out.WithFuelEUR, out.TripCostEUR, out.Complete
		o.runningEUR = out.DriverEUR + out.VehicleEUR
		if out.Trip != nil {
			o.Hours = out.Trip.Hours
		}
		if len(o.Ferries) == 0 && out.FerryCrossing != "" {
			o.Ferries = strings.Split(out.FerryCrossing, ", ")
		}
		opts[i], outs[i], reqs[i] = o, &out, r
	}
	if outs[0] == nil {
		return Response{}, fmt.Errorf("the primary route: %w", errs[0])
	}
	// Compared with the diesel where every route has its price.
	withFuel := true
	for i := range opts {
		if outs[i] != nil && !energyComplete(outs[i]) {
			withFuel = false
		}
	}
	for i := range opts {
		if outs[i] != nil {
			opts[i].DiffEUR = round2(routeCost(opts[i], withFuel) - routeCost(opts[0], withFuel))
		}
	}
	pick := 0
	switch {
	case req.Route == "cheapest":
		for i := range opts {
			if outs[i] == nil {
				continue
			}
			better := opts[i].Complete && !opts[pick].Complete ||
				opts[i].Complete == opts[pick].Complete && routeCost(opts[i], withFuel) < routeCost(opts[pick], withFuel)
			if better {
				pick = i
			}
		}
	case req.Route != "" && req.Route != "primary":
		pick = slices.IndexFunc(opts, func(o RouteOption) bool { return o.ID == req.Route })
		if pick < 0 {
			var ids []string
			for _, o := range opts {
				ids = append(ids, o.ID)
			}
			return Response{}, fmt.Errorf("route %q: this trip's routes are %s", req.Route, strings.Join(ids, ", "))
		}
		if outs[pick] == nil {
			return Response{}, fmt.Errorf("route %s: %w", req.Route, errs[pick])
		}
	}
	opts[pick].Chosen = true
	out := *outs[pick]
	if len(req.CompareCO2Classes) > 0 {
		r := *req
		o, err := c.priceRoute(vs[pick].res, &r, date)
		if err != nil {
			return Response{}, err
		}
		out = o
		reqs[pick] = r
	}
	*req = reqs[pick]
	out.Routes = opts
	desc := func(o RouteOption) string {
		s := o.ID
		if len(o.Ferries) > 0 {
			s += " (ferry " + strings.Join(o.Ferries, ", ") + ")"
		} else {
			s += " (no ferry)"
		}
		return s
	}
	note := fmt.Sprintf("Routes: %d priced; this is %s", len(opts), desc(opts[pick]))
	if req.Route == "cheapest" {
		// The truck's energy: an electric truck's electricity.
		energy := "diesel"
		if o := outs[pick]; o != nil && (o.Electricity != nil || o.Fuel == nil && req.Truck.CO2Class == 5) {
			energy = "electricity"
		}
		what := "charges and " + energy
		switch running := req.DriverEURPerH > 0 || req.VehicleEURPerKm > 0; {
		case running && withFuel:
			what = "trip cost (charges, " + energy + ", driver and vehicle)"
		case running:
			what = "charges, driver and vehicle (the " + energy + " isn't priced on every route: see its note)"
		case !withFuel:
			what = "charges (the " + energy + " isn't priced on every route: see its note)"
		}
		note += ", the cheapest by " + what
	}
	if len(opts) == 1 {
		note += "; Sootcase found no other route that differs enough (it shares less than 80% of its length, or takes other ferries) and is at most 1.5 times as long"
	}
	out.Notes = append(out.Notes, note+". Set route to a route's id to price that one.")
	return out, nil
}

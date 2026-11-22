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
	Roads      []string           `json:"roads,omitempty"`
	Ferries    []string           `json:"ferries,omitempty"`
	DistanceKm float64            `json:"distance_km"`
	FerryKm    float64            `json:"ferry_km,omitempty"`
	CountryKm  map[string]float64 `json:"country_km"`
	// Hours is the trip's driving time on it (Trip.Hours).
	Hours     float64 `json:"hours,omitempty"`
	TotalEUR  float64 `json:"total_eur"`
	CarbonEUR float64 `json:"carbon_eur"`
	// WithFuelEUR is the charges and the diesel (Response.WithFuelEUR);
	// TripCostEUR adds the running costs given.
	WithFuelEUR float64 `json:"with_fuel_eur,omitempty"`
	TripCostEUR float64 `json:"trip_cost_eur,omitempty"`
	Complete    bool    `json:"complete"`
	// DiffEUR is its cost less the primary's: trip_cost_eur with running
	// costs given, else with_fuel_eur where all have it, else total_eur.
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

// routeCost is what routes are compared by: the trip cost with the
// running costs given, else the charges and the diesel, or the charges
// where a diesel price is missing.
func routeCost(o RouteOption, withFuel bool) float64 {
	switch {
	case o.TripCostEUR > 0:
		return o.TripCostEUR
	case withFuel:
		return o.WithFuelEUR
	}
	return o.TotalEUR
}

// priceRoutes prices the trip on each of its routes and answers for the
// one asked for (req.Route), with routes listing them all.
func (c Calculator) priceRoutes(res sootcase.Result, req *Request, date time.Time) (Response, error) {
	vs := variants(res)
	opts := make([]RouteOption, len(vs))
	outs := make([]*Response, len(vs))
	reqs := make([]Request, len(vs))
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
			opts[i] = o
			continue
		}
		o.DistanceKm, o.FerryKm, o.CountryKm = out.DistanceKm, out.FerryKm, out.CountryKm
		o.TotalEUR, o.CarbonEUR, o.WithFuelEUR, o.TripCostEUR, o.Complete = out.TotalEUR, out.CarbonEUR, out.WithFuelEUR, out.TripCostEUR, out.Complete
		if out.Trip != nil {
			o.Hours = out.Trip.Hours
		}
		if len(o.Ferries) == 0 && out.FerryCrossing != "" {
			o.Ferries = strings.Split(out.FerryCrossing, ", ")
		}
		opts[i], outs[i], reqs[i] = o, &out, r
	}
	if outs[0] == nil {
		return Response{}, fmt.Errorf("the primary route: %s", opts[0].Error)
	}
	// Compared with the diesel where every route has its price.
	withFuel := true
	for i := range opts {
		if outs[i] != nil && (outs[i].Fuel == nil || !outs[i].Fuel.Complete) {
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
			return Response{}, fmt.Errorf("route %s: %s", req.Route, opts[pick].Error)
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
		what := "charges and diesel"
		if req.DriverEURPerH > 0 || req.VehicleEURPerKm > 0 {
			what = "trip cost (charges, diesel, driver and vehicle)"
		} else if !withFuel {
			what = "charges (a diesel price is missing)"
		}
		note += ", the cheapest by " + what
	}
	if len(opts) == 1 {
		note += "; Sootcase found no other route that differs enough (it shares less than 80% of its length, or takes other ferries) and is at most 1.5 times as long"
	}
	out.Notes = append(out.Notes, note+". Give route with a route's id to price that one.")
	return out, nil
}

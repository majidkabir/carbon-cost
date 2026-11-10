// Package cost works out what carbon and road charges a truck trip pays:
// km-based road tolls per country (with their CO2 part shown apart), the
// EU ETS on ferry crossings, and ETS2 on road fuel from 2028.
//
// Distances by country and emissions come from Sootcase; rates come from
// the official tables in package rates. Nothing here is fitted to data:
// every number is a published rate, a price the user gives, or Sootcase's
// GLEC/ISO 14083 result.
package cost

import (
	"context"
	"fmt"
	"math"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/fx"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/sootcase/pkg/borders"
)

// DefaultVehicleType is Sootcase's GLEC vehicle type used when the request
// names none: an articulated 34-40 t diesel truck.
const DefaultVehicleType = "glec/road/eu_sa/artic_34_40t/diesel"

// DKKPerEUR is the euro central rate of the Danish krone in ERM II, the
// default for converting DKK amounts to EUR.
const DKKPerEUR = 7.46038

// Charge kinds.
const (
	RoadToll = "road_toll"
	FerryETS = "ferry_ets"
	ETS2     = "ets2"
)

// ETS2Start is when ETS2 covers road transport fuel.
var ETS2Start = time.Date(2028, 1, 1, 0, 0, 0, 0, time.UTC)

// Request is a trip to price.
type Request struct {
	From sootcase.Location `json:"from"`
	To   sootcase.Location `json:"to"`
	Date string            `json:"date,omitempty"` // YYYY-MM-DD; default today
	// Time is the local departure time (HH:MM) on Date. Each toll station
	// is reached that much later as its km along the route take at
	// AvgSpeedKmh; that time prices congestion taxes and the hours a
	// toll system or station is free. Without it congestion taxes aren't
	// priced and hours aren't checked.
	Time string `json:"time,omitempty"`
	// AvgSpeedKmh is the average speed for those times, default
	// DefaultAvgSpeedKmh.
	AvgSpeedKmh float64 `json:"avg_speed_kmh,omitempty"`
	// DriverRest adds a single driver's breaks and daily rests to those
	// times (Regulation (EC) No 561/2006, Arts. 7 and 8): 45 minutes after
	// 4.5 hours' driving, 11 hours after 9.
	DriverRest  bool        `json:"driver_rest,omitempty"`
	CargoKg     float64     `json:"cargo_kg"`
	VehicleType string      `json:"vehicle_type,omitempty"`
	Truck       rates.Truck `json:"truck"`
	// TolledShare is the share of each country's km on tolled roads,
	// default 1 (all of it). Sootcase doesn't yet tell road classes apart,
	// so give it when part of a trip runs on untolled roads.
	TolledShare map[string]float64 `json:"tolled_share,omitempty"`
	// ETC: the truck pays tolls by an electronic toll device or account
	// agreement, for the operators' discounts on it (Croatia's ENC,
	// Storebælt Erhverv, ØresundBUSINESS).
	ETC bool `json:"etc,omitempty"`
	// Night: the trip passes night-tariff sections between 22:00 and
	// 05:00 (Austria's A 13 Brenner).
	Night bool `json:"night,omitempty"`
	// MotorwayShare is the share of an area's tolled km on motorways
	// (default 0), where its rates differ by road type (Brussels).
	MotorwayShare map[string]float64 `json:"motorway_share,omitempty"`
	// EnvZoneKm is km driven on tolled roads inside environmental zones,
	// by country (Denmark charges a surcharge there).
	EnvZoneKm map[string]float64 `json:"env_zone_km,omitempty"`
	// EUAEurPerT is the EU ETS allowance price (EUR per t CO2e), for
	// ferry crossings. 0: ferry ETS is not priced.
	EUAEurPerT float64 `json:"eua_eur_per_t,omitempty"`
	// FerryETSShare is the share of a crossing's emissions under the EU
	// ETS: 1 between two EU/EEA ports (default), 0.5 to or from a port
	// outside.
	FerryETSShare float64 `json:"ferry_ets_share,omitempty"`
	// ETS2EurPerT is the ETS2 allowance price (EUR per t CO2e), for trips
	// from 2028. 0: ETS2 is not priced.
	ETS2EurPerT float64 `json:"ets2_eur_per_t,omitempty"`
	// DKKPerEUR converts DKK to EUR; default DKKPerEUR.
	DKKPerEUR float64 `json:"dkk_per_eur,omitempty"`
	// FX converts other currencies to EUR, in units per euro, e.g.
	// {"CHF": 0.93}; default the ECB reference rates (Calculator.FX).
	FX map[string]float64 `json:"fx,omitempty"`

	ecb fx.Rates // set by Calculate from Calculator.FX
	// roadKm is each country's route km by road class, set by Calculate
	// from Calculator.Roads.
	roadKm map[string]roads.Km
	// roadOSM is the OSM extract date of each country's road classes.
	roadOSM map[string]string
	// spans are each country's stretches of the route, as [from, to] km
	// along it, set by Calculate from the route split by country.
	spans map[string][][2]float64
	// origin is the country the trip starts in, whose local time Time
	// is (set by Calculate; "" takes each station's country).
	origin string
	// CompareCO2Classes prices the same trip for trucks in these CO2
	// classes (e.g. [1, 4, 5]), otherwise the same as Truck.
	CompareCO2Classes []int `json:"compare_co2_classes,omitempty"`
	// TripsPerYear turns the comparison's savings per trip into savings
	// per year.
	TripsPerYear float64 `json:"trips_per_year,omitempty"`
}

// Comparison is the trip priced for a truck in another CO2 class.
type Comparison struct {
	CO2Class  int     `json:"co2_class"`
	TollEUR   float64 `json:"road_toll_eur"`
	TotalEUR  float64 `json:"total_eur"`
	CarbonEUR float64 `json:"carbon_eur"`
	// SavingEUR is what this truck saves per trip against the requested
	// one (negative: it costs more).
	SavingEUR        float64 `json:"saving_eur"`
	SavingPerYearEUR float64 `json:"saving_per_year_eur,omitempty"`
}

// Line is one charge.
type Line struct {
	Charge string `json:"charge"`
	// Days is the days a time-based charge is paid for.
	Days      int     `json:"days,omitempty"`
	Country   string  `json:"country,omitempty"`
	Region    string  `json:"region,omitempty"`  // ISO 3166-2, for regional tolls
	Road      string  `json:"road,omitempty"`    // motorway or other, where rates differ by road
	Section   string  `json:"section,omitempty"` // a fixed-charge section or a surcharged stretch
	Area      string  `json:"area,omitempty"`    // suburban or interurban, where rates differ by it
	Component string  `json:"component,omitempty"`
	Carbon    bool    `json:"carbon"` // a charge on CO2
	Km        float64 `json:"km,omitempty"`
	TonnesCO2 float64 `json:"t_co2e,omitempty"`
	Tonnes    float64 `json:"tonnes,omitempty"` // chargeable weight, for rates per tonne-km
	Rate      float64 `json:"rate"`
	RateUnit  string  `json:"rate_unit"` // e.g. "DKK/km", "CHF/tkm", "EUR/t CO2e"
	Currency  string  `json:"currency"`
	Amount    float64 `json:"amount"`
	AmountEUR float64 `json:"amount_eur"`
	Source    string  `json:"source"`
	// Sources link the documents the line's rate comes from.
	Sources []rates.Source `json:"sources,omitempty"`
}

// Response is a priced trip.
type Response struct {
	Date       string  `json:"date"`
	DistanceKm float64 `json:"distance_km"`
	FerryKm    float64 `json:"ferry_km,omitempty"`
	// FerryCrossing is the crossing the route uses, when recognised.
	FerryCrossing string             `json:"ferry_crossing,omitempty"`
	CountryKm     map[string]float64 `json:"country_km"`
	RegionKm      map[string]float64 `json:"region_km,omitempty"`
	TTWKg         float64            `json:"ttw_kg"`
	WTWKg         float64            `json:"wtw_kg"`
	Lines         []Line             `json:"lines"`
	TotalEUR      float64            `json:"total_eur"`
	CarbonEUR     float64            `json:"carbon_eur"` // the CO2 parts of tolls, ferry ETS and ETS2
	// NoRates lists countries on the route this tool has no toll table
	// for: their charges are not included.
	NoRates []string `json:"no_rates,omitempty"`
	// Compare is the trip priced for each of CompareCO2Classes.
	Compare []Comparison   `json:"compare,omitempty"`
	Notes   []string       `json:"notes,omitempty"`
	Sources []rates.Source `json:"sources"`
	// Route is the route split by country, for a map (Calculate with
	// Borders set).
	Route []Run `json:"route,omitempty"`
	// Provenance names the data and assumptions the result rests on.
	Provenance Provenance `json:"provenance"`
}

// Provenance is what a result was calculated from: enough to repeat it.
type Provenance struct {
	// Version is this tool's release (Calculator.Version).
	Version string `json:"carbon_cost_version,omitempty"`
	// Sootcase is the Sootcase server and its emission factor dataset.
	Sootcase string `json:"sootcase,omitempty"`
	// Tables are the rate tables priced, with their data files.
	Tables []TableUsed `json:"tables,omitempty"`
	// RoadClasses is the OpenStreetMap extract date of the road classes
	// used, by country.
	RoadClasses map[string]string `json:"road_classes_osm,omitempty"`
	// FerryMRV is the EU MRV publication a ferry crossing's emissions
	// come from.
	FerryMRV string `json:"ferry_mrv,omitempty"`
	// FX is the exchange rates used.
	FX []string `json:"fx,omitempty"`
	// Assumed lists defaults taken where the request didn't say.
	Assumed []string `json:"assumed,omitempty"`
}

// TableUsed is a rate table a result used.
type TableUsed struct {
	Name       string `json:"name"`
	Area       string `json:"area"`
	ValidFrom  string `json:"valid_from"`
	ValidTo    string `json:"valid_to,omitempty"`
	File       string `json:"file,omitempty"`
	OSMExtract string `json:"osm_extract,omitempty"`
}

// Calculator prices trips.
type Calculator struct {
	Sootcase sootcase.Client
	Tables   []rates.Table
	Ferries  *ferries.Data  // nil: ferry crossings use Sootcase's default
	Borders  *borders.Index // nil: no Route in the response
	// Roads tells motorway, national and local km apart (with Borders);
	// nil: motorway_share and tolled_share decide.
	Roads *roads.Index
	// FX gives exchange rates for currencies the request has no fx for;
	// nil: those need fx in the request.
	FX func(context.Context) (fx.Rates, error)
	// FXOn gives the rates of a past day (fx.OnDate); a trip on a day it
	// has uses them, other trips FX.
	FXOn func(time.Time) (fx.Rates, bool)
	Now  func() time.Time // default time.Now
	// Version is the release, for the response's provenance.
	Version string
}

// Calculate routes the trip with Sootcase and prices it.
func (c Calculator) Calculate(ctx context.Context, req Request) (Response, error) {
	date, err := c.date(req.Date)
	if err != nil {
		return Response{}, err
	}
	if err := check(req); err != nil {
		return Response{}, err
	}
	vt := req.VehicleType
	var assumed []string
	if req.Date == "" {
		assumed = append(assumed, "date: today ("+date.Format(time.DateOnly)+")")
	}
	if vt == "" {
		vt = DefaultVehicleType
		assumed = append(assumed, "vehicle_type: "+vt)
	}
	if c.FXOn != nil {
		if r, ok := c.FXOn(date); ok {
			req.ecb = r
		}
	}
	if req.ecb.Date == "" && c.FX != nil {
		if r, err := c.FX(ctx); err == nil {
			req.ecb = r
		}
	}
	no := false
	res, err := c.Sootcase.Calculate(ctx, sootcase.Shipment{ID: "trip", WeightKg: req.CargoKg, AddRoadLegs: &no,
		Legs: []sootcase.Leg{{ID: "road", Mode: "road", VehicleType: vt, From: req.From, To: req.To}}})
	if err != nil {
		return Response{}, err
	}
	var runs []Run
	if c.Borders != nil {
		var path [][2]float64
		for _, l := range res.Legs {
			path = append(path, l.Path...)
		}
		runs = Route(c.Borders, path, c.Ferries)
		req.spans = Spans(runs)
		for _, r := range runs {
			if r.Kind == "road" && r.Country != "" {
				req.origin = r.Country
				break
			}
		}
		if c.Roads != nil {
			req.roadKm = RoadKm(c.Roads, runs)
			req.roadOSM = map[string]string{}
			for cc := range req.roadKm {
				req.roadOSM[cc] = c.Roads.Extract(cc)
			}
		}
	}
	out, err := PriceWith(res, c.Tables, c.Ferries, req, date)
	if err != nil {
		return out, err
	}
	out.Route = thinRuns(runs, MapPoints)
	out.Provenance.Version = c.Version
	base := c.Sootcase.BaseURL
	if base == "" {
		base = sootcase.DefaultURL
	}
	out.Provenance.Sootcase = strings.TrimRight(base, "/")
	if res.Dataset != "" {
		out.Provenance.Sootcase += ", factors: " + res.Dataset
	}
	if req.Time != "" && req.origin != "" {
		assumed = append(assumed, fmt.Sprintf("time: %s local time in %s, where the trip starts; stations use their own country's time", req.Time, req.origin))
	}
	out.Provenance.Assumed = append(assumed, out.Provenance.Assumed...)
	return out, nil
}

func (c Calculator) date(s string) (time.Time, error) {
	if s == "" {
		now := time.Now
		if c.Now != nil {
			now = c.Now
		}
		y, m, d := now().Date()
		return time.Date(y, m, d, 0, 0, 0, 0, time.UTC), nil
	}
	t, err := time.Parse(time.DateOnly, s)
	if err != nil {
		return time.Time{}, fmt.Errorf("date must be YYYY-MM-DD")
	}
	return t, nil
}

func check(req Request) error {
	if err := req.Truck.Validate(); err != nil {
		return fmt.Errorf("truck: %w", err)
	}
	if req.CargoKg <= 0 {
		return fmt.Errorf("cargo_kg must be > 0")
	}
	if req.Time != "" {
		if err := rates.ValidTime(req.Time); err != nil {
			return fmt.Errorf("time: %w", err)
		}
	}
	if req.AvgSpeedKmh < 0 || req.AvgSpeedKmh > 130 {
		return fmt.Errorf("avg_speed_kmh must be 0-130")
	}
	for k, v := range req.TolledShare {
		if v < 0 || v > 1 {
			return fmt.Errorf("tolled_share[%s] must be 0-1", k)
		}
	}
	for k, v := range req.MotorwayShare {
		if v < 0 || v > 1 {
			return fmt.Errorf("motorway_share[%s] must be 0-1", k)
		}
	}
	for k, v := range req.FX {
		if v <= 0 {
			return fmt.Errorf("fx.%s must be > 0 (units per euro)", k)
		}
	}
	for k, v := range req.EnvZoneKm {
		if v < 0 {
			return fmt.Errorf("env_zone_km[%s] must be >= 0", k)
		}
	}
	for _, c := range req.CompareCO2Classes {
		if c < 1 || c > 5 {
			return fmt.Errorf("compare_co2_classes must be 1-5")
		}
	}
	if req.TripsPerYear < 0 {
		return fmt.Errorf("trips_per_year must be >= 0")
	}
	if req.EUAEurPerT < 0 || req.ETS2EurPerT < 0 || req.DKKPerEUR < 0 || req.FerryETSShare < 0 || req.FerryETSShare > 1 {
		return fmt.Errorf("prices, rates and shares can't be negative (ferry_ets_share is 0-1)")
	}
	return nil
}

// Price prices a trip from Sootcase's result, with ferry crossings at
// Sootcase's default factor.
func Price(res sootcase.Result, tables []rates.Table, req Request, date time.Time) (Response, error) {
	return PriceWith(res, tables, nil, req, date)
}

// PriceWith prices a trip from Sootcase's result; a recognised ferry
// crossing uses its ships' MRV data from fd when the truck's tare is
// given.
func PriceWith(res sootcase.Result, tables []rates.Table, fd *ferries.Data, req Request, date time.Time) (Response, error) {
	if err := check(req); err != nil {
		return Response{}, err
	}
	if len(res.Legs) == 0 {
		return Response{}, fmt.Errorf("sootcase returned no legs")
	}
	out := Response{Date: date.Format(time.DateOnly), CountryKm: map[string]float64{}, TTWKg: res.TTWKg, WTWKg: res.WTWKg}
	var ferryTTW float64
	routed := false
	for _, l := range res.Legs {
		out.DistanceKm += l.DistanceKm
		out.FerryKm += l.RouteParts["ferry"]
		for k, v := range l.CountryKm {
			out.CountryKm[k] += v
			routed = true
		}
		for k, v := range l.RegionKm {
			if out.RegionKm == nil {
				out.RegionKm = map[string]float64{}
			}
			out.RegionKm[k] += v
		}
		for _, p := range l.Parts {
			if p.Kind == "ferry" {
				ferryTTW += p.TTWKg
			}
		}
	}
	if !routed {
		return Response{}, fmt.Errorf("sootcase returned no distance by country: the server needs Sootcase v0.9.0 or later (country_km)")
	}
	for _, w := range res.Warnings {
		out.Notes = append(out.Notes, "Sootcase: "+w)
	}
	if req.Time != "" {
		if req.AvgSpeedKmh == 0 {
			out.Provenance.Assumed = append(out.Provenance.Assumed, fmt.Sprintf("avg_speed_kmh: %d (station passage times)", DefaultAvgSpeedKmh))
		}
		if req.DriverRest {
			out.Provenance.Assumed = append(out.Provenance.Assumed, "driver_rest: one driver, 45 min break after 4.5 h and 11 h rest after 9 h driving (Regulation (EC) No 561/2006)")
		}
	}
	seenTable := map[string]bool{}
	useTable := func(tb rates.Table) {
		k := tb.File + tb.Area() + tb.ValidFrom
		if seenTable[k] {
			return
		}
		seenTable[k] = true
		out.Provenance.Tables = append(out.Provenance.Tables, TableUsed{Name: tb.Name, Area: tb.Area(), ValidFrom: tb.ValidFrom,
			ValidTo: tb.ValidTo, File: tb.File, OSMExtract: tb.OSMExtract})
	}
	seenFX := map[string]bool{}
	eurPer := map[string]float64{"EUR": 1, "DKK": 1 / DKKPerEUR}
	if req.DKKPerEUR > 0 {
		eurPer["DKK"] = 1 / req.DKKPerEUR
	}
	for c, v := range req.FX {
		if v > 0 {
			eurPer[c] = 1 / v
		}
	}
	var lineSrc []rates.Source // the sources of the table being priced
	add := func(l Line) error {
		if l.Sources == nil {
			l.Sources = lineSrc
		}
		f, ok := eurPer[l.Currency]
		if ok && l.Currency != "EUR" && !seenFX[l.Currency] {
			seenFX[l.Currency] = true
			switch v, given := req.FX[l.Currency]; {
			case given && v > 0:
				out.Provenance.FX = append(out.Provenance.FX, fmt.Sprintf("%s: %g per EUR (request)", l.Currency, v))
			case l.Currency == "DKK" && req.DKKPerEUR > 0:
				out.Provenance.FX = append(out.Provenance.FX, fmt.Sprintf("DKK: %g per EUR (request)", req.DKKPerEUR))
			case l.Currency == "DKK":
				out.Provenance.FX = append(out.Provenance.FX, fmt.Sprintf("DKK: %g per EUR (ERM II central rate)", DKKPerEUR))
			}
		}
		if !ok {
			v := req.ecb.PerEUR[l.Currency]
			if v == 0 {
				return fmt.Errorf("no exchange rate for %s: give fx.%s (%s per euro)", l.Currency, l.Currency, l.Currency)
			}
			f = 1 / v
			eurPer[l.Currency] = f
			seenFX[l.Currency] = true
			out.Provenance.FX = append(out.Provenance.FX, fmt.Sprintf("%s: %g per EUR (%s, %s)", l.Currency, v, fx.Source, req.ecb.Date))
			out.Notes = append(out.Notes, fmt.Sprintf("%s converted at %g %s per euro (%s, %s); give fx.%s to use another rate.",
				l.Currency, v, l.Currency, fx.Source, req.ecb.Date, l.Currency))
		}
		l.Amount = round2(l.Amount)
		l.AmountEUR = round2(l.Amount * f)
		out.Lines = append(out.Lines, l)
		out.TotalEUR += l.AmountEUR
		if l.Carbon {
			out.CarbonEUR += l.AmountEUR
		}
		return nil
	}
	seenSrc := map[string]bool{}
	addSources := func(ss []rates.Source) {
		for _, s := range ss {
			if !seenSrc[s.URL] {
				seenSrc[s.URL] = true
				out.Sources = append(out.Sources, s)
			}
		}
	}

	var path [][2]float64
	for _, l := range res.Legs {
		path = append(path, l.Path...)
	}
	route := newTrack(path)
	// Road tolls, area by area: countries, or their regions where tolls
	// are set by region.
	for _, a := range areas(&out, tables) {
		cc, km := a.code, a.km
		tb, ok := rates.Find(tables, a.code, date)
		lineSrc = tb.Sources
		if !ok {
			if km >= 0.5 {
				out.NoRates = append(out.NoRates, a.code)
			}
			continue
		}
		share, shareGiven := 1.0, false
		for _, k := range []string{a.code, a.country} {
			if v, ok := req.TolledShare[k]; ok {
				share, shareGiven = v, true
				break
			}
		}
		tolledKm := km * share
		// Road classes along the route, where the rates differ by road:
		// motorway km at the motorway rate, other national roads at the
		// other-road rate, local roads untolled.
		rk, byRoute := req.roadKm[a.country]
		byRoute = byRoute && a.region == "" && rk.Total() > 0 && len(tb.Roads()) > 0
		if byRoute && !shareGiven {
			tolledKm = km * (rk.Motorway + rk.National) / rk.Total()
		}
		useTable(tb)
		if byRoute {
			if out.Provenance.RoadClasses == nil {
				out.Provenance.RoadClasses = map[string]string{}
			}
			d := req.roadOSM[a.country]
			if d == "" {
				d = "date not recorded"
			}
			out.Provenance.RoadClasses[a.country] = "OpenStreetMap " + d
			if rk.Uncertain >= 0.5 {
				out.Notes = append(out.Notes, fmt.Sprintf("%s: %.1f km counted as untolled local roads pass within %d m of a tolled road in OpenStreetMap, so may be on it; give tolled_share.%s if they are.",
					cc, rk.Uncertain, roads.NearM, cc))
			}
		}
		rs, exempt, ok := tb.Rates(req.Truck, date)
		switch {
		case !ok:
			out.Notes = append(out.Notes, fmt.Sprintf("%s: no toll for this truck (%s).", cc, tb.Vehicles))
			continue
		case exempt != "":
			out.Notes = append(out.Notes, fmt.Sprintf("%s: %s", cc, exempt))
			addSources(tb.Sources)
			continue
		}
		addSources(tb.Sources)
		if tb.PerDay {
			if tolledKm < 0.5 {
				continue
			}
			days, note := tripDays(tb, a.country, req, date)
			for _, r := range rs {
				if r.PerKm == 0 {
					continue // e.g. Latvia's zero-emission trucks
				}
				if err := add(Line{Charge: RoadToll, Country: a.country, Region: a.region, Component: r.Component, Carbon: r.Component == rates.CO2,
					Km: round3(tolledKm), Days: days, Rate: r.PerKm, RateUnit: tb.Currency + "/day", Currency: tb.Currency,
					Amount: r.PerKm * float64(days), Source: tb.Law}); err != nil {
					return Response{}, err
				}
			}
			out.Notes = append(out.Notes, cc+": "+note)
			if tb.MotorAxles && req.Truck.MotorAxles == 0 {
				out.Notes = append(out.Notes, fmt.Sprintf("%s: the charge counts the motor vehicle's own axles; priced with the truck's %d axles. Give truck.motor_axles (e.g. 2 for a two-axle tractor).", cc, req.Truck.Axles))
			}
			continue
		}
		// Km by road type, where the rates differ by road: motorway_share
		// of the tolled km on motorways, the rest on other roads.
		type part struct {
			road string
			km   float64
		}
		parts := []part{{"", tolledKm}}
		if roads := tb.Roads(); len(roads) > 0 {
			mw, given := 0.0, false
			for _, k := range []string{a.code, a.country} {
				if v, ok := req.MotorwayShare[k]; ok {
					mw, given = v, true
					break
				}
			}
			switch {
			case given && byRoute && !shareGiven:
				out.Notes = append(out.Notes, fmt.Sprintf("%s: %.0f%% of the %.1f km are on local roads by OpenStreetMap along the route, which aren't tolled.", cc, 100*rk.Local/rk.Total(), km))
			case given:
			case byRoute:
				if t := rk.Motorway + rk.National; t > 0 {
					mw = rk.Motorway / t
				}
				out.Notes = append(out.Notes, fmt.Sprintf("%s: by OpenStreetMap along the route, %.0f%% of the %.1f km are on motorways, %.0f%% on other national roads and %.0f%% on local roads%s. Give motorway_share.%s or tolled_share.%s to override.",
					cc, 100*rk.Motorway/rk.Total(), km, 100*rk.National/rk.Total(), 100*rk.Local/rk.Total(),
					map[bool]string{true: "", false: ", which aren't tolled"}[shareGiven], cc, cc))
			default:
				mw = tb.MotorwayShare
				out.Notes = append(out.Notes, fmt.Sprintf("%s: rates differ by road type; %.0f%% of the %.1f km are priced at the motorway rate, the rest at the other-road rate. Give motorway_share.%s for the share on motorways.",
					cc, mw*100, tolledKm, cc))
			}
			parts = []part{{rates.Motorway, tolledKm * mw}, {rates.OtherRoad, tolledKm * (1 - mw)}}
		}
		// Fixed-charge sections on the route: their km pay the section
		// charge instead of the per-km infrastructure rate.
		secs, secKm := onRoute(tb, route)
		for _, pt := range parts {
			if pt.km <= 0 && pt.road != "" {
				continue
			}
			prs := rs
			if pt.road != "" {
				prs, _, _ = tb.RatesOn(req.Truck, date, pt.road)
			}
			for _, r := range prs {
				if r.PerKm == 0 {
					continue // e.g. Bulgaria's CO2 part for zero-emission trucks
				}
				km := pt.km
				if r.Component == rates.Infrastructure && secKm > 0 {
					km = math.Max(0, km-secKm)
				}
				if r.Area != "" {
					sh := suburbanShare(tb, rk, byRoute, pt.road)
					if r.Area == rates.Interurban {
						sh = 1 - sh
					}
					km *= sh
				}
				l := Line{Charge: RoadToll, Country: a.country, Region: a.region, Road: pt.road, Area: r.Area, Component: r.Component,
					Carbon: r.Component == rates.CO2, Km: round3(km), Rate: r.PerKm, RateUnit: tb.Currency + "/km", Currency: tb.Currency,
					Amount: km * r.PerKm, Source: tb.Law}
				if tb.PerTonneKm {
					l.Tonnes, l.Rate, l.RateUnit = r.Tonnes, r.PerTonneKm, tb.Currency+"/tkm"
				}
				if err := add(l); err != nil {
					return Response{}, err
				}
			}
		}
		for _, s := range secs {
			v := s.sec.Amount(req.Truck, req.Night)
			if err := add(Line{Charge: RoadToll, Country: a.country, Region: a.region, Component: rates.Infrastructure, Section: s.sec.Name,
				Km: round3(s.km), Rate: v, RateUnit: tb.Currency + "/section", Currency: tb.Currency, Amount: v, Source: tb.Sections.Law}); err != nil {
				return Response{}, err
			}
			for _, pk := range tb.Sections.PerKm {
				r, ok := pk.Rate(req.Truck, s.sec)
				if !ok || r == 0 {
					continue
				}
				km := s.sec.Km
				if km == 0 {
					km = s.km
				}
				if err := add(Line{Charge: RoadToll, Country: a.country, Region: a.region, Component: pk.Component, Section: s.sec.Name,
					Km: round3(km), Rate: r, RateUnit: tb.Currency + "/km", Currency: tb.Currency, Amount: km * r, Source: pk.Law}); err != nil {
					return Response{}, err
				}
			}
		}
		for _, sc := range tb.Surcharges {
			var km float64
			for i := 0; i+1 < len(sc.Points); i++ {
				if k, ok := along(route, sc.Points[i], sc.Points[i+1]); ok {
					km += k
				}
			}
			if km == 0 {
				continue
			}
			for _, r := range rs {
				if r.Component != sc.Component {
					continue
				}
				if err := add(Line{Charge: RoadToll, Country: a.country, Region: a.region, Component: r.Component, Section: sc.Name,
					Km: round3(km), Rate: r.PerKm * sc.Factor, RateUnit: tb.Currency + "/km", Currency: tb.Currency,
					Amount: km * r.PerKm * sc.Factor, Source: sc.Law}); err != nil {
					return Response{}, err
				}
			}
		}
		zkm := req.EnvZoneKm[a.code]
		if a.region != "" && zkm == 0 {
			zkm = req.EnvZoneKm[a.country]
		}
		if zkm > 0 {
			zr := tb.EnvZoneRate(req.Truck)
			if zr == 0 {
				out.Notes = append(out.Notes, fmt.Sprintf("%s: env_zone_km given, but %s has no environmental zone surcharge.", cc, tb.Name))
			} else if err := add(Line{Charge: RoadToll, Country: a.country, Region: a.region, Component: rates.EnvZoneSurcharge, Km: zkm, Rate: zr,
				RateUnit: tb.Currency + "/km", Currency: tb.Currency, Amount: zkm * zr, Source: tb.Law}); err != nil {
				return Response{}, err
			}
		}
		sp := spans{}
		closedAny, err := priceClosed(tb, a.country, a.region, route, req, date, &out, add, sp)
		if err != nil {
			return Response{}, err
		}
		pointsAny, err := priceTollPoints(tb, a.country, route, req, date, &out, add, sp)
		if err != nil {
			return Response{}, err
		}
		if len(tb.TollPoints) > 0 && !pointsAny && km >= 1 {
			out.Notes = append(out.Notes, fmt.Sprintf("%s: the route passes none of the toll stations.", cc))
		}
		if len(tb.Closed) > 0 && len(tb.Rows) == 0 && !closedAny && km >= 1 {
			out.Notes = append(out.Notes, fmt.Sprintf("%s: the route uses none of the tolled motorways.", cc))
		}
		if tb.Sections != nil && len(tb.Rows) == 0 && len(secs) == 0 && km >= 1 {
			out.Notes = append(out.Notes, fmt.Sprintf("%s: the route passes none of the tolled sections.", cc))
		}
		if !shareGiven && !byRoute && len(tb.Rows) > 0 {
			out.Notes = append(out.Notes, fmt.Sprintf("%s: all %.1f km are counted as on tolled roads; give tolled_share.%s if part of the trip isn't. Tolled roads: %s",
				cc, km, cc, tb.TolledRoads))
		}
	}

	// Fixed-charge crossings (bridges) wherever the route passes them.
	for _, tb := range tables {
		if !tb.Crossings || !tb.Covers(date) || req.Truck.MaxMassKg < tb.MinKg {
			continue
		}
		lineSrc = tb.Sources
		sp := spans{}
		used, err := priceClosed(tb, tb.Country, "", route, req, date, &out, add, sp)
		if err != nil {
			return Response{}, err
		}
		usedPoints, err := priceTollPoints(tb, tb.Country, route, req, date, &out, add, sp)
		if err != nil {
			return Response{}, err
		}
		if used || usedPoints {
			addSources(tb.Sources)
			useTable(tb)
		}
	}

	// EU ETS on ferry crossings.
	if ferryTTW > 0 {
		switch {
		case req.EUAEurPerT == 0:
			out.Notes = append(out.Notes, "Ferry: give eua_eur_per_t to price the EU ETS on the crossing.")
		default:
			share := maritimeETSShare(date)
			if req.FerryETSShare > 0 {
				share *= req.FerryETSShare
			}
			crossingT, basis := ferryTTW/1000, "Sootcase ferry part (GLEC ro-pax default)"
			if t, b, ok := mrvFerry(&out, res, fd, req, date); ok {
				crossingT, basis = t, b
			}
			t := crossingT * share
			if err := add(Line{Charge: FerryETS, Carbon: true, Km: round3(out.FerryKm), TonnesCO2: round3(t), Rate: req.EUAEurPerT,
				RateUnit: "EUR/t CO2e", Currency: "EUR", Amount: t * req.EUAEurPerT,
				Source: "Directive 2003/87/EC as amended by (EU) 2023/959, Art. 3gb; emissions: " + basis, Sources: etsSources}); err != nil {
				return Response{}, err
			}
			out.Notes = append(out.Notes, fmt.Sprintf("Ferry: the ETS cost of this cargo's share of the crossing's emissions (%.0f%% of them under the ETS in %d). A ferry line's own surcharge follows its ships' real emissions and its pricing.",
				share*100, date.Year()))
		}
	}

	// ETS2 on road fuel from 2028.
	if !date.Before(ETS2Start) {
		roadT := (res.TTWKg - ferryTTW) / 1000
		switch {
		case req.ETS2EurPerT == 0:
			out.Notes = append(out.Notes, "ETS2: give ets2_eur_per_t to price ETS2 on the road fuel.")
		case roadT > 0:
			if err := add(Line{Charge: ETS2, Carbon: true, TonnesCO2: round3(roadT), Rate: req.ETS2EurPerT, RateUnit: "EUR/t CO2e",
				Currency: "EUR", Amount: roadT * req.ETS2EurPerT,
				Source: "Directive 2003/87/EC Chapter IVa (ETS2), from 2028; emissions: Sootcase road tank-to-wheel", Sources: etsSources}); err != nil {
				return Response{}, err
			}
			out.Notes = append(out.Notes, "ETS2: fuel suppliers pay it and pass it on in the fuel price; this is that cost for this trip's fuel.")
		}
	}
	out.TotalEUR, out.CarbonEUR = round2(out.TotalEUR), round2(out.CarbonEUR)
	if err := compare(&out, res, tables, fd, req, date, ferryTTW); err != nil {
		return Response{}, err
	}
	for k, v := range out.CountryKm {
		out.CountryKm[k] = round3(v)
	}
	for k, v := range out.RegionKm {
		out.RegionKm[k] = round3(v)
	}
	return out, nil
}

// area is a country, or a region of one, priced with its own toll table.
type area struct {
	code, country, region string
	km                    float64
}

// areas lists the route's countries, in code order, splitting those
// whose tolls are set by region into their regions (from region_km).
// A regional country without region_km is kept whole: it has no table,
// so it is reported under no_rates with a note.
func areas(out *Response, tables []rates.Table) []area {
	countries := make([]string, 0, len(out.CountryKm))
	for k := range out.CountryKm {
		countries = append(countries, k)
	}
	sort.Strings(countries)
	var as []area
	for _, cc := range countries {
		if !rates.Regional(tables, cc) {
			as = append(as, area{code: cc, country: cc, km: out.CountryKm[cc]})
			continue
		}
		var regs []string
		for k := range out.RegionKm {
			if strings.HasPrefix(k, cc+"-") {
				regs = append(regs, k)
			}
		}
		if len(regs) == 0 {
			if out.CountryKm[cc] >= 0.5 {
				out.Notes = append(out.Notes, fmt.Sprintf("%s: tolls differ by region, and Sootcase returned no region_km to split the %.1f km.", cc, out.CountryKm[cc]))
			}
			as = append(as, area{code: cc, country: cc, km: out.CountryKm[cc]})
			continue
		}
		sort.Strings(regs)
		for _, r := range regs {
			as = append(as, area{code: r, country: cc, region: r, km: out.RegionKm[r]})
		}
	}
	return as
}

// compare prices the trip again for each of req.CompareCO2Classes. The
// route and the cargo's emissions stay the same, except that a CO2 class
// 5 (zero-emission) truck burns no road fuel, so pays no ETS2.
func compare(out *Response, res sootcase.Result, tables []rates.Table, fd *ferries.Data, req Request, date time.Time, ferryTTW float64) error {
	if len(req.CompareCO2Classes) == 0 {
		return nil
	}
	sameEmissions := false
	for _, cls := range req.CompareCO2Classes {
		alt := req
		alt.Truck.CO2Class, alt.CompareCO2Classes = cls, nil
		altRes := res
		if cls == 5 && req.Truck.CO2Class != 5 {
			altRes.TTWKg = ferryTTW // no tailpipe emissions on the road
		} else if cls != req.Truck.CO2Class {
			sameEmissions = true
		}
		r, err := PriceWith(altRes, tables, fd, alt, date)
		if err != nil {
			return fmt.Errorf("compare co2_class %d: %w", cls, err)
		}
		c := Comparison{CO2Class: cls, TotalEUR: r.TotalEUR, CarbonEUR: r.CarbonEUR,
			SavingEUR: round2(out.TotalEUR - r.TotalEUR)}
		for _, l := range r.Lines {
			if l.Charge == RoadToll {
				c.TollEUR += l.AmountEUR
			}
		}
		c.TollEUR = round2(c.TollEUR)
		if req.TripsPerYear > 0 {
			c.SavingPerYearEUR = round2(c.SavingEUR * req.TripsPerYear)
		}
		out.Compare = append(out.Compare, c)
	}
	if req.Truck.CO2Class == 5 && !date.Before(ETS2Start) && req.ETS2EurPerT > 0 && slices.ContainsFunc(req.CompareCO2Classes, func(c int) bool { return c < 5 }) {
		out.Notes = append(out.Notes, "Compare: the diesel classes are priced with this zero-emission trip's road emissions, so their ETS2 is too low; price the diesel truck as the request to compare ETS2.")
	}
	if sameEmissions && !date.Before(ETS2Start) && req.ETS2EurPerT > 0 {
		out.Notes = append(out.Notes, "Compare: diesel trucks in other CO2 classes keep this truck's fuel emissions, so their ETS2 cost is the same; a lower class mostly changes the toll.")
	}
	return nil
}

// maritimeETSShare is the share of verified emissions shipping companies
// surrender allowances for: 40% for 2024, 70% for 2025, 100% from 2026.
func maritimeETSShare(date time.Time) float64 {
	switch y := date.Year(); {
	case y < 2024:
		return 0
	case y == 2024:
		return 0.4
	case y == 2025:
		return 0.7
	}
	return 1
}

func round2(v float64) float64 { return math.Round(v*100) / 100 }
func round3(v float64) float64 { return math.Round(v*1000) / 1000 }

// mrvFerry is the crossing's CO2e (tonnes) from its ships' MRV data: their
// freight intensity x (truck tare + cargo) x the ferry distance. ok is
// false, with a note, when the crossing isn't recognised, has no MRV data
// or the truck's tare isn't given.
func mrvFerry(out *Response, res sootcase.Result, fd *ferries.Data, req Request, date time.Time) (float64, string, bool) {
	if fd == nil {
		return 0, "", false
	}
	var route [][2]float64
	for _, l := range res.Legs {
		route = append(route, l.Path...)
	}
	c, ok := fd.Detect(route)
	if !ok {
		out.Notes = append(out.Notes, "Ferry: the crossing isn't one this tool has ship data for, so it uses Sootcase's default ro-pax factor.")
		return 0, "", false
	}
	out.FerryCrossing = c.Name
	in, ok := fd.Intensity(c, date.Year())
	if ok && req.Truck.TareKg > 0 {
		out.Provenance.FerryMRV = fmt.Sprintf("EU MRV %d, %s", in.Year.ReportingPeriod, in.Year.Version)
	}
	if !ok {
		out.Notes = append(out.Notes, fmt.Sprintf("Ferry: %s has no MRV data; Sootcase's default ro-pax factor is used.", c.Name))
		return 0, "", false
	}
	if req.Truck.TareKg == 0 {
		out.Notes = append(out.Notes, fmt.Sprintf("Ferry: give truck.tare_kg to use %s's own MRV data (%.1f g CO2e per tonne-nautical mile of vehicle and cargo); Sootcase's default ro-pax factor is used.",
			c.Name, in.GPerTNm))
		return 0, "", false
	}
	grossT := (float64(req.Truck.TareKg) + req.CargoKg) / 1000
	nm := out.FerryKm * ferries.NmPerKm
	names := make([]string, len(in.Ships))
	for i, s := range in.Ships {
		names[i] = s.Name
	}
	basis := fmt.Sprintf("EU MRV %d (%s), %s ships %s: %.1f g CO2e/t·nm x %.1f t (truck %.1f + cargo %.1f) x %.1f nm",
		in.Year.ReportingPeriod, in.Year.Version, c.Name, strings.Join(names, ", "), in.GPerTNm, grossT,
		float64(req.Truck.TareKg)/1000, req.CargoKg/1000, nm)
	if c.NotInMRV != "" {
		out.Notes = append(out.Notes, "Ferry: "+c.NotInMRV)
	}
	return in.GPerTNm * grossT * nm / 1e6, basis, true
}

type sectionOnRoute struct {
	sec rates.Section
	km  float64
}

// onRoute lists the table's fixed-charge sections the route passes and
// their total km along the route.
func onRoute(tb rates.Table, route *track) ([]sectionOnRoute, float64) {
	if tb.Sections == nil || len(route.pts) < 2 {
		return nil, 0
	}
	var out []sectionOnRoute
	var total float64
	for _, s := range tb.Sections.List {
		if km, ok := along(route, s.From, s.To); ok {
			out = append(out, sectionOnRoute{s, km})
			total += km
		}
	}
	return out, total
}

// SectionMatchKm is how close a route must pass to both ends of a
// section to count as driving it.
const SectionMatchKm = 0.5

// along is the route's km between two places, if it passes within
// SectionMatchKm of both and the stretch between is no longer than a road
// between them could be (4x the straight line, plus 2 km).
func along(route *track, a, b rates.Place) (float64, bool) {
	pa, da, _ := route.project(a)
	pb, db, _ := route.project(b)
	if da > SectionMatchKm || db > SectionMatchKm {
		return 0, false
	}
	km := math.Abs(pb - pa)
	if km == 0 || km > 4*haversine(a.Lat, a.Lon, b.Lat, b.Lon)+2 {
		return 0, false
	}
	return km, true
}

func haversine(lat1, lon1, lat2, lon2 float64) float64 {
	const r = 6371.0088
	rad := math.Pi / 180
	dLat, dLon := (lat2-lat1)*rad, (lon2-lon1)*rad
	h := math.Sin(dLat/2)*math.Sin(dLat/2) + math.Cos(lat1*rad)*math.Cos(lat2*rad)*math.Sin(dLon/2)*math.Sin(dLon/2)
	return 2 * r * math.Asin(math.Min(1, math.Sqrt(h)))
}

// suburbanShare is the share of km on suburban roads of a road type:
// from the route's toll sections where it matched them, the table's
// network share for the rest.
func suburbanShare(tb rates.Table, rk roads.Km, byRoute bool, road string) float64 {
	def, ok := tb.SuburbanShare[road]
	if !ok {
		def = tb.SuburbanShare[""]
	}
	if !byRoute {
		return def
	}
	km, sub, known := rk.Motorway, rk.MotorwaySub, rk.MotorwayKnown
	if road == rates.OtherRoad {
		km, sub, known = rk.National, rk.NationalSub, rk.NationalKnown
	}
	if km <= 0 {
		return def
	}
	return math.Min(1, (sub+math.Max(0, km-known)*def)/km)
}

// DefaultAvgSpeedKmh is the average truck speed taken to tell when a
// trip reaches each toll station: an assumption, not a law (EU trucks are
// limited to 90 km/h, Directive 92/6/EEC; stops and towns bring the
// average down).
const DefaultAvgSpeedKmh = 70

// passage is when the trip reaches the point pos km along the route,
// in the local time of the country there, and whether a departure time
// was given. The departure is local time where the trip starts.
func passage(req Request, date time.Time, pos float64, country string) (time.Time, bool) {
	if req.Time == "" {
		return time.Time{}, false
	}
	var h, m int
	fmt.Sscanf(req.Time, "%d:%d", &h, &m)
	v := req.AvgSpeedKmh
	if v <= 0 {
		v = DefaultAvgSpeedKmh
	}
	here := zone(country)
	from := zone(req.origin)
	if req.origin == "" {
		from = here
	}
	start := time.Date(date.Year(), date.Month(), date.Day(), h, m, 0, 0, from)
	hours := pos / v
	if req.DriverRest {
		hours = withRest(hours)
	}
	return start.Add(time.Duration(hours * float64(time.Hour))).In(here).Truncate(time.Minute), true
}

// withRest turns hours of driving into hours elapsed for one driver under
// Regulation (EC) No 561/2006: a 45-minute break after 4.5 hours'
// driving (Art. 7) and an 11-hour daily rest after 9 hours (Arts. 6 and
// 8), the rest taken only once more driving follows.
func withRest(d float64) float64 {
	if d <= 0 {
		return 0
	}
	days := math.Ceil(d/9) - 1 // full driving days before this one
	r := d - 9*days
	el := days*(9+0.75+11) + r
	if r > 4.5 {
		el += 0.75
	}
	return el
}

// tripDays is how many days of a time-based charge a trip pays in a
// country, from the passage times of its stretches there, and a note
// saying how.
func tripDays(tb rates.Table, country string, req Request, date time.Time) (int, string) {
	sp := req.spans[country]
	switch {
	case tb.Day == "":
		return 1, "a time-based charge, priced at one day's rate; a trip over more days pays for each day or a longer period."
	case req.Time == "" || len(sp) == 0:
		return 1, "a time-based charge, priced at one day's rate; give time (the departure) to count the days the trip spends there."
	}
	n := 0
	if tb.Day == "calendar" {
		seen := map[string]bool{}
		for _, s := range sp {
			a, _ := passage(req, date, s[0], country)
			b, _ := passage(req, date, s[1], country)
			last := time.Date(b.Year(), b.Month(), b.Day(), 0, 0, 0, 0, time.UTC)
			for d := time.Date(a.Year(), a.Month(), a.Day(), 0, 0, 0, 0, time.UTC); !d.After(last); d = d.AddDate(0, 0, 1) {
				if k := d.Format(time.DateOnly); !seen[k] {
					seen[k] = true
					n++
				}
			}
		}
	} else {
		var until time.Time
		for _, s := range sp {
			a, _ := passage(req, date, s[0], country)
			b, _ := passage(req, date, s[1], country)
			if n == 0 || !a.Before(until) {
				n, until = n+1, a.Add(24*time.Hour)
			}
			for b.After(until) {
				n, until = n+1, until.Add(24*time.Hour)
			}
		}
	}
	unit := map[string]string{"calendar": "calendar day", "24h": "24-hour period"}[tb.Day]
	if n != 1 {
		unit += "s"
	}
	rest := ""
	if !req.DriverRest {
		rest = " without driver rests (give driver_rest for them)"
	}
	return n, fmt.Sprintf("a time-based charge for each %s of use: the trip is there on %d %s by its passage times%s; a longer period may cost less.",
		map[string]string{"calendar": "calendar day", "24h": "24 hours"}[tb.Day], n, unit, rest)
}

// etsSources link the EU ETS Directive (consolidated) and Sootcase,
// which gives the emissions.
var etsSources = []rates.Source{
	{Title: "Directive 2003/87/EC (EU ETS), consolidated", URL: "https://eur-lex.europa.eu/eli/dir/2003/87/oj"},
	{Title: "Sootcase (route and emissions)", URL: "https://sootcase.org"},
}

// StationMatchKm is how close a route must pass a toll station's
// junction or booth to count as using it.
const StationMatchKm = 0.5

type systemUse struct {
	entry, exit string
	km          float64
	from        float64 // km along the route where it starts (chained systems)
}

// usesSystem finds where a route enters and leaves a closed toll system:
// the first and last of its stations the route passes.
func usesSystem(sys rates.TollSystem, route *track) (systemUse, bool) {
	if len(route.pts) < 2 {
		return systemUse{}, false
	}
	first, last := math.Inf(1), math.Inf(-1)
	var u systemUse
	for _, st := range sys.Stations {
		best, bestPos := math.Inf(1), 0.0
		for _, p := range st.Points {
			if pos, d, _ := route.project(p); d < best {
				best, bestPos = d, pos
			}
		}
		if best > StationMatchKm {
			continue
		}
		if bestPos < first {
			first, u.entry = bestPos, st.Name
		}
		if bestPos > last {
			last, u.exit = bestPos, st.Name
		}
	}
	if u.entry == "" {
		return u, false
	}
	u.km, u.from = last-first, first
	if u.entry == u.exit {
		_, open := sys.Prices[u.entry+"|"+u.entry]
		return u, open
	}
	return u, true
}

// priceClosed adds a line for each closed toll system of the table the
// route uses, and says whether it used any.
// spans: where along the route each closed system's tickets start and
// end (km), by system name.
type spans map[string][][2]float64

func priceClosed(tb rates.Table, country, region string, route *track, req Request, date time.Time, out *Response, add func(Line) error, sp spans) (bool, error) {
	used := false
	for _, sys := range tb.Closed {
		var uses []systemUse
		if sys.Chain {
			uses = chainUses(sys, route, req.Truck, req.ETC)
		} else if u, ok := usesSystem(sys, route); ok {
			uses = []systemUse{u}
		}
		for _, u := range uses {
			used = true
			if at, ok := passage(req, date, u.from, country); ok && len(sys.FreeHours) == 2 {
				if free, err := rates.Within(at.Format("15:04"), sys.FreeHours[0], sys.FreeHours[1]); err == nil && free {
					out.Notes = append(out.Notes, fmt.Sprintf("%s: %s is free from %s to %s (entered about %s).", country, sys.Name, sys.FreeHours[0], sys.FreeHours[1], at.Format("15:04")))
					continue
				}
			}
			if sp != nil {
				sp[sys.Name] = append(sp[sys.Name], [2]float64{u.from, u.from + u.km})
			}
			g := sys.GroupOf(req.Truck)
			p, ok := sys.Price(u.entry, u.exit, g, req.ETC)
			if !ok {
				out.Notes = append(out.Notes, fmt.Sprintf("%s: %s has no price from %s to %s for group %s.", country, sys.Name, u.entry, u.exit, g))
				continue
			}
			var pct float64
			var names []string
			for _, d := range sys.Discounts {
				if d.Applies(req.Truck, req.ETC) {
					pct += d.Percent
					names = append(names, fmt.Sprintf("%s %g%%", d.Name, d.Percent))
				}
			}
			if pct > 0 {
				p = round2(p * (1 - pct/100))
				out.Notes = append(out.Notes, fmt.Sprintf("%s: %s with %s off.", country, sys.Name, strings.Join(names, " and ")))
			}
			if req.Truck.LengthM == 0 && slices.ContainsFunc(sys.Groups, func(g rates.Group) bool { return g.MaxLengthM > 0 }) {
				out.Notes = append(out.Notes, fmt.Sprintf("%s: %s is priced by length; %g m assumed (group %s). Give the truck's length_m.", country, sys.Name, rates.DefaultLengthM, g))
			}
			name := sys.Name + ": " + u.entry
			if u.exit != u.entry {
				name += " – " + u.exit
			}
			if err := add(Line{Charge: RoadToll, Country: country, Region: region, Component: rates.Toll, Section: name,
				Km: round3(u.km), Rate: p, RateUnit: tb.Currency + "/passage", Currency: tb.Currency, Amount: p, Source: sys.Law}); err != nil {
				return used, err
			}
		}
	}
	return used, nil
}

// chainUses splits a route's passes through a chained toll system into
// tickets: the pairs with a published price, one after another along the
// route, that together cover the most km (on a tie, the fewest tickets).
// That is the longest pair from the first station passed, then again
// after its exit, except where a station beside the route (an exit's
// toll booth the route only drives past) would make a short ticket that
// blocks a longer one.
// sameKm: stations this close along the route are at the same place.
const sameKm = 0.3

func chainUses(sys rates.TollSystem, route *track, t rates.Truck, etc bool) []systemUse {
	type pass struct {
		name     string
		pos, off float64 // km along the route, and from it
	}
	var passes []pass
	for _, st := range sys.Stations {
		best, bestPos := math.Inf(1), 0.0
		for _, p := range st.Points {
			if pos, d, _ := route.project(p); d < best {
				best, bestPos = d, pos
			}
		}
		if best <= StationMatchKm {
			passes = append(passes, pass{st.Name, bestPos, best})
		}
	}
	sort.Slice(passes, func(i, j int) bool { return passes[i].pos < passes[j].pos })
	g := sys.GroupOf(t)
	n := len(passes)
	priced := func(i, j int) bool {
		if passes[j].name == passes[i].name {
			return false
		}
		_, ok := sys.Price(passes[i].name, passes[j].name, g, etc)
		return ok
	}
	// After a ticket's exit j the next may start at any other station at
	// the same place (where one concession's network meets the next's,
	// each names its station its own way): from cont(i, j), skipping j.
	cont := func(i, j int) int {
		k := j
		for k > i+1 && passes[j].pos-passes[k-1].pos <= sameKm {
			k--
		}
		return k
	}
	type best struct {
		cover   float64 // km
		tickets int
		off     float64 // km the tickets' stations lie off the route
		exit    int     // the ticket from this pass, -1 for none
	}
	// Covers within sameKm count as equal; then fewer tickets, then
	// stations on the road (a barrier across it rather than an exit's
	// booth beside it), then more km.
	better := func(a, b best) bool {
		if math.Abs(a.cover-b.cover) > sameKm {
			return a.cover > b.cover
		}
		if a.tickets != b.tickets {
			return a.tickets < b.tickets
		}
		if math.Abs(a.off-b.off) > 1e-6 {
			return a.off < b.off
		}
		return a.cover > b.cover+1e-9
	}
	type key struct{ k, skip int }
	memo := map[key]best{}
	// from(k, skip): the best from pass k on, never entering at pass skip.
	var from func(k, skip int) best
	from = func(k, skip int) best {
		if k >= n {
			return best{exit: -1}
		}
		if skip < k {
			skip = -1
		}
		if b, ok := memo[key{k, skip}]; ok {
			return b
		}
		b := from(k+1, skip)
		b.exit = -1
		if k != skip {
			for j := k + 1; j < n; j++ {
				if !priced(k, j) {
					continue
				}
				r := from(cont(k, j), j)
				if c := (best{passes[j].pos - passes[k].pos + r.cover, r.tickets + 1, passes[k].off + passes[j].off + r.off, j}); better(c, b) {
					b = c
				}
			}
		}
		memo[key{k, skip}] = b
		return b
	}
	for i := n - 1; i >= 0; i-- { // fill from the end, keeping the recursion shallow
		from(i, -1)
	}
	var out []systemUse
	for i, skip := 0, -1; i < n; {
		b := from(i, skip)
		if b.exit < 0 {
			i++
			continue
		}
		j := b.exit
		out = append(out, systemUse{entry: passes[i].name, exit: passes[j].name, km: passes[j].pos - passes[i].pos, from: passes[i].pos})
		i, skip = cont(i, j), j
	}
	// A barrier across an open section is priced on its own (its pair
	// with itself): passing it pays, unless a ticket's trip covers it.
	var spans [][2]float64
	for _, u := range out {
		spans = append(spans, [2]float64{u.from, u.from + u.km})
	}
	for _, p := range passes {
		if _, ok := sys.Price(p.name, p.name, g, etc); !ok {
			continue
		}
		inside := false
		for _, sp := range spans {
			inside = inside || (p.pos > sp[0]+sameKm && p.pos < sp[1]-sameKm)
		}
		if !inside {
			out = append(out, systemUse{entry: p.name, exit: p.name, from: p.pos})
		}
	}
	sort.SliceStable(out, func(a, b int) bool { return out[a].from < out[b].from })
	return out
}

// DefaultPointMatchKm is how close the route must pass a toll point
// when its table doesn't say.
const DefaultPointMatchKm = 0.05

// priceTollPoints adds a line for each toll point the route passes in a
// direction that pays, and says whether it passed any. Under an hour
// rule only the first passage of a group pays: the route is taken to
// pass a group's stations within its time limit.
func priceTollPoints(tb rates.Table, country string, route *track, req Request, date time.Time, out *Response, add func(Line) error, sp spans) (bool, error) {
	match := tb.PointMatchKm
	if match == 0 {
		match = DefaultPointMatchKm
	}
	type pass struct {
		tp  rates.TollPoint
		pos float64
	}
	var passes []pass
	for _, tp := range tb.TollPoints {
		pos, d, h := route.project(rates.Place{Lat: tp.Lat, Lon: tp.Lon})
		if d > match {
			continue
		}
		if tp.Heading != nil {
			diff := math.Abs(math.Mod(h-*tp.Heading+540, 360) - 180)
			if diff > 90 {
				continue
			}
		}
		passes = append(passes, pass{tp, pos})
	}
	sort.SliceStable(passes, func(i, j int) bool { return passes[i].pos < passes[j].pos })
	paid := map[int]time.Time{} // when each hour-rule group was last paid
	untimedFree := false
	last := map[string]float64{} // where each station was last paid, km along the route
	free, peak := 0, 0
	var cg struct {
		noTime, offHours, multi, freeHours int
		why                                string
		capped, windowAmt                  float64
		window                             time.Time
		day                                map[string]float64
	}
	cg.day = map[string]float64{}
	for _, p := range passes {
		// One station mapped as several booths (a lane, a carriageway):
		// passing them together pays once.
		if at, ok := last[p.tp.Name]; ok && p.pos-at < 1 {
			continue
		}
		if p.tp.Within != "" && slices.ContainsFunc(sp[p.tp.Within], func(s [2]float64) bool { return s[0] < p.pos && p.pos < s[1] }) {
			last[p.tp.Name] = p.pos
			out.Notes = append(out.Notes, fmt.Sprintf("%s: %s is included in the %s ticket.", country, p.tp.Name, p.tp.Within))
			continue
		}
		at, timed := passage(req, date, p.pos, country)
		if p.tp.Schedule != "" {
			c := tb.Congestion
			last[p.tp.Name] = p.pos
			if !timed {
				cg.noTime++
				continue
			}
			if taxed, why := c.Taxed(at); !taxed {
				cg.why = why + " (" + at.Format(time.DateOnly) + ")"
				continue
			}
			amt, err := c.Amount(p.tp.Schedule, at, at.Format("15:04"))
			if err != nil {
				return true, err
			}
			if amt == 0 {
				cg.offHours++
				continue
			}
			// Passages within MultiPassMinutes of a taxed one pay once, the
			// highest amount among them: only what exceeds the window's
			// amount so far is added.
			if c.MultiPassMinutes > 0 && !cg.window.IsZero() && at.Sub(cg.window) < time.Duration(c.MultiPassMinutes)*time.Minute {
				if amt <= cg.windowAmt {
					cg.multi++
					continue
				}
				amt, cg.windowAmt = amt-cg.windowAmt, amt
				cg.multi++
			} else if c.MultiPassMinutes > 0 {
				cg.window, cg.windowAmt = at, amt
			}
			day := at.Format(time.DateOnly)
			if dayCap := c.Cap(at); dayCap > 0 && cg.day[day]+amt > dayCap {
				amt = dayCap - cg.day[day]
				cg.capped = dayCap
				if amt <= 0 {
					continue
				}
			}
			cg.day[day] += amt
			if err := add(Line{Charge: RoadToll, Country: country, Component: rates.Toll, Section: p.tp.Name + " (" + at.Format("15:04") + ")",
				Rate: amt, RateUnit: tb.Currency + "/passage", Currency: tb.Currency, Amount: amt, Source: tb.Law}); err != nil {
				return true, err
			}
			continue
		}
		if timed && len(p.tp.FreeHours) == 2 {
			if free, err := rates.Within(at.Format("15:04"), p.tp.FreeHours[0], p.tp.FreeHours[1]); err == nil && free {
				last[p.tp.Name] = p.pos
				cg.freeHours++
				continue
			}
		}
		rate, ok := p.tp.Price(req.Truck, req.ETC)
		if !ok || rate == 0 {
			continue
		}
		if p.tp.Group != 0 {
			// The hour rule: after a paid passage the group's stations are
			// free for GroupMinutes; without times the trip is taken to pass
			// them all within it.
			mins := p.tp.GroupMinutes
			if mins == 0 {
				mins = 60
			}
			if t0, ok := paid[p.tp.Group]; ok && (!timed || at.Sub(t0) < time.Duration(mins)*time.Minute) {
				free++
				untimedFree = untimedFree || !timed
				continue
			}
			paid[p.tp.Group] = at
		}
		last[p.tp.Name] = p.pos
		if p.tp.PeakRate > rate {
			peak++
		}
		name := p.tp.Name
		if p.tp.Project != "" {
			name = p.tp.Project + ": " + name
		}
		if err := add(Line{Charge: RoadToll, Country: country, Component: rates.Toll, Section: name,
			Rate: rate, RateUnit: tb.Currency + "/passage", Currency: tb.Currency, Amount: rate, Source: tb.Law}); err != nil {
			return true, err
		}
	}
	if free > 0 {
		how := " (by the passage times)"
		if untimedFree {
			how = " (without a departure time the route is taken to pass them within the hour)"
		}
		out.Notes = append(out.Notes, fmt.Sprintf("%s: %d more toll station passage(s) free under their project's hour rule%s.", country, free, how))
	}
	if peak > 0 {
		out.Notes = append(out.Notes, fmt.Sprintf("%s: priced at the off-peak rate; %d of the stations charge more in rush hours.", country, peak))
	}
	switch {
	case cg.noTime > 0:
		out.Notes = append(out.Notes, fmt.Sprintf("%s: %s not priced: give time (HH:MM, local departure) to price its %d station passage(s).", country, tb.Name, cg.noTime))
	case cg.why != "":
		out.Notes = append(out.Notes, fmt.Sprintf("%s: %s: %s.", country, tb.Name, cg.why))
	}
	if cg.offHours > 0 {
		out.Notes = append(out.Notes, fmt.Sprintf("%s: %s: no tax at the time the trip reaches %d station(s).", country, tb.Name, cg.offHours))
	}
	if cg.freeHours > 0 {
		out.Notes = append(out.Notes, fmt.Sprintf("%s: %d toll station passage(s) free at the time the trip reaches them.", country, cg.freeHours))
	}
	if cg.multi > 0 {
		out.Notes = append(out.Notes, fmt.Sprintf("%s: %s: %d more passage(s) within %d minutes pay once, at the highest amount.", country, tb.Name, cg.multi, tb.Congestion.MultiPassMinutes))
	}
	if cg.capped > 0 {
		out.Notes = append(out.Notes, fmt.Sprintf("%s: %s: capped at %g %s a day.", country, tb.Name, cg.capped, tb.Currency))
	}
	return len(passes) > 0, nil
}

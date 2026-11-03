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
	"time"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
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
	From        sootcase.Location `json:"from"`
	To          sootcase.Location `json:"to"`
	Date        string            `json:"date,omitempty"` // YYYY-MM-DD; default today
	CargoKg     float64           `json:"cargo_kg"`
	VehicleType string            `json:"vehicle_type,omitempty"`
	Truck       rates.Truck       `json:"truck"`
	// TolledShare is the share of each country's km on tolled roads,
	// default 1 (all of it). Sootcase doesn't yet tell road classes apart,
	// so give it when part of a trip runs on untolled roads.
	TolledShare map[string]float64 `json:"tolled_share,omitempty"`
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
	Charge    string  `json:"charge"`
	Country   string  `json:"country,omitempty"`
	Component string  `json:"component,omitempty"`
	Carbon    bool    `json:"carbon"` // a charge on CO2
	Km        float64 `json:"km,omitempty"`
	TonnesCO2 float64 `json:"t_co2e,omitempty"`
	Rate      float64 `json:"rate"`
	RateUnit  string  `json:"rate_unit"` // e.g. "DKK/km", "EUR/t CO2e"
	Currency  string  `json:"currency"`
	Amount    float64 `json:"amount"`
	AmountEUR float64 `json:"amount_eur"`
	Source    string  `json:"source"`
}

// Response is a priced trip.
type Response struct {
	Date       string             `json:"date"`
	DistanceKm float64            `json:"distance_km"`
	FerryKm    float64            `json:"ferry_km,omitempty"`
	CountryKm  map[string]float64 `json:"country_km"`
	TTWKg      float64            `json:"ttw_kg"`
	WTWKg      float64            `json:"wtw_kg"`
	Lines      []Line             `json:"lines"`
	TotalEUR   float64            `json:"total_eur"`
	CarbonEUR  float64            `json:"carbon_eur"` // the CO2 parts of tolls, ferry ETS and ETS2
	// NoRates lists countries on the route this tool has no toll table
	// for: their charges are not included.
	NoRates []string `json:"no_rates,omitempty"`
	// Compare is the trip priced for each of CompareCO2Classes.
	Compare []Comparison   `json:"compare,omitempty"`
	Notes   []string       `json:"notes,omitempty"`
	Sources []rates.Source `json:"sources"`
}

// Calculator prices trips.
type Calculator struct {
	Sootcase sootcase.Client
	Tables   []rates.Table
	Now      func() time.Time // default time.Now
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
	if vt == "" {
		vt = DefaultVehicleType
	}
	no := false
	res, err := c.Sootcase.Calculate(ctx, sootcase.Shipment{ID: "trip", WeightKg: req.CargoKg, AddRoadLegs: &no,
		Legs: []sootcase.Leg{{ID: "road", Mode: "road", VehicleType: vt, From: req.From, To: req.To}}})
	if err != nil {
		return Response{}, err
	}
	return Price(res, c.Tables, req, date)
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
	for k, v := range req.TolledShare {
		if v < 0 || v > 1 {
			return fmt.Errorf("tolled_share[%s] must be 0-1", k)
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

// Price prices a trip from Sootcase's result.
func Price(res sootcase.Result, tables []rates.Table, req Request, date time.Time) (Response, error) {
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
		for _, p := range l.Parts {
			if p.Kind == "ferry" {
				ferryTTW += p.TTWKg
			}
		}
	}
	if !routed {
		return Response{}, fmt.Errorf("sootcase returned no distance by country: the server needs Sootcase v0.9.0 or later (country_km)")
	}
	eurPer := map[string]float64{"EUR": 1, "DKK": 1 / DKKPerEUR}
	if req.DKKPerEUR > 0 {
		eurPer["DKK"] = 1 / req.DKKPerEUR
	}
	add := func(l Line) error {
		f, ok := eurPer[l.Currency]
		if !ok {
			return fmt.Errorf("no exchange rate for %s", l.Currency)
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

	// Road tolls, country by country.
	countries := make([]string, 0, len(out.CountryKm))
	for k := range out.CountryKm {
		countries = append(countries, k)
	}
	sort.Strings(countries)
	for _, cc := range countries {
		km := out.CountryKm[cc]
		tb, ok := rates.Find(tables, cc, date)
		if !ok {
			if km >= 0.5 {
				out.NoRates = append(out.NoRates, cc)
			}
			continue
		}
		share := 1.0
		if v, ok := req.TolledShare[cc]; ok {
			share = v
		}
		tolledKm := km * share
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
		for _, r := range rs {
			if err := add(Line{Charge: RoadToll, Country: cc, Component: r.Component, Carbon: r.Component == rates.CO2,
				Km: round3(tolledKm), Rate: r.PerKm, RateUnit: tb.Currency + "/km", Currency: tb.Currency,
				Amount: tolledKm * r.PerKm, Source: tb.Law}); err != nil {
				return Response{}, err
			}
		}
		if zkm := req.EnvZoneKm[cc]; zkm > 0 {
			zr := tb.EnvZoneRate(req.Truck)
			if zr == 0 {
				out.Notes = append(out.Notes, fmt.Sprintf("%s: env_zone_km given, but %s has no environmental zone surcharge.", cc, tb.Name))
			} else if err := add(Line{Charge: RoadToll, Country: cc, Component: rates.EnvZoneSurcharge, Km: zkm, Rate: zr,
				RateUnit: tb.Currency + "/km", Currency: tb.Currency, Amount: zkm * zr, Source: tb.Law}); err != nil {
				return Response{}, err
			}
		}
		if _, given := req.TolledShare[cc]; !given {
			out.Notes = append(out.Notes, fmt.Sprintf("%s: all %.1f km are counted as on tolled roads; give tolled_share.%s if part of the trip isn't. Tolled roads: %s",
				cc, km, cc, tb.TolledRoads))
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
			t := ferryTTW / 1000 * share
			if err := add(Line{Charge: FerryETS, Carbon: true, Km: round3(out.FerryKm), TonnesCO2: round3(t), Rate: req.EUAEurPerT,
				RateUnit: "EUR/t CO2e", Currency: "EUR", Amount: t * req.EUAEurPerT,
				Source: "Directive 2003/87/EC as amended by (EU) 2023/959, Art. 3gb; emissions: Sootcase ferry part (GLEC ro-pax default)"}); err != nil {
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
				Source: "Directive 2003/87/EC Chapter IVa (ETS2), from 2028; emissions: Sootcase road tank-to-wheel"}); err != nil {
				return Response{}, err
			}
			out.Notes = append(out.Notes, "ETS2: fuel suppliers pay it and pass it on in the fuel price; this is that cost for this trip's fuel.")
		}
	}
	out.TotalEUR, out.CarbonEUR = round2(out.TotalEUR), round2(out.CarbonEUR)
	if err := compare(&out, res, tables, req, date, ferryTTW); err != nil {
		return Response{}, err
	}
	for k, v := range out.CountryKm {
		out.CountryKm[k] = round3(v)
	}
	return out, nil
}

// compare prices the trip again for each of req.CompareCO2Classes. The
// route and the cargo's emissions stay the same, except that a CO2 class
// 5 (zero-emission) truck burns no road fuel, so pays no ETS2.
func compare(out *Response, res sootcase.Result, tables []rates.Table, req Request, date time.Time, ferryTTW float64) error {
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
		r, err := Price(altRes, tables, alt, date)
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

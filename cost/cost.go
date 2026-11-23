// Package cost works out what carbon and road charges a truck trip pays:
// km-based road tolls per country (with their CO2 part shown apart), the
// EU ETS on ferry crossings, and ETS2 on road fuel from 2028.
//
// Distances by country and emissions come from Sootcase; rates come from
// the official tables in package tariffs (ORCT datasets). Nothing here is fitted to data:
// every number is a published rate, a price the user gives, or Sootcase's
// GLEC/ISO 14083 result.
package cost

import (
	"context"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/fx"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/carbon-cost/tariffs"
	"github.com/majidkabir/sootcase/pkg/borders"
)

// DefaultVehicleType is Sootcase's GLEC vehicle type used when the request
// names none: an articulated 34-40 t diesel truck.
const DefaultVehicleType = "glec/road/eu_sa/artic_34_40t/diesel"

// DKKPerEUR is the euro central rate of the Danish krone in ERM II, the
// default for converting DKK amounts to EUR.
const DKKPerEUR = 7.46038

// DieselKgCO2PerL is the tank-to-wheel CO2 of a litre of diesel (EN
// 16258:2012, Annex A, Table A.1: 3.21 kg CO2e per kg at 0.832 kg per
// litre), for the national taxes charged per litre when the request
// doesn't give diesel_l.
const DieselKgCO2PerL = 2.67

// Charge kinds.
const (
	RoadToll = "road_toll"
	FerryETS = "ferry_ets"
	// FerryUKETS is the UK ETS on a crossing between UK ports.
	FerryUKETS = "ferry_uk_ets"
	ETS2       = "ets2"
	// FuelCO2 is a national CO2 price on road fuel (Germany's BEHG,
	// Austria's NEHG 2022), paid where the fuel is bought.
	FuelCO2 = "fuel_co2"
	// AreaCharge is a charge per day in a zone (London's Congestion
	// Charge and Low Emission Zone).
	AreaCharge = "area_charge"
	// FerryFare is a ferry's fare for the truck: a crossings dataset its
	// table marks as a ferry (carbon-cost's ORCT extension "ferry").
	FerryFare = "ferry_fare"
)

// ETS2Start is when ETS2 covers road transport fuel.
var ETS2Start = time.Date(2028, 1, 1, 0, 0, 0, 0, time.UTC)

// Request is a trip to price.
type Request struct {
	// From and To are where the trip starts and ends, for a trip with no
	// stops between; give Stops instead for one with.
	From sootcase.Location `json:"from,omitempty"`
	To   sootcase.Location `json:"to,omitempty"`
	// Stops are the trip's stops in order: where the truck starts, where
	// it loads or unloads, where it ends (a depot it returns to empty, say).
	Stops []sootcase.Location `json:"stops,omitempty"`
	// Shipments are the trip's cargo, each from its loading stop to its
	// unloading stop; the result gives each one's share of the trip.
	// Without them cargo_kg is one shipment from the first stop to the
	// last. Put a groupage trip's other cargo in as shipments too, or the
	// one given carries the whole trip.
	Shipments []Shipment `json:"shipments,omitempty"`
	// Path is the way the truck drove (or will), [lon, lat] points from a
	// GPS track or telematics: its tolls, crossings and km by country are
	// priced on it instead of Sootcase's route. Sootcase still routes the
	// stops for the shipments' emissions and ferry crossings.
	Path [][2]float64 `json:"path,omitempty"`
	// CountryKm prices a trip with no route: the km driven in each country
	// (or region, ISO 3166-2, where tolls differ by region), from a
	// tachograph, say. Only charges by the km and by the day are priced;
	// tolls at stations, on sections and bridges need a route, and the
	// result lists them as missing. Not with from, to, stops, shipments or
	// path.
	CountryKm map[string]float64 `json:"country_km,omitempty"`
	Date      string             `json:"date,omitempty"` // YYYY-MM-DD; default today
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
	DriverRest bool `json:"driver_rest,omitempty"`
	// CargoKg is the cargo when the trip carries one shipment from start
	// to end (otherwise give shipments).
	CargoKg     float64     `json:"cargo_kg,omitempty"`
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
	// UKAGbpPerT is the UK ETS allowance price (GBP per t CO2e), for
	// crossings between UK ports from 1 July 2026. 0: not priced.
	UKAGbpPerT float64 `json:"uka_gbp_per_t,omitempty"`
	// FerryETSShare is the share of a crossing's emissions under the EU
	// ETS for a crossing this tool doesn't know: 1 between two EU/EEA
	// ports (default), 0.5 to or from a port outside. A known crossing's
	// share comes from its ports, its ships' size and the derogations in
	// force.
	FerryETSShare float64 `json:"ferry_ets_share,omitempty"`
	// FerryETSBasis is how a ferry's EU ETS is priced: by default the
	// surcharge its line publishes per metre of the vehicle, where the
	// crossing has one line that does (DFDS, Scandlines, POLSCA: what the
	// truck is charged), else the cargo's share of the ships' emissions
	// at eua_eur_per_t; "emissions" always prices the latter.
	FerryETSBasis string `json:"ferry_ets_basis,omitempty"`
	// ETS2EurPerT is the ETS2 allowance price (EUR per t CO2e), for trips
	// from 2028. 0: ETS2 is not priced.
	ETS2EurPerT float64 `json:"ets2_eur_per_t,omitempty"`
	// FuelCountry is where the trip's road fuel is bought (ISO 3166-1
	// alpha-2), for national CO2 prices on fuel. "": bought along the
	// route, each country's share in proportion to its road km.
	FuelCountry string `json:"fuel_country,omitempty"`
	// FuelPurchases are the fuel bought for the trip, by country: the
	// national CO2 prices on fuel go by where it was bought, and the
	// litres are the trip's diesel unless diesel_l or l_per_100km is
	// given.
	FuelPurchases []FuelPurchase `json:"fuel_purchases,omitempty"`
	// DieselL is the litres of diesel the truck burns on the trip's road
	// part, for the CO2 prices on fuel and ETS2.
	DieselL float64 `json:"diesel_l,omitempty"`
	// LPer100Km is the truck's diesel consumption, litres per 100 km, when
	// diesel_l isn't given. Without either the default for its vehicle
	// group and load is used (Trip.FuelBasis says which).
	LPer100Km float64 `json:"l_per_100km,omitempty"`
	// DieselEURPerL is what the truck pays for diesel, EUR per litre
	// without VAT, wherever it fills up; DieselEURPerLByCountry by
	// country (ISO 3166-1 alpha-2), over it. Without them, the EU's
	// Weekly Oil Bulletin's national averages of the trip's week. The
	// fuel cost is a line of its own: total_eur stays the charges, and
	// with_fuel_eur adds the fuel.
	DieselEURPerL          float64            `json:"diesel_eur_per_l,omitempty"`
	DieselEURPerLByCountry map[string]float64 `json:"diesel_eur_per_l_by_country,omitempty"`
	// DieselRefunds takes off the diesel the partial refund of the excise
	// that some countries pay road hauliers on the litres bought there
	// (France: trucks of 7.5 t or more). Give diesel prices before it.
	DieselRefunds bool `json:"diesel_refunds,omitempty"`
	// An electric truck's (CO2 class 5) energy: ElectricityKWh used on the
	// trip (from rFMS totalElectricEnergyUsed or charging records), or
	// KWhPer100Km over the road km; ElectricityEURPerKWh is what it pays
	// per kWh without VAT (blank: Eurostat's average for businesses where
	// it charges). KWhPer100Km also prices the electricity of a class 5
	// truck in the comparison.
	ElectricityKWh       float64 `json:"electricity_kwh,omitempty"`
	KWhPer100Km          float64 `json:"kwh_per_100km,omitempty"`
	ElectricityEURPerKWh float64 `json:"electricity_eur_per_kwh,omitempty"`
	// Currency (ISO 4217, e.g. DKK, PLN, SEK) adds the totals in that
	// currency (in_currency), at the rate its charges are converted at.
	Currency string `json:"currency,omitempty"`
	// DriverEURPerH and VehicleEURPerKm are the truck's own running costs:
	// the driver per hour of driving (Trip.Hours; put paid breaks and
	// allowances in the rate) and the vehicle per road km (tyres,
	// maintenance, depreciation). With either, trip_cost_eur
	// adds them to with_fuel_eur, and route "cheapest" compares by it.
	DriverEURPerH   float64 `json:"driver_eur_per_h,omitempty"`
	VehicleEURPerKm float64 `json:"vehicle_eur_per_km,omitempty"`
	// Alternatives asks Sootcase for up to this many routes of each leg
	// (2 to 5; Sootcase v0.14.0): each is priced in full, and routes
	// lists them. On a trip with stops, an alternative is one leg's other
	// route, the rest as Sootcase routes them.
	Alternatives int `json:"alternatives,omitempty"`
	// Route is the route priced: "primary" (Sootcase's, the default),
	// "cheapest" (of the routes, the one with the lowest with_fuel_eur, or
	// total_eur where a diesel price is missing, complete ones first), or
	// a route's id from routes (e.g. "alt1"; "leg2:alt1" on a trip with
	// stops). Without alternatives, cheapest asks for 3 routes and an id
	// for 5.
	Route string `json:"route,omitempty"`
	// Ferry "avoid" routes the trip on land only.
	Ferry string `json:"ferry,omitempty"`
	// DKKPerEUR converts DKK to EUR; default DKKPerEUR.
	DKKPerEUR float64 `json:"dkk_per_eur,omitempty"`
	// FX converts other currencies to EUR, in units per euro, e.g.
	// {"CHF": 0.93}; default the ECB reference rates (Calculator.FX).
	FX map[string]float64 `json:"fx,omitempty"`

	ecb fx.Rates // set by Calculate from Calculator.FX
	// legLoadKg is the load on board on each leg (Calculate); nil:
	// CargoKg on every leg.
	legLoadKg []float64
	// shipDistKm, shipTTW and shipWTW are each shipment's transport
	// activity distance and Sootcase emissions (Calculate).
	shipDistKm, shipTTW, shipWTW []float64
	// noFuel prices the trip without road diesel (a zero-emission truck
	// in a comparison).
	noFuel bool
	// roadKm is each country's route km by road class, set by Calculate
	// from Calculator.Roads.
	roadKm map[string]roads.Km
	// roadOSM is the OSM extract date of each country's road classes.
	roadOSM map[string]string
	// roadLeftOut names, by country, the stretches of the motorway class
	// left out of the road classes (counted as local roads).
	roadLeftOut map[string][]string
	// roadNetwork names, by country, the law whose tolled sections its road
	// classes are.
	roadNetwork map[string]string
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
	// EnergyEUR is its diesel or electricity, WithFuelEUR the charges and
	// it (Response.WithFuelEUR), and SavingWithFuelEUR what it saves with
	// the energy counted: null where either truck's energy has no price.
	EnergyEUR                float64  `json:"energy_eur,omitempty"`
	WithFuelEUR              float64  `json:"with_fuel_eur,omitempty"`
	SavingWithFuelEUR        *float64 `json:"saving_with_fuel_eur"`
	SavingWithFuelPerYearEUR *float64 `json:"saving_with_fuel_per_year_eur,omitempty"`
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
	Litres    float64 `json:"litres,omitempty"` // fuel, for taxes per litre
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
	// FerryCrossing names the crossings the route uses, when recognised.
	FerryCrossing string             `json:"ferry_crossing,omitempty"`
	CountryKm     map[string]float64 `json:"country_km"`
	RegionKm      map[string]float64 `json:"region_km,omitempty"`
	// TTWKg and WTWKg are the trip's greenhouse gas emissions, kg CO2e,
	// tank-to-wheel and well-to-wheel: from the truck's own diesel when it
	// is given (primary data, which Regulation (EU) 2026/1030 puts first),
	// else Sootcase's (GLEC default intensities x the tonne-km, modelled).
	TTWKg float64 `json:"ttw_kg"`
	WTWKg float64 `json:"wtw_kg"`
	// DataType is "primary" (the truck's diesel given) or "modelled"
	// (Sootcase's defaults, or the default diesel of the truck's group).
	DataType string `json:"data_type"`
	// EmissionsBasis says how TTWKg and WTWKg were found.
	EmissionsBasis string `json:"emissions_basis"`
	// IntensityG is the well-to-wheel g CO2e per tonne-km of the
	// shipments: EN ISO 14083's emission intensity.
	IntensityG float64 `json:"intensity_g_co2e_per_tkm"`
	// EURPerTkm and CarbonEURPerTkm are the trip's amounts per tonne-km
	// of its shipments: each shipment's rate, as they are shared by
	// tonne-km.
	EURPerTkm       float64 `json:"eur_per_tkm"`
	CarbonEURPerTkm float64 `json:"carbon_eur_per_tkm"`
	// Trip is the truck's trip: legs, loads and diesel.
	Trip *Trip `json:"trip,omitempty"`
	// Shipments are each shipment's share of the trip's charges, by
	// tonne-km (EN ISO 14083:2023). The totals are the truck's.
	Shipments []ShipmentCost `json:"shipments,omitempty"`
	Lines     []Line         `json:"lines"`
	TotalEUR  float64        `json:"total_eur"`
	CarbonEUR float64        `json:"carbon_eur"` // the CO2 parts of tolls, ferry ETS and ETS2
	// Routes are the routes priced, when alternatives were asked for: each
	// one's charges and the difference from Sootcase's primary route; the
	// one this answer prices is chosen.
	Routes []RouteOption `json:"routes,omitempty"`
	// Fuel is the trip's diesel at the price given, or the Weekly Oil
	// Bulletin's: not a charge, so not in total_eur.
	Fuel *FuelCost `json:"fuel,omitempty"`
	// Electricity is an electric truck's energy at the price given.
	Electricity *ElectricityCost `json:"electricity,omitempty"`
	// WithFuelEUR is total_eur and the truck's energy (the diesel or the
	// electricity), without counting twice the CO2 prices on fuel (and
	// ETS2) that the diesel price already holds.
	WithFuelEUR float64 `json:"with_fuel_eur,omitempty"`
	// InCurrency is the totals in Request.Currency.
	InCurrency *InCurrency `json:"in_currency,omitempty"`
	// DriverEUR and VehicleEUR are the running costs at the rates given;
	// TripCostEUR is with_fuel_eur (total_eur without a diesel price) and
	// them.
	DriverEUR   float64 `json:"driver_eur,omitempty"`
	VehicleEUR  float64 `json:"vehicle_eur,omitempty"`
	TripCostEUR float64 `json:"trip_cost_eur,omitempty"`
	// NoRates lists countries on the route this tool has no toll table
	// for: their charges are not included.
	NoRates []string `json:"no_rates,omitempty"`
	// Complete says whether the total includes every charge this tool
	// knows the trip meets; false when Missing lists any.
	Complete bool `json:"complete"`
	// Missing lists the charges the trip meets that the total leaves out:
	// areas with no table here, and rates that ended with no successor
	// here yet (a new year's tariffs not yet published or added).
	Missing []Missing `json:"missing,omitempty"`
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

// Missing is a charge the trip meets that the result leaves out.
type Missing struct {
	// Area is the country, or region, of the charge.
	Area string `json:"area"`
	// Charge is the kind of charge: road_toll, area_charge or fuel_co2.
	Charge string `json:"charge"`
	// Name is the scheme, for rates that ended.
	Name string `json:"name,omitempty"`
	// Reason is "no_table" (this tool has none for the area), "ended"
	// (its rates ended on Ended and the next ones aren't here yet) or
	// "no_route" (its tolls are at stations or on sections, and the trip
	// was given as country_km).
	Reason string `json:"reason"`
	// Ended is the last day of the last rates here.
	Ended string `json:"ended,omitempty"`
}

// Message says what is missing, in a sentence.
func (m Missing) Message() string {
	what := map[string]string{RoadToll: "tolls", AreaCharge: "area charge", FuelCO2: "CO2 price on diesel", FerryFare: "ferry fare"}[m.Charge]
	if m.Reason == "no_route" {
		return fmt.Sprintf("%s %s (%s): charged at toll stations or on sections, which need the route (give from and to, or path)", m.Area, what, m.Name)
	}
	if m.Reason == "ended" {
		return fmt.Sprintf("%s %s (%s): the rates here ended on %s and the next ones aren't in this release yet", m.Area, what, m.Name, m.Ended)
	}
	return fmt.Sprintf("%s %s: no table in this tool", m.Area, what)
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
	Tariffs  *tariffs.Set
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
	if req.Alternatives <= 1 && req.Route != "" && req.Route != "primary" {
		req.Alternatives = 3
		if req.Route != "cheapest" {
			req.Alternatives = 5
		}
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
	var res sootcase.Result
	var notes []string
	switch {
	case len(req.CountryKm) > 0:
		res = kmTrip(&req)
	default:
		if res, err = c.trip(ctx, &req, vt); err != nil {
			return Response{}, err
		}
		if len(req.Path) > 0 {
			if c.Borders == nil {
				return Response{}, fmt.Errorf("path: this server has no borders to split it by country")
			}
			notes = ownPath(c.Borders, c.Ferries, &res, req.Path)
		}
	}
	if req.Alternatives > 1 {
		out, err := c.priceRoutes(res, &req, date)
		if err != nil {
			return out, err
		}
		out.Notes = append(notes, out.Notes...)
		if req.Time != "" && req.origin != "" {
			assumed = append(assumed, fmt.Sprintf("time: %s local time in %s, where the trip starts; stations use their own country's time", req.Time, req.origin))
		}
		out.Provenance.Assumed = append(assumed, out.Provenance.Assumed...)
		return out, nil
	}
	out, err := c.priceRoute(res, &req, date)
	if err != nil {
		return out, err
	}
	out.Notes = append(notes, out.Notes...)
	if req.Time != "" && req.origin != "" {
		assumed = append(assumed, fmt.Sprintf("time: %s local time in %s, where the trip starts; stations use their own country's time", req.Time, req.origin))
	}
	out.Provenance.Assumed = append(assumed, out.Provenance.Assumed...)
	return out, nil
}

// priceRoute prices a trip on the route Sootcase gave (res): its runs by
// country and road class, then the charges.
func (c Calculator) priceRoute(res sootcase.Result, req *Request, date time.Time) (Response, error) {
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
			req.roadOSM, req.roadLeftOut, req.roadNetwork = map[string]string{}, map[string][]string{}, map[string]string{}
			for cc := range req.roadKm {
				req.roadOSM[cc] = c.Roads.Extract(cc)
				if n := c.Roads.Network(cc); n != "" {
					req.roadNetwork[cc] = n
				}
				if l := c.Roads.LeftOut(cc); len(l) > 0 {
					req.roadLeftOut[cc] = l
				}
			}
		}
	}
	out, err := PriceWith(res, c.Tariffs, c.Ferries, *req, date)
	if err != nil {
		return out, err
	}
	out.Route = thinRuns(runs, MapPoints)
	out.Provenance.Version = c.Version
	base := c.Sootcase.BaseURL
	if base == "" {
		base = sootcase.DefaultURL
	}
	if len(req.CountryKm) == 0 {
		out.Provenance.Sootcase = strings.TrimRight(base, "/")
	}
	if res.Dataset != "" {
		out.Provenance.Sootcase += ", factors: " + res.Dataset
	}
	return out, nil
}

// trip routes the trip's legs with Sootcase and sets the request's
// loads and each shipment's distance and emissions. Sootcase's emissions
// are its GLEC default intensity x tonne-km, so a leg is calculated once,
// at the heaviest load on board, and scaled to its own.
func (c Calculator) trip(ctx context.Context, req *Request, vt string) (sootcase.Result, error) {
	stops, ships := req.stops(), req.shipments()
	loads := legLoads(ships, len(stops)-1)
	var heaviest float64
	for _, l := range loads {
		heaviest = math.Max(heaviest, l)
	}
	no := false
	sh := sootcase.Shipment{ID: "trip", WeightKg: heaviest, AddRoadLegs: &no}
	for i := 0; i+1 < len(stops); i++ {
		id := "road"
		if len(stops) > 2 {
			id = fmt.Sprintf("leg%d", i+1)
		}
		sh.Legs = append(sh.Legs, sootcase.Leg{ID: id, Mode: "road", VehicleType: vt, From: stops[i], To: stops[i+1]})
	}
	opt := sootcase.Options{AvoidFerries: req.Ferry == "avoid"}
	if req.Alternatives > 1 {
		opt.Alternatives = req.Alternatives
	}
	res, err := c.Sootcase.CalculateWith(ctx, sh, opt)
	if err != nil {
		return res, err
	}
	if len(res.Legs) != len(sh.Legs) {
		return res, fmt.Errorf("sootcase returned %d legs for %d", len(res.Legs), len(sh.Legs))
	}
	perT := make([][2]float64, len(res.Legs)) // each leg's TTW and WTW per tonne on board
	res.TTWKg, res.WTWKg = 0, 0
	for i := range res.Legs {
		l := &res.Legs[i]
		perT[i] = [2]float64{l.TTWKg / heaviest * 1000, l.WTWKg / heaviest * 1000}
		f := loads[i] / heaviest
		l.TTWKg, l.WTWKg = l.TTWKg*f, l.WTWKg*f
		scaleParts(l, f)
		// Its other routes, at the same load.
		for k := range l.Alternatives {
			a := &l.Alternatives[k]
			a.TTWKg, a.WTWKg = a.TTWKg*f, a.WTWKg*f
			scaleParts(a, f)
		}
		res.TTWKg += l.TTWKg
		res.WTWKg += l.WTWKg
	}
	req.legLoadKg = loads
	if len(ships) == 1 && ships[0].From == 0 && ships[0].To == len(stops)-1 && len(stops) == 2 {
		return res, nil
	}
	// Each shipment's own route, loading stop to unloading stop: its
	// distance for the tonne-km and its emissions.
	req.shipDistKm, req.shipTTW, req.shipWTW = make([]float64, len(ships)), make([]float64, len(ships)), make([]float64, len(ships))
	type pair struct{ from, to int }
	done := map[pair][3]float64{} // km, TTW and WTW per tonne
	for i, s := range ships {
		pr := pair{s.From, s.To}
		v, ok := done[pr]
		if !ok && s.To == s.From+1 {
			v, ok = [3]float64{res.Legs[s.From].DistanceKm, perT[s.From][0], perT[s.From][1]}, true
		}
		if !ok {
			r, err := c.Sootcase.CalculateWith(ctx, sootcase.Shipment{ID: "shipment-" + s.ID, WeightKg: s.WeightKg, AddRoadLegs: &no,
				Legs: []sootcase.Leg{{ID: "road", Mode: "road", VehicleType: vt, From: stops[s.From], To: stops[s.To]}}},
				sootcase.Options{AvoidFerries: req.Ferry == "avoid"})
			if err != nil {
				return res, fmt.Errorf("shipment %s: %w", s.ID, err)
			}
			var km float64
			for _, l := range r.Legs {
				km += l.DistanceKm
			}
			v = [3]float64{km, r.TTWKg / s.WeightKg * 1000, r.WTWKg / s.WeightKg * 1000}
		}
		done[pr] = v
		req.shipDistKm[i] = v[0]
		req.shipTTW[i], req.shipWTW[i] = v[1]*s.WeightKg/1000, v[2]*s.WeightKg/1000
	}
	return res, nil
}

// scaleParts scales a leg's parts' emissions (its ferries) by f.
func scaleParts(l *sootcase.LegResult, f float64) {
	parts := make([]sootcase.Part, len(l.Parts))
	for j, p := range l.Parts {
		p.TTWKg, p.WTWKg = p.TTWKg*f, p.WTWKg*f
		parts[j] = p
	}
	l.Parts = parts
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
	if req.FerryETSBasis != "" && req.FerryETSBasis != "emissions" && req.FerryETSBasis != "surcharge" {
		return fmt.Errorf(`ferry_ets_basis: give "surcharge" (the default) or "emissions"`)
	}
	if err := checkTrip(req); err != nil {
		return err
	}
	if err := checkOwnRoute(req); err != nil {
		return err
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
	if req.Alternatives < 0 || req.Alternatives > 5 {
		return fmt.Errorf("alternatives %d: give 2 to 5 routes", req.Alternatives)
	}
	if req.Route != "" && !regexp.MustCompile(`^(primary|cheapest|(leg\d+:)?alt\d+)$`).MatchString(req.Route) {
		return fmt.Errorf("route %q: give primary, cheapest or a route's id (alt1, leg2:alt1)", req.Route)
	}
	if req.Ferry != "" && req.Ferry != "avoid" {
		return fmt.Errorf("ferry %q: give avoid, or leave it out", req.Ferry)
	}
	if (req.Alternatives > 1 || req.Route != "" && req.Route != "primary") && (len(req.Path) > 0 || len(req.CountryKm) > 0) {
		return fmt.Errorf("alternatives and route: not with path or country_km, which give the route")
	}
	if req.Ferry != "" && (len(req.Path) > 0 || len(req.CountryKm) > 0) {
		return fmt.Errorf("ferry: not with path or country_km, which give the route")
	}
	if req.DriverEURPerH < 0 || req.DriverEURPerH > 500 || req.VehicleEURPerKm < 0 || req.VehicleEURPerKm > 50 {
		return fmt.Errorf("driver_eur_per_h (0-500) and vehicle_eur_per_km (0-50): give EUR, e.g. 35 and 0.45")
	}
	if req.Currency != "" && !currencyCode.MatchString(req.Currency) {
		return fmt.Errorf("currency %q: give an ISO 4217 code such as DKK, PLN or SEK", req.Currency)
	}
	if req.ElectricityKWh < 0 || req.KWhPer100Km < 0 || req.KWhPer100Km > 1000 || req.ElectricityEURPerKWh < 0 || req.ElectricityEURPerKWh > 5 {
		return fmt.Errorf("electricity_kwh (0 or more), kwh_per_100km (0-1000) and electricity_eur_per_kwh (0-5): e.g. 120 kWh per 100 km at EUR 0.25")
	}
	if req.DieselEURPerL < 0 || req.DieselEURPerL > 10 {
		return fmt.Errorf("diesel_eur_per_l %v: give EUR per litre without VAT, e.g. 1.45", req.DieselEURPerL)
	}
	for cc, v := range req.DieselEURPerLByCountry {
		if !regexp.MustCompile(`^[A-Z]{2}$`).MatchString(cc) || v <= 0 || v > 10 {
			return fmt.Errorf("diesel_eur_per_l_by_country %s=%v: give ISO 3166-1 alpha-2 codes and EUR per litre without VAT, e.g. PL=1.25", cc, v)
		}
	}
	if req.FuelCountry != "" && !regexp.MustCompile(`^[A-Z]{2}$`).MatchString(req.FuelCountry) {
		return fmt.Errorf("fuel_country %q: give an ISO 3166-1 alpha-2 code, e.g. DE", req.FuelCountry)
	}
	if req.EUAEurPerT < 0 || req.UKAGbpPerT < 0 || req.ETS2EurPerT < 0 || req.DKKPerEUR < 0 || req.DieselL < 0 || req.FerryETSShare < 0 || req.FerryETSShare > 1 {
		return fmt.Errorf("prices, rates and shares can't be negative (ferry_ets_share is 0-1)")
	}
	return nil
}

// Price prices a trip from Sootcase's result, with ferry crossings at
// Sootcase's default factor.
func Price(res sootcase.Result, set *tariffs.Set, req Request, date time.Time) (Response, error) {
	return PriceWith(res, set, nil, req, date)
}

// PriceWith prices a trip from Sootcase's result; a recognised ferry
// crossing uses its ships' MRV data from fd when the truck's tare is
// given.
func PriceWith(res sootcase.Result, set *tariffs.Set, fd *ferries.Data, req Request, date time.Time) (Response, error) {
	if err := check(req); err != nil {
		return Response{}, err
	}
	if len(res.Legs) == 0 {
		return Response{}, fmt.Errorf("sootcase returned no legs")
	}
	out := Response{Date: date.Format(time.DateOnly), CountryKm: map[string]float64{}, TTWKg: res.TTWKg, WTWKg: res.WTWKg}
	if len(req.shipTTW) > 0 {
		out.TTWKg, out.WTWKg = 0, 0
		for i := range req.shipTTW {
			out.TTWKg += req.shipTTW[i]
			out.WTWKg += req.shipWTW[i]
		}
	}
	out.Trip = tripOf(res, req)
	req = tripEmissions(&out, res, req)
	if len(req.CountryKm) > 0 {
		out.Notes = append(out.Notes, "country_km: no route, so tolls at stations, on sections, bridges and tunnels, ferries and environmental zones aren't priced (give from and to, or path).")
	}
	// The road diesel's tank-to-wheel CO2, t: what ETS2 and the CO2 prices
	// on fuel are charged on.
	roadT := out.Trip.FuelL * DieselKgCO2PerL / 1000
	hasFerry, routed := false, false
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
				hasFerry = true
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
	add := func(l Line) error {
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
			v, src, day := req.ecb.PerEUR[l.Currency], fx.Source, req.ecb.Date
			if v == 0 {
				// A currency the ECB publishes no rate for (RSD, ALL): its
				// central bank's official rate.
				if nv, nday, nsrc, in := fx.NationalOnDate(l.Currency, date); in {
					v, day, src = nv, nday, nsrc
				}
			}
			if v == 0 {
				return fmt.Errorf("no exchange rate for %s: give fx.%s (%s per euro)", l.Currency, l.Currency, l.Currency)
			}
			f = 1 / v
			eurPer[l.Currency] = f
			seenFX[l.Currency] = true
			out.Provenance.FX = append(out.Provenance.FX, fmt.Sprintf("%s: %g per EUR (%s, %s)", l.Currency, v, src, day))
			out.Notes = append(out.Notes, fmt.Sprintf("%s converted at %g %s per euro (%s, %s); give fx.%s to use another rate.",
				l.Currency, v, l.Currency, src, day, l.Currency))
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
	var path [][2]float64
	for _, l := range res.Legs {
		path = append(path, l.Path...)
	}
	route := newTrack(path)
	p := newPricer(req, date, &out, add)
	// Road tolls, area by area: countries, or their regions where tolls
	// are set by region.
	for _, a := range areas(&out, set) {
		ds, ok := set.Find(a.code, date)
		if !ok {
			if a.km >= 0.5 {
				out.NoRates = append(out.NoRates, a.code)
				m := Missing{Area: a.code, Charge: RoadToll, Reason: "no_table"}
				if d, ok := set.Ended(a.code, date); ok {
					m.Reason, m.Name, m.Ended = "ended", d.Name, d.ValidTo
				}
				out.Missing = append(out.Missing, m)
			}
			continue
		}
		if err := p.priceArea(ds, a, route); err != nil {
			return Response{}, err
		}
	}
	// Fixed-charge crossings (bridges) wherever the route passes them.
	if err := p.priceCrossings(set, route); err != nil {
		return Response{}, err
	}

	// EU ETS on ferry crossings.
	if hasFerry {
		if err := priceFerryETS(&out, res, fd, req, date, add); err != nil {
			return Response{}, err
		}
	}

	// UK ETS on crossings between UK ports.
	if hasFerry {
		if err := priceFerryUKETS(&out, res, fd, req, date, add); err != nil {
			return Response{}, err
		}
	}

	// ETS2 on road fuel from 2028.
	if !date.Before(ETS2Start) {
		switch {
		case req.ETS2EurPerT == 0:
			out.Notes = append(out.Notes, "ETS2: give ets2_eur_per_t to price ETS2 on the road fuel.")
		case roadT > 0:
			if err := add(Line{Charge: ETS2, Carbon: true, TonnesCO2: round3(roadT), Rate: req.ETS2EurPerT, RateUnit: "EUR/t CO2e",
				Currency: "EUR", Amount: roadT * req.ETS2EurPerT,
				Source: fmt.Sprintf("Directive 2003/87/EC Chapter IVa (ETS2), from 2028; emissions: %.1f l of diesel x %.2f kg CO2/l (%s)", out.Trip.FuelL, DieselKgCO2PerL, out.Trip.FuelBasis), Sources: etsSources}); err != nil {
				return Response{}, err
			}
			out.Notes = append(out.Notes, "ETS2: fuel suppliers pay it and pass it on in the fuel price; this is that cost for this trip's fuel.")
		}
	}
	if err := p.priceFuel(set, out.Trip.FuelL); err != nil {
		return Response{}, err
	}
	if err := p.priceZones(set, route); err != nil {
		return Response{}, err
	}
	out.Missing = append(out.Missing, lapsed(set, req, &out, route, out.Trip.FuelL, date)...)
	out.Complete = len(out.Missing) == 0
	out.TotalEUR, out.CarbonEUR = round2(out.TotalEUR), round2(out.CarbonEUR)
	fuelCost(&out, req, date)
	electricityCost(&out, req, date)
	if err := compare(&out, res, set, fd, req, date); err != nil {
		return Response{}, err
	}
	runningCost(&out, req)
	allocate(&out, res, req)
	if err := convert(&out, req, date); err != nil {
		return Response{}, err
	}
	if out.Trip.FuelL > 0 && strings.HasPrefix(out.Trip.FuelBasis, "default") {
		out.Provenance.Assumed = append(out.Provenance.Assumed, fmt.Sprintf("diesel: %.1f l (%.1f l/100 km) for a new truck of its VECTO group (%s); give l_per_100km or diesel_l for the truck's own",
			out.Trip.FuelL, 100*out.Trip.FuelL/math.Max(out.Trip.RoadKm, 1e-9), vectoSource))
		addSource(&out, rates.Source{Title: "COM(2024) 313: CO2 emissions and fuel consumption of new heavy-duty vehicles, reporting period 2021", URL: vectoURL})
	}
	for k, v := range out.CountryKm {
		out.CountryKm[k] = round3(v)
	}
	for k, v := range out.RegionKm {
		out.RegionKm[k] = round3(v)
	}
	out.DistanceKm, out.FerryKm = round3(out.DistanceKm), round3(out.FerryKm)
	return out, nil
}

// addSource lists a source once.
func addSource(out *Response, s rates.Source) {
	for _, x := range out.Sources {
		if x.URL == s.URL {
			return
		}
	}
	out.Sources = append(out.Sources, s)
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
func areas(out *Response, set *tariffs.Set) []area {
	countries := make([]string, 0, len(out.CountryKm))
	for k := range out.CountryKm {
		countries = append(countries, k)
	}
	sort.Strings(countries)
	var as []area
	for _, cc := range countries {
		if !set.Regional(cc) {
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
func compare(out *Response, res sootcase.Result, set *tariffs.Set, fd *ferries.Data, req Request, date time.Time) error {
	if len(req.CompareCO2Classes) == 0 {
		return nil
	}
	sameEmissions := false
	for _, cls := range req.CompareCO2Classes {
		alt := req
		alt.Truck.CO2Class, alt.CompareCO2Classes, alt.Currency = cls, nil, ""
		if cls == 5 && req.Truck.CO2Class != 5 {
			alt.noFuel = true // no diesel on the road
		} else if cls != req.Truck.CO2Class && req.Truck.CO2Class != 5 {
			sameEmissions = true
		}
		r, err := PriceWith(res, set, fd, alt, date)
		if err != nil {
			return fmt.Errorf("compare co2_class %d: %w", cls, err)
		}
		c := Comparison{CO2Class: cls, TotalEUR: r.TotalEUR, CarbonEUR: r.CarbonEUR,
			SavingEUR: round2(out.TotalEUR - r.TotalEUR)}
		if energyPriced(&r) {
			c.EnergyEUR, c.WithFuelEUR = energyEUR(&r), r.WithFuelEUR
			if energyPriced(out) {
				v := round2(out.WithFuelEUR - r.WithFuelEUR)
				c.SavingWithFuelEUR = &v
				if req.TripsPerYear > 0 {
					y := round2(v * req.TripsPerYear)
					c.SavingWithFuelPerYearEUR = &y
				}
			}
		}
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
	if sameEmissions && !date.Before(ETS2Start) && req.ETS2EurPerT > 0 {
		out.Notes = append(out.Notes, "Compare: diesel trucks in other CO2 classes keep this truck's diesel, so their CO2 prices on fuel and ETS2 are the same; a lower class mostly changes the toll.")
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

// ferryPart is one ferry part of a leg: its km and Sootcase's default
// tank-to-wheel emissions for it, and the crossing it is, when known.
type ferryPart struct {
	km, ttwKg float64
	loadKg    float64 // on board the truck on its leg
	crossing  *ferries.Crossing
}

// ferryParts are the trip's ferry parts, each matched to a crossing in fd
// found on its leg: the ferry part whose length is nearest the route's km
// between the crossing's terminals (within 2 km or 30%), so a crossing
// whose terminals the route only passes near isn't taken for another.
func ferryParts(res sootcase.Result, fd *ferries.Data, req Request) []ferryPart {
	var out []ferryPart
	for li, l := range res.Legs {
		load := req.CargoKg
		if li < len(req.legLoadKg) {
			load = req.legLoadKg[li]
		}
		var ps []ferryPart
		for _, p := range l.Parts {
			if p.Kind == "ferry" {
				ps = append(ps, ferryPart{km: p.DistanceKm, ttwKg: p.TTWKg, loadKg: load})
			}
		}
		if len(ps) == 1 && l.RouteParts["ferry"] > 0 {
			ps[0].km = l.RouteParts["ferry"]
		}
		if fd != nil && len(ps) > 0 {
			cs := fd.DetectAll(l.Path)
			tr := newTrack(l.Path)
			for k := range cs {
				c := &cs[k]
				if len(c.Terminals) != 2 {
					continue
				}
				a, _, _ := tr.project(rates.Place{Lat: c.Terminals[0].Lat, Lon: c.Terminals[0].Lon})
				b, _, _ := tr.project(rates.Place{Lat: c.Terminals[1].Lat, Lon: c.Terminals[1].Lon})
				along, best, bi := math.Abs(b-a), math.Inf(1), -1
				for i, p := range ps {
					if d := math.Abs(p.km - along); p.crossing == nil && d < best && d <= math.Max(2, 0.3*along) {
						best, bi = d, i
					}
				}
				if bi >= 0 {
					ps[bi].crossing = c
				}
			}
		}
		out = append(out, ps...)
	}
	return out
}

// priceFerryETS adds a ferry ETS line for each crossing on the trip: the
// cargo's share of the crossing's emissions (its ships' MRV data when the
// crossing is known and the truck's tare given, else Sootcase's part),
// times the share of them under the EU ETS by law, times the phase-in.
func priceFerryETS(out *Response, res sootcase.Result, fd *ferries.Data, req Request, date time.Time, add func(Line) error) error {
	phase := maritimeETSShare(date)
	var names []string
	askEUA := false
	defer func() {
		if askEUA {
			out.Notes = append(out.Notes, "Ferry: give eua_eur_per_t to price the EU ETS on the crossing.")
		}
	}()
	for _, p := range ferryParts(res, fd, req) {
		emT, basis, section := p.ttwKg/1000, "Sootcase ferry part (GLEC ro-pax default)", ""
		cover, coverBasis := 1.0, ""
		if p.crossing != nil && req.FerryETSBasis != "emissions" {
			done, err := ferrySurcharge(out, fd, *p.crossing, p.km, req, date, add)
			if err != nil {
				return err
			}
			if done {
				names = append(names, p.crossing.Name)
				continue
			}
		}
		if req.EUAEurPerT == 0 {
			askEUA = true
			if p.crossing != nil {
				names = append(names, p.crossing.Name)
			}
			continue
		}
		if p.crossing == nil {
			if req.FerryETSShare > 0 {
				cover, coverBasis = req.FerryETSShare, fmt.Sprintf("%.0f%% of its emissions (ferry_ets_share)", req.FerryETSShare*100)
			}
			out.Notes = append(out.Notes, "Ferry: the crossing isn't one this tool has ship data for, so it uses Sootcase's default ro-pax factor and counts all its emissions under the ETS (ships under 5,000 GT and island derogations aren't known for it; give ferry_ets_share for a voyage to or from a port outside the EU/EEA).")
		} else {
			c := p.crossing
			section = c.Name
			names = append(names, c.Name)
			cov, ok := fd.Coverage(*c, date)
			if !ok {
				cov = ferries.Coverage{Share: 1, Basis: "all of its emissions"}
			}
			if cov.Note != "" {
				out.Notes = append(out.Notes, "Ferry: "+c.Name+": "+cov.Note+".")
			}
			if cov.Share == 0 {
				out.Notes = append(out.Notes, fmt.Sprintf("Ferry: %s: no EU ETS cost: %s.", c.Name, cov.Basis))
				continue
			}
			cover, coverBasis = cov.Share, cov.Basis
			if t, b, ok := mrvFerry(out, fd, c, p.km, p.loadKg, req, date); ok {
				emT, basis = t, b
			}
		}
		if emT == 0 {
			// The truck crosses empty: Sootcase's ferry part goes by the
			// cargo; the ships' MRV data count the truck itself.
			where := "a crossing"
			if section != "" {
				where = section
			}
			out.Notes = append(out.Notes, fmt.Sprintf("Ferry: the truck crosses %s empty, so the cargo's share of its emissions is none; the truck's own share needs the crossing's ships (MRV data) and truck.tare_kg.", where))
			continue
		}
		share := phase * cover
		t := emT * share
		src := "Directive 2003/87/EC as amended by (EU) 2023/959, Art. 3gb"
		if coverBasis != "" {
			src += "; " + coverBasis
		}
		if err := add(Line{Charge: FerryETS, Carbon: true, Section: section, Km: round3(p.km), TonnesCO2: round3(t), Rate: req.EUAEurPerT,
			RateUnit: "EUR/t CO2e", Currency: "EUR", Amount: t * req.EUAEurPerT,
			Source: src + "; emissions: " + basis, Sources: etsSources}); err != nil {
			return err
		}
		what := "the crossing's"
		if section != "" {
			what = section + "'s"
		}
		out.Notes = append(out.Notes, fmt.Sprintf("Ferry: the ETS cost of this cargo's share of %s emissions (%.0f%% of them under the ETS in %d). A ferry line's own surcharge follows its ships' real emissions and its pricing.",
			what, share*100, date.Year()))
	}
	out.FerryCrossing = strings.Join(names, ", ")
	return nil
}

// ferrySurcharge prices a crossing's EU ETS at the surcharge its line
// publishes, per metre of the vehicle, when the crossing has that one
// line; it says whether it did.
func ferrySurcharge(out *Response, fd *ferries.Data, c ferries.Crossing, km float64, req Request, date time.Time, add func(Line) error) (bool, error) {
	s, ok := fd.ETSSurcharge(c.ID, date)
	if !ok {
		return false, nil
	}
	length, assumed := req.Truck.LengthM, ""
	if length == 0 {
		length, assumed = rates.DefaultLengthM, fmt.Sprintf(" (%g m assumed; give the truck's length_m)", rates.DefaultLengthM)
	}
	m := s.Metres(length)
	if strings.Contains(c.Operator, ";") {
		out.Notes = append(out.Notes, fmt.Sprintf("Ferry: %s: %s's ETS surcharge is EUR %.2f per metre (EUR %.2f for %g m), but other lines (%s) sail it too, so its EU ETS is the cargo's share of the ships' emissions.",
			c.Name, s.Operator, s.EURPerM, s.EURPerM*m, m, c.Operator))
		return false, nil
	}
	ed := s.Edition
	src := fmt.Sprintf("%s ETS surcharge, %s, from %s", possessive(s.Operator), s.Route, ed.From)
	if ed.Basis != "" {
		src += " (" + ed.Basis + ")"
	}
	if err := add(Line{Charge: FerryETS, Carbon: true, Section: c.Name, Km: round3(km), Rate: s.EURPerM, RateUnit: "EUR/m",
		Currency: "EUR", Amount: s.EURPerM * m, Source: src,
		Sources: []rates.Source{{Title: s.Source.Title, URL: s.Source.URL}, etsSources[0]}}); err != nil {
		return false, err
	}
	how := "per metre of the vehicle"
	if s.CommencedMetre {
		how = "per commencing metre"
		if s.MinM > 0 {
			how += fmt.Sprintf(", at least %g", s.MinM)
		}
	}
	note := fmt.Sprintf("Ferry: %s: the EU ETS as %s charges it, its surcharge of EUR %.2f %s × %g m%s; ferry_ets_basis \"emissions\" prices the cargo's share of the ships' emissions instead.",
		c.Name, s.Operator, s.EURPerM, how, m, assumed)
	if ed.Note != "" {
		note += " The surcharge's edition: " + ed.Note + "."
	}
	out.Notes = append(out.Notes, note)
	return true, nil
}

// possessive is "DFDS'" or "POLSCA Baltic Ferries (Polferries, Unity
// Line)'s".
func possessive(name string) string {
	if strings.HasSuffix(name, "s") || strings.HasSuffix(name, "S") {
		return name + "'"
	}
	return name + "'s"
}

// priceFerryUKETS adds a UK ETS line for each crossing between two UK
// ports on the trip: the cargo's share of the crossing's emissions (as for
// the EU ETS) times the share of them under the UK ETS by law, at the UK
// allowance price.
func priceFerryUKETS(out *Response, res sootcase.Result, fd *ferries.Data, req Request, date time.Time, add func(Line) error) error {
	asked := false
	for _, p := range ferryParts(res, fd, req) {
		if p.crossing == nil {
			continue
		}
		c := p.crossing
		cov, applies := fd.UKCoverage(*c, date)
		if !applies {
			continue
		}
		if !strings.Contains(out.FerryCrossing, c.Name) {
			out.FerryCrossing = strings.TrimPrefix(out.FerryCrossing+", "+c.Name, ", ")
		}
		if cov.Share == 0 {
			out.Notes = append(out.Notes, fmt.Sprintf("Ferry: %s: no UK ETS cost: %s.", c.Name, cov.Basis))
			continue
		}
		if req.UKAGbpPerT == 0 {
			if !asked {
				out.Notes = append(out.Notes, "Ferry: give uka_gbp_per_t to price the UK ETS on a crossing between UK ports.")
				asked = true
			}
			continue
		}
		if cov.Note != "" {
			out.Notes = append(out.Notes, "Ferry: "+c.Name+": "+cov.Note+".")
		}
		emT, basis := p.ttwKg/1000, "Sootcase ferry part (GLEC ro-pax default)"
		if t, b, ok := mrvFerry(out, fd, c, p.km, p.loadKg, req, date); ok {
			emT, basis = t, b
		}
		t := emT * cov.Share
		if err := add(Line{Charge: FerryUKETS, Carbon: true, Section: c.Name, Km: round3(p.km), TonnesCO2: round3(t), Rate: req.UKAGbpPerT,
			RateUnit: "GBP/t CO2e", Currency: "GBP", Amount: t * req.UKAGbpPerT,
			Source: ferries.UKETSLaw + "; " + cov.Basis + "; emissions: " + basis, Sources: ukETSSources}); err != nil {
			return err
		}
	}
	return nil
}

var ukETSSources = []rates.Source{
	{Title: "The Greenhouse Gas Emissions Trading Scheme (Amendment) (Extension to Maritime Activities) Order 2026 (SI 2026/392)", URL: "https://www.legislation.gov.uk/uksi/2026/392/made"},
	{Title: "Sootcase (route and emissions)", URL: "https://sootcase.org"},
}

// mrvFerry is a crossing's CO2e (tonnes) for km on it from its ships' MRV
// data: their freight intensity x (truck tare + cargo) x the distance. ok
// is false, with a note, when the crossing has no MRV data or the truck's
// tare isn't given.
func mrvFerry(out *Response, fd *ferries.Data, c *ferries.Crossing, km, loadKg float64, req Request, date time.Time) (float64, string, bool) {
	in, ok := fd.Intensity(*c, date.Year())
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
	grossT := (float64(req.Truck.TareKg) + loadKg) / 1000
	nm := km * ferries.NmPerKm
	names := make([]string, len(in.Ships))
	for i, s := range in.Ships {
		names[i] = s.Name
	}
	basis := fmt.Sprintf("EU MRV %d (%s), %s ships %s: %.1f g CO2e/t·nm x %.1f t (truck %.1f + cargo %.1f) x %.1f nm",
		in.Year.ReportingPeriod, in.Year.Version, c.Name, strings.Join(names, ", "), in.GPerTNm, grossT,
		float64(req.Truck.TareKg)/1000, loadKg/1000, nm)
	if c.NotInMRV != "" {
		out.Notes = append(out.Notes, "Ferry: "+c.NotInMRV)
	}
	return in.GPerTNm * grossT * nm / 1e6, basis, true
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

// etsSources link the EU ETS Directive (consolidated) and Sootcase,
// which gives the emissions.
var etsSources = []rates.Source{
	{Title: "Directive 2003/87/EC (EU ETS), consolidated", URL: "https://eur-lex.europa.eu/eli/dir/2003/87/oj"},
	{Title: "Sootcase (route and emissions)", URL: "https://sootcase.org"},
}

// StationMatchKm is how close a route must pass a toll station's
// junction or booth to count as using it.
const StationMatchKm = 0.5

// sameKm: stations this close along the route are at the same place.
const sameKm = 0.3

// DefaultPointMatchKm is how close the route must pass a toll point
// when its table doesn't say.
const DefaultPointMatchKm = 0.05

// opName is an operator key ("operator|ref") as a line's section:
// "operator (ref)".
func opName(op string) string {
	name, ref, _ := strings.Cut(op, "|")
	if ref == "" {
		return name
	}
	return name + " (" + ref + ")"
}

// lapsed finds the crossings, zones and CO2 prices on diesel the trip
// meets under rates that ended with no successor here yet: each such
// table, priced on its last day, says whether the route would pay it.
func lapsed(set *tariffs.Set, req Request, out *Response, route *track, fuelL float64, date time.Time) []Missing {
	var ms []Missing
	for _, kind := range []string{tariffs.Crossings, tariffs.Zone, tariffs.FuelCO2} {
		for _, ds := range set.Lapsed(kind, date) {
			last, err := time.Parse(time.DateOnly, ds.ValidTo)
			if err != nil {
				continue
			}
			scratch := Response{CountryKm: out.CountryKm, RegionKm: out.RegionKm}
			n, lineCharge := 0, ""
			p := newPricer(req, last, &scratch, func(l Line) error { n++; lineCharge = l.Charge; return nil })
			one := &tariffs.Set{All: []*tariffs.Dataset{ds}}
			charge := RoadToll
			switch kind {
			case tariffs.Crossings:
				err = p.priceCrossings(one, route)
			case tariffs.Zone:
				charge, err = AreaCharge, p.priceZones(one, route)
			case tariffs.FuelCO2:
				charge, err = FuelCO2, p.priceFuel(one, fuelL)
			}
			if err == nil && n > 0 {
				if lineCharge == FerryFare {
					charge = FerryFare
				}
				ms = append(ms, Missing{Area: ds.Area(), Charge: charge, Name: ds.Name, Reason: "ended", Ended: ds.ValidTo})
			}
		}
	}
	return ms
}

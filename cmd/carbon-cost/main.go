// Command carbon-cost prices the carbon and road charges of a truck trip
// (package cost): road tolls by country (with their CO2 part), bridge,
// tunnel and ferry charges, the ETS on ferry crossings, national CO2
// prices on fuel and ETS2 from 2028.
//
//	carbon-cost calc -from DKCPH -to DEHAM -mass-kg 40000 -axles 5 -euro 6 -co2-class 1 -cargo-kg 20000
//	carbon-cost serve -addr :8090
//	carbon-cost rates
package main

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"html"
	"io"
	"io/fs"
	"log/slog"
	"maps"
	"math"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"runtime/debug"
	"slices"
	"sort"
	"strconv"
	"strings"
	"text/tabwriter"
	"time"
	"unicode/utf8"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/fx"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/site"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/carbon-cost/tariffs"
	"github.com/majidkabir/sootcase/pkg/borders"
)

// version is the release, set at build time with -ldflags "-X
// main.version=v0.28.0" (the Dockerfile and release workflow do).
var version = "dev"

// buildVersion is version: set by the build, or the module's release (go
// install of a tag), or dev with the commit otherwise (a checkout, whose
// Go stamps a pseudo-version, or go install of a commit).
func buildVersion() string {
	if version != "dev" {
		return version
	}
	return versionOf(debug.ReadBuildInfo())
}

func versionOf(bi *debug.BuildInfo, ok bool) string {
	if !ok {
		return version
	}
	v := bi.Main.Version
	rev, dirty := "", false
	if m := pseudoVersion.FindStringSubmatch(v); m != nil {
		rev, dirty = m[1], m[2] != ""
	} else if v != "" && v != "(devel)" && !strings.HasSuffix(v, "+dirty") {
		return v // a release (a checkout at its tag with changes is dev)
	}
	for _, s := range bi.Settings {
		switch s.Key {
		case "vcs.revision":
			rev = s.Value
		case "vcs.modified":
			dirty = s.Value == "true"
		}
	}
	if len(rev) < 7 {
		return version
	}
	if dirty {
		return "dev+" + rev[:7] + ".dirty"
	}
	return "dev+" + rev[:7]
}

// pseudoVersion is Go's version of a commit that no tag names
// (v0.120.1-0.20261127223745-82420437f9fd, +dirty with changes).
var pseudoVersion = regexp.MustCompile(`[-.]\d{14}-([0-9a-f]{12})(\+dirty)?$`)

const usage = `carbon-cost prices the carbon and road charges of a truck trip.

Commands:
  calc    price one trip, or each row of a CSV file (-csv; -shipment-rows for a row per shipment)
  report  add up priced CSV files by customer, month or any column (-by customer,month)
  serve   run the HTTP API (POST /v1/carbon-cost, /batch, /csv, /report, GET /v1/rates, GET /v1/rates/{file})
  rates   list the toll tables

Run "carbon-cost <command> -h" for a command's flags.
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "calc":
		err = calc(os.Args[2:])
	case "serve":
		err = serve(os.Args[2:])
	case "rates":
		err = listRates()
	case "report":
		err = report(os.Args[2:])
	default:
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

// sootcaseFlags adds the flags for reaching Sootcase.
func sootcaseFlags(fs *flag.FlagSet) *sootcase.Client {
	c := &sootcase.Client{APIKey: os.Getenv("SOOTCASE_API_KEY")}
	fs.StringVar(&c.BaseURL, "sootcase", envOr("SOOTCASE_URL", sootcase.DefaultURL), "Sootcase server URL (env SOOTCASE_URL)")
	return c
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func calculator(sc *sootcase.Client) (cost.Calculator, error) {
	set, err := tariffs.Load()
	if err != nil {
		return cost.Calculator{}, err
	}
	fd, err := ferries.Load()
	if err != nil {
		return cost.Calculator{}, err
	}
	bix, err := borders.Default()
	if err != nil {
		return cost.Calculator{}, err
	}
	fxCache := &fx.Cache{URL: os.Getenv("FX_URL")}
	rx, err := roads.Default()
	if err != nil {
		return cost.Calculator{}, err
	}
	return cost.Calculator{Sootcase: *sc, Tariffs: set, Ferries: &fd, Borders: bix, Roads: rx, FX: fxCache.Get, FXOn: fx.OnDate, Version: buildVersion()}, nil
}

func parseCalc(args []string, errs flag.ErrorHandling) (cost.Request, calcOpts, error) {
	return parseCalcWith(args, errs, nil)
}

// calcFlagNames are calc's flags, without the dash.
func calcFlagNames() map[string]bool {
	names := map[string]bool{}
	parseCalcWith(nil, flag.ContinueOnError, func(fs *flag.FlagSet) {
		fs.VisitAll(func(f *flag.Flag) { names[f.Name] = true })
	})
	return names
}

// parseCalcWith is parseCalc; inspect, if not nil, sees the flags before
// they are parsed.
func parseCalcWith(args []string, errs flag.ErrorHandling, inspect func(*flag.FlagSet)) (cost.Request, calcOpts, error) {
	fs := flag.NewFlagSet("calc", errs)
	if errs == flag.ContinueOnError {
		fs.SetOutput(io.Discard) // a CSV row's error goes in its row
	}
	sc := sootcaseFlags(fs)
	var req cost.Request
	from := fs.String("from", "", "origin: UN/LOCODE (DKCPH), IATA code or lat,lon")
	to := fs.String("to", "", "destination, as -from")
	fs.StringVar(&req.Date, "date", "", "trip date YYYY-MM-DD (default today)")
	fs.Float64Var(&req.CargoKg, "cargo-kg", 0, "cargo weight in kg")
	fs.StringVar(&req.VehicleType, "vehicle", "", "Sootcase vehicle type (default "+cost.DefaultVehicleType+", or GLEC's electric truck of the mass for CO2 class 5)")
	fs.IntVar(&req.Truck.MaxMassKg, "mass-kg", 40000, "truck's technically permissible maximum mass, kg")
	fs.IntVar(&req.Truck.Axles, "axles", 5, "axles (truck and trailer)")
	fs.IntVar(&req.Truck.Euro, "euro", 6, "Euro emission standard 0-6 (EEV = 5)")
	fs.IntVar(&req.Truck.CO2Class, "co2-class", 1, "EU CO2 emission class 1-5 (5 = zero-emission)")
	fs.IntVar(&req.Truck.TareKg, "tare-kg", 0, "truck's own weight with trailer, kg (lets ferries use their MRV data)")
	fs.IntVar(&req.Truck.MotorAxles, "motor-axles", 0, "the motor vehicle's own axles (e.g. 2 for a tractor; Lithuania, Iceland, Poland's A2 and A4)")
	fs.IntVar(&req.Truck.MotorMassKg, "motor-mass-kg", 0, "the motor vehicle's own permissible maximum mass, kg (Iceland's km fee)")
	fs.IntVar(&req.Truck.TrailerMassKg, "trailer-mass-kg", 0, "the trailer's own permissible maximum mass, kg (Iceland's km fee)")
	fs.Float64Var(&req.Truck.LengthM, "length-m", 0, "truck length with trailer, m, for bridge, tunnel and ferry prices by length (default 16.5)")
	fs.Float64Var(&req.Truck.HeightM, "height-m", 0, "truck height with load, m: the route keeps to roads the truck may drive (with its width, length and weight)")
	fs.Float64Var(&req.Truck.WidthM, "width-m", 0, "truck width, m, for the route")
	fs.IntVar(&req.Truck.AxleLoadKg, "axle-load-kg", 0, "heaviest axle load, kg, for the route")
	fs.IntVar(&req.Truck.CapacityKg, "capacity-kg", 0, "load capacity, kg (Croatian ferries price a semi-trailer by its capacity)")
	fs.BoolVar(&req.Truck.Hazmat, "hazmat", false, "carries dangerous goods (ADR): the route avoids roads barred to them")
	fs.StringVar(&req.Truck.ADRTunnelCode, "tunnel-code", "", "the load's ADR tunnel restriction code (B, C, D or E): the route avoids tunnels it may not enter")
	fs.Float64Var(&req.EUAEurPerT, "eua", 0, "EU ETS allowance price, EUR/t, for ferry crossings")
	fs.Float64Var(&req.UKAGbpPerT, "uka", 0, "UK ETS allowance price, GBP/t, for crossings between UK ports (from 1 July 2026)")
	fs.IntVar(&req.Alternatives, "alternatives", 0, "price up to this many routes of each leg (2 to 5): Sootcase's and its alternatives, listed under Routes")
	fs.StringVar(&req.Route, "route", "", "the route to price: primary (default), cheapest (the lowest charges and diesel), or a route's id from Routes (alt1; leg2:alt1 on a trip with stops)")
	avoidFerries := fs.Bool("avoid-ferries", false, "route on land only")
	fs.StringVar(&req.FerryETSBasis, "ferry-ets-basis", "", "a ferry's EU ETS: \"surcharge\" (default: its line's published surcharge where it has one) or \"emissions\" (the cargo's share of the ships' emissions)")
	fs.Float64Var(&req.FerryETSShare, "ferry-ets-share", 0, "share of ferry emissions under the ETS on a crossing the tool doesn't know (default 1; 0.5 to/from a non-EEA port)")
	fs.Float64Var(&req.ETS2EurPerT, "ets2", 0, "ETS2 allowance price, EUR/t, for trips from 2028")
	fs.StringVar(&req.FuelCountry, "fuel-country", "", "where the road fuel is bought (ISO code, e.g. DE), for national CO2 prices on fuel; default along the route by road km")
	fs.Float64Var(&req.DieselL, "diesel-l", 0, "litres of diesel the truck burns on the road, for the CO2 prices on fuel and ETS2")
	fs.Float64Var(&req.LPer100Km, "l-per-100km", 0, "the truck's diesel per 100 km (default: a new truck of its VECTO group with its load, COM(2024) 313)")
	dprice := fs.String("diesel-price", "", "what the truck pays for diesel, EUR per litre without VAT: one price (1.45), by country (PL=1.25,DE=1.55), or both (1.45,PL=1.25); a decimal comma too (1,45;PL=1,25); default the EU Weekly Oil Bulletin's national averages of the trip's week")
	fs.BoolVar(&req.DieselRefunds, "diesel-refunds", false, "take off the hauliers' partial refund of the excise on diesel where the law sets one (France, Italy, Spain, Hungary, Croatia and Slovenia from 7.5 t; Portugal from 35 t)")
	bought := fs.String("fuel-bought", "", "litres of diesel bought by country, e.g. DE=300,PL=150: the trip's diesel and where its CO2 prices are paid")
	via := fs.String("via", "", "stops between -from and -to, separated by ; (e.g. DEHAM;DEBER)")
	back := fs.Bool("return", false, "the truck returns empty to -from at the end")
	pathFile := fs.String("path", "", "the way driven, priced instead of Sootcase's route: a GPX file (track or route points) or JSON ([[lon,lat],...] or a GeoJSON LineString)")
	rfmsFiles := fs.String("rfms", "", "rFMS 4.0 responses from the truck maker's API (/vehiclepositions, /vehiclestatuses) for the trip's hours, files separated by ,: the way driven, the diesel burnt (engineTotalFuelUsed) and the date")
	vin := fs.String("vin", "", "the vehicle in the -rfms files, when they hold several")
	ckm := fs.String("country-km", "", "price a trip with no route on its km by country (or ISO 3166-2 region), e.g. DE=320,PL=410 (as the other lists by country, ; between them too, and a decimal comma: DE=320,5; not 1,200 nor 3.200: 3200, or 3.2?; a country twice adds up), from a tachograph; without -from and -to")
	ships := fs.String("shipments", "", "shipments instead of -cargo-kg, separated by ;: id:kg:from-to with stops numbered from 0 (-from) to the last (-to), e.g. A:12000:0-2;B:8000:1-2, and :ldm=2.4,pallets=6 for -cost-share-by")
	fs.StringVar(&req.CostShareBy, "cost-share-by", "", "share the costs among the shipments by tkm (default), loading_m or pallets (per km of each one's route); emissions are always by tkm")
	fs.Float64Var(&req.DKKPerEUR, "dkk-per-eur", 0, "DKK per EUR (default the ERM II central rate 7.46038)")
	tolled := fs.String("tolled-share", "", "share of each country's km on tolled roads, e.g. DK=1,DE=0.9 (default: the road classes from OpenStreetMap where known, else 1)")
	mway := fs.String("motorway-share", "", "share of tolled km on motorways where rates differ by road type, e.g. CZ=0.9,BE-BRU=0.2")
	fxs := fs.String("fx", "", "exchange rates in units per euro, e.g. CHF=0.93,CZK=24.3 (default the ECB reference rates)")
	zone := fs.String("env-zone-km", "", "km in environmental zones by country, e.g. DK=4")
	cmp := fs.String("compare", "", "also price the trip for these CO2 classes, e.g. 1,4,5")
	fs.Float64Var(&req.TripsPerYear, "trips-per-year", 0, "trips per year, for yearly savings in the comparison")
	fs.BoolVar(&req.ETC, "etc", false, "pays tolls by electronic toll device or agreement (operators' discounts)")
	fs.StringVar(&req.Time, "time", "", "departure time HH:MM, for congestion taxes, free hours, days of time-based charges and driving bans")
	fs.Float64Var(&req.AvgSpeedKmh, "avg-speed", 0, "average speed km/h for passage times (default 70)")
	fs.BoolVar(&req.DriverRest, "driver-rest", false, "add one driver's breaks and daily rests to passage times and the trip's time (Regulation (EC) No 561/2006)")
	fs.StringVar(&req.Currency, "currency", "", "also give the totals in this currency (DKK, PLN, SEK, ...), at the rate its charges are converted at: the ECB's of the trip's date, or -fx")
	fs.Float64Var(&req.KWhPer100Km, "kwh-per-100km", 0, "an electric truck's (CO2 class 5) kWh per 100 km, for its electricity and class 5 in -compare")
	fs.Float64Var(&req.ElectricityKWh, "electricity-kwh", 0, "kWh an electric truck used on the trip (rFMS totalElectricEnergyUsed, charging records)")
	fs.Float64Var(&req.ElectricityEURPerKWh, "electricity-price", 0, "what an electric truck pays per kWh, EUR without VAT (blank: Eurostat's average for businesses where it charges)")
	fs.Float64Var(&req.DriverEURPerH, "driver-eur-h", 0, "the driver's cost, EUR per hour of driving: adds a trip cost (charges, diesel, driver, vehicle), which -route cheapest compares")
	fs.Float64Var(&req.VehicleEURPerKm, "vehicle-eur-km", 0, "the truck's own cost, EUR per road km (tyres, maintenance, depreciation): adds to the trip cost")
	fs.BoolVar(&req.Night, "night", false, "the trip passes night-tariff sections at night (22:00-05:00, Austria's A 13)")
	asJSON := fs.Bool("json", false, "print the result as JSON")
	csvIn := fs.String("csv", "", "price each row of this CSV file (\"-\": standard input) and print a CSV of the results: its header names the flags above (from, to, date, cargo-kg, mass-kg, ...), each row's values override the command line's; a CSV separated by ; (Excel's where the decimal symbol is a comma) has decimal commas and dates such as 03.11.2026, and is written back so")
	if inspect != nil {
		inspect(fs)
	}
	if err := fs.Parse(args); err != nil {
		return req, calcOpts{}, err
	}
	opts := calcOpts{json: *asJSON, csv: *csvIn, sc: sc}

	var err error
	if *bought != "" {
		// Each purchase as given, a country twice too (as fuel_purchases).
		vals, err := countryValues(*bought, true)
		if err != nil {
			return req, opts, fmt.Errorf("-fuel-bought: %w", err)
		}
		for _, cv := range vals {
			if cv.cc == "" {
				return req, opts, fmt.Errorf("-fuel-bought: %v is not COUNTRY=litres", cv.v)
			}
			req.FuelPurchases = append(req.FuelPurchases, cost.FuelPurchase{Country: cv.cc, Litres: cv.v})
		}
	}
	if *avoidFerries {
		req.Ferry = "avoid"
	}
	if *dprice != "" {
		if err := dieselPriceFlag(&req, *dprice); err != nil {
			return req, opts, fmt.Errorf("-diesel-price: %w", err)
		}
	}
	if *pathFile != "" {
		if req.Path, err = readPath(*pathFile); err != nil {
			return req, opts, fmt.Errorf("-path: %w", err)
		}
	}
	if *rfmsFiles != "" {
		if err := rfmsFlags(&req, &opts, strings.Split(*rfmsFiles, ","), *vin, *ckm != ""); err != nil {
			return req, opts, fmt.Errorf("-rfms: %w", err)
		}
	}
	switch {
	case *ckm != "":
		if req.CountryKm, err = byCountry(*ckm, true); err != nil {
			return req, opts, fmt.Errorf("-country-km: %w", err)
		}
		if *from != "" || *to != "" || *via != "" || *ships != "" || *back {
			return req, opts, errors.New("-country-km prices a trip with no route: not with -from, -to, -via, -shipments or -return")
		}
	case *csvIn != "" && (*from == "" || *to == ""):
		return req, opts, nil // the rows give them
	default:
		if err := stopsFlags(&req, *from, *to, *via, *ships, *back); err != nil {
			return req, opts, err
		}
	}
	if req.TolledShare, err = byCountry(*tolled, false); err != nil {
		return req, opts, fmt.Errorf("-tolled-share: %w", err)
	}
	if req.MotorwayShare, err = byCountry(*mway, false); err != nil {
		return req, opts, fmt.Errorf("-motorway-share: %w", err)
	}
	if req.FX, err = byCountry(*fxs, false); err != nil {
		return req, opts, fmt.Errorf("-fx: %w", err)
	}
	if req.EnvZoneKm, err = byCountry(*zone, true); err != nil {
		return req, opts, fmt.Errorf("-env-zone-km: %w", err)
	}
	if req.CompareCO2Classes, err = ints(*cmp); err != nil {
		return req, opts, fmt.Errorf("-compare: %w", err)
	}
	return req, opts, nil
}

// calcOpts are calc's flags that aren't the trip.
type calcOpts struct {
	json bool
	csv  string
	sc   *sootcase.Client
	rfms string // what the trip took from rFMS
}

// dieselPriceFlag reads -diesel-price: a price for all litres, prices by
// country (CC=price), or both, as countryValues reads them.
func dieselPriceFlag(req *cost.Request, v string) error {
	vals, err := countryValues(v, false)
	if err != nil {
		return err
	}
	bare := 0
	for _, cv := range vals {
		if cv.v <= 0 {
			return fmt.Errorf("%q: give EUR per litre, e.g. 1.45 or PL=1.25", v)
		}
		if cv.cc == "" {
			if bare++; bare > 1 {
				return fmt.Errorf("%q: one price for all litres (a decimal point: 1.45), and CC=price for a country's", v)
			}
			req.DieselEURPerL = cv.v
			continue
		}
		if req.DieselEURPerLByCountry == nil {
			req.DieselEURPerLByCountry = map[string]float64{}
		}
		if _, twice := req.DieselEURPerLByCountry[cv.cc]; twice {
			return fmt.Errorf("%q: %s given twice", v, cv.cc)
		}
		req.DieselEURPerLByCountry[cv.cc] = cv.v
	}
	return nil
}

// countryValue is a value of a list by country; cc is "" for a value
// for all.
type countryValue struct {
	cc string
	v  float64
}

// countryValues reads a list of values by country (DE=320, a region
// BE-BRU=0.2, a currency CHF=0.93; DE:320 too) or for all (a bare number):
// entries separated by semicolons, or by commas before the next country,
// or between two values that each have a decimal point or comma
// (PL=1.25,1.45; PL=1,25,1,45; not DE=1.234,5). A value has a decimal point (1.45), or a decimal comma
// (320,5; 1,45) but for 1,200 (1200, or 1.2?), which is refused, as is
// 1.200 in a list that has decimal commas, or in a list of counts (km,
// litres: 3.200 km is 3200 written the European way, more likely than a
// km to three decimals). -diesel-price, -country-km,
// -fuel-bought, -tolled-share, -motorway-share, -fx and -env-zone-km take
// it, as the page does (testdata/countryvalues.json is both's cases).
func countryValues(s string, counts bool) ([]countryValue, error) {
	var out []countryValue
	var ms [][]string
	commas := false
	for _, e := range listEntries(s) {
		m := listEntry.FindStringSubmatch(e)
		if m == nil {
			return nil, fmt.Errorf("%q is not COUNTRY=number", e)
		}
		if m[3] == "," && len(m[2]) <= 3 && len(m[4]) == 3 {
			return nil, ambiguous(s, m)
		}
		commas = commas || m[3] == ","
		ms = append(ms, m)
	}
	for _, m := range ms {
		if (commas || counts) && m[3] == "." && len(m[2]) <= 3 && len(m[4]) == 3 {
			return nil, ambiguous(s, m)
		}
		num := m[2]
		if m[4] != "" {
			num += "." + m[4]
		}
		v, err := strconv.ParseFloat(num, 64)
		if err != nil {
			return nil, fmt.Errorf("%q: %s is no number", s, num)
		}
		out = append(out, countryValue{strings.ToUpper(m[1]), v})
	}
	return out, nil
}

// ambiguous is the error for 1,200 or 3.200 (a thousand, or a decimal?):
// the two ways to write it that are read one way (1200, or 1,2 / 3.2;
// 24,3050 for three decimals that are all there).
func ambiguous(s string, m []string) error {
	num := m[2] + m[3] + m[4]
	frac := strings.TrimRight(m[4], "0")
	dec := m[2]
	switch {
	case frac == "":
	case len(frac) == 3:
		dec += m[3] + frac + "0"
	default:
		dec += m[3] + frac
	}
	return fmt.Errorf("%q: %s is %s%s or %s? write %s%s, or %s", s, num, m[2], m[4], strings.Replace(num, m[3], ".", 1), m[2], m[4], dec)
}

// listEntries splits a list as countryValues says.
func listEntries(s string) []string {
	var out []string
	add := func(e string) {
		if e = strings.Trim(e, " \t"); e != "" {
			out = append(out, e)
		}
	}
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == ',' {
			rest := strings.TrimLeft(s[i+1:], " \t")
			letter := rest != "" && (rest[0] >= 'A' && rest[0] <= 'Z' || rest[0] >= 'a' && rest[0] <= 'z')
			// A bare value after one with its decimal point or comma, itself
			// with one (PL=1.25,1.45), not DE=1.234,5 (1234.5, the European way?).
			next := leadingNumber.FindString(rest)
			if !letter && !(strings.ContainsAny(valuePart(s[start:i]), ".,") && strings.ContainsAny(next, ".,")) {
				continue // a decimal comma, or refused with the entry
			}
		} else if s[i] != ';' {
			continue
		}
		add(s[start:i])
		start = i + 1
	}
	add(s[start:])
	return out
}

// valuePart is an entry's value (after its = or :).
func valuePart(e string) string {
	if i := strings.LastIndexAny(e, "=:"); i >= 0 {
		return e[i+1:]
	}
	return e
}

var leadingNumber = regexp.MustCompile(`^[0-9]+(?:[.,][0-9]+)?`)

var listEntry = regexp.MustCompile(`^(?:([A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,3})?)[ \t]*[=:][ \t]*)?(\d+)(?:([.,])(\d+))?$`)

// rfmsFlags takes the way driven, the diesel and the date from rFMS
// files, where the other flags don't give them.
func rfmsFlags(req *cost.Request, opts *calcOpts, names []string, vin string, countryKm bool) error {
	for i := range names {
		names[i] = strings.TrimSpace(names[i])
	}
	t, err := readRFMS(names, vin)
	if err != nil {
		return err
	}
	if len(t.Path) >= 2 && !countryKm {
		if len(req.Path) > 0 {
			return errors.New("not with -path: rFMS gives the way driven")
		}
		req.Path = t.Path
	}
	if t.DieselL > 0 && req.DieselL == 0 && req.LPer100Km == 0 && len(req.FuelPurchases) == 0 {
		req.DieselL = math.Round(t.DieselL*1000) / 1000
	}
	if t.KWh > 0 && req.ElectricityKWh == 0 && req.KWhPer100Km == 0 {
		req.ElectricityKWh = math.Round(t.KWh*1000) / 1000
	}
	if req.Date == "" && !t.From.IsZero() {
		// The day where the truck starts (rFMS times are UTC).
		cc := ""
		if bix, err := borders.Default(); err == nil && len(t.Path) > 0 {
			cc = bix.Country(t.Path[0][0], t.Path[0][1])
		}
		req.Date = t.From.In(cost.LocalZone(cc)).Format(time.DateOnly)
	}
	opts.rfms = t.summary()
	return nil
}

func calc(args []string) error {
	// -shipment-rows is calcCSV's, not a trip's.
	tripArgs, _ := withoutFlag(args, "shipment-rows")
	req, opts, err := parseCalc(tripArgs, flag.ExitOnError)
	if err != nil {
		return err
	}
	if opts.rfms != "" {
		fmt.Fprintln(os.Stderr, opts.rfms)
	}
	c, err := calculator(opts.sc)
	if err != nil {
		return err
	}
	if opts.csv != "" {
		return calcCSV(c, args, opts.csv)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	res, err := c.Calculate(ctx, req)
	if err != nil {
		return err
	}
	if opts.json {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(res)
	}
	printResult(res, req.CostShareBy)
	return nil
}

// location reads a code (DKCPH, CPH) or "lat,lon".
// stopsFlags sets the trip's stops and shipments from -from, -to, -via,
// -shipments and -return.
func stopsFlags(req *cost.Request, from, to, via, ships string, back bool) error {
	var err error
	if req.From, err = location(from); err != nil {
		return fmt.Errorf("-from: %w", err)
	}
	if req.To, err = location(to); err != nil {
		return fmt.Errorf("-to: %w", err)
	}
	if via != "" || back {
		req.Stops = []sootcase.Location{req.From}
		for _, v := range strings.Split(via, ";") {
			if strings.TrimSpace(v) == "" {
				continue
			}
			l, err := location(v)
			if err != nil {
				return fmt.Errorf("-via: %w", err)
			}
			req.Stops = append(req.Stops, l)
		}
		req.Stops = append(req.Stops, req.To)
		if back {
			req.Stops = append(req.Stops, req.From)
		}
		req.From, req.To = sootcase.Location{}, sootcase.Location{}
	}
	if ships != "" {
		if req.Shipments, err = shipmentsFlag(ships); err != nil {
			return fmt.Errorf("-shipments: %w", err)
		}
		req.CargoKg = 0 // the shipments replace -cargo-kg
	} else if back {
		// The cargo goes to -to; the way back is empty.
		req.Shipments = []cost.Shipment{{WeightKg: req.CargoKg, To: len(req.Stops) - 2}}
		req.CargoKg = 0
	}
	return nil
}

// shipmentsFlag reads id:kg:from-to;... .
func shipmentsFlag(s string) ([]cost.Shipment, error) {
	var out []cost.Shipment
	for _, part := range strings.Split(s, ";") {
		f := strings.Split(strings.TrimSpace(part), ":")
		if len(f) != 3 && len(f) != 4 {
			return nil, fmt.Errorf("%q: give id:kg:from-to, or id:kg:from-to:ldm=2.4,pallets=6", part)
		}
		kg, err := strconv.ParseFloat(f[1], 64)
		a, b, ok := strings.Cut(f[2], "-")
		from, err1 := strconv.Atoi(a)
		to, err2 := strconv.Atoi(b)
		if err != nil || !ok || err1 != nil || err2 != nil {
			return nil, fmt.Errorf("%q: give id:kg:from-to", part)
		}
		sh := cost.Shipment{ID: f[0], WeightKg: kg, From: from, To: to}
		if len(f) == 4 {
			// Its loading metres and pallet places, for -cost-share-by.
			for _, kv := range strings.Split(f[3], ",") {
				k, v, _ := strings.Cut(strings.TrimSpace(kv), "=")
				x, err := strconv.ParseFloat(v, 64)
				switch {
				case err != nil:
					return nil, fmt.Errorf("%q: %q is not key=number", part, kv)
				case k == "ldm":
					sh.LoadingM = x
				case k == "pallets":
					sh.Pallets = x
				default:
					return nil, fmt.Errorf("%q: %q: give ldm= or pallets=", part, k)
				}
			}
		}
		out = append(out, sh)
	}
	return out, nil
}

func location(s string) (sootcase.Location, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return sootcase.Location{}, errors.New("required")
	}
	if lat, lon, ok := strings.Cut(s, ","); ok {
		la, err1 := strconv.ParseFloat(strings.TrimSpace(lat), 64)
		lo, err2 := strconv.ParseFloat(strings.TrimSpace(lon), 64)
		if err1 != nil || err2 != nil || la < -90 || la > 90 || lo < -180 || lo > 180 {
			return sootcase.Location{}, fmt.Errorf("%q is not lat,lon", s)
		}
		return sootcase.Location{Lat: la, Lon: lo}, nil
	}
	return sootcase.Location{Code: strings.ToUpper(s)}, nil
}

// ints reads "1,4,5".
func ints(s string) ([]int, error) {
	if strings.TrimSpace(s) == "" {
		return nil, nil
	}
	var out []int
	for _, f := range strings.Split(s, ",") {
		n, err := strconv.Atoi(strings.TrimSpace(f))
		if err != nil {
			return nil, fmt.Errorf("%q is not a number", f)
		}
		out = append(out, n)
	}
	return out, nil
}

// byCountry reads "DK=1,DE=0.9".
// byCountry reads a list by country (countryValues, no bare values): a
// country given twice adds up where sum (km: a tachograph's DE, PL, DE
// again), else is refused (a share, a rate).
func byCountry(s string, sum bool) (map[string]float64, error) {
	vals, err := countryValues(s, sum) // the lists that add up are counts (km)
	if err != nil || vals == nil {
		return nil, err
	}
	out := map[string]float64{}
	for _, cv := range vals {
		if cv.cc == "" {
			return nil, fmt.Errorf("%q: %v is not COUNTRY=number", s, cv.v)
		}
		if _, twice := out[cv.cc]; twice && !sum {
			return nil, fmt.Errorf("%q: %s given twice", s, cv.cc)
		}
		out[cv.cc] += cv.v
	}
	return out, nil
}

func printResult(r cost.Response, shareBy string) {
	fmt.Printf("Trip on %s: %.1f km", r.Date, r.DistanceKm)
	if r.FerryKm > 0 {
		fmt.Printf(" (%.1f km by ferry)", r.FerryKm)
	}
	fmt.Println()
	if !r.Complete {
		fmt.Println("INCOMPLETE: the total leaves out charges this trip meets:")
		for _, m := range r.Missing {
			fmt.Println("  - " + m.Message())
		}
	}
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', tabwriter.AlignRight)
	fmt.Fprintln(w, "Charge\tCountry\tPart\tBasis\tRate\tAmount\tEUR\t")
	for _, l := range r.Lines {
		basis := fmt.Sprintf("%.1f km", l.Km)
		if l.Litres > 0 {
			basis = fmt.Sprintf("%.1f l", l.Litres)
		}
		if l.TonnesCO2 > 0 {
			basis = fmt.Sprintf("%.3f t CO2e", l.TonnesCO2)
		}
		if l.Days > 0 {
			basis = fmt.Sprintf("%d day(s)", l.Days)
		}
		where := l.Country
		if l.Region != "" {
			where = l.Region
		}
		part := l.Component
		if l.Carbon && part == "" {
			part = "co2"
		}
		if l.Road != "" || l.Area != "" {
			part += " (" + strings.TrimPrefix(l.Road+", "+l.Area, ", ")
			part = strings.TrimSuffix(part, ", ") + ")"
		}
		if l.Section != "" {
			part += ": " + l.Section
		}
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%g %s\t%.2f %s\t%.2f\t\n", l.Charge, where, part, basis, l.Rate, l.RateUnit, l.Amount, l.Currency, l.AmountEUR)
	}
	w.Flush()
	incomplete := ""
	if !r.Complete {
		incomplete = " (incomplete: see above)"
	}
	fmt.Printf("Total: EUR %.2f, of which carbon EUR %.2f%s\n", r.TotalEUR, r.CarbonEUR, incomplete)
	if tr := r.Trip; tr != nil {
		empty := ""
		if tr.EmptyKm > 0 {
			empty = fmt.Sprintf(", %.1f km empty", tr.EmptyKm)
		}
		fmt.Printf("Truck: %.1f road km%s, %.1f l diesel (%s)\n", tr.RoadKm, empty, tr.FuelL, tr.FuelBasis)
	}
	if f := r.Fuel; f != nil {
		var parts []string
		for _, b := range f.ByCountry {
			if b.EURPerL > 0 {
				parts = append(parts, fmt.Sprintf("%s %.1f l x %.4f", b.Country, b.Litres, b.EURPerL))
			} else {
				parts = append(parts, fmt.Sprintf("%s %.1f l, no price", b.Country, b.Litres))
			}
		}
		inc := ""
		if !f.Complete {
			inc = " (incomplete)"
		}
		if f.RefundEUR > 0 {
			inc += fmt.Sprintf(" after EUR %.2f of excise refunds", f.RefundEUR)
		}
		fmt.Printf("Fuel: EUR %.2f without VAT%s (%s); with fuel: EUR %.2f (the CO2 prices on fuel, EUR %.2f, are in the diesel price)\n",
			f.EUR, inc, strings.Join(parts, ", "), r.WithFuelEUR, f.InPriceEUR)
	}
	if e := r.Electricity; e != nil {
		fmt.Printf("Electricity: EUR %.2f without VAT (%.1f kWh x %g, %s); with electricity: EUR %.2f\n", e.EUR, e.KWh, e.EURPerKWh, e.Basis, r.WithFuelEUR)
	}
	if r.Trip != nil && r.Trip.RoutedFor != nil {
		keys := make([]string, 0, len(r.Trip.RoutedFor))
		for k := range r.Trip.RoutedFor {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		parts := make([]string, len(keys))
		for i, k := range keys {
			parts[i] = fmt.Sprintf("%s %v", k, r.Trip.RoutedFor[k])
		}
		fmt.Printf("Routed for the truck: %s\n", strings.Join(parts, ", "))
	}
	if r.Trip != nil && r.Trip.Hours > 0 {
		rest := ""
		if r.Trip.ElapsedH > r.Trip.Hours {
			rest = fmt.Sprintf("; %.2f h with breaks and rests", r.Trip.ElapsedH)
		}
		if r.Trip.BanWaitH > 0 {
			rest += fmt.Sprintf("; %.2f h waiting for driving bans", r.Trip.BanWaitH)
		}
		fmt.Printf("Driving: %.2f h (%s)%s\n", r.Trip.Hours, r.Trip.HoursBasis, rest)
	}
	if r.TripCostEUR > 0 {
		fmt.Printf("Trip cost: EUR %.2f (driver EUR %.2f, vehicle EUR %.2f)\n", r.TripCostEUR, r.DriverEUR, r.VehicleEUR)
	}
	if c := r.InCurrency; c != nil {
		extra := ""
		if c.WithFuel > 0 {
			extra += fmt.Sprintf(", with the energy %.2f", c.WithFuel)
		}
		if c.TripCost > 0 {
			extra += fmt.Sprintf(", trip cost %.2f", c.TripCost)
		}
		fmt.Printf("In %s: %.2f, of which carbon %.2f%s (%g per EUR, %s)\n", c.Currency, c.Total, c.Carbon, extra, c.PerEUR, c.Rate)
	}
	if r.EURPerTkm > 0 {
		fmt.Printf("Per tonne-km: EUR %.4f, of which carbon EUR %.4f\n", r.EURPerTkm, r.CarbonEURPerTkm)
	}
	if r.WTWKg > 0 {
		fmt.Printf("CO2e: %.1f kg well-to-wheel (%.1f tank-to-wheel), %.1f g per tonne-km; %s data: %s\n", r.WTWKg, r.TTWKg, r.IntensityG, r.DataType, r.EmissionsBasis)
		fmt.Printf("Method: %s. %s.\n", r.EmissionsStandard, r.Certification)
	}
	if len(r.Routes) > 0 {
		fmt.Println()
		w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
		tc := r.TripCostEUR > 0
		if tc {
			fmt.Fprintln(w, "Route\tkm\tHours\tFerries\tRoads\tCharges EUR\tWith diesel EUR\tTrip cost EUR\tDifference\t")
		} else {
			fmt.Fprintln(w, "Route\tkm\tHours\tFerries\tRoads\tCharges EUR\tWith diesel EUR\tDifference\t")
		}
		for _, o := range r.Routes {
			id := o.ID
			if o.Chosen {
				id += " *"
			}
			if o.Error != "" {
				fmt.Fprintf(w, "%s\t\t\t\t%s\t\t\t\n", id, o.Error)
				continue
			}
			ferries := strings.Join(o.Ferries, ", ")
			if ferries == "" {
				ferries = "none"
			}
			roads := strings.Join(o.Roads, " ")
			if len(roads) > 40 {
				roads = roads[:40] + "…"
			}
			inc := ""
			if !o.Complete {
				inc = " (incomplete)"
			}
			if tc {
				fmt.Fprintf(w, "%s\t%.1f\t%.2f\t%s\t%s\t%.2f%s\t%.2f\t%.2f\t%+.2f\t\n", id, o.DistanceKm, o.Hours, ferries, roads, o.TotalEUR, inc, o.WithFuelEUR, o.TripCostEUR, o.DiffEUR)
			} else {
				fmt.Fprintf(w, "%s\t%.1f\t%.2f\t%s\t%s\t%.2f%s\t%.2f\t%+.2f\t\n", id, o.DistanceKm, o.Hours, ferries, roads, o.TotalEUR, inc, o.WithFuelEUR, o.DiffEUR)
			}
		}
		w.Flush()
	}
	if len(r.Shipments) > 1 {
		fmt.Println()
		w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', tabwriter.AlignRight)
		fmt.Fprintln(w, "Shipment\tkg\tStops\tkm\ttkm\tShare\tEUR\tEUR/100 kg\tCarbon EUR\tCO2e kg\tg/tkm\tBy country\t")
		for _, s := range r.Shipments {
			var by []string
			for _, cc := range slices.Sorted(maps.Keys(s.ByCountry)) {
				by = append(by, fmt.Sprintf("%s %.2f", cc, s.ByCountry[cc]))
			}
			fmt.Fprintf(w, "%s\t%.0f\t%d-%d\t%.1f\t%.1f\t%.1f%%\t%.2f\t%.2f\t%.2f\t%.1f\t%.1f\t%s\t\n", s.ID, s.WeightKg, s.From, s.To, s.DistanceKm, s.TKm, 100*s.Share, s.TotalEUR, s.EURPer100Kg, s.CarbonEUR, s.WTWKg, s.IntensityG, strings.Join(by, ", "))
		}
		w.Flush()
		switch shareBy {
		case "loading_m", "pallets":
			fmt.Printf("Each shipment's share of the costs is its %s x its own route's km over all of theirs (cost_share_by); its emissions' share is its tonne-km (EN ISO 14083:2023).\n", map[string]string{"loading_m": "loading metres", "pallets": "pallet places"}[shareBy])
		default:
			fmt.Println("Each shipment's share is its tonne-km (weight x its own route's km) over all of theirs (EN ISO 14083:2023).")
		}
	}
	if len(r.Compare) > 0 {
		fmt.Println()
		w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', tabwriter.AlignRight)
		fmt.Fprintln(w, "CO2 class\tTolls EUR\tTotal EUR\tCarbon EUR\tSaving/trip\tSaving/year\tEnergy EUR\tWith energy\tSaving/trip\tSaving/year\t")
		opt := func(v *float64) string {
			if v == nil {
				return ""
			}
			return fmt.Sprintf("%.2f", *v)
		}
		for _, c := range r.Compare {
			year := ""
			if c.SavingPerYearEUR != 0 {
				year = fmt.Sprintf("%.2f", c.SavingPerYearEUR)
			}
			energy, with := "", ""
			if c.WithFuelEUR > 0 {
				energy, with = fmt.Sprintf("%.2f", c.EnergyEUR), fmt.Sprintf("%.2f", c.WithFuelEUR)
			}
			fmt.Fprintf(w, "%d\t%.2f\t%.2f\t%.2f\t%.2f\t%s\t%s\t%s\t%s\t%s\t\n", c.CO2Class, c.TollEUR, c.TotalEUR, c.CarbonEUR, c.SavingEUR, year,
				energy, with, opt(c.SavingWithFuelEUR), opt(c.SavingWithFuelPerYearEUR))
		}
		w.Flush()
		fmt.Println("Energy: the diesel, or an electric truck's electricity at -kwh-per-100km (blank without it) and -electricity-price or Eurostat's average for businesses.")
	}
	for _, n := range r.Notes {
		fmt.Println("- " + n)
	}
	p := r.Provenance
	if p.Sootcase != "" {
		fmt.Printf("\nData: carbon-cost %s; %s\n", p.Version, p.Sootcase)
	} else {
		fmt.Printf("\nData: carbon-cost %s\n", p.Version)
	}
	for _, t := range p.Tables {
		osm := ""
		if t.OSMExtract != "" {
			osm = ", OpenStreetMap " + t.OSMExtract
		}
		fmt.Printf("- %s: %s (tariffs/data/%s, from %s%s)\n", t.Area, t.Name, t.File, t.ValidFrom, osm)
	}
	for _, cc := range slices.Sorted(maps.Keys(p.RoadClasses)) {
		fmt.Printf("- %s road classes: %s\n", cc, p.RoadClasses[cc])
	}
	if p.FerryMRV != "" {
		fmt.Println("- Ferry: " + p.FerryMRV)
	}
	for _, f := range p.FX {
		fmt.Println("- " + f)
	}
	for _, a := range p.Assumed {
		fmt.Println("- Assumed " + a)
	}
}

func listRates() error {
	set, err := tariffs.Load()
	if err != nil {
		return err
	}
	for _, d := range set.All {
		to := d.ValidTo
		if to == "" {
			to = "until replaced"
		}
		fmt.Printf("%s  %s  %s to %s  (%s)\n", d.Area(), d.Name, d.ValidFrom, to, d.File)
		for _, s := range d.Sources() {
			fmt.Printf("    %s\n    %s\n", s.Title, s.URL)
		}
	}
	return nil
}

func serve(args []string) error {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	sc := sootcaseFlags(fs)
	addr := fs.String("addr", envOr("ADDR", ":8090"), "listen address (env ADDR)")
	tiles := fs.String("tiles", envOr("TILE_URL", DefaultTiles), "map tile URL template, {z}/{x}/{y}; \"none\" for no base map (env TILE_URL)")
	public := fs.String("public-url", envOr("PUBLIC_URL", site.DefaultBase), "the service's public URL, for the toll pages' links, canonical URLs and sitemap (env PUBLIC_URL)")
	fs.Parse(args)
	c, err := calculator(sc)
	if err != nil {
		return err
	}
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	h, err := handlerAt(c, *tiles, *public, true)
	if err != nil {
		return err
	}
	srv := &http.Server{Addr: *addr, Handler: h, ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout: 30 * time.Second, WriteTimeout: 3 * time.Minute, IdleTimeout: 2 * time.Minute}
	log.Info("listening", "addr", *addr, "sootcase", sc.BaseURL)
	return srv.ListenAndServe()
}

//go:embed web/openapi.json
var openAPI []byte

//go:embed web/index.html
var indexHTML string

//go:embed web/leaflet
var leafletFS embed.FS

// DefaultTiles is OpenStreetMap's standard tile layer. Its usage policy
// (https://operations.osmfoundation.org/policies/tiles/) allows light use
// with attribution; a busy deployment should set its own tile server.
const DefaultTiles = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

// Handler serves the web page and the HTTP API, and the toll pages at
// DefaultBase. tiles is the map's tile URL template ("" or "none": no
// base map).
func Handler(c cost.Calculator, tiles string) http.Handler {
	h, err := HandlerAt(c, tiles, site.DefaultBase)
	if err != nil {
		panic(err)
	}
	return h
}

// HandlerAt is Handler for a service whose public URL is public: the toll
// pages (package site) link, and give canonical URLs, under it.
func HandlerAt(c cost.Calculator, tiles, public string) (http.Handler, error) {
	return handlerAt(c, tiles, public, false)
}

// handlerAt is HandlerAt; warm builds the toll pages at once, in the
// background, rather than on the first visit.
func handlerAt(c cost.Calculator, tiles, public string, warm bool) (http.Handler, error) {
	pages, err := site.New(c.Tariffs, public, c.Now)
	if err != nil {
		return nil, err
	}
	if tiles == "none" {
		tiles = ""
	}
	imgSrc := "'self' data:"
	if u, err := url.Parse(strings.ReplaceAll(tiles, "{s}", "x")); err == nil && u.Host != "" {
		host := u.Host
		if strings.Contains(tiles, "{s}.") {
			_, rest, _ := strings.Cut(host, ".")
			host = "*." + rest
		}
		imgSrc += " " + u.Scheme + "://" + host
	}
	tj, _ := json.Marshal(tiles)
	page := strings.Replace(indexHTML, "const TILES = \"\";", "const TILES = "+string(tj)+";", 1)
	pub := html.EscapeString(strings.TrimRight(public, "/"))
	page = strings.Replace(page, "<!--meta-->", `<link rel="canonical" href="`+pub+`/">
<meta property="og:type" content="website">
<meta property="og:title" content="carbon-cost: what a truck trip pays for carbon and tolls">
<meta property="og:url" content="`+pub+`/">
<meta property="og:image" content="`+pub+`/tolls.png">
<meta name="twitter:card" content="summary_large_image">`, 1)
	csp := "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src " + imgSrc +
		"; connect-src 'self'; form-action 'none'; base-uri 'none'"
	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Content-Security-Policy", csp)
		w.Write([]byte(page))
	})
	static, _ := fs.Sub(leafletFS, "web")
	files := http.FileServerFS(static)
	mux.HandleFunc("GET /leaflet/{file}", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "public, max-age=86400")
		files.ServeHTTP(w, r)
	})
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok\n")) })
	mux.HandleFunc("GET /v1/openapi.json", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Write(openAPI)
	})
	mux.HandleFunc("GET /v1/rates", func(w http.ResponseWriter, _ *http.Request) { writeJSON(w, http.StatusOK, c.Tariffs.Summaries()) })
	mux.HandleFunc("GET /v1/rates/{cc}/{file}", func(w http.ResponseWriter, r *http.Request) {
		b, ok := c.Tariffs.Raw(r.PathValue("cc") + "/" + r.PathValue("file"))
		if !ok {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "no such dataset"})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write(b)
	})
	mux.HandleFunc("GET /v1/places", func(w http.ResponseWriter, r *http.Request) {
		q := strings.TrimSpace(r.URL.Query().Get("q"))
		if n := utf8.RuneCountInString(q); n < 2 || n > 100 {
			writeJSON(w, http.StatusOK, map[string]any{"places": []sootcase.Place{}})
			return
		}
		ps, err := c.Sootcase.Places(r.Context(), q, 8)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
			return
		}
		if ps == nil {
			ps = []sootcase.Place{}
		}
		w.Header().Set("Cache-Control", "public, max-age=86400")
		writeJSON(w, http.StatusOK, map[string]any{"places": ps})
	})
	mux.HandleFunc("POST /v1/carbon-cost/batch", func(w http.ResponseWriter, r *http.Request) {
		// Each trip is read on its own: one whose JSON is wrong has its
		// error, and doesn't fail the others.
		var req struct {
			Trips []json.RawMessage `json:"trips"`
		}
		if !readJSON(w, r, &req) {
			return
		}
		if len(req.Trips) == 0 || len(req.Trips) > MaxBatch {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": fmt.Sprintf("trips: give 1 to %d", MaxBatch)})
			return
		}
		trips, bad := make([]cost.Request, 0, len(req.Trips)), map[int]string{}
		for i, raw := range req.Trips {
			var t cost.Request
			dec := json.NewDecoder(bytes.NewReader(raw))
			dec.DisallowUnknownFields()
			if err := dec.Decode(&t); err != nil {
				bad[i] = "bad JSON: " + err.Error()
				continue
			}
			trips = append(trips, t)
		}
		ctx, cancel := context.WithTimeout(r.Context(), batchTime(w, len(trips)))
		defer cancel()
		got, out := priceAll(ctx, c.Calculate, trips), make([]BatchItem, len(req.Trips))
		for i := range out {
			if e, ok := bad[i]; ok {
				out[i].Error = e
				continue
			}
			out[i], got = got[0], got[1:]
		}
		writeJSON(w, http.StatusOK, BatchResponse{Results: out})
	})
	// A CSV of trips, as calc -csv takes it (but no flag that reads a
	// file or names a server), priced and sent back with the results.
	mux.HandleFunc("POST /v1/carbon-cost/csv", func(w http.ResponseWriter, r *http.Request) {
		batchTime(w, MaxBatch) // priceCSV gives its trips a minute each
		var buf bytes.Buffer
		rows := r.URL.Query().Get("rows")
		if rows != "" && rows != "trips" && rows != "shipments" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "rows: trips or shipments"})
			return
		}
		labels, err := priceCSV(r.Context(), c.Calculate, nil, http.MaxBytesReader(w, r.Body, 2<<20), &buf, webCSVFlags(), MaxBatch, rows == "shipments")
		if err != nil {
			writeJSON(w, bodyStatus(err), map[string]string{"error": err.Error()})
			return
		}
		if len(labels) > 0 {
			w.Header().Set("X-CSV-Labels", strings.Join(labels, ","))
		}
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		w.Header().Set("Content-Disposition", `attachment; filename="carbon-cost.csv"`)
		w.Write(buf.Bytes())
	})
	// A priced CSV added up by customer, month or any column.
	mux.HandleFunc("POST /v1/carbon-cost/report", func(w http.ResponseWriter, r *http.Request) {
		var buf bytes.Buffer
		if err := summarize([]io.Reader{http.MaxBytesReader(w, r.Body, 8<<20)}, &buf, splitList(r.URL.Query().Get("by"))); err != nil {
			writeJSON(w, bodyStatus(err), map[string]string{"error": err.Error()})
			return
		}
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		w.Header().Set("Content-Disposition", `attachment; filename="carbon-cost-report.csv"`)
		w.Write(buf.Bytes())
	})
	mux.HandleFunc("POST /v1/carbon-cost", func(w http.ResponseWriter, r *http.Request) {
		var req cost.Request
		if !readJSON(w, r, &req) {
			return
		}
		res, err := c.Calculate(r.Context(), req)
		if err != nil {
			// Bad input (ours, or Sootcase refusing the request itself) is
			// the caller's; Sootcase failing, limiting or refusing this
			// server is a bad gateway (busy: unavailable).
			status := http.StatusBadRequest
			var he *sootcase.HTTPError
			var fe *sootcase.Failed
			switch {
			case errors.As(err, &he) && he.Status == http.StatusTooManyRequests:
				status = http.StatusServiceUnavailable
			case errors.As(err, &he) && !he.CallerError():
				status = http.StatusBadGateway
			case errors.As(err, &fe):
				status = http.StatusBadGateway
			}
			writeJSON(w, status, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, res)
	})
	pages.Register(mux)
	if warm {
		pages.Warm()
	}
	return recovered(mux), nil
}

// recovered answers a request that fails by a bug with a 500 saying so,
// and logs it, not by dropping the connection.
func recovered(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if e := recover(); e != nil {
				if e == http.ErrAbortHandler {
					panic(e)
				}
				slog.Error("panic", "method", r.Method, "path", r.URL.Path, "err", e, "stack", string(debug.Stack()))
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": fmt.Sprintf("internal error: %v", e)})
			}
		}()
		h.ServeHTTP(w, r)
	})
}

// readJSON reads a request's body, one JSON object of up to 8 MiB (a path
// of up to cost.MaxPathPoints) with only known fields, into v; else it
// answers 413 or 400 and says false.
func readJSON(w http.ResponseWriter, r *http.Request, v any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20))
	dec.DisallowUnknownFields()
	err := dec.Decode(v)
	if err == nil {
		if _, err = dec.Token(); err == io.EOF {
			err = nil
		} else if err == nil {
			err = errors.New("more after the JSON object")
		}
	}
	var big *http.MaxBytesError
	switch {
	case errors.As(err, &big):
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": fmt.Sprintf("the body is over %d bytes", big.Limit)})
	case err != nil:
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad JSON: " + err.Error()})
	default:
		return true
	}
	return false
}

// bodyStatus is the status for a request body that couldn't be read: 413
// over its limit, else 400.
func bodyStatus(err error) int {
	if big := (*http.MaxBytesError)(nil); errors.As(err, &big) {
		return http.StatusRequestEntityTooLarge
	}
	return http.StatusBadRequest
}

// writeJSON writes v with the status; one that can't be written as JSON
// (an infinite or NaN number) is a 500 saying so, not an empty 200.
func writeJSON(w http.ResponseWriter, status int, v any) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		buf.Reset()
		status = http.StatusInternalServerError
		_ = json.NewEncoder(&buf).Encode(map[string]string{"error": "the result can't be written as JSON: " + err.Error()})
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(buf.Bytes())
}

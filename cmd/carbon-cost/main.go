// Command carbon-cost prices the carbon and road charges of a truck trip:
// km-based road tolls by country (with their CO2 part), the EU ETS on
// ferry crossings and ETS2 on road fuel from 2028.
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
	"runtime/debug"
	"slices"
	"strconv"
	"strings"
	"text/tabwriter"
	"time"

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

// buildVersion is version, with the commit when built from a checkout.
func buildVersion() string {
	if version != "dev" {
		return version
	}
	if bi, ok := debug.ReadBuildInfo(); ok {
		for _, s := range bi.Settings {
			if s.Key == "vcs.revision" && len(s.Value) >= 7 {
				return "dev+" + s.Value[:7]
			}
		}
	}
	return version
}

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
	fs.StringVar(&req.VehicleType, "vehicle", cost.DefaultVehicleType, "Sootcase vehicle type")
	fs.IntVar(&req.Truck.MaxMassKg, "mass-kg", 40000, "truck's technically permissible maximum mass, kg")
	fs.IntVar(&req.Truck.Axles, "axles", 5, "axles (truck and trailer)")
	fs.IntVar(&req.Truck.Euro, "euro", 6, "Euro emission standard 0-6 (EEV = 5)")
	fs.IntVar(&req.Truck.CO2Class, "co2-class", 1, "EU CO2 emission class 1-5 (5 = zero-emission)")
	fs.IntVar(&req.Truck.TareKg, "tare-kg", 0, "truck's own weight with trailer, kg (lets ferries use their MRV data)")
	fs.IntVar(&req.Truck.MotorAxles, "motor-axles", 0, "the motor vehicle's own axles (e.g. 2 for a tractor; Lithuania, Iceland)")
	fs.IntVar(&req.Truck.MotorMassKg, "motor-mass-kg", 0, "the motor vehicle's own permissible maximum mass, kg (Iceland's km fee)")
	fs.IntVar(&req.Truck.TrailerMassKg, "trailer-mass-kg", 0, "the trailer's own permissible maximum mass, kg (Iceland's km fee)")
	fs.Float64Var(&req.Truck.LengthM, "length-m", 0, "truck length with trailer, m, for bridge tolls (default 16.5)")
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
	dprice := fs.String("diesel-price", "", "what the truck pays for diesel, EUR per litre without VAT: one price (1.45), by country (PL=1.25,DE=1.55), or both (1.45,PL=1.25); default the EU Weekly Oil Bulletin's national averages of the trip's week")
	bought := fs.String("fuel-bought", "", "litres of diesel bought by country, e.g. DE=300,PL=150: the trip's diesel and where its CO2 prices are paid")
	via := fs.String("via", "", "stops between -from and -to, separated by ; (e.g. DEHAM;DEBER)")
	back := fs.Bool("return", false, "the truck returns empty to -from at the end")
	pathFile := fs.String("path", "", "the way driven, priced instead of Sootcase's route: a GPX file (track or route points) or JSON ([[lon,lat],...] or a GeoJSON LineString)")
	rfmsFiles := fs.String("rfms", "", "rFMS 4.0 responses from the truck maker's API (/vehiclepositions, /vehiclestatuses) for the trip's hours, files separated by ,: the way driven, the diesel burnt (engineTotalFuelUsed) and the date")
	vin := fs.String("vin", "", "the vehicle in the -rfms files, when they hold several")
	ckm := fs.String("country-km", "", "price a trip with no route on its km by country (or ISO 3166-2 region), e.g. DE=320,PL=410, from a tachograph; without -from and -to")
	ships := fs.String("shipments", "", "shipments instead of -cargo-kg, separated by ;: id:kg:from-to with stops numbered from 0 (-from) to the last (-to), e.g. A:12000:0-2;B:8000:1-2")
	fs.Float64Var(&req.DKKPerEUR, "dkk-per-eur", 0, "DKK per EUR (default the ERM II central rate 7.46038)")
	tolled := fs.String("tolled-share", "", "share of each country's km on tolled roads, e.g. DK=1,DE=0.9 (default 1)")
	mway := fs.String("motorway-share", "", "share of tolled km on motorways where rates differ by road type, e.g. CZ=0.9,BE-BRU=0.2")
	fxs := fs.String("fx", "", "exchange rates in units per euro, e.g. CHF=0.93,CZK=24.3 (default the ECB reference rates)")
	zone := fs.String("env-zone-km", "", "km in environmental zones by country, e.g. DK=4")
	cmp := fs.String("compare", "", "also price the trip for these CO2 classes, e.g. 1,4,5")
	fs.Float64Var(&req.TripsPerYear, "trips-per-year", 0, "trips per year, for yearly savings in the comparison")
	fs.BoolVar(&req.ETC, "etc", false, "pays tolls by electronic toll device or agreement (operators' discounts)")
	fs.StringVar(&req.Time, "time", "", "departure time HH:MM, for congestion taxes, free hours and days of time-based charges")
	fs.Float64Var(&req.AvgSpeedKmh, "avg-speed", 0, "average speed km/h for passage times (default 70)")
	fs.BoolVar(&req.DriverRest, "driver-rest", false, "add one driver's breaks and daily rests to passage times and the trip's time (Regulation (EC) No 561/2006)")
	fs.Float64Var(&req.KWhPer100Km, "kwh-per-100km", 0, "an electric truck's (CO2 class 5) kWh per 100 km, for its electricity and class 5 in -compare")
	fs.Float64Var(&req.ElectricityKWh, "electricity-kwh", 0, "kWh an electric truck used on the trip (rFMS totalElectricEnergyUsed, charging records)")
	fs.Float64Var(&req.ElectricityEURPerKWh, "electricity-price", 0, "what an electric truck pays per kWh, EUR without VAT")
	fs.Float64Var(&req.DriverEURPerH, "driver-eur-h", 0, "the driver's cost, EUR per hour of driving: adds a trip cost (charges, diesel, driver, vehicle), which -route cheapest compares")
	fs.Float64Var(&req.VehicleEURPerKm, "vehicle-eur-km", 0, "the truck's own cost, EUR per road km (tyres, maintenance, depreciation): adds to the trip cost")
	fs.BoolVar(&req.Night, "night", false, "the trip passes night-tariff sections at night (22:00-05:00, Austria's A 13)")
	asJSON := fs.Bool("json", false, "print the result as JSON")
	csvIn := fs.String("csv", "", "price each row of this CSV file (\"-\": standard input) and print a CSV of the results: its header names the flags above (from, to, date, cargo-kg, mass-kg, ...), each row's values override the command line's")
	if inspect != nil {
		inspect(fs)
	}
	if err := fs.Parse(args); err != nil {
		return req, calcOpts{}, err
	}
	opts := calcOpts{json: *asJSON, csv: *csvIn, sc: sc}

	var err error
	if *bought != "" {
		m, err := byCountry(*bought)
		if err != nil {
			return req, opts, fmt.Errorf("-fuel-bought: %w", err)
		}
		for _, cc := range slices.Sorted(maps.Keys(m)) {
			req.FuelPurchases = append(req.FuelPurchases, cost.FuelPurchase{Country: cc, Litres: m[cc]})
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
		if req.CountryKm, err = byCountry(*ckm); err != nil {
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
	if req.TolledShare, err = byCountry(*tolled); err != nil {
		return req, opts, fmt.Errorf("-tolled-share: %w", err)
	}
	if req.MotorwayShare, err = byCountry(*mway); err != nil {
		return req, opts, fmt.Errorf("-motorway-share: %w", err)
	}
	if req.FX, err = byCountry(*fxs); err != nil {
		return req, opts, fmt.Errorf("-fx: %w", err)
	}
	if req.EnvZoneKm, err = byCountry(*zone); err != nil {
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
// country (CC=price), or both, separated by commas.
func dieselPriceFlag(req *cost.Request, v string) error {
	for _, p := range strings.Split(v, ",") {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		cc, price, by := strings.Cut(p, "=")
		if !by {
			price = cc
		}
		x, err := strconv.ParseFloat(strings.TrimSpace(price), 64)
		if err != nil || x <= 0 {
			return fmt.Errorf("%q: give EUR per litre, e.g. 1.45 or PL=1.25", p)
		}
		if !by {
			req.DieselEURPerL = x
			continue
		}
		if req.DieselEURPerLByCountry == nil {
			req.DieselEURPerLByCountry = map[string]float64{}
		}
		req.DieselEURPerLByCountry[strings.ToUpper(strings.TrimSpace(cc))] = x
	}
	return nil
}

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
		req.Date = t.From.Format("2006-01-02")
	}
	opts.rfms = t.summary()
	return nil
}

func calc(args []string) error {
	req, opts, err := parseCalc(args, flag.ExitOnError)
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
	printResult(res)
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
		if len(f) != 3 {
			return nil, fmt.Errorf("%q: give id:kg:from-to", part)
		}
		kg, err := strconv.ParseFloat(f[1], 64)
		a, b, ok := strings.Cut(f[2], "-")
		from, err1 := strconv.Atoi(a)
		to, err2 := strconv.Atoi(b)
		if err != nil || !ok || err1 != nil || err2 != nil {
			return nil, fmt.Errorf("%q: give id:kg:from-to", part)
		}
		out = append(out, cost.Shipment{ID: f[0], WeightKg: kg, From: from, To: to})
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
func byCountry(s string) (map[string]float64, error) {
	if strings.TrimSpace(s) == "" {
		return nil, nil
	}
	out := map[string]float64{}
	for _, kv := range strings.Split(s, ",") {
		k, v, ok := strings.Cut(kv, "=")
		f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
		if !ok || err != nil {
			return nil, fmt.Errorf("%q is not COUNTRY=number", kv)
		}
		out[strings.ToUpper(strings.TrimSpace(k))] = f
	}
	return out, nil
}

func printResult(r cost.Response) {
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
		fmt.Printf("Fuel: EUR %.2f without VAT%s (%s); with fuel: EUR %.2f (the CO2 prices on fuel, EUR %.2f, are in the diesel price)\n",
			f.EUR, inc, strings.Join(parts, ", "), r.WithFuelEUR, f.InPriceEUR)
	}
	if e := r.Electricity; e != nil {
		fmt.Printf("Electricity: EUR %.2f without VAT (%.1f kWh x %g, %s); with electricity: EUR %.2f\n", e.EUR, e.KWh, e.EURPerKWh, e.Basis, r.WithFuelEUR)
	}
	if r.Trip != nil && r.Trip.Hours > 0 {
		rest := ""
		if r.Trip.ElapsedH > 0 {
			rest = fmt.Sprintf("; %.2f h with breaks and rests", r.Trip.ElapsedH)
		}
		fmt.Printf("Driving: %.2f h (%s)%s\n", r.Trip.Hours, r.Trip.HoursBasis, rest)
	}
	if r.TripCostEUR > 0 {
		fmt.Printf("Trip cost: EUR %.2f (driver EUR %.2f, vehicle EUR %.2f)\n", r.TripCostEUR, r.DriverEUR, r.VehicleEUR)
	}
	if r.EURPerTkm > 0 {
		fmt.Printf("Per tonne-km: EUR %.4f, of which carbon EUR %.4f\n", r.EURPerTkm, r.CarbonEURPerTkm)
	}
	if r.WTWKg > 0 {
		fmt.Printf("CO2e: %.1f kg well-to-wheel (%.1f tank-to-wheel), %.1f g per tonne-km; %s data: %s\n", r.WTWKg, r.TTWKg, r.IntensityG, r.DataType, r.EmissionsBasis)
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
		fmt.Println("Each shipment's share is its tonne-km (weight x its own route's km) over all of theirs (EN ISO 14083:2023).")
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
		fmt.Println("Energy: the diesel, or an electric truck's electricity at -kwh-per-100km and -electricity-price (blank without them).")
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
		if len(q) < 2 || len(q) > 100 {
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
		var req BatchRequest
		dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad JSON: " + err.Error()})
			return
		}
		if len(req.Trips) == 0 || len(req.Trips) > MaxBatch {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": fmt.Sprintf("trips: give 1 to %d", MaxBatch)})
			return
		}
		writeJSON(w, http.StatusOK, BatchResponse{Results: priceAll(r.Context(), c.Calculate, req.Trips)})
	})
	// A CSV of trips, as calc -csv takes it (but no flag that reads a
	// file or names a server), priced and sent back with the results.
	mux.HandleFunc("POST /v1/carbon-cost/csv", func(w http.ResponseWriter, r *http.Request) {
		var buf bytes.Buffer
		rows := r.URL.Query().Get("rows")
		if rows != "" && rows != "trips" && rows != "shipments" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "rows: trips or shipments"})
			return
		}
		labels, err := priceCSV(r.Context(), c.Calculate, nil, http.MaxBytesReader(w, r.Body, 2<<20), &buf, webCSVFlags(), MaxBatch, rows == "shipments")
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
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
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		w.Header().Set("Content-Disposition", `attachment; filename="carbon-cost-report.csv"`)
		w.Write(buf.Bytes())
	})
	mux.HandleFunc("POST /v1/carbon-cost", func(w http.ResponseWriter, r *http.Request) {
		var req cost.Request
		dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20)) // a path of up to cost.MaxPathPoints
		dec.DisallowUnknownFields()
		if err := dec.Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad JSON: " + err.Error()})
			return
		}
		res, err := c.Calculate(r.Context(), req)
		if err != nil {
			// Bad input (ours, or Sootcase refusing the request itself) is
			// the caller's; Sootcase failing, limiting or refusing this
			// server is a bad gateway (busy: unavailable).
			status := http.StatusBadRequest
			var he *sootcase.HTTPError
			switch {
			case errors.As(err, &he) && he.Status == http.StatusTooManyRequests:
				status = http.StatusServiceUnavailable
			case errors.As(err, &he) && !he.CallerError():
				status = http.StatusBadGateway
			case he == nil && strings.HasPrefix(err.Error(), "sootcase"):
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
	return mux, nil
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(v)
}

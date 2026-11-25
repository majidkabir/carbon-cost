package main

import (
	"context"
	"encoding/csv"
	"flag"
	"fmt"
	"io"
	"os"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/majidkabir/carbon-cost/cost"
)

// batchWorkers is how many trips of a batch are priced at once: each asks
// Sootcase for a route.
const batchWorkers = 4

// MaxBatch is the most trips one batch request may hold.
const MaxBatch = 100

// BatchRequest is several trips to price (POST /v1/carbon-cost/batch).
type BatchRequest struct {
	// Trips are priced each on its own, as POST /v1/carbon-cost would; at
	// most 100.
	Trips []cost.Request `json:"trips"`
}

// BatchItem is one trip's result, or why it couldn't be priced.
type BatchItem struct {
	// Result is the priced trip, as POST /v1/carbon-cost answers it.
	Result *cost.Response `json:"result,omitempty"`
	// Error says why the trip wasn't priced.
	Error string `json:"error,omitempty"`
}

// BatchResponse holds the trips' results in the order asked.
type BatchResponse struct {
	// Results are the trips' results, in the order of the request's.
	Results []BatchItem `json:"results"`
}

// priceAll prices the trips, a few at a time, each result in its trip's
// place.
func priceAll(ctx context.Context, calc func(context.Context, cost.Request) (cost.Response, error), trips []cost.Request) []BatchItem {
	out := make([]BatchItem, len(trips))
	next := make(chan int)
	var wg sync.WaitGroup
	for w := 0; w < batchWorkers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range next {
				r, err := calc(ctx, trips[i])
				if err != nil {
					out[i].Error = err.Error()
					continue
				}
				out[i].Result = &r
			}
		}()
	}
	for i := range trips {
		next <- i
	}
	close(next)
	wg.Wait()
	return out
}

// csvColumns are the result columns calc -csv adds after the input's.
// With -shipment-rows (rows=shipments on the server) a trip with
// shipments gives a row per shipment: shipment_id and shipment_kg set,
// and the amounts, km, tonne-km and CO2e the shipment's share.
var csvColumns = []string{"trip_date", "distance_km", "country_km", "total_eur", "carbon_eur", "road_toll_eur", "fuel_co2_eur", "ets_eur", "area_charge_eur", "ferry_fare_eur", "eur_by_country", "fuel_eur", "with_fuel_eur", "trip_cost_eur", "fuel_l", "kwh", "hours", "empty_km", "shipments", "shipment_id", "shipment_kg", "cargo_kg", "eur_per_tkm", "tkm", "wtw_kg", "ttw_kg", "g_co2e_per_tkm", "currency", "total_in_currency", "data_type", "route", "complete", "missing", "error"}

// calcCSV prices each row of a CSV file whose header names calc's flags
// (without the dash), each row's values on top of the command line's, and
// writes the rows back with the results added.
func calcCSV(c cost.Calculator, args []string, file string) error {
	var in io.Reader = os.Stdin
	if file != "-" {
		f, err := os.Open(file)
		if err != nil {
			return err
		}
		defer f.Close()
		in = f
	}
	base, perShipment := withoutFlag(withoutCSV(args), "shipment-rows")
	labels, err := priceCSV(context.Background(), c.Calculate, base, in, os.Stdout, calcFlagNames(), 0, perShipment)
	if len(labels) > 0 {
		fmt.Fprintf(os.Stderr, "calc -csv: columns kept as labels (no flag of that name): %s\n", strings.Join(labels, ", "))
	}
	return err
}

// webCSVFlags are the flags a CSV sent to the server may set: not those
// that read files or name servers.
func webCSVFlags() map[string]bool {
	ok := calcFlagNames()
	for _, f := range []string{"csv", "json", "path", "rfms", "vin", "sootcase"} {
		delete(ok, f)
	}
	return ok
}

// priceCSV prices each row of a CSV whose header names flags (allowed;
// other columns are kept as labels, and returned), on top of base, and
// writes the rows back with the results added. maxRows > 0 limits the
// rows; perShipment writes a row per shipment of a trip that has them.
func priceCSV(ctx context.Context, calc func(context.Context, cost.Request) (cost.Response, error), base []string, in io.Reader, out io.Writer,
	allowed map[string]bool, maxRows int, perShipment bool) ([]string, error) {
	rd := csv.NewReader(in)
	rd.FieldsPerRecord = -1
	rows, err := rd.ReadAll()
	if err != nil {
		return nil, fmt.Errorf("csv: %w", err)
	}
	if len(rows) < 2 {
		return nil, fmt.Errorf("csv: a header and at least one row are needed")
	}
	if maxRows > 0 && len(rows)-1 > maxRows {
		return nil, fmt.Errorf("csv: at most %d rows", maxRows)
	}
	head := rows[0]
	if len(head) > 0 {
		head[0] = strings.TrimPrefix(head[0], "\ufeff") // a BOM from Excel
	}
	// Columns that name no flag (a truck, an order number) are kept as
	// they are; a typo in a flag's name shows in this list.
	var labels []string
	for _, name := range head {
		if n := strings.TrimPrefix(strings.TrimSpace(name), "-"); n != "" && !allowed[n] {
			labels = append(labels, n)
		}
	}
	trips, bad := make([]cost.Request, len(rows)-1), make([]string, len(rows)-1)
	for i, row := range rows[1:] {
		a := slices.Clone(base)
		for k, name := range head {
			name = strings.TrimPrefix(strings.TrimSpace(name), "-")
			if k < len(row) && strings.TrimSpace(row[k]) != "" && allowed[name] {
				a = append(a, "-"+name+"="+strings.TrimSpace(row[k]))
			}
		}
		req, _, err := parseCalc(a, flag.ContinueOnError)
		if err != nil {
			bad[i] = err.Error()
			continue
		}
		trips[i] = req
	}
	ctx, cancel := context.WithTimeout(ctx, time.Duration(len(trips))*time.Minute)
	defer cancel()
	todo, at := []cost.Request{}, []int{}
	for i, r := range trips {
		if bad[i] == "" {
			todo, at = append(todo, r), append(at, i)
		}
	}
	res := priceAll(ctx, calc, todo)
	w := csv.NewWriter(out)
	w.Write(append(slices.Clone(head), csvColumns...))
	items := make([]BatchItem, len(trips))
	for k, i := range at {
		items[i] = res[k]
	}
	for i, row := range rows[1:] {
		for len(row) < len(head) {
			row = append(row, "")
		}
		if bad[i] != "" {
			items[i].Error = bad[i]
		}
		if r := items[i].Result; perShipment && r != nil && len(r.Shipments) > 1 {
			for _, sh := range r.Shipments {
				w.Write(append(slices.Clone(row[:len(head)]), csvShipment(r, sh)...))
			}
			continue
		}
		w.Write(append(row[:len(head)], csvResult(items[i])...))
	}
	w.Flush()
	return labels, w.Error()
}

// csvResult is a result's columns (csvColumns).
func csvResult(it BatchItem) []string {
	if it.Result == nil {
		out := make([]string, len(csvColumns))
		out[len(out)-1] = it.Error
		return out
	}
	r := it.Result
	by, byCC := map[string]float64{}, map[string]float64{}
	for _, l := range r.Lines {
		by[l.Charge] += l.AmountEUR
		if l.Country != "" {
			byCC[l.Country] += l.AmountEUR
		}
	}
	var cc []string
	for c, v := range byCC {
		cc = append(cc, fmt.Sprintf("%s=%.2f", c, v))
	}
	sort.Strings(cc)
	var km []string
	for cc, v := range r.CountryKm {
		km = append(km, fmt.Sprintf("%s=%.1f", cc, v))
	}
	sort.Strings(km)
	var miss []string
	for _, m := range r.Missing {
		miss = append(miss, m.Message())
	}
	f := func(v float64) string { return strconv.FormatFloat(v, 'f', 2, 64) }
	var fuel, empty string
	if r.Trip != nil {
		fuel, empty = f(r.Trip.FuelL), strconv.FormatFloat(r.Trip.EmptyKm, 'f', 1, 64)
	}
	// Each shipment's share: id=EUR.
	var ships []string
	if len(r.Shipments) > 1 {
		for _, s := range r.Shipments {
			ships = append(ships, s.ID+"="+f(s.TotalEUR))
		}
	}
	var cur, curTotal string
	if c := r.InCurrency; c != nil {
		cur, curTotal = c.Currency, f(c.Total)
	}
	var fuelEUR, withFuel, tripCost, hours, kwh string
	if r.Fuel != nil {
		fuelEUR, withFuel = f(r.Fuel.EUR), f(r.WithFuelEUR)
	}
	if e := r.Electricity; e != nil {
		fuelEUR, withFuel, kwh = f(e.EUR), f(r.WithFuelEUR), strconv.FormatFloat(e.KWh, 'f', 1, 64)
	}
	if r.TripCostEUR > 0 {
		tripCost = f(r.TripCostEUR)
	}
	if r.Trip != nil {
		hours = f(r.Trip.Hours)
	}
	var tkm, kg float64
	for _, s := range r.Shipments {
		tkm += s.TKm
		kg += s.WeightKg
	}
	// The route priced, when alternatives were asked for: its id and ferries.
	var route string
	for _, o := range r.Routes {
		if o.Chosen {
			route = o.ID
			if len(o.Ferries) > 0 {
				route += " (" + strings.Join(o.Ferries, ", ") + ")"
			}
		}
	}
	return []string{r.Date, strconv.FormatFloat(r.DistanceKm, 'f', 1, 64), strings.Join(km, ";"),
		f(r.TotalEUR), f(r.CarbonEUR), f(by[cost.RoadToll]), f(by[cost.FuelCO2]), f(by[cost.FerryETS] + by[cost.FerryUKETS] + by[cost.ETS2]), f(by[cost.AreaCharge]), f(by[cost.FerryFare]), strings.Join(cc, ";"),
		fuelEUR, withFuel, tripCost, fuel, kwh, hours, empty, strings.Join(ships, ";"), "", "", strconv.FormatFloat(kg, 'f', -1, 64), strconv.FormatFloat(r.EURPerTkm, 'f', 4, 64), strconv.FormatFloat(tkm, 'f', 1, 64),
		strconv.FormatFloat(r.WTWKg, 'f', 1, 64), strconv.FormatFloat(r.TTWKg, 'f', 1, 64), f(r.IntensityG), cur, curTotal, r.DataType, route,
		strconv.FormatBool(r.Complete), strings.Join(miss, "; "), ""}
}

// csvShipment is a shipment's columns (csvColumns): its share of the
// trip's amounts and CO2e, its own km and tonne-km.
func csvShipment(r *cost.Response, s cost.ShipmentCost) []string {
	out := csvResult(BatchItem{Result: r})
	f := func(v float64) string { return strconv.FormatFloat(v, 'f', 2, 64) }
	set := func(col, v string) { out[slices.Index(csvColumns, col)] = v }
	set("distance_km", strconv.FormatFloat(s.DistanceKm, 'f', 1, 64))
	var cc []string
	for c, v := range s.ByCountry {
		cc = append(cc, fmt.Sprintf("%s=%.2f", c, v))
	}
	sort.Strings(cc)
	set("country_km", "")
	set("total_eur", f(s.TotalEUR))
	set("carbon_eur", f(s.CarbonEUR))
	set("road_toll_eur", f(s.ByCharge[cost.RoadToll]))
	set("fuel_co2_eur", f(s.ByCharge[cost.FuelCO2]))
	set("ets_eur", f(s.ByCharge[cost.FerryETS]+s.ByCharge[cost.FerryUKETS]+s.ByCharge[cost.ETS2]))
	set("area_charge_eur", f(s.ByCharge[cost.AreaCharge]))
	set("ferry_fare_eur", f(s.ByCharge[cost.FerryFare]))
	set("fuel_eur", "")
	set("with_fuel_eur", "")
	if r.Fuel != nil || r.Electricity != nil {
		set("fuel_eur", f(s.FuelEUR))
		set("with_fuel_eur", f(s.WithFuelEUR))
	}
	set("kwh", "")
	if r.InCurrency != nil {
		set("total_in_currency", f(s.TotalInCurrency))
	}
	set("trip_cost_eur", "")
	if r.TripCostEUR > 0 {
		set("trip_cost_eur", f(s.TripCostEUR))
	}
	set("fuel_l", "")
	set("hours", "")
	set("empty_km", "")
	set("eur_by_country", strings.Join(cc, ";"))
	set("shipments", "")
	set("shipment_id", s.ID)
	set("shipment_kg", strconv.FormatFloat(s.WeightKg, 'f', -1, 64))
	set("cargo_kg", strconv.FormatFloat(s.WeightKg, 'f', -1, 64))
	set("eur_per_tkm", "")
	if s.TKm > 0 {
		set("eur_per_tkm", strconv.FormatFloat(s.TotalEUR/s.TKm, 'f', 4, 64))
	}
	set("tkm", strconv.FormatFloat(s.TKm, 'f', 1, 64))
	set("wtw_kg", strconv.FormatFloat(s.WTWKg, 'f', 1, 64))
	set("ttw_kg", strconv.FormatFloat(s.TTWKg, 'f', 1, 64))
	set("g_co2e_per_tkm", f(s.IntensityG))
	return out
}

// withoutFlag drops a bool flag from the arguments, and says whether it
// was there (as -name, --name or -name=true).
func withoutFlag(args []string, name string) ([]string, bool) {
	var out []string
	on := false
	for _, a := range args {
		switch strings.TrimLeft(a, "-") {
		case name, name + "=true", name + "=1":
			on = true
			continue
		case name + "=false", name + "=0":
			continue
		}
		out = append(out, a)
	}
	return out, on
}

// withoutCSV drops -csv and its value from calc's arguments.
func withoutCSV(args []string) []string {
	var out []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "-csv" || a == "--csv":
			i++
		case strings.HasPrefix(a, "-csv=") || strings.HasPrefix(a, "--csv="):
		default:
			out = append(out, a)
		}
	}
	return out
}

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
var csvColumns = []string{"trip_date", "distance_km", "country_km", "total_eur", "carbon_eur", "road_toll_eur", "fuel_co2_eur", "ets_eur", "area_charge_eur", "ferry_fare_eur", "fuel_l", "empty_km", "shipments", "wtw_kg", "g_co2e_per_tkm", "data_type", "complete", "missing", "error"}

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
	rd := csv.NewReader(in)
	rd.FieldsPerRecord = -1
	rows, err := rd.ReadAll()
	if err != nil {
		return fmt.Errorf("-csv: %w", err)
	}
	if len(rows) < 2 {
		return fmt.Errorf("-csv: a header and at least one row are needed")
	}
	head := rows[0]
	// Columns that name no flag (a truck, an order number) are kept as
	// they are; a typo in a flag's name shows in this list.
	known := calcFlagNames()
	var labels []string
	for _, name := range head {
		if n := strings.TrimPrefix(strings.TrimSpace(name), "-"); n != "" && !known[n] {
			labels = append(labels, n)
		}
	}
	if len(labels) > 0 {
		fmt.Fprintf(os.Stderr, "calc -csv: columns kept as labels (no flag of that name): %s\n", strings.Join(labels, ", "))
	}
	base := withoutCSV(args)
	trips, bad := make([]cost.Request, len(rows)-1), make([]string, len(rows)-1)
	for i, row := range rows[1:] {
		a := slices.Clone(base)
		for k, name := range head {
			name = strings.TrimPrefix(strings.TrimSpace(name), "-")
			if k < len(row) && strings.TrimSpace(row[k]) != "" && known[name] {
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
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(len(trips))*time.Minute)
	defer cancel()
	todo, at := []cost.Request{}, []int{}
	for i, r := range trips {
		if bad[i] == "" {
			todo, at = append(todo, r), append(at, i)
		}
	}
	res := priceAll(ctx, c.Calculate, todo)
	w := csv.NewWriter(os.Stdout)
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
		w.Write(append(row[:len(head)], csvResult(items[i])...))
	}
	w.Flush()
	return w.Error()
}

// csvResult is a result's columns (csvColumns).
func csvResult(it BatchItem) []string {
	if it.Result == nil {
		out := make([]string, len(csvColumns))
		out[len(out)-1] = it.Error
		return out
	}
	r := it.Result
	by := map[string]float64{}
	for _, l := range r.Lines {
		by[l.Charge] += l.AmountEUR
	}
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
	return []string{r.Date, strconv.FormatFloat(r.DistanceKm, 'f', 1, 64), strings.Join(km, ";"),
		f(r.TotalEUR), f(r.CarbonEUR), f(by[cost.RoadToll]), f(by[cost.FuelCO2]), f(by[cost.FerryETS] + by[cost.FerryUKETS] + by[cost.ETS2]), f(by[cost.AreaCharge]), f(by[cost.FerryFare]),
		fuel, empty, strings.Join(ships, ";"), strconv.FormatFloat(r.WTWKg, 'f', 1, 64), f(r.IntensityG), r.DataType,
		strconv.FormatBool(r.Complete), strings.Join(miss, "; "), ""}
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

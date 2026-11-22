package main

import (
	"encoding/csv"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"slices"
	"sort"
	"strconv"
	"strings"
)

// reportSums are the priced CSV's columns a report adds up.
var reportSums = []string{"distance_km", "empty_km", "fuel_l", "cargo_kg", "tkm", "wtw_kg", "ttw_kg", "total_eur", "carbon_eur",
	"road_toll_eur", "fuel_co2_eur", "ets_eur", "area_charge_eur", "ferry_fare_eur", "fuel_eur", "with_fuel_eur"}

// reportColumns follow the groups' columns in a report.
var reportColumns = append([]string{"rows", "shipments"}, append(slices.Clone(reportSums),
	"g_co2e_per_tkm", "eur_per_tkm", "eur_per_100kg", "road_toll_eur_per_100kg", "carbon_eur_per_100kg", "primary_tkm_share", "incomplete", "errors")...)

// report sums priced CSV files (calc -csv's output, or the web page's or
// POST /v1/carbon-cost/csv's) by the columns given, for a customer's or a
// month's emissions and charges.
func report(args []string) error {
	fs := flag.NewFlagSet("report", flag.ExitOnError)
	by := fs.String("by", "", "columns to group by, separated by ,: any column of the file (a label such as customer, or shipment_id), and month or year (of trip_date); blank: one total")
	fs.Usage = func() {
		fmt.Fprintln(os.Stderr, `Usage: carbon-cost report [-by customer,month] priced.csv ... (or - for stdin)

Adds up priced CSV files (calc -csv, with -shipment-rows for a row per
shipment) by the columns given: tonne-km, CO2e well-to-wheel and
tank-to-wheel, g CO2e per tonne-km, the share of tonne-km with primary
data, the charges, and EUR per 100 kg carried (-by from,to on a CSV of
lanes: a lane's toll surcharge). Writes CSV.`)
		fs.PrintDefaults()
	}
	fs.Parse(args)
	files := fs.Args()
	if len(files) == 0 {
		files = []string{"-"}
	}
	var ins []io.Reader
	for _, name := range files {
		if name == "-" {
			ins = append(ins, os.Stdin)
			continue
		}
		f, err := os.Open(name)
		if err != nil {
			return err
		}
		defer f.Close()
		ins = append(ins, f)
	}
	return summarize(ins, os.Stdout, splitList(*by))
}

func splitList(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

type reportGroup struct {
	key       []string
	rows      int
	shipments int
	sums      map[string]float64
	have      map[string]bool // columns with a value in some row
	primary   float64         // tonne-km with primary data
	incomp    int
	errs      int
}

// summarize adds up priced CSVs by the columns in by (month and year are
// of trip_date).
func summarize(ins []io.Reader, out io.Writer, by []string) error {
	groups := map[string]*reportGroup{}
	for n, in := range ins {
		rd := csv.NewReader(in)
		rd.FieldsPerRecord = -1
		rows, err := rd.ReadAll()
		if err != nil {
			return fmt.Errorf("file %d: %w", n+1, err)
		}
		if len(rows) < 1 {
			return fmt.Errorf("file %d: empty", n+1)
		}
		head := rows[0]
		if len(head) > 0 {
			head[0] = strings.TrimPrefix(head[0], "\ufeff")
		}
		col := map[string]int{}
		for i, h := range head {
			// calc -csv adds its columns after the input's; where a name
			// comes twice, the last (the result's) counts.
			col[strings.TrimSpace(h)] = i
		}
		for _, need := range []string{"trip_date", "total_eur", "wtw_kg", "tkm", "data_type", "complete", "error"} {
			if _, ok := col[need]; !ok {
				return fmt.Errorf("file %d: no %s column: give a CSV priced by carbon-cost (v0.105 or later)", n+1, need)
			}
		}
		for _, g := range by {
			if _, ok := col[g]; !ok && g != "month" && g != "year" {
				return fmt.Errorf("file %d: no column %q to group by", n+1, g)
			}
		}
		get := func(row []string, name string) string {
			if i, ok := col[name]; ok && i < len(row) {
				return strings.TrimSpace(row[i])
			}
			return ""
		}
		for _, row := range rows[1:] {
			// A row that failed has no trip_date: its date column, if any.
			day := get(row, "trip_date")
			if day == "" {
				day = get(row, "date")
			}
			key := make([]string, len(by))
			for i, g := range by {
				switch {
				case g == "month" && len(day) >= 7:
					key[i] = day[:7]
				case g == "year" && len(day) >= 4:
					key[i] = day[:4]
				case g == "month" || g == "year":
				default:
					key[i] = get(row, g)
				}
			}
			k := strings.Join(key, "\x00")
			gr := groups[k]
			if gr == nil {
				gr = &reportGroup{key: key, sums: map[string]float64{}, have: map[string]bool{}}
				groups[k] = gr
			}
			gr.rows++
			if get(row, "error") != "" {
				gr.errs++
				continue
			}
			if get(row, "shipment_id") != "" {
				gr.shipments++
			}
			for _, c := range reportSums {
				if v := get(row, c); v != "" {
					x, err := strconv.ParseFloat(v, 64)
					if err != nil {
						return fmt.Errorf("file %d: %s %q: %w", n+1, c, v, err)
					}
					gr.sums[c] += x
					gr.have[c] = true
				}
			}
			if get(row, "data_type") == "primary" {
				x, _ := strconv.ParseFloat(get(row, "tkm"), 64)
				gr.primary += x
			}
			if get(row, "complete") == "false" {
				gr.incomp++
			}
		}
	}
	if len(groups) == 0 {
		return errors.New("no rows")
	}
	list := make([]*reportGroup, 0, len(groups))
	for _, g := range groups {
		list = append(list, g)
	}
	sort.Slice(list, func(i, j int) bool { return slices.Compare(list[i].key, list[j].key) < 0 })
	w := csv.NewWriter(out)
	w.Write(append(slices.Clone(by), reportColumns...))
	f := func(v float64, d int) string { return strconv.FormatFloat(v, 'f', d, 64) }
	for _, g := range list {
		rec := append(slices.Clone(g.key), strconv.Itoa(g.rows), strconv.Itoa(g.shipments))
		for _, c := range reportSums {
			d := 2
			if c == "cargo_kg" {
				d = 0
			} else if c == "distance_km" || c == "empty_km" || c == "tkm" || c == "wtw_kg" || c == "ttw_kg" || c == "fuel_l" {
				d = 1
			}
			if !g.have[c] {
				rec = append(rec, "") // no row gave it (litres on shipment rows)
				continue
			}
			rec = append(rec, f(g.sums[c], d))
		}
		tkm, kg := g.sums["tkm"], g.sums["cargo_kg"]
		if tkm > 0 {
			rec = append(rec, f(1000*g.sums["wtw_kg"]/tkm, 1), f(g.sums["total_eur"]/tkm, 4))
		} else {
			rec = append(rec, "", "")
		}
		// Per 100 kg carried: a lane's surcharge for groupage.
		if kg > 0 {
			rec = append(rec, f(100*g.sums["total_eur"]/kg, 3), f(100*g.sums["road_toll_eur"]/kg, 3), f(100*g.sums["carbon_eur"]/kg, 3))
		} else {
			rec = append(rec, "", "", "")
		}
		if tkm > 0 {
			rec = append(rec, f(g.primary/tkm, 3))
		} else {
			rec = append(rec, "")
		}
		rec = append(rec, strconv.Itoa(g.incomp), strconv.Itoa(g.errs))
		w.Write(rec)
	}
	w.Flush()
	return w.Error()
}

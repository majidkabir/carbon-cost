package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"flag"
	"io"
	"os"
	"reflect"
	"runtime/debug"
	"slices"
	"strings"
	"testing"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// -diesel-price (and a CSV's diesel-price cell): one price, with a
// decimal point or comma, prices by country, or both; two bare prices
// are refused, not read as the last.
func TestDieselPriceFlag(t *testing.T) {
	for _, c := range []struct {
		in    string
		all   float64
		by    map[string]float64
		isErr bool
	}{
		{"1.45", 1.45, nil, false},
		{"1,5", 1.5, nil, false},
		{"1,45", 1.45, nil, false},
		{"PL=1.25, DE=1.6", 0, map[string]float64{"PL": 1.25, "DE": 1.6}, false},
		{"1.5, PL=1.25", 1.5, map[string]float64{"PL": 1.25}, false},
		{"1.4, 1.5", 0, nil, true},
		{"1,5, PL=1.25", 1.5, map[string]float64{"PL": 1.25}, false},
		{"DE=1,5", 0, map[string]float64{"DE": 1.5}, false},
		{"1,45;PL=1,25", 1.45, map[string]float64{"PL": 1.25}, false},
		{"DE=1,5,PL=1,4", 0, map[string]float64{"DE": 1.5, "PL": 1.4}, false},
		{"1,459", 0, nil, true}, // 1459, or 1.459?
		{"PL=2,1.45", 0, nil, true},
	} {
		var req cost.Request
		err := dieselPriceFlag(&req, c.in)
		if (err != nil) != c.isErr || !c.isErr && (req.DieselEURPerL != c.all || !reflect.DeepEqual(req.DieselEURPerLByCountry, c.by)) {
			t.Errorf("%q: %v %v %v", c.in, err, req.DieselEURPerL, req.DieselEURPerLByCountry)
		}
	}
}

// Every truck field the API takes has a calc flag (and so a CSV column).
func TestTruckFieldsHaveFlags(t *testing.T) {
	flagOf := map[string]string{"max_mass_kg": "mass-kg", "co2_class": "co2-class", "adr_tunnel_code": "tunnel-code", "hazmat": "hazmat"}
	names := calcFlagNames()
	tt := reflect.TypeOf(rates.Truck{})
	for i := 0; i < tt.NumField(); i++ {
		tag := strings.Split(tt.Field(i).Tag.Get("json"), ",")[0]
		if tag == "" || tag == "-" {
			continue
		}
		name := flagOf[tag]
		if name == "" {
			name = strings.ReplaceAll(tag, "_", "-")
		}
		if !names[name] {
			t.Errorf("truck.%s has no calc flag -%s", tag, name)
		}
	}
	// And it reaches the request.
	req, _, err := parseCalc([]string{"-from", "DEHAM", "-to", "DEBER", "-cargo-kg", "1000", "-capacity-kg", "25000"}, flag.ContinueOnError)
	if err != nil || req.Truck.CapacityKg != 25000 {
		t.Errorf("-capacity-kg: %v %+v", err, req.Truck)
	}
}

// A binary from go install reports its module's version.
func TestVersionFromModule(t *testing.T) {
	if v := versionOf(&debug.BuildInfo{Main: debug.Module{Version: "v0.120.0"}}, true); v != "v0.120.0" {
		t.Errorf("go install: %q", v)
	}
	if v := versionOf(&debug.BuildInfo{Main: debug.Module{Version: "(devel)"}, Settings: []debug.BuildSetting{{Key: "vcs.revision", Value: "abcdef123"}}}, true); v != "dev+abcdef1" {
		t.Errorf("a checkout before Go 1.24: %q", v)
	}
	// Go 1.24 stamps a checkout's build with a pseudo-version.
	if v := versionOf(&debug.BuildInfo{Main: debug.Module{Version: "v0.120.1-0.20261127223745-82420437f9fd+dirty"},
		Settings: []debug.BuildSetting{{Key: "vcs.revision", Value: "82420437f9fd0011"}, {Key: "vcs.modified", Value: "true"}}}, true); v != "dev+8242043.dirty" {
		t.Errorf("a checkout with changes: %q", v)
	}
	if v := versionOf(&debug.BuildInfo{Main: debug.Module{Version: "v0.120.1-0.20261127223745-82420437f9fd"}}, true); v != "dev+8242043" {
		t.Errorf("go install of a commit: %q", v)
	}
	if v := versionOf(&debug.BuildInfo{Main: debug.Module{Version: "v0.121.0+dirty"},
		Settings: []debug.BuildSetting{{Key: "vcs.revision", Value: "979487f2aa"}, {Key: "vcs.modified", Value: "true"}}}, true); v != "dev+979487f.dirty" {
		t.Errorf("a checkout at a tag, with changes: %q", v)
	}
}

// A CSV separated by semicolons (Excel's in most European locales) is
// read and written back so.
func TestCSVSemicolons(t *testing.T) {
	fake := fakeRoute(t)
	defer fake.Close()
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	var out strings.Builder
	labels, err := priceCSV(context.Background(), c.Calculate, []string{"-cargo-kg", "20000"}, strings.NewReader("from;to;date;co2-class;ref\nDEHAM;DEBER;2026-11-03;1;T1\n"), &out, calcFlagNames(), 100, false)
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if err != nil || !reflect.DeepEqual(labels, []string{"ref"}) || len(lines) != 2 || !strings.HasPrefix(lines[0], "from;to;date;co2-class;ref;trip_date") || !strings.Contains(lines[1], ";DE=100.0;") {
		b, _ := json.Marshal(labels)
		t.Errorf("%v labels %s:\n%s", err, b, out.String())
	}
}

// A ; CSV as Excel writes it where the decimal symbol is a comma: decimal
// commas (alone and in lists), the day first (with . - or /), a label
// with commas; written back, and added up by report, the same way, a
// failed row in its month. 12.500 (12500, or 12.5?) is refused, alone or
// in a list.
func TestCSVExcelDecimalComma(t *testing.T) {
	c, err := calculator(&sootcase.Client{BaseURL: "http://127.0.0.1:1"})
	if err != nil {
		t.Fatal(err)
	}
	in := "country-km;cargo-kg;date;l-per-100km;diesel-price;\"Kunde, Ort, PLZ\"\n" +
		"DE=100,PL=100;1000;03.11.2026;28,5;1,5;\"A, B\"\n" +
		"DE=100;12.500;03-11-2026;28,5;1,5;B\n" +
		"DE=100;1000;03/11/2026;28,5;DE=1,5;C\n" +
		"\"DE=3.200,PL=4.100\";1000;03.11.2026;28,5;1,5;D\n" +
		"\"DE=320,5;PL=410\";1000;03-11-2026;28,5;1,5;E\n"
	var out strings.Builder
	if _, err := priceCSV(context.Background(), c.Calculate, nil, strings.NewReader(in), &out, calcFlagNames(), 100, false); err != nil {
		t.Fatal(err)
	}
	rd := csv.NewReader(strings.NewReader(out.String()))
	rd.Comma = ';'
	rows, err := rd.ReadAll()
	if err != nil || len(rows) != 6 {
		t.Fatalf("%v:\n%s", err, out.String())
	}
	col := map[string]int{}
	for i, h := range rows[0] {
		col[h] = i
	}
	r := rows[1]
	if r[col["error"]] != "" || r[col["trip_date"]] != "2026-11-03" || !strings.HasPrefix(r[col["fuel_l"]], "57,0") || !strings.HasPrefix(r[col["fuel_eur"]], "85,5") || r[col["Kunde, Ort, PLZ"]] != "A, B" {
		t.Errorf("row 1: %q", r)
	}
	if e := rows[2][col["error"]]; !strings.Contains(e, "12.500") {
		t.Errorf("row 2: %q", e)
	}
	if r := rows[3]; r[col["error"]] != "" || r[col["trip_date"]] != "2026-11-03" || !strings.HasPrefix(r[col["fuel_eur"]], "42,75") {
		t.Errorf("row 3 (03/11/2026, DE=1,5): %q %q %q", r[col["error"]], r[col["trip_date"]], r[col["fuel_eur"]])
	}
	if e := rows[4][col["error"]]; !strings.Contains(e, "3.200") {
		t.Errorf("row 4 (DE=3.200 in a list): %q", e)
	}
	if r := rows[5]; r[col["error"]] != "" || !strings.HasPrefix(r[col["distance_km"]], "730,5") {
		t.Errorf("row 5 (DE=320,5;PL=410): %q %q", r[col["error"]], r[col["distance_km"]])
	}
	var rep strings.Builder
	if err := summarize([]io.Reader{strings.NewReader(out.String())}, &rep, []string{"month"}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(rep.String()), "\n")
	if len(lines) != 2 || !strings.HasPrefix(lines[0], "month;rows;shipments;") || !strings.HasPrefix(lines[1], "2026-11;5;") || !strings.HasSuffix(lines[1], ";2") {
		t.Errorf("report by month:\n%s", rep.String())
	}
	// A comma CSV with semicolons in a quoted label is still one; a ; CSV
	// with an unquoted label with commas (as Go's and Python's writers
	// write it) is still one.
	for in, want := range map[string]rune{
		"country-km,cargo-kg,\"Notes; a; b; c\"\nDE=100,1000,x\n":                 ',',
		"cargo-kg;date;Kunde, Ort, PLZ\n12000;03.11.2026;Muster, Berlin, 10115\n": ';',
		"\ufeffcargo-kg;date\n12000;03.11.2026\n":                                 ';',
	} {
		if _, comma, _ := sniffComma(strings.NewReader(in), calcFlagNames()); rune(comma) != want {
			t.Errorf("%q read as %q", in, rune(comma))
		}
	}
}

// Lists by country are read as testdata/countryvalues.json says, by calc
// and the page alike; and so by each flag that takes one.
func TestCountryValues(t *testing.T) {
	var file struct {
		Cases [][2]json.RawMessage `json:"cases"`
	}
	b, err := os.ReadFile("testdata/countryvalues.json")
	if err != nil || json.Unmarshal(b, &file) != nil {
		t.Fatal(err)
	}
	for _, c := range file.Cases {
		var in string
		var want [][2]any
		json.Unmarshal(c[0], &in)
		json.Unmarshal(c[1], &want)
		vals, err := countryValues(in, false)
		got := [][2]any{}
		for _, cv := range vals {
			got = append(got, [2]any{cv.cc, cv.v})
		}
		if (err != nil) != (want == nil) || want != nil && !reflect.DeepEqual(got, want) {
			t.Errorf("%q: %v %v; want %v", in, got, err, want)
		}
	}
	// Each flag that takes a list, and what it reads; a country twice adds
	// up for km and is kept as two purchases, else is refused.
	for _, f := range []struct {
		flag, v string
		got     func(cost.Request) any
		want    any
	}{
		{"-country-km", "DE=320,5;PL=410", func(r cost.Request) any { return r.CountryKm }, map[string]float64{"DE": 320.5, "PL": 410}},
		{"-country-km", "DE=120,PL=300,DE=80", func(r cost.Request) any { return r.CountryKm }, map[string]float64{"DE": 200, "PL": 300}},
		{"-fuel-bought", "DE=30,5;PL=10,DE=20", func(r cost.Request) any { return r.FuelPurchases }, []cost.FuelPurchase{{Country: "DE", Litres: 30.5}, {Country: "PL", Litres: 10}, {Country: "DE", Litres: 20}}},
		{"-tolled-share", "DE=0,9", func(r cost.Request) any { return r.TolledShare }, map[string]float64{"DE": 0.9}},
		{"-motorway-share", "CZ=0,9", func(r cost.Request) any { return r.MotorwayShare }, map[string]float64{"CZ": 0.9}},
		{"-fx", "CZK=24,3", func(r cost.Request) any { return r.FX }, map[string]float64{"CZK": 24.3}},
		{"-env-zone-km", "DK=4,5", func(r cost.Request) any { return r.EnvZoneKm }, map[string]float64{"DK": 4.5}},
		{"-diesel-price", "DE=1,5", func(r cost.Request) any { return r.DieselEURPerLByCountry }, map[string]float64{"DE": 1.5}},
		{"-env-zone-km", "DK=2,DK=3,5", func(r cost.Request) any { return r.EnvZoneKm }, map[string]float64{"DK": 5.5}},
		{"-fx", "CZK=24.305", func(r cost.Request) any { return r.FX }, map[string]float64{"CZK": 24.305}},
		{"-tolled-share", "DE=0.875", func(r cost.Request) any { return r.TolledShare }, map[string]float64{"DE": 0.875}},
		// Counts (km, litres) to three decimals are 3200 the European way.
		{"-country-km", "DE=3.200,PL=4.100", nil, nil},
		{"-fuel-bought", "DE=1.200", nil, nil},
		{"-diesel-price", "DE=1.234,5", nil, nil},
		{"-country-km", "DE=1" + strings.Repeat("0", 400), nil, nil},
		{"-fx", "CZK=24.3,CZK=25", nil, nil},
		{"-tolled-share", "DE=1,DE=0.5", nil, nil},
		{"-diesel-price", "DE=1.5,DE=1.6", nil, nil},
	} {
		args := []string{"-cargo-kg", "1000", "-date", "2026-11-03", f.flag, f.v}
		if f.flag != "-country-km" {
			args = append(args, "-country-km", "DE=100,CZ=100")
		}
		req, _, err := parseCalc(args, flag.ContinueOnError)
		if f.got == nil {
			if err == nil {
				t.Errorf("%s %s: no error", f.flag, f.v)
			}
			continue
		}
		if err != nil || !reflect.DeepEqual(f.got(req), f.want) {
			t.Errorf("%s %s: %v %v; want %v", f.flag, f.v, f.got(req), err, f.want)
		}
	}
	// Every flag that takes text with numbers in it is a list flag, checked
	// for 12.500 in a ; CSV.
	text := map[string]bool{"from": true, "to": true, "via": true, "date": true, "time": true, "vehicle": true, "tunnel-code": true, "route": true,
		"ferry-ets-basis": true, "fuel-country": true, "cost-share-by": true, "currency": true, "compare": true, "sootcase": true, "path": true,
		"rfms": true, "vin": true, "csv": true}
	parseCalcWith(nil, flag.ContinueOnError, func(fs *flag.FlagSet) {
		fs.VisitAll(func(f *flag.Flag) {
			if g, ok := f.Value.(flag.Getter); ok {
				if _, s := g.Get().(string); s && !text[f.Name] && !listFlags[f.Name] {
					t.Errorf("-%s: a list flag, or text?", f.Name)
				}
			}
		})
	})
}

// Every result column is a number or named a text.
func TestCSVTextColumns(t *testing.T) {
	for name := range csvText {
		if !slices.Contains(csvColumns, name) {
			t.Errorf("csvText %q is no result column", name)
		}
	}
}

// In a ; CSV a list's decimal commas are points (CZK=24,305; A:12000,5:0-2;
// ldm=2,4), its 12.500 refused; elsewhere the cell is the flag's as given.
func TestCSVLocaleLists(t *testing.T) {
	for _, c := range []struct {
		comma      csvLocale
		name, v    string
		want       string
		wantsError bool
	}{
		{';', "fx", "CZK=24,305", "CZK=24.3050", false}, // (24.305, not refused as 24305 the European way)
		{';', "country-km", "DE=3,200;PL=4,1", "DE=3.2000;PL=4.1", false},
		{';', "shipments", "A:12000,5:0-2;B:800:1-2:ldm=2,4,pallets=6", "A:12000.5:0-2;B:800:1-2:ldm=2.4,pallets=6", false},
		{';', "country-km", "DE=100,PL=100", "DE=100,PL=100", false},
		{';', "country-km", "DE=3.200,PL=4.100", "", true},
		{';', "diesel-price", "1,459", "1.4590", false},
		{',', "country-km", "DE=1,200", "DE=1,200", false},
	} {
		got, err := c.comma.in(c.name, c.v, calcNumberFlags())
		if (err != nil) != c.wantsError || got != c.want {
			t.Errorf("%c %s %q: %q %v", rune(c.comma), c.name, c.v, got, err)
		}
	}
	// report takes calc -csv's -date column (a failed row's month).
	priced := "-date,trip_date,total_eur,wtw_kg,tkm,data_type,complete,error\n2026-11-03,2026-11-03,10,5,100,modelled,true,\n2026-11-04,,,,,,,bad\n"
	var rep strings.Builder
	if err := summarize([]io.Reader{strings.NewReader(priced)}, &rep, []string{"month"}); err != nil || !strings.Contains(rep.String(), "\n2026-11,2,") {
		t.Errorf("report by month with a -date column: %v\n%s", err, rep.String())
	}
	// A BOM before a quoted first header cell (Excel's UTF-8 CSV): its
	// label read, the row priced.
	none := func(context.Context, cost.Request) (cost.Response, error) { return cost.Response{}, nil }
	errorsOf := func(in string) []string {
		var out strings.Builder
		if _, err := priceCSV(context.Background(), none, []string{"-cargo-kg", "1000"}, strings.NewReader(in), &out, calcFlagNames(), 100, false); err != nil {
			return []string{err.Error()}
		}
		rows, _ := csv.NewReader(strings.NewReader(out.String())).ReadAll()
		var errs []string
		for _, r := range rows[1:] {
			errs = append(errs, r[len(r)-1])
		}
		return errs
	}
	if e := errorsOf("\ufeff\"Kunde, Ort\",country-km\nA,DE=10\n"); !reflect.DeepEqual(e, []string{""}) {
		t.Errorf("BOM and a quoted cell: %q", e)
	}
	// A list cell unquoted in a comma CSV: more cells than the header names,
	// refused, not cut to DE=320.
	if e := errorsOf("cargo-kg,date,country-km\n1000,2026-11-03,DE=320,PL=410\n"); len(e) != 1 || !strings.Contains(e[0], "cells") {
		t.Errorf("an unquoted list cell: %q", e)
	}
	// In a ; CSV, a number after one with its decimal comma is one too, and
	// one with a decimal point stays.
	for in, want := range map[string]string{"PL=1,25,1,45": "PL=1.25,1.45", "PL=1.25,1.45": "PL=1.25,1.45"} {
		if got, err := csvLocale(';').in("diesel-price", in, nil); err != nil || got != want {
			t.Errorf("; CSV diesel-price %q: %q %v", in, got, err)
		}
	}
	// A ; CSV's shipment ids keep their commas; their kg take decimal commas.
	if got, _ := csvLocale(';').in("shipments", "4711,4712:12000,5:0-2;B:8000:1-2", nil); got != "4711,4712:12000.5:0-2;B:8000:1-2" {
		t.Errorf("shipments: %q", got)
	}
}

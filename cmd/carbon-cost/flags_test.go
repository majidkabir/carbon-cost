package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"flag"
	"reflect"
	"io"
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
		{"1,5, PL=1.25", 0, nil, true},
		{"DE=1,5", 0, map[string]float64{"DE": 1.5}, false},
		{"1,45;PL=1,25", 1.45, map[string]float64{"PL": 1.25}, false},
		{"DE=1,5,PL=1,4", 0, nil, true}, // DE=1 and 5 for all?
		{"PL=2,1.45", 1.45, map[string]float64{"PL": 2}, false},
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
// commas, the day first, a label with commas; written back, and added up
// by report, the same way. 12.500 (12500, or 12.5?) is refused.
func TestCSVExcelDecimalComma(t *testing.T) {
	c, err := calculator(&sootcase.Client{BaseURL: "http://127.0.0.1:1"})
	if err != nil {
		t.Fatal(err)
	}
	in := "country-km;cargo-kg;date;l-per-100km;diesel-price;\"Kunde, Ort, PLZ\"\n" +
		"DE=100,PL=100;1000;03.11.2026;28,5;1,5;\"A, B\"\n" +
		"DE=100;12.500;03-11-2026;28,5;DE=1,5;C\n"
	var out strings.Builder
	if _, err := priceCSV(context.Background(), c.Calculate, nil, strings.NewReader(in), &out, calcFlagNames(), 100, false); err != nil {
		t.Fatal(err)
	}
	rd := csv.NewReader(strings.NewReader(out.String()))
	rd.Comma = ';'
	rows, err := rd.ReadAll()
	if err != nil || len(rows) != 3 {
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
	var rep strings.Builder
	if err := summarize([]io.Reader{strings.NewReader(out.String())}, &rep, nil); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(rep.String()), "\n")
	if len(lines) != 2 || !strings.HasPrefix(lines[0], "rows;shipments;") || !strings.Contains(lines[1], ";85,5") {
		t.Errorf("report:\n%s", rep.String())
	}
	// A comma CSV with semicolons in a quoted label is still one.
	if _, comma, _ := sniffComma(strings.NewReader("country-km,cargo-kg,\"Notes; a; b; c\"\nDE=100,1000,x\n")); comma != ',' {
		t.Errorf("comma CSV read as %q", rune(comma))
	}
}

// Every result column is a number or named a text.
func TestCSVTextColumns(t *testing.T) {
	for name := range csvText {
		if !slices.Contains(csvColumns, name) {
			t.Errorf("csvText %q is no result column", name)
		}
	}
}

package main

import (
	"context"
	"encoding/json"
	"flag"
	"reflect"
	"runtime/debug"
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
		t.Errorf("a checkout: %q", v)
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

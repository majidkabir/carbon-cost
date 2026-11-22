package main

import (
	"flag"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestTripFlags(t *testing.T) {
	req, _, err := parseCalc([]string{"-from", "DEHAM", "-via", "DEBRE; NLRTM", "-to", "BEANR", "-return",
		"-shipments", "A:12000:0-2;B:8000:1-3", "-fuel-bought", "DE=300,NL=100", "-l-per-100km", "29"}, flag.ContinueOnError)
	if err != nil {
		t.Fatal(err)
	}
	if len(req.Stops) != 5 || req.Stops[1].Code != "DEBRE" || req.Stops[4].Code != "DEHAM" || req.From.Code != "" {
		t.Errorf("stops %+v", req.Stops)
	}
	if len(req.Shipments) != 2 || req.Shipments[1].ID != "B" || req.Shipments[1].From != 1 || req.Shipments[1].To != 3 || req.Shipments[0].WeightKg != 12000 {
		t.Errorf("shipments %+v", req.Shipments)
	}
	if len(req.FuelPurchases) != 2 || req.FuelPurchases[0].Country != "DE" || req.FuelPurchases[1].Litres != 100 || req.LPer100Km != 29 {
		t.Errorf("fuel %+v %v", req.FuelPurchases, req.LPer100Km)
	}
	// -return with -cargo-kg: the cargo to -to, back empty.
	req, _, err = parseCalc([]string{"-from", "DEHAM", "-to", "DEMUC", "-return", "-cargo-kg", "20000"}, flag.ContinueOnError)
	if err != nil || len(req.Stops) != 3 || len(req.Shipments) != 1 || req.Shipments[0].To != 1 || req.Shipments[0].WeightKg != 20000 || req.CargoKg != 0 {
		t.Errorf("return: %+v %v", req, err)
	}
	req, _, err = parseCalc([]string{"-country-km", "DE=300,be-vlg=40", "-cargo-kg", "1"}, flag.ContinueOnError)
	if err != nil || req.CountryKm["DE"] != 300 || req.CountryKm["BE-VLG"] != 40 {
		t.Errorf("country km: %+v %v", req.CountryKm, err)
	}
	if _, _, err := parseCalc([]string{"-country-km", "DE=300", "-from", "DEHAM"}, flag.ContinueOnError); err == nil {
		t.Error("-country-km with -from: want an error")
	}
	for _, bad := range []string{"A:1", "A:x:0-1", "A:1:0"} {
		if _, err := shipmentsFlag(bad); err == nil {
			t.Errorf("%q: want an error", bad)
		}
	}
}

func TestReadPath(t *testing.T) {
	dir := t.TempDir()
	files := map[string]string{
		"a.gpx": `<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
<trkpt lat="55.68" lon="12.57"><time>2026-11-03T08:00:00Z</time></trkpt><trkpt lat="55.2" lon="11.9"/></trkseg>
<trkseg><trkpt lat="54.7" lon="11.4"/></trkseg></trk></gpx>`,
		"r.gpx":     `<gpx><rte><rtept lat="55.68" lon="12.57"/><rtept lat="55.2" lon="11.9"/><rtept lat="54.7" lon="11.4"/></rte></gpx>`,
		"a.json":    `[[12.57, 55.68], [11.9, 55.2, 12], [11.4, 54.7]]`,
		"line.json": `{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[12.57, 55.68], [11.9, 55.2], [11.4, 54.7]]}}`,
		"fc.json":   `{"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "MultiLineString", "coordinates": [[[12.57, 55.68], [11.9, 55.2]], [[11.4, 54.7]]]}}]}`,
	}
	for name, body := range files {
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		pts, err := readPath(p)
		if err != nil || len(pts) != 3 || pts[0] != [2]float64{12.57, 55.68} || pts[2] != [2]float64{11.4, 54.7} {
			t.Errorf("%s: %v %v", name, pts, err)
		}
	}
	for _, bad := range []string{"", "<gpx></gpx>", `{"type": "Point", "coordinates": [1, 2]}`, `[[1]]`} {
		if _, err := parsePath([]byte(bad)); err == nil {
			t.Errorf("%q: want an error", bad)
		}
	}
}

func TestRFMS(t *testing.T) {
	dir := t.TempDir()
	pos := `{"vehiclePositionResponse": {"vehiclePositions": [
 {"vin": "YS2R4X20005399401", "triggerType": {"triggerType": "TIMER", "context": "RFMS"}, "createdDateTime": "2026-11-20T06:30:00Z", "receivedDateTime": "2026-11-20T06:30:05Z",
  "gnssPosition": {"latitude": 55.2, "longitude": 11.9, "positionDateTime": "2026-11-20T06:30:00Z"}},
 {"vin": "YS2R4X20005399401", "triggerType": {"triggerType": "TIMER", "context": "RFMS"}, "createdDateTime": "2026-11-20T06:00:00Z", "receivedDateTime": "2026-11-20T06:00:05Z",
  "gnssPosition": {"latitude": 55.68, "longitude": 12.57, "positionDateTime": "2026-11-20T06:00:00Z"}},
 {"vin": "WDB9634031L123456", "triggerType": {"triggerType": "TIMER", "context": "RFMS"}, "createdDateTime": "2026-11-20T06:00:00Z", "receivedDateTime": "2026-11-20T06:00:05Z",
  "gnssPosition": {"latitude": 48.1, "longitude": 11.5, "positionDateTime": "2026-11-20T06:00:00Z"}}
 ]}, "moreDataAvailable": false, "requestServerDateTime": "2026-11-21T08:00:00Z"}`
	st := `[{"vehicleStatusResponse": {"vehicleStatuses": [
 {"vin": "YS2R4X20005399401", "createdDateTime": "2026-11-20T05:55:00Z", "hrTotalVehicleDistance": 500000000, "engineTotalFuelUsed": 1000000000, "grossCombinationVehicleWeight": 38000},
 {"vin": "YS2R4X20005399401", "createdDateTime": "2026-11-20T07:10:00Z", "hrTotalVehicleDistance": 500642100, "engineTotalFuelUsed": 1000213400,
  "snapshotData": {"gnssPosition": {"latitude": 54.7, "longitude": 11.4, "positionDateTime": "2026-11-20T07:10:00Z"}}}
 ]}, "moreDataAvailable": false, "requestServerDateTime": "2026-11-21T08:00:00Z"}]`
	pp, sp := filepath.Join(dir, "pos.json"), filepath.Join(dir, "st.json")
	os.WriteFile(pp, []byte(pos), 0o644)
	os.WriteFile(sp, []byte(st), 0o644)
	if _, err := readRFMS([]string{pp, sp}, ""); err == nil || !strings.Contains(err.Error(), "-vin") {
		t.Errorf("two vehicles without -vin: %v", err)
	}
	req, opts, err := parseCalc([]string{"-from", "DKCPH", "-to", "DKRDB", "-cargo-kg", "20000", "-rfms", pp + ", " + sp, "-vin", "YS2R4X20005399401"}, flag.ContinueOnError)
	if err != nil {
		t.Fatal(err)
	}
	want := [][2]float64{{12.57, 55.68}, {11.9, 55.2}, {11.4, 54.7}}
	if !slices.Equal(req.Path, want) || req.DieselL != 213.4 || req.Date != "2026-11-20" {
		t.Errorf("path %v, diesel %v, date %q", req.Path, req.DieselL, req.Date)
	}
	if !strings.Contains(opts.rfms, "213.4 l diesel") || !strings.Contains(opts.rfms, "odometer 642.1 km") || !strings.Contains(opts.rfms, "3 positions") {
		t.Errorf("summary %q", opts.rfms)
	}
	// The user's own litres and date win.
	req, _, err = parseCalc([]string{"-from", "DKCPH", "-to", "DKRDB", "-diesel-l", "200", "-date", "2026-11-21", "-rfms", sp}, flag.ContinueOnError)
	if err != nil || req.DieselL != 200 || req.Date != "2026-11-21" || len(req.Path) != 0 {
		t.Errorf("own litres: %v %v %v %v", req.DieselL, req.Date, req.Path, err)
	}
	reset := `{"vehicleStatusResponse": {"vehicleStatuses": [
 {"vin": "A", "createdDateTime": "2026-11-20T05:00:00Z", "engineTotalFuelUsed": 900},
 {"vin": "A", "createdDateTime": "2026-11-20T06:00:00Z", "engineTotalFuelUsed": 100}]}}`
	if _, err := parseRFMS([][]byte{[]byte(reset)}, ""); err == nil || !strings.Contains(err.Error(), "reset") {
		t.Errorf("counter reset: %v", err)
	}
	if _, err := parseRFMS([][]byte{[]byte(`[[12.5, 55.6], [11.9, 55.2]]`)}, ""); err == nil {
		t.Error("not rFMS: want an error")
	}
	gas := `{"vehicleStatusResponse": {"vehicleStatuses": [
 {"vin": "A", "createdDateTime": "2026-11-20T05:00:00Z", "totalFuelUsedGaseous": 900, "snapshotData": {"gnssPosition": {"latitude": 55.68, "longitude": 12.57, "positionDateTime": "2026-11-20T05:00:00Z"}}},
 {"vin": "A", "createdDateTime": "2026-11-20T06:00:00Z", "totalFuelUsedGaseous": 990, "snapshotData": {"gnssPosition": {"latitude": 55.2, "longitude": 11.9, "positionDateTime": "2026-11-20T06:00:00Z"}}}]}}`
	g, err := parseRFMS([][]byte{[]byte(gas)}, "")
	if err != nil || g.DieselL != 0 || len(g.Path) != 2 || !strings.Contains(g.summary(), "a gas truck") {
		t.Errorf("gas truck: %+v %v", g, err)
	}
	// An electric truck: totalElectricEnergyUsed in Wh.
	ev := strings.ReplaceAll(strings.ReplaceAll(gas, `"totalFuelUsedGaseous": 900`, `"totalElectricEnergyUsed": 5000000`), `"totalFuelUsedGaseous": 990`, `"totalElectricEnergyUsed": 5084250`)
	e, err := parseRFMS([][]byte{[]byte(ev)}, "")
	if err != nil || e.KWh != 84.25 || !strings.Contains(e.summary(), "84.2 kWh") || len(e.Notes) != 0 {
		t.Errorf("electric truck: %+v %v", e, err)
	}
	evp := filepath.Join(t.TempDir(), "ev.json")
	os.WriteFile(evp, []byte(ev), 0o644)
	if req, _, err = parseCalc([]string{"-from", "DKCPH", "-to", "DKRDB", "-co2-class", "5", "-electricity-price", "0.3", "-rfms", evp}, flag.ContinueOnError); err != nil || req.ElectricityKWh != 84.25 || req.ElectricityEURPerKWh != 0.3 {
		t.Errorf("electric flags: %v %v", req.ElectricityKWh, err)
	}
}

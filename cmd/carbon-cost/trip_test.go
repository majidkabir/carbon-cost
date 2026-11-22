package main

import (
	"flag"
	"os"
	"path/filepath"
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

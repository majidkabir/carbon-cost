package roads

import (
	"bytes"
	"compress/gzip"
	"testing"
	"testing/fstest"
)

func gz(t *testing.T, s string) []byte {
	var b bytes.Buffer
	w := gzip.NewWriter(&b)
	w.Write([]byte(s))
	w.Close()
	return b.Bytes()
}

// A motorway along latitude 50.0 from lon 14.0 to 14.1, and a national
// road along latitude 50.01.
func TestClassify(t *testing.T) {
	fsys := fstest.MapFS{"data/cz.json.gz": {Data: gz(t, `{"country":"cz","mw":[[1400000,5000000,1410000,5000000]],"nat":[[1400000,5001000,1410000,5001000]]}`)}}
	ix, err := load(fsys)
	if err != nil {
		t.Fatal(err)
	}
	if !ix.Has("CZ") || ix.Has("PL") {
		t.Fatal("Has")
	}
	pts := [][2]float64{
		{14.00, 50.0001}, {14.02, 50.0002}, {14.04, 49.9998}, // motorway, 20 m off
		{14.05, 50.0100}, {14.07, 50.0100}, // national road
		{14.08, 50.0300}, {14.09, 50.0300}, // local
	}
	k, ok := ix.Classify("CZ", pts)
	if !ok {
		t.Fatal("not classified")
	}
	// 2 motorway segments (~2.9 km), mw->nat and nat->nat national,
	// nat->local and local->local local.
	if k.Motorway < 2.8 || k.Motorway > 3.0 || k.National < 2.5 || k.National > 3.0 || k.Local < 2.0 || k.Local > 3.6 {
		t.Errorf("%+v", k)
	}
	if _, ok := ix.Classify("PL", pts); ok {
		t.Error("PL classified")
	}
}

func TestDefault(t *testing.T) {
	ix, err := Default()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []string{"CZ", "PL", "BG", "SK", "HU", "RO"} {
		if !ix.Has(c) {
			t.Errorf("no ways for %s", c)
		}
	}
}

// Km counted as local but within NearM of a tolled road are uncertain;
// the extract date is read from the file.
func TestUncertain(t *testing.T) {
	fsys := fstest.MapFS{"data/cz.json.gz": {Data: gz(t, `{"country":"cz","osm_extract":"2026-11-08","mw":[[1400000,5000000,1410000,5000000]],"nat":[]}`)}}
	ix, err := load(fsys)
	if err != nil {
		t.Fatal(err)
	}
	if ix.Extract("CZ") != "2026-11-08" || ix.Extract("PL") != "" {
		t.Errorf("extract %q", ix.Extract("CZ"))
	}
	near, _ := ix.Classify("CZ", [][2]float64{{14.01, 50.0009}, {14.05, 50.0009}}) // 100 m off
	far, _ := ix.Classify("CZ", [][2]float64{{14.01, 50.005}, {14.05, 50.005}})    // 550 m off
	if near.Motorway != 0 || near.Uncertain < 2.8 || near.Uncertain != near.Local {
		t.Errorf("near %+v", near)
	}
	if far.Uncertain != 0 || far.Local < 2.8 {
		t.Errorf("far %+v", far)
	}
}

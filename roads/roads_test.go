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

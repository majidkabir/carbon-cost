package roads

import (
	"bytes"
	"compress/gzip"
	"strings"
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

// Poland's concession motorways (A4 Katowice-Kraków, A2 Świecko-Konin, A1
// Rusocin-Toruń) aren't e-TOLL roads: their km aren't motorway km; the A4
// west of Katowice, the A2 east of Konin and the A1 south of Toruń are.
func TestPolandConcessionsLeftOut(t *testing.T) {
	ix, err := Default()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		name string
		path [][2]float64
		mw   bool
	}{
		{"A4 Katowice-Kraków", [][2]float64{{19.48345, 50.12809}, {19.47637, 50.13268}, {19.47233, 50.13496}}, false},
		{"A2 Świecko-Konin", [][2]float64{{15.27033, 52.29541}, {15.27331, 52.29486}, {15.2763, 52.29454}}, false},
		{"A1 Rusocin-Toruń", [][2]float64{{18.62772, 53.83807}, {18.6267, 53.84388}, {18.62644, 53.84677}}, false},
		{"A4 west of Katowice", [][2]float64{{18.9038, 50.24821}, {18.89984, 50.24755}, {18.89749, 50.24734}}, true},
		{"A2 east of Konin", [][2]float64{{18.76627, 52.09968}, {18.76127, 52.10162}, {18.75713, 52.10342}}, true},
		{"A1 south of Toruń", [][2]float64{{18.75001, 52.87431}, {18.74677, 52.87717}, {18.73947, 52.88279}}, true},
	} {
		k, _ := ix.Classify("PL", c.path)
		if (k.Motorway > 0) != c.mw {
			t.Errorf("%s: %+v, want motorway km %v", c.name, k, c.mw)
		}
	}
}

// The data names the stretches it leaves out, for the road-class note.
func TestPolandLeftOutNamed(t *testing.T) {
	ix, err := Default()
	if err != nil {
		t.Fatal(err)
	}
	got := strings.Join(ix.LeftOut("PL"), "; ")
	for _, want := range []string{"A1 Rusocin-Toruń", "A2 Świecko-Konin", "A4 Katowice-Kraków"} {
		if !strings.Contains(got, want) {
			t.Errorf("PL left out %q, want %s", got, want)
		}
	}
	if l := ix.LeftOut("CZ"); len(l) != 0 {
		t.Errorf("CZ left out %v", l)
	}
}

// Budapest's main roads aren't in annex 1 of 25/2013 NFM: Kerepesi út
// (road 3) from Baross tér to Örs vezér tere is local, untolled road.
func TestBudapestNotTolled(t *testing.T) {
	ix, err := Default()
	if err != nil {
		t.Fatal(err)
	}
	var pts [][2]float64
	for i := 0; i <= 44; i++ {
		f := float64(i) / 44
		pts = append(pts, [2]float64{19.07916 + f*(19.14071-19.07916), 47.49948 + f*(47.50366-47.49948)})
	}
	k, _ := ix.Classify("HU", pts)
	if k.Motorway+k.National > 0.1 {
		t.Errorf("Kerepesi út: %+v", k)
	}
}

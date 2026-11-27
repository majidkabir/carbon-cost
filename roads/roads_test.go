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

// Road 21 Hatvan–Salgótarján, 2x2, where OSM's toll-section relations
// lack 21u7k310m–21u11k1015m (7+310–14+263) and annex 1 runs on between
// 21u6k640m and 21u14k263m: tolled main road, not local.
func TestHungaryDualCarriagewayGap(t *testing.T) {
	ix, err := Default()
	if err != nil {
		t.Fatal(err)
	}
	k, _ := ix.Classify("HU", [][2]float64{{19.66316, 47.73772}, {19.66294, 47.74044}, {19.66304, 47.74258}, {19.66424, 47.75065}, {19.66544, 47.75871}})
	if k.National < 2 || k.Local > 0.2 {
		t.Errorf("road 21 at 47.74-47.76 N: %+v", k)
	}
}

// Czechia tolls the class I roads of annex 2 of vyhláška č. 470/2012 Sb.,
// where the toll operator's map draws them: I/3 Mirošovice–Mezno is
// tolled; I/2 and I/9, which the annex doesn't list, aren't; the old I/55
// Přerov–Hulín, class II road 655 in OpenStreetMap, the map still tolls
// as a class I road.
func TestCzechTolledClassI(t *testing.T) {
	ix, err := Default()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		name   string
		path   [][2]float64
		tolled bool
	}{
		{"I/3 Mirošovice-Mezno", [][2]float64{{14.66406, 49.74099}, {14.66273, 49.73988}, {14.66214, 49.73892}, {14.66185, 49.73801}}, true},
		{"II/655 Přerov-Hulín", [][2]float64{{17.45113, 49.33785}, {17.4487, 49.34039}, {17.44785, 49.34162}, {17.44703, 49.34382}, {17.44633, 49.3469}}, true},
		{"I/2 Kostelec", [][2]float64{{14.83848, 49.98847}, {14.83999, 49.98737}, {14.84194, 49.98636}, {14.84406, 49.98562}}, false},
		{"I/9 Mělník", [][2]float64{{14.48426, 50.19186}, {14.48473, 50.19292}, {14.48539, 50.19394}, {14.4865, 50.19512}}, false},
	} {
		k, _ := ix.Classify("CZ", c.path)
		if (k.National > 0 && k.Motorway == 0 && k.Local < 0.05) != c.tolled || (!c.tolled && k.Local < k.Total()-0.01) {
			t.Errorf("%s: %+v, want tolled class I %v", c.name, k, c.tolled)
		}
	}
}

// Bulgaria tolls its class I and II roads where the toll segments of the
// list run: I-1 through Kresna, between two segments, isn't tolled;
// II-99 Atia–Burgas, one of the listed class II roads, is.
func TestBulgariaTollSegments(t *testing.T) {
	ix, err := Default()
	if err != nil {
		t.Fatal(err)
	}
	kresna, _ := ix.Classify("BG", [][2]float64{{23.15085, 41.72757}, {23.15061, 41.72648}, {23.15152, 41.72529}, {23.15291, 41.72392}})
	if kresna.Motorway+kresna.National > 0.05 {
		t.Errorf("I-1 in Kresna: %+v, want local", kresna)
	}
	road99, _ := ix.Classify("BG", [][2]float64{{27.56068, 42.43549}, {27.56245, 42.4377}, {27.56439, 42.44142}, {27.56578, 42.44275}, {27.56688, 42.44338}})
	if road99.National < 0.8 || road99.Local > 0.05 {
		t.Errorf("II-99 Atia-Burgas: %+v, want class I and II", road99)
	}
}

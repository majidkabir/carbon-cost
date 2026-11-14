// Package roads tells which km of a route run on a country's motorways
// and on its other national roads, from OpenStreetMap ways embedded in
// data/ (built by tools/roads). Toll laws in Czechia, Poland, Bulgaria,
// Slovakia, Hungary and Romania charge less off motorways and don't
// charge local roads.
package roads

import (
	"compress/gzip"
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"math"
	"strings"
	"sync"
)

//go:embed data/*.json.gz
var data embed.FS

// MatchM is how close a route point must be to a way to count as on it:
// the ways are simplified to 10 m and Sootcase's route keeps OSRM's
// points.
const MatchM = 40

// NearM is how close a point not on a way must be for the km next to it
// to count as uncertain: route points this near a tolled road may still
// be on it (OSRM's road and OSM's way drawn apart, or a slip road).
const NearM = 150

// Class of road.
const (
	Motorway = "motorway" // the toll law's motorway class
	National = "national" // other national roads
	Local    = "local"    // the rest: not tolled
)

// Km is a country's route km by road class. Where the country's ways
// carry a suburban share (Hungary's toll sections), Known is the km on
// ways with one and Sub that km weighted by it.
type Km struct {
	Motorway, National, Local    float64
	MotorwayKnown, NationalKnown float64
	MotorwaySub, NationalSub     float64
	// Uncertain is the Local km with an end within NearM of a motorway or
	// national road: they may be on it.
	Uncertain float64
	// MotorwayOp is the Motorway km by the ways' operator ("operator|ref"),
	// where the country's ways carry one (Italy's concessions).
	MotorwayOp map[string]float64
}

// Total is all the km.
func (k Km) Total() float64 { return k.Motorway + k.National + k.Local }

// Index holds the ways of the countries in data/.
type Index struct {
	countries map[string]*grid
	extract   map[string]string
}

// Extract is the date of the OpenStreetMap extract a country's ways come
// from ("" if not recorded).
func (ix *Index) Extract(country string) string {
	if ix == nil {
		return ""
	}
	return ix.extract[strings.ToUpper(country)]
}

const cell = 0.01 // degrees

type seg struct {
	a, b  [2]float64 // lon, lat
	class string
	sub   float64 // suburban share, -1 unknown
	op    string  // the way's operator ("operator|ref"), if recorded
}

type grid struct {
	cells map[[2]int32][]seg
}

var (
	once sync.Once
	def  *Index
	err0 error
)

// Default is the index of the embedded data.
func Default() (*Index, error) {
	once.Do(func() { def, err0 = load(data) })
	return def, err0
}

func load(fsys fs.FS) (*Index, error) {
	ix := &Index{countries: map[string]*grid{}, extract: map[string]string{}}
	files, err := fs.Glob(fsys, "data/*.json.gz")
	if err != nil {
		return nil, err
	}
	for _, f := range files {
		r, err := fsys.Open(f)
		if err != nil {
			return nil, err
		}
		zr, err := gzip.NewReader(r)
		if err != nil {
			r.Close()
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		var d struct {
			Country string    `json:"country"`
			Extract string    `json:"osm_extract"`
			MW      [][]int32 `json:"mw"`
			Nat     [][]int32 `json:"nat"`
			MWF     []float64 `json:"mwf"`
			NatF    []float64 `json:"natf"`
			Ops     []string  `json:"ops"`
			MWOp    []int     `json:"mwop"`
		}
		err = json.NewDecoder(zr).Decode(&d)
		r.Close()
		if err != nil {
			return nil, fmt.Errorf("%s: %w", f, err)
		}
		g := &grid{cells: map[[2]int32][]seg{}}
		for _, set := range []struct {
			lines [][]int32
			sub   []float64
			ops   []int
			class string
		}{{d.MW, d.MWF, d.MWOp, Motorway}, {d.Nat, d.NatF, nil, National}} {
			for j, l := range set.lines {
				sub := -1.0
				if j < len(set.sub) {
					sub = set.sub[j]
				}
				op := ""
				if j < len(set.ops) && set.ops[j] >= 0 && set.ops[j] < len(d.Ops) {
					op = d.Ops[set.ops[j]]
				}
				for i := 0; i+3 < len(l); i += 2 {
					g.add(seg{[2]float64{float64(l[i]) / 1e5, float64(l[i+1]) / 1e5}, [2]float64{float64(l[i+2]) / 1e5, float64(l[i+3]) / 1e5}, set.class, sub, op})
				}
			}
		}
		ix.countries[strings.ToUpper(d.Country)] = g
		if d.Extract != "" {
			ix.extract[strings.ToUpper(d.Country)] = d.Extract
		}
	}
	return ix, nil
}

func key(lon, lat float64) [2]int32 {
	return [2]int32{int32(math.Floor(lon / cell)), int32(math.Floor(lat / cell))}
}

func (g *grid) add(s seg) {
	lo, hi := key(math.Min(s.a[0], s.b[0]), math.Min(s.a[1], s.b[1])), key(math.Max(s.a[0], s.b[0]), math.Max(s.a[1], s.b[1]))
	for x := lo[0]; x <= hi[0]; x++ {
		for y := lo[1]; y <= hi[1]; y++ {
			k := [2]int32{x, y}
			g.cells[k] = append(g.cells[k], s)
		}
	}
}

// Has reports whether the index has ways for the country.
func (ix *Index) Has(country string) bool {
	if ix == nil {
		return false
	}
	_, ok := ix.countries[country]
	return ok
}

// classOf is the class of the nearest way within MatchM of p, Motorway
// winning over National when both are near, that way's suburban share
// (-1 unknown) and operator, and whether any way is within NearM.
func (g *grid) classOf(p [2]float64) (string, float64, string, bool) {
	k := key(p[0], p[1])
	best, sub, op, bestD := Local, -1.0, "", math.Inf(1)
	near := false
	for dx := int32(-1); dx <= 1; dx++ {
		for dy := int32(-1); dy <= 1; dy++ {
			for _, s := range g.cells[[2]int32{k[0] + dx, k[1] + dy}] {
				d := distM(p, s.a, s.b)
				if d <= NearM {
					near = true
				}
				if d > MatchM {
					continue
				}
				better := best == Local || (s.class == Motorway && best != Motorway) || (s.class == best && d < bestD)
				if better {
					best, sub, op, bestD = s.class, s.sub, s.op, d
				}
			}
		}
	}
	return best, sub, op, near
}

// Classify gives the km of a country's stretch of route (consecutive
// [lon, lat] points) by road class. A segment is on a motorway when both
// its ends are, on a national road when both ends are on one or the
// other, else local. Its suburban share is its ends' mean where both
// are known.
func (ix *Index) Classify(country string, points [][2]float64) (Km, bool) {
	var k Km
	if ix == nil || len(points) < 2 {
		return k, false
	}
	g, ok := ix.countries[country]
	if !ok {
		return k, false
	}
	prev, ps, po, pn := g.classOf(points[0])
	for i := 1; i < len(points); i++ {
		cur, cs, co, cn := g.classOf(points[i])
		km := haversine(points[i-1], points[i])
		known := ps >= 0 && cs >= 0
		sub := (ps + cs) / 2 * km
		switch {
		case prev == Motorway && cur == Motorway:
			k.Motorway += km
			if op := co; op != "" || po != "" {
				if op == "" {
					op = po
				}
				if k.MotorwayOp == nil {
					k.MotorwayOp = map[string]float64{}
				}
				k.MotorwayOp[op] += km
			}
			if known {
				k.MotorwayKnown += km
				k.MotorwaySub += sub
			}
		case prev != Local && cur != Local:
			k.National += km
			if known {
				k.NationalKnown += km
				k.NationalSub += sub
			}
		default:
			k.Local += km
			if pn || cn {
				k.Uncertain += km
			}
		}
		prev, ps, po, pn = cur, cs, co, cn
	}
	return k, true
}

// distM is the distance in metres from p to the segment ab, on a local
// flat projection.
func distM(p, a, b [2]float64) float64 {
	cos := math.Cos(p[1] * math.Pi / 180)
	ax, ay := (a[0]-p[0])*cos*111320, (a[1]-p[1])*111320
	bx, by := (b[0]-p[0])*cos*111320, (b[1]-p[1])*111320
	dx, dy := bx-ax, by-ay
	t := 0.0
	if l := dx*dx + dy*dy; l > 0 {
		t = math.Max(0, math.Min(1, -(ax*dx+ay*dy)/l))
	}
	x, y := ax+t*dx, ay+t*dy
	return math.Hypot(x, y)
}

func haversine(a, b [2]float64) float64 {
	const r = 6371.0
	la1, la2 := a[1]*math.Pi/180, b[1]*math.Pi/180
	dla, dlo := la2-la1, (b[0]-a[0])*math.Pi/180
	h := math.Sin(dla/2)*math.Sin(dla/2) + math.Cos(la1)*math.Cos(la2)*math.Sin(dlo/2)*math.Sin(dlo/2)
	return 2 * r * math.Asin(math.Sqrt(h))
}

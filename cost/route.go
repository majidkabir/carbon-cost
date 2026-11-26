package cost

import (
	"math"
	"slices"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/sootcase/pkg/borders"
)

// Run is a stretch of the route in one country (Kind "road"), on a
// recognised ferry crossing (Kind "ferry") or at sea (Kind "sea", more
// than borders.NearestKm from any coast), for a map. Consecutive runs
// share their end point.
type Run struct {
	// Kind is "road", "ferry" or "sea"; Country is the road run's.
	Kind    string `json:"kind"`
	Country string `json:"country,omitempty"`
	// Km is the run's length.
	Km     float64      `json:"km"`
	Points [][2]float64 `json:"points"` // [lon, lat]
}

// Route splits a [lon, lat] route into runs by country with the same
// Natural Earth borders and rule Sootcase uses for country_km: each
// segment counts for the country its midpoint is in, else the nearest
// one within borders.NearestKm. The segments between the terminals of
// each crossing in fd are the ferry.
func Route(ix *borders.Index, path [][2]float64, fd *ferries.Data) []Run {
	if ix == nil || len(path) < 2 {
		return nil
	}
	return routeSpans(ix, path, ferrySpans(path, fd))
}

// routeSpans is Route with the ferries' stretches given (index spans).
func routeSpans(ix *borders.Index, path [][2]float64, spans [][2]int) []Run {
	if ix == nil || len(path) < 2 {
		return nil
	}
	onFerry := func(k int) bool {
		for _, s := range spans {
			if k >= s[0] && k < s[1] {
				return true
			}
		}
		return false
	}
	var runs []Run
	for k := 0; k+1 < len(path); k++ {
		seg := path[k : k+2]
		kind, country := "road", ""
		if onFerry(k) {
			kind = "ferry"
		} else {
			for c := range ix.SplitKm(seg) {
				country = c
			}
			if country == "" {
				kind = "sea"
			}
		}
		km := haversine(seg[0][1], seg[0][0], seg[1][1], seg[1][0])
		if n := len(runs); n > 0 && runs[n-1].Kind == kind && runs[n-1].Country == country {
			runs[n-1].Points = append(runs[n-1].Points, round5(seg[1]))
			runs[n-1].Km += km
			continue
		}
		runs = append(runs, Run{Kind: kind, Country: country, Km: km, Points: [][2]float64{round5(seg[0]), round5(seg[1])}})
	}
	for i := range runs {
		runs[i].Km = math.Round(runs[i].Km*10) / 10
	}
	return runs
}

// ferrySpans are the stretches of a path on the crossings in fd it takes,
// from the point nearest one terminal to the one nearest the other, in
// order. A crossing counts where the path reaches both terminals (within
// 2 km, a terminal's place in the data may be off the quay, and nearer
// than half the way across) and goes half the way across at least
// between them: not a road along a harbour passing both, nor a crossing
// whose terminals are one port. Crossings one after another with no more
// than 3 km of path between (a ship calling at a port on the way) are one
// stretch.
func ferrySpans(path [][2]float64, fd *ferries.Data) [][2]int {
	if fd == nil || len(path) < 2 {
		return nil
	}
	var spans [][2]int
	for _, c := range fd.DetectAll(path) {
		if len(c.Terminals) != 2 {
			continue
		}
		t0, t1 := c.Terminals[0], c.Terminals[1]
		across := haversine(t0.Lat, t0.Lon, t1.Lat, t1.Lon)
		a, b := nearestIndex(path, t0), nearestIndex(path, t1)
		at := func(i int, t ferries.Point) bool {
			return haversine(path[i][1], path[i][0], t.Lat, t.Lon) <= min(2, across/2)
		}
		if a != b && across >= 0.5 && at(a, t0) && at(b, t1) && pathKm(path[min(a, b):max(a, b)+1]) >= across/2 {
			spans = append(spans, [2]int{min(a, b), max(a, b)})
		}
	}
	slices.SortFunc(spans, func(a, b [2]int) int { return a[0] - b[0] })
	var out [][2]int
	for _, s := range spans {
		if n := len(out); n > 0 && (s[0] <= out[n-1][1] || pathKm(path[out[n-1][1]:s[0]+1]) <= 3) {
			out[n-1][1] = max(out[n-1][1], s[1])
			continue
		}
		out = append(out, s)
	}
	return out
}

func nearestIndex(path [][2]float64, p ferries.Point) int {
	best, bi := math.Inf(1), 0
	for i, q := range path {
		if d := haversine(q[1], q[0], p.Lat, p.Lon); d < best {
			best, bi = d, i
		}
	}
	return bi
}

func round5(p [2]float64) [2]float64 {
	return [2]float64{math.Round(p[0]*1e5) / 1e5, math.Round(p[1]*1e5) / 1e5}
}

// MapPoints is about the most route points a response's runs keep for
// drawing; pricing uses the full route.
const MapPoints = 2000

// thinRuns keeps about limit points across the runs, evenly by index
// within each run, with each run's first and last.
func thinRuns(runs []Run, limit int) []Run {
	total := 0
	for _, r := range runs {
		total += len(r.Points)
	}
	if total <= limit {
		return runs
	}
	out := make([]Run, len(runs))
	for i, r := range runs {
		n := max(2, len(r.Points)*limit/total)
		if len(r.Points) > n {
			pts := make([][2]float64, 0, n)
			step := float64(len(r.Points)-1) / float64(n-1)
			for k := 0; k < n; k++ {
				pts = append(pts, r.Points[int(math.Round(float64(k)*step))])
			}
			r.Points = pts
		}
		out[i] = r
	}
	return out
}

// Spans are each country's road stretches of the runs, as [from, to] km
// along the route.
func Spans(runs []Run) map[string][][2]float64 {
	out := map[string][][2]float64{}
	pos := 0.0
	for _, r := range runs {
		if r.Kind == "road" && r.Country != "" {
			s := out[r.Country]
			if n := len(s); n > 0 && s[n-1][1] == pos {
				s[n-1][1] = pos + r.Km
			} else {
				s = append(s, [2]float64{pos, pos + r.Km})
			}
			out[r.Country] = s
		}
		pos += r.Km
	}
	return out
}

// RoadKm sums each country's road runs by road class, for the countries
// rx has ways for.
func RoadKm(rx *roads.Index, runs []Run) map[string]roads.Km {
	out := map[string]roads.Km{}
	for _, r := range runs {
		if r.Kind != "road" || !rx.Has(r.Country) {
			continue
		}
		if k, ok := rx.Classify(r.Country, r.Points); ok {
			t := out[r.Country]
			t.Motorway += k.Motorway
			t.National += k.National
			t.Local += k.Local
			t.Uncertain += k.Uncertain
			t.MotorwayKnown += k.MotorwayKnown
			for op, km := range k.MotorwayOp {
				if t.MotorwayOp == nil {
					t.MotorwayOp = map[string]float64{}
				}
				t.MotorwayOp[op] += km
			}
			t.NationalKnown += k.NationalKnown
			t.MotorwaySub += k.MotorwaySub
			t.NationalSub += k.NationalSub
			out[r.Country] = t
		}
	}
	return out
}

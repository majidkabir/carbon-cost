package cost

import (
	"math"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/sootcase/pkg/borders"
)

// Run is a stretch of the route in one country (Kind "road"), on a
// recognised ferry crossing (Kind "ferry") or at sea (Kind "sea", more
// than borders.NearestKm from any coast), for a map. Consecutive runs
// share their end point.
type Run struct {
	Kind    string       `json:"kind"`
	Country string       `json:"country,omitempty"`
	Km      float64      `json:"km"`
	Points  [][2]float64 `json:"points"` // [lon, lat]
}

// Route splits a [lon, lat] route into runs by country with the same
// Natural Earth borders and rule Sootcase uses for country_km: each
// segment counts for the country its midpoint is in, else the nearest
// one within borders.NearestKm. The segments between the terminals of a
// crossing in fd are the ferry.
func Route(ix *borders.Index, path [][2]float64, fd *ferries.Data) []Run {
	if ix == nil || len(path) < 2 {
		return nil
	}
	lo, hi := -1, -1
	if fd != nil {
		if c, ok := fd.Detect(path); ok && len(c.Terminals) == 2 {
			a, b := nearestIndex(path, c.Terminals[0]), nearestIndex(path, c.Terminals[1])
			lo, hi = min(a, b), max(a, b)
		}
	}
	var runs []Run
	for k := 0; k+1 < len(path); k++ {
		seg := path[k : k+2]
		kind, country := "road", ""
		if k >= lo && k < hi {
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

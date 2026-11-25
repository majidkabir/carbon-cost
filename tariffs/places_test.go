package tariffs

import (
	"encoding/json"
	"math"
	"testing"
)

// No station or point of one scheme sits where another scheme's does
// while both are in force: a gantry or booth collects one charge, so a
// shared place is one scheme's object placed at the other's (Skurubron's
// bridge gantries taken for Stockholm's congestion tax, a Spanish
// junction taken for a French one).
func TestNoSharedPlaces(t *testing.T) {
	s, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	type place struct {
		d        *Dataset
		name     string
		lat, lon float64
	}
	cell := func(lat, lon float64) [2]int { return [2]int{int(math.Floor(lat * 100)), int(math.Floor(lon * 100))} }
	grid := map[[2]int][]place{}
	for _, d := range s.All {
		for _, o := range d.Objects() {
			if o.Location == nil || o.Location.Geometry == nil {
				continue
			}
			var pts [][2]float64
			switch g := o.Location.Geometry; g.Type {
			case "Point":
				var p [2]float64
				if json.Unmarshal(g.Coordinates, &p) == nil {
					pts = append(pts, p)
				}
			case "MultiPoint":
				json.Unmarshal(g.Coordinates, &pts)
			}
			for _, p := range pts {
				c := cell(p[1], p[0])
				grid[c] = append(grid[c], place{d, o.Name, p[1], p[0]})
			}
		}
	}
	to := func(d *Dataset) string {
		if d.ValidTo == "" {
			return "9999-12-31"
		}
		return d.ValidTo
	}
	seen := map[string]bool{}
	for c, ps := range grid {
		for _, p := range ps {
			for dl := -1; dl <= 1; dl++ {
				for dn := -1; dn <= 1; dn++ {
					for _, q := range grid[[2]int{c[0] + dl, c[1] + dn}] {
						if p.d.Scheme >= q.d.Scheme || p.d.ValidFrom > to(q.d) || q.d.ValidFrom > to(p.d) {
							continue
						}
						m := math.Hypot((p.lat-q.lat)*111e3, (p.lon-q.lon)*111e3*math.Cos(p.lat*math.Pi/180))
						key := p.d.File + p.name + q.d.File + q.name
						if m < 150 && !seen[key] {
							seen[key] = true
							t.Errorf("%s %q is %.0f m from %s %q", p.d.File, p.name, m, q.d.File, q.name)
						}
					}
				}
			}
		}
	}
}

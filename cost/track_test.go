package cost

import (
	"math"
	"math/rand"
	"testing"

	"github.com/majidkabir/carbon-cost/rates"
)

// bruteProject scans every segment, as project did before the index.
func bruteProject(route [][2]float64, p rates.Place) (pos, dist float64) {
	dist = math.Inf(1)
	cos := math.Cos(p.Lat * math.Pi / 180)
	var cum float64
	for i := 0; i+1 < len(route); i++ {
		a, b := route[i], route[i+1]
		seg := haversine(a[1], a[0], b[1], b[0])
		ax, ay := (a[0]-p.Lon)*cos*111.2, (a[1]-p.Lat)*111.2
		bx, by := (b[0]-p.Lon)*cos*111.2, (b[1]-p.Lat)*111.2
		dx, dy := bx-ax, by-ay
		t := 0.0
		if l := dx*dx + dy*dy; l > 0 {
			t = math.Max(0, math.Min(1, -(ax*dx+ay*dy)/l))
		}
		if d := math.Hypot(ax+t*dx, ay+t*dy); d < dist && seg > 0 {
			dist, pos = d, cum+t*seg
		}
		cum += seg
	}
	return pos, dist
}

// The index finds what a full scan finds, within searchKm.
func TestTrackProject(t *testing.T) {
	r := rand.New(rand.NewSource(1))
	route := [][2]float64{{10, 60}}
	for i := 0; i < 5000; i++ {
		q := route[len(route)-1]
		route = append(route, [2]float64{q[0] + (r.Float64()-0.3)*0.004, q[1] + (r.Float64()-0.4)*0.003})
	}
	tr := newTrack(route)
	for i := 0; i < 2000; i++ {
		q := route[r.Intn(len(route))]
		p := rates.Place{Lat: q[1] + (r.Float64()-0.5)*0.04, Lon: q[0] + (r.Float64()-0.5)*0.06}
		wp, wd := bruteProject(route, p)
		gp, gd, _ := tr.project(p)
		if wd > searchKm {
			if !math.IsInf(gd, 1) && gd > searchKm {
				t.Fatalf("%v: got %g km off, want none", p, gd)
			}
			continue
		}
		if math.Abs(gd-wd) > 1e-9 || math.Abs(gp-wp) > 1e-6 {
			t.Fatalf("%v: got pos %g dist %g, want %g %g", p, gp, gd, wp, wd)
		}
	}
}

package cost

import (
	"math"

	"github.com/majidkabir/carbon-cost/rates"
)

// track is a route ([lon, lat] points) with its km along it and an index
// of its segments by grid cell, so places can be found along a full route
// of tens of thousands of points without scanning all of it.
type track struct {
	pts   [][2]float64
	cum   []float64 // km along the route at each point
	cells map[[2]int32][]int32
}

// trackCell is the grid cell, in degrees.
const trackCell = 0.02

// searchKm is the farthest a place may lie from the route to be found:
// more than every match distance the tables use.
const searchKm = 2.0

func trackKey(lon, lat float64) [2]int32 {
	return [2]int32{int32(math.Floor(lon / trackCell)), int32(math.Floor(lat / trackCell))}
}

func newTrack(pts [][2]float64) *track {
	t := &track{pts: pts, cum: make([]float64, len(pts)), cells: map[[2]int32][]int32{}}
	for i := 1; i < len(pts); i++ {
		t.cum[i] = t.cum[i-1] + haversine(pts[i-1][1], pts[i-1][0], pts[i][1], pts[i][0])
	}
	for i := 0; i+1 < len(pts); i++ {
		a, b := pts[i], pts[i+1]
		// Walk the segment in half-cell steps; a cell and its neighbours
		// cover what the segment clips.
		n := int(math.Ceil(math.Max(math.Abs(b[0]-a[0]), math.Abs(b[1]-a[1]))/(trackCell/2))) + 1
		seen := map[[2]int32]bool{}
		for s := 0; s <= n; s++ {
			f := float64(s) / float64(n)
			k := trackKey(a[0]+f*(b[0]-a[0]), a[1]+f*(b[1]-a[1]))
			for dx := int32(-1); dx <= 1; dx++ {
				for dy := int32(-1); dy <= 1; dy++ {
					c := [2]int32{k[0] + dx, k[1] + dy}
					if !seen[c] {
						seen[c] = true
						t.cells[c] = append(t.cells[c], int32(i))
					}
				}
			}
		}
	}
	return t
}

// project finds the point of the route nearest p: its km along the route,
// its distance from p in km (+Inf beyond searchKm) and the direction of
// travel there in degrees clockwise from north. On a tie the earlier
// segment wins.
func (t *track) project(p rates.Place) (pos, dist, heading float64) {
	dist = math.Inf(1)
	if t == nil || len(t.pts) < 2 {
		return 0, dist, 0
	}
	cos := math.Cos(p.Lat * math.Pi / 180)
	dLat := searchKm / 111.2
	dLon := dLat / math.Max(cos, 0.01)
	lo, hi := trackKey(p.Lon-dLon, p.Lat-dLat), trackKey(p.Lon+dLon, p.Lat+dLat)
	best := int32(-1)
	for x := lo[0]; x <= hi[0]; x++ {
		for y := lo[1]; y <= hi[1]; y++ {
			for _, i := range t.cells[[2]int32{x, y}] {
				a, b := t.pts[i], t.pts[i+1]
				seg := t.cum[i+1] - t.cum[i]
				if seg <= 0 {
					continue
				}
				ax, ay := (a[0]-p.Lon)*cos*111.2, (a[1]-p.Lat)*111.2
				bx, by := (b[0]-p.Lon)*cos*111.2, (b[1]-p.Lat)*111.2
				dx, dy := bx-ax, by-ay
				u := 0.0
				if l := dx*dx + dy*dy; l > 0 {
					u = math.Max(0, math.Min(1, -(ax*dx+ay*dy)/l))
				}
				d := math.Hypot(ax+u*dx, ay+u*dy)
				if d > searchKm || d > dist || (d == dist && i > best) {
					continue
				}
				best, dist, pos = i, d, t.cum[i]+u*seg
				heading = math.Mod(math.Atan2(dx, dy)*180/math.Pi+360, 360)
			}
		}
	}
	return pos, dist, heading
}

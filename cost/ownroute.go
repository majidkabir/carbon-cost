package cost

import (
	"fmt"
	"math"
	"regexp"
	"slices"
	"strings"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/carbon-cost/tariffs"
	"github.com/majidkabir/sootcase/pkg/borders"
)

// MaxPathPoints is the most points a path may have: a GPS track of a day
// at one point every few seconds.
const MaxPathPoints = 200000

// DieselKgCO2ePerLWTW is the well-to-wheel CO2e of a litre of diesel (EN
// 16258:2012, Annex A, Table A.1: 3.90 kg CO2e per kg at 0.832 kg per
// litre), for a trip priced on country_km, which Sootcase doesn't route.
const DieselKgCO2ePerLWTW = 3.24

// areaRE is a country (ISO 3166-1 alpha-2) or a region (ISO 3166-2).
var areaRE = regexp.MustCompile(`^[A-Z]{2}(-[A-Z0-9]{1,3})?$`)

// pathNearKm is how far from a stop the path may pass without a note.
const pathNearKm = 5

// maxPathStepDeg and maxPathSpanDeg bound a path: degrees between two
// points (some 2,000 km), and in all.
const maxPathStepDeg, maxPathSpanDeg = 20.0, 600.0

func checkOwnRoute(r Request) error {
	if len(r.Path) > 0 {
		if len(r.CountryKm) > 0 {
			return fmt.Errorf("give path or country_km, not both")
		}
		if len(r.Path) < 2 || len(r.Path) > MaxPathPoints {
			return fmt.Errorf("path: give 2 to %d [lon, lat] points", MaxPathPoints)
		}
		// A truck's way: no jump across the map between two points, and
		// not around the world (each degree crossed costs the track's
		// index its cells).
		var span float64
		for i, p := range r.Path {
			if !(p[0] >= -180 && p[0] <= 180 && p[1] >= -90 && p[1] <= 90) {
				return fmt.Errorf("path[%d]: give [lon, lat] in degrees", i)
			}
			if i > 0 {
				q := r.Path[i-1]
				d := math.Max(math.Abs(p[0]-q[0]), math.Abs(p[1]-q[1]))
				if d > maxPathStepDeg {
					return fmt.Errorf("path[%d]: %.1f degrees from the point before it; give points at most %g degrees apart", i, d, maxPathStepDeg)
				}
				span += d
			}
		}
		if span > maxPathSpanDeg {
			return fmt.Errorf("path: %.0f degrees in all; give at most %g (some 40,000 km)", span, maxPathSpanDeg)
		}
	}
	if len(r.CountryKm) == 0 {
		return nil
	}
	if len(r.Stops) > 0 || len(r.Shipments) > 0 || r.From != (sootcase.Location{}) || r.To != (sootcase.Location{}) {
		return fmt.Errorf("country_km prices one trip with no route: not with from, to, stops or shipments (give path for the way driven)")
	}
	whole := map[string]bool{}
	for k, v := range r.CountryKm {
		if !areaRE.MatchString(k) {
			return fmt.Errorf("country_km: %q is no ISO 3166-1 alpha-2 country or ISO 3166-2 region", k)
		}
		if !(v > 0 && v < 100000) {
			return fmt.Errorf("country_km.%s must be > 0 and < 100000", k)
		}
		if !strings.Contains(k, "-") {
			whole[k] = true
		}
	}
	for k := range r.CountryKm {
		if cc, _, ok := strings.Cut(k, "-"); ok && whole[cc] {
			return fmt.Errorf("country_km: give %s or its regions, not both", cc)
		}
	}
	return nil
}

// checkRegional refuses country_km for a whole country whose tolls are
// set by region (Belgium's): its km can't be priced without the split.
func checkRegional(set *tariffs.Set, km map[string]float64) error {
	for k := range km {
		if strings.Contains(k, "-") || set == nil || !set.Regional(k) {
			continue
		}
		var regions []string
		for _, d := range set.All {
			if d.Kind == tariffs.Toll && d.Country == k && d.Region != "" && !slices.Contains(regions, d.Region) {
				regions = append(regions, d.Region)
			}
		}
		slices.Sort(regions)
		return fmt.Errorf("country_km: %s's tolls are set by region: give the km in each (%s)", k, strings.Join(regions, ", "))
	}
	return nil
}

// kmTrip is a trip of one leg with only its km by country: a region's
// km count for its country too.
func kmTrip(req *Request) sootcase.Result {
	l := sootcase.LegResult{CountryKm: map[string]float64{}, RouteParts: map[string]float64{}}
	for k, v := range req.CountryKm {
		cc, _, region := strings.Cut(k, "-")
		l.CountryKm[cc] += v
		l.DistanceKm += v
		if region {
			if l.RegionKm == nil {
				l.RegionKm = map[string]float64{}
			}
			l.RegionKm[k] += v
		}
	}
	req.legLoadKg = []float64{req.CargoKg}
	return sootcase.Result{Legs: []sootcase.LegResult{l}}
}

// ownPath puts the way the truck drove in place of Sootcase's route: the
// path split into legs at the points nearest the stops (where Sootcase's
// legs end), and each leg's km, km by country and region and its ferry
// crossings from it. Sootcase's emissions stay: they are the shipments',
// on their own routes, the transport activity distance of EN ISO 14083.
func ownPath(ix *borders.Index, fd *ferries.Data, res *sootcase.Result, path [][2]float64) []string {
	given := len(path)
	path = compactPath(path, parkedKm)
	var notes []string
	var sootKm float64
	for _, l := range res.Legs {
		sootKm += l.DistanceKm
	}
	// The stops: the ends of Sootcase's legs.
	var stops [][2]float64
	ok := true
	for _, l := range res.Legs {
		if len(l.Path) == 0 {
			ok = false
			break
		}
	}
	if ok {
		stops = append(stops, res.Legs[0].Path[0])
		for _, l := range res.Legs {
			stops = append(stops, l.Path[len(l.Path)-1])
		}
	}
	cut := make([]int, 0, len(res.Legs)+1)
	cut = append(cut, 0)
	if ok {
		from := 0
		for _, s := range stops[1 : len(stops)-1] {
			from = nearestFrom(path, s, from)
			cut = append(cut, from)
		}
	} else {
		// No route points from Sootcase: split by its legs' km.
		cum := make([]float64, len(path))
		for i := 1; i < len(path); i++ {
			cum[i] = cum[i-1] + haversine(path[i-1][1], path[i-1][0], path[i][1], path[i][0])
		}
		var at float64
		for _, l := range res.Legs[:len(res.Legs)-1] {
			at += l.DistanceKm
			want := cum[len(cum)-1] * at / math.Max(sootKm, 1e-9)
			i := cut[len(cut)-1]
			for i < len(path)-1 && cum[i] < want {
				i++
			}
			cut = append(cut, i)
		}
	}
	cut = append(cut, len(path)-1)
	if ok {
		for i, s := range stops {
			p := path[cut[i]]
			if d := haversine(p[1], p[0], s[1], s[0]); d > pathNearKm {
				notes = append(notes, fmt.Sprintf("path: passes %.0f km from stop %d; check it is the trip's way.", d, i))
			}
		}
	}
	var ownKm float64
	for i := range res.Legs {
		l := &res.Legs[i]
		seg := path[cut[i] : cut[i+1]+1]
		if len(seg) < 2 {
			seg = [][2]float64{path[cut[i]], path[cut[i]]}
		}
		// The parts in the path's order: its road stretches (Sootcase's
		// road emissions shared by their km) and its ferries.
		var sootFerries []sootcase.Part
		var parts []sootcase.Part
		var roadTTW, roadWTW float64
		for _, p := range l.Parts {
			if p.Kind == "ferry" {
				sootFerries = append(sootFerries, p)
			} else {
				roadTTW, roadWTW = roadTTW+p.TTWKg, roadWTW+p.WTWKg
			}
		}
		var stretches []int // parts that are road, for their shares
		spans := ferrySpans(seg, fd)
		km := round3(pathKm(seg))
		l.DistanceKm, l.Path = km, seg
		l.CountryKm, l.RegionKm = map[string]float64{}, nil
		var ferryKm float64
		at := 0
		addRoad := func(line [][2]float64) {
			if len(line) < 2 {
				return
			}
			if rkm := pathKm(line); rkm > 0 {
				stretches = append(stretches, len(parts))
				parts = append(parts, sootcase.Part{Kind: "road", DistanceKm: round3(rkm)})
			}
			cs, rs := ix.SplitKmRegions(line)
			for k, v := range cs {
				if k != "" {
					l.CountryKm[k] += v
				}
			}
			for k, v := range rs {
				if l.RegionKm == nil {
					l.RegionKm = map[string]float64{}
				}
				l.RegionKm[k] += v
			}
		}
		for n, s := range spans {
			addRoad(seg[at : s[0]+1])
			fkm := round3(pathKm(seg[s[0] : s[1]+1]))
			ferryKm += fkm
			p := sootcase.Part{Kind: "ferry", DistanceKm: fkm}
			if n < len(sootFerries) && sootFerries[n].DistanceKm > 0 {
				f := fkm / sootFerries[n].DistanceKm
				p.TTWKg, p.WTWKg = sootFerries[n].TTWKg*f, sootFerries[n].WTWKg*f
			} else {
				notes = append(notes, fmt.Sprintf("path: a ferry crossing (%.0f km) Sootcase's route doesn't take: its EU ETS uses the ships' MRV data when the crossing is known and truck.tare_kg given, else it isn't priced.", fkm))
			}
			parts = append(parts, p)
			at = s[1]
		}
		addRoad(seg[at:])
		var roadKm float64
		for _, i := range stretches {
			roadKm += parts[i].DistanceKm
		}
		for _, i := range stretches {
			if roadKm > 0 {
				f := parts[i].DistanceKm / roadKm
				parts[i].TTWKg, parts[i].WTWKg = roadTTW*f, roadWTW*f
			}
		}
		if l.RouteParts == nil {
			l.RouteParts = map[string]float64{}
		}
		delete(l.RouteParts, "ferry")
		if ferryKm > 0 {
			l.RouteParts["ferry"] = round3(ferryKm)
		}
		if _, had := l.RouteParts["road"]; had {
			l.RouteParts["road"] = km - ferryKm
		}
		l.Parts = parts
		// Sootcase's country sections, main roads and driving time are its
		// route's: the path's own sections, by the same borders; its roads
		// aren't known, and its time is its km at avg_speed_kmh.
		l.CountrySections, l.Summary, l.DurationH = sectionsOf(ix, Route(ix, seg, fd)), nil, 0
		ownKm += km
	}
	notes = append(notes, fmt.Sprintf("Route: the path given (%d points, %.1f km), not Sootcase's (%.1f km); the shipments' emissions are Sootcase's on their own routes (EN ISO 14083's transport activity distance).", given, ownKm, sootKm))
	return notes
}

// parkedKm is how far a GPS fix must be from the last one kept to count:
// fixes logged while the truck stands (a stop, a break) wander a few
// metres, and would add km and seem to drive back past a booth.
const parkedKm = 0.025

// compactPath keeps a path's first and last points and each one at least
// minKm from the one kept before it.
func compactPath(path [][2]float64, minKm float64) [][2]float64 {
	if len(path) < 3 {
		return path
	}
	out := [][2]float64{path[0]}
	for _, p := range path[1 : len(path)-1] {
		q := out[len(out)-1]
		if haversine(q[1], q[0], p[1], p[0]) >= minKm {
			out = append(out, p)
		}
	}
	last := path[len(path)-1]
	if q := out[len(out)-1]; len(out) > 1 && haversine(q[1], q[0], last[1], last[0]) < minKm {
		out[len(out)-1] = last
	} else {
		out = append(out, last)
	}
	return out
}

// sectionsOf are a path's runs as country sections, as Sootcase gives
// them: each country's stretch in order, ferries apart.
func sectionsOf(ix *borders.Index, runs []Run) []sootcase.CountrySection {
	var out []sootcase.CountrySection
	pos := 0.0
	for _, r := range runs {
		ferry := r.Kind != "road"
		if n := len(out); n > 0 && out[n-1].Country == r.Country && out[n-1].Ferry == ferry {
			out[n-1].ToKm = pos + r.Km
		} else {
			out = append(out, sootcase.CountrySection{Country: r.Country, FromKm: pos, ToKm: pos + r.Km, Ferry: ferry})
		}
		if !ferry && ix != nil {
			s := &out[len(out)-1]
			s.Regions = append(s.Regions, regionsOf(ix, r, pos)...)
			if n := len(s.Regions); n > 1 && s.Regions[n-2].Region == s.Regions[n-1].Region {
				s.Regions[n-2].ToKm = s.Regions[n-1].ToKm
				s.Regions = s.Regions[:n-1]
			}
		}
		pos += r.Km
	}
	return out
}

// regionsOf are a road run's regions in order (Belgium's: its km by
// region, by the day each is driven), from its first-level regions where
// the borders have them; each step of the path in the region it is most
// in. pos is where the run starts.
func regionsOf(ix *borders.Index, r Run, pos float64) []sootcase.RegionSection {
	if _, rs := ix.SplitKmRegions(r.Points); len(rs) == 0 {
		return nil
	}
	var out []sootcase.RegionSection
	at, scale, walked := pos, 1.0, 0.0
	for i := 0; i+1 < len(r.Points); i++ {
		walked += haversine(r.Points[i][1], r.Points[i][0], r.Points[i+1][1], r.Points[i+1][0])
	}
	if walked > 0 {
		scale = r.Km / walked // the run's km, as Route counted them
	}
	for i := 0; i+1 < len(r.Points); i++ {
		a, b := r.Points[i], r.Points[i+1]
		km := haversine(a[1], a[0], b[1], b[0]) * scale
		_, rs := ix.SplitKmRegions([][2]float64{a, b})
		best, most := "", 0.0
		for k, v := range rs {
			if v > most || v == most && k < best {
				best, most = k, v
			}
		}
		switch n := len(out); {
		case best == "":
		case n > 0 && out[n-1].Region == best:
			out[n-1].ToKm = at + km
		default:
			out = append(out, sootcase.RegionSection{Region: best, FromKm: at, ToKm: at + km})
		}
		at += km
	}
	return out
}

// nearestFrom is the index of the path point nearest p from index from
// on: the first close pass (within pathNearKm) wins over a later one.
func nearestFrom(path [][2]float64, p [2]float64, from int) int {
	best, bi, near := math.Inf(1), from, false
	for i := from; i < len(path); i++ {
		d := haversine(path[i][1], path[i][0], p[1], p[0])
		if d < best {
			best, bi = d, i
		}
		if d <= pathNearKm {
			near = true
		}
		if near && d > best+4*pathNearKm {
			break
		}
	}
	return bi
}

func pathKm(line [][2]float64) float64 {
	var km float64
	for i := 1; i < len(line); i++ {
		km += haversine(line[i-1][1], line[i-1][0], line[i][1], line[i][0])
	}
	return km
}

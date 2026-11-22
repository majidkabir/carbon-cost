package cost

import (
	"fmt"
	"math"
	"regexp"
	"strings"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/sootcase"
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

func checkOwnRoute(r Request) error {
	if len(r.Path) > 0 {
		if len(r.CountryKm) > 0 {
			return fmt.Errorf("give path or country_km, not both")
		}
		if len(r.Path) < 2 || len(r.Path) > MaxPathPoints {
			return fmt.Errorf("path: give 2 to %d [lon, lat] points", MaxPathPoints)
		}
		for i, p := range r.Path {
			if !(p[0] >= -180 && p[0] <= 180 && p[1] >= -90 && p[1] <= 90) {
				return fmt.Errorf("path[%d]: give [lon, lat] in degrees", i)
			}
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
		var sootFerries []sootcase.Part
		var parts []sootcase.Part
		for _, p := range l.Parts {
			if p.Kind == "ferry" {
				sootFerries = append(sootFerries, p)
			} else {
				parts = append(parts, p)
			}
		}
		var spans [][2]int
		if fd != nil {
			for _, c := range fd.DetectAll(seg) {
				if len(c.Terminals) == 2 {
					a, b := nearestIndex(seg, c.Terminals[0]), nearestIndex(seg, c.Terminals[1])
					if a != b {
						spans = append(spans, [2]int{min(a, b), max(a, b)})
					}
				}
			}
		}
		km := pathKm(seg)
		l.DistanceKm, l.Path = km, seg
		l.CountryKm, l.RegionKm = map[string]float64{}, nil
		var ferryKm float64
		at := 0
		addRoad := func(line [][2]float64) {
			if len(line) < 2 {
				return
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
			if s[0] < at {
				continue // overlaps the one before
			}
			addRoad(seg[at : s[0]+1])
			fkm := pathKm(seg[s[0] : s[1]+1])
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
		if l.RouteParts == nil {
			l.RouteParts = map[string]float64{}
		}
		delete(l.RouteParts, "ferry")
		if ferryKm > 0 {
			l.RouteParts["ferry"] = ferryKm
		}
		if _, had := l.RouteParts["road"]; had {
			l.RouteParts["road"] = km - ferryKm
		}
		l.Parts = parts
		ownKm += km
	}
	notes = append(notes, fmt.Sprintf("Route: the path given (%d points, %.1f km), not Sootcase's (%.1f km); the shipments' emissions are Sootcase's on their own routes (EN ISO 14083's transport activity distance).", len(path), ownKm, sootKm))
	return notes
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

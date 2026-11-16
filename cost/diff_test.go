package cost

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/internal/legacy"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// TestDiffLegacy prices a corpus of trips built from every table with the
// engine before ORCT and with this one, and reports where they differ
// (DIFF=1; DIFF_OUT names a file for the differences).
func TestDiffLegacy(t *testing.T) {
	if os.Getenv("DIFF") == "" {
		t.Skip("DIFF not set")
	}
	tables, err := rates.All()
	if err != nil {
		t.Fatal(err)
	}
	set := all(t)
	type trip struct {
		name   string
		res    sootcase.Result
		req    Request
		date   time.Time
		roadKm map[string]roads.Km
		spans  map[string][][2]float64
		origin string
	}
	var trips []trip
	trucks := []rates.Truck{truck40, {MaxMassKg: 12000, Axles: 2, Euro: 5, CO2Class: 1}, {MaxMassKg: 44000, Axles: 5, Euro: 6, CO2Class: 5},
		{MaxMassKg: 26000, Axles: 3, Euro: 4, CO2Class: 1, LengthM: 12}}
	times := []string{"", "03:00", "07:30", "12:00", "16:00", "23:30"}
	day := func(s string) time.Time { d, _ := time.Parse(time.DateOnly, s); return d }
	dates := func(tb rates.Table) []time.Time {
		d := day(tb.ValidFrom)
		out := []time.Time{d, d.AddDate(0, 0, 5)}
		if tb.ValidTo != "" && day(tb.ValidTo).Before(out[1]) {
			out = out[:1]
		}
		return out
	}
	line := func(a, b rates.Place, cc string) sootcase.Result {
		pts := [][2]float64{{a.Lon, a.Lat}, {b.Lon, b.Lat}}
		km := haversine(a.Lat, a.Lon, b.Lat, b.Lon)
		return sootcase.Result{TTWKg: 50, Legs: []sootcase.LegResult{{DistanceKm: km, CountryKm: map[string]float64{cc: km}, Path: pts}}}
	}
	offset := func(p rates.Place, bearing, km float64) rates.Place {
		r := bearing * math.Pi / 180
		return rates.Place{Lat: p.Lat + km*math.Cos(r)/111.2, Lon: p.Lon + km*math.Sin(r)/(111.2*math.Cos(p.Lat*math.Pi/180))}
	}
	for _, tb := range tables {
		cc := tb.Country
		for _, d := range dates(tb) {
			// Rows: 100 km, with and without road classes.
			if len(tb.Rows) > 0 {
				res := sootcase.Result{TTWKg: 80, Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{cc: 100}}}}
				if tb.Region != "" {
					res.Legs[0].RegionKm = map[string]float64{tb.Region: 100}
				}
				for _, tr := range trucks {
					for _, rk := range []map[string]roads.Km{nil,
						{cc: {Motorway: 60, National: 30, Local: 10, MotorwayKnown: 40, MotorwaySub: 10, NationalKnown: 10, NationalSub: 5}},
						{cc: {Motorway: 80, National: 20, MotorwayOp: opsOf(tb, 50)}}} {
						trips = append(trips, trip{fmt.Sprintf("%s rows %v rk=%v", tb.File, tr, rk != nil), res, Request{CargoKg: 1000, Truck: tr}, d, rk, nil, ""})
					}
					trips = append(trips, trip{tb.File + " rows shares", res, Request{CargoKg: 1000, Truck: tr, TolledShare: map[string]float64{cc: 0.5},
						MotorwayShare: map[string]float64{cc: 0.7}, EnvZoneKm: map[string]float64{cc: 3}}, d, nil, nil, ""})
					if tb.PerDay {
						for _, tm := range []string{"08:00", "22:00"} {
							trips = append(trips, trip{tb.File + " per day " + tm, res, Request{CargoKg: 1000, Truck: tr, Time: tm}, d, nil,
								map[string][][2]float64{cc: {{0, 100}, {150, 1500}}}, cc})
						}
					}
				}
			}
			// Toll points: through each, both ways, at several times.
			for j, p := range tb.TollPoints {
				if !p.InForce(d) {
					continue
				}
				if j%3 != 0 && len(tb.TollPoints) > 60 {
					continue
				}
				h := 0.0
				if p.Heading != nil {
					h = *p.Heading
				}
				pl := rates.Place{Lat: p.Lat, Lon: p.Lon}
				for _, back := range []bool{false, true} {
					a, b := offset(pl, h+180, 0.5), offset(pl, h, 0.5)
					if back {
						a, b = b, a
					}
					for _, tm := range times {
						trips = append(trips, trip{fmt.Sprintf("%s point %s back=%v %s", tb.File, p.Name, back, tm), line(a, b, cc), Request{CargoKg: 1000, Truck: truck40, Time: tm, ETC: tm == "12:00"}, d, nil, nil, cc})
					}
				}
				// With the next point of its group, an hour apart or not.
				if p.Group != 0 && j+1 < len(tb.TollPoints) {
					q := tb.TollPoints[j+1]
					if q.Group == p.Group {
						res := line(pl, rates.Place{Lat: q.Lat, Lon: q.Lon}, cc)
						for _, tm := range []string{"", "06:45", "08:00", "14:50"} {
							for _, v := range []float64{0, 5} {
								trips = append(trips, trip{fmt.Sprintf("%s pair %s-%s %s v%g", tb.File, p.Name, q.Name, tm, v), res, Request{CargoKg: 1000, Truck: truck40, Time: tm, AvgSpeedKmh: v}, d, nil, nil, cc})
							}
						}
					}
				}
			}
			// Closed systems: between stations.
			for _, sys := range tb.Closed {
				n := len(sys.Stations)
				step := 1
				if n > 12 {
					step = n / 12
				}
				for i := 0; i < n; i += step {
					for k := i + step; k < n; k += step {
						a, b := sys.Stations[i], sys.Stations[k]
						if len(a.Points) == 0 || len(b.Points) == 0 {
							continue
						}
						for _, tm := range []string{"", "02:00", "12:00"} {
							for _, tr := range trucks[:2] {
								trips = append(trips, trip{fmt.Sprintf("%s system %s %s-%s %s", tb.File, sys.Name, a.Name, b.Name, tm), line(a.Points[0], b.Points[0], cc),
									Request{CargoKg: 1000, Truck: tr, Time: tm, ETC: tm == "12:00"}, d, nil, nil, cc})
							}
						}
					}
				}
			}
			// Sections: from end to end.
			if tb.Sections != nil {
				for _, s := range tb.Sections.List {
					for _, tr := range trucks {
						trips = append(trips, trip{tb.File + " section " + s.Name, line(s.From, s.To, cc), Request{CargoKg: 1000, Truck: tr}, d, nil, nil, cc})
						trips = append(trips, trip{tb.File + " section night " + s.Name, line(s.From, s.To, cc), Request{CargoKg: 1000, Truck: tr, Night: true}, d, nil, nil, cc})
					}
				}
			}
		}
	}
	// Zones: through each polygon's first vertex area.
	zones, _ := rates.ZonesAll()
	for _, z := range zones {
		if len(z.Polygons) == 0 {
			continue
		}
		var c [2]float64
		for _, p := range z.Polygons[0] {
			c[0] += p[0] / float64(len(z.Polygons[0]))
			c[1] += p[1] / float64(len(z.Polygons[0]))
		}
		a, b := rates.Place{Lon: c[0] - 0.3, Lat: c[1]}, rates.Place{Lon: c[0] + 0.3, Lat: c[1]}
		for _, tm := range times {
			for _, tr := range trucks {
				trips = append(trips, trip{"zone " + z.Name + " " + tm, line(a, b, z.Country), Request{CargoKg: 1000, Truck: tr, Time: tm}, day(z.ValidFrom).AddDate(0, 0, 3), nil, nil, z.Country})
			}
		}
	}
	// Fuel CO2: each country.
	fuels, _ := rates.FuelCO2All()
	for _, f := range fuels {
		res := sootcase.Result{TTWKg: 500, Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{f.Country: 60, "DE": 40}}}}
		trips = append(trips, trip{"fuel " + f.Country, res, Request{CargoKg: 1000, Truck: truck40, FuelCountry: f.Country}, day(f.ValidFrom), nil, nil, ""})
		trips = append(trips, trip{"fuel along " + f.Country, res, Request{CargoKg: 1000, Truck: truck40}, day(f.ValidFrom), nil, nil, ""})
	}
	var out []string
	bad, known := 0, 0
	every := 1
	fmt.Sscan(os.Getenv("DIFF_EVERY"), &every)
	start := time.Now()
	var lt, nt time.Duration
	for i, tp := range trips {
		if i%every != 0 || !strings.Contains(tp.name, os.Getenv("DIFF_ONLY")) {
			continue
		}
		var lreq legacy.Request
		b, _ := json.Marshal(tp.req)
		json.Unmarshal(b, &lreq)
		if tp.req.FX == nil {
			fxs := map[string]float64{}
			for _, c := range []string{"DKK", "SEK", "NOK", "CHF", "GBP", "HUF", "CZK", "PLN", "RON", "BGN", "HRK", "TRY", "RSD", "MKD", "BAM", "ALL", "MDL", "ISK"} {
				fxs[c] = 10
			}
			tp.req.FX, lreq.FX = fxs, fxs
		}
		t0 := time.Now()
		lr, lerr := legacy.PriceWithRoute(tp.res, tables, nil, lreq, tp.date, tp.roadKm, tp.spans, tp.origin)
		t1 := time.Now()
		nr, nerr := priceWithRoute(tp.res, set, nil, tp.req, tp.date, tp.roadKm, tp.spans, tp.origin)
		lt, nt = lt+t1.Sub(t0), nt+time.Since(t1)
		if (lerr == nil) != (nerr == nil) {
			bad++
			out = append(out, fmt.Sprintf("%s %s: errors %v / %v", tp.name, tp.date.Format(time.DateOnly), lerr, nerr))
			continue
		}
		if lerr != nil {
			continue
		}
		sums := func(ls []Line) map[string]float64 {
			m := map[string]float64{}
			for _, l := range ls {
				m[l.Charge+" "+l.Country+" "+l.Component] += l.AmountEUR
			}
			return m
		}
		var ll []Line
		b, _ = json.Marshal(lr.Lines)
		json.Unmarshal(b, &ll)
		ls, ns := sums(ll), sums(nr.Lines)
		var diffs []string
		keys := map[string]bool{}
		for k := range ls {
			keys[k] = true
		}
		for k := range ns {
			keys[k] = true
		}
		for _, k := range sortedKeys(keys) {
			if math.Abs(ls[k]-ns[k]) > 0.011 {
				diffs = append(diffs, fmt.Sprintf("%s: %.2f / %.2f", k, ls[k], ns[k]))
			}
		}
		if math.Abs(lr.TotalEUR-nr.TotalEUR) > 0.011 && len(diffs) == 0 {
			diffs = append(diffs, fmt.Sprintf("total %.2f / %.2f", lr.TotalEUR, nr.TotalEUR))
		}
		if fmt.Sprint(lr.NoRates) != fmt.Sprint(nr.NoRates) {
			diffs = append(diffs, fmt.Sprintf("no_rates %v / %v", lr.NoRates, nr.NoRates))
		}
		if len(diffs) > 0 && os.Getenv("DIFF_LINES") != "" {
			for _, l := range ll {
				t.Logf("legacy %+v", l)
			}
			for _, l := range nr.Lines {
				t.Logf("orct   %+v", l)
			}
		}
		if len(diffs) > 0 && explained(tp.name, tp.req.Time) != "" {
			known++
			continue
		}
		if len(diffs) > 0 {
			bad++
			out = append(out, fmt.Sprintf("%s %s %s: %s\n   legacy notes: %v\n   orct notes:   %v", tp.name, tp.date.Format(time.DateOnly), tp.req.Time,
				strings.Join(diffs, "; "), lr.Notes, nr.Notes))
		}
	}
	sort.Strings(out)
	if f := os.Getenv("DIFF_OUT"); f != "" {
		os.WriteFile(f, []byte(strings.Join(out, "\n")+"\n"), 0o644)
	}
	t.Logf("%d trips (every %d), %d differ, %d explained; legacy %v, orct %v, all %v", len(trips), every, bad, known, lt, nt, time.Since(start))
	if bad > 0 {
		t.Fail()
	}
}

// explained says why the engines may differ on a trip, where the
// difference is a fix in this engine.
func explained(name, tm string) string {
	switch {
	case strings.Contains(name, "system AP-8 Donostia – Behobia"):
		// The old engine took a station no price names (a stretch with no
		// toll, Irun Ventas – Irun M/O) as the exit, found no price and
		// charged nothing; the barrier Behobia – Irun Ventas is paid.
		return "untolled station as exit"
	case strings.HasPrefix(name, "zone London") && tm == "23:30":
		// A trip across midnight in the LEZ is in it on two charging days
		// (midnight to midnight); the old engine charged one.
		return "two charging days"
	}
	return ""
}

// opsOf splits km among a table's operators (for roads.Km.MotorwayOp).
func opsOf(tb rates.Table, km float64) map[string]float64 {
	var ops []string
	for _, r := range tb.Rows {
		if r.Operator != "" {
			ops = append(ops, r.Operator)
		}
	}
	if len(ops) == 0 {
		return nil
	}
	sort.Strings(ops)
	out := map[string]float64{}
	for i, o := range ops {
		if i%3 == 0 {
			out[o] += km / float64(len(ops)) * 3
		}
	}
	return out
}

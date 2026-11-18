package cost

import (
	"fmt"
	"math"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/orct"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// exemption is the note of an exemption rule that frees the truck from
// the dataset's per-km charges on the date, if one does.
func (p *pricer) exemption(ds *tariffs.Dataset) (string, bool) {
	day := p.date.Format(time.DateOnly)
	for _, r := range ds.Doc.Rules {
		if r.Kind != "exemption" {
			continue
		}
		crit, _ := r.Params["criteria"].(map[string]any)
		if ok, err := orct.Meets(crit, p.vehicle); err != nil || !ok {
			continue
		}
		from, _ := r.Params["from"].(string)
		until, _ := r.Params["until"].(string)
		if (from == "" || from <= day) && (until == "" || day <= until) {
			note, _ := r.Params["note"].(string)
			return note, true
		}
	}
	return "", false
}

// tolledRoads is the dataset's description of its tolled network.
func tolledRoads(ds *tariffs.Dataset) string {
	for _, o := range ds.Objects() {
		if o.Type == "network" && len(o.Parents) == 0 && o.Network != nil && o.Network.Description != "" {
			return o.Network.Description
		}
	}
	return ""
}

// priceArea prices an area's (a country's or region's) toll dataset: its
// per-km or per-day charges on the area's km, its sections, closed
// systems and toll points on the route.
func (p *pricer) priceArea(ds *tariffs.Dataset, a area, route *track) error {
	req, cc, km := p.req, a.code, a.km
	share, shareGiven := 1.0, false
	for _, k := range []string{a.code, a.country} {
		if v, ok := req.TolledShare[k]; ok {
			share, shareGiven = v, true
			break
		}
	}
	tolledKm := km * share
	nw := networkOf(ds)
	rk, byRoute := req.roadKm[a.country]
	byRoute = byRoute && a.region == "" && rk.Total() > 0 && len(nw.roadTypes) > 0
	if byRoute && !shareGiven {
		tolledKm = km * (rk.Motorway + rk.National) / rk.Total()
	}
	p.useTable(ds)
	if byRoute {
		if p.out.Provenance.RoadClasses == nil {
			p.out.Provenance.RoadClasses = map[string]string{}
		}
		d := req.roadOSM[a.country]
		if d == "" {
			d = "date not recorded"
		}
		p.out.Provenance.RoadClasses[a.country] = "OpenStreetMap " + d
		if rk.Uncertain >= 0.5 {
			p.note("%s: %.1f km counted as untolled local roads pass within %d m of a tolled road in OpenStreetMap, so may be on it; give tolled_share.%s if they are.",
				cc, rk.Uncertain, roads.NearM, cc)
		}
	}
	liable, err := ds.Liable(p.vehicle)
	if err != nil || !liable {
		p.note("%s: no toll for this truck (%s).", cc, ds.Doc.Liable.Description)
		return nil
	}
	if note, ok := p.exemption(ds); ok {
		p.note("%s: %s", cc, note)
		p.addSources(ds)
		return nil
	}
	p.addSources(ds)
	b := &batch{ds: ds}
	secs, secKm := p.sectionsOn(ds, route)
	if nw.perDay != nil {
		if tolledKm >= 0.5 {
			p.perDay(b, ds, nw, a, tolledKm)
		}
	} else if nw.hasRows {
		p.perKm(b, ds, nw, a, km, tolledKm, byRoute, shareGiven, rk, secKm, route)
	}
	for _, s := range secs {
		at, timed := p.at(ds, s.from, a.country)
		if !timed && req.Night {
			// The trip passes night-tariff sections between 22:00 and 05:00.
			at = time.Date(at.Year(), at.Month(), at.Day(), 23, 0, 0, 0, at.Location())
		}
		// Its km merge with the area's per-km lines (key), except where the
		// section's own toll replaces the per-km infrastructure charge.
		m := &lineMeta{charge: RoadToll, country: a.country, region: a.region, section: s.obj.Name, km: s.km, hasKm: true, key: "km//"}
		b.km(s.obj.ID, at, s.km, nil, m)
	}
	zkm := req.EnvZoneKm[a.code]
	if a.region != "" && zkm == 0 {
		zkm = req.EnvZoneKm[a.country]
	}
	if zkm > 0 {
		if nw.env == "" {
			p.note("%s: env_zone_km given, but %s has no environmental zone surcharge.", cc, ds.Name)
		} else {
			b.km(nw.env, p.noon(ds), zkm, nil, &lineMeta{charge: RoadToll, country: a.country, region: a.region, km: zkm, hasKm: true})
		}
	}
	systems, points := p.matchSystems(b, ds, a.country, a.region, route), p.matchPoints(b, ds, a.country, route)
	st, err := p.price(b, "", nil)
	if err != nil {
		return err
	}
	p.afterPoints(ds, a.country, st, points)
	p.afterSystems(ds, a.country, st, systems)
	if points.listed && !points.any && km >= 1 {
		p.note("%s: the route passes none of the toll stations.", cc)
	}
	if systems.listed && !nw.hasRows && !systems.any && km >= 1 {
		p.note("%s: the route uses none of the tolled motorways.", cc)
	}
	if hasSections(ds) && !nw.hasRows && len(secs) == 0 && km >= 1 {
		p.note("%s: the route passes none of the tolled sections.", cc)
	}
	if !shareGiven && !byRoute && nw.hasRows && nw.perDay == nil {
		p.note("%s: all %.1f km are counted as on tolled roads; give tolled_share.%s if part of the trip isn't. Tolled roads: %s",
			cc, km, cc, tolledRoads(ds))
	}
	p.unpriced(ds, cc, st)
	return nil
}

// unpriced notes what the statement couldn't price.
func (p *pricer) unpriced(ds *tariffs.Dataset, cc string, st *orct.Statement) {
	for _, i := range st.Issues {
		switch i.Code {
		case "partial_coverage", "outside_validity":
			continue
		}
		hint := ""
		if i.Code == "missing_parameter" {
			for param, field := range map[string]string{"vehicle parameter mass_kg ": "truck.motor_mass_kg", "vehicle parameter trailer_mass_kg ": "truck.trailer_mass_kg"} {
				if strings.Contains(i.Message, param) {
					hint = fmt.Sprintf(" Give %s (and truck.motor_axles): the charge goes by each vehicle's own permissible mass.", field)
				}
			}
			if strings.Contains(i.Message, "vehicle parameter load_capacity_kg ") {
				hint = " Give truck.capacity_kg (the load capacity: the semi-trailer's for a tractor with semi-trailer): the fare goes by the tonne of it."
			}
		}
		p.note("%s: %s not fully priced (%s: %s).%s", cc, ds.Name, i.Code, i.Message, hint)
	}
}

// perKm adds the area's km by road type, operator and area as events on
// the network.
func (p *pricer) perKm(b *batch, ds *tariffs.Dataset, nw *network, a area, km, tolledKm float64, byRoute, shareGiven bool, rk roads.Km, secKm float64, route *track) {
	req, cc := p.req, a.code
	type part struct {
		road string
		km   float64
	}
	parts := []part{{"", tolledKm}}
	if len(nw.roadTypes) > 0 {
		mw, given := 0.0, false
		for _, k := range []string{a.code, a.country} {
			if v, ok := req.MotorwayShare[k]; ok {
				mw, given = v, true
				break
			}
		}
		switch {
		case given && byRoute && !shareGiven:
			p.note("%s: %.0f%% of the %.1f km are on local roads by OpenStreetMap along the route, which aren't tolled.", cc, 100*rk.Local/rk.Total(), km)
		case given:
		case byRoute:
			if t := rk.Motorway + rk.National; t > 0 {
				mw = rk.Motorway / t
			}
			local := map[bool]string{true: "", false: ", which aren't tolled"}[shareGiven]
			if l := req.roadLeftOut[a.country]; len(l) > 0 {
				// The motorway stretches the toll leaves to their operators count here.
				local = fmt.Sprintf(" (including the motorways this toll leaves to their operators: %s)%s", strings.Join(l, ", "), map[bool]string{true: "", false: ", which it doesn't charge"}[shareGiven])
			}
			p.note("%s: by OpenStreetMap along the route, %.0f%% of the %.1f km are on motorways, %.0f%% on other national roads and %.0f%% on local roads%s. Give motorway_share.%s or tolled_share.%s to override.",
				cc, 100*rk.Motorway/rk.Total(), km, 100*rk.National/rk.Total(), 100*rk.Local/rk.Total(), local, cc, cc)
		default:
			ds.Ext("motorway_share", &mw)
			p.note("%s: rates differ by road type; %.0f%% of the %.1f km are priced at the motorway rate, the rest at the other-road rate. Give motorway_share.%s for the share on motorways.",
				cc, mw*100, tolledKm, cc)
		}
		parts = []part{{rates.Motorway, tolledKm * mw}, {rates.OtherRoad, tolledKm * (1 - mw)}}
	}
	type opPart struct {
		road, op string
		km       float64
	}
	var ops []opPart
	for _, pt := range parts {
		if pt.road == rates.Motorway && byRoute && len(nw.ops) > 0 && rk.Motorway > 0 && pt.km > 0 {
			keys := make([]string, 0, len(rk.MotorwayOp))
			on := 0.0
			for k, v := range rk.MotorwayOp {
				keys = append(keys, k)
				on += v
			}
			sort.Strings(keys)
			for _, k := range keys {
				ops = append(ops, opPart{pt.road, k, pt.km * rk.MotorwayOp[k] / rk.Motorway})
			}
			if rest := rk.Motorway - on; rest > 1e-9 {
				ops = append(ops, opPart{pt.road, "", pt.km * rest / rk.Motorway})
			}
			continue
		}
		ops = append(ops, opPart{pt.road, "", pt.km})
	}
	// Surcharged stretches the route drives: their km, as overlays.
	overlays := map[string]float64{}
	for _, o := range ds.Objects() {
		if o.Type != "network" || o.Location == nil || o.Location.Geometry == nil || o.Location.Geometry.Type != "LineString" {
			continue
		}
		pts := pointsOf(o)
		var skm float64
		for i := 0; i+1 < len(pts); i++ {
			if k, ok := along(route, pts[i], pts[i+1]); ok {
				skm += k
			}
		}
		if skm > 0 {
			overlays[o.ID] = skm
		}
	}
	at := p.noon(ds)
	for _, pt := range ops {
		if pt.km <= 0 && pt.road != "" {
			continue
		}
		k := math.Max(0, pt.km-secKm)
		section := ""
		if pt.op != "" {
			section = opName(pt.op)
		}
		// Per area where the rates differ by it: the suburban share of the
		// km on a cell of its own.
		splits := []struct {
			area string
			km   float64
		}{{"", k}}
		if len(nw.areas) > 0 {
			sh := suburbanShareORCT(ds, rk, byRoute, pt.road)
			splits = splits[:0]
			splits = append(splits, struct {
				area string
				km   float64
			}{rates.Suburban, k * sh}, struct {
				area string
				km   float64
			}{rates.Interurban, k * (1 - sh)})
		}
		key := fmt.Sprintf("km/%s/%s", pt.road, pt.op)
		for _, sp := range splits {
			obj := nw.object(pt.road, sp.area, pt.op)
			if obj == "" {
				continue
			}
			ov := map[string]float64{}
			for id, v := range overlays {
				ov[id] = math.Min(v, sp.km)
			}
			if sp.km <= 0 && len(splits) > 1 {
				continue
			}
			m := &lineMeta{charge: RoadToll, country: a.country, region: a.region, road: pt.road, section: section, km: sp.km, hasKm: true, key: key}
			// The cells' km merge into one line where a row prices both
			// alike (the same row): only where the rates differ by area
			// is it a line of its own.
			m.area = sp.area
			b.km(obj, at, sp.km, ov, m)
		}
	}
}

// suburbanShareORCT is the share of km on suburban roads of a road type:
// from the route's toll sections where it matched them, the dataset's
// network share for the rest.
func suburbanShareORCT(ds *tariffs.Dataset, rk roads.Km, byRoute bool, road string) float64 {
	shares := map[string]float64{}
	ds.Ext("suburban_share", &shares)
	def, ok := shares[road]
	if !ok {
		def = shares[""]
	}
	if !byRoute {
		return def
	}
	km, sub, known := rk.Motorway, rk.MotorwaySub, rk.MotorwayKnown
	if road == rates.OtherRoad {
		km, sub, known = rk.National, rk.NationalSub, rk.NationalKnown
	}
	if km <= 0 {
		return def
	}
	return math.Min(1, (sub+math.Max(0, km-known)*def)/km)
}

// perDay adds a period event for each day (or 24 hours) the trip spends
// in the area, from its passage times there.
func (p *pricer) perDay(b *batch, ds *tariffs.Dataset, nw *network, a area, tolledKm float64) {
	req, cc := p.req, a.code
	days, note := p.tripDaysORCT(ds, nw.perDay, a.country)
	m := &lineMeta{charge: RoadToll, country: a.country, region: a.region, km: tolledKm, hasKm: true, key: "day"}
	obj := nw.root
	for _, d := range days {
		b.event(obj, d, m)
	}
	p.note("%s", cc+": "+note)
	if hasMotorAxles(ds) && req.Truck.MotorAxles == 0 {
		p.note("%s: the charge counts the motor vehicle's own axles; priced with the truck's %d axles. Give truck.motor_axles (e.g. 2 for a two-axle tractor).", cc, req.Truck.Axles)
	}
}

// hasMotorAxles says whether the dataset's classes count the motor
// vehicle's own axles.
func hasMotorAxles(ds *tariffs.Dataset) bool {
	for _, s := range ds.Doc.Sets {
		for _, c := range s.Classes {
			if _, ok := c.Criteria["axles"]; ok {
				return true
			}
		}
	}
	return false
}

// tripDaysORCT are the times a time-based charge is used at, one in each
// day (or 24 hours) the trip spends in the country, and a note saying how
// they were counted.
func (p *pricer) tripDaysORCT(ds *tariffs.Dataset, ch *orct.Charge, country string) ([]time.Time, string) {
	req := p.req
	sp := req.spans[country]
	day := ""
	switch ch.DayBasis {
	case "calendar":
		day = "calendar"
	case "rolling":
		day = "24h"
	}
	switch {
	case day == "":
		return []time.Time{p.noon(ds)}, "a time-based charge, priced at one day's rate; a trip over more days pays for each day or a longer period."
	case req.Time == "" || len(sp) == 0:
		return []time.Time{p.noon(ds)}, "a time-based charge, priced at one day's rate; give time (the departure) to count the days the trip spends there."
	}
	var out []time.Time
	if day == "calendar" {
		seen := map[string]bool{}
		for _, s := range sp {
			a, _ := passage(req, p.date, s[0], country)
			b, _ := passage(req, p.date, s[1], country)
			last := time.Date(b.Year(), b.Month(), b.Day(), 0, 0, 0, 0, time.UTC)
			for d := time.Date(a.Year(), a.Month(), a.Day(), 0, 0, 0, 0, time.UTC); !d.After(last); d = d.AddDate(0, 0, 1) {
				if k := d.Format(time.DateOnly); !seen[k] {
					seen[k] = true
					at := time.Date(d.Year(), d.Month(), d.Day(), 12, 0, 0, 0, a.Location())
					if d.Equal(time.Date(a.Year(), a.Month(), a.Day(), 0, 0, 0, 0, time.UTC)) {
						at = a
					}
					out = append(out, at)
				}
			}
		}
	} else {
		var until time.Time
		for _, s := range sp {
			a, _ := passage(req, p.date, s[0], country)
			b, _ := passage(req, p.date, s[1], country)
			if len(out) == 0 || !a.Before(until) {
				out, until = append(out, a), a.Add(24*time.Hour)
			}
			for b.After(until) {
				out = append(out, until)
				until = until.Add(24 * time.Hour)
			}
		}
	}
	n := len(out)
	unit := map[string]string{"calendar": "calendar day", "24h": "24-hour period"}[day]
	if n != 1 {
		unit += "s"
	}
	rest := ""
	if !req.DriverRest {
		rest = " without driver rests (give driver_rest for them)"
	}
	return out, fmt.Sprintf("a time-based charge for each %s of use: the trip is there on %d %s by its passage times%s; a longer period may cost less.",
		map[string]string{"calendar": "calendar day", "24h": "24 hours"}[day], n, unit, rest)
}

// ---------------------------------------------------------------- sections

type sectionPass struct {
	obj      *orct.Object
	km, from float64
}

func hasSections(ds *tariffs.Dataset) bool {
	for _, o := range ds.Objects() {
		if o.Type == "section" {
			return true
		}
	}
	return false
}

// sectionsOn lists the dataset's sections the route drives from end to
// end, and their km along the route.
func (p *pricer) sectionsOn(ds *tariffs.Dataset, route *track) ([]sectionPass, float64) {
	if len(route.pts) < 2 {
		return nil, 0
	}
	var out []sectionPass
	var total float64
	for _, o := range ds.Objects() {
		if o.Type != "section" || o.From == nil || o.To == nil {
			continue
		}
		a, b := endOf(o.From), endOf(o.To)
		if km, ok := along(route, a, b); ok {
			pa, _, _ := route.project(a)
			pb, _, _ := route.project(b)
			out = append(out, sectionPass{o, km, math.Min(pa, pb)})
			total += km
		}
	}
	return out, total
}

// ---------------------------------------------------------------- closed systems

// system is a closed system (an od charge) and its stations.
type system struct {
	ch       *orct.Charge
	stations []*orct.Object
	matchKm  float64
	chain    bool
}

func systemsOf(ds *tariffs.Dataset) []*system {
	var chains []string
	ds.Ext("chain_systems", &chains)
	var out []*system
	for _, ch := range ds.Charges() {
		if ch.Type != "od" {
			continue
		}
		s := &system{ch: ch, matchKm: StationMatchKm, chain: slices.Contains(chains, ch.ID)}
		// A station no row prices from or to is no entry or exit of the
		// charge (a stretch with no toll): passing it uses nothing.
		priced := map[string]bool{}
		for n := 0; ; n++ {
			v := ch.RowValues(n)
			if v == nil {
				break
			}
			for _, c := range []string{"entry", "exit"} {
				if id, _ := v[c].(string); id != "" {
					priced[id] = true
				}
			}
		}
		prefix := "st" + strings.TrimPrefix(ch.ID, "system") + ":"
		for _, o := range ds.Objects() {
			if o.Type == "station" && strings.HasPrefix(o.ID, prefix) && priced[o.ID] {
				s.stations = append(s.stations, o)
				if o.Location != nil && o.Location.MatchM != nil {
					s.matchKm = *o.Location.MatchM / 1000
				}
			}
		}
		out = append(out, s)
	}
	return out
}

func (s *system) pass(st *orct.Object, route *track) (float64, float64) {
	best, bestPos := math.Inf(1), 0.0
	for _, pt := range pointsOf(st) {
		pos, d, h := route.project(pt)
		if pt.Heading != nil && math.Abs(math.Mod(h-*pt.Heading+540, 360)-180) > 60 {
			continue
		}
		if d < best {
			best, bestPos = d, pos
		}
	}
	return best, bestPos
}

// sysUse is a ticket: the stations a route enters and leaves a system at.
type sysUse struct {
	entry, exit *orct.Object
	km, from    float64
}

func (s *system) uses(ds *tariffs.Dataset, route *track, p *pricer) []sysUse {
	if len(route.pts) < 2 {
		return nil
	}
	if s.chain {
		return s.chainUses(ds, route, p)
	}
	first, last := math.Inf(1), math.Inf(-1)
	var u sysUse
	for _, st := range s.stations {
		best, pos := s.pass(st, route)
		if best > s.matchKm {
			continue
		}
		if pos < first {
			first, u.entry = pos, st
		}
		if pos > last {
			last, u.exit = pos, st
		}
	}
	if u.entry == nil {
		return nil
	}
	u.km, u.from = last-first, first
	if u.entry == u.exit && !ds.HasPair(s.ch.ID, u.entry.ID, u.entry.ID) {
		return nil
	}
	return []sysUse{u}
}

func (s *system) chainUses(ds *tariffs.Dataset, route *track, p *pricer) []sysUse {
	type pass struct {
		st       *orct.Object
		pos, off float64
	}
	var passes []pass
	for _, st := range s.stations {
		best, pos := s.pass(st, route)
		if best <= s.matchKm {
			passes = append(passes, pass{st, pos, best})
		}
	}
	sort.Slice(passes, func(i, j int) bool { return passes[i].pos < passes[j].pos })
	n := len(passes)
	at := p.noon(ds)
	rater := ds.Rater(p.vehicle, p.payment)
	known := map[[2]int]bool{}
	priced := func(i, j int) bool {
		if passes[j].st == passes[i].st {
			return false
		}
		if v, ok := known[[2]int{i, j}]; ok {
			return v
		}
		_, ok, err := rater.Rate(s.ch.ID, "", passes[i].st.ID, passes[j].st.ID, at)
		known[[2]int{i, j}] = ok && err == nil
		return ok && err == nil
	}
	cont := func(i, j int) int {
		k := j
		for k > i+1 && passes[j].pos-passes[k-1].pos <= sameKm {
			k--
		}
		return k
	}
	type best struct {
		cover   float64
		tickets int
		off     float64
		exit    int
	}
	better := func(a, b best) bool {
		if math.Abs(a.cover-b.cover) > sameKm {
			return a.cover > b.cover
		}
		if a.tickets != b.tickets {
			return a.tickets < b.tickets
		}
		if math.Abs(a.off-b.off) > 1e-6 {
			return a.off < b.off
		}
		return a.cover > b.cover+1e-9
	}
	type key struct{ k, skip int }
	memo := map[key]best{}
	var from func(k, skip int) best
	from = func(k, skip int) best {
		if k >= n {
			return best{exit: -1}
		}
		if skip < k {
			skip = -1
		}
		if b, ok := memo[key{k, skip}]; ok {
			return b
		}
		b := from(k+1, skip)
		b.exit = -1
		if k != skip {
			for j := k + 1; j < n; j++ {
				if !priced(k, j) {
					continue
				}
				r := from(cont(k, j), j)
				if c := (best{passes[j].pos - passes[k].pos + r.cover, r.tickets + 1, passes[k].off + passes[j].off + r.off, j}); better(c, b) {
					b = c
				}
			}
		}
		memo[key{k, skip}] = b
		return b
	}
	for i := n - 1; i >= 0; i-- {
		from(i, -1)
	}
	var out []sysUse
	for i, skip := 0, -1; i < n; {
		b := from(i, skip)
		if b.exit < 0 {
			i++
			continue
		}
		j := b.exit
		out = append(out, sysUse{entry: passes[i].st, exit: passes[j].st, km: passes[j].pos - passes[i].pos, from: passes[i].pos})
		i, skip = cont(i, j), j
	}
	var spans [][2]float64
	for _, u := range out {
		spans = append(spans, [2]float64{u.from, u.from + u.km})
	}
	for _, ps := range passes {
		if _, ok, err := rater.Rate(s.ch.ID, "", ps.st.ID, ps.st.ID, at); !ok || err != nil {
			continue
		}
		inside := false
		for _, sp := range spans {
			inside = inside || (ps.pos > sp[0]+sameKm && ps.pos < sp[1]-sameKm)
		}
		if !inside {
			out = append(out, sysUse{entry: ps.st, exit: ps.st, from: ps.pos})
		}
	}
	sort.SliceStable(out, func(a, b int) bool { return out[a].from < out[b].from })
	return out
}

// systemsMatched are the tickets a route takes, for notes after pricing.
type systemsMatched struct {
	listed, any  bool
	uses         []sysMatch
	untimedNight map[string]bool
}

type sysMatch struct {
	sys   *system
	use   sysUse
	at    time.Time
	timed bool
	meta  *lineMeta
}

// matchSystems adds an entry and an exit event for each ticket.
func (p *pricer) matchSystems(b *batch, ds *tariffs.Dataset, country, region string, route *track) *systemsMatched {
	sm := &systemsMatched{untimedNight: map[string]bool{}}
	for _, s := range systemsOf(ds) {
		sm.listed = true
		for _, u := range s.uses(ds, route, p) {
			sm.any = true
			at, timed := p.at(ds, u.from, country)
			end, _ := p.at(ds, u.from+u.km, country)
			if !timed {
				end = at
			}
			name := s.ch.Name + ": " + u.entry.Name
			if u.exit != u.entry {
				name += " – " + u.exit.Name
			}
			m := &lineMeta{charge: RoadToll, country: country, region: region, section: name, km: u.km, hasKm: true}
			e := b.event(u.entry.ID, at, m)
			e.Role = "entry"
			x := b.event(u.exit.ID, end, m)
			x.Role = "exit"
			sm.uses = append(sm.uses, sysMatch{s, u, at, timed, m})
		}
	}
	return sm
}

// timeClasses are the time classes of a charge's rows.
func timeClasses(ch *orct.Charge) []string {
	var out []string
	for n := 0; ; n++ {
		v := ch.RowValues(n)
		if v == nil {
			break
		}
		if tc, _ := v["time_class"].(string); tc != "" && !slices.Contains(out, tc) {
			out = append(out, tc)
		}
	}
	return out
}

// freeClass is a charge's time class of rows that charge nothing (free
// hours), if any.
func freeClass(ch *orct.Charge) string {
	for n := 0; ; n++ {
		v := ch.RowValues(n)
		if v == nil {
			return ""
		}
		if tc, _ := v["time_class"].(string); tc != "" && v["amount"] == "0" {
			if o, _ := v["object"].(string); o == "" {
				if e, _ := v["entry"].(string); e == "" {
					return tc
				}
			}
		}
	}
}

func hoursOf(tc *orct.TimeClass) (string, string) {
	if tc == nil || len(tc.Times) == 0 {
		return "", ""
	}
	end := tc.Times[0][1]
	if t, err := time.Parse("15:04", end); err == nil {
		end = t.Add(-time.Minute).Format("15:04")
	} else if end == "24:00" {
		end = "23:59"
	}
	return tc.Times[0][0], end
}

// afterSystems adds the notes on the tickets priced.
func (p *pricer) afterSystems(ds *tariffs.Dataset, country string, st *orct.Statement, sm *systemsMatched) {
	if len(sm.uses) == 0 {
		return
	}
	priced := map[*lineMeta]*orct.Line{}
	for _, l := range st.Lines {
		if l.Event != nil {
			if m, ok := l.Event.Ref.(*lineMeta); ok && ds.Charge(l.Charge).Type == "od" {
				priced[m] = l
			}
		}
	}
	for _, u := range sm.uses {
		ch := u.sys.ch
		free := freeClass(ch)
		if free != "" && u.timed {
			if in, _ := ds.InTimeClass(free, u.at); in {
				a, z := hoursOf(ds.TimeClass(free))
				p.note("%s: %s is free from %s to %s (entered about %s).", country, ch.Name, a, z, u.at.Format("15:04"))
				continue
			}
		}
		for _, tc := range timeClasses(ch) {
			if tc == free || !strings.Contains(tc, "night") {
				continue
			}
			a, z := hoursOf(ds.TimeClass(tc))
			if !u.timed {
				if !sm.untimedNight[ch.ID] {
					sm.untimedNight[ch.ID] = true
					p.note("%s: %s is cheaper from %s to %s; priced at the day tariff. Give a departure time.", country, ch.Name, a, z)
				}
			} else if in, _ := ds.InTimeClass(tc, u.at); in {
				p.note("%s: %s at the night tariff (entered about %s).", country, ch.Name, u.at.Format("15:04"))
			}
		}
		l := priced[u.meta]
		if l == nil {
			group := p.groupOf(ds, ch)
			p.note("%s: %s has no price from %s to %s for group %s.", country, ch.Name, u.use.entry.Name, u.use.exit.Name, group)
			continue
		}
		var names []string
		for _, n := range l.Notes {
			if strings.HasPrefix(n, "discount ") {
				names = append(names, strings.TrimPrefix(n, "discount "))
			}
		}
		if len(names) > 0 {
			p.note("%s: %s with %s off.", country, ch.Name, strings.Join(names, " and "))
		}
		if p.req.Truck.LengthM == 0 && lengthClasses(ds, ch) {
			p.note("%s: %s is priced by length; %g m assumed (group %s). Give the truck's length_m.", country, ch.Name, rates.DefaultLengthM, p.groupOf(ds, ch))
		}
	}
}

// groupOf is the label of the truck's class in an od charge's class set.
func (p *pricer) groupOf(ds *tariffs.Dataset, ch *orct.Charge) string {
	cls, _ := ds.Classify(p.vehicle)
	for n := 0; ; n++ {
		v := ch.RowValues(n)
		if v == nil {
			return ""
		}
		if c, _ := v["vehicle_class"].(string); c != "" {
			if id := cls[ds.SetOf(c)]; id != "" {
				if k := ds.Class(id); k != nil && k.Label != "" {
					return k.Label
				}
				return id
			}
			return ""
		}
	}
}

// lengthClasses says whether an od charge's classes differ by length.
func lengthClasses(ds *tariffs.Dataset, ch *orct.Charge) bool {
	for n := 0; ; n++ {
		v := ch.RowValues(n)
		if v == nil {
			return false
		}
		if c, _ := v["vehicle_class"].(string); c != "" {
			set := ds.SetOf(c)
			for _, s := range ds.Doc.Sets {
				if s.ID != set {
					continue
				}
				for _, k := range s.Classes {
					if _, ok := k.Criteria["train_length_m"]; ok {
						return true
					}
				}
			}
			return false
		}
	}
}

// ---------------------------------------------------------------- toll points

type pointPass struct {
	obj   *orct.Object
	ch    *orct.Charge
	pos   float64
	at    time.Time
	timed bool
	meta  *lineMeta
}

type pointsMatched struct {
	listed, any bool
	passes      []pointPass
	noTime      int
}

// pointCharges maps each point object to the charge in force on the date
// that prices it.
func (p *pricer) pointCharges(ds *tariffs.Dataset) map[string]*orct.Charge {
	day := p.date.Format(time.DateOnly)
	out := map[string]*orct.Charge{}
	for _, ch := range ds.Charges() {
		if ch.Type != "point" {
			continue
		}
		if (ch.ValidFrom != "" && day < ch.ValidFrom) || (ch.ValidTo != "" && day > ch.ValidTo) {
			continue
		}
		for o := range ch.RowObjects() {
			out[o] = ch
		}
	}
	return out
}

// matchPoints adds an event for each toll point the route passes in a
// direction that pays.
func (p *pricer) matchPoints(b *batch, ds *tariffs.Dataset, country string, route *track) *pointsMatched {
	pm := &pointsMatched{}
	charges := p.pointCharges(ds)
	var passes []pointPass
	for _, o := range ds.Objects() {
		if o.Type != "point" {
			continue
		}
		pm.listed = true
		ch := charges[o.ID]
		if ch == nil {
			continue
		}
		pts := pointsOf(o)
		if len(pts) == 0 {
			continue
		}
		match := DefaultPointMatchKm
		if o.Location.MatchM != nil {
			match = *o.Location.MatchM / 1000
		}
		pos, d, h := route.project(pts[0])
		if d > match {
			continue
		}
		if pts[0].Heading != nil && math.Abs(math.Mod(h-*pts[0].Heading+540, 360)-180) > 90 {
			continue
		}
		passes = append(passes, pointPass{obj: o, ch: ch, pos: pos})
	}
	sort.SliceStable(passes, func(i, j int) bool { return passes[i].pos < passes[j].pos })
	last := map[string]float64{}
	for _, ps := range passes {
		if at, ok := last[ps.obj.Name]; ok && ps.pos-at < 1 {
			continue
		}
		last[ps.obj.Name] = ps.pos
		ps.at, ps.timed = p.at(ds, ps.pos, country)
		if ps.ch.Component == "congestion" && !ps.timed {
			pm.noTime++
			continue
		}
		name := ps.obj.Name
		if strings.HasPrefix(ps.obj.Note, "Toll project: ") {
			name = strings.TrimPrefix(ps.obj.Note, "Toll project: ") + ": " + name
		}
		if ps.ch.Component == "congestion" {
			name = ps.obj.Name + " (" + ps.at.Format("15:04") + ")"
		}
		ps.meta = &lineMeta{charge: RoadToll, country: country, section: name}
		b.event(ps.obj.ID, ps.at, ps.meta)
		pm.passes = append(pm.passes, ps)
		pm.any = true
	}
	return pm
}

// afterPoints adds the notes on the toll points priced.
func (p *pricer) afterPoints(ds *tariffs.Dataset, country string, st *orct.Statement, pm *pointsMatched) {
	if !pm.listed {
		return
	}
	paid := map[*lineMeta]*orct.Line{}
	for _, l := range st.Lines {
		if l.Event == nil {
			continue
		}
		if m, ok := l.Event.Ref.(*lineMeta); ok && ds.Charge(l.Charge).Type == "point" {
			paid[m] = l
		}
	}
	free, peakUntimed, nightUntimed := 0, 0, map[string][2]string{}
	untimedFree := false
	var cong struct{ offHours, multi int }
	congName := ""
	for _, ps := range pm.passes {
		l := paid[ps.meta]
		if ps.ch.Component == "congestion" {
			congName = ps.ch.ID
			switch {
			case l == nil:
				cong.offHours++
			case slices.ContainsFunc(l.Notes, func(n string) bool { return strings.HasPrefix(n, "passage group") }):
				cong.multi++
			}
			continue
		}
		if l == nil {
			for _, r := range ds.Doc.Rules {
				if r.Kind == "included_in" && slices.Contains(strs(r.Params["objects"]), ps.obj.ID) {
					sys := ds.Charge(fmt.Sprint(r.Params["charge"]))
					if sys != nil {
						p.note("%s: %s is included in the %s ticket.", country, ps.obj.Name, sys.Name)
					}
				}
			}
			continue
		}
		if slices.ContainsFunc(l.Notes, func(n string) bool { return strings.HasPrefix(n, "passage group") }) {
			free++
			untimedFree = untimedFree || !ps.timed
		}
		if !ps.timed {
			for _, tc := range timeClasses(ps.ch) {
				t := ds.TimeClass(tc)
				if t == nil || !rowsOn(ps.ch, ps.obj.ID, tc) {
					continue
				}
				switch {
				case strings.HasPrefix(tc, "night"):
					a, z := hoursOf(t)
					nightUntimed[ps.obj.Name] = [2]string{a, z}
				case strings.HasPrefix(tc, "rush"):
					peakUntimed++
				}
			}
		}
	}
	for _, n := range sortedKeys(nightUntimed) {
		p.note("%s: %s is cheaper from %s to %s; priced at the day price. Give a departure time.", country, n, nightUntimed[n][0], nightUntimed[n][1])
	}
	if free > 0 {
		how := " (by the passage times)"
		if untimedFree {
			how = " (without a departure time the route is taken to pass them within the hour)"
		}
		p.note("%s: %d more toll station passage(s) free: their group charges once within its time (the hour rule)%s.", country, free, how)
	}
	if peakUntimed > 0 {
		p.note("%s: %d station passage(s) charge more in rush hours; priced at the off-peak rate. Give a departure time.", country, peakUntimed)
	}
	if pm.noTime > 0 {
		p.note("%s: %s not priced: give time (HH:MM, local departure) to price its %d station passage(s).", country, ds.Name, pm.noTime)
	}
	if congName != "" && cong.offHours > 0 {
		p.note("%s: %d passage(s) outside the tax's hours or days.", country, cong.offHours)
	}
	if cong.multi > 0 {
		p.note("%s: %d passage(s) within the multi-passage window pay only the highest amount.", country, cong.multi)
	}
}

func rowsOn(ch *orct.Charge, obj, tc string) bool {
	return slices.Contains(ch.RowObjects()[obj], tc)
}

func strs(v any) []string {
	l, _ := v.([]any)
	var out []string
	for _, x := range l {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// ---------------------------------------------------------------- crossings, zones, fuel

// priceCrossings prices the bridges and tunnels the route passes.
func (p *pricer) priceCrossings(set *tariffs.Set, route *track) error {
	for _, ds := range set.OfKind(tariffs.Crossings, p.date) {
		if ok, err := ds.Liable(p.vehicle); err != nil || !ok {
			continue
		}
		b := &batch{ds: ds}
		sm, pm := p.matchSystems(b, ds, ds.Country, "", route), p.matchPoints(b, ds, ds.Country, route)
		if !sm.any && !pm.any {
			continue
		}
		st, err := p.price(b, "", nil)
		if err != nil {
			return err
		}
		pm.listed = len(pm.passes) > 0
		p.afterPoints(ds, ds.Country, st, pm)
		p.afterSystems(ds, ds.Country, st, sm)
		p.addSources(ds)
		p.useTable(ds)
	}
	return nil
}

// priceZones adds a day's charge for each zone the route drives into, at
// the times it is there (noon without a departure time).
func (p *pricer) priceZones(set *tariffs.Set, route *track) error {
	for _, ds := range set.OfKind(tariffs.Zone, p.date) {
		if ok, err := ds.Liable(p.vehicle); err != nil || !ok {
			continue
		}
		var zone *orct.Object
		for _, o := range ds.Objects() {
			if o.Type == "area" {
				zone = o
			}
		}
		if zone == nil {
			continue
		}
		polys := polygonsOf(zone)
		var in []int
		for i, pt := range route.pts {
			if inPolygons(polys, pt) {
				in = append(in, i)
			}
		}
		if len(in) == 0 {
			continue
		}
		ch := ds.Charges()[0]
		km := route.cum[in[len(in)-1]] - route.cum[in[0]]
		m := &lineMeta{charge: AreaCharge, country: ds.Country, section: zone.Name, km: km, hasKm: true, key: "zone"}
		b := &batch{ds: ds}
		timed := p.req.Time != ""
		if timed {
			for _, i := range in {
				at, _ := passage(p.req, p.date, route.cum[i], ds.Country)
				b.event(zone.ID, at, m)
			}
		} else {
			b.event(zone.ID, p.noon(ds), m)
		}
		var amount float64
		st, err := p.price(b, ds.Method()+" ("+ds.File+")", func(l *Line, ol *orct.Line) { amount = ol.Amount.Float() })
		if err != nil {
			return err
		}
		switch {
		case len(st.Lines) > 0 && amount == 0:
			p.note("%s: the route enters the %s; a Euro %d truck pays nothing there.", ds.Country, ds.Name, p.req.Truck.Euro)
		case len(st.Lines) == 0 && timed:
			p.note("%s: the route is in the %s outside its charging hours.", ds.Country, ds.Name)
		case !timed && len(ch.Columns) > 0 && len(timeClasses(ch)) > 0 && ch.Unmatched == "free":
			p.note("%s: the %s charges only at certain hours; taken to be in them. Give a departure time.", ds.Country, ds.Name)
		}
	}
	return nil
}

// priceFuel prices national CO2 prices on road fuel: fuel bought in
// fuel_country, or along the route in proportion to each country's km.
func (p *pricer) priceFuel(set *tariffs.Set, roadT float64) error {
	if roadT <= 0 {
		return nil
	}
	req, out := p.req, p.out
	share := map[string]float64{}
	if req.FuelCountry != "" {
		share[req.FuelCountry] = 1
	} else {
		var total float64
		for _, km := range out.CountryKm {
			total += km
		}
		for cc, km := range out.CountryKm {
			if total > 0 {
				share[cc] = km / total
			}
		}
	}
	priced, perLitre := false, false
	for _, cc := range sortedKeys(share) {
		if share[cc] <= 0 {
			continue
		}
		var ds *tariffs.Dataset
		for _, d := range set.OfKind(tariffs.FuelCO2, p.date) {
			if d.Country == cc {
				ds = d
			}
		}
		if ds == nil {
			continue
		}
		var obj string
		for _, o := range ds.Objects() {
			if o.Type == "jurisdiction" {
				obj = o.ID
			}
		}
		t := roadT * share[cc]
		m := &lineMeta{charge: FuelCO2, country: cc}
		if req.FuelCountry == "" {
			m.km, m.hasKm = out.CountryKm[cc], true
		}
		unit, v := "t_co2", t
		if len(ds.Doc.Charges) > 0 && ds.Doc.Charges[0].Unit == "litre" {
			// A tax per litre: the litres given, or the CO2's at the
			// standard factor.
			unit, v = "litre", t*1000/DieselKgCO2PerL
			if req.DieselL > 0 {
				v = req.DieselL * share[cc]
			} else {
				perLitre = true
			}
		}
		b := &batch{ds: ds}
		b.quants = append(b.quants, orct.Quantity{Dataset: ds.ID, Object: obj, Time: stamp(p.noon(ds)), Unit: unit, Value: orct.FloatStr(v), Ref: m})
		if _, err := p.price(b, ds.Name+" ("+ds.File+")", nil); err != nil {
			return err
		}
		priced = true
	}
	switch {
	case priced && req.FuelCountry == "":
		p.note("Fuel CO2: national CO2 prices on diesel are paid where the fuel is bought; here the fuel is taken as bought along the route in proportion to each country's road km. Give fuel_country for where the truck fills up.")
	case priced:
		p.note("Fuel CO2: the national CO2 price on diesel of %s, where the fuel is bought, on this trip's road fuel.", req.FuelCountry)
	}
	if perLitre {
		p.note("Fuel CO2: taxes per litre are on the road part's tank-to-wheel CO2 at %.2f kg CO2e per litre of diesel (EN 16258:2012, Annex A). Give diesel_l for the litres the truck burns.", DieselKgCO2PerL)
	}
	return nil
}

// ---------------------------------------------------------------- provenance

func (p *pricer) addSources(ds *tariffs.Dataset) {
	for _, s := range srcs(ds) {
		if !slices.ContainsFunc(p.out.Sources, func(x rates.Source) bool { return x.URL == s.URL }) {
			p.out.Sources = append(p.out.Sources, s)
		}
	}
}

func (p *pricer) useTable(ds *tariffs.Dataset) {
	for _, t := range p.out.Provenance.Tables {
		if t.File == ds.File {
			return
		}
	}
	var osm string
	ds.Ext("osm_extract", &osm)
	p.out.Provenance.Tables = append(p.out.Provenance.Tables, TableUsed{Name: ds.Name, Area: ds.Area(), ValidFrom: ds.ValidFrom,
		ValidTo: ds.ValidTo, File: ds.File, OSMExtract: osm})
}

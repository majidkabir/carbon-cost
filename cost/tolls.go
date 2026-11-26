package cost

import (
	"encoding/json"
	"fmt"
	"math"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/majidkabir/carbon-cost/orct"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// Tolls are priced from ORCT datasets (package tariffs): the route is
// matched to a dataset's charge objects (its network by road class, its
// stations, toll points, sections, zones) and each use becomes an ORCT
// event; package orct prices the events as the specification says and
// each statement line becomes a Line.

// vehicleOf is the truck as ORCT vehicle parameters.
// Vehicle is a truck as the rate tables' vehicle parameters (ORCT 6.6),
// as the calculator prices it.
func Vehicle(t rates.Truck) map[string]any { return vehicleOf(t) }

func vehicleOf(t rates.Truck) map[string]any {
	axles := t.Axles
	if t.MotorAxles > 0 {
		axles = t.MotorAxles
	}
	// carbon-cost prices road fuel as diesel; a zero-emission truck (CO2
	// class 5) counts as electric.
	energy := "diesel"
	if t.CO2Class == 5 {
		energy = "electric"
	}
	v := map[string]any{"train_mass_kg": float64(t.MaxMassKg), "train_axles": float64(t.Axles), "axles": float64(axles),
		"euro_class": strconv.Itoa(t.Euro), "co2_class": float64(t.CO2Class), "train_length_m": t.Length(), "energy": energy}
	if t.MotorMassKg > 0 {
		v["mass_kg"] = float64(t.MotorMassKg)
	}
	if t.TrailerMassKg > 0 {
		v["trailer_mass_kg"] = float64(t.TrailerMassKg)
	}
	if t.CapacityKg > 0 {
		v["load_capacity_kg"] = float64(t.CapacityKg)
	}
	return v
}

// lineMeta is what a Line takes from the use an event stands for.
type lineMeta struct {
	charge                               string // RoadToll, FerryFare, AreaCharge or FuelCO2
	country, region, road, area, section string
	km, tonnesCO2                        float64
	hasKm                                bool
	// key: the lines of events with the same key and row are one Line (a
	// part's km split by area, a period's days).
	key string
}

// batch is one dataset's events for a trip, priced together.
type batch struct {
	ds     *tariffs.Dataset
	events []orct.Event
	quants []orct.Quantity
}

func stamp(t time.Time) string { return t.Format(time.RFC3339) }

func (b *batch) event(obj string, at time.Time, m *lineMeta) *orct.Event {
	b.events = append(b.events, orct.Event{Dataset: b.ds.ID, Object: obj, Time: stamp(at), Ref: m})
	return &b.events[len(b.events)-1]
}

// keepDays keeps the uses on the local days keep says: a ticket (entry
// and exit) by its time basis's, as versions takes its table.
func (b *batch) keepDays(keep func(day string) bool) {
	day := func(ts string) string {
		t, err := b.ds.Local(ts)
		if err != nil {
			return ""
		}
		return t.Format(time.DateOnly)
	}
	var evs []orct.Event
	for i := 0; i < len(b.events); i++ {
		e := b.events[i]
		if x := i + 1; e.Role == "entry" && x < len(b.events) && b.events[x].Role == "exit" && b.events[x].Ref == e.Ref {
			lead := e
			if odBasisExit(b.ds) {
				lead = b.events[x]
			}
			if keep(day(lead.Time)) {
				evs = append(evs, e, b.events[x])
			}
			i = x
			continue
		}
		if keep(day(e.Time)) {
			evs = append(evs, e)
		}
	}
	b.events = evs
	b.quants = slices.DeleteFunc(b.quants, func(q orct.Quantity) bool { return !keep(day(q.Time)) })
}

func (b *batch) km(obj string, at time.Time, km float64, overlays map[string]float64, m *lineMeta) {
	e := b.event(obj, at, m)
	d := orct.FloatStr(km)
	e.Km = &d
	for k, v := range overlays {
		if e.Overlays == nil {
			e.Overlays = map[string]orct.Dec{}
		}
		e.Overlays[k] = orct.FloatStr(v)
	}
}

// pricer prices one trip's tolls.
type pricer struct {
	req     Request
	date    time.Time
	out     *Response
	add     func(Line) error
	vehicle map[string]any
	payment []string
	// set has the other versions of a scheme, for a use the trip reaches
	// after its table's last day (nil: none are looked for).
	set *tariffs.Set
	// fareAt are the places of the fare tables' ports the route passed.
	fareAt []rates.Place
	// shared are the days of shared vignettes paid so far: group, day,
	// the area charged.
	shared map[string]map[string]string
	// only, when set, keeps an area's uses on the local days it says: a
	// version prices its own days where the scheme changes kind (otherKind).
	only func(day string) bool
}

func newPricer(req Request, date time.Time, out *Response, add func(Line) error) *pricer {
	p := &pricer{req: req, date: date, out: out, add: add, vehicle: vehicleOf(req.Truck)}
	// The load carried on the trip, for fares per tonne of it (the Elbe
	// ferry's per started 1,000 kg): the heaviest on any leg, where the
	// legs aren't priced each at their own (priceCrossings).
	load := req.CargoKg
	for _, l := range req.legLoadKg {
		load = math.Max(load, l)
	}
	if load > 0 {
		p.vehicle["load_kg"] = load
	}
	if req.ETC {
		p.payment = []string{"electronic"}
	}
	return p
}

func (p *pricer) note(format string, a ...any) {
	if n := fmt.Sprintf(format, a...); !slices.Contains(p.out.Notes, n) {
		p.out.Notes = append(p.out.Notes, n)
	}
}

// noon is the time an untimed use is priced at: noon local time on the
// trip's date, so day rates apply.
func (p *pricer) noon(ds *tariffs.Dataset) time.Time {
	return time.Date(p.date.Year(), p.date.Month(), p.date.Day(), 12, 0, 0, 0, ds.TZ())
}

// at is when the trip reaches pos km along the route in the dataset's
// country, and whether a departure time was given (else noon).
func (p *pricer) at(ds *tariffs.Dataset, pos float64, country string) (time.Time, bool) {
	if t, ok := passage(p.req, p.date, pos, country); ok {
		return t, true
	}
	return p.noon(ds), false
}

// chargeOf is a statement line's charge, from the dataset that priced it:
// a later version's for a use moved there (its charge ids may be others).
func (p *pricer) chargeOf(ds *tariffs.Dataset, l *orct.Line) *orct.Charge {
	if l.Dataset != "" && l.Dataset != ds.ID && p.set != nil {
		for _, d := range p.set.All {
			if d.ID == l.Dataset {
				return d.Charge(l.Charge)
			}
		}
	}
	return ds.Charge(l.Charge)
}

// componentOf is the Line component of an ORCT charge.
func componentOf(ch *orct.Charge) string {
	switch ch.Type {
	case "point", "od", "area":
		return rates.Toll
	}
	if ch.ComponentLabel != "" {
		return ch.ComponentLabel
	}
	switch ch.Component {
	case "infrastructure":
		return rates.Infrastructure
	case "air_pollution":
		return rates.Air
	case "noise":
		return rates.Noise
	case "air_pollution_noise":
		return rates.AirNoise
	case "co2", "carbon_price":
		return rates.CO2
	case "unspecified":
		return rates.Toll
	}
	return ch.Component
}

// sourceText is a charge's legal basis: its own method, else the dataset's.
func sourceText(ds *tariffs.Dataset, ch *orct.Charge) string {
	var s string
	if len(ch.Method) > 0 && json.Unmarshal(ch.Method, &s) == nil && s != "" {
		return s
	}
	return ds.Method()
}

func srcs(ds *tariffs.Dataset) []rates.Source {
	var out []rates.Source
	for _, s := range ds.Sources() {
		out = append(out, rates.Source{Title: s.Title, URL: s.URL})
	}
	return out
}

// price prices the batch and adds its lines; it returns the statement.
func (p *pricer) price(b *batch, src string, extra func(*Line, *orct.Line)) (*orct.Statement, error) {
	if len(b.events) == 0 && len(b.quants) == 0 {
		return &orct.Statement{}, nil
	}
	versions := p.versions(b)
	dss := []*orct.Dataset{b.ds.Dataset}
	for _, v := range versions {
		if v != b.ds {
			dss = append(dss, v.Dataset)
		}
	}
	u := &orct.Usage{ORCTUsage: "0.3", Vehicle: p.vehicle, Payment: p.payment, Events: b.events, Quantities: b.quants}
	st := orct.Calculate(dss, u)
	var lines []*Line
	merged := map[string]*Line{}
	// lineDay is each event time's local day, lineAt each line's (a cap's
	// cut is a day's).
	lineDay, lineAt := map[string]string{}, map[*Line]string{}
	for _, ol := range st.Lines {
		if ol.Event != nil {
			d := b.ds
			if v := versions[ol.Dataset]; v != nil {
				d = v
			}
			if t, err := d.Local(ol.Event.Time); err == nil {
				lineDay[ol.Event.Time] = t.Format(time.DateOnly)
			}
		}
	}
	for _, ol := range st.Lines {
		ds := b.ds
		if v := versions[ol.Dataset]; v != nil {
			ds = v
		}
		cur := ds.Doc.Header.Currency
		ch := ds.Charge(ol.Charge)
		var m *lineMeta
		if ol.Event != nil {
			m, _ = ol.Event.Ref.(*lineMeta)
		}
		if m == nil {
			m = &lineMeta{charge: RoadToll, country: ds.Country}
		}
		amount := ol.Amount.Float()
		key := ""
		if m.key != "" && ol.Row != nil && (ch.Type == "distance" || ch.Type == "period" || ch.Type == "area") {
			key = fmt.Sprintf("%s|%s|%s|%d", m.key, ol.Dataset, ol.Charge, *ol.Row)
		}
		rate, _ := orct.ParseDec(ol.Rate)
		// A factor rule's surcharge on part of the km (a surcharged
		// stretch) is a line of its own, l keeping the base amount.
		factors := func(l *Line) {
			for _, r := range ds.Doc.Rules {
				if r.Kind != "factor" || !slices.Contains(r.AppliesTo, ol.Charge) || ol.Event == nil {
					continue
				}
				obj, _ := r.Params["object"].(string)
				okm, ok := ol.Event.Overlays[obj]
				if !ok || okm.Sign() == 0 {
					continue
				}
				extra := amount - rate.Mul(ol.Quantity).Float()
				l.Amount -= extra
				sk := key + "|" + obj
				if prev, ok := merged[sk]; ok && key != "" {
					prev.Amount += extra
					prev.Km += okm.Float()
					continue
				}
				f, _ := orct.ParseDec(fmt.Sprint(r.Params["factor"]))
				s := *l
				s.Section, s.Km = ds.Object(obj).Name, okm.Float()
				s.Rate = rate.Mul(f.Sub(orct.DecInt(1))).Float()
				s.Amount = extra
				lines = append(lines, &s)
				if key != "" {
					merged[sk] = &s
				}
			}
		}
		if l, ok := merged[key]; ok && key != "" {
			l.Amount += amount
			if l.Area != m.area {
				l.Area = ""
			}
			switch ch.Type {
			case "period", "area": // another day: the same km
				l.Days++
			case "distance":
				if m.hasKm {
					l.Km += m.km
				}
			}
			factors(l)
			continue
		}
		l := &Line{Charge: m.charge, Country: m.country, Region: m.region, Road: m.road, Area: m.area, Section: m.section,
			Component: componentOf(ch), Rate: rate.Float(), Currency: cur, Amount: amount, Source: src, Sources: srcs(ds)}
		if src == "" {
			l.Source = sourceText(ds, ch)
		}
		if m.hasKm {
			l.Km = m.km
		}
		l.Carbon = l.Component == rates.CO2
		switch ch.Type {
		case "distance":
			l.RateUnit = cur + "/" + ch.Unit
			if ch.Unit == "tkm" && m.km > 0 {
				l.Tonnes = ol.Quantity.Float() / m.km
			}
		case "period":
			l.RateUnit, l.Days = cur+"/day", 1
		case "section":
			l.RateUnit = cur + "/section"
			if ch.Unit == "km" {
				l.RateUnit = cur + "/km"
				l.Km = ol.Quantity.Float()
			}
		case "point", "od":
			l.RateUnit = cur + "/passage"
		case "area":
			l.RateUnit, l.Days = cur+"/day", 1
		case "quantity":
			if ch.Unit == "litre" {
				l.RateUnit, l.Litres = cur+"/l", ol.Quantity.Float()
			} else {
				l.RateUnit, l.TonnesCO2 = cur+"/t CO2", ol.Quantity.Float()
			}
		}
		if ol.Unit == "rule" {
			// A cap's cut (a day's maximum of passages) comes off that
			// day's last passages first, none below nothing: those over
			// the maximum are free.
			if amount < 0 && ol.Event != nil && capCut(ol) {
				day := lineDay[ol.Event.Time]
				left := -amount
				for i := len(lines) - 1; i >= 0 && left > 1e-9; i-- {
					x := lines[i]
					if x.Charge != m.charge || x.Country != m.country || x.Currency != cur || lineAt[x] != day || x.Amount <= 0 {
						continue
					}
					cut := math.Min(x.Amount, left)
					x.Amount -= cut
					left -= cut
				}
				amount = -left
				if left <= 1e-9 {
					continue
				}
			}
			// A rule's adjustment (a cap, a minimum): it adds to the line
			// of the use it adjusts.
			if prev := lastOf(lines, m); prev != nil {
				prev.Amount += amount
				continue
			}
			l.Rate, l.Km = amount, 0
		}
		if extra != nil {
			extra(l, ol)
		}
		if ol.Event != nil {
			lineAt[l] = lineDay[ol.Event.Time]
		}
		lines = append(lines, l)
		if key != "" {
			merged[key] = l
		}
		factors(l)
	}
	for _, l := range lines {
		if math.Abs(l.Amount) < 0.005 && l.Charge != FuelCO2 {
			continue
		}
		l.Km = round3(l.Km)
		l.TonnesCO2 = round3(l.TonnesCO2)
		l.Litres = round3(l.Litres)
		if err := p.add(*l); err != nil {
			return st, err
		}
	}
	return st, nil
}

// versions moves the batch's uses on days after its table's last to the
// version of the scheme in force then (a bridge crossed after midnight on
// 31 December pays the new year's toll), and returns the tables so used,
// by id. A use with no table in force that day is reported missing.
func (p *pricer) versions(b *batch) map[string]*tariffs.Dataset {
	out := map[string]*tariffs.Dataset{b.ds.ID: b.ds}
	// at is the table of b.ds's scheme in force on the local day of ts:
	// b.ds, a later or earlier version, or nil.
	at := func(ts string) *tariffs.Dataset {
		t, err := b.ds.Local(ts)
		if err != nil {
			return b.ds
		}
		day := t.Format(time.DateOnly)
		if b.ds.ValidFrom <= day && (b.ds.ValidTo == "" || day <= b.ds.ValidTo) {
			return b.ds
		}
		if p.set != nil {
			if v, ok := p.set.Version(b.ds, day); ok {
				return v
			}
		}
		return nil
	}
	// gone reports a use with no table that day: before the first (one
	// that starts later, unless the charge itself began then) or after the
	// last.
	gone := func(ts string, ref any) {
		if p.set == nil {
			return
		}
		charge := RoadToll
		if m, ok := ref.(*lineMeta); ok && m.charge != "" {
			charge = m.charge
		}
		m := Missing{Area: b.ds.Area(), Charge: charge, Name: b.ds.Name, Reason: "ended", Ended: b.ds.ValidTo}
		if t, err := b.ds.Local(ts); err == nil && t.Format(time.DateOnly) < b.ds.ValidFrom {
			if since := ""; b.ds.Ext("charged_from", &since) && since >= b.ds.ValidFrom {
				return // no charge before it
			}
			m = Missing{Area: b.ds.Area(), Charge: charge, Name: b.ds.Name, Reason: "before_table", Starts: b.ds.ValidFrom}
		}
		if !slices.ContainsFunc(p.out.Missing, func(x Missing) bool { return x.Name == m.Name && x.Reason == m.Reason }) {
			p.out.Missing = append(p.out.Missing, m)
		}
	}
	use := func(v *tariffs.Dataset) {
		if v != b.ds && out[v.ID] == nil {
			out[v.ID] = v
			p.addSources(v)
			p.useTable(v)
		}
	}
	move := func(ds, obj *string, ts string, ref any) {
		v := at(ts)
		switch {
		case v == nil:
			gone(ts, ref)
		case v != b.ds:
			use(v)
			*ds, *obj = v.ID, sameObject(b.ds, v, *obj)
		}
	}
	// within is ts taken within v's days: its first instant or its last.
	within := func(v *tariffs.Dataset, ts string) string {
		t, err := v.Local(ts)
		if err != nil {
			return ts
		}
		day := t.Format(time.DateOnly)
		if day < v.ValidFrom {
			if d, err := time.ParseInLocation(time.DateOnly, v.ValidFrom, v.TZ()); err == nil {
				return stamp(d)
			}
		}
		if v.ValidTo != "" && day > v.ValidTo {
			if d, err := time.ParseInLocation(time.DateOnly, v.ValidTo, v.TZ()); err == nil {
				return stamp(d.Add(24*time.Hour - time.Second))
			}
		}
		return ts
	}
	const dropped = "(no table)" // a ticket with no table: neither event priced
	// The tickets' spans and tables: a use a ticket includes (a bridge in
	// its fare, ORCT included_in) goes with the ticket's table.
	type span struct {
		from, to time.Time
		v        *tariffs.Dataset
	}
	var tickets []span
	included := map[string]bool{}
	for _, r := range b.ds.Doc.Rules {
		if r.Kind == "included_in" {
			if objs, ok := r.Params["objects"].([]any); ok {
				for _, o := range objs {
					if id, ok := o.(string); ok {
						included[id] = true
					}
				}
			}
		}
	}
	timeOf := func(ts string) time.Time {
		t, _ := time.Parse(time.RFC3339, ts)
		return t
	}
	for i := 0; i < len(b.events); i++ {
		e := &b.events[i]
		if x := i + 1; e.Role == "entry" && x < len(b.events) && b.events[x].Role == "exit" && b.events[x].Ref == e.Ref {
			// A ticket is priced by one table: the one in force at its
			// time basis, the entry (its rows' times go by it), else the
			// one at the exit (a table that starts that midnight); the
			// other event is taken within that table's days.
			ex := &b.events[x]
			lead, other := e, ex
			if odBasisExit(b.ds) {
				lead, other = ex, e
			}
			v := at(lead.Time)
			if v == nil {
				v = at(other.Time)
			}
			if len(included) > 0 {
				tickets = append(tickets, span{timeOf(e.Time), timeOf(ex.Time), v})
			}
			if v == nil {
				gone(lead.Time, lead.Ref)
				e.Dataset, ex.Dataset = dropped, dropped
				i = x
				continue
			}
			if v != b.ds {
				use(v)
				e.Object, ex.Object = sameObject(b.ds, v, e.Object), sameObject(b.ds, v, ex.Object)
			}
			e.Dataset, ex.Dataset = v.ID, v.ID
			e.Time, ex.Time = within(v, e.Time), within(v, ex.Time)
			i = x
			continue
		}
		from := e.Dataset
		if included[e.Object] {
			if t := timeOf(e.Time); slices.ContainsFunc(tickets, func(s span) bool { return !t.Before(s.from) && !t.After(s.to) }) {
				continue // the second pass puts it with its ticket
			}
		}
		move(&e.Dataset, &e.Object, e.Time, e.Ref)
		if e.Dataset != from && len(e.Overlays) > 0 {
			ov := map[string]orct.Dec{}
			for k, v := range e.Overlays {
				if id := sameObject(b.ds, out[e.Dataset], k); id != "" {
					ov[id] = v
				}
			}
			e.Overlays = ov
		}
	}
	// The uses a ticket includes: with its table, within its days (or
	// none, with it).
	for i := range b.events {
		e := &b.events[i]
		if e.Role != "" || !included[e.Object] || e.Dataset != b.ds.ID {
			continue
		}
		t := timeOf(e.Time)
		for _, s := range tickets {
			if t.Before(s.from) || t.After(s.to) {
				continue
			}
			switch {
			case s.v == nil:
				e.Dataset = dropped
			case s.v != b.ds:
				e.Dataset, e.Object = s.v.ID, sameObject(b.ds, s.v, e.Object)
			}
			if s.v != nil {
				e.Time = within(s.v, e.Time)
			}
			break
		}
	}
	b.events = slices.DeleteFunc(b.events, func(e orct.Event) bool { return e.Dataset == dropped })
	for i := range b.quants {
		move(&b.quants[i].Dataset, &b.quants[i].Object, b.quants[i].Time, b.quants[i].Ref)
	}
	// A use on a day the scheme charges nothing (Romania's Danube bridges
	// from 1 October 2026) owes nothing.
	free := func(id string) bool {
		if d := out[id]; d != nil && d.Doc.NoCharge != nil {
			p.note("%s: from %s, %s", d.Area(), d.ValidFrom, d.Doc.NoCharge.Description)
			return true
		}
		return false
	}
	b.events = slices.DeleteFunc(b.events, func(e orct.Event) bool { return free(e.Dataset) })
	b.quants = slices.DeleteFunc(b.quants, func(q orct.Quantity) bool { return free(q.Dataset) })
	return out
}

// odBasisExit says whether the dataset's tickets take their time at the
// exit (time_basis "exit"), not the entry.
func odBasisExit(ds *tariffs.Dataset) bool {
	for _, ch := range ds.Charges() {
		if ch.Type == "od" && ch.TimeBasis == "exit" {
			return true
		}
	}
	return false
}

// goneObject stands for an object a later version doesn't have: the
// calculator reports its use unpriced (unknown_object).
const goneObject = "(not in this version)"

// sameObject is the object of version v that is old's object id: ids
// aren't kept from one version to the next (Norway's and Greece's number
// their stations), so the one of the same type, name, road and operator,
// the nearest facing the same way where there are several; goneObject if
// v has none.
func sameObject(old, v *tariffs.Dataset, id string) string {
	o := old.Object(id)
	if o == nil || v == nil {
		return id
	}
	same := func(x *orct.Object) bool {
		return x.Type == o.Type && x.Name == o.Name && x.Road == o.Road && x.Operator == o.Operator
	}
	// Its own id, where it is still there (renamed or not: "A1 Pombal -
	// Soure" became "A1 Pombal – Soure"), or both have no place (a
	// network).
	if x := v.Object(id); x != nil && x.Type == o.Type {
		if km, ok := objectKm(o, x); !ok || km < samePlaceKm {
			return id
		}
	}
	best, bestKm := goneObject, math.Inf(1)
	for _, x := range v.Objects() {
		if same(x) {
			km, _ := objectKm(o, x)
			if km < bestKm {
				best, bestKm = x.ID, km
			}
		}
	}
	if best != goneObject {
		return best
	}
	// Else one of its type in its place, renamed and renumbered ("Fv4856
	// Skjoldavegen", 16 m from "Skjoldavegen"): both placed, a section's
	// both ends (not a piece of one split).
	for _, x := range v.Objects() {
		if x.Type == o.Type {
			if km, ok := objectKm(o, x); ok && km < samePlaceKm && km < bestKm {
				best, bestKm = x.ID, km
			}
		}
	}
	return best
}

// samePlaceKm is how near an object of the next version must be to be
// the same one when its name has changed.
const samePlaceKm = 0.2

// objectKm is how far apart two objects are: their points (a
// section's farther apart end), with 1,000 km more for points facing
// other ways; ok is false if either has no place (a network).
func objectKm(a, b *orct.Object) (float64, bool) {
	ends := func(o *orct.Object) []rates.Place {
		if pts := pointsOf(o); len(pts) > 0 {
			return pts[:1]
		}
		if o.From != nil && len(o.From.Geometry.Coordinates) > 0 && o.To != nil && len(o.To.Geometry.Coordinates) > 0 {
			return []rates.Place{endOf(o.From), endOf(o.To)}
		}
		return nil
	}
	pa, pb := ends(a), ends(b)
	if len(pa) == 0 || len(pa) != len(pb) {
		return 0, false
	}
	km := 0.0
	for i := range pa {
		km = math.Max(km, haversine(pa[i].Lat, pa[i].Lon, pb[i].Lat, pb[i].Lon))
	}
	if pa[0].Heading != nil && pb[0].Heading != nil {
		if d := math.Mod(math.Abs(*pa[0].Heading-*pb[0].Heading), 360); math.Min(d, 360-d) > 90 {
			km += 1000
		}
	}
	return km, true
}

// capCut says whether a rule's line is a cap's (orct notes it "cap <id>").
func capCut(ol *orct.Line) bool {
	return slices.ContainsFunc(ol.Notes, func(n string) bool { return strings.HasPrefix(n, "cap ") })
}

// lastOf is the last line priced from the same use (meta), if any.
func lastOf(lines []*Line, m *lineMeta) *Line {
	for i := len(lines) - 1; i >= 0; i-- {
		l := lines[i]
		if l.Section == m.section && l.Country == m.country {
			return l
		}
	}
	return nil
}

// ---------------------------------------------------------------- networks

// network is a dataset's network objects by what they cover.
type network struct {
	root, env string
	sections  string
	byType    map[string]string // road type -> object
	byArea    map[string]string // area -> object
	cells     map[[2]string]string
	ops       []*orct.Object
	roadTypes []string // the road types its rates differ by
	areas     []string
	hasRows   bool // distance or period charges
	perDay    *orct.Charge
	tkm       bool
}

func networkOf(ds *tariffs.Dataset) *network {
	n := &network{byType: map[string]string{}, byArea: map[string]string{}, cells: map[[2]string]string{}}
	rowObj := map[string]bool{}
	for _, ch := range ds.Charges() {
		switch ch.Type {
		case "distance", "period":
			if ch.ComponentLabel == rates.EnvZoneSurcharge {
				for o := range ch.RowObjects() {
					n.env = o
				}
				continue
			}
			n.hasRows = true
			for o := range ch.RowObjects() {
				rowObj[o] = true
			}
			if ch.Type == "period" {
				n.perDay = ch
			}
			if ch.Unit == "tkm" {
				n.tkm = true
			}
		}
	}
	for _, o := range ds.Objects() {
		if o.Type != "network" {
			continue
		}
		switch {
		case o.ID == n.env:
		case o.Operator != "":
			n.ops = append(n.ops, o)
		case o.Network != nil && len(o.Network.RoadTypes) == 1 && o.Network.Area != "":
			n.cells[[2]string{roadTypeOf(o), o.Network.Area}] = o.ID
		case o.Network != nil && len(o.Network.RoadTypes) == 1:
			n.byType[roadTypeOf(o)] = o.ID
		case o.Network != nil && o.Network.Area != "":
			n.byArea[o.Network.Area] = o.ID
		case len(o.Parents) == 0 && n.root == "" && o.Location == nil:
			n.root = o.ID
		case o.Location == nil && len(o.Parents) > 0 && n.sections == "" && strings.HasPrefix(o.Name, "Sections with a toll"):
			n.sections = o.ID
		}
	}
	for rt := range n.byType {
		n.roadTypes = append(n.roadTypes, rt)
	}
	sort.Strings(n.roadTypes)
	if len(n.byType) == 1 && len(n.ops) > 0 {
		// Only operators' rows: the rates don't differ by road type
		// unless rows name one.
		n.roadTypes = n.roadTypesNamed(ds)
	}
	for a := range n.byArea {
		n.areas = append(n.areas, a)
	}
	sort.Strings(n.areas)
	return n
}

// roadTypesNamed are the road types rows are keyed by (not through an
// operator).
func (n *network) roadTypesNamed(ds *tariffs.Dataset) []string {
	var out []string
	for _, ch := range ds.Charges() {
		for o := range ch.RowObjects() {
			for rt, id := range n.byType {
				if id == o && !slices.Contains(out, rt) {
					out = append(out, rt)
				}
			}
			for k, id := range n.cells {
				if id == o && !slices.Contains(out, k[0]) {
					out = append(out, k[0])
				}
			}
		}
	}
	sort.Strings(out)
	return out
}

// roadTypeOf is a network object's road type as carbon-cost names it.
func roadTypeOf(o *orct.Object) string {
	if o.Network.RoadTypes[0] == "motorway" {
		return rates.Motorway
	}
	return rates.OtherRoad
}

// object is the most specific network object for km on a road type (""
// for any), in an area ("" for any), on an operator's ways (op as
// roads.Km keys them, "operator|ref|name").
func (n *network) object(road, area, op string) string {
	if op != "" {
		parts := strings.Split(op, "|")
		for k := min(len(parts), 3); k >= 1; k-- {
			r, name := "", ""
			if k >= 2 {
				r = parts[1]
			}
			if k >= 3 {
				name = parts[2]
			}
			for _, o := range n.ops {
				if o.Operator == parts[0] && o.Road == r && o.Name == name {
					return o.ID
				}
			}
		}
	}
	if id, ok := n.cells[[2]string{road, area}]; ok && road != "" && area != "" {
		return id
	}
	if id, ok := n.byType[road]; ok && road != "" {
		return id
	}
	if id, ok := n.byArea[area]; ok && area != "" {
		return id
	}
	return n.root
}

// ---------------------------------------------------------------- geometry

func placeOf(coord []float64) rates.Place { return rates.Place{Lon: coord[0], Lat: coord[1]} }

// points and polygons cache the places and the polygons read from
// objects' locations (an area's points are none: each kind its own).
var points, polygons sync.Map // *orct.Object -> []rates.Place, polys

// pointsOf are a location's points, each with its heading and name.
func pointsOf(o *orct.Object) []rates.Place {
	if v, ok := points.Load(o); ok {
		return v.([]rates.Place)
	}
	pts := readPoints(o)
	points.Store(o, pts)
	return pts
}

func readPoints(o *orct.Object) []rates.Place {
	if o.Location == nil || o.Location.Geometry == nil {
		return nil
	}
	g := o.Location.Geometry
	var out []rates.Place
	switch g.Type {
	case "Point":
		var c []float64
		json.Unmarshal(g.Coordinates, &c)
		p := placeOf(c)
		p.Heading = o.Location.Heading
		out = append(out, p)
	case "MultiPoint", "LineString":
		var cs [][]float64
		json.Unmarshal(g.Coordinates, &cs)
		for i, c := range cs {
			p := placeOf(c)
			if i < len(o.Location.Headings) {
				p.Heading = o.Location.Headings[i]
			}
			if i < len(o.Location.PointNames) {
				p.Name = o.Location.PointNames[i]
			}
			out = append(out, p)
		}
	}
	return out
}

func endOf(pl *orct.Place) rates.Place {
	var c []float64
	json.Unmarshal(pl.Geometry.Coordinates, &c)
	p := placeOf(c)
	p.Name, p.Heading = pl.Name, pl.Heading
	return p
}

type polys [][][][2]float64

// polygonsOf are an area's polygons, each its outer ring and holes.
func polygonsOf(o *orct.Object) [][][][2]float64 {
	if v, ok := polygons.Load(o); ok {
		return v.(polys)
	}
	p := readPolygons(o)
	polygons.Store(o, polys(p))
	return p
}

func readPolygons(o *orct.Object) [][][][2]float64 {
	if o.Location == nil || o.Location.Geometry == nil {
		return nil
	}
	var out [][][][2]float64
	switch o.Location.Geometry.Type {
	case "MultiPolygon":
		json.Unmarshal(o.Location.Geometry.Coordinates, &out)
	case "Polygon":
		var p [][][2]float64
		json.Unmarshal(o.Location.Geometry.Coordinates, &p)
		out = append(out, p)
	}
	return out
}

// bboxOf is the polygons' outer rings' box: min lon, min lat, max lon,
// max lat.
func bboxOf(polys [][][][2]float64) [4]float64 {
	b := [4]float64{math.Inf(1), math.Inf(1), math.Inf(-1), math.Inf(-1)}
	for _, poly := range polys {
		if len(poly) == 0 {
			continue
		}
		for _, p := range poly[0] {
			b[0], b[1], b[2], b[3] = min(b[0], p[0]), min(b[1], p[1]), max(b[2], p[0]), max(b[3], p[1])
		}
	}
	return b
}

func inPolygons(polys [][][][2]float64, pt [2]float64) bool {
	for _, poly := range polys {
		if len(poly) == 0 || !inRing(poly[0], pt) {
			continue
		}
		hole := false
		for _, h := range poly[1:] {
			hole = hole || inRing(h, pt)
		}
		if !hole {
			return true
		}
	}
	return false
}

func inRing(r [][2]float64, p [2]float64) bool {
	in := false
	for i, j := 0, len(r)-1; i < len(r); j, i = i, i+1 {
		if (r[i][1] > p[1]) != (r[j][1] > p[1]) && p[0] < (r[j][0]-r[i][0])*(p[1]-r[i][1])/(r[j][1]-r[i][1])+r[i][0] {
			in = !in
		}
	}
	return in
}

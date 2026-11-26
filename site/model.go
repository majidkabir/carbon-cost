package site

import (
	"fmt"
	"math"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/orct"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// What the pages show, worked out from the rate tables with the
// calculator's own pricing (package orct, the calculator's vehicle).

// scheme is a toll scheme's versions around a day.
type scheme struct {
	ID, Name, Kind string
	Current        *tariffs.Dataset
	Past           []*tariffs.Dataset // before Current, newest first
	Upcoming       []*tariffs.Dataset // from after the day, soonest first
}

// latest is the version in force, else the first to come.
func (s *scheme) latest() *tariffs.Dataset {
	if s.Current != nil {
		return s.Current
	}
	if len(s.Upcoming) > 0 {
		return s.Upcoming[0]
	}
	return s.Past[0]
}

// country is a country's schemes.
type country struct {
	Code, Slug, Name, Local string
	Schemes                 []*scheme
}

func (c *country) of(kind string) []*scheme {
	var out []*scheme
	for _, s := range c.Schemes {
		if s.Kind == kind {
			out = append(out, s)
		}
	}
	return out
}

// group sorts the datasets by country and scheme, as on the day.
func group(set *tariffs.Set, day string) []*country {
	by := map[string]*country{}
	schemes := map[string]*scheme{}
	for _, d := range set.All {
		c := by[d.Country]
		if c == nil {
			c = &country{Code: d.Country, Slug: strings.ToLower(d.Country), Name: countryName(d.Country), Local: localNames[d.Country]}
			by[d.Country] = c
		}
		s := schemes[d.Scheme]
		if s == nil {
			s = &scheme{ID: d.Scheme, Name: d.Name, Kind: d.Kind}
			schemes[d.Scheme] = s
			c.Schemes = append(c.Schemes, s)
		}
		switch {
		case d.ValidFrom > day:
			s.Upcoming = append(s.Upcoming, d)
		case d.ValidTo != "" && d.ValidTo < day:
			s.Past = append(s.Past, d)
		case s.Current == nil || d.ValidFrom > s.Current.ValidFrom:
			if s.Current != nil {
				s.Past = append(s.Past, s.Current)
			}
			s.Current = d
		default:
			s.Past = append(s.Past, d)
		}
	}
	kindRank := map[string]int{tariffs.Toll: 0, tariffs.Crossings: 1, tariffs.Zone: 2, tariffs.FuelCO2: 3}
	var out []*country
	for _, c := range by {
		for _, s := range c.Schemes {
			sort.Slice(s.Past, func(i, j int) bool { return s.Past[i].ValidFrom > s.Past[j].ValidFrom })
			sort.Slice(s.Upcoming, func(i, j int) bool { return s.Upcoming[i].ValidFrom < s.Upcoming[j].ValidFrom })
			s.Name = s.latest().Name
		}
		sort.SliceStable(c.Schemes, func(i, j int) bool {
			a, b := c.Schemes[i], c.Schemes[j]
			if kindRank[a.Kind] != kindRank[b.Kind] {
				return kindRank[a.Kind] < kindRank[b.Kind]
			}
			return a.ID < b.ID
		})
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

// Reference trucks.
var (
	// truck40 is a tractor with semi-trailer: 25 t of load capacity is
	// what Croatia's state ferries charge it by.
	truck40 = rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1, CapacityKg: 25000}
	byMass  = []struct {
		Label string
		Truck rates.Truck
	}{
		{"7.5 t, 2 axles", rates.Truck{MaxMassKg: 7500, Axles: 2, Euro: 6, CO2Class: 1}},
		{"12 t, 2 axles", rates.Truck{MaxMassKg: 12000, Axles: 2, Euro: 6, CO2Class: 1}},
		{"18 t, 2 axles", rates.Truck{MaxMassKg: 18000, Axles: 2, Euro: 6, CO2Class: 1}},
		{"26 t, 3 axles", rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}},
		{"32 t, 4 axles", rates.Truck{MaxMassKg: 32000, Axles: 4, Euro: 6, CO2Class: 1}},
		{"40 t, 5 axles", truck40},
	}
)

const truck40Label = "40 t, 5 axles, Euro VI, CO2 class 1"

// part is a component of an amount.
type part struct {
	Charge *orct.Charge // the first charge of the component
	Amount float64
	CO2    bool
}

// amount is what a use costs, by component.
type amount struct {
	Total, CO2 float64
	Parts      []part
	Cur        string
	OK         bool // the calculator priced every use
}

func (a amount) share() float64 {
	if a.Total == 0 {
		return 0
	}
	return a.CO2 / a.Total
}

func (a amount) scaled(f float64) amount {
	b := a
	b.Total, b.CO2 = a.Total*f, a.CO2*f
	b.Parts = make([]part, len(a.Parts))
	for i, p := range a.Parts {
		p.Amount *= f
		b.Parts[i] = p
	}
	return b
}

// noon is noon of the day in the dataset's time zone.
func noon(ds *tariffs.Dataset, day string) string {
	t, err := time.ParseInLocation(time.DateOnly, day, ds.TZ())
	if err != nil {
		t = time.Now().In(ds.TZ())
	}
	return time.Date(t.Year(), t.Month(), t.Day(), 12, 0, 0, 0, ds.TZ()).Format(time.RFC3339)
}

// day is the day a dataset is priced on: the page's day, or its first.
func priceDay(ds *tariffs.Dataset, today string) string {
	if ds.ValidFrom > today || (ds.ValidTo != "" && ds.ValidTo < today) {
		return ds.ValidFrom
	}
	return today
}

// calc prices events for the truck, as the calculator does.
// exampleLoadKg is the load the examples carry, for fares by the load's
// weight: the example semi-trailer's load capacity (c.fares.load).
const exampleLoadKg = 25000

func calc(ds *tariffs.Dataset, t rates.Truck, events []orct.Event) amount {
	v := cost.Vehicle(t)
	if t.CapacityKg > 0 {
		v["load_kg"] = float64(exampleLoadKg) // a fare by the load: the example's full load
	}
	u := &orct.Usage{ORCTUsage: "0.3", Vehicle: v, Events: events}
	st := orct.Calculate([]*orct.Dataset{ds.Dataset}, u)
	a := amount{Cur: ds.Doc.Header.Currency, OK: true}
	for _, is := range st.Issues {
		if is.Code != "partial_coverage" {
			a.OK = false
		}
	}
	idx := map[string]int{}
	for _, l := range st.Lines {
		ch := ds.Charge(l.Charge)
		if ch == nil {
			continue
		}
		v := l.Amount.Float()
		co2 := ch.Component == "co2"
		i, ok := idx[ch.Component]
		if !ok {
			i = len(a.Parts)
			idx[ch.Component] = i
			a.Parts = append(a.Parts, part{Charge: ch, CO2: co2})
		}
		a.Parts[i].Amount += v
		a.Total += v
		if co2 {
			a.CO2 += v
		}
	}
	return a
}

// kmObjects are the roads a dataset's km charges price for the 40 t
// truck, in the rows' order: each object of their rows that a toll is due
// on, but not one above another whose km more charges price (a network
// whose road types carry the rates). full: the objects that all the km
// charges price (not a stretch with part of them, such as a section with
// a toll of its own).
func kmObjects(ds *tariffs.Dataset) []string {
	objs, _ := kmRoads(ds, priceDay(ds, ds.ValidFrom))
	return objs
}

func kmRoads(ds *tariffs.Dataset, day string) (objs []string, full map[string]bool) {
	var cand []string
	seen := map[string]bool{}
	distance := map[string]bool{}
	for i := range ds.Doc.Charges {
		ch := &ds.Doc.Charges[i]
		if ch.Type != "distance" || (ch.Unit != "km" && ch.Unit != "tkm") {
			continue
		}
		distance[ch.ID] = true
		col := index(ch.Columns, "object")
		for _, r := range ch.Rows {
			o := ""
			if col >= 0 {
				o, _ = r[col].(string)
			} else if len(ch.Objects) > 0 {
				o = ch.Objects[0]
			}
			if o != "" && !seen[o] {
				seen[o] = true
				cand = append(cand, o)
			}
		}
	}
	if len(cand) == 0 {
		return nil, nil
	}
	// Road types that combine others (a motorway that is interurban).
	for _, o := range ds.Doc.Objects {
		if o.Type == "network" && !seen[o.ID] {
			seen[o.ID] = true
			cand = append(cand, o.ID)
		}
	}
	charges := map[string]map[string]bool{}
	for _, o := range cand {
		km := orct.FloatStr(100)
		u := &orct.Usage{ORCTUsage: "0.3", Vehicle: cost.Vehicle(truck40), Events: []orct.Event{{Dataset: ds.ID, Object: o, Time: noon(ds, day), Km: &km}}}
		st := orct.Calculate([]*orct.Dataset{ds.Dataset}, u)
		set, total := map[string]bool{}, 0.0
		for _, l := range st.Lines {
			if v := l.Amount.Float(); v > 0 && distance[l.Charge] {
				set[l.Charge] = true
				total += v
			}
		}
		if total > 0 {
			charges[o] = set
		}
	}
	superset := func(a, b map[string]bool) bool { // a ⊋ b
		if len(a) <= len(b) {
			return false
		}
		for k := range b {
			if !a[k] {
				return false
			}
		}
		return true
	}
	most := 0
	for _, o := range cand {
		set, ok := charges[o]
		if !ok {
			continue
		}
		drop := false
		for _, p := range cand {
			if q, ok := charges[p]; ok && p != o {
				if _, below := ds.Ancestors(p)[o]; below && superset(q, set) {
					drop = true
					break
				}
			}
		}
		if !drop {
			objs = append(objs, o)
			most = max(most, len(set))
		}
	}
	full = map[string]bool{}
	for _, o := range objs {
		full[o] = len(charges[o]) == most
	}
	return objs, full
}

func index(cols []string, c string) int {
	for i, x := range cols {
		if x == c {
			return i
		}
	}
	return -1
}

// perKm prices 100 km on the road for the truck on the day, per km.
func perKm(ds *tariffs.Dataset, obj string, t rates.Truck, day string) amount {
	km := orct.FloatStr(100)
	a := calc(ds, t, []orct.Event{{Dataset: ds.ID, Object: obj, Time: noon(ds, day), Km: &km}})
	return a.scaled(0.01)
}

// roadRate is a road's per-km rate for the reference truck.
type roadRate struct {
	Obj  string // the road's object
	Rate amount
	Full bool // all the km charges price it
}

// kmRates are the per-km rates of the truck on each road.
func kmRates(ds *tariffs.Dataset, t rates.Truck, day string) []roadRate {
	var out []roadRate
	objs, full := kmRoads(ds, day)
	for _, o := range objs {
		a := perKm(ds, o, t, day)
		if a.OK {
			out = append(out, roadRate{o, a, full[o]})
		}
	}
	return out
}

// fare is an example trip (From, To), passage (From) or vignette
// (Period, an ISO 8601 period).
type fare struct {
	From, To, Period string
	Rate             amount
}

// classRows are the rows of a charge for the truck's classes, each with
// its rank: 0 for the truck's own class, 1 for that class's fallback and
// so on, a row for any vehicle last (a row of a nearer class wins, as the
// calculator picks it).
func classRows(ds *tariffs.Dataset, ch *orct.Charge, t rates.Truck) map[int]int {
	classes, _ := ds.Classify(cost.Vehicle(t))
	rank := map[string]int{}
	for _, id := range classes {
		for k := 0; id != "" && k < 10; k++ {
			if _, ok := rank[id]; !ok {
				rank[id] = k
			}
			c := ds.Class(id)
			if c == nil {
				break
			}
			id = c.Fallback
		}
	}
	vc := index(ch.Columns, "vehicle_class")
	pay, user := index(ch.Columns, "payment"), index(ch.Columns, "user_class")
	out := map[int]int{}
	for i, r := range ch.Rows {
		k := 100 // no class: below every class of the truck
		if vc >= 0 {
			v, _ := r[vc].(string)
			if v != "" {
				var ok bool
				if k, ok = rank[v]; !ok {
					continue
				}
			}
		}
		if (pay >= 0 && r[pay] != nil) || (user >= 0 && r[user] != nil) {
			continue
		}
		out[i] = k
	}
	return out
}

// pick keeps, per key, the row of the nearest class, the dearest of those.
type pick struct {
	rank int
	v    float64
}

func (p pick) better(q pick) bool { return q.rank < p.rank || (q.rank == p.rank && q.v > p.v) }

func rowAmount(ch *orct.Charge, r []any) float64 {
	i := index(ch.Columns, "amount")
	if i < 0 {
		return 0
	}
	v, _ := num(r[i])
	return v
}

// odFares are a closed system's dearest trips for the truck (the longest,
// mostly), no station twice, priced as the calculator prices them, and the
// system's size.
func odFares(ds *tariffs.Dataset, ch *orct.Charge, t rates.Truck, day string, n int) (fares []fare, stations, pairs int) {
	en, ex := index(ch.Columns, "entry"), index(ch.Columns, "exit")
	if en < 0 || ex < 0 {
		return nil, 0, 0
	}
	sts, all := map[string]bool{}, map[[2]string]bool{}
	for _, r := range ch.Rows {
		a, _ := r[en].(string)
		b, _ := r[ex].(string)
		sts[a], sts[b] = true, true
		if a > b {
			a, b = b, a
		}
		all[[2]string{a, b}] = true
	}
	type cand struct {
		a, b string
		v    float64
	}
	best := map[[2]string]pick{}
	for i, rk := range classRows(ds, ch, t) {
		r := ch.Rows[i]
		a, _ := r[en].(string)
		b, _ := r[ex].(string)
		if a == b {
			continue
		}
		k := [2]string{a, b}
		if p, ok := best[k]; !ok || p.better(pick{rk, rowAmount(ch, r)}) {
			best[k] = pick{rk, rowAmount(ch, r)}
		}
	}
	var cs []cand
	for k, p := range best {
		cs = append(cs, cand{k[0], k[1], p.v})
	}
	sort.Slice(cs, func(i, j int) bool {
		if cs[i].v != cs[j].v {
			return cs[i].v > cs[j].v
		}
		return cs[i].a+cs[i].b < cs[j].a+cs[j].b
	})
	// The dearest candidates priced as the calculator prices them at noon
	// (a row's amount may be another hour's), then the dearest of those,
	// no station twice.
	when := noon(ds, day)
	type priced struct {
		a, b string
		v    amount
	}
	var ps []priced
	done := map[[2]string]bool{}
	for _, c := range cs {
		if len(ps) == 5*n {
			break
		}
		k := [2]string{c.a, c.b}
		if c.a > c.b {
			k = [2]string{c.b, c.a}
		}
		if done[k] {
			continue
		}
		done[k] = true
		a := calc(ds, t, []orct.Event{{Dataset: ds.ID, Object: c.a, Time: when, Role: "entry"}, {Dataset: ds.ID, Object: c.b, Time: when, Role: "exit"}})
		if a.OK && a.Total > 0 {
			ps = append(ps, priced{c.a, c.b, a})
		}
	}
	sort.SliceStable(ps, func(i, j int) bool { return ps[i].v.Total > ps[j].v.Total })
	used := map[string]bool{}
	for _, p := range ps {
		if len(fares) == n {
			break
		}
		if used[p.a] || used[p.b] {
			continue
		}
		fares = append(fares, fare{From: p.a, To: p.b, Rate: p.v})
		used[p.a], used[p.b] = true, true
	}
	return fares, len(sts), len(all)
}

// pointFares are a charge's dearest points for the truck, and how many
// points it has.
func pointFares(ds *tariffs.Dataset, ch *orct.Charge, t rates.Truck, day string, n int) ([]fare, int) {
	col := index(ch.Columns, "object")
	objs := map[string]float64{}
	all := map[string]bool{}
	for _, r := range ch.Rows {
		if col >= 0 {
			o, _ := r[col].(string)
			all[o] = true
		}
	}
	picks := map[string]pick{}
	for i, rk := range classRows(ds, ch, t) {
		r := ch.Rows[i]
		o := ""
		if col >= 0 {
			o, _ = r[col].(string)
		} else if len(ch.Objects) > 0 {
			o = ch.Objects[0]
		}
		if p, ok := picks[o]; o != "" && (!ok || p.better(pick{rk, rowAmount(ch, r)})) {
			picks[o] = pick{rk, rowAmount(ch, r)}
		}
	}
	for o, p := range picks {
		objs[o] = p.v
	}
	if col < 0 {
		for _, o := range ch.Objects {
			all[o] = true
		}
	}
	// The dearest by what each passage is priced at noon (a row's amount
	// alone may be another class's or another hour's).
	when := noon(ds, day)
	priced := map[string]amount{}
	keys := make([]string, 0, len(objs))
	for o := range objs {
		if a := calc(ds, t, []orct.Event{{Dataset: ds.ID, Object: o, Time: when}}); a.OK && a.Total > 0 {
			priced[o] = a
			keys = append(keys, o)
		}
	}
	sort.Slice(keys, func(i, j int) bool {
		if a, b := priced[keys[i]].Total, priced[keys[j]].Total; a != b {
			return a > b
		}
		return keys[i] < keys[j]
	})
	var out []fare
	for _, o := range keys {
		if len(out) == n {
			break
		}
		out = append(out, fare{From: o, Rate: priced[o]})
	}
	return out, len(all)
}

var durRe = regexp.MustCompile(`^P(\d+)([DWMY])$`)

// productName says an ISO 8601 period: "1 day", "30 days", "1 year".
func (l *Loc) productName(p string) string {
	m := durRe.FindStringSubmatch(p)
	if m == nil {
		return p
	}
	if m[1] == "1" {
		return l.T("per." + m[2] + "1")
	}
	return l.T("per."+m[2], "n", m[1])
}

// products are a period charge's products for the truck, cheapest first.
func products(ds *tariffs.Dataset, ch *orct.Charge, t rates.Truck) []fare {
	pc := index(ch.Columns, "product")
	if pc < 0 {
		return nil
	}
	best := map[string]pick{}
	var order []string
	rows := classRows(ds, ch, t)
	for i, r := range ch.Rows {
		rk, ok := rows[i]
		if !ok {
			continue
		}
		p, _ := r[pc].(string)
		q, seen := best[p]
		if !seen {
			order = append(order, p)
		}
		if !seen || q.better(pick{rk, rowAmount(ch, r)}) {
			best[p] = pick{rk, rowAmount(ch, r)}
		}
	}
	var out []fare
	for _, p := range order {
		out = append(out, fare{Period: p, Rate: amount{Total: best[p].v, Cur: ds.Doc.Header.Currency, OK: true}})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Rate.Total < out[j].Rate.Total })
	return out
}

// zeRule is a rule exempting zero-emission trucks, with its end.
func zeRule(ds *tariffs.Dataset) (until, note string, ok bool) {
	for _, r := range ds.Doc.Rules {
		if r.Kind != "exemption" {
			continue
		}
		c, _ := r.Params["criteria"].(map[string]any)
		cs := list(c["co2_class"])
		if len(cs) == 1 && cs[0] == "5" {
			u, _ := r.Params["until"].(string)
			n, _ := r.Params["note"].(string)
			return u, n, true
		}
	}
	return "", "", false
}

// zeTruck is the 40 t truck, zero-emission.
var zeTruck = rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5, CapacityKg: 25000}

// tableRow is a rate table row as text.
type tableRow struct {
	Cells []string
	CO2   bool
}

// rateTable is a charge's rows as text, the first max of them.
type rateTable struct {
	Name, Unit string
	CO2        bool
	Head       []string
	Rows       []tableRow
	Total      int
}

func (l *Loc) fullTable(ds *tariffs.Dataset, ch *orct.Charge, max int) rateTable {
	t := rateTable{Name: l.chargeName(ch), Unit: l.unitName(ch.Unit), CO2: ch.Component == "co2" || ch.Component == "carbon_price", Total: len(ch.Rows)}
	for _, c := range ch.Columns {
		h := l.T("colh." + c)
		if h == "colh."+c {
			h = strings.ReplaceAll(c, "_", " ")
		}
		if c == "amount" {
			h = ds.Doc.Header.Currency + " " + l.unitName(ch.Unit)
		}
		t.Head = append(t.Head, h)
	}
	for i, r := range ch.Rows {
		if i == max {
			break
		}
		var cells []string
		for j, c := range ch.Columns {
			v := r[j]
			var s string
			switch {
			case v == nil:
				s = "–"
			case c == "object" || c == "entry" || c == "exit":
				s = l.objectName(ds, fmt.Sprint(v))
			case c == "vehicle_class":
				s = l.className(ds, fmt.Sprint(v))
			case c == "time_class":
				if tc := ds.TimeClass(fmt.Sprint(v)); tc != nil && tc.Label != "" {
					s = tc.Label
				} else {
					s = fmt.Sprint(v)
				}
			case c == "product":
				s = l.productName(fmt.Sprint(v))
			case c == "amount":
				if f, ok := num(v); ok {
					s = l.num(f, 0, 6)
				} else {
					s = fmt.Sprint(v)
				}
			default:
				s = fmt.Sprint(v)
			}
			cells = append(cells, s)
		}
		t.Rows = append(t.Rows, tableRow{Cells: cells, CO2: t.CO2})
	}
	return t
}

// round4 keeps a per-km figure stable for comparing versions.
func round4(v float64) float64 { return math.Round(v*1e4) / 1e4 }

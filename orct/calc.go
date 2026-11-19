package orct

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"time"
)

// Implemented are the features this calculator implements (10.3).
var Implemented = map[string]bool{"type.distance": true, "type.section": true, "type.od": true, "type.point": true,
	"type.area": true, "type.period": true, "type.quantity": true, "time_classes": true, "calendars": true,
	"user_classes": true, "rounding": true, "volume": true, "dynamic": true, "rule.exemption": true,
	"rule.included_in": true, "rule.passage_group": true, "rule.factor": true, "rule.discount": true,
	"rule.minimum": true, "rule.cap": true}

const nullRank = 1000000

// MinorUnits are the decimal places of currencies other than 2.
var MinorUnits = map[string]int{"JPY": 0, "KRW": 0, "ISK": 0, "CLP": 0, "BHD": 3, "KWD": 3, "OMR": 3, "TND": 3, "JOD": 3}

// Usage is a vehicle's use of charge objects (clause 9).
type Usage struct {
	ORCTUsage   string                    `json:"orct_usage"`
	Vehicle     map[string]any            `json:"vehicle,omitempty"`
	Payment     []string                  `json:"payment,omitempty"`
	UserClasses map[string][]string       `json:"user_classes,omitempty"`
	PriorUses   map[string]map[string]int `json:"prior_uses,omitempty"`
	Events      []Event                   `json:"events,omitempty"`
	Quantities  []Quantity                `json:"quantities,omitempty"`
}

// Event is one use of an object.
type Event struct {
	Dataset  string         `json:"dataset"`
	Object   string         `json:"object"`
	Time     string         `json:"time"`
	Km       *Dec           `json:"km,omitempty"`
	Role     string         `json:"role,omitempty"`
	Overlays map[string]Dec `json:"overlays,omitempty"`
	// Ref is the caller's own reference, carried to the lines.
	Ref any `json:"-"`
}

// UnmarshalJSON reads km and overlays from JSON numbers.
func (e *Event) UnmarshalJSON(b []byte) error {
	var raw struct {
		Dataset  string                 `json:"dataset"`
		Object   string                 `json:"object"`
		Time     string                 `json:"time"`
		Km       json.Number            `json:"km"`
		Role     string                 `json:"role"`
		Overlays map[string]json.Number `json:"overlays"`
	}
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	*e = Event{Dataset: raw.Dataset, Object: raw.Object, Time: raw.Time, Role: raw.Role}
	if raw.Km != "" {
		d, err := numDec(raw.Km)
		if err != nil {
			return err
		}
		e.Km = &d
	}
	if raw.Overlays != nil {
		e.Overlays = map[string]Dec{}
		for k, v := range raw.Overlays {
			d, err := numDec(v)
			if err != nil {
				return err
			}
			e.Overlays[k] = d
		}
	}
	return nil
}

// numDec is a JSON number as the reference calculator reads it:
// Decimal(str(float(x))).
func numDec(n json.Number) (Dec, error) {
	f, err := n.Float64()
	if err != nil {
		return Dec{}, err
	}
	return FloatStr(f), nil
}

// FloatStr is Decimal(str(f)): the shortest decimal that reads back as f.
func FloatStr(f float64) Dec {
	return MustDec(strconv.FormatFloat(f, 'g', -1, 64))
}

// Quantity is a measured quantity (tonnes CO2, litres).
type Quantity struct {
	Dataset string `json:"dataset"`
	Object  string `json:"object"`
	Time    string `json:"time"`
	Unit    string `json:"unit"`
	Value   Dec    `json:"value"`
	Ref     any    `json:"-"`
}

// UnmarshalJSON reads value from a JSON number or string.
func (q *Quantity) UnmarshalJSON(b []byte) error {
	var raw struct {
		Dataset string          `json:"dataset"`
		Object  string          `json:"object"`
		Time    string          `json:"time"`
		Unit    string          `json:"unit"`
		Value   json.RawMessage `json:"value"`
	}
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	*q = Quantity{Dataset: raw.Dataset, Object: raw.Object, Time: raw.Time, Unit: raw.Unit}
	var s string
	if json.Unmarshal(raw.Value, &s) == nil {
		d, err := ParseDec(s)
		q.Value = d
		return err
	}
	f, err := json.Number(string(raw.Value)).Float64()
	if err != nil {
		return err
	}
	q.Value = DecFloat(f) // Decimal(float) is exact
	if f == float64(int64(f)) {
		q.Value = DecInt(int64(f))
	}
	return nil
}

// MarshalJSON writes value as a string.
func (q Quantity) MarshalJSON() ([]byte, error) {
	type alias struct {
		Dataset string `json:"dataset"`
		Object  string `json:"object"`
		Time    string `json:"time"`
		Unit    string `json:"unit"`
		Value   string `json:"value"`
	}
	return json.Marshal(alias{q.Dataset, q.Object, q.Time, q.Unit, q.Value.String()})
}

// Statement is the charge statement (9.2).
type Statement struct {
	ORCTStatement string  `json:"orct_statement"`
	Complete      bool    `json:"complete"`
	Lines         []*Line `json:"lines"`
	Totals        []Total `json:"totals"`
	Issues        []Issue `json:"issues"`
}

// Total is the total in one currency.
type Total struct {
	Currency string `json:"currency"`
	Amount   string `json:"amount"`
}

// Issue is something left unpriced or uncertain.
type Issue struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Dataset string `json:"dataset,omitempty"`
	Charge  string `json:"charge,omitempty"`
}

// Line is one priced use, or a rule's or rounding's adjustment.
type Line struct {
	Dataset        string          `json:"dataset"`
	DatasetVersion string          `json:"dataset_version,omitempty"`
	Charge         string          `json:"charge"`
	Component      string          `json:"component"`
	Objects        []string        `json:"objects"`
	Row            *int            `json:"row,omitempty"`
	Quantity       Dec             `json:"quantity"`
	Unit           string          `json:"unit"`
	Rate           string          `json:"rate,omitempty"`
	Amount         Dec             `json:"amount"`
	Currency       string          `json:"currency"`
	TaxBasis       string          `json:"tax_basis"`
	TaxRate        json.RawMessage `json:"tax_rate,omitempty"`
	Basis          string          `json:"basis,omitempty"`
	Sources        json.RawMessage `json:"sources,omitempty"`
	Notes          []string        `json:"notes,omitempty"`

	// Event is the use's event (for a period product, its start); Ref the
	// caller's reference from it.
	Event    *Event `json:"-"`
	Use      *Use   `json:"-"`
	Product  string `json:"-"`
	discount *Dec
}

// Use is what a row is selected for (6.10.3).
type Use struct {
	Object, Entry, Exit string
	Time                time.Time
	Product             string
	ordinal             *int
	ordinalUnk          *unknown
	trip                *[2]string
}

func (u *Use) get(col string) (string, bool) {
	switch col {
	case "object":
		return u.Object, u.Object != ""
	case "entry":
		return u.Entry, u.Entry != ""
	case "exit":
		return u.Exit, u.Exit != ""
	}
	return "", false
}

// Calc prices one usage with the given datasets.
type Calc struct {
	ds       map[string]*Dataset
	usage    *Usage
	vehicle  map[string]any
	lines    []*Line
	issues   []Issue
	complete bool

	quantities []*Quantity
	vclass     map[string]classOf
	held       map[string]bool
}

// Derive returns the vehicle with the values clause 6.6.1 derives where the
// usage does not give them, until none is left to derive: without a trailer,
// trailer_mass_kg and trailer_axles are 0 and the train values the motor
// vehicle's; trailer_axles is train_axles - axles; trailer follows from
// trailer_axles or trailer_mass_kg.
func Derive(vehicle map[string]any) map[string]any {
	v := map[string]any{}
	for k, x := range vehicle {
		v[k] = x
	}
	setDefault := func(k string, x any) bool {
		if _, ok := v[k]; ok {
			return false
		}
		v[k] = x
		return true
	}
	for {
		changed := false
		if t, ok := v["trailer"].(bool); ok && !t {
			changed = setDefault("trailer_mass_kg", float64(0)) || changed
			changed = setDefault("trailer_axles", float64(0)) || changed
			if m, ok := v["mass_kg"]; ok {
				changed = setDefault("train_mass_kg", m) || changed
			}
			if a, ok := v["axles"]; ok {
				changed = setDefault("train_axles", a) || changed
			}
		}
		if _, ok := v["trailer_axles"]; !ok {
			ta, ok1 := num(v["train_axles"])
			a, ok2 := num(v["axles"])
			if ok1 && ok2 {
				v["trailer_axles"] = ta - a
				changed = true
			}
		}
		if _, ok := v["trailer"]; !ok {
			ta, okA := num(v["trailer_axles"])
			tm, okM := num(v["trailer_mass_kg"])
			switch {
			case (okA && ta > 0) || (okM && tm > 0):
				v["trailer"], changed = true, true
			case okA && ta == 0:
				v["trailer"], changed = false, true
			}
		}
		if !changed {
			return v
		}
	}
}

// Calculate prices a usage (clause 8).
func Calculate(datasets []*Dataset, usage *Usage) *Statement {
	c := &Calc{ds: map[string]*Dataset{}, usage: usage, vehicle: Derive(usage.Vehicle), complete: true}
	for _, d := range datasets {
		c.ds[d.ID] = d
	}
	return c.run()
}

func (c *Calc) issue(code, msg, ds, charge string) {
	c.issues = append(c.issues, Issue{code, msg, ds, charge})
	c.complete = false
}

func (c *Calc) heldOf(ds *Dataset) map[string]bool {
	held := map[string]bool{}
	for _, u := range c.usage.UserClasses[ds.ID] {
		held[u] = true
	}
	pay := map[string]bool{}
	for _, p := range c.usage.Payment {
		pay[p] = true
	}
	for _, u := range ds.Doc.Users {
		for _, p := range u.Payment {
			if pay[p] {
				held[u.ID] = true
			}
		}
	}
	return held
}

// catch runs f and turns an unknown panic into its value.
func catch(f func()) (u *unknown) {
	defer func() {
		if r := recover(); r != nil {
			x, ok := r.(unknown)
			if !ok {
				panic(r)
			}
			u = &x
		}
	}()
	f()
	return nil
}

// ---------------------------------------------------------------- 6.10.3

type cand struct {
	prio  int
	ranks []int
	r     *row
	unk   *unknown
}

func keyLess(a, b cand) int {
	if a.prio != b.prio {
		if -a.prio < -b.prio {
			return -1
		}
		return 1
	}
	for i := range a.ranks {
		if i >= len(b.ranks) {
			return 1
		}
		if a.ranks[i] != b.ranks[i] {
			if a.ranks[i] < b.ranks[i] {
				return -1
			}
			return 1
		}
	}
	if len(a.ranks) < len(b.ranks) {
		return -1
	}
	return 0
}

// selectRow is the row for a use, or nil; it panics with unknown where an
// undecided row would rank at or above the best decided one, or the best
// rows tie.
func (c *Calc) selectRow(ds *Dataset, ch *Charge, use *Use) *row {
	var cands []cand
	for _, i := range ch.candidates(ds, use) {
		rw := &ch.rows[i]
		var ranks []int
		var unk *unknown
		ok := true
		for _, col := range ch.Columns {
			if col == "amount" || col == "priority" {
				continue
			}
			v := rw.vals[col]
			if v == nil {
				ranks = append(ranks, nullRank)
				continue
			}
			rank, found := 0, false
			switch col {
			case "object", "entry", "exit":
				s, _ := v.(string)
				id, okU := use.get(col)
				if okU {
					rank, found = ds.Ancestors(id)[s]
				}
			case "vehicle_class":
				s, _ := v.(string)
				cur := c.vclass[ds.setOf[s]]
				if cur.unk != nil {
					if unk == nil {
						unk = cur.unk
					}
					rank, found = 0, true
				} else {
					seen, id := 0, cur.id
					for id != "" {
						if id == s {
							rank, found = seen, true
							break
						}
						cl := ds.classes[id]
						if cl == nil {
							break
						}
						id, seen = cl.Fallback, seen+1
					}
				}
			case "time_class":
				s, _ := v.(string)
				var in bool
				if u := catch(func() { in = ds.inTimeClass(s, use.Time) }); u != nil {
					if unk == nil {
						unk = u
					}
					rank, found = 0, true
				} else if in {
					rank, found = 0, true
				}
			case "user_class":
				s, _ := v.(string)
				if c.held[s] {
					rank, found = 0, true
				}
			case "product":
				s, _ := v.(string)
				if s == use.Product {
					rank, found = 0, true
				}
			case "volume":
				f, isNum := v.(float64)
				switch {
				case use.ordinalUnk != nil:
					if unk == nil {
						unk = use.ordinalUnk
					}
					rank, found = 0, true
				case use.ordinal == nil || !isNum || f != float64(int(f)) || int(f) > *use.ordinal:
				default:
					rank, found = *use.ordinal-int(f), true
				}
			}
			if !found {
				ok = false
				break
			}
			ranks = append(ranks, rank)
		}
		if ok {
			cands = append(cands, cand{rw.prio, ranks, rw, unk})
		}
	}
	var known []cand
	for _, cd := range cands {
		if cd.unk == nil {
			known = append(known, cd)
		}
	}
	sort.SliceStable(known, func(i, j int) bool { return keyLess(known[i], known[j]) < 0 })
	for _, cd := range cands {
		if cd.unk != nil && (len(known) == 0 || keyLess(cd, known[0]) <= 0) {
			panic(*cd.unk)
		}
	}
	if len(known) == 0 {
		return nil
	}
	var top []cand
	for _, cd := range known {
		if keyLess(cd, known[0]) == 0 {
			top = append(top, cd)
		}
	}
	if len(top) > 1 {
		seen := map[string]bool{}
		for _, cd := range top {
			k := ""
			for _, col := range ch.Columns {
				if col == "user_class" || col == "amount" {
					continue
				}
				b, _ := json.Marshal(cd.r.vals[col])
				k += col + "=" + string(b) + ";"
			}
			seen[k] = true
		}
		if len(seen) > 1 {
			var ns []string
			for _, cd := range top {
				ns = append(ns, strconv.Itoa(cd.r.n))
			}
			panic(unknown{fmt.Sprintf("rows %s tie", joinIDs(ns)), "ambiguous_rows"})
		}
	}
	pick := top[0]
	for _, cd := range top[1:] {
		if x := cd.r.amount.Cmp(pick.r.amount); x < 0 || (x == 0 && cd.r.n < pick.r.n) {
			pick = cd
		}
	}
	return pick.r
}

func (c *Calc) lookup(ds *Dataset, ch *Charge, use *Use) *row {
	r := c.selectRow(ds, ch, use)
	if r == nil && ch.Type == "od" && !ch.Directed {
		sw := *use
		sw.Entry, sw.Exit = use.Exit, use.Entry
		r = c.selectRow(ds, ch, &sw)
	}
	return r
}

// ---------------------------------------------------------------- 8.4

// use is one priced use of a charge, a day's group of area events, a
// period's set of days, or an undecided use.
type pricedUse struct {
	use    *Use
	q      Dec
	objs   []string
	event  *Event
	kind   string // "", "day", "period"
	day    time.Time
	days   []time.Time
	events []*Event
	unk    *unknown
	quant  *Quantity
}

func (c *Calc) chargeObjects(ch *Charge) map[string]bool {
	objs := map[string]bool{}
	for _, o := range ch.Objects {
		objs[o] = true
	}
	for _, r := range ch.rows {
		for _, k := range []string{"object", "entry", "exit"} {
			if s, ok := r.str(k); ok && s != "" {
				objs[s] = true
			}
		}
	}
	return objs
}

func (c *Calc) uses(ds *Dataset, ch *Charge, events []*Event) []*pricedUse {
	objs := c.chargeObjects(ch)
	var mine []*Event
	for _, e := range events {
		for a := range ds.Ancestors(e.Object) {
			if objs[a] {
				mine = append(mine, e)
				break
			}
		}
	}
	switch ch.Type {
	case "distance", "section", "point":
		var out []*pricedUse
		for _, e := range mine {
			q := DecInt(1)
			if ch.Type == "distance" {
				if e.Km == nil {
					out = append(out, &pricedUse{unk: &unknown{fmt.Sprintf("event on %s at %s has no km", e.Object, e.Time), "missing_km"}})
					continue
				}
				q = *e.Km
				if ch.Unit == "tkm" {
					basis := ch.MassBasis
					if basis == "" {
						basis = "train_mass_kg"
					}
					m, ok := num(c.vehicle[basis])
					if !ok {
						panic(unknown{"vehicle parameter " + basis + " is missing", "missing_parameter"})
					}
					capKg := m
					if ch.MassCapKg != nil && *ch.MassCapKg != 0 {
						capKg = *ch.MassCapKg
					}
					q = q.Mul(massDec(c.vehicle[basis], m, capKg)).Quo(DecInt(1000))
				}
			} else if ch.Type == "point" && ch.Unit == "t" {
				q = c.tonnes(ch)
			} else if ch.Type == "section" && ch.Unit == "km" {
				o := ds.objects[e.Object]
				if o == nil || o.LengthKm == nil {
					panic(unknown{"section " + e.Object + " has no official length", "unpriced"})
				}
				q = FloatStr(*o.LengthKm)
			}
			out = append(out, &pricedUse{use: &Use{Object: e.Object, Time: ds.local(e.Time)}, q: q, objs: []string{e.Object}, event: e})
		}
		return out
	case "od":
		return c.odUses(ds, ch, mine)
	case "area":
		if ch.Unit == "entry" {
			var out []*pricedUse
			for _, e := range mine {
				if e.Role == "entry" {
					out = append(out, &pricedUse{use: &Use{Object: e.Object, Time: ds.local(e.Time)}, q: DecInt(1), objs: []string{e.Object}, event: e})
				}
			}
			return out
		}
		byDay := map[string][]*Event{}
		var keys []string
		for _, e := range mine {
			d := isoDate(ds.local(e.Time))
			if _, ok := byDay[d]; !ok {
				keys = append(keys, d)
			}
			byDay[d] = append(byDay[d], e)
		}
		sort.Strings(keys)
		var out []*pricedUse
		for _, k := range keys {
			d, _ := time.Parse(time.DateOnly, k)
			out = append(out, &pricedUse{kind: "day", day: d, events: byDay[k]})
		}
		return out
	case "period":
		seen := map[string]bool{}
		var days []time.Time
		for _, e := range mine {
			t := ds.local(e.Time)
			if ch.DayBasis != "rolling" {
				t = time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
			}
			k := t.UTC().Format(time.RFC3339Nano)
			if !seen[k] {
				seen[k] = true
				days = append(days, t)
			}
		}
		sort.Slice(days, func(i, j int) bool { return days[i].Before(days[j]) })
		return []*pricedUse{{kind: "period", days: days, events: mine}}
	case "quantity":
		var out []*pricedUse
		for _, q := range c.quantities {
			if !objs[q.Object] || q.Unit != ch.Unit {
				continue
			}
			d := isoDate(ds.local(q.Time))
			if !(firstOr(ch.ValidFrom, "0000") <= d && d <= firstOr(ch.ValidTo, "9999-12-31")) {
				continue
			}
			ev := &Event{Dataset: q.Dataset, Object: q.Object, Time: q.Time, Ref: q.Ref}
			out = append(out, &pricedUse{use: &Use{Object: q.Object, Time: ds.local(q.Time)}, q: q.Value, objs: []string{q.Object}, event: ev, quant: q})
		}
		return out
	}
	return nil
}

// massDec is Decimal(min(mass, cap)) for the vehicle's mass value.
func massDec(raw any, m, capKg float64) Dec {
	v := m
	if capKg < m {
		v = capKg
	}
	if v == float64(int64(v)) {
		return DecInt(int64(v))
	}
	return DecFloat(v)
}

func firstOr(s, def string) string {
	if s == "" {
		return def
	}
	return s
}

// tonnes is a `t` charge's quantity: the mass parameter mass_basis in
// tonnes (8.4).
func (c *Calc) tonnes(ch *Charge) Dec {
	basis := ch.MassBasis
	if basis == "" {
		basis = "train_mass_kg"
	}
	m, ok := num(c.vehicle[basis])
	if !ok {
		panic(unknown{"vehicle parameter " + basis + " is missing", "missing_parameter"})
	}
	return massDec(c.vehicle[basis], m, m).Quo(DecInt(1000))
}

func (c *Calc) odUses(ds *Dataset, ch *Charge, events []*Event) []*pricedUse {
	evs := append([]*Event(nil), events...)
	sort.SliceStable(evs, func(i, j int) bool { return evs[i].Time < evs[j].Time })
	var trips [][]*Event
	var cur []*Event
	for _, e := range evs {
		if e.Role == "entry" && len(cur) > 0 {
			trips = append(trips, cur)
			cur = nil
		}
		cur = append(cur, e)
		if e.Role == "exit" {
			trips = append(trips, cur)
			cur = nil
		}
	}
	if len(cur) > 0 {
		trips = append(trips, cur)
	}
	var out []*pricedUse
	for _, trip := range trips {
		a, b := trip[0], trip[len(trip)-1]
		when, ev := a.Time, a
		if ch.TimeBasis == "exit" {
			when, ev = b.Time, b
		}
		t := [2]string{a.Time, b.Time}
		q := DecInt(1)
		if ch.Unit == "t" {
			q = c.tonnes(ch)
		}
		out = append(out, &pricedUse{use: &Use{Entry: a.Object, Exit: b.Object, Time: ds.local(when), trip: &t}, q: q,
			objs: []string{a.Object, b.Object}, event: ev})
	}
	return out
}

// ---------------------------------------------------------------- 8

func (c *Calc) run() *Statement {
	byDS := map[string][]*Event{}
	var order []string
	for i := range c.usage.Events {
		e := &c.usage.Events[i]
		if _, ok := byDS[e.Dataset]; !ok {
			order = append(order, e.Dataset)
		}
		byDS[e.Dataset] = append(byDS[e.Dataset], e)
	}
	for _, q := range c.usage.Quantities {
		if _, ok := byDS[q.Dataset]; !ok {
			order = append(order, q.Dataset)
			byDS[q.Dataset] = nil
		}
	}
	for _, id := range order {
		ds := c.ds[id]
		if ds == nil {
			c.issue("unknown_dataset", "dataset "+id+" not given", "", "")
			continue
		}
		c.dataset(ds, byDS[id])
	}
	return c.statement()
}

func (c *Calc) dataset(ds *Dataset, events []*Event) {
	doc := ds.Doc
	var missing []string
	for _, f := range doc.Header.RequiredFeatures {
		if !Implemented[f] {
			missing = append(missing, f)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		c.issue("unsupported_feature", joinIDs(missing), ds.ID, "")
	}
	var known []*Event
	var unknownObjs []string
	for _, e := range events {
		if ds.objects[e.Object] != nil {
			known = append(known, e)
		} else {
			unknownObjs = append(unknownObjs, e.Object)
		}
	}
	var quants []*Quantity
	for i := range c.usage.Quantities {
		q := &c.usage.Quantities[i]
		if q.Dataset != ds.ID {
			continue
		}
		if ds.objects[q.Object] != nil {
			quants = append(quants, q)
		} else {
			unknownObjs = append(unknownObjs, q.Object)
		}
	}
	for _, o := range unknownObjs {
		c.issue("unknown_object", "object "+o+" is not in the dataset", ds.ID, "")
	}
	inValidity := func(ts string) bool {
		d := isoDate(ds.local(ts))
		return doc.Header.ValidFrom <= d && d <= firstOr(doc.Header.ValidTo, "9999-12-31")
	}
	var valid []*Event
	for _, e := range known {
		if inValidity(e.Time) {
			valid = append(valid, e)
		}
	}
	c.quantities = nil
	for _, q := range quants {
		if inValidity(q.Time) {
			c.quantities = append(c.quantities, q)
		}
	}
	if out := len(known) - len(valid) + len(quants) - len(c.quantities); out > 0 {
		c.issue("outside_validity", fmt.Sprintf("%d events or quantities outside the dataset's validity", out), ds.ID, "")
	}
	liable := false
	if u := catch(func() { liable = meets(doc.Liable.Criteria, c.vehicle) }); u != nil {
		c.issue(u.code, u.msg, ds.ID, "")
		return
	}
	if !liable {
		return
	}
	c.vclass, c.held = ds.classify(c.vehicle), c.heldOf(ds)
	var lines []*Line
	used := map[string]bool{}
	for i := range doc.Charges {
		ch := &doc.Charges[i]
		var inForce []*Event
		for _, e := range valid {
			d := isoDate(ds.local(e.Time))
			if firstOr(ch.ValidFrom, "0000") <= d && d <= firstOr(ch.ValidTo, "9999-12-31") {
				inForce = append(inForce, e)
			}
		}
		var mine []*Line
		if u := catch(func() { mine = c.priceCharge(ds, ch, inForce, used) }); u != nil {
			c.issue(u.code, u.msg, ds.ID, ch.ID)
			used[ch.ID] = true
			continue
		}
		lines = append(lines, c.exempt(ds, ch, mine)...)
	}
	// 8.9: the coverage scopes the usage touches.
	touched := map[string]bool{"dataset": true}
	for _, e := range valid {
		for a := range ds.Ancestors(e.Object) {
			touched[a] = true
		}
	}
	for _, q := range c.quantities {
		for a := range ds.Ancestors(q.Object) {
			touched[a] = true
		}
	}
	for k := range used {
		touched[k] = true
	}
	for _, v := range c.vclass {
		if v.unk == nil && v.id != "" {
			touched[v.id] = true
		}
	}
	for k := range c.held {
		touched[k] = true
	}
	for _, l := range lines {
		if l.Row != nil {
			r := ds.charges[l.Charge].rows[*l.Row]
			for _, k := range []string{"vehicle_class", "time_class", "user_class"} {
				if s, ok := r.str(k); ok && s != "" {
					touched[s] = true
				}
			}
		}
	}
	for _, r := range doc.Rules {
		for _, a := range r.AppliesTo {
			if used[a] {
				touched[r.ID] = true
			}
		}
	}
	var scopes []string
	for s := range ds.partial {
		if touched[s] {
			scopes = append(scopes, s)
		}
	}
	sort.Strings(scopes)
	for _, s := range scopes {
		c.issue("partial_coverage", "coverage of "+s+" is not complete", ds.ID, "")
	}
	lines = c.applyRules(ds, lines)
	c.roundLines(ds, &lines)
	c.lines = append(c.lines, lines...)
}

func (c *Calc) lineDate(ds *Dataset, l *Line) string {
	t := l.Event.Time
	if len(t) > 10 && t[10] == 'T' {
		return isoDate(ds.local(t))
	}
	return t[:10]
}

func param(p map[string]any, k string) string {
	s, _ := p[k].(string)
	return s
}

func paramMap(p map[string]any, k string) map[string]any {
	m, _ := p[k].(map[string]any)
	if m == nil {
		return map[string]any{}
	}
	return m
}

func contains(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}

func (c *Calc) exempt(ds *Dataset, ch *Charge, lines []*Line) []*Line {
	for _, r := range ds.Doc.Rules {
		if r.Kind != "exemption" || !contains(r.AppliesTo, ch.ID) || len(lines) == 0 {
			continue
		}
		p := r.Params
		if uc := param(p, "user_class"); uc != "" && !c.held[uc] {
			continue
		}
		ok := false
		if u := catch(func() { ok = meets(paramMap(p, "criteria"), c.vehicle) }); u != nil {
			c.issue("missing_parameter", u.msg, ds.ID, ch.ID)
			continue
		}
		if !ok {
			continue
		}
		from, until := firstOr(param(p, "from"), "0000"), firstOr(param(p, "until"), "9999-12-31")
		var keep []*Line
		for _, l := range lines {
			d := c.lineDate(ds, l)
			if !(from <= d && d <= until) {
				keep = append(keep, l)
			}
		}
		lines = keep
	}
	return lines
}

func (c *Calc) line(ds *Dataset, ch *Charge, objs []string, r *row, q Dec, ev *Event) *Line {
	tax := ds.Doc.Tax
	if ch.Tax != nil {
		tax = *ch.Tax
	}
	n := r.n
	rate, _ := r.vals["amount"].(string)
	l := &Line{Dataset: ds.ID, Charge: ch.ID, Component: ch.Component, Objects: objs, Row: &n, Quantity: q, Unit: ch.Unit,
		Rate: rate, Amount: r.amount.Mul(q), Currency: ds.Doc.Header.Currency, TaxBasis: tax.Basis, Basis: ch.Basis,
		Sources: ch.Sources, Event: ev, DatasetVersion: ds.Doc.Header.Version}
	if rd := ch.Rounding; rd != nil && rd.Stage == "use" {
		l.Amount = quantize(l.Amount, rd.Increment, rd.Mode)
	}
	if len(tax.Rate) > 0 && string(tax.Rate) != "null" && string(tax.Rate) != `""` && string(tax.Rate) != "0" {
		l.TaxRate = tax.Rate
	}
	return l
}

func quantize(a Dec, inc, mode string) Dec { return a.Quantize(MustDec(inc), mode) }

func (c *Calc) priceCharge(ds *Dataset, ch *Charge, events []*Event, used map[string]bool) []*Line {
	var out []*Line
	uses := c.uses(ds, ch, events)
	if len(ch.Dynamic) > 0 {
		if len(uses) > 0 {
			used[ch.ID] = true
			url, _ := ch.Dynamic["url"].(string)
			c.issue("dynamic_tariff", "amounts are set in real time: "+url, ds.ID, ch.ID)
		}
		return nil
	}
	if contains(ch.Columns, "volume") {
		c.ordinals(ds, ch, uses)
	}
	unpriced := func(code, msg string) {
		if code != "unmatched" || firstOr(ch.Unmatched, "unpriced") == "unpriced" {
			if code == "unmatched" {
				code = "unpriced"
			}
			c.issue(code, msg, ds.ID, ch.ID)
		}
	}
	for _, u := range uses {
		used[ch.ID] = true
		if u.unk != nil {
			unpriced(u.unk.code, u.unk.msg)
			continue
		}
		switch u.kind {
		case "day":
			var found *row
			var fe *Event
			if x := catch(func() {
				for _, e := range u.events {
					r := c.lookup(ds, ch, &Use{Object: e.Object, Time: ds.local(e.Time)})
					if r != nil && (found == nil || r.amount.Cmp(found.amount) > 0) {
						found, fe = r, e
					}
				}
			}); x != nil {
				unpriced(x.code, isoDate(u.day)+": "+x.msg)
				continue
			}
			if found != nil {
				out = append(out, c.line(ds, ch, []string{fe.Object}, found, DecInt(1), fe))
			} else {
				unpriced("unmatched", "no row for "+isoDate(u.day))
			}
			continue
		case "period":
			var ls []*Line
			if x := catch(func() { ls = c.period(ds, ch, u.days, u.events) }); x != nil {
				unpriced(x.code, x.msg)
				continue
			}
			out = append(out, ls...)
			continue
		}
		var r *row
		if x := catch(func() { r = c.lookup(ds, ch, u.use) }); x != nil {
			unpriced(x.code, joinIDs(u.objs)+": "+x.msg)
			continue
		}
		if r == nil {
			unpriced("unmatched", "no row for "+joinIDs(u.objs))
			continue
		}
		l := c.line(ds, ch, u.objs, r, u.q, u.event)
		l.Use = u.use
		out = append(out, l)
	}
	return out
}

func (c *Calc) ordinals(ds *Dataset, ch *Charge, uses []*pricedUse) {
	var simple []*pricedUse
	for _, u := range uses {
		if u.unk == nil && u.kind == "" {
			simple = append(simple, u)
		}
	}
	if len(simple) == 0 || ch.Volume == nil {
		return
	}
	sort.SliceStable(simple, func(i, j int) bool { return simple[i].use.Time.Before(simple[j].use.Time) })
	per := ch.Volume.Per
	period := func(t time.Time) string {
		switch per {
		case "year":
			return t.Format("2006")
		case "month":
			return t.Format("2006-01")
		}
		return t.Format(time.DateOnly)
	}
	prior, hasPrior := c.usage.PriorUses[ds.ID][ch.ID]
	first, counts := period(simple[0].use.Time), map[string]int{}
	for _, u := range simple {
		p := period(u.use.Time)
		counts[p]++
		if p == first && !hasPrior {
			u.use.ordinalUnk = &unknown{"the usage does not give the prior uses of " + ch.ID, "missing_count"}
		} else {
			n := counts[p]
			if p == first {
				n += prior
			}
			u.use.ordinal = &n
		}
	}
}

var durationRe = regexp.MustCompile(`^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?$`)

// durationDays is a product's duration as years, months and days, or
// false when it isn't PnYnMnWnD.
func durationDays(p string) (int, int, int, bool) {
	m := durationRe.FindStringSubmatch(p)
	if m == nil || (m[1] == "" && m[2] == "" && m[3] == "" && m[4] == "") {
		return 0, 0, 0, false
	}
	n := func(s string) int { v, _ := strconv.Atoi(s); return v }
	return n(m[1]), n(m[2]), n(m[3])*7 + n(m[4]), true
}

// productEnd is the first instant a product bought at start no longer
// covers (8.4).
func productEnd(start time.Time, p string) time.Time {
	y, mo, d, _ := durationDays(p)
	months := int(start.Month()) - 1 + mo + 12*y
	year, month := start.Year()+months/12, months%12+1
	last := time.Date(year, time.Month(month)+1, 0, 0, 0, 0, 0, time.UTC).Day()
	day := start.Day()
	if day > last {
		day = last
	}
	return time.Date(year, time.Month(month), day+d, start.Hour(), start.Minute(), start.Second(), start.Nanosecond(), start.Location())
}

type buy struct {
	p     string
	r     *row
	start time.Time
}

type plan struct {
	cost  Dec
	count int
	order []int
	buys  []buy
}

func planLess(a, b plan) bool {
	if x := a.cost.Cmp(b.cost); x != 0 {
		return x < 0
	}
	if a.count != b.count {
		return a.count < b.count
	}
	for i := range a.order {
		if i >= len(b.order) {
			return false
		}
		if a.order[i] != b.order[i] {
			return a.order[i] < b.order[i]
		}
	}
	return len(a.order) < len(b.order)
}

func (c *Calc) period(ds *Dataset, ch *Charge, days []time.Time, events []*Event) []*Line {
	if len(days) == 0 {
		return nil
	}
	var products []string
	for _, r := range ch.rows {
		p, _ := r.str("product")
		if p == "" || contains(products, p) {
			continue
		}
		if _, _, _, ok := durationDays(p); !ok {
			c.issue("unsupported_product", "product "+p, ds.ID, ch.ID)
			continue
		}
		products = append(products, p)
	}
	obj := events[0].Object
	objSet := map[string]bool{}
	for _, e := range events {
		objSet[e.Object] = true
	}
	var objs []string
	for o := range objSet {
		objs = append(objs, o)
	}
	sort.Strings(objs)
	rolling := ch.DayBasis == "rolling"
	at := func(d time.Time) time.Time {
		if rolling {
			return d
		}
		return time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, ds.tz)
	}
	best := map[int]plan{len(days): {cost: Dec{}}}
	for i := len(days) - 1; i >= 0; i-- {
		var cands []plan
		for _, p := range products {
			r := c.lookup(ds, ch, &Use{Object: obj, Time: at(days[i]), Product: p})
			if r == nil {
				continue
			}
			var end time.Time
			if rolling {
				end = productEnd(days[i], p)
			} else {
				end = productEnd(time.Date(days[i].Year(), days[i].Month(), days[i].Day(), 0, 0, 0, 0, time.UTC), p)
			}
			j := len(days)
			for k := i; k < len(days); k++ {
				if !days[k].Before(end) {
					j = k
					break
				}
			}
			b, ok := best[j]
			if !ok {
				continue
			}
			cands = append(cands, plan{b.cost.Add(r.amount), b.count + 1, append([]int{r.n}, b.order...),
				append([]buy{{p, r, days[i]}}, b.buys...)})
		}
		if len(cands) > 0 {
			m := cands[0]
			for _, x := range cands[1:] {
				if planLess(x, m) {
					m = x
				}
			}
			best[i] = m
		}
	}
	b0, ok := best[0]
	if !ok {
		panic(unknown{"no product priced for " + isoDate(days[0]), "unpriced"})
	}
	var out []*Line
	for _, b := range b0.buys {
		ev := &Event{Dataset: ds.ID, Object: obj, Time: isoformat(at(b.start)), Ref: events[0].Ref}
		l := c.line(ds, ch, objs, b.r, DecInt(1), ev)
		l.Product = b.p
		out = append(out, l)
	}
	return out
}

// ---------------------------------------------------------------- 8.6

func (c *Calc) applyRules(ds *Dataset, lines []*Line) []*Line {
	order := []string{"included_in", "passage_group", "factor", "discount", "minimum", "cap"}
	for _, kind := range order {
		for i := range ds.Doc.Rules {
			r := &ds.Doc.Rules[i]
			if r.Kind != kind {
				continue
			}
			switch kind {
			case "included_in":
				lines = c.ruleIncludedIn(ds, r, lines)
			case "passage_group":
				c.rulePassageGroup(ds, r, lines)
			case "factor":
				c.ruleFactor(ds, r, lines)
			case "discount":
				c.ruleDiscount(ds, r, lines)
			case "minimum":
				lines = c.ruleMinimum(ds, r, lines)
			case "cap":
				lines = c.ruleCap(ds, r, lines)
			}
		}
		if kind == "discount" {
			for _, l := range lines {
				if l.discount != nil && l.discount.Sign() != 0 {
					pct := *l.discount
					if pct.Cmp(DecInt(100)) > 0 {
						pct = DecInt(100)
					}
					l.Amount = l.Amount.Sub(l.Amount.Mul(pct).Quo(DecInt(100)))
				}
				l.discount = nil
			}
		}
	}
	for _, r := range ds.Doc.Rules {
		if !contains(order, r.Kind) && r.Kind != "exemption" {
			c.issue("unsupported_rule", r.Kind, ds.ID, "")
		}
	}
	return lines
}

func (c *Calc) ruleIncludedIn(ds *Dataset, r *Rule, lines []*Line) []*Line {
	var trips [][2]time.Time
	for _, l := range lines {
		if l.Charge == param(r.Params, "charge") && l.Use != nil && l.Use.trip != nil {
			trips = append(trips, [2]time.Time{ds.local(l.Use.trip[0]), ds.local(l.Use.trip[1])})
		}
	}
	objs := map[string]bool{}
	for _, o := range strs(r.Params["objects"]) {
		objs[o] = true
	}
	var keep []*Line
	for _, l := range lines {
		if contains(r.AppliesTo, l.Charge) {
			hit := len(objs) == 0
			for _, o := range l.Objects {
				hit = hit || objs[o]
			}
			if hit {
				t := ds.local(l.Event.Time)
				in := false
				for _, tr := range trips {
					in = in || (!t.Before(tr[0]) && !t.After(tr[1]))
				}
				if in {
					continue
				}
			}
		}
		keep = append(keep, l)
	}
	return keep
}

func (c *Calc) rulePassageGroup(ds *Dataset, r *Rule, lines []*Line) {
	objs := map[string]bool{}
	for _, o := range strs(r.Params["objects"]) {
		objs[o] = true
	}
	mins, _ := num(r.Params["minutes"])
	span := time.Duration(mins * float64(time.Minute))
	pays := firstOr(param(r.Params, "pays"), "first")
	var group []*Line
	for _, l := range lines {
		if !contains(r.AppliesTo, l.Charge) || l.Amount.Sign() <= 0 {
			continue
		}
		for _, o := range l.Objects {
			if objs[o] {
				group = append(group, l)
				break
			}
		}
	}
	sort.SliceStable(group, func(i, j int) bool { return group[i].Event.Time < group[j].Event.Time })
	var run []*Line
	var start time.Time
	started := false
	closeRun := func() {
		if len(run) == 0 {
			return
		}
		keep := run[0]
		if pays != "first" {
			for _, x := range run[1:] {
				if x.Amount.Cmp(keep.Amount) > 0 {
					keep = x
				}
			}
		}
		for _, x := range run {
			if x != keep {
				x.Amount = Dec{}
				x.Notes = append(x.Notes, "passage group "+r.ID)
			}
		}
	}
	for _, l := range group {
		t := ds.local(l.Event.Time)
		if !started || t.Sub(start) >= span {
			closeRun()
			run, start, started = nil, t, true
		}
		run = append(run, l)
	}
	closeRun()
}

func (c *Calc) ruleFactor(ds *Dataset, r *Rule, lines []*Line) {
	f := MustDec(factorString(r.Params["factor"]))
	obj := param(r.Params, "object")
	for _, l := range lines {
		if !contains(r.AppliesTo, l.Charge) || (l.Unit != "km" && l.Unit != "tkm") || l.Event == nil {
			continue
		}
		okm, ok := l.Event.Overlays[obj]
		if !ok || okm.Sign() == 0 || l.Event.Km == nil {
			continue
		}
		share := okm.Quo(*l.Event.Km)
		l.Amount = l.Amount.Add(l.Amount.Mul(share).Mul(f.Sub(DecInt(1))))
		l.Notes = append(l.Notes, fmt.Sprintf("factor %s on %s km", factorString(r.Params["factor"]), okm.String()))
	}
}

func factorString(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case float64:
		return strconv.FormatFloat(x, 'g', -1, 64)
	}
	return "1"
}

func (c *Calc) ruleDiscount(ds *Dataset, r *Rule, lines []*Line) {
	p := r.Params
	any := false
	for _, l := range lines {
		any = any || contains(r.AppliesTo, l.Charge)
	}
	if !any {
		return
	}
	if crit := paramMap(p, "criteria"); len(crit) > 0 {
		ok := false
		if u := catch(func() { ok = meets(crit, c.vehicle) }); u != nil {
			c.issue("missing_parameter", u.msg, ds.ID, "")
			return
		}
		if !ok {
			return
		}
	}
	if pay := strs(p["payment"]); len(pay) > 0 {
		hit := false
		for _, x := range pay {
			hit = hit || contains(c.usage.Payment, x)
		}
		if !hit {
			return
		}
	}
	if uc := param(p, "user_class"); uc != "" && !c.held[uc] {
		return
	}
	pct := MustDec(factorString(p["percent"]))
	name := firstOr(param(p, "name"), r.ID)
	for _, l := range lines {
		if contains(r.AppliesTo, l.Charge) {
			cur := Dec{}
			if l.discount != nil {
				cur = *l.discount
			}
			d := cur.Add(pct)
			l.discount = &d
			l.Notes = append(l.Notes, fmt.Sprintf("discount %s %s%%", name, factorString(p["percent"])))
		}
	}
}

type periodGroup struct {
	key   string
	lines []*Line
}

func (c *Calc) periods(ds *Dataset, r *Rule, lines []*Line) []*periodGroup {
	per := param(r.Params, "per")
	var out []*periodGroup
	idx := map[string]*periodGroup{}
	for _, l := range lines {
		if !contains(r.AppliesTo, l.Charge) {
			continue
		}
		t := ds.local(l.Event.Time)
		key := "usage"
		switch per {
		case "day":
			key = isoDate(t)
		case "month":
			key = t.Format("2006-01")
		}
		g := idx[key]
		if g == nil {
			g = &periodGroup{key: key}
			idx[key] = g
			out = append(out, g)
		}
		g.lines = append(g.lines, l)
	}
	return out
}

func (c *Calc) adjustment(ds *Dataset, appliesTo []string, amount Dec, group []*Line, note string) *Line {
	charge := ""
	for _, a := range appliesTo {
		for _, l := range group {
			if l.Charge == a {
				charge = a
				break
			}
		}
		if charge != "" {
			break
		}
	}
	var s *Line
	for _, l := range group {
		if l.Charge == charge {
			s = l
			break
		}
	}
	return &Line{Dataset: s.Dataset, DatasetVersion: s.DatasetVersion, Currency: s.Currency, TaxBasis: s.TaxBasis, Basis: s.Basis,
		Sources: s.Sources, Charge: charge, Component: s.Component, Objects: []string{}, Quantity: DecInt(1), Unit: "rule",
		Amount: amount, Notes: []string{note}, Event: s.Event}
}

func sum(ls []*Line) Dec {
	t := Dec{}
	for _, l := range ls {
		t = t.Add(l.Amount)
	}
	return t
}

func (c *Calc) ruleMinimum(ds *Dataset, r *Rule, lines []*Line) []*Line {
	m := MustDec(factorString(r.Params["amount"]))
	for _, g := range c.periods(ds, r, lines) {
		if t := sum(g.lines); t.Cmp(m) < 0 {
			lines = append(lines, c.adjustment(ds, r.AppliesTo, m.Sub(t), g.lines, "minimum "+r.ID))
		}
	}
	return lines
}

func (c *Calc) ruleCap(ds *Dataset, r *Rule, lines []*Line) []*Line {
	tc := param(r.Params, "time_class")
	capAmt := MustDec(factorString(r.Params["amount"]))
	for _, g := range c.periods(ds, r, lines) {
		group := g.lines
		if tc != "" {
			var in []*Line
			if u := catch(func() {
				for _, l := range group {
					if ds.inTimeClass(tc, ds.local(l.Event.Time)) {
						in = append(in, l)
					}
				}
			}); u != nil {
				c.issue("unknown_time_class", u.msg, ds.ID, "")
				continue
			}
			group = in
		}
		if t := sum(group); len(group) > 0 && t.Cmp(capAmt) > 0 {
			lines = append(lines, c.adjustment(ds, r.AppliesTo, capAmt.Sub(t), group, "cap "+r.ID))
		}
	}
	return lines
}

// ---------------------------------------------------------------- 8.7

func (c *Calc) roundLines(ds *Dataset, lines *[]*Line) {
	for i := range ds.Doc.Charges {
		ch := &ds.Doc.Charges[i]
		rd := ch.Rounding
		if rd == nil || rd.Stage == "use" {
			continue
		}
		var mine []*Line
		for _, l := range *lines {
			if l.Charge == ch.ID {
				mine = append(mine, l)
			}
		}
		switch rd.Stage {
		case "line":
			for _, l := range mine {
				l.Amount = quantize(l.Amount, rd.Increment, rd.Mode)
			}
		case "charge":
			if len(mine) == 0 {
				continue
			}
			t := sum(mine)
			if diff := quantize(t, rd.Increment, rd.Mode).Sub(t); diff.Sign() != 0 {
				*lines = append(*lines, c.adjustment(ds, []string{ch.ID}, diff, mine, "rounding"))
			}
		}
	}
}

func (c *Calc) statement() *Statement {
	totals := map[string]Dec{}
	var curs []string
	for _, l := range c.lines {
		if _, ok := totals[l.Currency]; !ok {
			curs = append(curs, l.Currency)
		}
		totals[l.Currency] = totals[l.Currency].Add(l.Amount)
	}
	sort.Strings(curs)
	st := &Statement{ORCTStatement: "0.3", Complete: c.complete, Lines: c.lines, Issues: c.issues}
	if st.Lines == nil {
		st.Lines = []*Line{}
	}
	if st.Issues == nil {
		st.Issues = []Issue{}
	}
	st.Totals = []Total{}
	for _, cur := range curs {
		mu, ok := MinorUnits[cur]
		if !ok {
			mu = 2
		}
		inc := "1"
		if mu > 0 {
			inc = "0." + fmt.Sprintf("%0*d", mu, 1)
		}
		st.Totals = append(st.Totals, Total{cur, quantize(totals[cur], inc, "half_up").Plain()})
	}
	return st
}

// rowIndex finds the rows that can match a use by their object, entry and
// exit columns: a row whose value there is neither null nor an ancestor of
// the use's object can't match (6.10.3), so only the others are ranked.
type rowIndex struct {
	cols  []string         // of object, entry, exit: those the charge has
	byKey map[string][]int // the rows with all of them set, by value
	open  []int            // the rows with one of them null
}

func (ch *Charge) index() *rowIndex {
	ch.idxOnce.Do(func() { ch.idx = ch.buildIndex() })
	return ch.idx
}

func (ch *Charge) buildIndex() *rowIndex {
	ix := &rowIndex{byKey: map[string][]int{}}
	for _, c := range []string{"object", "entry", "exit"} {
		if contains(ch.Columns, c) {
			ix.cols = append(ix.cols, c)
		}
	}
	for i, r := range ch.rows {
		key, open := "", false
		for _, c := range ix.cols {
			s, _ := r.str(c)
			if s == "" {
				open = true
				break
			}
			key += s + "\x00"
		}
		if open || len(ix.cols) == 0 {
			ix.open = append(ix.open, i)
		} else {
			ix.byKey[key] = append(ix.byKey[key], i)
		}
	}
	return ix
}

// candidates are the indices of the rows that may match the use, in order.
func (ch *Charge) candidates(ds *Dataset, use *Use) []int {
	ix := ch.index()
	if len(ix.cols) == 0 {
		return ix.open
	}
	keys := []string{""}
	for _, c := range ix.cols {
		id, ok := use.get(c)
		if !ok {
			return ix.open
		}
		var next []string
		for a := range ds.Ancestors(id) {
			for _, k := range keys {
				next = append(next, k+a+"\x00")
			}
		}
		keys = next
	}
	out := append([]int(nil), ix.open...)
	for _, k := range keys {
		out = append(out, ix.byKey[k]...)
	}
	sort.Ints(out)
	return out
}

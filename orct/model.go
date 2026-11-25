// Package orct reads ORCT 0.3 datasets (Open Road Charging Tariffs) and
// prices usages with them as the specification's clause 8 says. It follows
// the reference calculator (tools/orct_calc.py in the ORCT repository)
// step by step, with the same decimal arithmetic, so the two give the same
// statement for the same usage.
package orct

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

// Document is an ORCT dataset as published (6.1). Each field is the member its JSON tag names;
// Header is the dataset member, and Liable, Sets, Times, Calendars,
// Users and Objects are liable_vehicles, vehicle_class_sets,
// time_classes, calendars, user_classes and charge_objects.
type Document struct {
	ORCT    string          `json:"orct"`
	Header  Header          `json:"dataset"`
	Sources json.RawMessage `json:"sources,omitempty"`
	Tax     Tax             `json:"tax"`
	Liable  struct {
		Description string         `json:"description,omitempty"`
		Criteria    map[string]any `json:"criteria"`
	} `json:"liable_vehicles"`
	Sets       []ClassSet      `json:"vehicle_class_sets"`
	Times      []TimeClass     `json:"time_classes,omitempty"`
	Calendars  []Calendar      `json:"calendars,omitempty"`
	Users      []UserClass     `json:"user_classes,omitempty"`
	Objects    []Object        `json:"charge_objects"`
	Charges    []Charge        `json:"charges"`
	Rules      []Rule          `json:"rules,omitempty"`
	Coverage   []Coverage      `json:"coverage"`
	NoCharge   *NoCharge       `json:"no_charge,omitempty"`
	Extensions json.RawMessage `json:"extensions,omitempty"`
}

// NoCharge states that the scheme's area levies no charge (6.13). Each field is the member its JSON tag names.
type NoCharge struct {
	Description string   `json:"description"`
	Sources     []string `json:"sources"`
}

// Header is the dataset member (6.2). Each field is the member its JSON tag names.
type Header struct {
	ID               string          `json:"id"`
	Version          string          `json:"version,omitempty"`
	Scheme           json.RawMessage `json:"scheme,omitempty"`
	Publisher        json.RawMessage `json:"publisher,omitempty"`
	Currency         string          `json:"currency"`
	Timezone         string          `json:"timezone"`
	ValidFrom        string          `json:"valid_from"`
	ValidTo          string          `json:"valid_to,omitempty"`
	RequiredFeatures []string        `json:"required_features,omitempty"`
	Method           json.RawMessage `json:"method,omitempty"`
	License          json.RawMessage `json:"license,omitempty"`
	DerivedFrom      json.RawMessage `json:"derived_from,omitempty"`
}

// Tax is how the amounts stand to VAT or a sales tax (6.4). Each field is the member its JSON tag names.
type Tax struct {
	Basis string          `json:"basis"`
	Name  string          `json:"name,omitempty"`
	Rate  json.RawMessage `json:"rate,omitempty"`
	Note  string          `json:"note,omitempty"`
}

// ClassSet is a vehicle class set (6.6.3). Each field is the member its JSON tag names.
type ClassSet struct {
	ID      string  `json:"id"`
	Name    string  `json:"name,omitempty"`
	Classes []Class `json:"classes"`
}

// Class is a vehicle class (6.6.2, 6.6.3). Each field is the member its JSON tag names.
type Class struct {
	ID       string         `json:"id"`
	Label    string         `json:"label,omitempty"`
	Criteria map[string]any `json:"criteria"`
	Fallback string         `json:"fallback,omitempty"`
}

// TimeClass is a time class (6.7). Each field is the member its JSON tag names.
type TimeClass struct {
	ID      string           `json:"id"`
	Label   string           `json:"label,omitempty"`
	Days    []map[string]any `json:"days,omitempty"`
	Times   [][2]string      `json:"times,omitempty"`
	Defined *bool            `json:"defined,omitempty"`
	Note    string           `json:"note,omitempty"`
}

// Calendar is an explicit list of dates (6.7). Each field is the member its JSON tag names.
type Calendar struct {
	ID       string   `json:"id"`
	Name     string   `json:"name,omitempty"`
	Dates    []string `json:"dates"`
	CoversTo string   `json:"covers_to"`
}

// UserClass is a user class (6.8). Each field is the member its JSON tag names.
type UserClass struct {
	ID      string   `json:"id"`
	Label   string   `json:"label,omitempty"`
	Payment []string `json:"payment,omitempty"`
}

// Object is a charge object (6.9). Each field is the member its JSON tag names.
type Object struct {
	ID           string          `json:"id"`
	Type         string          `json:"type"`
	Parents      []string        `json:"parents,omitempty"`
	Name         string          `json:"name,omitempty"`
	Names        json.RawMessage `json:"names,omitempty"`
	Code         string          `json:"code,omitempty"`
	Operator     string          `json:"operator,omitempty"`
	Road         string          `json:"road,omitempty"`
	Network      *Network        `json:"network,omitempty"`
	From         *Place          `json:"from,omitempty"`
	To           *Place          `json:"to,omitempty"`
	LengthKm     *float64        `json:"length_km,omitempty"`
	Location     *Location       `json:"location,omitempty"`
	Jurisdiction json.RawMessage `json:"jurisdiction,omitempty"`
	Note         string          `json:"note,omitempty"`
}

// Network describes a network object (6.9). Each field is the member its JSON tag names.
type Network struct {
	RoadTypes   []string `json:"road_types,omitempty"`
	Area        string   `json:"area,omitempty"`
	Description string   `json:"description,omitempty"`
}

// Place is a section's end (6.9). Each field is the member its JSON tag names.
type Place struct {
	Name     string   `json:"name,omitempty"`
	Geometry Geometry `json:"geometry"`
	Heading  *float64 `json:"heading,omitempty"`
}

// Location is where a toll charger detects an object's use (6.9). Each field is the member its JSON tag names.
type Location struct {
	Geometry   *Geometry       `json:"geometry,omitempty"`
	OpenLR     string          `json:"openlr,omitempty"`
	OSM        json.RawMessage `json:"osm,omitempty"`
	Heading    *float64        `json:"heading,omitempty"`
	MatchM     *float64        `json:"match_m,omitempty"`
	Headings   []*float64      `json:"headings,omitempty"`
	PointNames []string        `json:"point_names,omitempty"`
}

// Geometry is an RFC 7946 geometry. Each field is the member its JSON tag names.
type Geometry struct {
	Type        string          `json:"type"`
	Coordinates json.RawMessage `json:"coordinates"`
}

// Charge is a charge with its rate table (6.10). Each field is the member its JSON tag names.
type Charge struct {
	ID             string                `json:"id"`
	Name           string                `json:"name,omitempty"`
	Type           string                `json:"type"`
	Component      string                `json:"component"`
	ComponentLabel string                `json:"component_label,omitempty"`
	Unit           string                `json:"unit"`
	Columns        []string              `json:"columns"`
	Rows           [][]any               `json:"rows"`
	Objects        []string              `json:"objects,omitempty"`
	Sources        json.RawMessage       `json:"sources,omitempty"`
	Basis          string                `json:"basis,omitempty"`
	ValidFrom      string                `json:"valid_from,omitempty"`
	ValidTo        string                `json:"valid_to,omitempty"`
	Rounding       *Rounding             `json:"rounding,omitempty"`
	Dynamic        map[string]any        `json:"dynamic,omitempty"`
	Volume         *struct{ Per string } `json:"volume,omitempty"`
	Unmatched      string                `json:"unmatched,omitempty"`
	MassBasis      string                `json:"mass_basis,omitempty"`
	MassCapKg      *float64              `json:"mass_cap_kg,omitempty"`
	MassStepKg     *float64              `json:"mass_step_kg,omitempty"`
	TimeBasis      string                `json:"time_basis,omitempty"`
	Directed       bool                  `json:"directed,omitempty"`
	DayBasis       string                `json:"day_basis,omitempty"`
	Tax            *Tax                  `json:"tax,omitempty"`
	Method         json.RawMessage       `json:"method,omitempty"`

	rows    []row
	idx     *rowIndex
	idxOnce sync.Once
}

// Rounding is a charge's rounding (6.10.1). Each field is the member its JSON tag names.
type Rounding struct {
	Increment string `json:"increment"`
	Mode      string `json:"mode"`
	Stage     string `json:"stage"`
}

// Rule is a rule (6.11). Each field is the member its JSON tag names.
type Rule struct {
	ID        string         `json:"id"`
	Kind      string         `json:"kind"`
	AppliesTo []string       `json:"applies_to"`
	Params    map[string]any `json:"params"`
}

// Coverage is a coverage entry (6.12). Each field is the member its JSON tag names.
type Coverage struct {
	Scope  string `json:"scope"`
	Status string `json:"status"`
	Note   string `json:"note,omitempty"`
}

// row is one rate table row, by column.
type row struct {
	n      int
	vals   map[string]any // column -> value (nil for null)
	amount Dec
	prio   int
}

func (r row) str(col string) (string, bool) {
	v, ok := r.vals[col].(string)
	return v, ok
}

// Dataset is a document ready to price with.
type Dataset struct {
	// Doc is the document, and ID its dataset id.
	Doc     *Document
	ID      string
	tz      *time.Location
	objects map[string]*Object
	anc     map[string]map[string]int
	setOf   map[string]string
	classes map[string]*Class
	times   map[string]*TimeClass
	cals    map[string]*Calendar
	charges map[string]*Charge
	partial map[string]bool
}

// Load reads a document.
func Load(b []byte) (*Dataset, error) {
	var doc Document
	if err := json.Unmarshal(b, &doc); err != nil {
		return nil, err
	}
	return New(&doc)
}

// New prepares a document for pricing.
func New(doc *Document) (*Dataset, error) {
	tz, err := time.LoadLocation(doc.Header.Timezone)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", doc.Header.ID, err)
	}
	ds := &Dataset{Doc: doc, ID: doc.Header.ID, tz: tz, objects: map[string]*Object{}, anc: map[string]map[string]int{},
		setOf: map[string]string{}, classes: map[string]*Class{}, times: map[string]*TimeClass{}, cals: map[string]*Calendar{},
		charges: map[string]*Charge{}, partial: map[string]bool{}}
	if doc.NoCharge != nil && len(doc.Objects)+len(doc.Charges)+len(doc.Rules) > 0 {
		return nil, fmt.Errorf("%s: a dataset with no_charge has no charge objects, charges or rules", ds.ID)
	}
	for i := range doc.Objects {
		ds.objects[doc.Objects[i].ID] = &doc.Objects[i]
	}
	for i := range doc.Sets {
		for j := range doc.Sets[i].Classes {
			c := &doc.Sets[i].Classes[j]
			ds.setOf[c.ID] = doc.Sets[i].ID
			ds.classes[c.ID] = c
		}
	}
	for i := range doc.Times {
		ds.times[doc.Times[i].ID] = &doc.Times[i]
	}
	for i := range doc.Calendars {
		ds.cals[doc.Calendars[i].ID] = &doc.Calendars[i]
	}
	for i := range doc.Charges {
		ch := &doc.Charges[i]
		ds.charges[ch.ID] = ch
		ch.rows = make([]row, len(ch.Rows))
		for n, r := range ch.Rows {
			rw := row{n: n, vals: map[string]any{}}
			for k, c := range ch.Columns {
				if k < len(r) {
					rw.vals[c] = r[k]
				}
			}
			a, ok := rw.vals["amount"].(string)
			if !ok {
				return nil, fmt.Errorf("%s: charge %s row %d: amount is not a string", ds.ID, ch.ID, n)
			}
			if rw.amount, err = ParseDec(a); err != nil {
				return nil, fmt.Errorf("%s: charge %s row %d: %w", ds.ID, ch.ID, n, err)
			}
			if p, ok := rw.vals["priority"].(float64); ok {
				rw.prio = int(p)
			}
			ch.rows[n] = rw
		}
	}
	for _, c := range doc.Coverage {
		if c.Status != "complete" {
			ds.partial[c.Scope] = true
		}
	}
	for id := range ds.objects {
		ds.anc[id] = ds.ancestors(id)
	}
	return ds, nil
}

// TZ is the dataset's time zone.
func (ds *Dataset) TZ() *time.Location { return ds.tz }

// Object is the object with the id, or nil.
func (ds *Dataset) Object(id string) *Object { return ds.objects[id] }

// Charge is the charge with the id, or nil.
func (ds *Dataset) Charge(id string) *Charge { return ds.charges[id] }

// Partial says whether the coverage of a scope is not complete.
func (ds *Dataset) Partial(scope string) bool { return ds.partial[scope] }

// Ancestors is oid and every object above it, with the number of parent
// steps by the shortest path (6.9).
func (ds *Dataset) Ancestors(oid string) map[string]int {
	if a, ok := ds.anc[oid]; ok {
		return a
	}
	return ds.ancestors(oid) // an object the dataset doesn't have: itself only
}

func (ds *Dataset) ancestors(oid string) map[string]int {
	dist, frontier := map[string]int{oid: 0}, []string{oid}
	for len(frontier) > 0 {
		var next []string
		for _, o := range frontier {
			if ob := ds.objects[o]; ob != nil {
				for _, p := range ob.Parents {
					if _, ok := dist[p]; !ok {
						dist[p] = dist[o] + 1
						next = append(next, p)
					}
				}
			}
		}
		frontier = next
	}
	return dist
}

// Local is an RFC 3339 time in the dataset's time zone.
func (ds *Dataset) Local(ts string) (time.Time, error) {
	t, err := parseTime(ts)
	if err != nil {
		return time.Time{}, err
	}
	return t.In(ds.tz), nil
}

func (ds *Dataset) local(ts string) time.Time {
	t, err := ds.Local(ts)
	if err != nil {
		panic(unknown{"bad time " + ts + ": " + err.Error(), "missing_parameter"})
	}
	return t
}

func parseTime(ts string) (time.Time, error) {
	for _, l := range []string{time.RFC3339Nano, "2006-01-02T15:04Z07:00"} {
		if t, err := time.Parse(l, ts); err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("not an RFC 3339 time with an offset")
}

func isoDate(t time.Time) string { return t.Format(time.DateOnly) }

// isoformat writes a time as Python's isoformat does (seconds always,
// fractions when not zero).
func isoformat(t time.Time) string {
	if t.Nanosecond() != 0 {
		return t.Format("2006-01-02T15:04:05.000000-07:00")
	}
	return t.Format("2006-01-02T15:04:05-07:00")
}

// ---------------------------------------------------------------- 6.7

type tri int

const (
	no tri = iota
	yes
	undecided
)

func easter(y int) time.Time {
	a, b, c := y%19, y/100, y%100
	d, e := b/4, b%4
	f := (b + 8) / 25
	g := (b - f + 1) / 3
	h := (19*a + b - d - g + 15) % 30
	i, k := c/4, c%4
	l := (32 + 2*e + 2*i - h - k) % 7
	m := (a + 11*h + 22*l) / 451
	return time.Date(y, time.Month((h+l-7*m+114)/31), (h+l-7*m+114)%31+1, 0, 0, 0, 0, time.UTC)
}

func ints(v any) []int {
	l, _ := v.([]any)
	out := make([]int, 0, len(l))
	for _, x := range l {
		if f, ok := x.(float64); ok {
			out = append(out, int(f))
		}
	}
	return out
}

func strs(v any) []string {
	l, _ := v.([]any)
	out := make([]string, 0, len(l))
	for _, x := range l {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func pairs(v any) [][2]any {
	l, _ := v.([]any)
	out := make([][2]any, 0, len(l))
	for _, x := range l {
		if p, ok := x.([]any); ok && len(p) == 2 {
			out = append(out, [2]any{p[0], p[1]})
		}
	}
	return out
}

func has(m map[string]any, k string) bool { _, ok := m[k]; return ok }

// dayIn is the three-valued day selector test (6.7).
func (ds *Dataset) dayIn(sel map[string]any, d time.Time) tri {
	iso := d.Format(time.DateOnly)
	md := iso[5:]
	if has(sel, "weekdays") {
		wd := int(d.Weekday())
		if wd == 0 {
			wd = 7
		}
		found := false
		for _, x := range ints(sel["weekdays"]) {
			found = found || x == wd
		}
		if !found {
			return no
		}
	}
	if has(sel, "months") {
		found := false
		for _, x := range ints(sel["months"]) {
			found = found || x == int(d.Month())
		}
		if !found {
			return no
		}
	}
	result := yes
	if has(sel, "dates") || has(sel, "date_ranges") || has(sel, "easter") || has(sel, "calendars") {
		hit := false
		for _, x := range strs(sel["dates"]) {
			hit = hit || x == md || x == iso
		}
		for _, p := range pairs(sel["date_ranges"]) {
			a, _ := p[0].(string)
			b, _ := p[1].(string)
			if len(a) == 5 {
				if a <= b {
					hit = hit || (a <= md && md <= b)
				} else {
					hit = hit || md >= a || md <= b
				}
			} else {
				hit = hit || (a <= iso && iso <= b)
			}
		}
		for _, p := range pairs(sel["easter"]) {
			a, _ := p[0].(float64)
			b, _ := p[1].(float64)
			e := easter(d.Year())
			off := int(time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, time.UTC).Sub(e).Hours() / 24)
			hit = hit || (int(a) <= off && off <= int(b))
		}
		unk := false
		for _, cid := range strs(sel["calendars"]) {
			cal := ds.cals[cid]
			if cal == nil {
				unk = true
				continue
			}
			if iso > cal.CoversTo {
				unk = true
			} else {
				for _, x := range cal.Dates {
					hit = hit || x == iso
				}
			}
		}
		switch {
		case hit:
			result = yes
		case unk:
			result = undecided
		default:
			result = no
		}
	}
	ex, ok := sel["exclude"].(map[string]any)
	if result == no || !ok {
		return result
	}
	switch ds.dayIn(ex, d) {
	case yes:
		return no
	case undecided:
		return undecided
	}
	return result
}

func (ds *Dataset) daySelected(tc *TimeClass, d time.Time) bool {
	if len(tc.Days) == 0 {
		return true
	}
	und := false
	for _, s := range tc.Days {
		switch ds.dayIn(s, d) {
		case yes:
			return true
		case undecided:
			und = true
		}
	}
	if und {
		panic(unknown{fmt.Sprintf("time class %s needs a calendar past its covers_to for %s", tc.ID, isoDate(d)), "unknown_time_class"})
	}
	return false
}

// InTimeClass says whether the local time t is in the time class; it
// panics with unknown where the data does not decide.
func (ds *Dataset) inTimeClass(tid string, t time.Time) bool {
	tc := ds.times[tid]
	if tc == nil {
		panic(unknown{"time class " + tid + " is not in the dataset", "unknown_time_class"})
	}
	if tc.Defined != nil && !*tc.Defined {
		panic(unknown{"time class " + tid + " is not defined", "unknown_time_class"})
	}
	hm := t.Format("15:04")
	day := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	if len(tc.Times) == 0 {
		return ds.daySelected(tc, day)
	}
	for _, se := range tc.Times {
		start, end := se[0], se[1]
		if start < end {
			if start <= hm && hm < end && ds.daySelected(tc, day) {
				return true
			}
		} else {
			if hm >= start && ds.daySelected(tc, day) {
				return true
			}
			if hm < end && ds.daySelected(tc, day.AddDate(0, 0, -1)) {
				return true
			}
		}
	}
	return false
}

// ---------------------------------------------------------------- 6.6

// unknown is something the data or the usage does not decide (8.9).
type unknown struct {
	msg, code string
}

// Error gives the message.
func (u unknown) Error() string { return u.msg }

func num(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	case json.Number:
		f, err := x.Float64()
		return f, err == nil
	}
	return 0, false
}

func equal(a, b any) bool {
	if x, ok := num(a); ok {
		y, ok2 := num(b)
		return ok2 && x == y
	}
	if x, ok := a.(string); ok {
		y, ok2 := b.(string)
		return ok2 && x == y
	}
	if x, ok := a.(bool); ok {
		y, ok2 := b.(bool)
		return ok2 && x == y
	}
	return false
}

// meetsTri is the three-valued criteria test (6.6.2): yes, no, or
// undecided with the first missing parameter.
func meetsTri(criteria map[string]any, vehicle map[string]any) (tri, string) {
	keys := make([]string, 0, len(criteria))
	for k := range criteria {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	missing := ""
	for _, param := range keys {
		cond := criteria[param]
		if param == "any_of" {
			alts, _ := cond.([]any)
			anyYes, allNo, firstMissing := false, true, ""
			for _, a := range alts {
				am, _ := a.(map[string]any)
				r, m := meetsTri(am, vehicle)
				anyYes = anyYes || r == yes
				allNo = allNo && r == no
				if r == undecided && firstMissing == "" {
					firstMissing = m
				}
			}
			if anyYes {
				continue
			}
			if allNo {
				return no, ""
			}
			if missing == "" {
				missing = firstMissing
			}
			continue
		}
		v, ok := vehicle[param]
		if !ok || v == nil {
			if missing == "" {
				missing = param
			}
			continue
		}
		switch c := cond.(type) {
		case map[string]any:
			x, okx := num(v)
			if !okx {
				return no, ""
			}
			if m, ok := num(c["min"]); ok && has(c, "min") && x < m {
				return no, ""
			}
			if m, ok := num(c["max"]); ok && has(c, "max") && x > m {
				return no, ""
			}
			if m, ok := num(c["gt"]); ok && has(c, "gt") && !(x > m) {
				return no, ""
			}
			if m, ok := num(c["lt"]); ok && has(c, "lt") && !(x < m) {
				return no, ""
			}
		case []any:
			found := false
			for _, y := range c {
				found = found || equal(v, y)
			}
			if !found {
				return no, ""
			}
		default:
			if !equal(v, cond) {
				return no, ""
			}
		}
	}
	if missing != "" {
		return undecided, missing
	}
	return yes, ""
}

func meets(criteria, vehicle map[string]any) bool {
	r, m := meetsTri(criteria, vehicle)
	if r == undecided {
		panic(unknown{"vehicle parameter " + m + " is missing", "missing_parameter"})
	}
	return r == yes
}

// classOf is the vehicle's class in each set: the first it meets (6.6.3).
type classOf struct {
	id  string
	unk *unknown
}

func (ds *Dataset) classify(vehicle map[string]any) map[string]classOf {
	out := map[string]classOf{}
	for _, s := range ds.Doc.Sets {
		func() {
			defer func() {
				if r := recover(); r != nil {
					u, ok := r.(unknown)
					if !ok {
						panic(r)
					}
					out[s.ID] = classOf{unk: &u}
				}
			}()
			out[s.ID] = classOf{}
			for _, c := range s.Classes {
				if meets(c.Criteria, vehicle) {
					out[s.ID] = classOf{id: c.ID}
					return
				}
			}
		}()
	}
	return out
}

func joinIDs(ids []string) string { return "[" + strings.Join(ids, ", ") + "]" }

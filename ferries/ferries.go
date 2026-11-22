// Package ferries knows truck ferry crossings and the CO2e their ships
// report under the EU MRV regulation, so a crossing's emissions can come
// from its own ships instead of a default factor.
//
// MRV reports each ro-pax ship's CO2e assigned to freight and its freight
// transport work in tonne-nautical miles, where the freight mass includes
// the vehicles (Implementing Regulation (EU) 2016/1928; the method
// Scandlines and Stena Line use for their own freight figures). A truck's
// share is therefore intensity x (vehicle + cargo mass) x distance.
package ferries

import (
	"embed"
	"encoding/json"
	"fmt"
	"math"
	"path"
	"sort"
	"strings"
	"time"
)

//go:embed data/*.json
var files embed.FS

// Point is a place.
type Point struct {
	Name string  `json:"name"`
	Lat  float64 `json:"lat"`
	Lon  float64 `json:"lon"`
	// Country is the port's state (ISO 3166-1 alpha-2), for the share
	// of a voyage's emissions under the EU ETS.
	Country string `json:"country,omitempty"`
	// Region is the UK nation of a UK port (ISO 3166-2: GB-NIR, GB-SCT),
	// for the UK ETS's share and its Scottish ferry services.
	Region string `json:"region,omitempty"`
}

// Ship is a ship on a crossing.
type Ship struct {
	IMO  string `json:"imo,omitempty"`
	Name string `json:"name"`
	// Since is the year the ship entered service, where its operator
	// says: a ship in service in a year whose EU MRV report doesn't list
	// it is under 5,000 GT.
	Since int `json:"since,omitempty"`
}

// Exemption is a derogation from surrendering allowances for a
// crossing's voyages, in force from From to Until (ISO dates).
type Exemption struct {
	From  string `json:"from"`
	Until string `json:"until"`
	Law   string `json:"law"`
	URL   string `json:"url"`
}

// Source is where a crossing's ships come from.
type Source struct {
	Title string `json:"title"`
	URL   string `json:"url"`
}

// Crossing is a ferry route and its ships.
type Crossing struct {
	ID        string  `json:"id"`
	Name      string  `json:"name"`
	Operator  string  `json:"operator"`
	Terminals []Point `json:"terminals"`
	Ships     []Ship  `json:"ships"`
	NotInMRV  string  `json:"not_in_mrv,omitempty"`
	Source    Source  `json:"source"`
	// Exemptions are derogations for the crossing's voyages.
	Exemptions []Exemption `json:"exemptions,omitempty"`
}

// MRVShip is one ship's yearly freight figures.
type MRVShip struct {
	IMO            string  `json:"imo"`
	Name           string  `json:"name"`
	FreightCO2T    float64 `json:"freight_co2_t"`
	FreightWorkTNm float64 `json:"freight_work_t_nm"`
	GPerTNm        float64 `json:"g_per_t_nm"`
}

// MRVYear is one reporting period of the EU MRV publication.
type MRVYear struct {
	Source          string    `json:"source"`
	ReportingPeriod int       `json:"reporting_period"`
	Version         string    `json:"version"`
	Ships           []MRVShip `json:"ships"`
}

// Listed is a ship in an EU MRV report (passenger, ro-pax or ro-ro).
type Listed struct {
	IMO  string `json:"imo"`
	Name string `json:"name"`
	Type string `json:"type"`
}

// ListedYear is one MRV report's passenger, ro-pax and ro-ro ships: every
// such ship above 5,000 GT on voyages to, from or between EU/EEA ports
// that year (Regulation (EU) 2015/757, Art. 2(1)).
type ListedYear struct {
	ReportingPeriod int      `json:"reporting_period"`
	Version         string   `json:"version"`
	Ships           []Listed `json:"ships"`
}

// Data is the crossings and the MRV years.
type Data struct {
	Crossings []Crossing
	Years     []MRVYear    // oldest first
	Listed    []ListedYear // oldest first
	// Surcharges are the ferry lines' published ETS surcharges.
	Surcharges []ETSSurcharges
}

// Load reads the embedded data.
func Load() (Data, error) {
	var d Data
	ents, err := files.ReadDir("data")
	if err != nil {
		return d, err
	}
	// crossings.json (by hand, with sources) and crossings-*.json (built,
	// such as crossings-islands.json by tools/tables/ets_islands.py).
	for _, e := range ents {
		if e.Name() != "crossings.json" && !strings.HasPrefix(e.Name(), "crossings-") {
			continue
		}
		var cs struct {
			Crossings []Crossing `json:"crossings"`
		}
		b, err := files.ReadFile(path.Join("data", e.Name()))
		if err != nil {
			return d, err
		}
		if err := json.Unmarshal(b, &cs); err != nil {
			return d, fmt.Errorf("%s: %w", e.Name(), err)
		}
		d.Crossings = append(d.Crossings, cs.Crossings...)
	}
	if b, err := files.ReadFile("data/ets-surcharges.json"); err == nil {
		var s struct {
			Operators []ETSSurcharges `json:"operators"`
		}
		if err := json.Unmarshal(b, &s); err != nil {
			return d, fmt.Errorf("ets-surcharges.json: %w", err)
		}
		d.Surcharges = s.Operators
	}
	for _, e := range ents {
		if strings.HasPrefix(e.Name(), "mrv-ships-") {
			b, err := files.ReadFile(path.Join("data", e.Name()))
			if err != nil {
				return d, err
			}
			var y ListedYear
			if err := json.Unmarshal(b, &y); err != nil {
				return d, fmt.Errorf("%s: %w", e.Name(), err)
			}
			d.Listed = append(d.Listed, y)
			continue
		}
		if !strings.HasPrefix(e.Name(), "mrv-ropax-") {
			continue
		}
		b, err := files.ReadFile(path.Join("data", e.Name()))
		if err != nil {
			return d, err
		}
		var y MRVYear
		if err := json.Unmarshal(b, &y); err != nil {
			return d, fmt.Errorf("%s: %w", e.Name(), err)
		}
		d.Years = append(d.Years, y)
	}
	sort.Slice(d.Years, func(i, j int) bool { return d.Years[i].ReportingPeriod < d.Years[j].ReportingPeriod })
	sort.Slice(d.Listed, func(i, j int) bool { return d.Listed[i].ReportingPeriod < d.Listed[j].ReportingPeriod })
	return d, nil
}

// MatchKm is how close a route must pass to both terminals of a crossing.
const MatchKm = 3

// Detect finds the crossing a route uses: one whose terminals both lie
// within MatchKm of the route's [lon, lat] points. ok is false if none or
// more than one match.
func (d Data) Detect(route [][2]float64) (Crossing, bool) {
	var found []Crossing
	for _, c := range d.Crossings {
		all := len(c.Terminals) > 0
		for _, t := range c.Terminals {
			if !near(route, t) {
				all = false
				break
			}
		}
		if all {
			found = append(found, c)
		}
	}
	if len(found) != 1 {
		return Crossing{}, false
	}
	return found[0], true
}

// DetectAll finds every crossing a route uses (both terminals within
// MatchKm of its points), in the order the route reaches them.
func (d Data) DetectAll(route [][2]float64) []Crossing {
	type hit struct {
		c   Crossing
		pos int
	}
	var hits []hit
	for _, c := range d.Crossings {
		if len(c.Terminals) == 0 {
			continue
		}
		first, all := len(route), true
		for _, t := range c.Terminals {
			i := nearestWithin(route, t)
			if i < 0 {
				all = false
				break
			}
			first = min(first, i)
		}
		if all {
			hits = append(hits, hit{c, first})
		}
	}
	sort.SliceStable(hits, func(i, j int) bool { return hits[i].pos < hits[j].pos })
	out := make([]Crossing, len(hits))
	for i, h := range hits {
		out[i] = h.c
	}
	return out
}

// nearestWithin is the index of the route point nearest p, or -1 if none
// is within MatchKm.
func nearestWithin(route [][2]float64, p Point) int {
	best, bi := math.Inf(1), -1
	for i, q := range route {
		if d := km(q[1], q[0], p.Lat, p.Lon); d <= MatchKm && d < best {
			best, bi = d, i
		}
	}
	return bi
}

func near(route [][2]float64, p Point) bool {
	for _, q := range route {
		if km(q[1], q[0], p.Lat, p.Lon) <= MatchKm {
			return true
		}
	}
	return false
}

func km(lat1, lon1, lat2, lon2 float64) float64 {
	const r = 6371.0088
	rad := math.Pi / 180
	dLat, dLon := (lat2-lat1)*rad, (lon2-lon1)*rad
	h := math.Sin(dLat/2)*math.Sin(dLat/2) + math.Cos(lat1*rad)*math.Cos(lat2*rad)*math.Sin(dLon/2)*math.Sin(dLon/2)
	return 2 * r * math.Asin(math.Min(1, math.Sqrt(h)))
}

// Intensity is a crossing's freight CO2e per tonne-nautical mile from the
// latest MRV year before tripYear (a year's report is published the next
// year), weighted by each ship's freight transport work: the sum of their
// freight CO2e over the sum of their freight work.
type Intensity struct {
	GPerTNm float64
	Year    MRVYear
	Ships   []MRVShip // the crossing's ships found in that year
}

// Intensity returns the crossing's MRV intensity for a trip in tripYear.
func (d Data) Intensity(c Crossing, tripYear int) (Intensity, bool) {
	for i := len(d.Years) - 1; i >= 0; i-- {
		y := d.Years[i]
		if y.ReportingPeriod >= tripYear && i > 0 {
			continue
		}
		var in Intensity
		var co2, work float64
		for _, s := range c.Ships {
			for _, m := range y.Ships {
				if m.IMO == s.IMO && m.FreightWorkTNm > 0 {
					in.Ships = append(in.Ships, m)
					co2 += m.FreightCO2T
					work += m.FreightWorkTNm
				}
			}
		}
		if work == 0 {
			continue
		}
		in.GPerTNm, in.Year = co2*1e6/work, y
		return in, true
	}
	return Intensity{}, false
}

// NmPerKm converts kilometres to nautical miles.
const NmPerKm = 1 / 1.852

// ETS covers ships of this gross tonnage and above (Directive 2003/87/EC,
// Annex I, maritime transport).
const ETSMinGT = 5000

// eea are the states whose ports are under the jurisdiction of a Member
// State for the maritime EU ETS: the EU and the EEA EFTA states, which
// apply the Directive under the EEA Agreement.
var eea = map[string]bool{"AT": true, "BE": true, "BG": true, "HR": true, "CY": true, "CZ": true, "DK": true, "EE": true, "FI": true,
	"FR": true, "DE": true, "GR": true, "HU": true, "IE": true, "IT": true, "LV": true, "LT": true, "LU": true, "MT": true, "NL": true,
	"PL": true, "PT": true, "RO": true, "SK": true, "SI": true, "ES": true, "SE": true, "IS": true, "LI": true, "NO": true}

// Coverage is the share of a crossing's emissions shipping companies
// surrender allowances for (before the phase-in), and the law it rests on.
type Coverage struct {
	Share float64
	Basis string
	// Note says what the share can't tell (some ships under 5,000 GT).
	Note string
}

// DirectiveURL is the EU ETS Directive, consolidated.
const DirectiveURL = "https://eur-lex.europa.eu/eli/dir/2003/87/oj"

// UKETSStart is when the UK ETS covers domestic maritime voyages (The
// Greenhouse Gas Emissions Trading Scheme (Amendment) (Extension to
// Maritime Activities) Order 2026, SI 2026/392, art. 1).
var UKETSStart = time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)

// UKETSLaw names the UK ETS's maritime provisions.
const UKETSLaw = "Greenhouse Gas Emissions Trading Scheme Order 2020, Schedule 2A, as inserted by SI 2026/392"

// UKCoverage is the crossing's share of a voyage's emissions under the UK
// ETS on day, for a crossing between two UK ports (applies is false
// otherwise): from 1 July 2026, 100% of a domestic voyage and 50% of one
// between Northern Ireland and Great Britain (Schedule 2A, para 15(1));
// none on a ship that operates a Scottish ferry service, between points in
// Scotland (para 5(1)(k), (3)), or one under 5,000 GT (para 5(1)), which
// the EU MRV reports can't tell for a voyage within the UK.
func (d Data) UKCoverage(c Crossing, day time.Time) (cov Coverage, applies bool) {
	if len(c.Terminals) != 2 || c.Terminals[0].Country != "GB" || c.Terminals[1].Country != "GB" {
		return Coverage{}, false
	}
	a, b := c.Terminals[0].Region, c.Terminals[1].Region
	switch {
	case day.Before(UKETSStart):
		return Coverage{Basis: "the UK ETS covers maritime emissions from 1 July 2026 (SI 2026/392)"}, true
	case a == "GB-SCT" && b == "GB-SCT":
		return Coverage{Basis: "a Scottish ferry service, between points in Scotland, is outside the UK ETS (" + UKETSLaw + ", para 5(1)(k))"}, true
	case (a == "GB-NIR") != (b == "GB-NIR"):
		cov = Coverage{Share: 0.5, Basis: "50% of its emissions: a voyage between Northern Ireland and Great Britain (" + UKETSLaw + ", para 15(1)(a))"}
	default:
		cov = Coverage{Share: 1, Basis: "100% of its emissions: a voyage between UK ports (" + UKETSLaw + ", para 15(1)(b))"}
	}
	if len(c.Ships) == 0 {
		cov.Note = fmt.Sprintf("its ships aren't known here: a crossing on one under %d GT is outside the UK ETS", ETSMinGT)
	}
	return cov, true
}

// Coverage is the crossing's ETS coverage for a voyage on day: none on
// ships under 5,000 GT (Annex I) or under a derogation in force; 100%
// between two ports under the jurisdiction of a Member State (EU or EEA),
// 50% between one of them and a port outside (Art. 3ga(1)). ok is false
// when the terminals' countries aren't known.
func (d Data) Coverage(c Crossing, day time.Time) (Coverage, bool) {
	small, why := d.small(c)
	if small == len(c.Ships) && small > 0 {
		return Coverage{Basis: fmt.Sprintf("its ships are under %d GT, outside the EU ETS (Directive 2003/87/EC, Annex I): %s", ETSMinGT, why)}, true
	}
	cov, ok := c.portCoverage(day)
	switch {
	case small > 0:
		cov.Note = fmt.Sprintf("some of its ships are under %d GT (%s): a crossing on one of them is outside the EU ETS", ETSMinGT, why)
	case len(c.Ships) == 0 && cov.Share > 0:
		cov.Note = fmt.Sprintf("its ships aren't known here: a crossing on one under %d GT is outside the EU ETS", ETSMinGT)
	}
	return cov, ok
}

// small counts the crossing's ships known to be under 5,000 GT: in
// service in a year whose MRV report (which every ship above 5,000 GT on
// EU/EEA voyages files, Regulation (EU) 2015/757, Art. 2(1)) doesn't list
// them, by IMO number or, without one, by name.
func (d Data) small(c Crossing) (int, string) {
	n, years := 0, map[int]bool{}
	var names []string
	for _, s := range c.Ships {
		if s.Since == 0 {
			continue
		}
		absent := 0
		for _, y := range d.Listed {
			if y.ReportingPeriod < s.Since {
				continue
			}
			if !y.lists(s) {
				absent++
				years[y.ReportingPeriod] = true
			} else {
				absent = -1000
			}
		}
		if absent > 0 {
			n++
			names = append(names, fmt.Sprintf("%s, in service since %d", s.Name, s.Since))
		}
	}
	if n == 0 {
		return 0, ""
	}
	var ys []string
	for y := range years {
		ys = append(ys, fmt.Sprint(y))
	}
	sort.Strings(ys)
	return n, fmt.Sprintf("%s aren't in the EU MRV report for %s, which every ship above %d GT on EU/EEA voyages files (Regulation (EU) 2015/757, Art. 2(1))",
		strings.Join(names, "; "), strings.Join(ys, " and "), ETSMinGT)
}

// lists says whether the report lists the ship.
func (y ListedYear) lists(s Ship) bool {
	for _, l := range y.Ships {
		if s.IMO != "" && l.IMO == s.IMO || s.IMO == "" && normName(l.Name) == normName(s.Name) {
			return true
		}
	}
	return false
}

func normName(s string) string {
	r := strings.NewReplacer("Ø", "O", "Æ", "AE", "Å", "AA", "Ö", "O", "Õ", "O", "Ä", "A", "Ü", "U", "É", "E")
	return strings.Join(strings.Fields(r.Replace(strings.ToUpper(s))), " ")
}

func (c Crossing) portCoverage(day time.Time) (Coverage, bool) {
	d := day.Format(time.DateOnly)
	for _, e := range c.Exemptions {
		if e.From <= d && d <= e.Until {
			return Coverage{Basis: fmt.Sprintf("no allowances are surrendered for its voyages until %s (%s)", e.Until, e.Law)}, true
		}
	}
	in := 0
	for _, t := range c.Terminals {
		if t.Country == "" {
			return Coverage{}, false
		}
		if eea[t.Country] {
			in++
		}
	}
	switch {
	case in == len(c.Terminals):
		return Coverage{Share: 1, Basis: "100% of its emissions: a voyage between ports under the jurisdiction of Member States (Directive 2003/87/EC, Art. 3ga(1))"}, true
	case in > 0:
		return Coverage{Share: 0.5, Basis: "50% of its emissions: a voyage between a port under the jurisdiction of a Member State and one outside (Directive 2003/87/EC, Art. 3ga(1))"}, true
	}
	return Coverage{Basis: "its ports are outside the EU and the EEA"}, true
}

// ETSSurcharges are a ferry line's published EU ETS surcharges for
// freight, per metre of the vehicle's length (ets-surcharges.json, built
// by tools/tables/ferry_ets.py).
type ETSSurcharges struct {
	Operator string `json:"operator"`
	Unit     string `json:"unit"`
	// CommencedMetre: charged per commencing metre (the length rounded
	// up), with at least MinM metres.
	CommencedMetre bool         `json:"commenced_metre"`
	MinM           float64      `json:"min_m"`
	Source         Source       `json:"source"`
	Routes         []ETSRoute   `json:"routes"`
	Editions       []ETSEdition `json:"editions"`
	// PerRoute: an edition names only some routes, the others keep theirs.
	PerRoute bool `json:"per_route,omitempty"`
}

// ETSRoute is one of the operator's routes and the crossings it sails.
type ETSRoute struct {
	Name      string   `json:"name"`
	Crossings []string `json:"crossings"`
}

// ETSEdition is the surcharges in force from From to To (or, without To,
// until the next edition).
type ETSEdition struct {
	From       string             `json:"from"`
	To         string             `json:"to,omitempty"`
	EUAEurPerT float64            `json:"eua_eur_per_t,omitempty"`
	Basis      string             `json:"basis,omitempty"`
	Source     string             `json:"source"`
	Note       string             `json:"note,omitempty"`
	Rates      map[string]float64 `json:"rates"`
}

// Surcharge is the ETS surcharge on a crossing on a day.
type Surcharge struct {
	Operator, Route string
	EURPerM         float64
	CommencedMetre  bool
	MinM            float64
	Edition         ETSEdition
	Source          Source
}

// Metres is the length charged for a vehicle of length m.
func (s Surcharge) Metres(m float64) float64 {
	if s.CommencedMetre {
		m = math.Ceil(m - 1e-9)
	}
	return math.Max(m, s.MinM)
}

// ETSSurcharge is the surcharge an operator publishes for a crossing on a
// day, if any is in force.
func (d Data) ETSSurcharge(crossing string, day time.Time) (Surcharge, bool) {
	ds := day.Format(time.DateOnly)
	for _, o := range d.Surcharges {
		for _, r := range o.Routes {
			if !containsString(r.Crossings, crossing) {
				continue
			}
			var best *ETSEdition
			for i := range o.Editions {
				e := &o.Editions[i]
				if e.From > ds {
					continue
				}
				if _, ok := e.Rates[r.Name]; !ok && o.PerRoute {
					continue
				}
				if best == nil || e.From > best.From {
					best = e
				}
			}
			if best == nil || best.To != "" && best.To < ds {
				continue
			}
			rate, ok := best.Rates[r.Name]
			if !ok {
				continue
			}
			src := o.Source
			if best.Source != "" {
				src.URL = best.Source
			}
			return Surcharge{Operator: o.Operator, Route: r.Name, EURPerM: rate, CommencedMetre: o.CommencedMetre, MinM: o.MinM, Edition: *best, Source: src}, true
		}
	}
	return Surcharge{}, false
}

func containsString(ss []string, s string) bool {
	for _, x := range ss {
		if x == s {
			return true
		}
	}
	return false
}

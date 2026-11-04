// Package rates holds official per-km road toll rates, one JSON file per
// country and validity period in data/, embedded in the binary. Every
// file names the law and the pages its numbers come from.
//
// A toll is the sum of its components (infrastructure, air pollution,
// noise, CO2 ...). Each component is a table of rows; the first row that
// matches the truck gives that component's rate.
package rates

import (
	"embed"
	"encoding/json"
	"fmt"
	"path"
	"slices"
	"sort"
	"strings"
	"time"
)

//go:embed data/*.json
var files embed.FS

// Component names. CO2 is the carbon part of a toll.
const (
	Infrastructure   = "infrastructure"
	Toll             = "toll" // one rate with no legal split
	CO2              = "co2"
	Air              = "air"
	Noise            = "noise"
	AirNoise         = "air_noise"
	EnvZoneSurcharge = "env_zone_surcharge"
)

// Source is a document the rates come from.
type Source struct {
	Title string `json:"title"`
	URL   string `json:"url"`
}

// Row is one component rate for the trucks it matches. Zero or empty
// conditions match any truck; MaxKg and MaxAxles 0 mean no upper limit.
type Row struct {
	Component string `json:"component"`
	MinKg     int    `json:"min_kg,omitempty"`
	MaxKg     int    `json:"max_kg,omitempty"`
	MinAxles  int    `json:"min_axles,omitempty"`
	MaxAxles  int    `json:"max_axles,omitempty"`
	Euro      []int  `json:"euro,omitempty"`
	CO2Class  []int  `json:"co2_class,omitempty"`
	// Road is set where the rate depends on the road type (Motorway or
	// OtherRoad): the row applies only to km on that type.
	Road string `json:"road,omitempty"`
	// Area is set where the rate depends on whether the road is
	// suburban or interurban (Suburban or Interurban): the row applies to
	// that share of the km (Table.SuburbanShare).
	Area string  `json:"area,omitempty"`
	Rate float64 `json:"rate"` // currency per km, or per tonne-km in a PerTonneKm table
}

// Areas for rates that differ by suburban or interurban road.
const (
	Suburban   = "suburban"
	Interurban = "interurban"
)

// Road types for rates that differ by road.
const (
	Motorway  = "motorway"
	OtherRoad = "other"
)

// Exemption makes trucks of the given CO2 classes toll-free until a date.
type Exemption struct {
	CO2Class []int  `json:"co2_class"`
	Until    string `json:"until"` // inclusive, YYYY-MM-DD
	Note     string `json:"note"`
}

// Table is one country's toll for one validity period.
type Table struct {
	Country string `json:"country"` // ISO 3166-1 alpha-2
	// Region is set for a regional toll (ISO 3166-2, e.g. BE-VLG): the
	// table then applies to that region's km, not the country's.
	Region      string   `json:"region,omitempty"`
	Currency    string   `json:"currency"`
	ValidFrom   string   `json:"valid_from"`         // inclusive, YYYY-MM-DD
	ValidTo     string   `json:"valid_to,omitempty"` // inclusive; "" = until replaced
	Name        string   `json:"name"`
	Law         string   `json:"law"`
	Sources     []Source `json:"sources"`
	Vehicles    string   `json:"vehicles"`
	MinKg       int      `json:"min_kg"` // lighter trucks pay no toll
	TolledRoads string   `json:"tolled_roads"`
	// PerTonneKm tables charge their rates per tonne-km of the truck's
	// maximum mass, up to MaxChargeableKg (Switzerland's LSVA).
	PerTonneKm      bool `json:"per_tonne_km,omitempty"`
	MaxChargeableKg int  `json:"max_chargeable_kg,omitempty"`
	// MotorwayShare is the share of km priced at motorway rates when the
	// rates differ by road type and the request doesn't say (default 0).
	MotorwayShare float64 `json:"motorway_share,omitempty"`
	// SuburbanShare is the share of km on suburban roads, by road type
	// ("" for any), for rows with an Area, where the route doesn't tell.
	SuburbanShare    map[string]float64 `json:"suburban_share,omitempty"`
	EnvZoneSurcharge string             `json:"env_zone_surcharge,omitempty"`
	Exemptions       []Exemption        `json:"exemptions,omitempty"`
	Rows             []Row              `json:"rows"`
	// Sections are road sections with a fixed infrastructure charge per
	// passage instead of the per-km one (Austria's special toll sections).
	Sections *Sections `json:"sections,omitempty"`
	// Crossings marks a table of fixed-charge crossings (bridges) only:
	// its closed systems are priced wherever the route passes them, on top
	// of the countries' own tolls.
	Crossings bool `json:"crossings,omitempty"`
	// Closed are toll systems priced from entry to exit station
	// (Croatia's motorways).
	Closed []TollSystem `json:"closed_systems,omitempty"`
	// Surcharges raise a component's per-km rate on a stretch of road.
	Surcharges []Surcharge `json:"surcharges,omitempty"`
}

// TollSystem is a closed toll system: the price from the station where
// a truck enters to the one where it leaves, by vehicle group. An open
// toll station (a barrier on the road) is priced from itself to itself.
type TollSystem struct {
	Name string `json:"name"`
	Law  string `json:"law"`
	// Chain prices a trip that passes many stations as consecutive
	// published entry-exit pairs that together cover the most of it
	// (France); otherwise one ticket from the first to the last station.
	Chain    bool                          `json:"chain,omitempty"`
	Groups   []Group                       `json:"groups"`
	Stations []Station                     `json:"stations"`
	Prices   map[string]map[string]float64 `json:"prices"` // "entry|exit" -> group -> price
	// ETCPrices replace Prices for trucks paying by an electronic toll
	// device or agreement (Request.ETC), where the operator sets them.
	ETCPrices map[string]map[string]float64 `json:"etc_prices,omitempty"`
	// Discounts in percent of the price, added up over those that apply.
	Discounts []Discount `json:"discounts,omitempty"`
}

// Discount is a percentage off a toll system's price for the trucks it
// matches; ETC ones only for trucks paying electronically.
type Discount struct {
	Name     string  `json:"name"`
	ETC      bool    `json:"etc,omitempty"`
	Euro     []int   `json:"euro,omitempty"`
	CO2Class []int   `json:"co2_class,omitempty"`
	Percent  float64 `json:"percent"`
}

// Applies says whether the discount is for the truck.
func (d Discount) Applies(t Truck, etc bool) bool {
	if d.ETC && !etc {
		return false
	}
	if len(d.Euro) == 0 && len(d.CO2Class) == 0 {
		return true
	}
	return slices.Contains(d.Euro, t.Euro) || slices.Contains(d.CO2Class, t.CO2Class)
}

// Group is a vehicle group of a toll system; the first a truck matches
// is its group.
type Group struct {
	Name       string  `json:"name"`
	MinKg      int     `json:"min_kg,omitempty"`
	MinAxles   int     `json:"min_axles,omitempty"`
	MaxAxles   int     `json:"max_axles,omitempty"`
	MinLengthM float64 `json:"min_length_m,omitempty"` // more than this
	MaxLengthM float64 `json:"max_length_m,omitempty"` // up to this
}

// Station is a toll station: where a route passes one of its points (the
// motorway junction or the toll booths), it uses the station.
type Station struct {
	Name   string  `json:"name"`
	Points []Place `json:"points"`
}

// GroupOf is the truck's vehicle group, "" if none matches.
func (s TollSystem) GroupOf(t Truck) string {
	for _, g := range s.Groups {
		l := t.Length()
		if t.MaxMassKg >= g.MinKg && t.Axles >= g.MinAxles && (g.MaxAxles == 0 || t.Axles <= g.MaxAxles) &&
			l > g.MinLengthM && (g.MaxLengthM == 0 || l <= g.MaxLengthM) {
			return g.Name
		}
	}
	return ""
}

// Price is the price from entry to exit for a group, either way round,
// from ETCPrices for a truck paying electronically where it has one.
func (s TollSystem) Price(entry, exit, group string, etc bool) (float64, bool) {
	tables := []map[string]map[string]float64{s.Prices}
	if etc && s.ETCPrices != nil {
		tables = []map[string]map[string]float64{s.ETCPrices, s.Prices}
	}
	for _, tb := range tables {
		for _, k := range []string{entry + "|" + exit, exit + "|" + entry} {
			if p, ok := tb[k][group]; ok {
				return p, true
			}
		}
	}
	return 0, false
}

// Place is a point on a road.
type Place struct {
	Name string  `json:"name"`
	Lat  float64 `json:"lat"`
	Lon  float64 `json:"lon"`
}

// Sections lists the fixed-charge sections and the law they come from.
type Sections struct {
	Law          string    `json:"law"`
	TariffGroups string    `json:"tariff_groups"`
	List         []Section `json:"list"`
	// PerKm are charges per km of a section's official length (Km), on
	// top of its fixed charge: Slovenia's rail surcharge and external-cost
	// charge.
	PerKm []SectionPerKm `json:"per_km,omitempty"`
}

// SectionPerKm is a per-km charge on sections. Rates are keyed by
// TollClass and, as Key says, the truck's emission key (EmissionKey) and
// the section's Area ("class/emission/area"), or the section's Tier
// ("class/tier"). Sections with no rate for their key don't pay it.
type SectionPerKm struct {
	Component string             `json:"component"`
	Name      string             `json:"name"`
	Law       string             `json:"law"`
	Key       string             `json:"key"` // "class/emission/area" or "class/tier"
	Rates     map[string]float64 `json:"rates"`
}

// Rate is the charge's per-km rate on the section for the truck.
func (c SectionPerKm) Rate(t Truck, s Section) (float64, bool) {
	var k string
	switch c.Key {
	case "class/emission/area":
		k = TollClass(t) + "/" + EmissionKey(t) + "/" + s.Area
	case "class/tier":
		if s.Tier == "" {
			return 0, false
		}
		k = TollClass(t) + "/" + s.Tier
	default:
		return 0, false
	}
	v, ok := c.Rates[k]
	return v, ok
}

// TollClass is Slovenia's toll class by axles: R2 (2 axles), R3 (3), R4
// (more than 3).
func TollClass(t Truck) string {
	switch {
	case t.Axles <= 2:
		return "R2"
	case t.Axles == 3:
		return "R3"
	}
	return "R4"
}

// EmissionKey is "zev" for a zero-emission truck (CO2 class 5), else
// "euro0" ... "euro6".
func EmissionKey(t Truck) string {
	if t.CO2Class == 5 {
		return "zev"
	}
	return fmt.Sprintf("euro%d", t.Euro)
}

// Section is a road section from one place to another with a fixed
// infrastructure charge: per tariff group (E for CO2 class 5, A for the
// rest), for 2, 3 and 4+ axles, and optionally a night charge for 4+
// axles.
type Section struct {
	ID        string                `json:"id"`
	Road      string                `json:"road"`
	Name      string                `json:"name"`
	From      Place                 `json:"from"`
	To        Place                 `json:"to"`
	Tariff    map[string][3]float64 `json:"tariff,omitempty"`
	NightKat4 map[string]float64    `json:"night_kat4,omitempty"`
	// Km is the section's official length, where the law gives one.
	Km float64 `json:"km,omitempty"`
	// Area is suburban or interurban, for charges that differ by it.
	Area string `json:"area,omitempty"`
	// Tier picks the section's per-km surcharge rates, if any.
	Tier string `json:"tier,omitempty"`
	// Classes are Slovenia's charges per toll class (R2, R3, R4) in nine
	// columns: EURO 0-III, IV, V, EEV and VI with CO2 class 1, then EURO
	// VI with CO2 classes 2, 3, 4 and 5.
	Classes map[string][9]float64 `json:"classes,omitempty"`
}

// Amount is the section's charge for the truck, by day or at night.
func (s Section) Amount(t Truck, night bool) float64 {
	if s.Classes != nil {
		col := 0
		switch {
		case t.CO2Class == 5:
			col = 8
		case t.CO2Class >= 2 && t.Euro == 6:
			col = 3 + t.CO2Class
		case t.Euro == 6:
			col = 4
		case t.Euro == 5:
			col = 2 // EEV is counted as Euro V here
		case t.Euro == 4:
			col = 1
		}
		return s.Classes[TollClass(t)][col]
	}
	g := "A"
	if t.CO2Class == 5 {
		g = "E"
	}
	k := 2
	switch {
	case t.Axles <= 2:
		k = 0
	case t.Axles == 3:
		k = 1
	}
	if v, ok := s.NightKat4[g]; ok && night && k == 2 {
		return v
	}
	return s.Tariff[g][k]
}

// Surcharge raises Component's per-km rate by Factor on a stretch of
// road given as its junctions in order: the km between consecutive
// junctions a route passes count.
type Surcharge struct {
	ID        string  `json:"id"`
	Name      string  `json:"name"`
	Points    []Place `json:"points"`
	Component string  `json:"component"`
	Factor    float64 `json:"factor"`
	Law       string  `json:"law"`
}

// Truck is what a toll rate depends on.
type Truck struct {
	MaxMassKg int `json:"max_mass_kg"` // technically permissible maximum mass
	Axles     int `json:"axles"`
	Euro      int `json:"euro"`      // emission standard 0-6 (EEV counts as 5)
	CO2Class  int `json:"co2_class"` // EU CO2 emission class 1-5 (5 = zero-emission)
	// TareKg is the truck's own weight (with trailer), optional: ferries
	// report freight emissions per tonne of vehicle and cargo.
	TareKg int `json:"tare_kg,omitempty"`
	// LengthM is the vehicle's length with trailer, optional: bridge tolls
	// are priced by length (default DefaultLengthM).
	LengthM float64 `json:"length_m,omitempty"`
}

// DefaultLengthM is the length assumed when a truck's isn't given: a
// tractor with semi-trailer (EU maximum 16.50 m, Directive 96/53/EC).
const DefaultLengthM = 16.5

// Length is the truck's length, DefaultLengthM if not given.
func (t Truck) Length() float64 {
	if t.LengthM > 0 {
		return t.LengthM
	}
	return DefaultLengthM
}

// Validate checks a truck's fields.
func (t Truck) Validate() error {
	switch {
	case t.MaxMassKg <= 0:
		return fmt.Errorf("max_mass_kg must be > 0")
	case t.Axles < 2 || t.Axles > 10:
		return fmt.Errorf("axles must be 2-10")
	case t.Euro < 0 || t.Euro > 6:
		return fmt.Errorf("euro must be 0-6")
	case t.CO2Class < 1 || t.CO2Class > 5:
		return fmt.Errorf("co2_class must be 1-5")
	case t.TareKg < 0 || (t.TareKg > 0 && t.TareKg >= t.MaxMassKg):
		return fmt.Errorf("tare_kg must be >= 0 and below max_mass_kg")
	case t.LengthM < 0 || t.LengthM > 50:
		return fmt.Errorf("length_m must be 0-50")
	}
	return nil
}

func (r Row) matches(t Truck) bool {
	return t.MaxMassKg >= r.MinKg && (r.MaxKg == 0 || t.MaxMassKg <= r.MaxKg) &&
		t.Axles >= r.MinAxles && (r.MaxAxles == 0 || t.Axles <= r.MaxAxles) &&
		(len(r.Euro) == 0 || slices.Contains(r.Euro, t.Euro)) &&
		(len(r.CO2Class) == 0 || slices.Contains(r.CO2Class, t.CO2Class))
}

// Rate is a component's rate for a truck. In a PerTonneKm table,
// PerTonneKm is the published rate and Tonnes the chargeable weight.
type Rate struct {
	Component  string
	PerKm      float64
	PerTonneKm float64
	Tonnes     float64
	Area       string // Suburban or Interurban, for a share of the km
}

// Rates are the truck's rates for each component, in the table's row
// order, without the environmental zone surcharge. ok is false if the
// truck is lighter than the table's MinKg. An exemption on the date gives
// no rates and its note. For a table whose rates differ by road type,
// use RatesOn.
func (tb Table) Rates(t Truck, date time.Time) (rs []Rate, exemptNote string, ok bool) {
	return tb.RatesOn(t, date, "")
}

// Roads lists the road types the table's rates differ by, if any.
func (tb Table) Roads() []string {
	var out []string
	for _, r := range tb.Rows {
		if r.Road != "" && !slices.Contains(out, r.Road) {
			out = append(out, r.Road)
		}
	}
	return out
}

// RatesOn is Rates for km on one road type: rows for that road and rows
// for any road.
func (tb Table) RatesOn(t Truck, date time.Time, road string) (rs []Rate, exemptNote string, ok bool) {
	if t.MaxMassKg < tb.MinKg {
		return nil, "", false
	}
	for _, e := range tb.Exemptions {
		if slices.Contains(e.CO2Class, t.CO2Class) && !date.After(day(e.Until)) {
			return nil, e.Note, true
		}
	}
	seen := map[string]bool{}
	for _, r := range tb.Rows {
		if r.Component == EnvZoneSurcharge || seen[r.Component+"/"+r.Area] || !r.matches(t) || (r.Road != "" && r.Road != road) {
			continue
		}
		seen[r.Component+"/"+r.Area] = true
		if tb.PerTonneKm {
			kg := t.MaxMassKg
			if tb.MaxChargeableKg > 0 {
				kg = min(kg, tb.MaxChargeableKg)
			}
			tonnes := float64(kg) / 1000
			rs = append(rs, Rate{Component: r.Component, PerKm: r.Rate * tonnes, PerTonneKm: r.Rate, Tonnes: tonnes, Area: r.Area})
			continue
		}
		rs = append(rs, Rate{Component: r.Component, PerKm: r.Rate, Area: r.Area})
	}
	return rs, "", true
}

// EnvZoneRate is the truck's environmental zone surcharge per km, 0 if
// the table has none.
func (tb Table) EnvZoneRate(t Truck) float64 {
	for _, r := range tb.Rows {
		if r.Component == EnvZoneSurcharge && r.matches(t) {
			return r.Rate
		}
	}
	return 0
}

// Covers says whether the table is in force on the date.
func (tb Table) Covers(date time.Time) bool {
	return !date.Before(day(tb.ValidFrom)) && (tb.ValidTo == "" || !date.After(day(tb.ValidTo)))
}

func day(s string) time.Time {
	t, err := time.Parse(time.DateOnly, s)
	if err != nil {
		panic(fmt.Sprintf("rates: bad date %q", s)) // checked by Load
	}
	return t
}

// All loads every embedded table, sorted by country and date.
func All() ([]Table, error) {
	ents, err := files.ReadDir("data")
	if err != nil {
		return nil, err
	}
	var out []Table
	for _, e := range ents {
		b, err := files.ReadFile(path.Join("data", e.Name()))
		if err != nil {
			return nil, err
		}
		var tb Table
		if err := json.Unmarshal(b, &tb); err != nil {
			return nil, fmt.Errorf("%s: %w", e.Name(), err)
		}
		if err := tb.check(); err != nil {
			return nil, fmt.Errorf("%s: %w", e.Name(), err)
		}
		out = append(out, tb)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Area() != out[j].Area() {
			return out[i].Area() < out[j].Area()
		}
		return out[i].ValidFrom < out[j].ValidFrom
	})
	return out, nil
}

func (tb Table) check() error {
	if _, err := time.Parse(time.DateOnly, tb.ValidFrom); err != nil {
		return fmt.Errorf("bad valid_from %q", tb.ValidFrom)
	}
	if _, err := time.Parse(time.DateOnly, tb.ValidTo); tb.ValidTo != "" && err != nil {
		return fmt.Errorf("bad valid_to %q", tb.ValidTo)
	}
	for _, e := range tb.Exemptions {
		if _, err := time.Parse(time.DateOnly, e.Until); err != nil {
			return fmt.Errorf("bad exemption date %q", e.Until)
		}
	}
	if tb.Region != "" && !strings.HasPrefix(tb.Region, tb.Country+"-") {
		return fmt.Errorf("region %q is not in country %s", tb.Region, tb.Country)
	}
	if tb.Country == "" || tb.Currency == "" || len(tb.Sources) == 0 || (len(tb.Rows) == 0 && tb.Sections == nil && len(tb.Closed) == 0) {
		return fmt.Errorf("country, currency, sources and rows (or sections) are required")
	}
	if tb.MotorwayShare < 0 || tb.MotorwayShare > 1 {
		return fmt.Errorf("motorway_share must be 0-1")
	}
	if tb.Crossings && (len(tb.Rows) > 0 || len(tb.Closed) == 0) {
		return fmt.Errorf("a crossings table has closed systems and no rows")
	}
	for k, v := range tb.SuburbanShare {
		if v < 0 || v > 1 {
			return fmt.Errorf("suburban_share[%s] must be 0-1", k)
		}
	}
	for _, r := range tb.Rows {
		if r.Area != "" && r.Area != Suburban && r.Area != Interurban {
			return fmt.Errorf("bad area %q", r.Area)
		}
	}
	for _, r := range tb.Rows {
		if r.Rate < 0 {
			return fmt.Errorf("negative rate in %+v", r)
		}
	}
	return nil
}

// Area is what the table applies to: its region if it has one, else
// its country.
func (tb Table) Area() string {
	if tb.Region != "" {
		return tb.Region
	}
	return tb.Country
}

// Find is the table for the area (a country, or a region for regional
// tolls) on the date, if any.
func Find(tables []Table, area string, date time.Time) (Table, bool) {
	for _, tb := range tables {
		if !tb.Crossings && tb.Area() == area && tb.Covers(date) {
			return tb, true
		}
	}
	return Table{}, false
}

// Regional says whether the country's tolls are set by region: then its
// km must be split by region to be priced.
func Regional(tables []Table, country string) bool {
	for _, tb := range tables {
		if !tb.Crossings && tb.Country == country && tb.Region != "" {
			return true
		}
	}
	return false
}

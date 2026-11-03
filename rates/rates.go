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
	Component string  `json:"component"`
	MinKg     int     `json:"min_kg,omitempty"`
	MaxKg     int     `json:"max_kg,omitempty"`
	MinAxles  int     `json:"min_axles,omitempty"`
	MaxAxles  int     `json:"max_axles,omitempty"`
	Euro      []int   `json:"euro,omitempty"`
	CO2Class  []int   `json:"co2_class,omitempty"`
	Rate      float64 `json:"rate"` // currency per km
}

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
	Region           string      `json:"region,omitempty"`
	Currency         string      `json:"currency"`
	ValidFrom        string      `json:"valid_from"`         // inclusive, YYYY-MM-DD
	ValidTo          string      `json:"valid_to,omitempty"` // inclusive; "" = until replaced
	Name             string      `json:"name"`
	Law              string      `json:"law"`
	Sources          []Source    `json:"sources"`
	Vehicles         string      `json:"vehicles"`
	MinKg            int         `json:"min_kg"` // lighter trucks pay no toll
	TolledRoads      string      `json:"tolled_roads"`
	EnvZoneSurcharge string      `json:"env_zone_surcharge,omitempty"`
	Exemptions       []Exemption `json:"exemptions,omitempty"`
	Rows             []Row       `json:"rows"`
}

// Truck is what a toll rate depends on.
type Truck struct {
	MaxMassKg int `json:"max_mass_kg"` // technically permissible maximum mass
	Axles     int `json:"axles"`
	Euro      int `json:"euro"`      // emission standard 0-6 (EEV counts as 5)
	CO2Class  int `json:"co2_class"` // EU CO2 emission class 1-5 (5 = zero-emission)
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
	}
	return nil
}

func (r Row) matches(t Truck) bool {
	return t.MaxMassKg >= r.MinKg && (r.MaxKg == 0 || t.MaxMassKg <= r.MaxKg) &&
		t.Axles >= r.MinAxles && (r.MaxAxles == 0 || t.Axles <= r.MaxAxles) &&
		(len(r.Euro) == 0 || slices.Contains(r.Euro, t.Euro)) &&
		(len(r.CO2Class) == 0 || slices.Contains(r.CO2Class, t.CO2Class))
}

// Rate is a component's rate for a truck.
type Rate struct {
	Component string
	PerKm     float64
}

// Rates are the truck's rates for each component, in the table's row
// order, without the environmental zone surcharge. ok is false if the
// truck is lighter than the table's MinKg. An exemption on the date gives
// no rates and its note.
func (tb Table) Rates(t Truck, date time.Time) (rs []Rate, exemptNote string, ok bool) {
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
		if r.Component == EnvZoneSurcharge || seen[r.Component] || !r.matches(t) {
			continue
		}
		seen[r.Component] = true
		rs = append(rs, Rate{Component: r.Component, PerKm: r.Rate})
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
	if tb.Country == "" || tb.Currency == "" || len(tb.Sources) == 0 || len(tb.Rows) == 0 {
		return fmt.Errorf("country, currency, sources and rows are required")
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
		if tb.Area() == area && tb.Covers(date) {
			return tb, true
		}
	}
	return Table{}, false
}

// Regional says whether the country's tolls are set by region: then its
// km must be split by region to be priced.
func Regional(tables []Table, country string) bool {
	for _, tb := range tables {
		if tb.Country == country && tb.Region != "" {
			return true
		}
	}
	return false
}

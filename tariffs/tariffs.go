// Package tariffs holds the rate tables carbon-cost prices with, as ORCT
// 0.3 datasets (package orct), embedded from data/: each toll scheme,
// crossing, zone and national CO2 price on fuel, one dataset per version.
// The workflows build them from the official sources and convert them
// (tools/orct/convert.py); nothing else is read.
package tariffs

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"path"
	"sort"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/orct"
)

//go:embed data
var files embed.FS

// Extension is the carbon-cost extension member of a dataset.
const Extension = "io.github.majidkabir.carboncost"

// Kinds of dataset.
const (
	Toll      = "toll"      // a country's or region's tolls
	Crossings = "crossings" // bridges and tunnels, priced wherever a route passes them
	Zone      = "zone"      // a charge per day in a zone
	FuelCO2   = "fuel_co2"  // a national CO2 price on road fuel
)

// Dataset is one dataset with what carbon-cost looks it up by.
type Dataset struct {
	*orct.Dataset
	File      string // <cc>/<name>.orct.json, under data/
	Scheme    string // e.g. "no", "dk-bridges"
	Name      string
	Country   string
	Region    string
	Kind      string
	ValidFrom string
	ValidTo   string
	ext       map[string]json.RawMessage
}

// Area is the country, or the region for regional tolls.
func (d *Dataset) Area() string {
	if d.Region != "" {
		return d.Region
	}
	return d.Country
}

// Covers says whether the dataset is in force on the date.
func (d *Dataset) Covers(date time.Time) bool {
	day := date.Format(time.DateOnly)
	return d.ValidFrom <= day && (d.ValidTo == "" || day <= d.ValidTo)
}

// Ext reads a member of the carbon-cost extension into v, and says
// whether it is there.
func (d *Dataset) Ext(key string, v any) bool {
	raw, ok := d.ext[key]
	if !ok {
		return false
	}
	return json.Unmarshal(raw, v) == nil
}

// Method is the dataset's method: the law and how the table was made.
func (d *Dataset) Method() string {
	var s string
	json.Unmarshal(d.Doc.Header.Method, &s)
	return s
}

// Source is a source document.
type Source struct {
	// Title names the document (a law, a table, a dataset), and URL is
	// where it is published.
	Title string `json:"title"`
	URL   string `json:"url"`
}

// Sources are the dataset's sources.
func (d *Dataset) Sources() []Source {
	var ss []Source
	json.Unmarshal(d.Doc.Sources, &ss)
	return ss
}

// Set is every dataset.
type Set struct {
	// All are the datasets, sorted by area, scheme and first day.
	All  []*Dataset
	fsys fs.FS
	dir  string
}

// Summary is what a dataset is, for a list of them.
type Summary struct {
	// File is the dataset, <cc>/<name>.orct.json: GET /v1/rates/{cc}/{file}.
	File string `json:"file"`
	// ID is the dataset's ORCT id, Scheme its toll scheme's id (each
	// version of a scheme is a dataset) and Name the scheme's name.
	ID     string `json:"id"`
	Scheme string `json:"scheme"`
	Name   string `json:"name"`
	// Country (ISO 3166-1 alpha-2) and Region (ISO 3166-2, for regional
	// tolls) are where it charges.
	Country string `json:"country"`
	Region  string `json:"region,omitempty"`
	// Kind is toll, crossings, zone or fuel_co2.
	Kind string `json:"kind"`
	// ValidFrom and ValidTo are the days it is in force (no ValidTo: until
	// replaced).
	ValidFrom string `json:"valid_from"`
	ValidTo   string `json:"valid_to,omitempty"`
	// Method is the law and how the dataset was made from it.
	Method string `json:"method,omitempty"`
	// Sources are the documents it comes from.
	Sources []Source `json:"sources,omitempty"`
}

// Summaries list the datasets.
func (s *Set) Summaries() []Summary {
	out := make([]Summary, 0, len(s.All))
	for _, d := range s.All {
		out = append(out, Summary{File: d.File, ID: d.ID, Scheme: d.Scheme, Name: d.Name, Country: d.Country, Region: d.Region,
			Kind: d.Kind, ValidFrom: d.ValidFrom, ValidTo: d.ValidTo, Method: d.Method(), Sources: d.Sources()})
	}
	return out
}

// Raw is a dataset's document as published (File, e.g.
// "dk/dk-2026-01-01.orct.json"); false for no such dataset.
func (s *Set) Raw(file string) ([]byte, bool) {
	for _, d := range s.All {
		if d.File == file && s.fsys != nil {
			b, err := fs.ReadFile(s.fsys, path.Join(s.dir, file))
			return b, err == nil
		}
	}
	return nil, false
}

// Load reads the embedded datasets.
func Load() (*Set, error) { return LoadFS(files, "data") }

// LoadFS reads the datasets under dir (<cc>/<name>.orct.json).
func LoadFS(fsys fs.FS, dir string) (*Set, error) {
	s := &Set{fsys: fsys, dir: dir}
	err := fs.WalkDir(fsys, dir, func(p string, e fs.DirEntry, err error) error {
		if err != nil || e.IsDir() || !strings.HasSuffix(p, ".orct.json") {
			return err
		}
		b, err := fs.ReadFile(fsys, p)
		if err != nil {
			return err
		}
		d, err := Parse(b)
		if err != nil {
			return fmt.Errorf("%s: %w", p, err)
		}
		d.File = path.Join(path.Base(path.Dir(p)), path.Base(p))
		s.All = append(s.All, d)
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Slice(s.All, func(i, j int) bool {
		a, b := s.All[i], s.All[j]
		if a.Area() != b.Area() {
			return a.Area() < b.Area()
		}
		if a.Scheme != b.Scheme {
			return a.Scheme < b.Scheme
		}
		return a.ValidFrom < b.ValidFrom
	})
	return s, nil
}

// Parse reads one dataset.
func Parse(b []byte) (*Dataset, error) {
	ds, err := orct.Load(b)
	if err != nil {
		return nil, err
	}
	var scheme struct {
		ID, Name, Country, Region string
	}
	json.Unmarshal(ds.Doc.Header.Scheme, &scheme)
	d := &Dataset{Dataset: ds, Scheme: scheme.ID, Name: scheme.Name, Country: scheme.Country, Region: scheme.Region,
		ValidFrom: ds.Doc.Header.ValidFrom, ValidTo: ds.Doc.Header.ValidTo, Kind: Toll}
	var ext map[string]map[string]json.RawMessage
	json.Unmarshal(ds.Doc.Extensions, &ext)
	d.ext = ext[Extension]
	var cross bool
	switch {
	case d.Ext("crossings", &cross) && cross:
		d.Kind = Crossings
	case len(ds.Doc.Charges) > 0 && ds.Doc.Charges[0].Type == "area" && strings.HasPrefix(d.Scheme, "zone-"):
		d.Kind = Zone
	case len(ds.Doc.Charges) > 0 && ds.Doc.Charges[0].Type == "quantity":
		d.Kind = FuelCO2
	}
	return d, nil
}

// Find is the toll dataset of the area (a country, or a region where
// tolls are set by region) in force on the date.
func (s *Set) Find(area string, date time.Time) (*Dataset, bool) {
	for _, d := range s.All {
		if d.Kind == Toll && d.Area() == area && d.Covers(date) {
			return d, true
		}
	}
	return nil, false
}

// Version is the dataset of d's scheme in force on day (YYYY-MM-DD).
func (s *Set) Version(d *Dataset, day string) (*Dataset, bool) {
	for _, v := range s.All {
		if v.Scheme == d.Scheme && v.Kind == d.Kind && v.Area() == d.Area() && v.ValidFrom <= day && (v.ValidTo == "" || day <= v.ValidTo) {
			return v, true
		}
	}
	return nil, false
}

// First is the area's first toll dataset when it starts after the date:
// rates here only from a later day.
func (s *Set) First(area string, date time.Time) (*Dataset, bool) {
	day := date.Format(time.DateOnly)
	var first *Dataset
	for _, d := range s.All {
		if d.Kind == Toll && d.Area() == area && (first == nil || d.ValidFrom < first.ValidFrom) {
			first = d
		}
	}
	if first == nil || first.ValidFrom <= day {
		return nil, false
	}
	if since := ""; first.Ext("charged_from", &since) && day < since {
		return nil, false
	}
	return first, true
}

// Ended is the area's last toll dataset when none is in force on the date
// and that one ended before it: rates that ended with no successor here
// yet.
func (s *Set) Ended(area string, date time.Time) (*Dataset, bool) {
	if _, ok := s.Find(area, date); ok {
		return nil, false
	}
	day := date.Format(time.DateOnly)
	var last *Dataset
	for _, d := range s.All {
		if d.Kind == Toll && d.Area() == area && d.ValidTo != "" && d.ValidTo < day && (last == nil || d.ValidTo > last.ValidTo) {
			last = d
		}
	}
	return last, last != nil
}

// Ahead lists, for each scheme of the kind with no rates in force on the
// date and none that ended before it, its first rates: tables here that
// start after the date. A scheme whose first table says the charge
// itself began then (charged_from) is left out before that day.
func (s *Set) Ahead(kind string, date time.Time) []*Dataset {
	day := date.Format(time.DateOnly)
	first, before := map[string]*Dataset{}, map[string]bool{}
	for _, d := range s.All {
		if d.Kind != kind {
			continue
		}
		if d.ValidFrom <= day {
			before[d.Scheme] = true
		}
		if f := first[d.Scheme]; f == nil || d.ValidFrom < f.ValidFrom {
			first[d.Scheme] = d
		}
	}
	var out []*Dataset
	for sch, d := range first {
		if since := ""; before[sch] || d.Ext("charged_from", &since) && day < since {
			continue
		}
		out = append(out, d)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].File < out[j].File })
	return out
}

// Lapsed lists, for each scheme of the kind with no dataset in force on
// the date, its last dataset if that ended before the date: rates that
// ended with no successor here yet. (A scheme that really ends has a
// successor that says so: a dataset with no_charge.)
func (s *Set) Lapsed(kind string, date time.Time) []*Dataset {
	day := date.Format(time.DateOnly)
	last, inForce := map[string]*Dataset{}, map[string]bool{}
	for _, d := range s.All {
		if d.Kind != kind {
			continue
		}
		if d.Covers(date) {
			inForce[d.Scheme] = true
		}
		if d.ValidTo != "" && d.ValidTo < day {
			if l := last[d.Scheme]; l == nil || d.ValidTo > l.ValidTo {
				last[d.Scheme] = d
			}
		}
	}
	var out []*Dataset
	for sch, d := range last {
		if !inForce[sch] {
			out = append(out, d)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].File < out[j].File })
	return out
}

// Regional says whether the country's tolls are set by region.
func (s *Set) Regional(country string) bool {
	for _, d := range s.All {
		if d.Kind == Toll && d.Country == country && d.Region != "" {
			return true
		}
	}
	return false
}

// OfKind lists the datasets of a kind in force on the date.
func (s *Set) OfKind(kind string, date time.Time) []*Dataset {
	var out []*Dataset
	for _, d := range s.All {
		if d.Kind == kind && d.Covers(date) {
			out = append(out, d)
		}
	}
	return out
}

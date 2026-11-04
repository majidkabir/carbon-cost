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
)

//go:embed data/*.json
var files embed.FS

// Point is a place.
type Point struct {
	Name string  `json:"name"`
	Lat  float64 `json:"lat"`
	Lon  float64 `json:"lon"`
}

// Ship is a ship on a crossing.
type Ship struct {
	IMO  string `json:"imo"`
	Name string `json:"name"`
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

// Data is the crossings and the MRV years.
type Data struct {
	Crossings []Crossing
	Years     []MRVYear // oldest first
}

// Load reads the embedded data.
func Load() (Data, error) {
	var d Data
	var cs struct {
		Crossings []Crossing `json:"crossings"`
	}
	b, err := files.ReadFile("data/crossings.json")
	if err != nil {
		return d, err
	}
	if err := json.Unmarshal(b, &cs); err != nil {
		return d, fmt.Errorf("crossings.json: %w", err)
	}
	d.Crossings = cs.Crossings
	ents, err := files.ReadDir("data")
	if err != nil {
		return d, err
	}
	for _, e := range ents {
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

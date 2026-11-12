package rates

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"path"
	"regexp"
	"strings"
	"time"
)

// ZonePrefix starts the name of each area charge's file in data/.
const ZonePrefix = "zone-"

// Zone is an area charged per day a truck drives in it (London's
// Congestion Charge and Low Emission Zone): Charge once per day, for a
// truck of at least MinKg below the ExemptEuro emission standard (0: any),
// when it is in the zone in the charging hours.
type Zone struct {
	Country   string   `json:"country"`
	Currency  string   `json:"currency"`
	ValidFrom string   `json:"valid_from"`
	ValidTo   string   `json:"valid_to,omitempty"`
	Name      string   `json:"name"`
	Law       string   `json:"law"`
	Sources   []Source `json:"sources"`
	MinKg     int      `json:"min_kg"`
	Charge    float64  `json:"charge"` // per day
	// ExemptEuro: trucks meeting this Euro standard or a later one pay
	// nothing (0: none exempt).
	ExemptEuro int `json:"exempt_euro,omitempty"`
	// EuroCharges: lower charges for trucks meeting a Euro standard (the
	// highest MinEuro the truck meets), Charge for the rest.
	EuroCharges []EuroCharge `json:"euro_charges,omitempty"`
	// Hours the zone charges, from and to (HH:MM, both included), on
	// weekdays (Monday to Friday) and weekends; none: all day, every day.
	Weekdays []string `json:"weekdays,omitempty"`
	Weekends []string `json:"weekends,omitempty"`
	// NoCharge: days of the year (MM-DD, from and to, both included,
	// wrapping past the year's end) when the zone charges nothing.
	NoCharge []string `json:"no_charge,omitempty"`
	// Polygons: the zone's outer rings, [lon, lat] points; Holes: inner
	// rings cut out of them.
	Polygons [][][2]float64 `json:"polygons"`
	Holes    [][][2]float64 `json:"holes,omitempty"`
	OSM      string         `json:"osm_extract"`
	File     string         `json:"-"`
}

// EuroCharge is a zone's daily charge for trucks of MinEuro or later.
type EuroCharge struct {
	MinEuro int     `json:"min_euro"`
	Charge  float64 `json:"charge"`
}

// ChargeFor is the zone's daily charge for a truck of the Euro standard.
func (z Zone) ChargeFor(euro int) float64 {
	c, best := z.Charge, -1
	for _, e := range z.EuroCharges {
		if euro >= e.MinEuro && e.MinEuro > best {
			c, best = e.Charge, e.MinEuro
		}
	}
	return c
}

// Covers says whether the zone is in force on the day.
func (z Zone) Covers(d time.Time) bool {
	day := d.Format(time.DateOnly)
	return day >= z.ValidFrom && (z.ValidTo == "" || day <= z.ValidTo)
}

// Contains says whether the point [lon, lat] is in the zone.
func (z Zone) Contains(p [2]float64) bool {
	in := false
	for _, r := range z.Polygons {
		if inRing(r, p) {
			in = true
			break
		}
	}
	if !in {
		return false
	}
	for _, r := range z.Holes {
		if inRing(r, p) {
			return false
		}
	}
	return true
}

func inRing(r [][2]float64, p [2]float64) bool {
	in := false
	for i, j := 0, len(r)-1; i < len(r); j, i = i, i+1 {
		a, b := r[i], r[j]
		if (a[1] > p[1]) != (b[1] > p[1]) && p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0] {
			in = !in
		}
	}
	return in
}

// Charging says whether the zone charges at the local time t.
func (z Zone) Charging(t time.Time) bool {
	md := t.Format("01-02")
	if len(z.NoCharge) == 2 {
		a, b := z.NoCharge[0], z.NoCharge[1]
		if (a <= b && md >= a && md <= b) || (a > b && (md >= a || md <= b)) {
			return false
		}
	}
	h := z.Weekdays
	if wd := t.Weekday(); wd == time.Saturday || wd == time.Sunday {
		h = z.Weekends
	}
	if len(z.Weekdays) == 0 && len(z.Weekends) == 0 {
		return true
	}
	if len(h) != 2 {
		return false
	}
	ok, _ := Within(t.Format("15:04"), h[0], h[1])
	return ok
}

var zoneName = regexp.MustCompile(`^zone-[a-z]{2}-[a-z0-9-]+-\d{4}-\d{2}-\d{2}\.json$`)

// ZonesAll loads data/zone-*.json.
func ZonesAll() ([]Zone, error) { return LoadZones(files, "data") }

// LoadZones reads and checks the zone files in dir of fsys.
func LoadZones(fsys fs.FS, dir string) ([]Zone, error) {
	ents, err := fs.ReadDir(fsys, dir)
	if err != nil {
		return nil, err
	}
	var out []Zone
	for _, e := range ents {
		if !strings.HasPrefix(e.Name(), ZonePrefix) {
			continue
		}
		b, err := fs.ReadFile(fsys, path.Join(dir, e.Name()))
		if err != nil {
			return nil, err
		}
		var z Zone
		if err := json.Unmarshal(b, &z); err != nil {
			return nil, fmt.Errorf("%s: %w", e.Name(), err)
		}
		z.File = e.Name()
		if !zoneName.MatchString(e.Name()) || !strings.HasPrefix(e.Name(), ZonePrefix+strings.ToLower(z.Country)+"-") || !strings.HasSuffix(e.Name(), "-"+z.ValidFrom+".json") {
			return nil, fmt.Errorf("%s: name must be zone-<cc>-<zone>-<valid_from>.json", e.Name())
		}
		if z.Name == "" || z.Law == "" || len(z.Sources) == 0 || z.Currency == "" || z.Charge <= 0 || len(z.Polygons) == 0 || z.OSM == "" {
			return nil, fmt.Errorf("%s: name, law, sources, currency, charge, polygons and osm_extract are required", e.Name())
		}
		for _, h := range [][]string{z.Weekdays, z.Weekends} {
			if len(h) != 0 {
				if _, err := Within("00:00", h[0], h[len(h)-1]); err != nil || len(h) != 2 {
					return nil, fmt.Errorf("%s: hours must be [from, to] (HH:MM)", e.Name())
				}
			}
		}
		if len(z.NoCharge) != 0 && len(z.NoCharge) != 2 {
			return nil, fmt.Errorf("%s: no_charge must be [from, to] (MM-DD)", e.Name())
		}
		out = append(out, z)
	}
	return out, nil
}

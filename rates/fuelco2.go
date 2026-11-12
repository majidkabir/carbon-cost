package rates

import (
	"encoding/json"
	"fmt"
	"path"
	"sort"
	"strings"
	"time"
)

// FuelCO2Prefix starts the names of the files in data/ that hold a
// country's CO2 price on road fuel.
const FuelCO2Prefix = "fuelco2-"

// FuelCO2 is a country's CO2 price on road diesel in force for a period:
// a national emissions trading system's certificate price (Germany's
// BEHG, Austria's NEHG 2022) or a carbon tax, per tonne of CO2. The fuel
// supplier pays it and passes it on in the price of the fuel, so a trip
// pays it where its fuel is bought.
type FuelCO2 struct {
	Country   string   `json:"country"` // ISO 3166-1 alpha-2
	Currency  string   `json:"currency"`
	ValidFrom string   `json:"valid_from"`         // inclusive, YYYY-MM-DD
	ValidTo   string   `json:"valid_to,omitempty"` // inclusive; "" = until replaced
	Name      string   `json:"name"`
	RatePerT  float64  `json:"rate_per_t"` // per tonne of CO2
	Law       string   `json:"law"`
	Sources   []Source `json:"sources"`
	File      string   `json:"-"`
}

// Covers says if the price is in force on date.
func (f FuelCO2) Covers(date time.Time) bool {
	return !date.Before(day(f.ValidFrom)) && (f.ValidTo == "" || !date.After(day(f.ValidTo)))
}

// FuelCO2All loads every embedded fuel CO2 price, sorted by country and date.
func FuelCO2All() ([]FuelCO2, error) {
	ents, err := files.ReadDir("data")
	if err != nil {
		return nil, err
	}
	var out []FuelCO2
	for _, e := range ents {
		if !strings.HasPrefix(e.Name(), FuelCO2Prefix) {
			continue
		}
		b, err := files.ReadFile(path.Join("data", e.Name()))
		if err != nil {
			return nil, err
		}
		var f FuelCO2
		if err := json.Unmarshal(b, &f); err != nil {
			return nil, fmt.Errorf("%s: %w", e.Name(), err)
		}
		if f.Country == "" || f.Currency == "" || f.RatePerT < 0 || f.Law == "" || len(f.Sources) == 0 {
			return nil, fmt.Errorf("%s: country, currency, rate_per_t, law and sources are required", e.Name())
		}
		for _, d := range []string{f.ValidFrom, f.ValidTo} {
			if _, err := time.Parse(time.DateOnly, d); err != nil && d != "" || f.ValidFrom == "" {
				return nil, fmt.Errorf("%s: bad dates", e.Name())
			}
		}
		if want := FuelCO2Prefix + strings.ToLower(f.Country) + "-" + f.ValidFrom + ".json"; e.Name() != want {
			return nil, fmt.Errorf("%s: should be named %s", e.Name(), want)
		}
		f.File = e.Name()
		out = append(out, f)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Country != out[j].Country {
			return out[i].Country < out[j].Country
		}
		return out[i].ValidFrom < out[j].ValidFrom
	})
	return out, nil
}

// FindFuelCO2 returns the country's fuel CO2 price in force on date.
func FindFuelCO2(fs []FuelCO2, country string, date time.Time) (FuelCO2, bool) {
	for _, f := range fs {
		if f.Country == country && f.Covers(date) {
			return f, true
		}
	}
	return FuelCO2{}, false
}

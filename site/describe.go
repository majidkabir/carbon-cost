package site

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"

	"github.com/majidkabir/carbon-cost/orct"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// Words for what the rate tables hold, for the pages.

// countries are the names of the countries the tables cover.
var countries = map[string]string{
	"AD": "Andorra", "AL": "Albania", "AT": "Austria", "BA": "Bosnia and Herzegovina", "BE": "Belgium", "BG": "Bulgaria",
	"BY": "Belarus", "CH": "Switzerland", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "ES": "Spain",
	"FI": "Finland", "FO": "Faroe Islands", "FR": "France", "GB": "United Kingdom", "GR": "Greece", "HR": "Croatia",
	"HU": "Hungary", "IE": "Ireland", "IS": "Iceland", "IT": "Italy", "LI": "Liechtenstein", "LT": "Lithuania",
	"LU": "Luxembourg", "LV": "Latvia", "MD": "Moldova", "ME": "Montenegro", "MK": "North Macedonia", "NL": "Netherlands",
	"NO": "Norway", "PL": "Poland", "PT": "Portugal", "RO": "Romania", "RS": "Serbia", "SE": "Sweden", "SI": "Slovenia",
	"SK": "Slovakia", "TR": "Türkiye",
}

// localNames are the toll's own names that people search for.
var localNames = map[string]string{
	"DE": "Lkw-Maut", "AT": "GO-Maut", "CH": "LSVA", "LI": "LSVA", "CZ": "mýtné", "SK": "mýto", "PL": "e-TOLL", "HU": "HU-GO",
	"NL": "vrachtwagenheffing", "BE": "kilometerheffing", "DK": "vejafgift", "SI": "DarsGo", "FR": "péage", "IT": "pedaggio",
	"ES": "peaje", "PT": "portagem", "HR": "cestarina", "RS": "putarina", "BG": "e-toll", "GR": "diodia",
}

func countryName(cc string) string {
	if n, ok := countries[cc]; ok {
		return n
	}
	return cc
}

var roman = map[string]string{"0": "0", "1": "I", "2": "II", "3": "III", "4": "IV", "5": "V", "6": "VI", "EEV": "EEV"}

func num(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case int:
		return float64(x), true
	case string:
		f, err := strconv.ParseFloat(x, 64)
		return f, err == nil
	}
	return 0, false
}

func list(v any) []string {
	var out []string
	switch x := v.(type) {
	case []any:
		for _, e := range x {
			out = append(out, fmt.Sprint(e))
		}
	case string:
		out = []string{x}
	case float64, bool:
		out = []string{fmt.Sprint(x)}
	}
	return out
}

func tonnes(kg float64) string {
	return strconv.FormatFloat(kg/1000, 'f', -1, 64) + " t"
}

// massRange says a {min, max} of kilograms: "> 3.5 t", "≤ 18 t".
func massRange(v any) string {
	m, ok := v.(map[string]any)
	if !ok {
		return fmt.Sprint(v)
	}
	var parts []string
	if lo, ok := num(m["min"]); ok {
		if math.Mod(lo, 1000) == 1 || math.Mod(lo, 500) == 1 {
			parts = append(parts, "> "+tonnes(lo-1))
		} else {
			parts = append(parts, "≥ "+tonnes(lo))
		}
	}
	if hi, ok := num(m["max"]); ok {
		if math.Mod(hi+1, 500) == 0 {
			parts = append(parts, "< "+tonnes(hi+1))
		} else {
			parts = append(parts, "≤ "+tonnes(hi))
		}
	}
	return strings.Join(parts, ", ")
}

func countRange(v any, unit string) string {
	m, ok := v.(map[string]any)
	if !ok {
		return strings.Join(list(v), ", ") + " " + unit
	}
	lo, hasLo := num(m["min"])
	hi, hasHi := num(m["max"])
	switch {
	case hasLo && hasHi && lo == hi:
		return fmt.Sprintf("%g %s", lo, unit)
	case hasLo && hasHi:
		return fmt.Sprintf("%g–%g %s", lo, hi, unit)
	case hasLo:
		return fmt.Sprintf("%g+ %s", lo, unit)
	case hasHi:
		return fmt.Sprintf("≤ %g %s", hi, unit)
	}
	return ""
}

func numRange(v any, unit string) string {
	m, ok := v.(map[string]any)
	if !ok {
		return fmt.Sprint(v) + " " + unit
	}
	var parts []string
	if lo, ok := num(m["min"]); ok {
		parts = append(parts, fmt.Sprintf("≥ %g %s", lo, unit))
	}
	if hi, ok := num(m["max"]); ok {
		parts = append(parts, fmt.Sprintf("≤ %g %s", hi, unit))
	}
	return strings.Join(parts, ", ")
}

// critOrder is the order criteria are said in.
var critOrder = []string{"category", "train_mass_kg", "mass_kg", "trailer_mass_kg", "load_capacity_kg", "train_axles", "axles",
	"trailer_axles", "trailer", "train_length_m", "euro_class", "co2_class", "energy"}

// criteria says what vehicles meet the criteria.
func criteria(c map[string]any) string {
	if len(c) == 0 {
		return "All vehicles"
	}
	keys := make([]string, 0, len(c))
	for k := range c {
		keys = append(keys, k)
	}
	rank := func(k string) int {
		for i, o := range critOrder {
			if o == k {
				return i
			}
		}
		return len(critOrder)
	}
	sort.Slice(keys, func(i, j int) bool {
		if rank(keys[i]) != rank(keys[j]) {
			return rank(keys[i]) < rank(keys[j])
		}
		return keys[i] < keys[j]
	})
	var parts []string
	for _, k := range keys {
		v := c[k]
		switch k {
		case "train_mass_kg":
			parts = append(parts, massRange(v))
		case "mass_kg":
			parts = append(parts, "motor vehicle "+massRange(v))
		case "trailer_mass_kg":
			parts = append(parts, "trailer "+massRange(v))
		case "load_capacity_kg":
			parts = append(parts, "load capacity "+massRange(v))
		case "train_axles":
			parts = append(parts, countRange(v, "axles"))
		case "axles":
			parts = append(parts, "motor vehicle "+countRange(v, "axles"))
		case "trailer_axles":
			parts = append(parts, "trailer "+countRange(v, "axles"))
		case "train_length_m":
			parts = append(parts, "length "+numRange(v, "m"))
		case "trailer":
			if b, _ := v.(bool); b {
				parts = append(parts, "with trailer")
			} else {
				parts = append(parts, "without trailer")
			}
		case "euro_class":
			var es []string
			for _, e := range list(v) {
				if r, ok := roman[e]; ok && e != "EEV" {
					es = append(es, "Euro "+r)
				} else {
					es = append(es, e)
				}
			}
			parts = append(parts, strings.Join(es, ", "))
		case "co2_class":
			parts = append(parts, co2Classes(list(v)))
		case "energy":
			parts = append(parts, strings.Join(list(v), ", "))
		case "category":
			parts = append(parts, strings.Join(list(v), ", "))
		case "any_of":
			var alts []string
			if xs, ok := v.([]any); ok {
				for _, x := range xs {
					if m, ok := x.(map[string]any); ok {
						alts = append(alts, criteria(m))
					}
				}
			}
			parts = append(parts, "("+strings.Join(alts, " or ")+")")
		default:
			parts = append(parts, fmt.Sprintf("%s: %v", strings.ReplaceAll(k, "_", " "), v))
		}
	}
	s := strings.Join(parts, ", ")
	return capital(s)
}

// capital is s with its first letter capitalised.
func capital(s string) string {
	r := []rune(s)
	if len(r) == 0 {
		return s
	}
	return strings.ToUpper(string(r[0])) + string(r[1:])
}

func co2Classes(cs []string) string {
	if len(cs) == 1 && cs[0] == "5" {
		return "CO2 class 5 (zero-emission)"
	}
	if len(cs) > 2 {
		ok := true
		for i := 1; i < len(cs); i++ {
			a, _ := strconv.Atoi(cs[i-1])
			b, _ := strconv.Atoi(cs[i])
			ok = ok && b == a+1
		}
		if ok {
			return "CO2 class " + cs[0] + "–" + cs[len(cs)-1]
		}
	}
	return "CO2 class " + strings.Join(cs, ", ")
}

// className says a vehicle class: its label, else its criteria.
func className(ds *tariffs.Dataset, id string) string {
	c := ds.Class(id)
	if c == nil {
		return id
	}
	if c.Label != "" {
		return c.Label
	}
	return criteria(c.Criteria)
}

var objWords = map[string]string{"motorway": "motorways", "other": "other roads", "interurban": "interurban", "suburban": "suburban",
	"urban": "urban", "roads": "toll roads", "main": "main roads", "expressway": "expressways", "trunk": "trunk roads"}

// objectName says a charge object: its name, else what its id says.
func objectName(ds *tariffs.Dataset, id string) string {
	o := ds.Object(id)
	if o != nil && o.Name != "" {
		return o.Name
	}
	if id == "roads" {
		return "Toll roads"
	}
	head, rest, ok := strings.Cut(id, ":")
	if !ok {
		return id
	}
	if head == "op" {
		return rest
	}
	var ws []string
	for _, p := range strings.Split(rest, ":") {
		if w, ok := objWords[p]; ok {
			ws = append(ws, w)
		} else {
			ws = append(ws, strings.ReplaceAll(p, "_", " "))
		}
	}
	s := strings.Join(ws, ", ")
	return capital(s)
}

var units = map[string]string{"km": "per km", "tkm": "per tonne-km", "trip": "per trip", "passage": "per passage", "use": "per use",
	"product": "per vignette", "day": "per day", "t_co2": "per t CO2", "litre": "per litre", "t": "per tonne", "entry": "per entry"}

func unitName(u string) string {
	if s, ok := units[u]; ok {
		return s
	}
	return "per " + u
}

var components = map[string]string{"infrastructure": "Infrastructure", "air_pollution": "Air pollution", "noise": "Noise",
	"air_pollution_noise": "Air pollution and noise", "co2": "CO2", "carbon_price": "CO2 price", "congestion": "Congestion",
	"access": "Access", "other": "Other", "unspecified": "Toll"}

func componentName(ch *orct.Charge) string {
	if ch.ComponentLabel != "" {
		return ch.ComponentLabel
	}
	if s, ok := components[ch.Component]; ok {
		return s
	}
	return ch.Component
}

var symbols = map[string]string{"EUR": "€", "GBP": "£"}

// money says an amount: "€0.348", "1.21 DKK"; per-km rates keep their
// third and fourth decimals.
func money(v float64, cur string) string {
	var s string
	switch a := math.Abs(v); {
	case a == 0:
		s = "0"
	case a < 10:
		s = strconv.FormatFloat(v, 'f', 4, 64)
		s = strings.TrimRight(s, "0")
		if i := strings.IndexByte(s, '.'); i < 0 {
			s += ".00"
		} else if len(s)-i-1 < 2 {
			s += strings.Repeat("0", 2-(len(s)-i-1))
		}
	case a < 100000:
		s = strconv.FormatFloat(v, 'f', 2, 64)
	default:
		s = strconv.FormatFloat(v, 'f', 0, 64)
	}
	if sym, ok := symbols[cur]; ok {
		return sym + s
	}
	return s + " " + cur
}

func pct(part, whole float64) string {
	if whole == 0 {
		return ""
	}
	return strconv.FormatFloat(math.Round(part/whole*100), 'f', 0, 64) + "%"
}

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

// Words for what the rate tables hold, in a page's language.

// countries are the countries' English names (each language's are in
// locales.json, from the CLDR).
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

func (l *Loc) tonnes(kg float64) string { return l.Dec(kg/1000) + " " + l.T("sym.t") }

// massRange says a {min, max} of kilograms: "> 3.5 t", "≤ 18 t".
func (l *Loc) massRange(v any) string {
	m, ok := v.(map[string]any)
	if !ok {
		return fmt.Sprint(v)
	}
	var parts []string
	if lo, ok := num(m["min"]); ok {
		if math.Mod(lo, 1000) == 1 || math.Mod(lo, 500) == 1 {
			parts = append(parts, "> "+l.tonnes(lo-1))
		} else {
			parts = append(parts, "≥ "+l.tonnes(lo))
		}
	}
	if gt, ok := num(m["gt"]); ok {
		parts = append(parts, "> "+l.tonnes(gt))
	}
	if hi, ok := num(m["max"]); ok {
		if math.Mod(hi+1, 500) == 0 {
			parts = append(parts, "< "+l.tonnes(hi+1))
		} else {
			parts = append(parts, "≤ "+l.tonnes(hi))
		}
	}
	return strings.Join(parts, ", ")
}

func (l *Loc) countRange(v any) string {
	m, ok := v.(map[string]any)
	if !ok {
		return strings.Join(list(v), ", ")
	}
	lo, hasLo := num(m["min"])
	hi, hasHi := num(m["max"])
	switch {
	case hasLo && hasHi && lo == hi:
		return l.Dec(lo)
	case hasLo && hasHi:
		return l.Dec(lo) + "–" + l.Dec(hi)
	case hasLo:
		return l.Dec(lo) + "+"
	case hasHi:
		return "≤ " + l.Dec(hi)
	}
	return ""
}

func (l *Loc) numRange(v any, unit string) string {
	m, ok := v.(map[string]any)
	if !ok {
		return fmt.Sprint(v) + " " + unit
	}
	var parts []string
	if lo, ok := num(m["min"]); ok {
		parts = append(parts, "≥ "+l.Dec(lo)+" "+unit)
	}
	if gt, ok := num(m["gt"]); ok {
		parts = append(parts, "> "+l.Dec(gt)+" "+unit)
	}
	if hi, ok := num(m["max"]); ok {
		parts = append(parts, "≤ "+l.Dec(hi)+" "+unit)
	}
	return strings.Join(parts, ", ")
}

// critOrder is the order criteria are said in.
var critOrder = []string{"category", "train_mass_kg", "mass_kg", "trailer_mass_kg", "load_capacity_kg", "train_axles", "axles",
	"trailer_axles", "trailer", "train_length_m", "euro_class", "co2_class", "energy"}

// criteria says what vehicles meet the criteria.
func (l *Loc) criteria(c map[string]any) string {
	if len(c) == 0 {
		return l.T("cr.all")
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
			parts = append(parts, l.massRange(v))
		case "mass_kg":
			parts = append(parts, l.T("cr.motor", "x", l.massRange(v)))
		case "trailer_mass_kg":
			parts = append(parts, l.T("cr.trailer", "x", l.massRange(v)))
		case "load_capacity_kg":
			parts = append(parts, l.T("cr.cap", "x", l.massRange(v)))
		case "train_axles":
			parts = append(parts, l.T("cr.axles", "n", l.countRange(v)))
		case "axles":
			parts = append(parts, l.T("cr.motor", "x", l.T("cr.axles", "n", l.countRange(v))))
		case "trailer_axles":
			parts = append(parts, l.T("cr.trailer", "x", l.T("cr.axles", "n", l.countRange(v))))
		case "train_length_m":
			parts = append(parts, l.T("cr.length", "x", l.numRange(v, "m")))
		case "trailer":
			if b, _ := v.(bool); b {
				parts = append(parts, l.T("cr.withtrailer"))
			} else {
				parts = append(parts, l.T("cr.notrailer"))
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
			parts = append(parts, l.co2Classes(list(v)))
		case "energy", "category":
			parts = append(parts, strings.Join(list(v), ", "))
		case "any_of":
			var alts []string
			if xs, ok := v.([]any); ok {
				for _, x := range xs {
					if m, ok := x.(map[string]any); ok {
						alts = append(alts, l.criteria(m))
					}
				}
			}
			parts = append(parts, "("+strings.Join(alts, l.T("cr.or"))+")")
		default:
			parts = append(parts, fmt.Sprintf("%s: %v", strings.ReplaceAll(k, "_", " "), v))
		}
	}
	return capital(strings.Join(parts, ", "))
}

// capital is s with its first letter capitalised.
func capital(s string) string {
	r := []rune(s)
	if len(r) == 0 {
		return s
	}
	return strings.ToUpper(string(r[0])) + string(r[1:])
}

func (l *Loc) co2Classes(cs []string) string {
	if len(cs) == 1 && cs[0] == "5" {
		return l.T("cr.ze")
	}
	if len(cs) > 2 {
		ok := true
		for i := 1; i < len(cs); i++ {
			a, _ := strconv.Atoi(cs[i-1])
			b, _ := strconv.Atoi(cs[i])
			ok = ok && b == a+1
		}
		if ok {
			return l.T("cr.co2", "x", cs[0]+"–"+cs[len(cs)-1])
		}
	}
	return l.T("cr.co2", "x", strings.Join(cs, ", "))
}

// className says a vehicle class: in English its label, else (and in
// other languages) its criteria.
func (l *Loc) className(ds *tariffs.Dataset, id string) string {
	c := ds.Class(id)
	if c == nil {
		return id
	}
	if c.Label != "" && (l.Code == "en" || len(c.Criteria) == 0) {
		return c.Label
	}
	return l.criteria(c.Criteria)
}

var objWords = []string{"motorway", "other", "interurban", "suburban", "urban", "main", "expressway", "trunk"}

// objectName says a charge object: its name, else what its id says.
func (l *Loc) objectName(ds *tariffs.Dataset, id string) string {
	o := ds.Object(id)
	if o != nil && o.Name != "" {
		return o.Name
	}
	if id == "roads" {
		return l.T("obj.roads")
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
		known := false
		for _, w := range objWords {
			if p == w {
				ws, known = append(ws, l.T("obj."+w)), true
				break
			}
		}
		if !known {
			ws = append(ws, strings.ReplaceAll(p, "_", " "))
		}
	}
	return capital(strings.Join(ws, ", "))
}

func (l *Loc) unitName(u string) string {
	if s := l.T("unit." + u); s != "unit."+u {
		return s
	}
	return "/ " + u
}

func (l *Loc) componentName(ch *orct.Charge) string {
	if s := l.T("comp." + ch.Component); s != "comp."+ch.Component {
		return s
	}
	if ch.ComponentLabel != "" {
		return ch.ComponentLabel
	}
	return ch.Component
}

// chargeName is a charge's name: its own in English, else its component.
func (l *Loc) chargeName(ch *orct.Charge) string {
	if l.Code == "en" && ch.Name != "" {
		return ch.Name
	}
	return l.componentName(ch)
}

package site

import (
	"embed"
	"encoding/json"
	"fmt"
	"math"
	"path"
	"sort"
	"strconv"
	"strings"
	"time"
)

// The pages' languages: messages (site/i18n/<lang>.json, written by hand
// from en.json) and each language's formats and country names from the
// Unicode CLDR (site/i18n/locales.json, tools/site/locales.py).

//go:embed i18n/*.json
var i18nFS embed.FS

// local are the languages of each country's own page, after English.
var local = map[string][]string{
	"AD": {"ca"}, "AL": {"sq"}, "AT": {"de"}, "BA": {"bs"}, "BE": {"nl", "fr", "de"}, "BG": {"bg"}, "BY": {"ru"},
	"CH": {"de", "fr", "it"}, "CZ": {"cs"}, "DE": {"de"}, "DK": {"da"}, "EE": {"et"}, "ES": {"es"}, "FI": {"fi", "sv"},
	"FO": {"fo"}, "FR": {"fr"}, "GR": {"el"}, "HR": {"hr"}, "HU": {"hu"}, "IS": {"is"}, "IT": {"it"}, "LI": {"de"},
	"LT": {"lt"}, "LU": {"fr", "de"}, "LV": {"lv"}, "MD": {"ro"}, "ME": {"sr"}, "MK": {"mk"}, "NL": {"nl"}, "NO": {"nb"},
	"PL": {"pl"}, "PT": {"pt"}, "RO": {"ro"}, "RS": {"sr"}, "SE": {"sv"}, "SI": {"sl"}, "SK": {"sk"}, "TR": {"tr"},
}

type localeData struct {
	Locale    string            `json:"locale"`
	Name      string            `json:"name"`
	Countries map[string]string `json:"countries"`
	Decimal   string            `json:"decimal"`
	Group     string            `json:"group"`
	Currency  string            `json:"currency"`
	Percent   string            `json:"percent"`
	Date      string            `json:"date"`
	Months    []string          `json:"months"`
}

// Loc is a language: its messages and formats.
type Loc struct {
	Code string
	Name string
	msgs map[string]string
	en   map[string]string
	ld   localeData
}

// loadLocs reads the languages that have messages.
func loadLocs() (map[string]*Loc, error) {
	var ls struct {
		Languages map[string]localeData `json:"languages"`
	}
	b, err := i18nFS.ReadFile("i18n/locales.json")
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(b, &ls); err != nil {
		return nil, err
	}
	msgs := map[string]map[string]string{}
	ents, _ := i18nFS.ReadDir("i18n")
	for _, e := range ents {
		code := strings.TrimSuffix(e.Name(), ".json")
		if code == "locales" {
			continue
		}
		b, err := i18nFS.ReadFile(path.Join("i18n", e.Name()))
		if err != nil {
			return nil, err
		}
		m := map[string]string{}
		if err := json.Unmarshal(b, &m); err != nil {
			return nil, fmt.Errorf("i18n/%s: %w", e.Name(), err)
		}
		msgs[code] = m
	}
	en := msgs["en"]
	out := map[string]*Loc{}
	for code, m := range msgs {
		ld, ok := ls.Languages[code]
		if !ok {
			return nil, fmt.Errorf("i18n: %s has no CLDR data in locales.json", code)
		}
		out[code] = &Loc{Code: code, Name: ld.Name, msgs: m, en: en, ld: ld}
	}
	if out["en"] == nil {
		return nil, fmt.Errorf("i18n: no en.json")
	}
	return out, nil
}

// T is a message with its {name} placeholders filled from name, value
// pairs; English when the language lacks it.
func (l *Loc) T(id string, kv ...any) string {
	s, ok := l.msgs[id]
	if !ok {
		if s, ok = l.en[id]; !ok {
			return id
		}
	}
	for i := 0; i+1 < len(kv); i += 2 {
		s = strings.ReplaceAll(s, "{"+fmt.Sprint(kv[i])+"}", fmt.Sprint(kv[i+1]))
	}
	return s
}

// Country is a country's name.
func (l *Loc) Country(cc string) string {
	if n, ok := l.ld.Countries[cc]; ok {
		return n
	}
	return countryName(cc)
}

// num writes v with decimals digits (trimmed to min..max).
func (l *Loc) num(v float64, minDec, maxDec int) string {
	s := strconv.FormatFloat(math.Abs(v), 'f', maxDec, 64)
	if i := strings.IndexByte(s, '.'); i >= 0 {
		s = strings.TrimRight(s, "0")
		if d := len(s) - i - 1; d < minDec {
			s += strings.Repeat("0", minDec-d)
		}
		s = strings.TrimSuffix(s, ".")
	}
	ip, fp, _ := strings.Cut(s, ".")
	for i := len(ip) - 3; i > 0; i -= 3 {
		ip = ip[:i] + "\x00" + ip[i:]
	}
	ip = strings.ReplaceAll(ip, "\x00", l.ld.Group)
	if fp != "" {
		ip += l.ld.Decimal + fp
	}
	if v < 0 {
		ip = "-" + ip
	}
	return ip
}

// Int writes a count.
func (l *Loc) Int(n int) string { return l.num(float64(n), 0, 0) }

// Dec writes a measure such as 3.5 (t) or 16.5 (m).
func (l *Loc) Dec(v float64) string { return l.num(v, 0, 2) }

var symbols = map[string]string{"EUR": "€", "GBP": "£"}

// Money writes an amount in its currency the language's way; per-km
// rates keep their third and fourth decimals.
func (l *Loc) Money(v float64, cur string) string {
	var n string
	switch a := math.Abs(v); {
	case a == 0:
		n = "0"
	case a < 10:
		n = l.num(v, 2, 4)
	case a < 100000:
		n = l.num(v, 2, 2)
	default:
		n = l.num(v, 0, 0)
	}
	sym, ok := symbols[cur]
	if !ok {
		sym = cur
	}
	p := l.ld.Currency
	cy, hash := strings.Index(p, "¤"), strings.Index(p, "#")
	if cy < hash {
		sp := ""
		if r := p[cy+len("¤"):]; !ok || strings.HasPrefix(r, "\u00a0") || strings.HasPrefix(r, " ") {
			sp = "\u00a0"
		}
		return sym + sp + n
	}
	sp := ""
	if r := p[:cy]; !ok || strings.HasSuffix(r, "\u00a0") || strings.HasSuffix(r, " ") {
		sp = "\u00a0"
	}
	return n + sp + sym
}

// Pct writes part of whole as a percentage.
func (l *Loc) Pct(part, whole float64) string {
	if whole == 0 {
		return ""
	}
	return l.PctOf(part / whole)
}

// PctOf writes a share (0.45) as a percentage.
func (l *Loc) PctOf(share float64) string {
	n := l.num(math.Round(share*100), 0, 0)
	p := l.ld.Percent
	if strings.HasPrefix(p, "%") {
		return "%" + n
	}
	if strings.Contains(p, " %") {
		return n + " %"
	}
	return n + "%"
}

// Date writes a day (YYYY-MM-DD) in the language's long form.
func (l *Loc) Date(d string) string {
	t, err := time.Parse(time.DateOnly, d)
	if err != nil {
		return d
	}
	var b strings.Builder
	p := l.ld.Date
	for i := 0; i < len(p); {
		c := p[i]
		if c == '\'' {
			j := strings.IndexByte(p[i+1:], '\'')
			if j < 0 {
				b.WriteString(p[i+1:])
				break
			}
			b.WriteString(p[i+1 : i+1+j])
			i += j + 2
			continue
		}
		n := 1
		for i+n < len(p) && p[i+n] == c {
			n++
		}
		switch c {
		case 'd':
			if n == 2 {
				fmt.Fprintf(&b, "%02d", t.Day())
			} else {
				b.WriteString(strconv.Itoa(t.Day()))
			}
		case 'M', 'L':
			switch {
			case n >= 4:
				b.WriteString(l.ld.Months[t.Month()-1])
			case n == 2:
				fmt.Fprintf(&b, "%02d", int(t.Month()))
			default:
				b.WriteString(strconv.Itoa(int(t.Month())))
			}
		case 'y':
			b.WriteString(strconv.Itoa(t.Year()))
		default:
			b.WriteString(p[i : i+n])
		}
		i += n
	}
	return b.String()
}

// langsOf are the languages a country's page is in: English first.
func langsOf(cc string, have map[string]*Loc) []string {
	out := []string{"en"}
	for _, l := range local[cc] {
		if have[l] != nil {
			out = append(out, l)
		}
	}
	return out
}

// sortedLangs are the languages with messages, English first.
func sortedLangs(have map[string]*Loc) []string {
	var out []string
	for c := range have {
		if c != "en" {
			out = append(out, c)
		}
	}
	sort.Strings(out)
	return append([]string{"en"}, out...)
}

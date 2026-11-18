package site

import (
	"fmt"
	"html/template"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/orct"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// Page data: figures as text, ready for the templates.

type figRow struct {
	Label, Total, CO2, Share, EUR string
	Highlight                     bool
}

type fareRow struct {
	What, Total, CO2 string
}

type versionRow struct {
	From, To, Rate, CO2, Law, File string
	Upcoming, Current              bool
}

type schemeView struct {
	Name, Kind, How, From, To, Method, File, Cur string
	Liable                                       string
	Roads                                        []figRow // the 40 t truck per km, by road
	ByMass, ByCO2, ByEuro                        []figRow
	ZE                                           string
	Fares                                        []fareRow
	FareNote                                     string
	Products                                     []fareRow
	Tables                                       []rateTable
	Versions                                     []versionRow
	Example                                      string
	Sources                                      []tariffs.Source
	Upcoming                                     bool
}

type fuelView struct {
	Name, Rate, PerLitre, From, Law string
	Versions                        []versionRow
	Sources                         []tariffs.Source
}

type countryView struct {
	Head
	C                 *country
	H1, Lead          string
	Schemes           []schemeView
	Fuel              []fuelView
	Trip              string // the calculator, with a trip in the country
	TripName          string
	Others, Countries []link
	Sources           []tariffs.Source
	Updated           string
}

type overviewRow struct {
	Name, Href, How, Rate, Share, ZE, Fuel string
}

type overviewView struct {
	Head
	Rows              []overviewRow
	FXNote            string
	Updated           string
	Others, Countries []link
}

type crossRow struct {
	Cells []string
	Href  string
	Note  string
}

type crossView struct {
	Head
	H1, Lead          string
	Cols              []string
	Rows              []crossRow
	Body              []template.HTML
	Notes             []string
	Sources           []tariffs.Source
	Others, Countries []link
	Updated           string
}

// Cross-country pages.
var crossPages = []link{
	{"Zero-emission truck toll exemptions in Europe", "/tolls/zero-emission-trucks"},
	{"ETS2: the cost per litre of diesel from 2028", "/tolls/ets2-diesel"},
	{"National CO2 taxes on diesel by country", "/tolls/co2-tax-diesel"},
}

// trips are a trip in each country for the calculator's "price your trip".
var trips = map[string][2][3]any{
	"AD": {{"Andorra la Vella", 42.507, 1.522}, {"Pas de la Casa", 42.543, 1.733}},
	"AL": {{"Tirana", 41.328, 19.818}, {"Kukës", 42.077, 20.421}},
	"AT": {{"Salzburg", 47.809, 13.055}, {"Vienna", 48.208, 16.373}},
	"BA": {{"Sarajevo", 43.856, 18.413}, {"Zenica", 44.203, 17.908}},
	"BE": {{"Antwerp", 51.219, 4.402}, {"Liège", 50.633, 5.567}},
	"BG": {{"Sofia", 42.698, 23.322}, {"Plovdiv", 42.144, 24.750}},
	"BY": {{"Brest", 52.093, 23.685}, {"Minsk", 53.902, 27.562}},
	"CH": {{"Basel", 47.560, 7.589}, {"Chiasso", 45.832, 9.032}},
	"CZ": {{"Prague", 50.076, 14.438}, {"Brno", 49.195, 16.607}},
	"DE": {{"Hamburg", 53.551, 9.994}, {"Munich", 48.137, 11.576}},
	"DK": {{"Padborg", 54.826, 9.358}, {"Copenhagen", 55.676, 12.568}},
	"EE": {{"Tallinn", 59.437, 24.754}, {"Tartu", 58.378, 26.729}},
	"ES": {{"Bilbao", 43.263, -2.935}, {"Zaragoza", 41.649, -0.889}},
	"FI": {{"Helsinki", 60.170, 24.938}, {"Tampere", 61.498, 23.761}},
	"FO": {{"Tórshavn", 62.009, -6.772}, {"Klaksvík", 62.226, -6.589}},
	"FR": {{"Paris", 48.857, 2.352}, {"Lyon", 45.764, 4.836}},
	"GB": {{"Dover", 51.128, 1.314}, {"London", 51.507, -0.128}},
	"GR": {{"Athens", 37.984, 23.728}, {"Thessaloniki", 40.640, 22.944}},
	"HR": {{"Zagreb", 45.815, 15.982}, {"Split", 43.508, 16.440}},
	"HU": {{"Budapest", 47.498, 19.040}, {"Szeged", 46.253, 20.148}},
	"IE": {{"Dublin", 53.350, -6.260}, {"Cork", 51.898, -8.475}},
	"IS": {{"Reykjavík", 64.147, -21.942}, {"Akureyri", 65.684, -18.088}},
	"IT": {{"Milan", 45.464, 9.190}, {"Bologna", 44.494, 11.343}},
	"LI": {{"Vaduz", 47.141, 9.521}, {"Balzers", 47.066, 9.502}},
	"LT": {{"Vilnius", 54.687, 25.280}, {"Kaunas", 54.899, 23.904}},
	"LU": {{"Luxembourg", 49.611, 6.130}, {"Ettelbruck", 49.847, 6.104}},
	"LV": {{"Riga", 56.949, 24.105}, {"Daugavpils", 55.875, 26.536}},
	"MD": {{"Chișinău", 47.011, 28.863}, {"Bălți", 47.762, 27.929}},
	"ME": {{"Podgorica", 42.441, 19.263}, {"Kolašin", 42.822, 19.517}},
	"MK": {{"Skopje", 41.998, 21.425}, {"Gevgelija", 41.141, 22.502}},
	"NL": {{"Rotterdam", 51.924, 4.478}, {"Venlo", 51.370, 6.172}},
	"NO": {{"Oslo", 59.913, 10.752}, {"Bergen", 60.392, 5.322}},
	"PL": {{"Warsaw", 52.230, 21.012}, {"Poznań", 52.406, 16.925}},
	"PT": {{"Lisbon", 38.722, -9.139}, {"Porto", 41.158, -8.629}},
	"RO": {{"Bucharest", 44.426, 26.103}, {"Constanța", 44.160, 28.635}},
	"RS": {{"Belgrade", 44.787, 20.457}, {"Niš", 43.320, 21.896}},
	"SE": {{"Malmö", 55.605, 13.004}, {"Gothenburg", 57.709, 11.975}},
	"SI": {{"Ljubljana", 46.057, 14.506}, {"Maribor", 46.554, 15.646}},
	"SK": {{"Bratislava", 48.149, 17.107}, {"Žilina", 49.223, 18.740}},
	"TR": {{"Istanbul", 41.008, 28.978}, {"Ankara", 39.934, 32.860}},
}

func (s *Site) trip(cc string) (href, name string) {
	t, ok := trips[cc]
	if !ok || t[0][0] == nil {
		return s.prefix + "/", ""
	}
	q := fmt.Sprintf("from=%v,%v&from_name=%s&to=%v,%v&to_name=%s", t[0][1], t[0][2], urlq(t[0][0]), t[1][1], t[1][2], urlq(t[1][0]))
	return s.prefix + "/?" + q, fmt.Sprintf("%v to %v", t[0][0], t[1][0])
}

func urlq(v any) string { return strings.ReplaceAll(templateURL(fmt.Sprint(v)), "+", "%20") }

func templateURL(s string) string { return template.URLQueryEscaper(s) }

// kindHow says how a scheme charges.
func kindHow(ds *tariffs.Dataset) string {
	seen := map[string]bool{}
	var hows []string
	for i := range ds.Doc.Charges {
		ch := &ds.Doc.Charges[i]
		var h string
		switch {
		case ch.Type == "distance" && ch.Unit == "tkm":
			h = "per km by weight"
		case ch.Type == "distance":
			h = "per km"
		case ch.Type == "section":
			h = "per section"
		case ch.Type == "od":
			h = "per trip, by entry and exit"
		case ch.Type == "point":
			h = "per passage"
		case ch.Type == "period":
			h = "time-based vignette"
		case ch.Type == "area":
			h = "per day in a zone"
		case ch.Type == "quantity":
			h = "CO2 price on fuel"
		default:
			h = ch.Type
		}
		if !seen[h] {
			seen[h] = true
			hows = append(hows, h)
		}
	}
	return strings.Join(hows, "; ")
}

func short(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	cut := string(r[:n])
	if i := strings.LastIndex(cut, " "); i > len(cut)/2 {
		cut = cut[:i]
	}
	return strings.TrimRight(cut, " ,;:") + "…"
}

func dateName(d string) string {
	t, err := time.Parse(time.DateOnly, d)
	if err != nil {
		return d
	}
	return t.Format("2 January 2006")
}

func (s *Site) build(day string) *built {
	today, _ := time.Parse(time.DateOnly, day)
	cs := group(s.set, day)
	b := &built{pages: map[string][]byte{}, cards: map[string]card{}, images: map[string][]byte{}, mod: map[string]string{}}
	year := today.Year()
	var rows []overviewRow
	countryLinks := []link{}
	for _, c := range cs {
		countryLinks = append(countryLinks, link{c.Name, s.prefix + "/tolls/" + c.Slug})
	}
	for _, c := range cs {
		v, row, cd, mod := s.countryPage(c, day, today, year)
		v.Others, v.Countries = crossPages, countryLinks
		path := "/tolls/" + c.Slug
		b.pages[path] = s.render("country.html", v)
		b.cards[path] = cd
		b.paths = append(b.paths, path)
		b.mod[path] = mod
		rows = append(rows, row)
	}
	// Overview.
	ov := overviewView{Rows: rows, Updated: day, Others: crossPages}
	if r, ok := fxDate(today); ok {
		ov.FXNote = "Rates in other currencies are converted to euros at the ECB reference rate of " + dateName(r) +
			" (DKK at the ERM II central rate, RSD at the National Bank of Serbia's middle rate)."
	}
	ld := s.datasetLD("/tolls", fmt.Sprintf("Truck tolls in Europe %d", year),
		"Road tolls for trucks over 3.5 t in "+fmt.Sprint(len(cs))+" European countries, as ORCT rate tables built from the laws and official tariffs, with each charge's CO2 part.",
		"Europe", nil, "")
	ov.Head = s.mkHead("/tolls", fmt.Sprintf("Truck tolls in Europe %d: rates per km by country, with the CO2 part", year),
		fmt.Sprintf("Truck tolls in %d European countries for a 40 t Euro VI truck: how each country charges, the rate per km and its CO2 share. From the laws, updated by workflows.", len(cs)),
		ld, link{"Truck tolls", s.prefix + "/tolls"})
	b.pages["/tolls"] = s.render("overview.html", ov)
	b.cards["/tolls"] = card{Kicker: "carbon-cost · truck tolls", Title: fmt.Sprintf("Truck tolls in Europe %d", year),
		Big: fmt.Sprintf("%d countries", len(cs)), BigNote: "Rates per km by weight, Euro and CO2 class, from the law",
		Footer: hostPath(s.base) + "/tolls"}
	b.paths = append(b.paths, "/tolls")
	b.mod["/tolls"] = day
	// Across countries.
	for _, p := range []struct {
		path string
		f    func([]*country, string, time.Time) (crossView, card)
	}{{"/tolls/zero-emission-trucks", s.zePage}, {"/tolls/ets2-diesel", s.ets2Page}, {"/tolls/co2-tax-diesel", s.fuelPage}} {
		v, cd := p.f(cs, day, today)
		v.Others, v.Countries = crossPages, countryLinks
		b.pages[p.path] = s.render("cross.html", v)
		b.cards[p.path] = cd
		b.paths = append(b.paths, p.path)
		b.mod[p.path] = day
	}
	b.paths = append(b.paths, "/")
	b.pages["/sitemap.xml"] = sitemap(s.base, b.paths, b.mod)
	return b
}

func hostPath(base string) string {
	return strings.TrimPrefix(strings.TrimPrefix(base, "https://"), "http://")
}

func fxDate(day time.Time) (string, bool) {
	r, ok := fxOnDate(day)
	return r, ok
}

// datasetLD is schema.org Dataset markup for a page.
func (s *Site) datasetLD(path, name, desc, area string, files []string, from string) map[string]any {
	ld := map[string]any{
		"@context": "https://schema.org", "@type": "Dataset", "name": name, "description": desc,
		"url": s.base + path, "license": "https://opensource.org/licenses/MIT", "isAccessibleForFree": true,
		"creator":              map[string]any{"@type": "Organization", "name": "carbon-cost", "url": "https://github.com/majidkabir/carbon-cost"},
		"spatialCoverage":      map[string]any{"@type": "Place", "name": area},
		"measurementTechnique": "Transcribed from the laws and official tariffs by repeatable workflows; ORCT 0.3 rate tables",
		"keywords":             []string{"truck toll", "HGV toll", "road charges", "CO2 class", "Eurovignette", "ORCT"},
	}
	if from != "" {
		ld["temporalCoverage"] = from + "/.."
	}
	var dist []map[string]any
	for _, f := range files {
		dist = append(dist, map[string]any{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": s.base + "/v1/rates/" + f})
	}
	if len(dist) > 0 {
		ld["distribution"] = dist
	}
	return ld
}

// versions lists a scheme's versions with the truck's rate per km.
func versions(sc *scheme, today string, perKmOf func(*tariffs.Dataset) (string, string)) []versionRow {
	var all []*tariffs.Dataset
	for i := len(sc.Past) - 1; i >= 0; i-- {
		all = append(all, sc.Past[i])
	}
	if sc.Current != nil {
		all = append(all, sc.Current)
	}
	all = append(all, sc.Upcoming...)
	var out []versionRow
	for _, d := range all {
		r, co2 := perKmOf(d)
		to := d.ValidTo
		if to == "" {
			to = "until replaced"
		}
		out = append(out, versionRow{From: d.ValidFrom, To: to, Rate: r, CO2: co2, Law: short(lawOnly(d.Method()), 160), File: d.File,
			Upcoming: d.ValidFrom > today, Current: d == sc.Current})
	}
	// Newest first.
	for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
		out[i], out[j] = out[j], out[i]
	}
	return out
}

// lawOnly is a method's text without its clauses on how the workflows
// read the sources.
func lawOnly(m string) string {
	var keep []string
	for _, p := range strings.Split(m, "; ") {
		if !strings.Contains(p, "tools/") && !strings.Contains(p, "workflow") && !strings.Contains(p, "in a browser") {
			keep = append(keep, p)
		}
	}
	return strings.Join(keep, "; ")
}

func sources(ds ...*tariffs.Dataset) []tariffs.Source {
	seen := map[string]bool{}
	var out []tariffs.Source
	for _, d := range ds {
		if d == nil {
			continue
		}
		for _, s := range d.Sources() {
			if !seen[s.URL] {
				seen[s.URL] = true
				out = append(out, s)
			}
		}
	}
	return out
}

func fig(a amount, label string, day time.Time) figRow {
	r := figRow{Label: label, Total: money(a.Total, a.Cur), CO2: "–", Share: "–"}
	if a.CO2 > 0 {
		r.CO2, r.Share = money(a.CO2, a.Cur), pct(a.CO2, a.Total)
	} else if a.Total > 0 {
		r.CO2, r.Share = money(0, a.Cur), "0%"
	}
	if a.Cur != "EUR" {
		if e, ok := toEUR(a.Total, a.Cur, day); ok {
			r.EUR = money(e, "EUR")
		}
	}
	return r
}

func (s *Site) countryPage(c *country, day string, today time.Time, year int) (countryView, overviewRow, card, string) {
	v := countryView{C: c}
	row := overviewRow{Name: c.Name, Href: s.prefix + "/tolls/" + c.Slug, Rate: "–", Share: "–", ZE: "–", Fuel: "–"}
	var all []*tariffs.Dataset
	var hows []string
	var files []string
	var cd card
	mod := ""
	var lo, hi, shLo, shHi float64
	lo = -1
	kmScheme := false
	nSt, nTrips, nPlaces := 0, 0, 0
	var top *fare
	for _, sc := range c.Schemes {
		ds := sc.latest()
		all = append(all, ds)
		files = append(files, ds.File)
		for _, d := range append(append([]*tariffs.Dataset{}, sc.Past...), sc.Upcoming...) {
			if d.ValidFrom <= day && d.ValidFrom > mod {
				mod = d.ValidFrom
			}
		}
		if ds.ValidFrom <= day && ds.ValidFrom > mod {
			mod = ds.ValidFrom
		}
		if sc.Kind == tariffs.FuelCO2 {
			fv := fuelView{Name: ds.Name, From: ds.ValidFrom, Law: ds.Method(), Sources: ds.Sources()}
			fv.Rate, fv.PerLitre = fuelRate(ds, today)
			fv.Versions = versions(sc, day, func(d *tariffs.Dataset) (string, string) { r, l := fuelRate(d, today); return r, l })
			v.Fuel = append(v.Fuel, fv)
			if sc.Current != nil {
				row.Fuel = fv.PerLitre
			}
			continue
		}
		pday := priceDay(ds, day)
		sv := schemeView{Name: ds.Name, Kind: sc.Kind, How: kindHow(ds), From: ds.ValidFrom, To: ds.ValidTo, Method: ds.Method(), File: ds.File,
			Cur: ds.Doc.Header.Currency, Liable: ds.Doc.Liable.Description, Sources: ds.Sources(), Upcoming: sc.Current == nil}
		if sc.Kind == tariffs.Toll || sc.Kind == tariffs.Crossings {
			hows = append(hows, kindHow(ds))
		}
		// Per km.
		roads := kmRates(ds, truck40, pday)
		for i, r := range roads {
			f := fig(r.Rate, r.Road, today)
			f.Highlight = i == 0
			sv.Roads = append(sv.Roads, f)
			if e, ok := toEUR(r.Rate.Total, r.Rate.Cur, today); ok && r.Full && sc.Current != nil && sc.Kind == tariffs.Toll {
				kmScheme = true
				if lo < 0 || e < lo {
					lo = e
				}
				if e > hi {
					hi = e
				}
				sh := r.Rate.share()
				if shLo == 0 && shHi == 0 || sh < shLo {
					shLo = sh
				}
				if sh > shHi {
					shHi = sh
				}
			}
		}
		if len(roads) > 0 {
			obj, _ := kmRoads(ds, pday)
			obj0 := obj[0]
			for _, m := range byMass {
				a := perKm(ds, obj0, m.Truck, pday)
				if a.OK {
					sv.ByMass = append(sv.ByMass, fig(a, m.Label, today))
				}
			}
			for cl := 1; cl <= 5; cl++ {
				t := truck40
				t.CO2Class = cl
				a := perKm(ds, obj0, t, pday)
				label := fmt.Sprintf("CO2 class %d", cl)
				if cl == 5 {
					label += " (zero-emission)"
				}
				if a.OK {
					sv.ByCO2 = append(sv.ByCO2, fig(a, label, today))
				}
			}
			for _, e := range []int{6, 5, 4, 3, 2, 1, 0} {
				t := truck40
				t.Euro = e
				a := perKm(ds, obj0, t, pday)
				if a.OK {
					sv.ByEuro = append(sv.ByEuro, fig(a, "Euro "+roman[fmt.Sprint(e)], today))
				}
			}
			if same(sv.ByCO2) {
				sv.ByCO2 = nil
			}
			if same(sv.ByEuro) {
				sv.ByEuro = nil
			}
			if same(sv.ByMass) {
				sv.ByMass = nil
			}
			r := roads[0]
			var ps []string
			for _, p := range r.Rate.scaled(100).Parts {
				ps = append(ps, lowerWord(p.Name)+" "+money(p.Amount, r.Rate.Cur))
			}
			sv.Example = fmt.Sprintf("A 40 t, 5-axle Euro VI diesel truck (CO2 class 1) driving 100 km on %s pays %s", lowerWord(r.Road), money(r.Rate.Total*100, r.Rate.Cur))
			if len(ps) > 1 {
				sv.Example += ": " + strings.Join(ps, ", ")
			}
			sv.Example += "."
			// Zero-emission.
			ze := perKm(ds, obj0, zeTruck, pday)
			until, note, ok := zeRule(ds)
			switch {
			case ok && ze.Total == 0:
				sv.ZE = note
				after := dayAfter(until)
				if ds.ValidTo == "" || ds.ValidTo >= after {
					if za := perKm(ds, obj0, zeTruck, after); za.OK {
						sv.ZE += fmt.Sprintf(" From %s, as the law stands, a zero-emission 40 t truck pays %s per km on %s.", dateName(after), money(za.Total, za.Cur), lowerWord(r.Road))
					}
				}
			case ze.OK && ze.Total < r.Rate.Total:
				sv.ZE = fmt.Sprintf("A zero-emission 40 t truck (CO2 class 5) pays %s per km on %s, %s less than the diesel truck.",
					money(ze.Total, ze.Cur), lowerWord(r.Road), pct(r.Rate.Total-ze.Total, r.Rate.Total))
			case ze.OK:
				sv.ZE = "Zero-emission trucks pay the same as diesel trucks."
			}
			if sc.Current != nil && sc.Kind == tariffs.Toll {
				switch {
				case ok && ze.Total == 0:
					row.ZE = "Free until " + until[:4]
				case ze.OK && ze.Total < r.Rate.Total:
					row.ZE = pct(r.Rate.Total-ze.Total, r.Rate.Total) + " less"
				case ze.OK && row.ZE == "–":
					row.ZE = "No reduction"
				}
			}
		}
		// Trips, passages and vignettes.
		var fares []fare
		for i := range ds.Doc.Charges {
			ch := &ds.Doc.Charges[i]
			switch ch.Type {
			case "od":
				fs, st, pairs := odFares(ds, ch, truck40, pday, 10)
				fares = append(fares, fs...)
				if st > 0 {
					sv.FareNote += fmt.Sprintf("%s: %s stations, %s trips priced. ", nameOr(ch), thousands(st), thousands(pairs))
					if sc.Kind == tariffs.Toll {
						nSt, nTrips = nSt+st, nTrips+pairs
					}
				}
			case "point", "section":
				if ch.Unit == "km" {
					continue
				}
				fs, n := pointFares(ds, ch, truck40, pday, 12)
				fares = append(fares, fs...)
				if n > 0 {
					sv.FareNote += fmt.Sprintf("%s: %s %s. ", nameOr(ch), thousands(n), map[bool]string{true: "places", false: "place"}[n != 1])
					nPlaces += n
				}
			case "period":
				for _, f := range products(ds, ch, truck40) {
					sv.Products = append(sv.Products, fareRow{f.What, money(f.Rate.Total, f.Rate.Cur), ""})
				}
				if sv.Example == "" && len(sv.Products) > 0 {
					sv.Example = fmt.Sprintf("A 40 t, 5-axle Euro VI truck pays %s for a vignette of %s.", sv.Products[0].Total, sv.Products[0].What)
				}
			}
			if ch.Type != "quantity" {
				sv.Tables = append(sv.Tables, fullTable(ds, ch, 200))
			}
		}
		sort.SliceStable(fares, func(i, j int) bool { return fares[i].Rate.Total > fares[j].Rate.Total })
		if len(fares) > 0 && sc.Kind == tariffs.Toll && sc.Current != nil && top == nil {
			top = &fares[0]
		}
		if sv.Example == "" && len(fares) > 0 {
			f := fares[0]
			if strings.Contains(f.What, " – ") {
				sv.Example = fmt.Sprintf("A 40 t, 5-axle Euro VI truck pays %s from %s.", money(f.Rate.Total, f.Rate.Cur), strings.Replace(f.What, " – ", " to ", 1))
			} else {
				sv.Example = fmt.Sprintf("A 40 t, 5-axle Euro VI truck pays %s at %s.", money(f.Rate.Total, f.Rate.Cur), f.What)
			}
		}
		for i, f := range fares {
			if i == 12 {
				break
			}
			sv.Fares = append(sv.Fares, fareRow{f.What, money(f.Rate.Total, f.Rate.Cur), ""})
		}
		sv.Versions = versions(sc, day, func(d *tariffs.Dataset) (string, string) {
			rs := kmRates(d, truck40, priceDay(d, day))
			if len(rs) == 0 {
				return "", ""
			}
			return money(rs[0].Rate.Total, rs[0].Rate.Cur), money(rs[0].Rate.CO2, rs[0].Rate.Cur)
		})
		v.Schemes = append(v.Schemes, sv)
		if cd.Title == "" && len(roads) > 0 && sc.Kind == tariffs.Toll {
			r := roads[0].Rate
			cd = card{Big: money(r.Total, r.Cur) + " per km", BigNote: truck40Label + ", " + lowerWord(roads[0].Road)}
			if r.CO2 > 0 {
				cd.Accent, cd.AccentCO = fmt.Sprintf("CO2 part: %s per km (%s)", money(r.CO2, r.Cur), pct(r.CO2, r.Total)), "carbon"
			}
		}
	}
	if kmScheme {
		row.Rate = money(lo, "EUR")
		if hi-lo > 0.0005 {
			row.Rate += "–" + money(hi, "EUR")
		}
		row.Share = fmt.Sprintf("%.0f%%", shLo*100)
		if shHi-shLo > 0.005 {
			row.Share = fmt.Sprintf("%.0f–%.0f%%", shLo*100, shHi*100)
		}
	}
	row.How = strings.Join(dedupe(hows), "; ")
	if row.How == "" {
		row.How = "CO2 price on fuel only"
	}
	// Words.
	local := ""
	if c.Local != "" {
		local = " (" + c.Local + ")"
	}
	if kmScheme {
		v.H1 = fmt.Sprintf("%s truck toll %d%s: rates per km by weight, Euro and CO2 class", c.Name, year, local)
	} else if row.How == "CO2 price on fuel only" {
		v.H1 = fmt.Sprintf("%s CO2 tax on diesel %d: the rate per litre for trucks", c.Name, year)
	} else {
		v.H1 = fmt.Sprintf("%s truck tolls %d%s: %s for trucks over 3.5 t", c.Name, year, local, row.How)
	}
	var size []string
	if nSt > 0 {
		size = append(size, fmt.Sprintf("%s toll stations and %s trips", thousands(nSt), thousands(nTrips)))
	}
	if nPlaces > 0 {
		size = append(size, fmt.Sprintf("%s toll points, bridges and tunnels", thousands(nPlaces)))
	}
	desc := fmt.Sprintf("%s truck tolls %d%s for trucks over 3.5 t: %s", c.Name, year, local, row.How)
	if len(size) > 0 {
		desc += ", " + strings.Join(size, " and ")
	}
	desc += ", from the law and the official tariffs."
	if top != nil {
		desc += fmt.Sprintf(" A 40 t Euro VI truck pays up to %s for one trip or passage.", money(top.Rate.Total, top.Rate.Cur))
	}
	desc += " Full rate tables, history, changes to come and the law behind each rate."
	if row.How == "CO2 price on fuel only" && len(v.Fuel) > 0 {
		desc = fmt.Sprintf("%s's CO2 tax on diesel in %d from the law: %s (%s per litre), its history and the changes to come.", c.Name, year, v.Fuel[0].Rate, v.Fuel[0].PerLitre)
	}
	if kmScheme {
		co2 := ""
		if shHi > 0 {
			co2 = " (CO2 part " + row.Share + ")"
		}
		desc = fmt.Sprintf("%s truck toll %d%s: a 40 t Euro VI truck pays %s per km%s. Rates by weight, Euro and CO2 class, history and upcoming changes, with the law behind each rate.",
			c.Name, year, local, row.Rate, co2)
	}
	v.Lead = desc
	v.Trip, v.TripName = s.trip(c.Code)
	v.Sources = sources(all...)
	v.Updated = mod
	path := "/tolls/" + c.Slug
	ld := s.datasetLD(path, fmt.Sprintf("%s truck tolls %d", c.Name, year), desc+" ORCT rate tables, one per scheme and version.", c.Name, files, mod)
	var basedOn []string
	for _, src := range v.Sources {
		basedOn = append(basedOn, src.URL)
	}
	if len(basedOn) > 0 {
		ld["isBasedOn"] = basedOn
	}
	title := v.H1
	v.Head = s.mkHead(path, title, short(desc, 300), ld, link{"Truck tolls", s.prefix + "/tolls"}, link{c.Name, s.prefix + path})
	cd.Kicker, cd.Footer = "carbon-cost · truck tolls", hostPath(s.base)+path
	cd.Title = fmt.Sprintf("%s truck toll%s %d%s", c.Name, map[bool]string{true: "", false: "s"}[kmScheme], year, local)
	if cd.Big == "" {
		cd.Big = capital(row.How)
		cd.BigNote = "Rates for trucks over 3.5 t, from the law"
		if len(size) > 0 {
			cd.Accent = capital(strings.Join(size, ", "))
		}
	}
	return v, row, cd, mod
}

// lowerWord lowercases a name's first letter, unless it starts an
// acronym ("CO2", "A1") or a proper name the data spells so.
func lowerWord(s string) string {
	r := []rune(s)
	if len(r) > 1 && unicode.IsUpper(r[0]) && unicode.IsLower(r[1]) && !strings.Contains(s, "S.p.A") {
		return string(unicode.ToLower(r[0])) + string(r[1:])
	}
	return s
}

// thousands writes n with thousands separators: 27,915.
func thousands(n int) string {
	s := fmt.Sprint(n)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}

func nameOr(ch *orct.Charge) string {
	if ch.Name != "" {
		return ch.Name
	}
	return componentName(ch)
}

func same(rs []figRow) bool {
	for _, r := range rs[min(1, len(rs)):] {
		if r.Total != rs[0].Total || r.CO2 != rs[0].CO2 {
			return false
		}
	}
	return true
}

func dedupe(xs []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, x := range xs {
		for _, p := range strings.Split(x, "; ") {
			if p != "" && !seen[p] {
				seen[p] = true
				out = append(out, p)
			}
		}
	}
	return out
}

// fuelRate is a fuel CO2 dataset's rate as the law says it, and per litre
// of diesel in euros.
func fuelRate(ds *tariffs.Dataset, day time.Time) (string, string) {
	for i := range ds.Doc.Charges {
		ch := &ds.Doc.Charges[i]
		if ch.Type != "quantity" || len(ch.Rows) == 0 {
			continue
		}
		v := rowAmount(ch, ch.Rows[0])
		cur := ds.Doc.Header.Currency
		rate := money(v, cur) + " " + unitName(ch.Unit)
		perL := v
		if ch.Unit == "t_co2" {
			perL = v * cost.DieselKgCO2PerL / 1000
		} else if ch.Unit != "litre" {
			return rate, "–"
		}
		if e, ok := toEUR(perL, cur, day); ok {
			return rate, money(e, "EUR")
		}
		return rate, money(perL, cur)
	}
	return "–", "–"
}

func sortRows(rows []crossRow) {
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].Cells[0] < rows[j].Cells[0] })
}

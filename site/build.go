package site

import (
	"fmt"
	"html/template"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// The pages are priced once a day (countryData, by the calculator's code)
// and written in each language (countryView).

// ---- Priced data ----

type massRate struct {
	Truck rates.Truck
	A     amount
}

type euroRate struct {
	Euro int
	A    amount
}

type zeData struct {
	Kind       string // "free" (exempt), "less", "same" or ""
	Until      string
	After      string // the day after the exemption
	AfterRate  amount
	AfterOK    bool
	ZE, Diesel amount
	Road       string
}

type versionData struct {
	Ds      *tariffs.Dataset
	Rate    amount
	HasRate bool
}

type schemeData struct {
	Sc                        *scheme
	Ds                        *tariffs.Dataset
	Hows                      []string
	Roads                     []roadRate
	ByMass                    []massRate
	ByCO2                     []amount // CO2 class 1 to 5
	ByEuro                    []euroRate
	ZE                        zeData
	Fares                     []fare // dearest first, 12 at most
	NOD, NSt, NTrips, NPlaces int
	Cap                       bool
	Load                      bool // fares by the load's weight, priced with exampleLoadKg
	Products                  []fare
	Versions                  []versionData
	ExampleKind               string // "km", "od", "point", "vignette"
}

type fuelRateT struct {
	V         float64
	Unit, Cur string
	PerL      float64 // in Cur
	PerLEUR   float64
	OK, EUROK bool
}

type fuelVersion struct {
	Ds   *tariffs.Dataset
	Rate fuelRateT
}

type fuelData struct {
	Sc       *scheme
	Ds       *tariffs.Dataset
	Rate     fuelRateT
	Versions []fuelVersion
}

type countryData struct {
	C                  *country
	Schemes            []*schemeData
	Fuel               []*fuelData
	KmScheme           bool
	Lo, Hi, ShLo, ShHi float64
	ZEKind             string
	ZEUntil            string
	ZEPct              float64
	FuelPerL           *fuelRateT
	NSt, NTrips, NPl   int
	Top                *fare
	First              *roadRate // the card's figure
	FirstDs            *tariffs.Dataset
	Mod                string
	Files              []string
	All                []*tariffs.Dataset
}

// kindHows are a scheme's ways of charging (message ids).
func kindHows(ds *tariffs.Dataset) []string {
	seen := map[string]bool{}
	var hows []string
	for i := range ds.Doc.Charges {
		ch := &ds.Doc.Charges[i]
		var h string
		switch {
		case ch.Type == "distance" && ch.Unit == "tkm":
			h = "how.tkm"
		case ch.Type == "distance":
			h = "how.km"
		case ch.Type == "section":
			h = "how.section"
		case ch.Type == "od":
			h = "how.od"
		case ch.Type == "point":
			h = "how.point"
		case ch.Type == "period":
			h = "how.period"
		case ch.Type == "area":
			h = "how.area"
		case ch.Type == "quantity":
			h = "how.fuel"
		default:
			continue
		}
		if !seen[h] {
			seen[h] = true
			hows = append(hows, h)
		}
	}
	return hows
}

func classesTest(ds *tariffs.Dataset, param string) bool {
	for _, s := range ds.Doc.Sets {
		for _, cl := range s.Classes {
			if _, ok := cl.Criteria[param]; ok {
				return true
			}
		}
	}
	return false
}

// fuelRateOf is a fuel CO2 dataset's rate, and per litre of diesel.
func fuelRateOf(ds *tariffs.Dataset, day time.Time) fuelRateT {
	for i := range ds.Doc.Charges {
		ch := &ds.Doc.Charges[i]
		if ch.Type != "quantity" || len(ch.Rows) == 0 {
			continue
		}
		r := fuelRateT{V: rowAmount(ch, ch.Rows[0]), Unit: ch.Unit, Cur: ds.Doc.Header.Currency, OK: true}
		switch ch.Unit {
		case "t_co2":
			r.PerL = r.V * cost.DieselKgCO2PerL / 1000
		case "litre":
			r.PerL = r.V
		default:
			return r
		}
		r.PerLEUR, r.EUROK = toEUR(r.PerL, r.Cur, day)
		return r
	}
	return fuelRateT{}
}

// price works out a country's figures on the day.
func price(c *country, day string, today time.Time) *countryData {
	d := &countryData{C: c, Lo: -1}
	for _, sc := range c.Schemes {
		ds := sc.latest()
		d.All = append(d.All, ds)
		d.Files = append(d.Files, ds.File)
		for _, x := range append(append([]*tariffs.Dataset{ds}, sc.Past...), sc.Upcoming...) {
			if x.ValidFrom <= day && x.ValidFrom > d.Mod {
				d.Mod = x.ValidFrom
			}
		}
		if sc.Kind == tariffs.FuelCO2 {
			f := &fuelData{Sc: sc, Ds: ds, Rate: fuelRateOf(ds, today)}
			for _, v := range history(sc) {
				f.Versions = append(f.Versions, fuelVersion{v, fuelRateOf(v, today)})
			}
			d.Fuel = append(d.Fuel, f)
			if sc.Current != nil && d.FuelPerL == nil && f.Rate.EUROK {
				d.FuelPerL = &f.Rate
			}
			continue
		}
		pday := priceDay(ds, day)
		sd := &schemeData{Sc: sc, Ds: ds, Hows: kindHows(ds)}
		sd.Roads = kmRates(ds, truck40, pday)
		current := sc.Current != nil && sc.Kind == tariffs.Toll
		for _, r := range sd.Roads {
			if e, ok := toEUR(r.Rate.Total, r.Rate.Cur, today); ok && r.Full && current {
				d.KmScheme = true
				if d.Lo < 0 || e < d.Lo {
					d.Lo = e
				}
				d.Hi = max(d.Hi, e)
				sh := r.Rate.share()
				if d.ShLo == 0 && d.ShHi == 0 || sh < d.ShLo {
					d.ShLo = sh
				}
				d.ShHi = max(d.ShHi, sh)
			}
		}
		if len(sd.Roads) > 0 {
			obj := sd.Roads[0].Obj
			for _, m := range byMass {
				if a := perKm(ds, obj, m.Truck, pday); a.OK {
					sd.ByMass = append(sd.ByMass, massRate{m.Truck, a})
				}
			}
			for cl := 1; cl <= 5; cl++ {
				t := truck40
				t.CO2Class = cl
				if a := perKm(ds, obj, t, pday); a.OK {
					sd.ByCO2 = append(sd.ByCO2, a)
				}
			}
			for _, e := range []int{6, 5, 4, 3, 2, 1, 0} {
				t := truck40
				t.Euro = e
				if a := perKm(ds, obj, t, pday); a.OK {
					sd.ByEuro = append(sd.ByEuro, euroRate{e, a})
				}
			}
			if sameAll(len(sd.ByMass), func(i int) amount { return sd.ByMass[i].A }) {
				sd.ByMass = nil
			}
			if len(sd.ByCO2) != 5 || sameAll(len(sd.ByCO2), func(i int) amount { return sd.ByCO2[i] }) {
				sd.ByCO2 = nil
			}
			if sameAll(len(sd.ByEuro), func(i int) amount { return sd.ByEuro[i].A }) {
				sd.ByEuro = nil
			}
			sd.ExampleKind = "km"
			// Zero-emission.
			r := sd.Roads[0]
			ze := perKm(ds, obj, zeTruck, pday)
			z := zeData{ZE: ze, Diesel: r.Rate, Road: obj}
			until, _, ok := zeRule(ds)
			switch {
			case ok && ze.Total == 0:
				z.Kind, z.Until, z.After = "free", until, dayAfter(until)
				if ds.ValidTo == "" || ds.ValidTo >= z.After {
					z.AfterRate = perKm(ds, obj, zeTruck, z.After)
					z.AfterOK = z.AfterRate.OK
				}
			case ze.OK && ze.Total < r.Rate.Total:
				z.Kind = "less"
			case ze.OK:
				z.Kind = "same"
			}
			sd.ZE = z
			if current {
				switch {
				case z.Kind == "free":
					d.ZEKind, d.ZEUntil = "free", until
				case z.Kind == "less" && d.ZEKind == "":
					d.ZEKind, d.ZEPct = "less", (r.Rate.Total-ze.Total)/r.Rate.Total
				case z.Kind == "same" && d.ZEKind == "":
					d.ZEKind = "none"
				}
			}
			if d.First == nil && sc.Kind == tariffs.Toll {
				d.First, d.FirstDs = &sd.Roads[0], ds
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
					sd.NOD, sd.NSt, sd.NTrips = sd.NOD+1, sd.NSt+st, sd.NTrips+pairs
				}
			case "point", "section":
				if ch.Unit == "km" {
					continue
				}
				fs, n := pointFares(ds, ch, truck40, pday, 12)
				fares = append(fares, fs...)
				sd.NPlaces += n
			case "period":
				sd.Products = append(sd.Products, products(ds, ch, truck40)...)
			}
		}
		byLoad := false
		for i := range ds.Doc.Charges {
			byLoad = byLoad || ds.Doc.Charges[i].MassBasis == "load_kg"
		}
		if byLoad {
			fares = sumByPlaces(ds, fares) // the truck's fare and its load's, one trip
		}
		sort.SliceStable(fares, func(i, j int) bool { return fares[i].Rate.Total > fares[j].Rate.Total })
		if len(fares) > 12 {
			fares = fares[:12]
		}
		sd.Fares = fares
		sd.Cap = len(fares) > 0 && classesTest(ds, "load_capacity_kg")
		sd.Load = len(fares) > 0 && byLoad
		if sd.ExampleKind == "" {
			switch {
			case len(fares) > 0 && fares[0].To != "":
				sd.ExampleKind = "od"
			case len(fares) > 0:
				sd.ExampleKind = "point"
			case len(sd.Products) > 0:
				sd.ExampleKind = "vignette"
			}
		}
		if sc.Kind == tariffs.Toll {
			d.NSt, d.NTrips, d.NPl = d.NSt+sd.NSt, d.NTrips+sd.NTrips, d.NPl+sd.NPlaces
			if len(fares) > 0 && sc.Current != nil && d.Top == nil {
				d.Top = &sd.Fares[0]
			}
		}
		for _, v := range history(sc) {
			vd := versionData{Ds: v}
			if rs := kmRates(v, truck40, priceDay(v, day)); len(rs) > 0 {
				vd.Rate, vd.HasRate = rs[0].Rate, true
			}
			sd.Versions = append(sd.Versions, vd)
		}
		d.Schemes = append(d.Schemes, sd)
	}
	return d
}

// sameAll says whether the n amounts are all the same.
func sameAll(n int, at func(int) amount) bool {
	for i := 1; i < n; i++ {
		if round4(at(i).Total) != round4(at(0).Total) || round4(at(i).CO2) != round4(at(0).CO2) {
			return false
		}
	}
	return true
}

// history is a scheme's versions, newest first.
func history(sc *scheme) []*tariffs.Dataset {
	var all []*tariffs.Dataset
	for i := len(sc.Upcoming) - 1; i >= 0; i-- {
		all = append(all, sc.Upcoming[i])
	}
	if sc.Current != nil {
		all = append(all, sc.Current)
	}
	return append(all, sc.Past...)
}

// ---- Views ----

type figRow struct {
	Label, Total, CO2, Share, EUR string
	Highlight                     bool
}

type fareRow struct {
	What, Total string
}

type versionRow struct {
	From, To, Rate, CO2, Law, File string
	Upcoming, Current              bool
}

type schemeView struct {
	Name, How, From, To, Method, File, Cur string
	Liable                                 string
	Roads                                  []figRow
	ByMass, ByCO2, ByEuro                  []figRow
	ZE                                     string
	Fares                                  []fareRow
	FareNote                               string
	Products                               []fareRow
	Tables                                 []rateTable
	Versions                               []versionRow
	HasRate                                bool
	Example                                string
	Sources                                []tariffs.Source
	Upcoming                               bool
}

type fuelView struct {
	Name, Rate, PerLitre, From, Law string
	Versions                        []versionRow
	Sources                         []tariffs.Source
}

type countryView struct {
	Head
	H1, Lead          string
	Schemes           []schemeView
	Fuel              []fuelView
	Trip              string
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
	H1, Lead          string
	Rows              []overviewRow
	FXNote            string
	Updated           string
	Others, Countries []link
}

type crossRow struct {
	Cells []string
	Href  string
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

// Cross-country pages: their paths and title messages.
var crossPages = []struct {
	Path, Title string
	EnglishOnly bool
}{
	{"/tolls/zero-emission-trucks", "x.ze.link", false},
	{"/tolls/ets2-diesel", "x.ets2.link", false},
	{"/tolls/co2-tax-diesel", "x.fuel.link", false},
	{ferryPath, "x.ferry.link", true},
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

func (s *Site) trip(l *Loc, cc string) (href, name string) {
	t, ok := trips[cc]
	if !ok {
		return s.prefix + "/", ""
	}
	a, b := fmt.Sprint(t[0][0]), fmt.Sprint(t[1][0])
	// The country's own languages say its places' own names.
	for _, x := range local[cc] {
		if x == l.Code {
			a, b = endonym(a), endonym(b)
		}
	}
	q := fmt.Sprintf("from=%v,%v&from_name=%s&to=%v,%v&to_name=%s", t[0][1], t[0][2], urlq(a), t[1][1], t[1][2], urlq(b))
	return s.prefix + "/?" + q, l.T("cta.trip", "from", a, "to", b)
}

// localWords are a toll's own name in its own script, where the
// English page spells it in Latin letters.
var localWords = map[[2]string]string{{"GR", "el"}: "διόδια"}

// endonyms are the trips' places in their own language.
var endonyms = map[string]string{
	"Vienna": "Wien", "Antwerp": "Antwerpen", "Sofia": "София", "Plovdiv": "Пловдив", "Brest": "Брест", "Minsk": "Минск",
	"Prague": "Praha", "Munich": "München", "Copenhagen": "København", "Athens": "Αθήνα", "Thessaloniki": "Θεσσαλονίκη",
	"Milan": "Milano", "Riga": "Rīga", "Skopje": "Скопје", "Gevgelija": "Гевгелија", "Warsaw": "Warszawa", "Lisbon": "Lisboa",
	"Bucharest": "București", "Belgrade": "Beograd", "Gothenburg": "Göteborg", "Istanbul": "İstanbul", "Tirana": "Tiranë",
}

func endonym(s string) string {
	if e, ok := endonyms[s]; ok {
		return e
	}
	return s
}

func urlq(v any) string {
	return strings.ReplaceAll(template.URLQueryEscaper(fmt.Sprint(v)), "+", "%20")
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

func hostPath(base string) string {
	return strings.TrimPrefix(strings.TrimPrefix(base, "https://"), "http://")
}

func (l *Loc) fig(a amount, label string, day time.Time) figRow {
	r := figRow{Label: label, Total: l.Money(a.Total, a.Cur), CO2: "–", Share: "–"}
	if a.CO2 > 0 {
		r.CO2, r.Share = l.Money(a.CO2, a.Cur), l.Pct(a.CO2, a.Total)
	} else if a.Total > 0 {
		r.CO2, r.Share = l.Money(0, a.Cur), l.PctOf(0)
	}
	if a.Cur != "EUR" {
		if e, ok := toEUR(a.Total, a.Cur, day); ok {
			r.EUR = l.Money(e, "EUR")
		}
	}
	return r
}

// lower lowercases a name's first letter inside a sentence, unless it
// starts an acronym ("CO2", "A1") or the language capitalises nouns.
func (l *Loc) lower(s string) string {
	if l.Code == "de" {
		return s
	}
	return lowerWord(s)
}

// lowerWord lowercases a name's first letter, unless it starts an
// acronym ("CO2", "A1").
func lowerWord(s string) string {
	r := []rune(s)
	if len(r) > 1 && strings.ToUpper(string(r[0])) == string(r[0]) && strings.ToLower(string(r[1])) == string(r[1]) && strings.ToUpper(string(r[1])) != string(r[1]) {
		return strings.ToLower(string(r[0])) + string(r[1:])
	}
	return s
}

func (l *Loc) fareName(ds *tariffs.Dataset, f fare) string {
	switch {
	case f.Period != "":
		return l.productName(f.Period)
	case f.To != "":
		return l.objectName(ds, f.From) + " – " + l.objectName(ds, f.To)
	}
	return l.objectName(ds, f.From)
}

func (l *Loc) hows(ids []string) string {
	var out []string
	for _, h := range ids {
		out = append(out, l.T(h))
	}
	return strings.Join(out, "; ")
}

// countryHows are a country's ways of charging, tolls and crossings.
func countryHows(d *countryData) []string {
	seen := map[string]bool{}
	var out []string
	for _, sd := range d.Schemes {
		if sd.Sc.Kind != tariffs.Toll && sd.Sc.Kind != tariffs.Crossings {
			continue
		}
		for _, h := range sd.Hows {
			if !seen[h] {
				seen[h] = true
				out = append(out, h)
			}
		}
	}
	return out
}

func (l *Loc) sizeWords(d *countryData) []string {
	var size []string
	if d.NSt > 0 {
		size = append(size, l.T("c.size.od", "stations", l.Int(d.NSt), "trips", l.Int(d.NTrips)))
	}
	if d.NPl > 0 {
		size = append(size, l.T("c.size.points", "n", l.Int(d.NPl)))
	}
	return size
}

func (s *Site) countryView(l *Loc, d *countryData, day string, today time.Time, year int) (countryView, overviewRow, card) {
	c := d.C
	name := l.Country(c.Code)
	path := s.pagePath(l.Code, "/tolls/"+c.Slug)
	v := countryView{}
	row := overviewRow{Name: name, Href: s.prefix + path, Rate: "–", Share: "–", ZE: "–", Fuel: "–"}
	for _, f := range d.Fuel {
		fv := fuelView{Name: f.Ds.Name, From: l.Date(f.Ds.ValidFrom), Law: lawOnly(f.Ds.Method()), Sources: f.Ds.Sources()}
		fv.Rate, fv.PerLitre = l.fuelText(f.Rate)
		for _, x := range f.Versions {
			r, pl := l.fuelText(x.Rate)
			fv.Versions = append(fv.Versions, l.versionRow(x.Ds, f.Sc, day, r, pl))
		}
		v.Fuel = append(v.Fuel, fv)
	}
	if d.FuelPerL != nil {
		row.Fuel = l.Money(d.FuelPerL.PerLEUR, "EUR")
	}
	for _, sd := range d.Schemes {
		ds := sd.Ds
		sv := schemeView{Name: ds.Name, How: l.hows(sd.Hows), From: l.Date(ds.ValidFrom), Method: lawOnly(ds.Method()), File: ds.File,
			Cur: ds.Doc.Header.Currency, Sources: ds.Sources(), Upcoming: sd.Sc.Current == nil}
		if ds.ValidTo != "" {
			sv.To = l.Date(ds.ValidTo)
		}
		sv.Liable = ds.Doc.Liable.Description
		if l.Code != "en" && len(ds.Doc.Liable.Criteria) > 0 {
			sv.Liable = l.criteria(ds.Doc.Liable.Criteria)
			if r := []rune(sv.Liable); len(r) > 0 && !unicode.IsLetter(r[0]) {
				sv.Liable = l.T("cr.vehicles", "x", sv.Liable)
			}
		}
		for i, r := range sd.Roads {
			f := l.fig(r.Rate, l.objectName(ds, r.Obj), today)
			f.Highlight = i == 0
			sv.Roads = append(sv.Roads, f)
		}
		for _, m := range sd.ByMass {
			sv.ByMass = append(sv.ByMass, l.fig(m.A, l.T("mass.label", "t", l.Dec(float64(m.Truck.MaxMassKg)/1000), "axles", m.Truck.Axles), today))
		}
		for i, a := range sd.ByCO2 {
			label := l.T("co2.label", "n", i+1)
			if i == 4 {
				label = l.T("cr.ze")
			}
			sv.ByCO2 = append(sv.ByCO2, l.fig(a, label, today))
		}
		for _, e := range sd.ByEuro {
			sv.ByEuro = append(sv.ByEuro, l.fig(e.A, "Euro "+roman[fmt.Sprint(e.Euro)], today))
		}
		switch z := sd.ZE; z.Kind {
		case "free":
			sv.ZE = l.T("c.ze.free", "date", l.Date(z.Until))
			if z.AfterOK {
				sv.ZE += " " + l.T("c.ze.after", "date", l.Date(z.After), "amount", l.Money(z.AfterRate.Total, z.AfterRate.Cur), "road", l.lower(l.objectName(ds, z.Road)))
			}
		case "less":
			sv.ZE = l.T("c.ze.less", "amount", l.Money(z.ZE.Total, z.ZE.Cur), "road", l.lower(l.objectName(ds, z.Road)), "pct", l.Pct(z.Diesel.Total-z.ZE.Total, z.Diesel.Total))
		case "same":
			sv.ZE = l.T("c.ze.same")
		}
		switch sd.ExampleKind {
		case "km":
			r := sd.Roads[0]
			a := r.Rate.scaled(100)
			sv.Example = l.T("c.ex.km", "road", l.lower(l.objectName(ds, r.Obj)), "amount", l.Money(a.Total, a.Cur))
			if len(a.Parts) > 1 {
				var ps []string
				for _, p := range a.Parts {
					ps = append(ps, l.lower(l.componentName(p.Charge))+" "+l.Money(p.Amount, a.Cur))
				}
				sv.Example += l.T("c.ex.parts", "parts", strings.Join(ps, ", "))
			}
			sv.Example += "."
		case "od":
			f := sd.Fares[0]
			sv.Example = l.T("c.ex.od", "amount", l.Money(f.Rate.Total, f.Rate.Cur), "from", l.objectName(ds, f.From), "to", l.objectName(ds, f.To))
		case "point":
			f := sd.Fares[0]
			sv.Example = l.T("c.ex.point", "amount", l.Money(f.Rate.Total, f.Rate.Cur), "place", l.objectName(ds, f.From))
		case "vignette":
			f := sd.Products[0]
			sv.Example = l.T("c.ex.vignette", "amount", l.Money(f.Rate.Total, f.Rate.Cur), "period", l.productName(f.Period))
		}
		for _, f := range sd.Fares {
			sv.Fares = append(sv.Fares, fareRow{l.fareName(ds, f), l.Money(f.Rate.Total, f.Rate.Cur)})
		}
		var notes []string
		if sd.NOD > 0 {
			notes = append(notes, l.T("c.fares.od", "systems", l.Int(sd.NOD), "stations", l.Int(sd.NSt), "trips", l.Int(sd.NTrips)))
		}
		if sd.NPlaces > 0 {
			notes = append(notes, l.T("c.fares.points", "n", l.Int(sd.NPlaces)))
		}
		if sd.Cap {
			notes = append(notes, l.T("c.fares.cap"))
		}
		if sd.Load {
			notes = append(notes, l.T("c.fares.load"))
		}
		sv.FareNote = strings.Join(notes, " ")
		for _, p := range sd.Products {
			sv.Products = append(sv.Products, fareRow{l.productName(p.Period), l.Money(p.Rate.Total, p.Rate.Cur)})
		}
		for i := range ds.Doc.Charges {
			if ch := &ds.Doc.Charges[i]; ch.Type != "quantity" {
				sv.Tables = append(sv.Tables, l.fullTable(ds, ch, 200))
			}
		}
		for _, x := range sd.Versions {
			r, co2 := "", ""
			if x.HasRate {
				r, co2 = l.Money(x.Rate.Total, x.Rate.Cur), l.Money(x.Rate.CO2, x.Rate.Cur)
				sv.HasRate = true
			}
			sv.Versions = append(sv.Versions, l.versionRow(x.Ds, sd.Sc, day, r, co2))
		}
		v.Schemes = append(v.Schemes, sv)
	}
	// The overview's row.
	if d.KmScheme {
		row.Rate = l.Money(d.Lo, "EUR")
		if d.Hi-d.Lo > 0.0005 {
			row.Rate += "–" + l.Money(d.Hi, "EUR")
		}
		row.Share = l.PctOf(d.ShLo)
		if d.ShHi-d.ShLo > 0.005 {
			row.Share = l.PctOf(d.ShLo) + "–" + l.PctOf(d.ShHi)
		}
	}
	switch d.ZEKind {
	case "free":
		row.ZE = l.T("ze.free.until", "year", d.ZEUntil[:4])
	case "less":
		row.ZE = l.T("ze.less", "pct", l.PctOf(d.ZEPct))
	case "none":
		row.ZE = l.T("ze.none")
	}
	hows := countryHows(d)
	row.How = l.hows(hows)
	fuelOnly := len(hows) == 0
	if fuelOnly {
		row.How = l.T("how.fuelonly")
	}
	// Words.
	loc := ""
	// The toll's own name, unless the language's words say it already.
	local := c.Local
	if w, ok := localWords[[2]string{c.Code, l.Code}]; ok {
		local = w
	}
	if local != "" && !strings.Contains(strings.ToLower(l.T("c.h1.km", "country", name, "year", year, "local", "")), strings.ToLower(local)) {
		loc = " (" + local + ")"
	}
	switch {
	case d.KmScheme:
		v.H1 = l.T("c.h1.km", "country", name, "year", year, "local", loc)
		co2 := ""
		if d.ShHi > 0 {
			co2 = l.T("c.desc.co2", "share", row.Share)
		}
		v.Lead = l.T("c.desc.km", "country", name, "year", year, "local", loc, "rate", row.Rate, "co2", co2)
	case fuelOnly && len(v.Fuel) > 0:
		v.H1 = l.T("c.h1.fuel", "country", name, "year", year)
		v.Lead = l.T("c.desc.fuel", "country", name, "year", year, "rate", v.Fuel[0].Rate, "perl", v.Fuel[0].PerLitre)
	default:
		v.H1 = l.T("c.h1.other", "country", name, "year", year, "local", loc, "how", row.How)
		sz := ""
		if size := l.sizeWords(d); len(size) > 0 {
			sz = ", " + strings.Join(size, l.T("cr.and"))
		}
		top := ""
		if d.Top != nil {
			top = " " + l.T("c.top", "amount", l.Money(d.Top.Rate.Total, d.Top.Rate.Cur))
		}
		v.Lead = l.T("c.desc.other", "country", name, "year", year, "local", loc, "how", row.How, "size", sz, "top", top)
	}
	v.Trip, v.TripName = s.trip(l, c.Code)
	v.Sources = sources(d.All...)
	v.Updated = l.Date(d.Mod)
	ld := s.datasetLD(path, l.T("c.ld.name", "country", name, "year", year), v.Lead+" "+l.T("c.ld.more"), name, d.Files, d.Mod, l.Code)
	var basedOn []string
	for _, src := range v.Sources {
		basedOn = append(basedOn, src.URL)
	}
	if len(basedOn) > 0 {
		ld["isBasedOn"] = basedOn
	}
	v.Head = s.mkHead(l, path, v.H1, short(v.Lead, 300), ld, link{l.T("nav.tolls"), s.prefix + s.pagePath(l.Code, "/tolls")}, link{name, s.prefix + path})
	// The share image.
	cd := card{Kicker: l.T("site.kicker"), Footer: hostPath(s.base) + path}
	if d.KmScheme {
		cd.Title = l.T("card.title.km", "country", name, "year", year, "local", loc)
	} else {
		cd.Title = l.T("card.title.other", "country", name, "year", year, "local", loc)
	}
	if f := d.First; f != nil {
		cd.Big = l.T("card.km", "amount", l.Money(f.Rate.Total, f.Rate.Cur))
		cd.BigNote = l.T("card.km.note", "road", l.lower(l.objectName(d.FirstDs, f.Obj)))
		if f.Rate.CO2 > 0 {
			cd.Accent, cd.AccentCO = l.T("card.co2", "amount", l.Money(f.Rate.CO2, f.Rate.Cur), "pct", l.Pct(f.Rate.CO2, f.Rate.Total)), "carbon"
		}
	} else {
		cd.Big = capital(row.How)
		cd.BigNote = l.T("card.other.note")
		if size := l.sizeWords(d); len(size) > 0 {
			cd.Accent = capital(strings.Join(size, ", "))
		}
	}
	return v, row, cd
}

func (l *Loc) versionRow(ds *tariffs.Dataset, sc *scheme, day, rate, co2 string) versionRow {
	to := l.T("hist.untilreplaced")
	if ds.ValidTo != "" {
		to = l.Date(ds.ValidTo)
	}
	return versionRow{From: l.Date(ds.ValidFrom), To: to, Rate: rate, CO2: co2, Law: short(lawOnly(ds.Method()), 160), File: ds.File,
		Upcoming: ds.ValidFrom > day, Current: ds == sc.Current}
}

func (l *Loc) fuelText(r fuelRateT) (rate, perL string) {
	if !r.OK {
		return "–", "–"
	}
	rate = l.Money(r.V, r.Cur) + " " + l.unitName(r.Unit)
	switch {
	case r.EUROK:
		perL = l.Money(r.PerLEUR, "EUR")
	case r.Unit == "litre" || r.Unit == "t_co2":
		perL = l.Money(r.PerL, r.Cur)
	default:
		perL = "–"
	}
	return rate, perL
}

// allLanguages makes every page in every language; without it a language
// has the pages of the countries it is spoken in and the overview, and
// the pages across countries are in English.
var allLanguages = true

func (s *Site) build(day string) *built {
	today, _ := time.Parse(time.DateOnly, day)
	year := today.Year()
	cs := group(s.set, day)
	data := map[string]*countryData{}
	for _, c := range cs {
		data[c.Code] = price(c, day, today)
	}
	langs := sortedLangs(s.locs)
	// Each language's pages are built on their own; the data they read is
	// only read.
	outs := make([]*built, len(langs))
	var wg sync.WaitGroup
	for i, lang := range langs {
		wg.Add(1)
		go func() {
			defer wg.Done()
			outs[i] = s.buildLang(lang, langs, cs, data, day, today, year)
		}()
	}
	wg.Wait()
	b := &built{pages: map[string][]byte{}, cards: map[string]card{}, images: map[string][]byte{}, mod: map[string]string{}}
	for _, o := range outs {
		for p, page := range o.pages {
			b.pages[p] = page
		}
		for p, cd := range o.cards {
			b.cards[p] = cd
		}
		for p, m := range o.mod {
			b.mod[p] = m
		}
		b.paths = append(b.paths, o.paths...)
	}
	b.paths = append(b.paths, "/")
	b.pages["/sitemap.xml"] = gz(sitemap(s.base, b.paths, b.mod))
	return b
}

// has says whether a language has a country's page: English and the
// country's own languages always, every language with allLanguages.
func (s *Site) has(lang, cc string) bool {
	if lang == "en" || allLanguages {
		return true
	}
	for _, x := range langsOf(cc, s.locs) {
		if x == lang {
			return true
		}
	}
	return false
}

func crossIn(lang string) bool { return lang == "en" || allLanguages }

// buildLang builds a language's pages, kept gzipped.
func (s *Site) buildLang(lang string, langs []string, cs []*country, data map[string]*countryData, day string, today time.Time, year int) *built {
	b := &built{pages: map[string][]byte{}, cards: map[string]card{}, mod: map[string]string{}}
	add := func(path string, page []byte, cd card, mod string) {
		b.pages[path] = gz(page)
		b.cards[path] = cd
		b.paths = append(b.paths, path)
		b.mod[path] = mod
	}
	l := s.locs[lang]
	var rows []overviewRow
	var countryLinks, others []link
	for _, c := range cs {
		cl := lang
		if !s.has(lang, c.Code) {
			cl = "en"
		}
		countryLinks = append(countryLinks, link{l.Country(c.Code), s.prefix + s.pagePath(cl, "/tolls/"+c.Slug)})
	}
	for _, x := range crossPages {
		cl := lang
		if !crossIn(lang) || x.EnglishOnly {
			cl = "en"
		}
		others = append(others, link{l.T(x.Title), s.prefix + s.pagePath(cl, x.Path)})
	}
	for _, c := range cs {
		v, row, cd := s.countryView(l, data[c.Code], day, today, year)
		if !s.has(lang, c.Code) {
			row.Href = s.prefix + "/tolls/" + c.Slug
			rows = append(rows, row)
			continue
		}
		rows = append(rows, row)
		v.Others, v.Countries = others, countryLinks
		v.Alternates = s.alternates(langs, "/tolls/"+c.Slug, func(x string) bool { return s.has(x, c.Code) })
		add(s.pagePath(lang, "/tolls/"+c.Slug), s.render("country.html", v), cd, data[c.Code].Mod)
	}
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].Name < rows[j].Name })
	// Overview.
	ov := overviewView{Rows: rows, Updated: l.Date(day), Others: others, Countries: countryLinks}
	ov.H1 = l.T("ov.h1", "year", year)
	ov.Lead = l.T("ov.lead")
	if r, ok := fxOnDate(today); ok {
		ov.FXNote = l.T("ov.fx", "date", l.Date(r))
	}
	path := s.pagePath(lang, "/tolls")
	desc := l.T("ov.desc", "n", len(cs))
	ld := s.datasetLD(path, l.T("ov.ld.name", "year", year), desc, "Europe", nil, "", lang)
	ov.Head = s.mkHead(l, path, ov.H1, desc, ld, link{l.T("nav.tolls"), s.prefix + path})
	ov.Alternates = s.alternates(langs, "/tolls", func(string) bool { return true })
	add(path, s.render("overview.html", ov), card{Kicker: l.T("site.kicker"), Title: l.T("ov.card.title", "year", year), Big: l.T("ov.card.big", "n", len(cs)),
		BigNote: l.T("ov.card.note"), Footer: hostPath(s.base) + path}, day)
	if !crossIn(lang) {
		return b
	}
	for _, p := range []struct {
		path string
		f    func(*Loc, []*country, map[string]*countryData, string, time.Time) (crossView, card)
	}{{"/tolls/zero-emission-trucks", s.zePage}, {"/tolls/ets2-diesel", s.ets2Page}, {"/tolls/co2-tax-diesel", s.fuelPage}} {
		v, cd := p.f(l, cs, data, day, today)
		v.Others, v.Countries = others, countryLinks
		v.Alternates = s.alternates(langs, p.path, crossIn)
		add(s.pagePath(lang, p.path), s.render("cross.html", v), cd, day)
	}
	if lang == "en" {
		v, cd := s.ferryPage(l, day, today)
		v.Others, v.Countries = others, countryLinks
		add(ferryPath, s.render("cross.html", v), cd, day)
	}
	return b
}

// pagePath is a page's path in a language: English at the root, others
// under their code ("/de/tolls/at").
func (s *Site) pagePath(lang, p string) string {
	if lang == "en" {
		return p
	}
	return "/" + lang + p
}

// alternates are a page's versions in the languages that have it.
func (s *Site) alternates(langs []string, p string, has func(string) bool) []alt {
	var out []alt
	for _, x := range langs {
		if has(x) {
			out = append(out, alt{Lang: x, Name: s.locs[x].Name, Href: s.base + s.pagePath(x, p), Path: s.prefix + s.pagePath(x, p)})
		}
	}
	if len(out) < 2 {
		return nil
	}
	return out
}

// datasetLD is schema.org Dataset markup for a page.
func (s *Site) datasetLD(path, name, desc, area string, files []string, from, lang string) map[string]any {
	ld := map[string]any{
		"@context": "https://schema.org", "@type": "Dataset", "name": name, "description": desc, "inLanguage": lang,
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

func sortRows(rows []crossRow) {
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].Cells[0] < rows[j].Cells[0] })
}

// sumByPlaces adds up fares between the same places in different charges
// (a ferry's fare for the truck and its fare for the load).
func sumByPlaces(ds *tariffs.Dataset, fares []fare) []fare {
	name := func(id string) string {
		if o := ds.Object(id); o != nil && o.Name != "" {
			return o.Name
		}
		return id
	}
	var out []fare
	at := map[[3]string]int{}
	for _, f := range fares {
		k := [3]string{name(f.From), name(f.To), f.Period}
		if i, ok := at[k]; ok && out[i].Rate.Cur == f.Rate.Cur {
			out[i].Rate.Total += f.Rate.Total
			out[i].Rate.CO2 += f.Rate.CO2
			continue
		}
		at[k] = len(out)
		out = append(out, f)
	}
	return out
}

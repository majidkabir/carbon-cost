// Package bans holds countries' driving bans for trucks on weekends,
// public holidays and nights, from each country's law, and their public
// holidays, so a trip can be checked against them.
package bans

import (
	"fmt"
	"slices"
	"time"
)

// Rule is one driving ban: in a country, for trucks over MinMassKg (the
// technically permissible maximum mass; with a trailer, over
// TrailerMassKg for the truck or the trailer), on Days from From to To
// local time ("24:00" for midnight at the day's end), within the season
// FromDay to ToDay ("MM-DD", inclusive) if one is given.
type Rule struct {
	Country       string
	Name          string
	MinMassKg     int
	TrailerMassKg int
	// Days: "mon".."sun", "holiday" for the public holidays of Holidays
	// (regional ones count only where the route is in a region that keeps
	// them, else the rule says it may apply) and "holiday_eve" for the
	// day before one. Where a country's law counts runs of days off
	// (Sundays and its holidays): "dayoff_first", "dayoff_last" and
	// "dayoff_single" for the first and last day of a run and a day off
	// alone, "sat_after_workday" for a Saturday after a working day, and
	// "good_friday".
	Days           []string
	From, To       string
	FromDay, ToDay string
	// Since and Until ("YYYY-MM-DD", inclusive) bound the dates the rule
	// is law, when it changed.
	Since, Until string
	// ExemptIntlEuro, when set, exempts trucks of at least this Euro class
	// in international traffic (Hungary's winter exemption).
	ExemptIntlEuro int
	// Season, when set, gives the year's season (first and last day,
	// inclusive) where it moves from year to year.
	Season func(year int) (from, to time.Time)
	// Listed: the ban holds only on roads the law lists, which the route
	// doesn't tell, so a trip is said to may run into it.
	Listed bool
	// Roads are the listed roads' refs ("A-6"), where the calendar gives
	// them, to match with the route's main roads.
	Roads []string
	// TransitFrom and TransitTo: the ban holds only on trucks in transit
	// from one of those countries towards TransitTo (Luxembourg's).
	TransitFrom      []string
	TransitTo        string
	Exemptions, Note string
	Law, Title, URL  string
}

// Holiday is a public holiday the bans count.
type Holiday struct {
	Date time.Time
	Name string
	// Regions (ISO 3166-2) where it is kept; none: everywhere.
	Regions []string
	// NoEve: the day before it isn't banned as its eve.
	NoEve bool
}

// Rules are the bans in.
var Rules = []Rule{
	{Country: "DE", Name: "Sunday and public holiday ban", MinMassKg: 7500, Days: []string{"sun", "holiday"}, From: "00:00", To: "22:00",
		Exemptions: "combined transport to and from rail terminals (200 km) and ports (150 km), fresh milk, meat, fish and perishable fruit and vegetables, live bees, towing, and empty runs with them",
		Note:       "also trailers behind any truck",
		Law:        "Straßenverkehrs-Ordnung (StVO), § 30 (3) and (4)",
		Title:      "Gesetze im Internet: StVO § 30 Umweltschutz, Sonn- und Feiertagsfahrverbot",
		URL:        "https://www.gesetze-im-internet.de/stvo_2013/__30.html"},
	{Country: "AT", Name: "weekend and public holiday ban", MinMassKg: 7500, TrailerMassKg: 3500, Days: []string{"sat"}, From: "15:00", To: "24:00",
		Exemptions: "milk, perishable foods, live animals for slaughter, combined transport to and from listed terminals, and others in § 42 (3)",
		Law:        "Straßenverkehrsordnung 1960 (StVO), § 42 (1) and (2)",
		Title:      "RIS: StVO 1960 § 42 Fahrverbot für Lastkraftfahrzeuge",
		URL:        "https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40276972/NOR40276972.html"},
	{Country: "AT", Name: "weekend and public holiday ban", MinMassKg: 7500, TrailerMassKg: 3500, Days: []string{"sun", "holiday"}, From: "00:00", To: "22:00",
		Exemptions: "milk, perishable foods, live animals for slaughter, combined transport to and from listed terminals, and others in § 42 (3)",
		Law:        "Straßenverkehrsordnung 1960 (StVO), § 42 (1) and (2)",
		Title:      "RIS: StVO 1960 § 42 Fahrverbot für Lastkraftfahrzeuge",
		URL:        "https://www.ris.bka.gv.at/Dokumente/Bundesnormen/NOR40276972/NOR40276972.html"},
}

func init() {
	ch := Rule{Country: "CH", MinMassKg: 3500, TrailerMassKg: 3500,
		Exemptions: "only with a cantonal permit (VRV Art. 92)",
		Note:       "articulated vehicles over 5 t combined, and vehicles towing a trailer over 3.5 t, too",
		Law:        "Strassenverkehrsgesetz (SVG), Art. 2 Abs. 2; Verkehrsregelnverordnung (VRV), Art. 91",
		Title:      "ASTRA: Sonntags- und Nachtfahrten",
		URL:        "https://www.astra.admin.ch/de/sonntags-und-nachtfahrten"}
	sunday, night1, night2 := ch, ch, ch
	sunday.Name, sunday.Days, sunday.From, sunday.To = "Sunday and public holiday ban", []string{"sun", "holiday"}, "00:00", "24:00"
	all := []string{"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
	night1.Name, night1.Days, night1.From, night1.To = "night ban", all, "00:00", "05:00"
	night2.Name, night2.Days, night2.From, night2.To = "night ban", all, "22:00", "24:00"
	fr := Rule{Country: "FR", Name: "weekend and public holiday ban", MinMassKg: 7500,
		Exemptions: "perishables, live animals, and the other transports of Art. 4, and prefects' permits; on top, the summer and winter Saturdays of each year's arrêté, and Île-de-France's own bans",
		Law:        "Arrêté du 16 avril 2021 relatif à l'interdiction de circulation des véhicules de transport de marchandises à certaines périodes, art. 1; public holidays: Code du travail, art. L3133-1",
		Title:      "Ministère de la Transition écologique: Règles et interdictions de circulation dans le transport routier",
		URL:        "https://www.ecologie.gouv.fr/politiques-publiques/regles-interdictions-circulation-transport-routier"}
	frEve, frDay := fr, fr
	frEve.Days, frEve.From, frEve.To = []string{"sat", "holiday_eve"}, "22:00", "24:00"
	frDay.Days, frDay.From, frDay.To = []string{"sun", "holiday"}, "00:00", "22:00"
	Rules = append(Rules, sunday, night1, night2, frEve, frDay)
	Rules = append(Rules, Rule{Country: "DE", Name: "summer Saturday ban", MinMassKg: 7500, Days: []string{"sat"}, From: "07:00", To: "20:00",
		FromDay: "07-01", ToDay: "08-31", Listed: true,
		Exemptions: "combined transport, fresh milk, meat, fish, perishable fruit and vegetables, live bees and the others of § 1 (4), and empty runs with them",
		Note:       "only on the motorway sections and federal roads § 1 (2) and (3) list; also trucks with trailers",
		Law:        "Ferienreiseverordnung (FerReiseV), § 1",
		Title:      "Gesetze im Internet: Ferienreiseverordnung § 1",
		URL:        "https://www.gesetze-im-internet.de/ferreisev_1985/__1.html"})
	cz := Rule{Country: "CZ", Name: "Sunday and holiday ban", MinMassKg: 7500, TrailerMassKg: 3500,
		Exemptions: "perishables, live animals, fuel, post, combined transport and the others of § 43 (3), and permits",
		Note:       "on motorways and class I roads",
		Law:        "Zákon č. 361/2000 Sb. o silničním provozu, § 43; days off: zákon č. 245/2000 Sb.",
		Title:      "Portál veřejné správy: Výjimka z omezení jízdy některých vozidel v rámci celé ČR",
		URL:        "https://portal.gov.cz/sluzby-vs/vyjimka-z-omezeni-jizdy-nekterych-vozidel-v-ramci-cele-cr-S551"}
	czSun, czFri, czSat := cz, cz, cz
	czSun.Days, czSun.From, czSun.To = []string{"sun", "holiday"}, "13:00", "22:00"
	czFri.Name, czFri.Days, czFri.From, czFri.To, czFri.FromDay, czFri.ToDay = "summer ban", []string{"fri"}, "17:00", "21:00", "07-01", "08-31"
	czSat.Name, czSat.Days, czSat.From, czSat.To, czSat.FromDay, czSat.ToDay = "summer ban", []string{"sat"}, "07:00", "13:00", "07-01", "08-31"
	Rules = append(Rules, czSun, czFri, czSat)
	sk := Rule{Country: "SK", MinMassKg: 7500, TrailerMassKg: 3500,
		Exemptions: "perishables, live animals, post, fuel, combined transport, supplies to continuously running plants in Slovakia, vehicles returning to Slovakia, and the others of § 39 (3)",
		Note:       "on motorways, expressways and class I roads",
		Law:        "Zákon č. 8/2009 Z. z. o cestnej premávke, § 39 (1) and (2), as amended by zákon č. 131/2026 Z. z. from 1 September 2026; days off: zákon č. 241/1993 Z. z., § 2",
		Title:      "Slov-Lex: zákon č. 131/2026 Z. z., Čl. I body 45 a 46",
		URL:        "https://static.slov-lex.sk/static/SK/ZZ/2026/131/20260901.html"}
	for _, v := range []struct{ since, until, first, day string }{{"", "2026-08-31", "07:00", "00:00"}, {"2026-09-01", "", "09:00", "06:00"}} {
		last, first, sat := sk, sk, sk
		last.Name, last.Days, last.From, last.To = "Sunday and day off ban", []string{"sun", "dayoff_last", "dayoff_single"}, v.day, "22:00"
		first.Name, first.Days, first.From, first.To = "first day off ban", []string{"dayoff_first"}, v.first, "19:00"
		sat.Name, sat.Days, sat.From, sat.To, sat.FromDay, sat.ToDay = "summer Saturday ban", []string{"sat_after_workday"}, v.first, "19:00", "07-01", "08-31"
		for _, r := range []*Rule{&last, &first, &sat} {
			r.Since, r.Until = v.since, v.until
		}
		Rules = append(Rules, last, first, sat)
	}
}

// Night bans that low-noise trucks are exempt from are noted, not
// checked: StVO 1960 § 42 (6) bans trucks over 7.5 t from 22:00 to 05:00
// in Austria unless they are low-noise (lärmarm), as most new trucks are.
var NightNotes = map[string]string{
	"AT": "Austria bans trucks over 7.5 t from 22:00 to 05:00 unless they are low-noise (lärmarm; StVO 1960, § 42 (6)); more bans on the A 12 and A 13 by the yearly Fahrverbotskalender",
}

// easter is Easter Sunday of a year (the Gregorian computus).
func easter(y int) time.Time {
	a, b, c := y%19, y/100, y%100
	d, e := b/4, b%4
	f := (b + 8) / 25
	g := (b - f + 1) / 3
	h := (19*a + b - d - g + 15) % 30
	i, k := c/4, c%4
	l := (32 + 2*e + 2*i - h - k) % 7
	m := (a + 11*h + 22*l) / 451
	month := (h + l - 7*m + 114) / 31
	day := (h+l-7*m+114)%31 + 1
	return time.Date(y, time.Month(month), day, 0, 0, 0, 0, time.UTC)
}

// Holidays are the public holidays a country's bans count in a year.
func Holidays(country string, y int) []Holiday {
	e := easter(y)
	fixed := func(m time.Month, d int, name string, regions ...string) Holiday {
		return Holiday{Date: time.Date(y, m, d, 0, 0, 0, 0, time.UTC), Name: name, Regions: regions}
	}
	moving := func(days int, name string, regions ...string) Holiday {
		return Holiday{Date: e.AddDate(0, 0, days), Name: name, Regions: regions}
	}
	switch country {
	case "DE":
		// StVO § 30 (4).
		return []Holiday{fixed(1, 1, "Neujahr"), moving(-2, "Karfreitag"), moving(1, "Ostermontag"), fixed(5, 1, "Tag der Arbeit"),
			moving(39, "Christi Himmelfahrt"), moving(50, "Pfingstmontag"),
			moving(60, "Fronleichnam", "DE-BW", "DE-BY", "DE-HE", "DE-NW", "DE-RP", "DE-SL"),
			fixed(10, 3, "Tag der deutschen Einheit"),
			fixed(10, 31, "Reformationstag", "DE-BB", "DE-HB", "DE-HH", "DE-MV", "DE-NI", "DE-SN", "DE-ST", "DE-SH", "DE-TH"),
			fixed(11, 1, "Allerheiligen", "DE-BW", "DE-BY", "DE-NW", "DE-RP", "DE-SL"),
			fixed(12, 25, "1. Weihnachtstag"), fixed(12, 26, "2. Weihnachtstag")}
	case "AT":
		// Arbeitsruhegesetz, § 7 (2) (as the Feiertagsruhegesetz 1957, § 1).
		return []Holiday{fixed(1, 1, "Neujahr"), fixed(1, 6, "Heilige Drei Könige"), moving(1, "Ostermontag"), fixed(5, 1, "Staatsfeiertag"),
			moving(39, "Christi Himmelfahrt"), moving(50, "Pfingstmontag"), moving(60, "Fronleichnam"), fixed(8, 15, "Mariä Himmelfahrt"),
			fixed(10, 26, "Nationalfeiertag"), fixed(11, 1, "Allerheiligen"), fixed(12, 8, "Mariä Empfängnis"),
			fixed(12, 25, "Christtag"), fixed(12, 26, "Stefanitag")}
	case "CH":
		// VRV Art. 91 Abs. 1: 26 December only when Christmas falls on
		// neither a Monday nor a Friday; a day a canton doesn't keep isn't
		// a ban day there.
		hs := []Holiday{fixed(1, 1, "Neujahr"), moving(-2, "Karfreitag"), moving(1, "Ostermontag"), moving(39, "Auffahrt"),
			moving(50, "Pfingstmontag"), fixed(8, 1, "Bundesfeiertag"), fixed(12, 25, "Weihnachten")}
		if wd := time.Date(y, 12, 25, 0, 0, 0, 0, time.UTC).Weekday(); wd != time.Monday && wd != time.Friday {
			hs = append(hs, fixed(12, 26, "Stephanstag"))
		}
		return hs
	case "HR":
		// Zakon o blagdanima, spomendanima i neradnim danima u Republici
		// Hrvatskoj (NN 110/19, 72/25), članak 1.
		return []Holiday{fixed(1, 1, "Nova godina"), fixed(1, 6, "Bogojavljenje"), moving(0, "Uskrs"), moving(1, "Uskrsni ponedjeljak"),
			moving(60, "Tijelovo"), fixed(5, 1, "Praznik rada"), fixed(5, 30, "Dan državnosti"), fixed(6, 22, "Dan antifašističke borbe"),
			fixed(8, 5, "Dan pobjede i domovinske zahvalnosti"), fixed(8, 15, "Velika Gospa"), fixed(11, 1, "Svi sveti"),
			fixed(11, 18, "Dan sjećanja na žrtve Domovinskog rata"), fixed(12, 25, "Božić"), fixed(12, 26, "Sveti Stjepan")}
	case "RO":
		// Legea nr. 53/2003 – Codul muncii, art. 139 alin. (1) (with Legea
		// nr. 52/2023), but the other cults' days; Easter and Pentecost
		// are the Orthodox ones.
		oe := orthodoxEaster(y)
		om := func(days int, name string) Holiday { return Holiday{Date: oe.AddDate(0, 0, days), Name: name} }
		return []Holiday{fixed(1, 1, "Anul Nou"), fixed(1, 2, "Anul Nou"), fixed(1, 6, "Boboteaza"), fixed(1, 7, "Sfântul Ioan Botezătorul"),
			fixed(1, 24, "Ziua Unirii Principatelor Române"), om(-2, "Vinerea Mare"), om(0, "Paștele"), om(1, "a doua zi de Paște"),
			fixed(5, 1, "Ziua Muncii"), fixed(6, 1, "Ziua Copilului"), om(49, "Rusaliile"), om(50, "a doua zi de Rusalii"),
			fixed(8, 15, "Adormirea Maicii Domnului"), fixed(11, 30, "Sfântul Andrei"), fixed(12, 1, "Ziua Națională a României"),
			fixed(12, 25, "Crăciunul"), fixed(12, 26, "a doua zi de Crăciun")}
	case "LI":
		// VRV Art. 89 Abs. 1.
		return []Holiday{fixed(1, 1, "Neujahr"), fixed(1, 6, "Heilige Drei Könige"), moving(1, "Ostermontag"), fixed(5, 1, "1. Mai"),
			moving(39, "Auffahrt"), moving(50, "Pfingstmontag"), moving(60, "Fronleichnam"), fixed(8, 15, "Maria Himmelfahrt"),
			fixed(9, 8, "Maria Geburt"), fixed(11, 1, "Allerheiligen"), fixed(12, 8, "Maria Empfängnis"), fixed(12, 25, "Weihnachten"),
			fixed(12, 26, "St. Stefanstag")}
	case "CZ":
		// Zákon č. 245/2000 Sb.: state holidays and the other holidays.
		return []Holiday{fixed(1, 1, "Den obnovy samostatného českého státu"), moving(-2, "Velký pátek"), moving(1, "Velikonoční pondělí"),
			fixed(5, 1, "Svátek práce"), fixed(5, 8, "Den vítězství"), fixed(7, 5, "Den slovanských věrozvěstů Cyrila a Metoděje"),
			fixed(7, 6, "Den upálení mistra Jana Husa"), fixed(9, 28, "Den české státnosti"), fixed(10, 28, "Den vzniku samostatného československého státu"),
			fixed(11, 17, "Den boje za svobodu a demokracii"), fixed(12, 24, "Štědrý den"), fixed(12, 25, "1. svátek vánoční"), fixed(12, 26, "2. svátek vánoční")}
	case "SK":
		// Zákon č. 241/1993 Z. z., § 1 and § 2: the days off besides
		// Sundays (1 September, 28 October and 17 November are state
		// holidays but not days off, § 2 (3); 8 May and 15 September
		// aren't in 2026, § 4b).
		h := []Holiday{fixed(1, 1, "Deň vzniku Slovenskej republiky"), fixed(1, 6, "Zjavenie Pána"), moving(-2, "Veľký piatok"), moving(1, "Veľkonočný pondelok"),
			fixed(5, 1, "Sviatok práce"), fixed(5, 8, "Deň víťazstva nad fašizmom"), fixed(7, 5, "Sviatok svätého Cyrila a svätého Metoda"),
			fixed(8, 29, "Výročie Slovenského národného povstania"), fixed(9, 15, "Sedembolestná Panna Mária"), fixed(11, 1, "Sviatok Všetkých svätých"),
			fixed(12, 24, "Štedrý deň"), fixed(12, 25, "Prvý sviatok vianočný"), fixed(12, 26, "Druhý sviatok vianočný")}
		if y == 2026 {
			h = slices.DeleteFunc(h, func(d Holiday) bool { return d.Date.Month() == 5 && d.Date.Day() == 8 || d.Date.Month() == 9 })
		}
		return h
	case "HU":
		// Munka törvénykönyve (2012. évi I. törvény), 102. § (1), with 24
		// December from 14 November 2026 (2026. évi LXXII. törvény).
		h := []Holiday{fixed(1, 1, "Újév"), fixed(3, 15, "Nemzeti ünnep"), moving(-2, "Nagypéntek"), moving(1, "Húsvéthétfő"),
			fixed(5, 1, "A munka ünnepe"), moving(50, "Pünkösdhétfő"), fixed(8, 20, "Az államalapítás ünnepe"), fixed(10, 23, "Nemzeti ünnep"),
			fixed(11, 1, "Mindenszentek"), fixed(12, 25, "Karácsony"), fixed(12, 26, "Karácsony másnapja")}
		if y >= 2026 {
			h = append(h, fixed(12, 24, "Szenteste"))
		}
		return h
	case "PL":
		// The regulation's own list, § 2 pkt 1 (24 December and 6 January,
		// days off since, aren't in it); pkt 2 bans the eves of b) to j).
		h := []Holiday{fixed(1, 1, "Nowy Rok"), moving(0, "Pierwszy dzień Wielkiej Nocy"), moving(1, "Drugi dzień Wielkiej Nocy"),
			fixed(5, 1, "Święto Państwowe"), fixed(5, 3, "Święto Narodowe Trzeciego Maja"), moving(49, "Zielone Świątki"), moving(60, "Boże Ciało"),
			fixed(8, 15, "Wniebowzięcie Najświętszej Maryi Panny"), fixed(11, 1, "Wszystkich Świętych"), fixed(11, 11, "Narodowe Święto Niepodległości"),
			fixed(12, 25, "Pierwszy dzień Bożego Narodzenia"), fixed(12, 26, "Drugi dzień Bożego Narodzenia")}
		for _, i := range []int{0, 10, 11} {
			h[i].NoEve = true
		}
		return h
	case "SI":
		// Zakon o praznikih in dela prostih dnevih (ZPDPD), 1. and 2.
		// člen: the holidays that are days off, and the other days off.
		return []Holiday{fixed(1, 1, "Novo leto"), fixed(1, 2, "Novo leto"), fixed(2, 8, "Prešernov dan"), moving(0, "Velikonočna nedelja"),
			moving(1, "Velikonočni ponedeljek"), fixed(4, 27, "Dan upora proti okupatorju"), fixed(5, 1, "Praznik dela"), fixed(5, 2, "Praznik dela"),
			moving(49, "Binkoštna nedelja"), fixed(6, 25, "Dan državnosti"), fixed(8, 15, "Marijino vnebovzetje"), fixed(10, 31, "Dan reformacije"),
			fixed(11, 1, "Dan spomina na mrtve"), fixed(12, 25, "Božič"), fixed(12, 26, "Dan samostojnosti in enotnosti")}
	case "FR":
		// Code du travail, art. L3133-1.
		return []Holiday{fixed(1, 1, "Jour de l'an"), moving(1, "Lundi de Pâques"), fixed(5, 1, "Fête du travail"), fixed(5, 8, "Victoire 1945"),
			moving(39, "Ascension"), moving(50, "Lundi de Pentecôte"), fixed(7, 14, "Fête nationale"), fixed(8, 15, "Assomption"),
			fixed(11, 1, "Toussaint"), fixed(11, 11, "Armistice"), fixed(12, 25, "Noël")}
	}
	return nil
}

// HolidaySources are the laws the holidays come from.
var HolidaySources = map[string][2]string{
	"DE": {"Gesetze im Internet: StVO § 30 (4)", "https://www.gesetze-im-internet.de/stvo_2013/__30.html"},
	"AT": {"RIS: Arbeitsruhegesetz, § 7 Feiertagsruhe", "https://www.ris.bka.gv.at/eli/bgbl/1983/144/P7/NOR40213419"},
	"SK": {"Slov-Lex: zákon č. 241/1993 Z. z. o štátnych sviatkoch, dňoch pracovného pokoja a pamätných dňoch", "https://static.slov-lex.sk/static/SK/ZZ/1993/241/20261029.html"},
}

// Applies says a rule covers the truck.
func (r Rule) Applies(maxMassKg int, trailer bool) bool {
	return maxMassKg > r.MinMassKg || trailer && r.TrailerMassKg > 0 && maxMassKg > r.TrailerMassKg
}

// Window is a ban in force over a stretch of time, local time.
type Window struct {
	Rule     Rule
	From, To time.Time
	// Holiday names the holiday it is for; Regions, where it is kept only
	// in some regions.
	Holiday string
	Regions []string
}

var weekday = map[time.Weekday]string{time.Monday: "mon", time.Tuesday: "tue", time.Wednesday: "wed", time.Thursday: "thu",
	time.Friday: "fri", time.Saturday: "sat", time.Sunday: "sun"}

// Windows lists a country's bans for the truck that overlap from-to (in
// the country's local time, loc).
func Windows(country string, maxMassKg int, trailer bool, from, to time.Time, loc *time.Location) []Window {
	if country == "HU" {
		if !huRule.Applies(maxMassKg, trailer) {
			return nil
		}
		return huWindows(from, to, loc)
	}
	if country == "LU" {
		return luWindows(maxMassKg, trailer, from, to, loc)
	}
	var out []Window
	day := time.Date(from.In(loc).Year(), from.In(loc).Month(), from.In(loc).Day(), 0, 0, 0, 0, loc)
	hol := map[string]Holiday{}
	// The years around too: the day before 1 January is an eve, the day
	// after 31 December a day off.
	for y := day.Year() - 1; y <= to.In(loc).Year()+1; y++ {
		for _, h := range Holidays(country, y) {
			hol[h.Date.Format(time.DateOnly)] = h
		}
	}
	// off is a day off: a Sunday or a holiday kept everywhere.
	off := func(d time.Time) bool {
		h, ok := hol[d.Format(time.DateOnly)]
		return d.Weekday() == time.Sunday || ok && len(h.Regions) == 0
	}
	for ; day.Before(to); day = time.Date(day.Year(), day.Month(), day.Day()+1, 0, 0, 0, 0, loc) {
		md, ymd := day.Format("01-02"), day.Format(time.DateOnly)
		h, isHol := hol[ymd]
		prev, next := off(day.AddDate(0, 0, -1)), off(day.AddDate(0, 0, 1))
		kinds := []string{weekday[day.Weekday()]}
		if e := easter(day.Year()).AddDate(0, 0, -2); day.Month() == e.Month() && day.Day() == e.Day() {
			kinds = append(kinds, "good_friday")
		}
		if off(day) {
			switch {
			case !prev && !next:
				kinds = append(kinds, "dayoff_single")
			case !prev:
				kinds = append(kinds, "dayoff_first")
			case !next:
				kinds = append(kinds, "dayoff_last")
			}
		} else if day.Weekday() == time.Saturday && !prev {
			kinds = append(kinds, "sat_after_workday")
		}
		for _, r := range Rules {
			if r.Country != country || !r.Applies(maxMassKg, trailer) {
				continue
			}
			if r.FromDay != "" && (md < r.FromDay || md > r.ToDay) || r.Since != "" && ymd < r.Since || r.Until != "" && ymd > r.Until {
				continue
			}
			if r.Season != nil {
				if f, t := r.Season(day.Year()); ymd < f.Format(time.DateOnly) || ymd > t.Format(time.DateOnly) {
					continue
				}
			}
			on := slices.ContainsFunc(kinds, func(k string) bool { return slices.Contains(r.Days, k) })
			holidayOnly := false
			if !on && isHol && slices.Contains(r.Days, "holiday") {
				on, holidayOnly = true, true
			}
			if eve, ok := hol[day.AddDate(0, 0, 1).Format(time.DateOnly)]; !on && ok && !eve.NoEve && slices.Contains(r.Days, "holiday_eve") {
				on, holidayOnly, h = true, true, Holiday{Name: "eve of " + eve.Name, Regions: eve.Regions}
			}
			if !on {
				continue
			}
			w := Window{Rule: r, From: at(day, r.From), To: at(day, r.To)}
			if holidayOnly {
				w.Holiday, w.Regions = h.Name, h.Regions
			}
			if isHol && !holidayOnly && len(kinds) > 1 && slices.Contains(r.Days, kinds[1]) {
				w.Holiday, w.Regions = h.Name, h.Regions
			}
			if w.To.After(from) && w.From.Before(to) && !covered(out, w) {
				out = slices.DeleteFunc(out, func(o Window) bool { return covered([]Window{w}, o) })
				out = append(out, w)
			}
		}
	}
	if country == "HR" && hrRule.Applies(maxMassKg, trailer) {
		for _, w := range hrHolidayWindows(from, to, loc) {
			if !covered(out, w) {
				out = slices.DeleteFunc(out, func(o Window) bool { return covered([]Window{w}, o) })
				out = append(out, w)
			}
		}
		slices.SortStableFunc(out, func(a, b Window) int { return a.From.Compare(b.From) })
	}
	if r, ok := calendarRules[country]; ok && r.Applies(maxMassKg, trailer) {
		for _, w := range calendarWindows(country, from, to, loc) {
			if !covered(out, w) {
				out = slices.DeleteFunc(out, func(o Window) bool { return covered([]Window{w}, o) })
				out = append(out, w)
			}
		}
		slices.SortStableFunc(out, func(a, b Window) int { return a.From.Compare(b.From) })
	}
	return out
}

// covered says another of the country's windows already spans w, as
// when a Sunday is also the first day of a run of days off.
func covered(out []Window, w Window) bool {
	for _, o := range out {
		// A ban only on listed roads or in some regions doesn't cover one
		// that holds everywhere.
		sure := !o.Rule.Listed && len(o.Regions) == 0 || w.Rule.Listed && !o.Rule.Listed || len(w.Regions) > 0 && !o.Rule.Listed ||
			o.Rule.Listed && w.Rule.Listed && o.Rule.Note == w.Rule.Note
		if o.Rule.Country == w.Rule.Country && sure && !o.From.After(w.From) && !o.To.Before(w.To) {
			return true
		}
	}
	return false
}

// at is a day's local clock time "HH:MM" ("24:00": the next midnight).
func at(day time.Time, hm string) time.Time {
	var h, m int
	fmt.Sscanf(hm, "%d:%d", &h, &m)
	return time.Date(day.Year(), day.Month(), day.Day()+h/24, h%24, m, 0, 0, day.Location())
}

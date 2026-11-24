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
	// Days: "mon".."sun", and "holiday" for the public holidays of
	// Holidays (regional ones count only where the route is in a region
	// that keeps them, else the rule says it may apply).
	Days             []string
	From, To         string
	FromDay, ToDay   string
	Exemptions, Note string
	Law, Title, URL  string
}

// Holiday is a public holiday the bans count.
type Holiday struct {
	Date time.Time
	Name string
	// Regions (ISO 3166-2) where it is kept; none: everywhere.
	Regions []string
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
	}
	return nil
}

// HolidaySources are the laws the holidays come from.
var HolidaySources = map[string][2]string{
	"DE": {"Gesetze im Internet: StVO § 30 (4)", "https://www.gesetze-im-internet.de/stvo_2013/__30.html"},
	"AT": {"RIS: Arbeitsruhegesetz, § 7 Feiertagsruhe", "https://www.ris.bka.gv.at/eli/bgbl/1983/144/P7/NOR40213419"},
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
	var out []Window
	day := time.Date(from.In(loc).Year(), from.In(loc).Month(), from.In(loc).Day(), 0, 0, 0, 0, loc)
	hol := map[string]Holiday{}
	for y := day.Year(); y <= to.In(loc).Year(); y++ {
		for _, h := range Holidays(country, y) {
			hol[h.Date.Format(time.DateOnly)] = h
		}
	}
	for ; day.Before(to); day = time.Date(day.Year(), day.Month(), day.Day()+1, 0, 0, 0, 0, loc) {
		md := day.Format("01-02")
		h, isHol := hol[day.Format(time.DateOnly)]
		for _, r := range Rules {
			if r.Country != country || !r.Applies(maxMassKg, trailer) {
				continue
			}
			if r.FromDay != "" && (md < r.FromDay || md > r.ToDay) {
				continue
			}
			on := slices.Contains(r.Days, weekday[day.Weekday()])
			holidayOnly := false
			if !on && isHol && slices.Contains(r.Days, "holiday") {
				on, holidayOnly = true, true
			}
			if !on {
				continue
			}
			w := Window{Rule: r, From: at(day, r.From), To: at(day, r.To)}
			if holidayOnly {
				w.Holiday, w.Regions = h.Name, h.Regions
			}
			if w.To.After(from) && w.From.Before(to) {
				out = append(out, w)
			}
		}
	}
	return out
}

// at is a day's local clock time "HH:MM" ("24:00": the next midnight).
func at(day time.Time, hm string) time.Time {
	var h, m int
	fmt.Sscanf(hm, "%d:%d", &h, &m)
	return time.Date(day.Year(), day.Month(), day.Day()+h/24, h%24, m, 0, 0, day.Location())
}

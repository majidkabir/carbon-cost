package bans

import (
	"slices"
	"time"
)

// Croatia: Naredba o ograničenju prometa na cestama (Narodne novine
// 64/09; suspended by NN 46/20 until 1 July 2020 at the latest), over
// 7.5 t, only on the roads of its point I:
//   - II.: from 15 June to 15 September, Saturdays 04:00-14:00 and
//     Sundays 12:00-23:00; Good Friday and the eves of the holidays
//     15:00-23:00, the last day of a holiday 14:00-23:00; a holiday (or
//     its last day) on a Friday or Saturday moves that ban to the Sunday
//     12:00-23:00, and one on a Sunday or Monday moves the eve's ban to
//     the Friday before, 15:00-23:00;
//   - III.: Sundays 06:00-22:00 on the D2 from Varaždin to the Dubrava
//     Križovljanska border crossing.
//
// Holidays: Zakon o blagdanima, spomendanima i neradnim danima u
// Republici Hrvatskoj (NN 110/19, 72/25), članak 1.
var hrRule = Rule{Country: "HR", MinMassKg: 7500, Listed: true,
	Roads: []string{"D8", "D9", "D21", "D23", "D39", "D66", "D200", "D300", "Ž5002"},
	Note: "on the D8 (Bakar–Zadar–Split–Dubrovnik–Karasovići, not Šibenik bridge to Šibenik east or Bilice to Stobreč), D9, D21 (Kaštel–Buje–Kanfanar), D23 (Žuta Lokva–Senj), " +
		"D39, D66, D200, D300, Ž5002 (Novigrad–Poreč–Vrsar) and the ferry ports of Split and Zadar; also vehicles over 14 m",
	Exemptions: "perishables, live animals, concrete, asphalt and fuel, post and press, and the others of point IV, and police permits (point V)",
	Law:        "Naredba o ograničenju prometa na cestama (NN 64/09), točka I. i II.",
	Title:      "Narodne novine 64/2009: Naredba o ograničenju prometa na cestama",
	URL:        "https://narodne-novine.nn.hr/clanci/sluzbeni/2009_06_64_1440.html"}

var hrD2 = func() Rule {
	r := hrRule
	r.Name, r.Days, r.From, r.To = "Sunday ban on the D2", []string{"sun"}, "06:00", "22:00"
	r.Roads = []string{"D2"}
	r.Note = "on the D2 from Varaždin to the Dubrava Križovljanska border crossing"
	r.Exemptions = "vehicles of firms and people based along that D2, and deliveries there of perishables, live animals, concrete, asphalt and fuel (point III)"
	r.Law = "Naredba o ograničenju prometa na cestama (NN 64/09), točka III."
	return r
}()

func init() {
	sat, sun, fri := hrRule, hrRule, hrRule
	sat.Name, sat.Days, sat.From, sat.To, sat.FromDay, sat.ToDay = "summer Saturday ban", []string{"sat"}, "04:00", "14:00", "06-15", "09-15"
	sun.Name, sun.Days, sun.From, sun.To, sun.FromDay, sun.ToDay = "summer Sunday ban", []string{"sun"}, "12:00", "23:00", "06-15", "09-15"
	fri.Name, fri.Days, fri.From, fri.To = "Good Friday ban", []string{"good_friday"}, "15:00", "23:00"
	Rules = append(Rules, sat, sun, fri, hrD2)
	HolidaySources["HR"] = [2]string{"Narodne novine 110/2019: Zakon o blagdanima, spomendanima i neradnim danima u Republici Hrvatskoj, članak 1.",
		"https://narodne-novine.nn.hr/clanci/sluzbeni/2019_11_110_2212.html"}
}

// hrHolidayWindows are point II.'s bans around the holidays: the eve's
// and the last day's, moved as the Naredba says.
func hrHolidayWindows(from, to time.Time, loc *time.Location) []Window {
	hol := map[string]Holiday{}
	for y := from.In(loc).Year() - 1; y <= to.In(loc).Year()+1; y++ {
		for _, h := range Holidays("HR", y) {
			hol[h.Date.Format(time.DateOnly)] = h
		}
	}
	day := func(d time.Time, n int) time.Time { return time.Date(d.Year(), d.Month(), d.Day()+n, 0, 0, 0, 0, loc) }
	isHol := func(d time.Time) bool { _, ok := hol[d.Format(time.DateOnly)]; return ok }
	var out []Window
	add := func(d time.Time, f, t, name, holiday string) {
		r := hrRule
		r.Name, r.From, r.To = name, f, t
		w := Window{Rule: r, From: at(d, f), To: at(d, t), Holiday: holiday}
		if w.To.After(from) && w.From.Before(to) && !slices.ContainsFunc(out, func(o Window) bool { return o.From.Equal(w.From) }) {
			out = append(out, w)
		}
	}
	start := time.Date(from.In(loc).Year(), from.In(loc).Month(), from.In(loc).Day(), 0, 0, 0, 0, loc)
	for d := day(start, -7); d.Before(day(to.In(loc), 7)); d = day(d, 1) {
		if !isHol(d) || isHol(day(d, -1)) {
			continue // not the first day of a holiday
		}
		last := d
		for isHol(day(last, 1)) {
			last = day(last, 1)
		}
		name := hol[d.Format(time.DateOnly)].Name
		switch d.Weekday() {
		case time.Sunday:
			add(day(d, -2), "15:00", "23:00", "holiday eve ban", "eve of "+name+" (on the Friday)")
		case time.Monday:
			add(day(d, -3), "15:00", "23:00", "holiday eve ban", "eve of "+name+" (on the Friday)")
		default:
			add(day(d, -1), "15:00", "23:00", "holiday eve ban", "eve of "+name)
		}
		lastName := hol[last.Format(time.DateOnly)].Name
		switch last.Weekday() {
		case time.Friday:
			add(day(last, 2), "12:00", "23:00", "holiday's last day ban", lastName+" (on the Sunday)")
		case time.Saturday:
			add(day(last, 1), "12:00", "23:00", "holiday's last day ban", lastName+" (on the Sunday)")
		default:
			add(last, "14:00", "23:00", "holiday's last day ban", lastName)
		}
	}
	return out
}

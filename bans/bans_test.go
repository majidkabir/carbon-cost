package bans

import (
	"slices"
	"strings"
	"testing"
	"time"
)

func TestHolidays(t *testing.T) {
	// Easter Sunday: 5 April 2026, 28 March 2027, 31 March 2024.
	for y, want := range map[int]string{2026: "2026-04-05", 2027: "2027-03-28", 2024: "2024-03-31"} {
		if got := easter(y).Format(time.DateOnly); got != want {
			t.Errorf("easter %d: %s, want %s", y, got, want)
		}
	}
	// Vienna's list for 2026: Christi Himmelfahrt 14 May, Pfingstmontag 25
	// May, Fronleichnam 4 June.
	got := map[string]string{}
	for _, h := range Holidays("AT", 2026) {
		got[h.Name] = h.Date.Format(time.DateOnly)
	}
	for name, want := range map[string]string{"Ostermontag": "2026-04-06", "Christi Himmelfahrt": "2026-05-14", "Pfingstmontag": "2026-05-25", "Fronleichnam": "2026-06-04", "Nationalfeiertag": "2026-10-26"} {
		if got[name] != want {
			t.Errorf("AT %s: %s, want %s", name, got[name], want)
		}
	}
	if len(Holidays("AT", 2026)) != 13 || len(Holidays("DE", 2026)) != 12 {
		t.Errorf("counts: AT %d, DE %d", len(Holidays("AT", 2026)), len(Holidays("DE", 2026)))
	}
}

func TestWindows(t *testing.T) {
	ber, _ := time.LoadLocation("Europe/Berlin")
	vie, _ := time.LoadLocation("Europe/Vienna")
	// Saturday 28 November 2026 18:00 to Sunday 29 November 10:00 in
	// Germany: the Sunday ban from 00:00 to 22:00.
	from := time.Date(2026, 11, 28, 18, 0, 0, 0, ber)
	w := Windows("DE", 40000, 0, from, from.Add(16*time.Hour), ber)
	if len(w) != 1 || w[0].From.Format("2006-01-02 15:04") != "2026-11-29 00:00" || w[0].To.Format("15:04") != "22:00" {
		t.Fatalf("DE weekend: %+v", w)
	}
	// A 7.5 t truck isn't covered; one of 12 t is.
	if len(Windows("DE", 7500, 0, from, from.Add(16*time.Hour), ber)) != 0 {
		t.Error("7.5 t: want none")
	}
	// Austria: Saturday from 15:00, and the Sunday.
	w = Windows("AT", 40000, 0, time.Date(2026, 11, 28, 12, 0, 0, 0, vie), time.Date(2026, 11, 29, 23, 0, 0, 0, vie), vie)
	if len(w) != 2 || w[0].From.Format("15:04") != "15:00" || w[0].To.Format("2006-01-02 15:04") != "2026-11-29 00:00" {
		t.Fatalf("AT weekend: %+v", w)
	}
	// A regional holiday: Reformation Day, Saturday 31 October 2026, in
	// northern Germany only; and 26 October 2026, a Monday, in Austria.
	w = Windows("DE", 40000, 0, time.Date(2026, 10, 31, 8, 0, 0, 0, ber), time.Date(2026, 10, 31, 12, 0, 0, 0, ber), ber)
	if len(w) != 1 || w[0].Holiday != "Reformationstag" || len(w[0].Regions) != 9 {
		t.Fatalf("DE Reformationstag: %+v", w)
	}
	w = Windows("AT", 40000, 0, time.Date(2026, 10, 26, 8, 0, 0, 0, vie), time.Date(2026, 10, 26, 12, 0, 0, 0, vie), vie)
	if len(w) != 1 || w[0].Holiday != "Nationalfeiertag" {
		t.Fatalf("AT Nationalfeiertag: %+v", w)
	}
	// Daylight saving ends on Sunday 25 October 2026: the ban is still
	// 00:00 to 22:00 by the clock.
	w = Windows("DE", 40000, 0, time.Date(2026, 10, 25, 1, 0, 0, 0, ber), time.Date(2026, 10, 25, 23, 0, 0, 0, ber), ber)
	if len(w) != 1 || w[0].To.Format("15:04") != "22:00" {
		t.Fatalf("DST: %+v", w)
	}
}

func TestSwissAndFrenchBans(t *testing.T) {
	zrh, _ := time.LoadLocation("Europe/Zurich")
	par, _ := time.LoadLocation("Europe/Paris")
	// Switzerland, over 3.5 t: the night ban every night, all Sunday.
	w := Windows("CH", 12000, 0, time.Date(2026, 11, 27, 21, 0, 0, 0, zrh), time.Date(2026, 11, 28, 6, 0, 0, 0, zrh), zrh)
	if len(w) != 2 || w[0].Rule.Name != "night ban" || w[0].From.Format("15:04") != "22:00" || w[1].To.Format("15:04") != "05:00" {
		t.Fatalf("CH night: %+v", w)
	}
	if w := Windows("CH", 12000, 0, time.Date(2026, 11, 29, 10, 0, 0, 0, zrh), time.Date(2026, 11, 29, 11, 0, 0, 0, zrh), zrh); len(w) != 1 || w[0].Rule.Name != "Sunday and public holiday ban" {
		t.Fatalf("CH Sunday: %+v", w)
	}
	// Christmas 2026 on a Friday: 26 December isn't a ban day; 2027's is
	// on a Saturday, so it is.
	has26 := func(y int) bool {
		for _, h := range Holidays("CH", y) {
			if h.Name == "Stephanstag" {
				return true
			}
		}
		return false
	}
	if has26(2026) || !has26(2027) {
		t.Errorf("CH 26 December: 2026 %v, 2027 %v", has26(2026), has26(2027))
	}
	// France: from 22:00 on the eve of 11 November (a Wednesday in 2026)
	// to 22:00 on the day.
	w = Windows("FR", 40000, 0, time.Date(2026, 11, 10, 20, 0, 0, 0, par), time.Date(2026, 11, 11, 23, 0, 0, 0, par), par)
	if len(w) != 2 || w[0].From.Format("2006-01-02 15:04") != "2026-11-10 22:00" || w[0].Holiday != "eve of Armistice" || w[1].To.Format("2006-01-02 15:04") != "2026-11-11 22:00" {
		t.Fatalf("FR 11 November: %+v", w)
	}
	// A weekend: Saturday 22:00 to Sunday 22:00.
	w = Windows("FR", 40000, 0, time.Date(2026, 11, 28, 12, 0, 0, 0, par), time.Date(2026, 11, 29, 23, 0, 0, 0, par), par)
	if len(w) != 2 || w[0].From.Format("Mon 15:04") != "Sat 22:00" || w[1].To.Format("Mon 15:04") != "Sun 22:00" {
		t.Fatalf("FR weekend: %+v", w)
	}
}

func TestCzechBans(t *testing.T) {
	prg, _ := time.LoadLocation("Europe/Prague")
	// 17 November 2026, a Tuesday holiday: 13:00-22:00.
	w := Windows("CZ", 40000, 0, time.Date(2026, 11, 17, 8, 0, 0, 0, prg), time.Date(2026, 11, 17, 23, 0, 0, 0, prg), prg)
	if len(w) != 1 || w[0].From.Format("15:04") != "13:00" || w[0].Holiday == "" {
		t.Fatalf("CZ 17 November: %+v", w)
	}
	// Summer: Friday 17:00-21:00 and Saturday 07:00-13:00, then Sunday.
	w = Windows("CZ", 40000, 0, time.Date(2026, 7, 10, 12, 0, 0, 0, prg), time.Date(2026, 7, 12, 23, 0, 0, 0, prg), prg)
	if len(w) != 3 || w[0].Rule.Name != "summer ban" || w[1].From.Format("Mon 15:04") != "Sat 07:00" || w[2].From.Format("Mon 15:04") != "Sun 13:00" {
		t.Fatalf("CZ summer: %+v", w)
	}
	// Not in November on a Saturday.
	if w := Windows("CZ", 40000, 0, time.Date(2026, 11, 28, 6, 0, 0, 0, prg), time.Date(2026, 11, 28, 14, 0, 0, 0, prg), prg); len(w) != 0 {
		t.Errorf("CZ November Saturday: %+v", w)
	}
}

func TestSlovakBans(t *testing.T) {
	ba, _ := time.LoadLocation("Europe/Bratislava")
	day := func(y int, m time.Month, d int) (time.Time, time.Time) {
		return time.Date(y, m, d, 0, 0, 0, 0, ba), time.Date(y, m, d, 23, 59, 0, 0, ba)
	}
	cases := []struct {
		y       int
		m       time.Month
		d       int
		want    string // "" for no ban
		holiday bool
	}{
		{2026, 11, 22, "06:00-22:00", false}, // Sunday, after 131/2026
		{2026, 8, 2, "00:00-22:00", false},   // Sunday, before it
		{2026, 8, 1, "07:00-19:00", false},   // summer Saturday after a working day
		{2026, 8, 29, "07:00-19:00", true},   // Saturday holiday: first of a run
		{2026, 8, 30, "00:00-22:00", false},  // its Sunday, last of the run
		{2026, 12, 24, "09:00-19:00", true},  // first of 24-27 December
		{2026, 12, 25, "", false},            // between the first and the last
		{2026, 12, 27, "06:00-22:00", false}, // Sunday, last
		{2027, 1, 1, "06:00-22:00", true},    // Friday alone: Saturday isn't a day off
		{2026, 11, 17, "", false},            // state holiday, not a day off
		{2026, 9, 15, "", false},             // not a day off in 2026 (§ 4b)
		{2027, 9, 15, "06:00-22:00", true},   // a day off again
		{2026, 11, 28, "", false},            // Saturday outside summer
	}
	for _, c := range cases {
		f, to := day(c.y, c.m, c.d)
		w := Windows("SK", 40000, 0, f, to, ba)
		got := ""
		if len(w) == 1 {
			got = w[0].From.Format("15:04") + "-" + w[0].To.Format("15:04")
		}
		if len(w) > 1 || got != c.want || len(w) == 1 && (w[0].Holiday != "") != c.holiday {
			t.Errorf("%d-%02d-%02d: %+v, want %s", c.y, c.m, c.d, w, c.want)
		}
	}
	if w := Windows("SK", 7500, 0, time.Date(2026, 11, 22, 0, 0, 0, 0, ba), time.Date(2026, 11, 22, 23, 0, 0, 0, ba), ba); len(w) != 0 {
		t.Errorf("7.5 t: %+v", w)
	}
}

func TestHungarianBans(t *testing.T) {
	bud, _ := time.LoadLocation("Europe/Budapest")
	at := func(y int, m time.Month, d, h int) time.Time { return time.Date(y, m, d, h, 0, 0, 0, bud) }
	f := "Mon 2 Jan 15:04"
	cases := []struct {
		from, to time.Time
		want     []string
	}{
		// Winter weekend: Saturday 22:00 to Sunday 22:00.
		{at(2026, 11, 27, 12), at(2026, 11, 30, 12), []string{"Sat 28 Nov 22:00-Sun 29 Nov 22:00"}},
		// Summer: Saturday 15:00 to Sunday 22:00.
		{at(2026, 7, 10, 12), at(2026, 7, 13, 12), []string{"Sat 11 Jul 15:00-Sun 12 Jul 22:00"}},
		// 8 August 2026 is a working Saturday: no summer Saturday ban.
		{at(2026, 8, 7, 12), at(2026, 8, 10, 12), nil},
		// 20 August 2026, a Thursday: from 22:00 the day before.
		{at(2026, 8, 19, 12), at(2026, 8, 21, 12), []string{"Wed 19 Aug 22:00-Thu 20 Aug 22:00"}},
		// 20 August 2027, a Friday, in summer: § 2 (2), Friday 08:00 to Sunday 22:00.
		{at(2027, 8, 19, 12), at(2027, 8, 23, 12), []string{"Fri 20 Aug 08:00-Sun 22 Aug 22:00"}},
		// 1 May 2027, a Saturday, outside summer: § 2 (2), Saturday 08:00 to Sunday 22:00.
		{at(2027, 4, 30, 12), at(2027, 5, 3, 12), []string{"Sat 1 May 08:00-Sun 2 May 22:00"}},
		// Easter 2027: Good Friday, then Saturday 22:00 to Monday 22:00.
		{at(2027, 3, 25, 12), at(2027, 3, 30, 12), []string{"Thu 25 Mar 22:00-Fri 26 Mar 22:00", "Sat 27 Mar 22:00-Mon 29 Mar 22:00"}},
		// Christmas 2026: 24 December is a day off now, Wednesday 22:00 to Sunday 27 December 22:00.
		{at(2026, 12, 23, 12), at(2026, 12, 28, 12), []string{"Wed 23 Dec 22:00-Sun 27 Dec 22:00"}},
	}
	for _, c := range cases {
		var got []string
		for _, w := range Windows("HU", 40000, 0, c.from, c.to, bud) {
			got = append(got, w.From.Format(f)+"-"+w.To.Format(f))
		}
		if !slices.Equal(got, c.want) {
			t.Errorf("%s: %v, want %v", c.from.Format(f), got, c.want)
		}
	}
	// The winter exemption for international traffic from Euro 3.
	w := Windows("HU", 40000, 0, at(2026, 11, 27, 12), at(2026, 11, 30, 12), bud)
	if len(w) != 1 || !w[0].Exempt(6, true) || w[0].Exempt(6, false) || w[0].Exempt(2, true) {
		t.Errorf("winter exemption: %+v", w)
	}
	if w := Windows("HU", 40000, 0, at(2026, 7, 10, 12), at(2026, 7, 13, 12), bud); len(w) != 1 || w[0].Exempt(6, true) {
		t.Errorf("summer: no exemption: %+v", w)
	}
}

func TestPolishBans(t *testing.T) {
	waw, _ := time.LoadLocation("Europe/Warsaw")
	f, l := plSummer(2026)
	if f.Format(time.DateOnly) != "2026-06-26" || l.Format(time.DateOnly) != "2026-08-30" {
		t.Errorf("summer 2026: %s to %s", f, l)
	}
	// 2027: 20 June is a Sunday, lessons end Friday 25 June; 1 September
	// is a Wednesday, so the last Sunday before is 29 August.
	if f, l := plSummer(2027); f.Format(time.DateOnly) != "2027-06-25" || l.Format(time.DateOnly) != "2027-08-29" {
		t.Errorf("summer 2027: %s to %s", f, l)
	}
	day := func(y int, m time.Month, d int) []Window {
		return Windows("PL", 40000, 0, time.Date(y, m, d, 0, 0, 0, 0, waw), time.Date(y, m, d, 23, 59, 0, 0, waw), waw)
	}
	span := func(w []Window) (s []string) {
		for _, x := range w {
			s = append(s, x.From.Format("15:04")+"-"+x.To.Format("15:04"))
		}
		return
	}
	for _, c := range []struct {
		y    int
		m    time.Month
		d    int
		want []string
	}{
		{2026, 11, 11, []string{"08:00-22:00"}}, // Independence Day
		{2026, 11, 10, []string{"18:00-22:00"}}, // its eve
		{2026, 12, 24, nil},                     // not in the regulation
		{2026, 12, 31, nil},                     // New Year's eve isn't banned
		{2026, 7, 10, []string{"18:00-22:00"}},  // summer Friday
		{2026, 7, 11, []string{"08:00-14:00"}},  // summer Saturday
		{2026, 8, 15, []string{"08:00-22:00"}},  // Saturday 15 August: the holiday's hours
		{2026, 8, 14, []string{"18:00-22:00"}},  // its eve, a summer Friday
		{2026, 9, 5, nil},                       // Saturday after the summer
		{2026, 11, 29, nil},                     // a Sunday outside summer
		{2027, 5, 15, []string{"18:00-22:00"}},  // eve of Pentecost Sunday
	} {
		if got := span(day(c.y, c.m, c.d)); !slices.Equal(got, c.want) {
			t.Errorf("%d-%02d-%02d: %v, want %v", c.y, c.m, c.d, got, c.want)
		}
	}
	if w := Windows("PL", 12000, 0, time.Date(2026, 11, 11, 0, 0, 0, 0, waw), time.Date(2026, 11, 11, 23, 0, 0, 0, waw), waw); len(w) != 0 {
		t.Errorf("12 t: %+v", w)
	}
}

func TestSlovenianBans(t *testing.T) {
	lj, _ := time.LoadLocation("Europe/Ljubljana")
	if f, l := siSeason(2025); f.Format(time.DateOnly) != "2025-06-28" || l.Format(time.DateOnly) != "2025-09-07" {
		t.Errorf("season 2025: %s to %s", f, l)
	}
	day := func(y int, m time.Month, d int) (s []string) {
		for _, w := range Windows("SI", 40000, 0, time.Date(y, m, d, 0, 0, 0, 0, lj), time.Date(y, m, d, 23, 59, 0, 0, lj), lj) {
			s = append(s, w.From.Format("15:04")+"-"+w.To.Format("15:04"))
		}
		return
	}
	for _, c := range []struct {
		y    int
		m    time.Month
		d    int
		want []string
	}{
		{2026, 4, 3, []string{"14:00-22:00"}},   // Good Friday
		{2026, 11, 29, []string{"08:00-22:00"}}, // Sunday
		{2026, 12, 25, []string{"08:00-22:00"}}, // Christmas, a Friday
		{2026, 11, 23, nil},                     // Maister's day isn't a day off
		{2026, 7, 4, []string{"08:00-13:00"}},   // a season Saturday
		{2026, 11, 28, nil},                     // a Saturday outside it
	} {
		if got := day(c.y, c.m, c.d); !slices.Equal(got, c.want) {
			t.Errorf("%d-%02d-%02d: %v, want %v", c.y, c.m, c.d, got, c.want)
		}
	}
}

func TestItalianCalendar(t *testing.T) {
	rome, _ := time.LoadLocation("Europe/Rome")
	w := Windows("IT", 40000, 0, time.Date(2026, 8, 14, 0, 0, 0, 0, rome), time.Date(2026, 8, 16, 23, 0, 0, 0, rome), rome)
	var got []string
	for _, x := range w {
		got = append(got, x.From.Format("Mon 2 15:04")+"-"+x.To.Format("15:04"))
	}
	if want := []string{"Fri 14 16:00-22:00", "Sat 15 07:00-22:00", "Sun 16 07:00-22:00"}; !slices.Equal(got, want) {
		t.Errorf("Ferragosto: %v", got)
	}
	if w[0].Rule.Law == "" || w[0].Rule.URL == "" {
		t.Errorf("rule: %+v", w[0].Rule)
	}
	if w := Windows("IT", 7500, 0, time.Date(2026, 8, 15, 0, 0, 0, 0, rome), time.Date(2026, 8, 15, 23, 0, 0, 0, rome), rome); len(w) != 0 {
		t.Errorf("7.5 t: %+v", w)
	}
	if !slices.Equal(CalendarYears("IT"), []int{2026}) {
		t.Errorf("years %v", CalendarYears("IT"))
	}
}

func TestLiechtensteinBans(t *testing.T) {
	vaduz, _ := time.LoadLocation("Europe/Vaduz")
	// 8 December 2026, a Tuesday: Maria Empfängnis, all day, plus the
	// nights either side.
	w := Windows("LI", 40000, 0, time.Date(2026, 12, 8, 6, 0, 0, 0, vaduz), time.Date(2026, 12, 8, 21, 0, 0, 0, vaduz), vaduz)
	if len(w) != 1 || w[0].Holiday != "Maria Empfängnis" || w[0].From.Hour() != 0 || w[0].To.Day() != 9 {
		t.Errorf("8 December: %+v", w)
	}
	// A weekday night.
	if w := Windows("LI", 40000, 0, time.Date(2026, 11, 24, 21, 0, 0, 0, vaduz), time.Date(2026, 11, 24, 23, 0, 0, 0, vaduz), vaduz); len(w) != 1 || w[0].Rule.Name != "night ban" {
		t.Errorf("night: %+v", w)
	}
}

func TestFrenchCalendar(t *testing.T) {
	par, _ := time.LoadLocation("Europe/Paris")
	// Saturday 18 July 2026: 07:00-19:00 everywhere, then from 22:00 the
	// weekend ban.
	w := Windows("FR", 40000, 0, time.Date(2026, 7, 18, 0, 0, 0, 0, par), time.Date(2026, 7, 18, 23, 59, 0, 0, par), par)
	if len(w) != 2 || w[0].From.Hour() != 7 || w[0].To.Hour() != 19 || w[0].Rule.Listed || w[1].From.Hour() != 22 {
		t.Errorf("18 July: %+v", w)
	}
	// Saturday 7 February 2026: only on the listed Alpine roads.
	w = Windows("FR", 40000, 0, time.Date(2026, 2, 7, 0, 0, 0, 0, par), time.Date(2026, 2, 7, 20, 0, 0, 0, par), par)
	if len(w) != 1 || !w[0].Rule.Listed || w[0].To.Hour() != 18 || !strings.Contains(w[0].Rule.Note, "Auvergne-Rhône-Alpes") {
		t.Errorf("7 February: %+v", w)
	}
}

func TestAustrianDecrees(t *testing.T) {
	vie, _ := time.LoadLocation("Europe/Vienna")
	// Saturday 11 July 2026: the weekend ban from 15:00 everywhere, and the
	// decrees' bans on their own roads, each its own window.
	w := Windows("AT", 40000, 0, time.Date(2026, 7, 11, 0, 0, 0, 0, vie), time.Date(2026, 7, 11, 23, 59, 0, 0, vie), vie)
	var listed, sure int
	laws := map[string]bool{}
	for _, x := range w {
		if x.Rule.Listed {
			listed++
			laws[x.Rule.Law] = true
		} else {
			sure++
		}
	}
	// Luegbrücke both ways, the B roads, the A 4, the A 10 southbound.
	if sure != 1 || listed != 5 || len(laws) != 3 {
		t.Errorf("11 July: %d sure, %d listed, laws %v", sure, listed, laws)
	}
	if !slices.Equal(CalendarYears("AT"), []int{2026}) {
		t.Errorf("years %v", CalendarYears("AT"))
	}
	// Friday 10 April 2026: northbound from the Brenner, 07:00-22:00.
	w = Windows("AT", 40000, 0, time.Date(2026, 4, 10, 0, 0, 0, 0, vie), time.Date(2026, 4, 10, 23, 0, 0, 0, vie), vie)
	if len(w) != 1 || !w[0].Rule.Listed || !strings.Contains(w[0].Rule.Note, "towards Innsbruck") || w[0].To.Hour() != 22 {
		t.Errorf("10 April: %+v", w)
	}
}

func TestSpainCalendar(t *testing.T) {
	// Sunday 16 August 2026: listed road sections only, each with its
	// roads; none under 7.5 t.
	loc, _ := time.LoadLocation("Europe/Madrid")
	day := time.Date(2026, 8, 16, 0, 0, 0, 0, loc)
	ws := Windows("ES", 40000, 0, day, day.AddDate(0, 0, 1), loc)
	if len(ws) < 10 {
		t.Fatalf("%d windows", len(ws))
	}
	for _, w := range ws {
		if !w.Rule.Listed || len(w.Rule.Roads) == 0 || !strings.HasPrefix(w.Rule.Note, "on the ") {
			t.Errorf("%+v", w.Rule)
		}
	}
	if ws := Windows("ES", 7500, 0, day, day.AddDate(0, 0, 1), loc); len(ws) != 0 {
		t.Errorf("7.5 t: %d windows", len(ws))
	}
}

func TestCroatia(t *testing.T) {
	loc, _ := time.LoadLocation("Europe/Zagreb")
	win := func(from string, days int) []Window {
		d, _ := time.ParseInLocation(time.DateOnly, from, loc)
		return Windows("HR", 40000, 0, d, d.AddDate(0, 0, days), loc)
	}
	type w struct{ from, to string }
	got := func(ws []Window) []w {
		var out []w
		for _, x := range ws {
			if !x.Rule.Listed || len(x.Rule.Roads) == 0 {
				t.Errorf("not listed: %+v", x.Rule)
			}
			out = append(out, w{x.From.Format("2006-01-02 15:04"), x.To.Format("15:04")})
		}
		return out
	}
	// Labour Day, Friday 1 May 2026: the eve, Thursday, 15-23; the day
	// itself moves to Sunday 3 May 12-23.
	if g := got(win("2026-04-30", 4)); !slices.Equal(g, []w{{"2026-04-30 15:00", "23:00"}, {"2026-05-03 06:00", "22:00"}, {"2026-05-03 12:00", "23:00"}}) {
		t.Errorf("1 May: %v", g)
	}
	// Easter 2026 (5-6 April): Good Friday 15-23 (also the moved eve),
	// Easter Monday 14-23, and the D2's Sunday.
	if g := got(win("2026-04-03", 4)); !slices.Equal(g, []w{{"2026-04-03 15:00", "23:00"}, {"2026-04-05 06:00", "22:00"}, {"2026-04-06 14:00", "23:00"}}) {
		t.Errorf("Easter: %v", g)
	}
	// A summer weekend: Saturday 04-14, Sunday 12-23 and the D2's.
	if g := got(win("2026-07-11", 2)); !slices.Equal(g, []w{{"2026-07-11 04:00", "14:00"}, {"2026-07-12 06:00", "22:00"}, {"2026-07-12 12:00", "23:00"}}) {
		t.Errorf("July: %v", g)
	}
	// Christmas 2026, Friday and Saturday: the eve Thursday 24, the last
	// day moved to Sunday 27.
	if g := got(win("2026-12-24", 4)); !slices.Equal(g, []w{{"2026-12-24 15:00", "23:00"}, {"2026-12-27 06:00", "22:00"}, {"2026-12-27 12:00", "23:00"}}) {
		t.Errorf("Christmas: %v", g)
	}
	if len(win("2026-07-11", 2)) == 0 || len(Windows("HR", 7500, 0, time.Date(2026, 7, 11, 0, 0, 0, 0, loc), time.Date(2026, 7, 13, 0, 0, 0, 0, loc), loc)) != 0 {
		t.Error("7.5 t")
	}
}

func TestLuxembourg(t *testing.T) {
	loc, _ := time.LoadLocation("Europe/Luxembourg")
	// Whitsun 2026: Saturday 23 May to Monday 25 May. Towards France one
	// window, Saturday 21:30 to Monday 21:45; towards Germany Saturday
	// 23:30 to Sunday 21:45 and Sunday 23:30 to Monday 21:45.
	d := time.Date(2026, 5, 23, 0, 0, 0, 0, loc)
	var fr, de []string
	for _, w := range Windows("LU", 40000, 0, d, d.AddDate(0, 0, 3), loc) {
		s := w.From.Format("Mon 15:04") + "-" + w.To.Format("Mon 15:04")
		if w.Rule.TransitTo == "FR" {
			fr = append(fr, s)
		} else {
			de = append(de, s)
		}
	}
	if !slices.Equal(fr, []string{"Sat 21:30-Mon 21:45"}) || !slices.Equal(de, []string{"Sat 23:30-Sun 21:45", "Sun 23:30-Mon 21:45"}) {
		t.Errorf("FR %v, DE %v", fr, de)
	}
}

func TestRomania(t *testing.T) {
	if e := orthodoxEaster(2026); e.Format(time.DateOnly) != "2026-04-12" {
		t.Errorf("Orthodox Easter 2026: %v", e)
	}
	if e := orthodoxEaster(2027); e.Format(time.DateOnly) != "2027-05-02" {
		t.Errorf("Orthodox Easter 2027: %v", e)
	}
	loc, _ := time.LoadLocation("Europe/Bucharest")
	ws := func(from string, days int) []string {
		d, _ := time.ParseInLocation(time.DateOnly, from, loc)
		var out []string
		for _, w := range Windows("RO", 40000, 0, d, d.AddDate(0, 0, days), loc) {
			out = append(out, w.Rule.Roads[0]+" "+w.From.Format("01-02 15:04")+"-"+w.To.Format("15:04"))
		}
		return out
	}
	// Sf. Andrei and the National Day 2026 (Monday and Tuesday): only the
	// DN7, all year; the A2 and DN39 from April to September.
	if g := ws("2026-11-29", 3); !slices.Equal(g, []string{"DN7 11-29 18:00-22:00", "DN7 11-30 06:00-22:00", "DN7 12-01 06:00-22:00"}) {
		t.Errorf("Sf. Andrei: %v", g)
	}
	// 15 August 2026, a Saturday: the summer weekend and the holiday.
	g := ws("2026-08-14", 1)
	if !slices.Contains(g, "A2 08-14 16:00-22:00") || !slices.Contains(g, "A2 08-14 12:00-22:00") || !slices.Contains(g, "DN39 08-14 06:00-22:00") {
		t.Errorf("14 August: %v", g)
	}
}

func TestGreece(t *testing.T) {
	loc, _ := time.LoadLocation("Europe/Athens")
	n := func(from string, days int, mass int) (int, []Window) {
		d, _ := time.ParseInLocation(time.DateOnly, from, loc)
		ws := Windows("GR", mass, 0, d, d.AddDate(0, 0, days), loc)
		return len(ws), ws
	}
	// Christmas Eve 2026: the twelve sections leaving the cities, 16-22.
	if c, ws := n("2026-12-24", 1, 12000); c != 12 || ws[0].From.Hour() != 16 || ws[0].To.Hour() != 22 || !ws[0].Rule.Listed {
		t.Errorf("24 December: %d %+v", c, ws)
	}
	// Friday 14 August 2026 is Β6's, not Β9's: 16-22, not 16-21, and the
	// Thessaloniki–Kavala road both ways from Β10 (15-22).
	_, ws := n("2026-08-14", 1, 12000)
	for _, w := range ws {
		if w.To.Hour() == 21 {
			t.Errorf("14 August: a Β9 window %+v", w)
		}
	}
	// An ordinary summer Friday: Β9's 13 windows (the Kavala road both
	// ways) and Β10's two.
	if c, _ := n("2026-07-10", 1, 12000); c != 15 {
		t.Errorf("10 July: %d windows", c)
	}
	if c, _ := n("2026-12-24", 1, 3500); c != 0 {
		t.Errorf("3.5 t: %d windows", c)
	}
}

// New Year's Eve is the eve of a day off in the next year: France's
// ban from 22:00 holds on 31 December however late the trip ends.
func TestNewYearsEve(t *testing.T) {
	loc, _ := time.LoadLocation("Europe/Paris")
	from := time.Date(2026, 12, 31, 21, 0, 0, 0, loc)
	ws := Windows("FR", 40000, 20000, from, time.Date(2026, 12, 31, 23, 30, 0, 0, loc), loc)
	if len(ws) == 0 {
		t.Fatalf("FR 31 December 21:00-23:30: no ban; want the eve of 1 January's from 22:00")
	}
}

// Greece's decree for 2026 holds the first days of 2027: those are
// covered; later ones aren't.
func TestCalendarCovers(t *testing.T) {
	for day, want := range map[string]bool{"2026-06-01": true, "2027-01-03": true, "2027-02-10": false} {
		d, _ := time.Parse(time.DateOnly, day)
		if got := CalendarCovers("GR", d); got != want {
			t.Errorf("GR %s covered %v, want %v", day, got, want)
		}
	}
}

// Austria bans a truck towing a trailer when the truck or the trailer is
// over 3.5 t, whatever the combination's mass (StVO 1960 § 42 (1)).
func TestTrailerBan(t *testing.T) {
	vie, _ := time.LoadLocation("Europe/Vienna")
	from, to := time.Date(2026, 11, 22, 10, 0, 0, 0, vie), time.Date(2026, 11, 22, 12, 0, 0, 0, vie)
	if len(Windows("AT", 7100, 3600, from, to, vie)) == 0 {
		t.Errorf("AT, 7.1 t towing a 3.6 t trailer on a Sunday: no ban")
	}
	if len(Windows("AT", 7000, 3500, from, to, vie)) != 0 || len(Windows("AT", 7100, 0, from, to, vie)) != 0 {
		t.Errorf("AT: a ban on a 7 t combination of 3.5 t each, or a 7.1 t truck without a trailer")
	}
}

// Germany's Sunday ban holds for trailers behind any truck (StVO § 30
// (3): "sowie Anhänger hinter Lastkraftwagen").
func TestGermanTrailerBan(t *testing.T) {
	ber, _ := time.LoadLocation("Europe/Berlin")
	from, to := time.Date(2026, 11, 29, 10, 0, 0, 0, ber), time.Date(2026, 11, 29, 12, 0, 0, 0, ber)
	if len(Windows("DE", 5000, 2500, from, to, ber)) == 0 {
		t.Errorf("DE, a 5 t combination on a Sunday: no ban")
	}
	if len(Windows("DE", 5000, 0, from, to, ber)) != 0 {
		t.Errorf("DE, a 5 t truck without a trailer: banned")
	}
}

// A calendar country's windows are built once, not for each stretch of a
// route: ten thousand lookups take little time.
func TestCalendarWindowsCached(t *testing.T) {
	mad, _ := time.LoadLocation("Europe/Madrid")
	from := time.Date(2026, 7, 1, 0, 0, 0, 0, mad)
	t0 := time.Now()
	for i := 0; i < 10000; i++ {
		Windows("ES", 40000, 0, from, from.Add(48*time.Hour), mad)
	}
	if d := time.Since(t0); d > 3*time.Second {
		t.Errorf("10,000 lookups in %v", d)
	}
}

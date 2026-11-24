package bans

import (
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
	w := Windows("DE", 40000, false, from, from.Add(16*time.Hour), ber)
	if len(w) != 1 || w[0].From.Format("2006-01-02 15:04") != "2026-11-29 00:00" || w[0].To.Format("15:04") != "22:00" {
		t.Fatalf("DE weekend: %+v", w)
	}
	// A 7.5 t truck isn't covered; one of 12 t is.
	if len(Windows("DE", 7500, false, from, from.Add(16*time.Hour), ber)) != 0 {
		t.Error("7.5 t: want none")
	}
	// Austria: Saturday from 15:00, and the Sunday.
	w = Windows("AT", 40000, false, time.Date(2026, 11, 28, 12, 0, 0, 0, vie), time.Date(2026, 11, 29, 23, 0, 0, 0, vie), vie)
	if len(w) != 2 || w[0].From.Format("15:04") != "15:00" || w[0].To.Format("2006-01-02 15:04") != "2026-11-29 00:00" {
		t.Fatalf("AT weekend: %+v", w)
	}
	// A regional holiday: Reformation Day, Saturday 31 October 2026, in
	// northern Germany only; and 26 October 2026, a Monday, in Austria.
	w = Windows("DE", 40000, false, time.Date(2026, 10, 31, 8, 0, 0, 0, ber), time.Date(2026, 10, 31, 12, 0, 0, 0, ber), ber)
	if len(w) != 1 || w[0].Holiday != "Reformationstag" || len(w[0].Regions) != 9 {
		t.Fatalf("DE Reformationstag: %+v", w)
	}
	w = Windows("AT", 40000, false, time.Date(2026, 10, 26, 8, 0, 0, 0, vie), time.Date(2026, 10, 26, 12, 0, 0, 0, vie), vie)
	if len(w) != 1 || w[0].Holiday != "Nationalfeiertag" {
		t.Fatalf("AT Nationalfeiertag: %+v", w)
	}
	// Daylight saving ends on Sunday 25 October 2026: the ban is still
	// 00:00 to 22:00 by the clock.
	w = Windows("DE", 40000, false, time.Date(2026, 10, 25, 1, 0, 0, 0, ber), time.Date(2026, 10, 25, 23, 0, 0, 0, ber), ber)
	if len(w) != 1 || w[0].To.Format("15:04") != "22:00" {
		t.Fatalf("DST: %+v", w)
	}
}

func TestSwissAndFrenchBans(t *testing.T) {
	zrh, _ := time.LoadLocation("Europe/Zurich")
	par, _ := time.LoadLocation("Europe/Paris")
	// Switzerland, over 3.5 t: the night ban every night, all Sunday.
	w := Windows("CH", 12000, false, time.Date(2026, 11, 27, 21, 0, 0, 0, zrh), time.Date(2026, 11, 28, 6, 0, 0, 0, zrh), zrh)
	if len(w) != 2 || w[0].Rule.Name != "night ban" || w[0].From.Format("15:04") != "22:00" || w[1].To.Format("15:04") != "05:00" {
		t.Fatalf("CH night: %+v", w)
	}
	if w := Windows("CH", 12000, false, time.Date(2026, 11, 29, 10, 0, 0, 0, zrh), time.Date(2026, 11, 29, 11, 0, 0, 0, zrh), zrh); len(w) != 1 || w[0].Rule.Name != "Sunday and public holiday ban" {
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
	w = Windows("FR", 40000, false, time.Date(2026, 11, 10, 20, 0, 0, 0, par), time.Date(2026, 11, 11, 23, 0, 0, 0, par), par)
	if len(w) != 2 || w[0].From.Format("2006-01-02 15:04") != "2026-11-10 22:00" || w[0].Holiday != "eve of Armistice" || w[1].To.Format("2006-01-02 15:04") != "2026-11-11 22:00" {
		t.Fatalf("FR 11 November: %+v", w)
	}
	// A weekend: Saturday 22:00 to Sunday 22:00.
	w = Windows("FR", 40000, false, time.Date(2026, 11, 28, 12, 0, 0, 0, par), time.Date(2026, 11, 29, 23, 0, 0, 0, par), par)
	if len(w) != 2 || w[0].From.Format("Mon 15:04") != "Sat 22:00" || w[1].To.Format("Mon 15:04") != "Sun 22:00" {
		t.Fatalf("FR weekend: %+v", w)
	}
}

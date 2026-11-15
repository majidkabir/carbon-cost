package rates

import (
	"testing"
	"time"
)

func TestZone(t *testing.T) {
	z := Zone{
		Polygons: [][][2]float64{{{0, 0}, {2, 0}, {2, 2}, {0, 2}}},
		Holes:    [][][2]float64{{{0.5, 0.5}, {1, 0.5}, {1, 1}, {0.5, 1}}},
		Weekdays: []string{"07:00", "18:00"}, Weekends: []string{"12:00", "18:00"},
		NoCharge: []string{"12-25", "01-01"},
	}
	for p, want := range map[[2]float64]bool{{1.5, 1.5}: true, {0.7, 0.7}: false, {3, 1}: false} {
		if z.Contains(p) != want {
			t.Errorf("Contains(%v) = %v", p, !want)
		}
	}
	at := func(s string) time.Time { v, _ := time.Parse("2006-01-02 15:04", s); return v }
	for s, want := range map[string]bool{
		"2026-11-11 08:00": true,  // Wednesday
		"2026-11-11 19:00": false, // after hours
		"2026-11-14 10:00": false, // Saturday morning
		"2026-11-14 13:00": true,  // Saturday afternoon
		"2026-12-28 10:00": false, // Christmas to New Year
		"2027-01-01 13:00": false,
		"2027-01-04 10:00": true,
	} {
		if z.Charging(at(s)) != want {
			t.Errorf("Charging(%s) = %v", s, !want)
		}
	}
	if _, err := ZonesAll(); err != nil {
		t.Fatal(err)
	}
}

func TestEasterSeason(t *testing.T) {
	for y, want := range map[int]string{2024: "2024-03-31", 2025: "2025-04-20", 2026: "2026-04-05"} {
		if got := Easter(y).Format("2006-01-02"); got != want {
			t.Errorf("Easter %d: %s, want %s", y, got, want)
		}
	}
	// AP-46: Viernes de Dolores (Easter - 9) to the Sunday after Easter (+7).
	s := Season{Months: []int{5, 6, 7, 8, 9, 10}, Weekdays: []int{0, 6}, EasterFrom: -9, EasterTo: 7}
	for d, want := range map[string]bool{"2026-03-27": true, "2026-03-26": false, "2026-04-12": true, "2026-04-13": false, "2026-11-14": true, "2026-11-13": false, "2026-07-01": true} {
		day, _ := time.Parse("2006-01-02", d)
		if s.Has(day) != want {
			t.Errorf("%s: %v, want %v", d, !want, want)
		}
	}
}

// Norway's public holidays and the eves some projects free from rush-hour
// prices, in 2026 (Easter 5 April).
func TestNorwegianHolidays(t *testing.T) {
	for day, want := range map[string]string{
		"2026-01-01": "h", "2026-04-01": "e", "2026-04-02": "h", "2026-04-03": "h", "2026-04-06": "h",
		"2026-05-01": "h", "2026-05-14": "h", "2026-05-17": "h", "2026-05-25": "h", "2026-12-24": "e", "2026-12-25": "h",
		"2026-12-31": "e", "2026-03-31": "", "2026-05-13": "", "2026-11-05": "", "2026-12-23": "",
	} {
		d, _ := time.Parse(time.DateOnly, day)
		got := ""
		if NorwegianHoliday(d) != "" {
			got += "h"
		}
		if NorwegianEve(d) != "" {
			got += "e"
		}
		if got != want {
			t.Errorf("%s: %q, want %q", day, got, want)
		}
	}
	r := Rush{Hours: [][]string{{"06:30", "08:59"}}, FreeDays: []string{"norwegian_holidays", "july"}}
	for at, want := range map[string]bool{"2026-11-05 06:29": false, "2026-11-05 06:30": true, "2026-11-05 08:59": true,
		"2026-11-05 09:00": false, "2026-11-07 07:00": false, "2026-07-02 07:00": false, "2026-12-24 07:00": true, "2026-12-25 07:00": false} {
		tm, _ := time.Parse("2006-01-02 15:04", at)
		if got, _, err := r.In(tm); err != nil || got != want {
			t.Errorf("%s: in rush %v (%v), want %v", at, got, err, want)
		}
	}
	r.FreeDays = []string{"norwegian_holidays", "norwegian_eves"}
	if got, _, _ := r.In(time.Date(2026, 12, 24, 7, 0, 0, 0, time.UTC)); got {
		t.Error("Christmas Eve with norwegian_eves: in rush")
	}
}

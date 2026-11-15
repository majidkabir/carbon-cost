package rates

import (
	"fmt"
	"time"
)

// Rush is when a toll point charges its PeakRate: within Hours, Monday to
// Friday, except its FreeDays.
type Rush struct {
	// Hours: each from and to (HH:MM, both included).
	Hours [][]string `json:"hours"`
	// FreeDays, besides Saturdays and Sundays: "norwegian_holidays"
	// (NorwegianRushFree) and "july".
	FreeDays []string `json:"free_days,omitempty"`
}

// In says whether the local time t is in the rush hours, and if not, why.
func (r Rush) In(t time.Time) (bool, string, error) {
	day := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	if wd := day.Weekday(); wd == time.Saturday || wd == time.Sunday {
		return false, "no rush-hour price on weekends", nil
	}
	for _, f := range r.FreeDays {
		switch f {
		case "norwegian_holidays":
			if k := NorwegianRushFree(day); k != "" {
				return false, "no rush-hour price on " + k, nil
			}
		case "july":
			if day.Month() == time.July {
				return false, "no rush-hour price in July", nil
			}
		default:
			return false, "", fmt.Errorf("unknown rush-free days %q", f)
		}
	}
	at := t.Format("15:04")
	for _, h := range r.Hours {
		if len(h) != 2 {
			return false, "", fmt.Errorf("bad rush hours %v", h)
		}
		in, err := Within(at, h[0], h[1])
		if err != nil {
			return false, "", err
		}
		if in {
			return true, "", nil
		}
	}
	return false, "outside the rush hours", nil
}

// NorwegianHolidays are Norway's public holidays (offentlige fridager)
// other than ordinary Sundays, by key: the helligdager of the
// helligdagsfredloven (lov 24. februar 1995 nr. 12) § 2 and the
// høgtidsdager 1 and 17 May (lov 26. april 1947 nr. 1 § 1).
func NorwegianHolidays(year int) map[string]time.Time {
	d := func(m time.Month, day int) time.Time { return time.Date(year, m, day, 0, 0, 0, 0, time.UTC) }
	easter := easterSunday(year)
	return map[string]time.Time{
		"new_year": d(time.January, 1), "maundy_thursday": easter.AddDate(0, 0, -3), "good_friday": easter.AddDate(0, 0, -2),
		"easter": easter, "easter_monday": easter.AddDate(0, 0, 1), "may_1": d(time.May, 1), "may_17": d(time.May, 17),
		"ascension": easter.AddDate(0, 0, 39), "pentecost": easter.AddDate(0, 0, 49), "whit_monday": easter.AddDate(0, 0, 50),
		"christmas": d(time.December, 25), "boxing_day": d(time.December, 26),
	}
}

// NorwegianRushFree names the day when Norway's toll stations charge no
// rush-hour price on it although it is a weekday, or is empty: the
// Takstretningslinjer for bompengeprosjekt på offentlig veg (Vegdirektoratet,
// July 2025) § 3.3 leave out public holidays, Christmas Eve, New Year's Eve
// and the Wednesday before Maundy Thursday.
func NorwegianRushFree(day time.Time) string {
	day = time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)
	for k, h := range NorwegianHolidays(day.Year()) {
		if h.Equal(day) {
			return "a public holiday (" + k + ")"
		}
	}
	switch {
	case day.Month() == time.December && day.Day() == 24:
		return "Christmas Eve"
	case day.Month() == time.December && day.Day() == 31:
		return "New Year's Eve"
	case day.Equal(easterSunday(day.Year()).AddDate(0, 0, -4)):
		return "the Wednesday before Maundy Thursday"
	}
	return ""
}

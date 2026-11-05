package rates

import (
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"
)

// Congestion is a time-based congestion tax (Sweden's trängselskatt): its
// toll points charge, per passage, the amount of their schedule at the
// time of day, on taxed days only.
type Congestion struct {
	// Schedules are the amounts by time of day, by schedule name (a toll
	// point's Schedule).
	Schedules map[string][]TimeAmount `json:"schedules"`
	// HighSeason are the date ranges of the high season, where amounts
	// differ by season: "MM-DD", or "midsummer_eve-1" (the day before
	// Midsummer Eve).
	HighSeason [][2]string `json:"high_season,omitempty"`
	// DayCap is the most one vehicle pays in a day (DayCapHigh in high
	// season).
	DayCap     float64 `json:"day_cap,omitempty"`
	DayCapHigh float64 `json:"day_cap_high,omitempty"`
	// MultiPassMinutes: passages within this many minutes of a taxed one
	// pay once, the highest amount among them.
	MultiPassMinutes int `json:"multi_pass_minutes,omitempty"`
	// July: "free" (no tax in July) or "first5" (only on its first five
	// weekdays).
	July string `json:"july,omitempty"`
	// EveTaxed: the public holidays whose eve is taxed anyway (the day
	// before a public holiday is otherwise free): good_friday, ascension,
	// all_saints, may_1, june_6.
	EveTaxed []string `json:"eve_taxed,omitempty"`
}

// TimeAmount is a schedule's amount from From to To (HH:MM, both
// included: the hour and started minute), High in high season.
type TimeAmount struct {
	From   string  `json:"from"`
	To     string  `json:"to"`
	Amount float64 `json:"amount"`
	High   float64 `json:"high,omitempty"`
}

// SwedishHolidays are the public holidays (allmänna helgdagar, Lag
// 1989:253) of the year other than ordinary Sundays, by key.
func SwedishHolidays(year int) map[string]time.Time {
	d := func(m time.Month, day int) time.Time { return time.Date(year, m, day, 0, 0, 0, 0, time.UTC) }
	easter := easterSunday(year)
	sat := func(m time.Month, from int) time.Time { // the Saturday from the date on
		t := d(m, from)
		for t.Weekday() != time.Saturday {
			t = t.AddDate(0, 0, 1)
		}
		return t
	}
	return map[string]time.Time{
		"new_year": d(time.January, 1), "epiphany": d(time.January, 6),
		"good_friday": easter.AddDate(0, 0, -2), "easter": easter, "easter_monday": easter.AddDate(0, 0, 1),
		"may_1": d(time.May, 1), "ascension": easter.AddDate(0, 0, 39), "pentecost": easter.AddDate(0, 0, 49),
		"june_6": d(time.June, 6), "midsummer": sat(time.June, 20), "all_saints": sat(time.October, 31),
		"christmas": d(time.December, 25), "boxing_day": d(time.December, 26),
	}
}

// easterSunday by the anonymous Gregorian algorithm.
func easterSunday(y int) time.Time {
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

// Taxed says whether the tax is charged on the day, and why not.
func (c Congestion) Taxed(day time.Time) (bool, string) {
	day = time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)
	if wd := day.Weekday(); wd == time.Saturday || wd == time.Sunday {
		return false, "no tax on weekends"
	}
	hol := SwedishHolidays(day.Year())
	for k, h := range hol {
		if h.Equal(day) {
			return false, "no tax on public holidays (" + k + ")"
		}
	}
	next := SwedishHolidays(day.AddDate(0, 0, 1).Year())
	for k, h := range next {
		if h.Equal(day.AddDate(0, 0, 1)) && !slices.Contains(c.EveTaxed, k) {
			return false, "no tax on the day before a public holiday (" + k + ")"
		}
	}
	if day.Month() == time.July {
		switch c.July {
		case "free":
			return false, "no tax in July"
		case "first5":
			n := 0
			for t := time.Date(day.Year(), time.July, 1, 0, 0, 0, 0, time.UTC); !t.After(day); t = t.AddDate(0, 0, 1) {
				if wd := t.Weekday(); wd != time.Saturday && wd != time.Sunday {
					n++
				}
			}
			if n > 5 {
				return false, "no tax in July after its first five weekdays"
			}
		}
	}
	return true, ""
}

// High says whether the day is in the high season.
func (c Congestion) High(day time.Time) bool {
	md := func(s string) (time.Time, error) {
		if s == "midsummer_eve-1" {
			return SwedishHolidays(day.Year())["midsummer"].AddDate(0, 0, -2), nil
		}
		t, err := time.Parse("01-02", s)
		return time.Date(day.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC), err
	}
	day = time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)
	for _, r := range c.HighSeason {
		a, err1 := md(r[0])
		b, err2 := md(r[1])
		if err1 == nil && err2 == nil && !day.Before(a) && !day.After(b) {
			return true
		}
	}
	return false
}

// minutes parses HH:MM.
func minutes(s string) (int, error) {
	h, m, ok := strings.Cut(s, ":")
	hh, err1 := strconv.Atoi(h)
	mm, err2 := strconv.Atoi(m)
	if !ok || err1 != nil || err2 != nil || hh < 0 || hh > 23 || mm < 0 || mm > 59 {
		return 0, fmt.Errorf("bad time %q (HH:MM)", s)
	}
	return hh*60 + mm, nil
}

// Amount is the schedule's amount per passage at the time (HH:MM) on the
// day: 0 outside its hours.
func (c Congestion) Amount(schedule string, day time.Time, at string) (float64, error) {
	t, err := minutes(at)
	if err != nil {
		return 0, err
	}
	high := c.High(day)
	for _, w := range c.Schedules[schedule] {
		from, err1 := minutes(w.From)
		to, err2 := minutes(w.To)
		if err1 != nil || err2 != nil {
			return 0, fmt.Errorf("schedule %s: bad window %s–%s", schedule, w.From, w.To)
		}
		if t >= from && t <= to {
			if high && w.High > 0 {
				return w.High, nil
			}
			return w.Amount, nil
		}
	}
	return 0, nil
}

// Cap is the day's maximum.
func (c Congestion) Cap(day time.Time) float64 {
	if c.High(day) && c.DayCapHigh > 0 {
		return c.DayCapHigh
	}
	return c.DayCap
}

// ValidTime checks an HH:MM time.
func ValidTime(s string) error {
	_, err := minutes(s)
	return err
}

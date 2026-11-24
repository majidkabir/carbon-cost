package bans

import (
	"slices"
	"time"
)

// Hungary's ban is set by periods running from the evening before a day
// off, so it is built here rather than from day rules.
// 190/2008. (VII. 29.) Korm. rendelet, § 2:
//   - (1) a) from 1 July to 31 August: aa) on Saturdays that aren't
//     working days from 15:00 to Sunday 22:00; ab) on public holidays from
//     22:00 the day before to 22:00 on the day;
//   - (1) b) from 1 September to 30 June: from 22:00 the day before to
//     22:00 on Sundays and public holidays;
//   - (2) a holiday on a Friday or Saturday in summer, or on a Saturday the
//     rest of the year: one period from 08:00 on its first day to 22:00 on
//     the last;
//   - (3) from 4 November to 1 March, (1) b) and (2) don't bind trucks of
//     Euro 3 and up in international traffic.
var huRule = Rule{Country: "HU", Name: "weekend and public holiday ban", MinMassKg: 7500,
	Exemptions: "perishables, live animals, harvest, post, the others of § 5, and permits (§ 4)",
	Note:       "on all public roads",
	Law:        "190/2008. (VII. 29.) Korm. rendelet, § 2",
	Title:      "Nemzeti Jogszabálytár: 190/2008. (VII. 29.) Korm. rendelet a nehéz tehergépkocsik közlekedésének korlátozásáról",
	URL:        "https://njt.jog.gov.hu/jogszabaly/2008-190-20-22"}

// huWinter is the same ban from 4 November to 1 March, when § 2 (3)
// exempts international traffic from Euro 3.
var huWinter = func() Rule { r := huRule; r.ExemptIntlEuro = 3; return r }()

// huWorkingSaturdays are the Saturdays made working days by the year's
// decree on the working days around holidays (Mt. 102. § (5)): 10/2025.
// (IV. 30.) NGM rendelet, § 2, as amended by 4/2026. (XI. 13.) SZCSM
// rendelet. Other years' aren't in.
var huWorkingSaturdays = []string{"2026-01-10", "2026-08-08"}

func init() {
	Rules = append(Rules, huRule)
	HolidaySources["HU"] = [2]string{"Nemzeti Jogszabálytár: 2026. évi LXXII. törvény (december 24., Mt. 102. § (1))", "https://njt.jog.gov.hu/jogszabaly/2026-72-00-00"}
}

func huWindows(from, to time.Time, loc *time.Location) []Window {
	hol := map[string]Holiday{}
	for y := from.In(loc).Year() - 1; y <= to.In(loc).Year()+1; y++ {
		for _, h := range Holidays("HU", y) {
			hol[h.Date.Format(time.DateOnly)] = h
		}
	}
	key := func(d time.Time) string { return d.Format(time.DateOnly) }
	summer := func(d time.Time) bool { md := d.Format("01-02"); return md >= "07-01" && md <= "08-31" }
	isHol := func(d time.Time) bool { _, ok := hol[key(d)]; return ok }
	off := func(d time.Time) bool { return d.Weekday() == time.Sunday || isHol(d) }
	workSat := func(d time.Time) bool { return slices.Contains(huWorkingSaturdays, key(d)) }
	summerSat := func(d time.Time) bool { return summer(d) && d.Weekday() == time.Saturday && !workSat(d) && !isHol(d) }
	date := func(d time.Time, h int) time.Time { return time.Date(d.Year(), d.Month(), d.Day(), h, 0, 0, 0, loc) }
	add := func(d time.Time, n int) time.Time { return time.Date(d.Year(), d.Month(), d.Day()+n, 0, 0, 0, 0, loc) }

	type span struct {
		from, to time.Time
		holiday  string
	}
	var spans []span
	start := add(time.Date(from.In(loc).Year(), from.In(loc).Month(), from.In(loc).Day(), 0, 0, 0, 0, loc), -4)
	for d := start; d.Before(add(to.In(loc), 4)); d = add(d, 1) {
		h := hol[key(d)]
		switch {
		case isHol(d) && (summer(d) && (d.Weekday() == time.Friday || d.Weekday() == time.Saturday) || !summer(d) && d.Weekday() == time.Saturday):
			// § 2 (2): from 08:00 on the first day of the run of days off
			// to 22:00 on its last.
			first, last := d, d
			for p := add(first, -1); off(p) || summerSat(p); p = add(p, -1) {
				first = p
			}
			for n := add(last, 1); off(n) || summerSat(n); n = add(n, 1) {
				last = n
			}
			spans = append(spans, span{date(first, 8), date(last, 22), h.Name})
		case summerSat(d):
			spans = append(spans, span{date(d, 15), date(add(d, 1), 22), ""})
		case off(d) && (!summer(d) || isHol(d)):
			spans = append(spans, span{date(add(d, -1), 22), date(d, 22), h.Name})
		}
	}
	// Periods that overlap or touch are one.
	slices.SortStableFunc(spans, func(a, b span) int { return a.from.Compare(b.from) })
	var merged []span
	for _, s := range spans {
		if n := len(merged); n > 0 && !s.from.After(merged[n-1].to) {
			if s.to.After(merged[n-1].to) {
				merged[n-1].to = s.to
			}
			if merged[n-1].holiday == "" {
				merged[n-1].holiday = s.holiday
			}
			continue
		}
		merged = append(merged, s)
	}
	var out []Window
	for _, s := range merged {
		if !s.to.After(from) || !s.from.Before(to) {
			continue
		}
		r := huRule
		if md := s.from.Format("01-02"); (md >= "11-04" || md <= "03-01") && !summer(s.from) {
			r = huWinter
		}
		out = append(out, Window{Rule: r, From: s.from, To: s.to, Holiday: s.holiday})
	}
	return out
}

// Exempt says the window doesn't bind the truck: Hungary's winter
// exemption for Euro 3 and up in international traffic.
func (w Window) Exempt(euro int, international bool) bool {
	return w.Rule.ExemptIntlEuro > 0 && international && euro >= w.Rule.ExemptIntlEuro
}

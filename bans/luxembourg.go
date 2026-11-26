package bans

import (
	"slices"
	"time"
)

// Luxembourg: Règlement grand-ducal du 19 juillet 1997 relatif aux
// limitations de la circulation des poids lourds les dimanches et jours
// fériés (consolidated version of 23 December 2024), over 7.5 t, only in
// transit:
//   - art. 1: from Belgium or Germany towards France, from 21:30 on
//     Saturdays and the eves of the holidays of art. 3 to 21:45 on the
//     Sundays and holidays; from Belgium or France towards Germany, from
//     23:30;
//   - art. 3: 1 January, Easter Monday, 1 May, Ascension, Whit Monday,
//     15 August, 1 November and 25 December; towards France also 8 May,
//     14 July and 11 November; towards Germany also Good Friday, Corpus
//     Christi, 3 October and 26 December.
//
// The minister's one-off derogations (art. 2bis) aren't followed.
var luBase = Rule{Country: "LU", MinMassKg: 7500,
	Exemptions: "live animals, perishables, harvest, fairs and events, press, removals, combined transport towards Germany up to 200 km, emergency services and ministerial permits (art. 2)",
	Law:        "Règlement grand-ducal du 19 juillet 1997 relatif aux limitations de la circulation des poids lourds les dimanches et jours fériés, art. 1 and 3",
	Title:      "Legilux: Règlement grand-ducal du 19 juillet 1997 relatif aux limitations de la circulation des poids lourds les dimanches et jours fériés (version consolidée)",
	URL:        "https://legilux.public.lu/eli/etat/leg/rgd/1997/07/19/n2/consolide/20241223"}

var luToFR = func() Rule {
	r := luBase
	r.Name, r.From, r.To = "Sunday and holiday ban for transit to France", "21:30", "21:45"
	r.TransitFrom, r.TransitTo = []string{"BE", "DE"}, "FR"
	r.Note = "only in transit from Belgium or Germany towards France"
	return r
}()

var luToDE = func() Rule {
	r := luBase
	r.Name, r.From, r.To = "Sunday and holiday ban for transit to Germany", "23:30", "21:45"
	r.TransitFrom, r.TransitTo = []string{"BE", "FR"}, "DE"
	r.Note = "only in transit from Belgium or France towards Germany"
	return r
}()

func init() {
	Rules = append(Rules, luToFR, luToDE)
	HolidaySources["LU"] = [2]string{luBase.Title + ", art. 3", luBase.URL}
}

// luHolidays are art. 3's holidays for transit towards to (FR or DE).
func luHolidays(to string, y int) []Holiday {
	e := easter(y)
	fixed := func(m time.Month, d int, name string) Holiday {
		return Holiday{Date: time.Date(y, m, d, 0, 0, 0, 0, time.UTC), Name: name}
	}
	moving := func(days int, name string) Holiday { return Holiday{Date: e.AddDate(0, 0, days), Name: name} }
	h := []Holiday{fixed(1, 1, "Jour de l'An"), moving(1, "Lundi de Pâques"), fixed(5, 1, "Fête du Travail"), moving(39, "Ascension"),
		moving(50, "Lundi de Pentecôte"), fixed(8, 15, "Assomption"), fixed(11, 1, "Toussaint"), fixed(12, 25, "Noël")}
	if to == "FR" {
		h = append(h, fixed(5, 8, "8 mai"), fixed(7, 14, "14 juillet"), fixed(11, 11, "11 novembre"))
	} else {
		h = append(h, moving(-2, "Vendredi Saint"), moving(60, "Fête-Dieu"), fixed(10, 3, "3 octobre"), fixed(12, 26, "St. Etienne"))
	}
	return h
}

// luWindows are each direction's bans, from the evening before a Sunday
// or holiday to 21:45 on it, runs of days merged into one window.
func luWindows(maxMassKg, towKg int, from, to time.Time, loc *time.Location) []Window {
	var out []Window
	for _, r := range []Rule{luToFR, luToDE} {
		if !r.Applies(maxMassKg, towKg) {
			continue
		}
		hol := map[string]Holiday{}
		for y := from.In(loc).Year() - 1; y <= to.In(loc).Year()+1; y++ {
			for _, h := range luHolidays(r.TransitTo, y) {
				hol[h.Date.Format(time.DateOnly)] = h
			}
		}
		var ws []Window
		start := time.Date(from.In(loc).Year(), from.In(loc).Month(), from.In(loc).Day()-2, 0, 0, 0, 0, loc)
		for d := start; d.Before(to.In(loc).AddDate(0, 0, 1)); d = time.Date(d.Year(), d.Month(), d.Day()+1, 0, 0, 0, 0, loc) {
			h, isHol := hol[d.Format(time.DateOnly)]
			if d.Weekday() != time.Sunday && !isHol {
				continue
			}
			w := Window{Rule: r, From: at(d.AddDate(0, 0, -1), r.From), To: at(d, r.To)}
			if isHol {
				w.Holiday = h.Name
			}
			if n := len(ws); n > 0 && !ws[n-1].To.Before(w.From) {
				ws[n-1].To = w.To
				if ws[n-1].Holiday == "" {
					ws[n-1].Holiday = w.Holiday
				}
				continue
			}
			ws = append(ws, w)
		}
		for _, w := range ws {
			if w.To.After(from) && w.From.Before(to) {
				out = append(out, w)
			}
		}
	}
	slices.SortStableFunc(out, func(a, b Window) int { return a.From.Compare(b.From) })
	return out
}

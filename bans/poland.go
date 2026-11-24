package bans

import "time"

// Poland: rozporządzenie Ministra Transportu z dnia 31 lipca 2007 r. w
// sprawie okresowych ograniczeń oraz zakazu ruchu niektórych rodzajów
// pojazdów na drogach (consolidated text Dz. U. 2023 poz. 2423), § 2:
// over 12 t on all roads, 08:00-22:00 on its holidays, 18:00-22:00 on the
// eves of b) to j), and in the school summer holidays Fridays
// 18:00-22:00, Saturdays 08:00-14:00 and Sundays 08:00-22:00.
var plRule = Rule{Country: "PL", MinMassKg: 12000,
	Exemptions: "dangerous goods under orange plates, perishables of annex 1, live animals, post, fuel, combined transport, trucks returning to their base, and the others of § 3",
	Note:       "on all roads",
	Law:        "Rozporządzenie Ministra Transportu z dnia 31 lipca 2007 r. (Dz. U. 2023 poz. 2423), § 2",
	Title:      "ISAP: Dz. U. 2023 poz. 2423, okresowe ograniczenia oraz zakaz ruchu niektórych rodzajów pojazdów na drogach",
	URL:        "https://api.sejm.gov.pl/eli/acts/DU/2023/2423/text.html"}

// plSummer is § 2 pkt 3's period: from the Friday school lessons end on,
// or the next one after they end, to the last Sunday before they start.
// Lessons end on the first Friday after 20 June, or the Wednesday before
// when that Thursday is a holiday (then the period still starts on that
// Friday), and start on the first weekday of September, the Monday after
// when 1 September is a Friday or Saturday (rozporządzenie MEN z dnia 11
// sierpnia 2017 r. w sprawie organizacji roku szkolnego, Dz. U. 2023 poz.
// 1211, § 2 ust. 1).
func plSummer(y int) (time.Time, time.Time) {
	from := time.Date(y, 6, 21, 0, 0, 0, 0, time.UTC)
	for from.Weekday() != time.Friday {
		from = from.AddDate(0, 0, 1)
	}
	start := time.Date(y, 9, 1, 0, 0, 0, 0, time.UTC)
	for start.Weekday() == time.Saturday || start.Weekday() == time.Sunday || start.Weekday() == time.Friday {
		start = start.AddDate(0, 0, 1)
	}
	to := start.AddDate(0, 0, -1)
	for to.Weekday() != time.Sunday {
		to = to.AddDate(0, 0, -1)
	}
	return from, to
}

func init() {
	day, eve := plRule, plRule
	day.Name, day.Days, day.From, day.To = "public holiday ban", []string{"holiday"}, "08:00", "22:00"
	eve.Name, eve.Days, eve.From, eve.To = "public holiday eve ban", []string{"holiday_eve"}, "18:00", "22:00"
	Rules = append(Rules, day, eve)
	for _, d := range []struct{ day, from, to string }{{"fri", "18:00", "22:00"}, {"sat", "08:00", "14:00"}, {"sun", "08:00", "22:00"}} {
		r := plRule
		r.Name, r.Days, r.From, r.To, r.Season = "summer holiday ban", []string{d.day}, d.from, d.to, plSummer
		Rules = append(Rules, r)
	}
	HolidaySources["PL"] = [2]string{plRule.Title, plRule.URL}
}

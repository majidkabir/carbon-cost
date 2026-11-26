package bans

import "time"

// Slovenia: Odredba o omejitvi prometa na cestah v Republiki Sloveniji
// (Uradni list RS, št. 75/11, 195/21 in 67/25), 2. člen: over 7.5 t, on
// the roads of its 4. člen, the Friday before Easter 14:00-22:00, Sundays
// and days off 08:00-22:00, and in the tourist season Saturdays
// 08:00-13:00 (06:00-16:00 on five of the listed roads, not told apart
// here).
var siRule = Rule{Country: "SI", MinMassKg: 7500,
	Exemptions: "the order's exemptions (perishables, live animals, and others)",
	Note:       "on the motorways and main roads the order lists; on five of them in the tourist season Saturdays 06:00-16:00",
	Law:        "Odredba o omejitvi prometa na cestah v Republiki Sloveniji (Uradni list RS, št. 75/11, 195/21 in 67/25), 2. člen",
	Title:      "Uradni list RS, št. 75/2011: Odredba o omejitvi prometa na cestah v Republiki Sloveniji",
	URL:        "https://www.uradni-list.si/glasilo-uradni-list-rs/vsebina/2011-01-3206"}

// siSeason is 2. člen (2)'s tourist season: from the last weekend
// (Saturday and Sunday) in June to the first in September, both included.
func siSeason(y int) (time.Time, time.Time) {
	sun := time.Date(y, 6, 30, 0, 0, 0, 0, time.UTC)
	for sun.Weekday() != time.Sunday {
		sun = sun.AddDate(0, 0, -1)
	}
	sat := time.Date(y, 9, 1, 0, 0, 0, 0, time.UTC)
	for sat.Weekday() != time.Saturday {
		sat = sat.AddDate(0, 0, 1)
	}
	return sun.AddDate(0, 0, -1), sat.AddDate(0, 0, 1)
}

func init() {
	fri, sun, sat := siRule, siRule, siRule
	fri.Name, fri.Days, fri.From, fri.To = "Good Friday ban", []string{"good_friday"}, "14:00", "22:00"
	sun.Name, sun.Days, sun.From, sun.To = "Sunday and day off ban", []string{"sun", "holiday"}, "08:00", "22:00"
	sat.Name, sat.Days, sat.From, sat.To, sat.Season = "tourist season Saturday ban", []string{"sat"}, "08:00", "13:00", siSeason
	Rules = append(Rules, fri, sun, sat)
	HolidaySources["SI"] = [2]string{"GOV.SI: Državni prazniki, dela prosti dnevi in dan žalovanja", "https://www.gov.si/teme/drzavni-prazniki-in-dela-prosti-dnevi/"}
}

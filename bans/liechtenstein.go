package bans

// Liechtenstein: Verkehrsregelnverordnung (VRV, LGBl. 1978 Nr. 19),
// Art. 89, under the Strassenverkehrsgesetz's Art. 2 Abs. 2: on all
// Sundays and its holidays, and every night 22:00-05:00, for heavy motor
// vehicles (over 3.5 t), articulated vehicles over 5 t and vehicles
// towing a trailer over 3.5 t.
var liRule = Rule{Country: "LI", MinMassKg: 3500, TrailerMassKg: 3500,
	Exemptions: "Art. 89a, and permits valid for Switzerland and Liechtenstein (Art. 90)",
	Note:       "articulated vehicles over 5 t combined, and vehicles towing a trailer over 3.5 t, too",
	Law:        "Verkehrsregelnverordnung (VRV, LGBl. 1978 Nr. 19), Art. 89",
	Title:      "Gesetze.li: Verkehrsregelnverordnung (VRV), Fassung 01.05.2023",
	URL:        "https://gesetze.li/konso/pdf/1978019000?version=54"}

func init() {
	sunday, night1, night2 := liRule, liRule, liRule
	all := []string{"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
	sunday.Name, sunday.Days, sunday.From, sunday.To = "Sunday and public holiday ban", []string{"sun", "holiday"}, "00:00", "24:00"
	night1.Name, night1.Days, night1.From, night1.To = "night ban", all, "00:00", "05:00"
	night2.Name, night2.Days, night2.From, night2.To = "night ban", all, "22:00", "24:00"
	Rules = append(Rules, sunday, night1, night2)
	HolidaySources["LI"] = [2]string{liRule.Title, liRule.URL}
}

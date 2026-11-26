package bans

import "time"

// Romania: Ordinul MT-MAI nr. 1249/132/2018 (consolidated with Ordinul
// nr. 248/2022), anexa nr. 1: over 7.5 t, on four sections only:
//   - A2 București–Constanța: from 1 April to 30 September, the day
//     before a holiday 16:00-22:00 and the holidays 06:00-22:00, both
//     ways; from 1 July to 31 August, towards Constanța Fridays
//     12:00-22:00 and Saturdays 06:00-22:00, towards București Sundays
//     06:00-22:00 and Mondays 12:00-22:00;
//   - DN7 Pitești–Râmnicu Vâlcea–Veștem: all year, the day before a
//     holiday 18:00-22:00 and the holidays 06:00-22:00; from 1 July to
//     31 August Fridays 18:00-22:00, Saturdays and Sundays 06:00-22:00;
//   - DN39 Agigea–Mangalia: from 1 April to 30 September, the day before
//     a holiday 16:00-22:00 and the holidays 06:00-22:00; from 1 July to
//     31 August Fridays, Saturdays and Sundays 06:00-22:00;
//   - DN22C Murfatlar–Cernavodă, towards Cernavodă: from 1 July to
//     31 August Sundays 06:00-22:00.
//
// The free days the government declares between holidays and weekends
// (art. 2 (2)) hold like holidays; they aren't followed here.
var roRule = Rule{Country: "RO", MinMassKg: 7500, Listed: true,
	Exemptions: "the vehicles of anexa nr. 2 (army, police, ambulance, fire, perishables, live animals, fuel, and others) and local residents (riverani)",
	Law:        "Ordinul MT-MAI nr. 1249/132/2018, anexa nr. 1 (as amended by Ordinul nr. 248/2022)",
	Title:      "CNAIR: Ordinul nr. 1249/132/2018 privind instituirea restricției de circulație pentru vehiculele rutiere cu masa totală maximă autorizată mai mare de 7,5 tone (consolidated 31 January 2024)",
	URL:        "https://www.cnadnr.ro/sites/default/files/pagini-statice/Ordin%20comun%20MT%20-%20MAI%201249%20-%20132%20din%202018.pdf"}

func init() {
	r := func(name string, days []string, from, to, fromDay, toDay string, roads []string, note string) Rule {
		x := roRule
		x.Name, x.Days, x.From, x.To, x.FromDay, x.ToDay, x.Roads, x.Note = name, days, from, to, fromDay, toDay, roads, note
		return x
	}
	a2 := "on the A2 from București (A2/DNCB) to Constanța (A2/A4)"
	dn7 := "on the DN7 from Pitești (DN7/DN7C) through Râmnicu Vâlcea to Veștem (DN7/DN1), both ways"
	dn39 := "on the DN39 from Agigea (DN39/DN39A) to Mangalia, both ways"
	Rules = append(Rules,
		r("holiday eve ban", []string{"holiday_eve"}, "16:00", "22:00", "04-01", "09-30", []string{"A2"}, a2+", both ways"),
		r("holiday ban", []string{"holiday"}, "06:00", "22:00", "04-01", "09-30", []string{"A2"}, a2+", both ways"),
		r("summer Friday ban", []string{"fri"}, "12:00", "22:00", "07-01", "08-31", []string{"A2"}, a2+", towards Constanța"),
		r("summer Saturday ban", []string{"sat"}, "06:00", "22:00", "07-01", "08-31", []string{"A2"}, a2+", towards Constanța"),
		r("summer Sunday ban", []string{"sun"}, "06:00", "22:00", "07-01", "08-31", []string{"A2"}, a2+", towards București"),
		r("summer Monday ban", []string{"mon"}, "12:00", "22:00", "07-01", "08-31", []string{"A2"}, a2+", towards București"),
		r("holiday eve ban", []string{"holiday_eve"}, "18:00", "22:00", "", "", []string{"DN7"}, dn7),
		r("holiday ban", []string{"holiday"}, "06:00", "22:00", "", "", []string{"DN7"}, dn7),
		r("summer Friday ban", []string{"fri"}, "18:00", "22:00", "07-01", "08-31", []string{"DN7"}, dn7),
		r("summer weekend ban", []string{"sat", "sun"}, "06:00", "22:00", "07-01", "08-31", []string{"DN7"}, dn7),
		r("holiday eve ban", []string{"holiday_eve"}, "16:00", "22:00", "04-01", "09-30", []string{"DN39"}, dn39),
		r("holiday ban", []string{"holiday"}, "06:00", "22:00", "04-01", "09-30", []string{"DN39"}, dn39),
		r("summer weekend ban", []string{"fri", "sat", "sun"}, "06:00", "22:00", "07-01", "08-31", []string{"DN39"}, dn39),
		r("summer Sunday ban", []string{"sun"}, "06:00", "22:00", "07-01", "08-31", []string{"DN22C"}, "on the DN22C from Murfatlar (DN22C/DN3) towards Cernavodă (DN22C/A2)"),
	)
	HolidaySources["RO"] = [2]string{"Camera Deputaților, Departamentul de Studii Parlamentare: Sărbători legale (the days of Legea nr. 53/2003 – Codul muncii, art. 139 alin. (1), as completed by Legea nr. 52/2023)",
		"https://www.cdep.ro/intranet/docs_dip/13818_sarbatorilegale.pdf"}
}

// orthodoxEaster is the Orthodox Easter Sunday of a year (the Julian
// computus, in the Gregorian calendar).
func orthodoxEaster(y int) time.Time {
	a, b, c := y%4, y%7, y%19
	d := (19*c + 15) % 30
	e := (2*a + 4*b - d + 34) % 7
	month := (d + e + 114) / 31
	day := (d+e+114)%31 + 1
	return time.Date(y, time.Month(month), day, 0, 0, 0, 0, time.UTC).AddDate(0, 0, y/100-y/400-2)
}

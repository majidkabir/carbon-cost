package bans

import (
	"embed"
	"encoding/json"
	"slices"
	"time"
)

// Calendars are bans a country sets by decree for each day of a year
// (Italy's yearly calendar), transcribed into data/<country>-<year>.json.
//
//go:embed data/*.json
var calendarFiles embed.FS

// Calendar is one year's decree.
type Calendar struct {
	Country string `json:"country"`
	Year    int    `json:"year"`
	Law     string `json:"law"`
	Source  struct {
		ID, Title, URL, Page string
	} `json:"source"`
	Days []struct {
		Date, From, To string
		// FromDate, ToDate and Weekday ("sat"): every such weekday in the
		// range, both ends included, instead of Date.
		FromDate string `json:"from_date"`
		ToDate   string `json:"to_date"`
		Weekday  string
		// Listed: only on roads the decree lists (see Note), Roads their
		// refs.
		Listed bool
		Roads  []string
		Note   string
		// Except are dates of a weekday range it doesn't hold on.
		Except []string
	} `json:"days"`
}

var calendars = map[string][]Calendar{}

// calendarRules are the rules a country's calendars hold their windows
// under. Spain's calendar is only listed roads.
var calendarRules = map[string]Rule{
	"AT": {Country: "AT", Name: "road ban of the year's decree", MinMassKg: 7500, TrailerMassKg: 7500,
		Exemptions: "those of each decree's § 2 (and § 1's local traffic, where named)"},
	"ES": {Country: "ES", Name: "road restriction of the DGT's resolution", MinMassKg: 7500,
		Exemptions: "live animals, perishables (ATP) of at least half the load, Correos' universal postal service Monday to Friday, de-icing material in winter and breakdown vehicles (B.1.2)",
		Note:       "on the roads the DGT watches; Catalonia and the Basque Country set their own"},
	"FR": {Country: "FR", Name: "complementary Saturday ban", MinMassKg: 7500,
		Exemptions: "those of the arrêté du 16 avril 2021, art. 4, and prefects' permits",
		Note:       "summer Saturdays on the whole network"},
	"GR": {Country: "GR", Name: "holiday and summer ban on listed roads", MinMassKg: 3500,
		Exemptions: "road assistance, post and press, live animals and ATP perishables of at least 10% of the load, fresh fruit and vegetables, fuel for firefighting, utilities' repairs and the others of άρθρο 1, Γ",
		Note:       "on the motorway and national road sections the decision lists"},
	"IT": {Country: "IT", Name: "calendar ban", MinMassKg: 7500,
		Exemptions: "perishables, live animals, post, fuel, combined transport and the others of art. 7 and 8, and prefects' permits",
		Note:       "on roads outside built-up areas; with papers, from abroad it starts 4 h later and to abroad it ends 2 h earlier (art. 3), and Sardinia's and Sicily's ferries have their own shifts (art. 4 and 5)"},
}

func init() {
	files, _ := calendarFiles.ReadDir("data")
	for _, f := range files {
		b, _ := calendarFiles.ReadFile("data/" + f.Name())
		var c Calendar
		if err := json.Unmarshal(b, &c); err != nil {
			panic("bans: " + f.Name() + ": " + err.Error())
		}
		calendars[c.Country] = append(calendars[c.Country], c)
		if c.Days == nil || calendarRules[c.Country].Country == "" {
			panic("bans: " + f.Name() + ": no days, or no calendar rule for " + c.Country)
		}
	}
	for cc, r := range calendarRules {
		if len(calendars[cc]) > 0 && !hasRules(cc) {
			Rules = append(Rules, r)
		}
	}
}

// calendarWindows are a calendar country's windows from to to; none for a
// year whose decree isn't in.
func calendarWindows(country string, from, to time.Time, loc *time.Location) []Window {
	var out []Window
	for _, c := range calendars[country] {
		r := calendarRules[country]
		r.Law, r.Title, r.URL = c.Law, c.Source.Title, c.Source.URL
		for _, d := range c.Days {
			var days []time.Time
			if d.Date != "" {
				if day, err := time.ParseInLocation(time.DateOnly, d.Date, loc); err == nil {
					days = append(days, day)
				}
			} else if a, err1 := time.ParseInLocation(time.DateOnly, d.FromDate, loc); err1 == nil {
				if b, err2 := time.ParseInLocation(time.DateOnly, d.ToDate, loc); err2 == nil {
					for day := a; !day.After(b); day = time.Date(day.Year(), day.Month(), day.Day()+1, 0, 0, 0, 0, loc) {
						if weekday[day.Weekday()] == d.Weekday && !slices.Contains(d.Except, day.Format(time.DateOnly)) {
							days = append(days, day)
						}
					}
				}
			}
			rr := r
			if d.Listed {
				rr.Listed, rr.Note, rr.Roads = true, d.Note, d.Roads
			}
			for _, day := range days {
				w := Window{Rule: rr, From: at(day, d.From), To: at(day, d.To)}
				if w.To.After(from) && w.From.Before(to) {
					out = append(out, w)
				}
			}
		}
	}
	return out
}

// CalendarYears are the years a calendar country's decrees are in.
func CalendarYears(country string) []int {
	var ys []int
	for _, c := range calendars[country] {
		if !slices.Contains(ys, c.Year) {
			ys = append(ys, c.Year)
		}
	}
	return ys
}

// hasRules says the country has day rules besides its calendars.
func hasRules(country string) bool {
	for _, r := range Rules {
		if r.Country == country {
			return true
		}
	}
	return false
}

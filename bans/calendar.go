package bans

import (
	"embed"
	"encoding/json"
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
	} `json:"days"`
}

var calendars = map[string][]Calendar{}

// calendarRules are the rules a country's calendars hold their windows
// under.
var calendarRules = map[string]Rule{
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
		r := calendarRules[c.Country]
		r.Law, r.Title, r.URL = c.Law, c.Source.Title, c.Source.URL
		calendarRules[c.Country] = r
	}
	for _, r := range calendarRules {
		Rules = append(Rules, r)
	}
}

// calendarWindows are a calendar country's windows from to to; none for a
// year whose decree isn't in.
func calendarWindows(country string, from, to time.Time, loc *time.Location) []Window {
	var out []Window
	for _, c := range calendars[country] {
		for _, d := range c.Days {
			day, err := time.ParseInLocation(time.DateOnly, d.Date, loc)
			if err != nil {
				continue
			}
			w := Window{Rule: calendarRules[country], From: at(day, d.From), To: at(day, d.To)}
			if w.To.After(from) && w.From.Before(to) {
				out = append(out, w)
			}
		}
	}
	return out
}

// CalendarYears are the years a calendar country's decrees are in.
func CalendarYears(country string) []int {
	var ys []int
	for _, c := range calendars[country] {
		ys = append(ys, c.Year)
	}
	return ys
}

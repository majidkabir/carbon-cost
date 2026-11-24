package cost

import (
	"fmt"
	"math"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/bans"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// BanHit is a driving ban the trip runs into.
type BanHit struct {
	Country string `json:"country"`
	Ban     string `json:"ban"`
	// From and To are the ban's window, local time (RFC 3339).
	From string `json:"from"`
	To   string `json:"to"`
	// Holiday names the public holiday it is for, and Regions where it is
	// kept only in some regions.
	Holiday string   `json:"holiday,omitempty"`
	Regions []string `json:"regions,omitempty"`
	// Certain: the trip is in the country while the ban is in force, by
	// its passage times. Otherwise it may be: no departure time was given,
	// the holiday is regional, or the leg crosses several countries and
	// Sootcase didn't say in which order.
	Certain bool `json:"certain"`
	// WaitH is how long the truck waits for the ban to end, where Certain.
	WaitH float64 `json:"wait_h,omitempty"`
	// Note says where or for whom else the ban holds.
	Note       string `json:"note,omitempty"`
	Exemptions string `json:"exemptions,omitempty"`
	Law        string `json:"law"`
}

// segment is a stretch of the route in one country, km along it.
type segment struct {
	country  string
	from, to float64
	ordered  bool
}

// segments are the route's stretches by country: a leg in one country is
// one; a leg across several is split only where Sootcase gives its
// country_sections, else its countries are kept unordered over the leg.
func segments(res sootcase.Result) []segment {
	var out []segment
	pos := 0.0
	for _, l := range res.Legs {
		end := pos + l.DistanceKm
		switch {
		case len(l.CountrySections) > 0:
			for _, s := range l.CountrySections {
				out = append(out, segment{s.Country, pos + s.FromKm, pos + s.ToKm, true})
			}
		default:
			ccs := make([]string, 0, len(l.CountryKm))
			for cc, km := range l.CountryKm {
				if km >= 0.5 {
					ccs = append(ccs, cc)
				}
			}
			sort.Strings(ccs)
			for _, cc := range ccs {
				out = append(out, segment{cc, pos, end, len(ccs) == 1})
			}
		}
		pos = end
	}
	return out
}

// checkBans finds the driving bans the trip runs into, by its passage
// times where a departure time is given, else by its days.
func checkBans(out *Response, res sootcase.Result, req Request, date time.Time) {
	segs := segments(res)
	trailer := false
	var hits []BanHit
	var wait float64
	seen := map[string]bool{}
	countries := 0
	for _, km := range out.CountryKm {
		if km >= 0.5 {
			countries++
		}
	}
	exempted := false
	// windows are the bans in force, less those the truck is exempt from.
	windows := func(country string, from, to time.Time, loc *time.Location) []bans.Window {
		ws := bans.Windows(country, req.Truck.MaxMassKg, trailer, from, to, loc)
		return slices.DeleteFunc(ws, func(w bans.Window) bool {
			if w.Exempt(req.Truck.Euro, countries > 1) {
				exempted = true
				return true
			}
			return false
		})
	}
	for _, s := range segs {
		if !slices.ContainsFunc(bans.Rules, func(r bans.Rule) bool { return r.Country == s.country }) {
			continue
		}
		loc := zone(s.country)
		t0, timed := passage(req, date, s.from, s.country)
		t1, _ := passage(req, date, s.to, s.country)
		if !timed {
			// No departure time: the days the trip may take.
			t0 = time.Date(date.Year(), date.Month(), date.Day(), 0, 0, 0, 0, loc)
			days := 1 + int(math.Ceil(tripHoursFor(out, req)/24))
			t1 = t0.AddDate(0, 0, days)
		}
		shift := time.Duration(wait * float64(time.Hour))
		t0, t1 = t0.Add(shift), t1.Add(shift)
		add := func(w bans.Window, certain bool, waitH float64) {
			key := s.country + w.From.String()
			if seen[key] {
				return
			}
			seen[key] = true
			hits = append(hits, BanHit{Country: s.country, Ban: w.Rule.Name, From: w.From.Format(time.RFC3339), To: w.To.Format(time.RFC3339),
				Holiday: w.Holiday, Regions: w.Regions, Note: w.Rule.Note, Exemptions: w.Rule.Exemptions, Law: w.Rule.Law, Certain: certain, WaitH: waitH})
			addSource(out, rates.Source{Title: w.Rule.Title, URL: w.Rule.URL})
			if src, ok := bans.HolidaySources[s.country]; ok && w.Holiday != "" {
				addSource(out, rates.Source{Title: src[0], URL: src[1]})
			}
		}
		if !timed || !s.ordered {
			for _, w := range windows(s.country, t0, t1, loc) {
				add(w, false, 0)
			}
			continue
		}
		// Drive the segment, stopping for each ban in force until it ends;
		// a regional holiday's ban is reported, not waited for.
		cursor, left := t0, t1.Sub(t0)
		for left > 0 {
			var next *bans.Window
			for _, w := range windows(s.country, cursor, cursor.Add(left), loc) {
				if len(w.Regions) > 0 || w.Rule.Listed {
					add(w, false, 0)
					continue
				}
				if next == nil || w.From.Before(next.From) {
					w := w
					next = &w
				}
			}
			if next == nil {
				break
			}
			stop := cursor
			if next.From.After(stop) {
				stop = next.From
			}
			left -= stop.Sub(cursor)
			waitH := math.Round(next.To.Sub(stop).Hours()*100) / 100
			add(*next, true, waitH)
			wait += waitH
			cursor = next.To
		}
	}
	out.Bans = hits
	for cc := range out.CountryKm {
		if out.CountryKm[cc] >= 0.5 && len(bans.CalendarYears(cc)) > 0 && !slices.Contains(bans.CalendarYears(cc), date.Year()) {
			out.Notes = append(out.Notes, fmt.Sprintf("Driving ban: %s's calendar of bans for %d isn't in, so its bans aren't checked.", cc, date.Year()))
		}
	}
	if exempted {
		out.Notes = append(out.Notes, "Driving ban: Hungary's weekend and holiday ban doesn't bind a truck of Euro 3 and up in international traffic from 4 November to 1 March (190/2008. (VII. 29.) Korm. rendelet, § 2 (3)).")
	}
	if out.Trip != nil && wait > 0 {
		out.Trip.BanWaitH = math.Round(wait*100) / 100
	}
	for _, h := range hits {
		from, _ := time.Parse(time.RFC3339, h.From)
		to, _ := time.Parse(time.RFC3339, h.To)
		what := fmt.Sprintf("%s's %s (%s) from %s to %s", h.Country, h.Ban, h.Law, from.Format("Mon 2 Jan 15:04"), to.Format("Mon 2 Jan 15:04"))
		if h.Note != "" {
			what += " (" + h.Note + ")"
		}
		if h.Holiday != "" {
			what += ", " + h.Holiday
			if len(h.Regions) > 0 {
				what += " (only in " + strings.Join(h.Regions, ", ") + ")"
			}
		}
		switch {
		case h.Certain:
			out.Notes = append(out.Notes, fmt.Sprintf("Driving ban: the truck reaches %s and waits %.1f h, unless exempt (%s).", what, h.WaitH, h.Exemptions))
		case req.Time == "":
			out.Notes = append(out.Notes, fmt.Sprintf("Driving ban: the trip may run into %s; give the departure time (time) to check.", what))
		default:
			out.Notes = append(out.Notes, fmt.Sprintf("Driving ban: the trip may run into %s.", what))
		}
	}
	for cc, note := range bans.NightNotes {
		if out.CountryKm[cc] >= 0.5 && req.Truck.MaxMassKg > 7500 {
			out.Notes = append(out.Notes, "Night ban: "+note+".")
		}
	}
}

// tripHoursFor is the trip's time for its days: with rests where asked.
func tripHoursFor(out *Response, req Request) float64 {
	if out.Trip == nil {
		return 0
	}
	if out.Trip.ElapsedH > 0 {
		return out.Trip.ElapsedH
	}
	return out.Trip.Hours
}

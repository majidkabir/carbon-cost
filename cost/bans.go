package cost

import (
	"fmt"
	"maps"
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
	// Country is where the ban holds (ISO 3166-1 alpha-2).
	Country string `json:"country"`
	// Ban names the rule: the days and hours it holds and for which trucks.
	Ban string `json:"ban"`
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
	// Note says where or for whom else the ban holds; Listed, that it
	// holds only on the roads it names (Roads, their refs).
	Note   string   `json:"note,omitempty"`
	Listed bool     `json:"listed,omitempty"`
	Roads  []string `json:"roads,omitempty"`
	// Exemptions are the law's exemptions, in short (perishable goods,
	// combined transport, ...): the truck may have one.
	Exemptions string `json:"exemptions,omitempty"`
	// Law is the law that sets the ban; sources links it.
	Law string `json:"law"`
}

// segment is a stretch of the route in one country, km along it.
type segment struct {
	country  string
	from, to float64
	ordered  bool
	// region is its first-level region (ISO 3166-2) where Sootcase gives
	// it; then a regional holiday's ban holds there or not at all.
	region string
	// roads are its leg's main roads (Sootcase's summary), where given.
	roads []string
	// prev and next are the countries the trip is in before and after it
	// ("" at the trip's ends), known (around) where all the segments are
	// in order.
	prev, next string
	around     bool
}

// roadRef is a road ref to compare: upper case, no spaces or hyphens.
func roadRef(s string) string {
	return strings.NewReplacer(" ", "", "-", "").Replace(strings.ToUpper(s))
}

// onRoads says a listed ban's roads are among the leg's main roads.
func onRoads(ban, leg []string) bool {
	for _, l := range leg {
		for _, r := range strings.Split(l, ";") {
			for _, b := range ban {
				if roadRef(r) == roadRef(b) {
					return true
				}
			}
		}
	}
	return false
}

// maxBanDays is the longest trip whose driving bans are checked.
const maxBanDays = 31

// segments are the route's stretches by country: a leg in one country is
// one; a leg across several is split only where Sootcase gives its
// country_sections, else its countries are kept unordered over the leg.
func segments(res sootcase.Result) []segment {
	var out []segment
	pos := 0.0
	for _, l := range res.Legs {
		end := pos + l.DistanceKm
		n := len(out)
		switch {
		case len(l.CountrySections) > 0:
			for _, s := range l.CountrySections {
				switch {
				case s.Ferry || s.Country == "":
				case len(s.Regions) > 0:
					for _, r := range s.Regions {
						out = append(out, segment{country: s.Country, from: pos + r.FromKm, to: pos + r.ToKm, ordered: true, region: r.Region})
					}
				default:
					out = append(out, segment{country: s.Country, from: pos + s.FromKm, to: pos + s.ToKm, ordered: true})
				}
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
				out = append(out, segment{country: cc, from: pos, to: end, ordered: len(ccs) == 1})
			}
		}
		if l.Summary != nil {
			for i := n; i < len(out); i++ {
				out[i].roads = l.Summary.Roads
			}
		}
		pos = end
	}
	// The countries before and after each stretch, for transit bans.
	// By runs of one country (its regions' stretches are one run), so a
	// path of many stretches takes linear time.
	if slices.ContainsFunc(out, func(s segment) bool { return !s.ordered }) {
		return out
	}
	for i := 0; i < len(out); {
		j := i
		for j < len(out) && out[j].country == out[i].country {
			j++
		}
		prev, next := "", ""
		if i > 0 {
			prev = out[i-1].country
		}
		if j < len(out) {
			next = out[j].country
		}
		for k := i; k < j; k++ {
			out[k].around, out[k].prev, out[k].next = true, prev, next
		}
		i = j
	}
	return out
}

// banStop is where along the route (km) the truck waits for a ban to
// end, and how long (hours).
type banStop struct{ pos, waitH float64 }

// checkBans finds the driving bans the trip runs into, by its passage
// times where a departure time is given, else by its days. It returns the
// stops the truck makes for them, which the times of what follows go by.
func checkBans(out *Response, res sootcase.Result, req Request, date time.Time) []banStop {
	req.banStops = nil // its own times are those without waits
	segs := segments(res)
	// A trip of more than a month (a month's km by country, or a very low
	// average speed) is a total, not a drive to plan: no bans checked.
	end := 0.0
	for _, s := range segs {
		end = max(end, s.to)
	}
	hours := tripHoursFor(out, req)
	if t0, ok := passage(req, date, 0, ""); ok {
		t1, _ := passage(req, date, end, "")
		hours = max(hours, t1.Sub(t0).Hours())
	}
	if hours > maxBanDays*24 {
		out.Notes = append(out.Notes, fmt.Sprintf("Driving ban: the trip takes more than %d days, so bans aren't checked.", maxBanDays))
		return nil
	}
	var stops []banStop
	// Towing a trailer (more axles than the motor vehicle's own, or a
	// trailer's mass given): the heavier of the truck's and the trailer's
	// own masses, or the least it can be where one or both aren't given (the
	// two together are at least the combination's: with one given, the
	// other is at least the rest; with neither, half); bans for trucks with
	// trailers go by it.
	towKg := 0
	if t := req.Truck; t.MotorAxles > 0 && t.MotorAxles < t.Axles || t.TrailerMassKg > 0 {
		switch m, tr := t.MotorMassKg, t.TrailerMassKg; {
		case m > 0 && tr > 0:
			towKg = max(m, tr)
		case m > 0 || tr > 0:
			towKg = max(m+tr, t.MaxMassKg-m-tr)
		default:
			towKg = (t.MaxMassKg + 1) / 2
		}
	}
	var hits []BanHit
	var wait float64
	// there are when the trip is in each country with bans.
	type banSpan struct {
		cc       string
		from, to time.Time
	}
	var there []banSpan
	seen := map[string]bool{}
	countries := 0
	for _, km := range out.CountryKm {
		if km >= 0.5 {
			countries++
		}
	}
	exempted := false
	offRoad := map[string]map[string]bool{} // country: listed restrictions not on the route's main roads
	// windows are the bans in force, less those the truck is exempt from
	// and those on listed roads that aren't among the leg's main roads;
	// in a known region, a regional holiday's ban holds or doesn't.
	windows := func(s segment, from, to time.Time, loc *time.Location) []bans.Window {
		ws := bans.Windows(s.country, req.Truck.MaxMassKg, towKg, from, to, loc)
		ws = slices.DeleteFunc(ws, func(w bans.Window) bool {
			if w.Exempt(req.Truck.Euro, countries > 1) {
				exempted = true
				return true
			}
			if w.Rule.TransitTo != "" && s.around && (!slices.Contains(w.Rule.TransitFrom, s.prev) || s.next != w.Rule.TransitTo) {
				return true // not in that transit
			}
			if len(w.Rule.Roads) > 0 && len(s.roads) > 0 && !onRoads(w.Rule.Roads, s.roads) {
				if offRoad[s.country] == nil {
					offRoad[s.country] = map[string]bool{}
				}
				offRoad[s.country][w.Rule.Note] = true
				return true
			}
			return false
		})
		for i := range ws {
			if ws[i].Rule.TransitTo != "" && !s.around {
				ws[i].Rule.Listed = true // the trip's way through isn't known
			}
		}
		if s.region == "" {
			return ws
		}
		out := ws[:0]
		for _, w := range ws {
			if len(w.Regions) > 0 {
				if !slices.Contains(w.Regions, s.region) {
					continue
				}
				w.Regions, w.Holiday = nil, w.Holiday+" ("+s.region+")"
			}
			out = append(out, w)
		}
		return out
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
		w0 := wait
		add := func(w bans.Window, certain bool, waitH float64) {
			key := s.country + w.From.String() + w.Rule.Note
			if seen[key] {
				return
			}
			seen[key] = true
			hits = append(hits, BanHit{Country: s.country, Ban: w.Rule.Name, From: w.From.Format(time.RFC3339), To: w.To.Format(time.RFC3339),
				Holiday: w.Holiday, Regions: w.Regions, Note: w.Rule.Note, Listed: w.Rule.Listed, Roads: w.Rule.Roads,
				Exemptions: w.Rule.Exemptions, Law: w.Rule.Law, Certain: certain, WaitH: waitH})
			addSource(out, rates.Source{Title: w.Rule.Title, URL: w.Rule.URL})
			if src, ok := bans.HolidaySources[s.country]; ok && w.Holiday != "" {
				addSource(out, rates.Source{Title: src[0], URL: src[1]})
			}
		}
		if !timed || !s.ordered {
			for _, w := range windows(s, t0, t1, loc) {
				add(w, false, 0)
			}
			there = append(there, banSpan{s.country, t0, t1})
			continue
		}
		// Drive the segment, stopping for each ban in force until it ends;
		// a regional holiday's ban is reported, not waited for.
		// A week ahead at a time, so a long trip's bans are found in time
		// linear in its length.
		const ahead = 7 * 24 * time.Hour
		cursor, left := t0, t1.Sub(t0)
		for left > 0 {
			span := min(left, ahead)
			var next *bans.Window
			for _, w := range windows(s, cursor, cursor.Add(span), loc) {
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
				cursor, left = cursor.Add(span), left-span
				continue
			}
			stop := cursor
			if next.From.After(stop) {
				stop = next.From
			}
			left -= stop.Sub(cursor)
			waitH := math.Round(next.To.Sub(stop).Hours()*100) / 100
			add(*next, true, waitH)
			// Where it stops: the first km reached then, at the waits so far.
			shiftNow := time.Duration(wait * float64(time.Hour))
			lo, hi := s.from, s.to
			for i := 0; i < 40; i++ {
				mid := (lo + hi) / 2
				if t, _ := passage(req, date, mid, s.country); t.Add(shiftNow).Before(stop) {
					lo = mid
				} else {
					hi = mid
				}
			}
			stops = append(stops, banStop{hi, waitH})
			wait += waitH
			cursor = next.To
		}
		there = append(there, banSpan{s.country, t0, t1.Add(time.Duration((wait - w0) * float64(time.Hour)))})
	}
	out.Bans = hits
	// A decree of bans not in for a day the trip is in its country.
	noted := map[string]bool{}
	for _, sp := range there {
		if len(bans.CalendarYears(sp.cc)) == 0 {
			continue
		}
		last := sp.to.Add(-time.Nanosecond).Format(time.DateOnly)
		if sp.to.Equal(sp.from) {
			last = sp.from.Format(time.DateOnly)
		}
		for d := sp.from; d.Format(time.DateOnly) <= last; d = d.AddDate(0, 0, 1) {
			if k := fmt.Sprint(sp.cc, d.Year()); !noted[k] && !bans.CalendarCovers(sp.cc, d) {
				noted[k] = true
				out.Notes = append(out.Notes, fmt.Sprintf("Driving ban: %s's decree of bans for %d isn't in, so those bans aren't checked.", sp.cc, d.Year()))
			}
		}
	}
	if exempted {
		out.Notes = append(out.Notes, "Driving ban: Hungary's weekend and holiday ban doesn't bind a truck of Euro 3 and up in international traffic from 4 November to 1 March (190/2008. (VII. 29.) Korm. rendelet, § 2 (3)).")
	}
	if out.Trip != nil && wait > 0 {
		out.Trip.BanWaitH = math.Round(wait*100) / 100
	}
	// A country's many restrictions on listed roads (Spain's) in one note.
	listed := map[string][]BanHit{}
	for _, h := range hits {
		if h.Listed && len(h.Roads) > 0 && !h.Certain {
			listed[h.Country] = append(listed[h.Country], h)
		}
	}
	for _, cc := range slices.Sorted(maps.Keys(listed)) {
		hs := listed[cc]
		if len(hs) <= 3 {
			delete(listed, cc)
			continue
		}
		var each []string
		for i, h := range hs {
			if i == 8 {
				each = append(each, fmt.Sprintf("and %d more", len(hs)-8))
				break
			}
			from, _ := time.Parse(time.RFC3339, h.From)
			to, _ := time.Parse(time.RFC3339, h.To)
			each = append(each, fmt.Sprintf("%s %s to %s", strings.Join(h.Roads, "/"), from.Format("Mon 2 Jan 15:04"), to.Format("15:04")))
		}
		out.Notes = append(out.Notes, fmt.Sprintf("Driving ban: the trip may run into %d of %s's %ss on listed roads (%s): %s; bans gives each road section and direction.",
			len(hs), cc, hs[0].Ban, hs[0].Law, strings.Join(each, ", ")))
	}
	for _, cc := range slices.Sorted(maps.Keys(offRoad)) {
		var main []string
		for _, s := range segs {
			if s.country == cc {
				for _, r := range s.roads {
					if !slices.Contains(main, r) {
						main = append(main, r)
					}
				}
			}
		}
		out.Notes = append(out.Notes, fmt.Sprintf("Driving ban: %d of %s's restrictions on listed roads in force then are on roads that aren't among the route's main roads (%s), so they aren't counted; check the sections near the stops.",
			len(offRoad[cc]), cc, strings.Join(main, ", ")))
	}
	for _, h := range hits {
		if listed[h.Country] != nil && h.Listed && len(h.Roads) > 0 && !h.Certain {
			continue
		}
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
	return stops
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

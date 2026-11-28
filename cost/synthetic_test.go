// Tests on synthetic datasets: testdata/synthetic/tables holds them in the
// builders' table form, testdata/synthetic/orct as tools/orct/convert.py
// writes them (convert.py tables/<name> orct/<name>).

package cost

import (
	"os"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/rates"

	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// synthetic loads the datasets of one testdata/synthetic/orct folder.
func synthetic(t *testing.T, name string) *tariffs.Set {
	t.Helper()
	set, err := tariffs.LoadFS(os.DirFS("testdata/synthetic/orct"), name)
	if err != nil || len(set.All) == 0 {
		t.Fatalf("%s: %v", name, err)
	}
	return set
}

// Regional tolls are priced on Sootcase's region_km; country_km keeps the
// whole country.
func TestPrice_Regions(t *testing.T) {
	// BE-VLG 0.20 + 0.05 CO2 per km, BE-WAL 0.17 per km.
	tbs := synthetic(t, "regions")
	trip := sootcase.Result{TTWKg: 100, Legs: []sootcase.LegResult{{DistanceKm: 150,
		CountryKm: map[string]float64{"BE": 100, "FR": 50},
		RegionKm:  map[string]float64{"BE-VLG": 60, "BE-WAL": 38, "BE-BRU": 2}}}}
	nov26 := time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC)

	r, err := Price(trip, tbs, Request{CargoKg: 1, Truck: truck40, TolledShare: map[string]float64{"BE-WAL": 0.5}}, nov26)
	if err != nil {
		t.Fatal(err)
	}
	// VLG 60 km x (0.20 + 0.05) = 12 + 3; WAL 19 km x 0.17 = 3.23.
	for _, tc := range []struct {
		region, comp string
		km, amount   float64
	}{
		{"BE-VLG", "toll", 60, 12}, {"BE-VLG", rates.CO2, 60, 3}, {"BE-WAL", "toll", 19, 3.23},
	} {
		var found bool
		for _, l := range r.Lines {
			if l.Region == tc.region && l.Component == tc.comp {
				found = true
				if l.Country != "BE" || l.Km != tc.km || l.Amount != tc.amount {
					t.Errorf("%s %s: %+v, want %v km, %v EUR", tc.region, tc.comp, l, tc.km, tc.amount)
				}
			}
		}
		if !found {
			t.Errorf("no %s %s line", tc.region, tc.comp)
		}
	}
	if r.CountryKm["BE"] != 100 || r.RegionKm["BE-VLG"] != 60 || r.CarbonEUR != 3 {
		t.Errorf("country_km %v, region_km %v, carbon %v", r.CountryKm, r.RegionKm, r.CarbonEUR)
	}
	// Brussels has no table here, France none at all.
	if strings.Join(r.NoRates, ",") != "BE-BRU,FR" {
		t.Errorf("no_rates %v, want BE-BRU,FR", r.NoRates)
	}

	// A country-wide tolled_share applies to all its regions.
	r, _ = Price(trip, tbs, Request{CargoKg: 1, Truck: truck40, TolledShare: map[string]float64{"BE": 0.5}}, nov26)
	for _, l := range r.Lines {
		if l.Region == "BE-VLG" && l.Km != 30 {
			t.Errorf("BE share 0.5: VLG km %v, want 30", l.Km)
		}
	}

	// An older Sootcase without region_km: Belgium can't be split.
	old := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{"BE": 100}}}}
	r, err = Price(old, tbs, Request{CargoKg: 1, Truck: truck40}, nov26)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Lines) != 0 || strings.Join(r.NoRates, ",") != "BE" || !hasNote(r, "region_km") {
		t.Errorf("no region_km: lines %v, no_rates %v, notes %v", r.Lines, r.NoRates, r.Notes)
	}
}

// A toll booth on an exit the route only drives past (R, 0.1 km off the
// road) has a short priced pair to the barrier B; taking it would leave
// B's long ticket to N unused.
func TestChainBoothBeside(t *testing.T) {
	route := [][2]float64{{-0.1, 45}, {2.1, 45}}
	uses := func(name string) string {
		t.Helper()
		ds := synthetic(t, name).All[0]
		p := newPricer(Request{CargoKg: 1000, Truck: truck40}, time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC), &Response{}, nil)
		var out []string
		for _, s := range systemsOf(ds) {
			for _, u := range s.uses(ds, newTrack(route), p) {
				out = append(out, u.entry.Name+"-"+u.exit.Name)
			}
		}
		return strings.Join(out, ",")
	}
	// R|B 2.25, P|N 39.25, B|N 52.17.
	if got := uses("chain-beside"); got != "B-N" {
		t.Errorf("got %s, want one ticket B-N", got)
	}
	// Where two networks meet, the next ticket starts at the other
	// network's station at the same place (P2 beside P): B|P, P2|N.
	if got := uses("chain-meet"); got != "B-P,P2-N" {
		t.Errorf("got %s, want B-P, P2-N", got)
	}
	// A barrier across the road (X) and an exit's booth beside it (Y) at
	// the same place: a trip driving through takes its ticket at X.
	if got := uses("chain-barrier"); got != "X-N" {
		t.Errorf("got %s, want X-N", got)
	}
	// A barrier priced on its own (Z|Z) pays when passed outside a
	// ticket, not inside one (W|W, past N).
	if got := uses("chain-own"); got != "X-N,W-W" {
		t.Errorf("got %s, want X-N and W-W", got)
	}
}

// The departure time and the km along the route tell when each station
// is reached.
func TestPassageTimes(t *testing.T) {
	sum := func(r Response, src string) float64 {
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Source, src) {
				got += l.AmountEUR
			}
		}
		return got
	}
	run := func(tbs *tariffs.Set, cc string, path [][2]float64, req Request) Response {
		t.Helper()
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{cc: 1}, Path: path}}}
		req.CargoKg, req.Truck = 1000, truck40
		r, err := Price(trip, tbs, req, time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		return r
	}
	fx := map[string]float64{"SEK": 11}
	// Danvikstull ~35 km after the start: leaving 06:35 it is reached about
	// 07:05 at 70 km/h, 45 SEK in high season (30 at 06:35).
	sto := [][2]float64{{18.1034, 59.0}, {18.1034, 59.3130}, {18.1034, 59.3150}}
	if got := sum(run(all(t), "SE", sto, Request{Time: "06:35", FX: fx}), "trängselskatt"); got != 4.09 {
		t.Errorf("Stockholm reached at 07:05: %.2f, want 4.09", got)
	}
	// Göteborg: Marieholmsleden about 06:58 (16 SEK), Ringömotet about
	// 07:01 at 20 km/h (22 SEK): within 60 minutes, the highest once.
	gbg := [][2]float64{{11.9941, 57.7190}, {11.99404, 57.7199}, {11.9839, 57.7238}, {11.98, 57.725}}
	if got := sum(run(all(t), "SE", gbg, Request{Time: "06:58", AvgSpeedKmh: 20, FX: fx}), "trängselskatt"); got != 2.0 {
		t.Errorf("Göteborg 16 then 22 within the hour: %.2f, want 2.00", got)
	}
	// A toll station free at night (5 EUR, free 22:00-05:59).
	path := [][2]float64{{10, 49.99}, {10, 50.01}}
	for at, want := range map[string]float64{"12:00": 5, "23:30": 0, "": 5} {
		if got := sum(run(synthetic(t, "night-free"), "DE", path, Request{Time: at}), "test law"); got != want {
			t.Errorf("free hours at %q: %.2f, want %.2f", at, got, want)
		}
	}
	// Two versions of one station, each in force for part of the table's
	// time: 4 EUR until 2026-11-04, 6 from 2026-11-05.
	if got := sum(run(synthetic(t, "versioned"), "DE", path, Request{}), "test law"); got != 6 {
		t.Errorf("versioned station on 2026-11-05: %.2f, want 6", got)
	}
}

// Days of a time-based charge by passage times: Sweden counts calendar
// days, Estonia 24-hour periods.
func TestTripDays(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	set := all(t)
	ds := func(cc string) *tariffs.Dataset {
		x, ok := set.Find(cc, date)
		if !ok {
			t.Fatal(cc)
		}
		return x
	}
	se, ee, lv := ds("SE"), ds("EE"), ds("LV")
	for _, tc := range []struct {
		name  string
		ds    *tariffs.Dataset
		req   Request
		spans [][2]float64
		want  int
	}{
		{"no time", se, Request{}, [][2]float64{{0, 700}}, 1},
		{"SE same day", se, Request{Time: "08:00"}, [][2]float64{{0, 700}}, 1},
		{"SE past midnight", se, Request{Time: "20:00"}, [][2]float64{{0, 700}}, 2},
		{"SE with rests", se, Request{Time: "08:00", DriverRest: true}, [][2]float64{{0, 700}}, 2},
		{"SE out and back in", se, Request{Time: "08:00"}, [][2]float64{{0, 100}, {1200, 1300}}, 2},
		{"EE within 24 h", ee, Request{Time: "20:00"}, [][2]float64{{0, 700}}, 1},
		{"EE over 24 h", ee, Request{Time: "20:00"}, [][2]float64{{0, 1800}}, 2},
		// LV's table doesn't say whether its day is a calendar day or 24
		// hours: the fewest, by 24 hours (and days_unknown).
		{"LV: day not known", lv, Request{Time: "20:00"}, [][2]float64{{0, 1800}}, 2},
	} {
		req := tc.req
		req.spans = map[string][][2]float64{tc.ds.Country: tc.spans}
		if got, note := tripDaysOf(t, tc.ds, req, date); got != tc.want {
			t.Errorf("%s: %d days, want %d (%s)", tc.name, got, tc.want, note)
		}
	}
	// LV's day not known: unknown where calendar days are more than 24-hour
	// periods (20:00 to 04:00 the next day: one period, two days), not where
	// they are the same.
	for _, c := range []struct {
		at      string
		unknown bool
	}{{"20:00", true}, {"08:00", false}, {"", true}} { // no time: other departures make more calendar days
		sp := [][2]float64{{0, 600}}
		if c.at == "" {
			sp = [][2]float64{{200, 800}}
		}
		p := newPricer(Request{Time: c.at, spans: map[string][][2]float64{"LV": sp}}, date, &Response{}, nil)
		if _, note, unknown := p.tripDaysORCT(lv, networkOf(lv).perDay, "LV"); unknown != c.unknown {
			t.Errorf("LV at %s: unknown %v, want %v (%s)", c.at, unknown, c.unknown, note)
		}
	}
}

// tripDaysOf counts the days of a dataset's time-based charge.
func tripDaysOf(t *testing.T, ds *tariffs.Dataset, req Request, date time.Time) (int, string) {
	t.Helper()
	nw := networkOf(ds)
	if nw.perDay == nil {
		t.Fatalf("%s: no time-based charge", ds.File)
	}
	p := newPricer(req, date, &Response{}, nil)
	days, note, _ := p.tripDaysORCT(ds, nw.perDay, ds.Country)
	return len(days), note
}

// Passage times are local where the station is: 23:30 leaving Portugal
// is 00:30 in Spain, and the day counts by the local date.
func TestPassageZones(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	req := Request{Time: "23:30", origin: "PT"}
	if at, _ := passage(req, date, 0, "ES"); at.Format("2006-01-02 15:04") != "2026-11-05 00:30" {
		t.Errorf("ES: %v", at)
	}
	if at, _ := passage(req, date, 0, "PT"); at.Format("2006-01-02 15:04") != "2026-11-04 23:30" {
		t.Errorf("PT: %v", at)
	}
	// From Denmark at 23:00, an hour on is midnight in Sweden but 23:00 in
	// Britain: one calendar day there, two in Sweden.
	dk := Request{Time: "23:00", origin: "DK", spans: map[string][][2]float64{"SE": {{0, 70}}, "GB": {{0, 70}}}}
	set := all(t)
	se, _ := set.Find("SE", date)
	gb, _ := set.Find("GB", date)
	if n, _ := tripDaysOf(t, se, dk, date); n != 2 {
		t.Errorf("SE: %d days", n)
	}
	if n, _ := tripDaysOf(t, gb, dk, date); n != 1 {
		t.Errorf("GB: %d days", n)
	}
}

// Norway's rush hours: the rush-hour price within the hours on weekdays
// other than public holidays (and July where the project says so); the hour rule charges the first passage, or the hour's highest
// price where the group pays the highest.
func TestNorwayRush(t *testing.T) {
	// Toll points A and B, 100 NOK or 150 in rush hours (06:30-08:59 and
	// 15:00-16:59 but on Norwegian holidays, and in July where the
	// project says so), in one hour group (60 minutes).
	// A about 06:24 and B about 06:34 when leaving 06:15 at 70 km/h.
	path := [][2]float64{{10, 59.9}, {10, 60.2}}
	run := func(day, at, pays string, july bool) (float64, []string) {
		t.Helper()
		name := "rush-first"
		if pays == "highest" {
			name = "rush-highest"
			if july {
				name += "-july"
			}
		}
		tb := synthetic(t, name)
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 33, CountryKm: map[string]float64{"NO": 33}, Path: path}}}
		d, _ := time.Parse(time.DateOnly, day)
		r, err := Price(trip, tb, Request{CargoKg: 1000, Truck: truck40, Time: at, FX: map[string]float64{"NOK": 11.7}}, d)
		if err != nil {
			t.Fatal(err)
		}
		sum := 0.0
		for _, l := range r.Lines {
			if l.Country == "NO" {
				sum += l.Amount
			}
		}
		return sum, r.Notes
	}
	for _, tc := range []struct {
		day, at, pays string
		july          bool
		want          float64
	}{
		{"2026-11-05", "06:15", "highest", false, 150}, // 100 at A, then 50 more at B in rush
		{"2026-11-05", "06:15", "", false, 100},        // the first passage pays
		{"2026-11-05", "07:00", "", false, 150},        // both in rush: A pays
		{"2026-11-05", "12:00", "highest", false, 100}, // off-peak
		{"2026-11-07", "07:00", "highest", false, 100}, // Saturday
		{"2026-12-24", "07:00", "highest", false, 150}, // Christmas Eve: only norwegian_eves frees it
		{"2026-12-25", "07:00", "highest", false, 100}, // Christmas Day
		{"2026-05-01", "07:00", "highest", false, 100}, // 1 May
		{"2026-05-14", "07:00", "highest", false, 100}, // Ascension Day
		{"2026-07-01", "07:00", "highest", false, 150},
		{"2026-07-01", "07:00", "highest", true, 100}, // no rush-hour price in July (Fjellinjen)
	} {
		if got, notes := run(tc.day, tc.at, tc.pays, tc.july); got != tc.want {
			t.Errorf("%s %s pays %q july %v: %.0f NOK, want %.0f: %v", tc.day, tc.at, tc.pays, tc.july, got, tc.want, notes)
		}
	}
	got, notes := run("2026-11-05", "", "highest", false)
	if got != 100 || !slices.ContainsFunc(notes, func(n string) bool { return strings.Contains(n, "Give a departure time") }) {
		t.Errorf("without a time: %.0f NOK, want 100 and a note: %v", got, notes)
	}
}

// A country entered later in the trip: with no time, the days leaving at
// 00:00, and days_unknown when another departure makes another count (each
// minute's, so a day of 25 hours too); bans in the country make it unknown,
// bans elsewhere don't; with no route positions, days_unknown even with
// time.
func TestDaysEnteredLater(t *testing.T) {
	date := time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC)
	se, ok := all(t).Find("SE", date)
	if !ok {
		t.Fatal("SE")
	}
	nw := networkOf(se)
	for _, c := range []struct {
		name    string
		req     Request
		spans   [][2]float64
		days    int
		unknown bool
	}{
		{"no time, entered at 300 km", Request{}, [][2]float64{{300, 940}}, 1, true},
		{"no time, with rests", Request{DriverRest: true}, [][2]float64{{300, 940}}, 2, true},
		{"no time, 30 km on the day of 25 hours", Request{Date: "2026-10-25"}, [][2]float64{{300, 330}}, 1, true},
		{"at 15:00", Request{Time: "15:00"}, [][2]float64{{300, 940}}, 2, false},
		{"no positions, with time", Request{Time: "08:00"}, nil, 1, true},
	} {
		req := c.req
		req.spans = map[string][][2]float64{"SE": c.spans}
		day := date
		if req.Date != "" {
			day, _ = time.Parse(time.DateOnly, req.Date)
		}
		p := newPricer(req, day, &Response{}, nil)
		days, note, unknown := p.tripDaysORCT(se, nw.perDay, "SE")
		if len(days) != c.days || unknown != c.unknown {
			t.Errorf("%s: %d days, unknown %v; want %d, %v (%s)", c.name, len(days), unknown, c.days, c.unknown, note)
		}
		if c.req.Time != "" && strings.Contains(note, "give time") {
			t.Errorf("%s: the note asks for time, which is given: %s", c.name, note)
		}
	}
}

// Bans and days: a ban in the country may lengthen its stretch (unknown);
// one elsewhere moves its passages alike, which a 24-hour count doesn't
// feel, unless it lies between two of its stretches.
func TestDaysAndBans(t *testing.T) {
	date := time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC)
	lt, ok := all(t).Find("LT", date)
	if !ok {
		t.Fatal("LT")
	}
	nw := networkOf(lt)
	for _, c := range []struct {
		ban     string
		unknown bool
		spans   map[string][][2]float64
	}{{"", false, nil}, {"PL", false, nil}, {"LT", true, nil},
		// Vilnius - Warsaw - Vilnius: a wait in Poland lies between LT's stretches.
		{"PL", true, map[string][][2]float64{"LT": {{0, 170}, {1070, 1240}}, "PL": {{170, 1070}}}}} {
		out := &Response{}
		if c.ban != "" {
			out.Bans = []BanHit{{Country: c.ban}}
		}
		sp := c.spans
		if sp == nil {
			sp = map[string][][2]float64{"LT": {{300, 500}}}
		}
		p := newPricer(Request{spans: sp}, date, out, nil)
		if _, note, unknown := p.tripDaysORCT(lt, nw.perDay, "LT"); unknown != c.unknown {
			t.Errorf("ban in %q: unknown %v, want %v (%s)", c.ban, unknown, c.unknown, note)
		}
	}
}

// A trip with no time: its km by day as a 00:00 departure has them (as the
// charges by the day count it), each at noon: a table starting the next
// day prices that day's km (the Dutch HGV charge from 1 July 2026).
func TestKmDaysWithoutTime(t *testing.T) {
	date := time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC)
	nl, ok := all(t).Find("NL", date)
	if !ok {
		t.Fatal("NL")
	}
	p := newPricer(Request{spans: map[string][][2]float64{"NL": {{0, 1700}}}}, date, &Response{}, nil)
	var days []string
	for _, d := range p.kmDays(nl, "NL", "") {
		days = append(days, d.at.Format("2006-01-02 15:04"))
	}
	if len(days) != 2 || days[0] != "2026-06-30 12:00" || days[1] != "2026-07-01 12:00" {
		t.Errorf("km days %v; want 30 June and 1 July, at noon", days)
	}
}

package tariffs

import (
	"sort"
	"strings"
	"testing"
	"time"
)

// HistoryFrom is the first day trips are priced for.
var HistoryFrom = time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

// historyGaps lists the areas whose datasets don't yet cover every day
// from HistoryFrom to the end of 2026, with why. TestHistoryCoverage
// fails on a gap not listed here, and on a listed area that has none.
var historyGaps = map[string]string{
	"ES": "SEITT's 2024 tariffs (and the AP-41's of 2025) are neither served nor archived any more",
	"MD": "e-Vinieta publishes the current vignette amounts without a date; earlier ones aren't archived",
	"IT": "the Ministry's sheets of each concession's unit rates (directive 2022/362 art. 11) start with 2025; 2024's rates aren't published with them",
}

// gaps are an area's uncovered days from HistoryFrom to the end of 2026,
// as [first, last] ranges.
func gaps(s *Set, area string) [][2]string {
	end := time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC)
	var out [][2]string
	var open time.Time
	for d := HistoryFrom; !d.After(end); d = d.AddDate(0, 0, 1) {
		_, ok := s.Find(area, d)
		switch {
		case !ok && open.IsZero():
			open = d
		case ok && !open.IsZero():
			out = append(out, [2]string{open.Format(time.DateOnly), d.AddDate(0, 0, -1).Format(time.DateOnly)})
			open = time.Time{}
		}
	}
	if !open.IsZero() {
		out = append(out, [2]string{open.Format(time.DateOnly), end.Format(time.DateOnly)})
	}
	return out
}

func TestHistoryCoverage(t *testing.T) {
	s, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	areas := map[string]bool{}
	for _, d := range s.All {
		if d.Kind == Toll {
			areas[d.Area()] = true
		}
	}
	var names []string
	for a := range areas {
		names = append(names, a)
	}
	sort.Strings(names)
	for _, a := range names {
		g := gaps(s, a)
		why, listed := historyGaps[a]
		switch {
		case len(g) > 0 && !listed:
			t.Errorf("%s: no dataset for %v", a, g)
		case len(g) == 0 && listed:
			t.Errorf("%s: covered now; remove it from historyGaps (%s)", a, why)
		case len(g) > 0:
			t.Logf("%s: no dataset for %v (%s)", a, g, why)
		}
	}
}

// Find takes the first toll dataset in force, so an area's toll datasets
// must not overlap in time; nor may two versions of any one scheme.
func TestNoOverlaps(t *testing.T) {
	s, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	end := func(d *Dataset) string {
		if d.ValidTo == "" {
			return "9999-12-31"
		}
		return d.ValidTo
	}
	for i, a := range s.All {
		for _, b := range s.All[i+1:] {
			same := a.Scheme == b.Scheme || (a.Kind == Toll && b.Kind == Toll && a.Area() == b.Area())
			if same && a.ValidFrom <= end(b) && b.ValidFrom <= end(a) {
				t.Errorf("%s and %s overlap", a.File, b.File)
			}
		}
	}
}

// Every dataset's dates are days, the first not after the last.
func TestDates(t *testing.T) {
	s, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	for _, d := range s.All {
		from, err := time.Parse(time.DateOnly, d.ValidFrom)
		if err != nil {
			t.Errorf("%s: valid_from %q", d.File, d.ValidFrom)
			continue
		}
		if d.ValidTo == "" {
			continue
		}
		if to, err := time.Parse(time.DateOnly, d.ValidTo); err != nil || to.Before(from) {
			t.Errorf("%s: valid_to %q", d.File, d.ValidTo)
		}
	}
}

func dataset(t *testing.T, s *Set, file string) *Dataset {
	t.Helper()
	for _, d := range s.All {
		if d.File == file {
			return d
		}
	}
	t.Fatalf("no %s", file)
	return nil
}

// AP-46's high season: May to October, weekends, and Viernes de Dolores
// (Easter - 9) to the Sunday after Easter (+7).
func TestEasterSeason(t *testing.T) {
	s, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	ds := dataset(t, s, "es/es-ap46-2026-01-01.orct.json")
	for d, want := range map[string]bool{"2026-03-27": true, "2026-03-26": false, "2026-04-12": true, "2026-04-13": false, "2026-11-14": true, "2026-11-13": false, "2026-07-01": true} {
		day, _ := time.Parse(time.DateOnly, d)
		if in, err := ds.InTimeClass("high-season", day.Add(12*time.Hour)); err != nil || in != want {
			t.Errorf("%s: %v (%v), want %v", d, in, err, want)
		}
	}
}

// Norway's public holidays and the eves some projects free from rush-hour
// prices, in 2026 (Easter 5 April): a holiday is in neither rush class, an
// eve only in the one that keeps eves.
func TestNorwegianHolidays(t *testing.T) {
	s, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	ds := dataset(t, s, "no/no-2026-11-12.orct.json")
	oslo, err := time.LoadLocation("Europe/Oslo")
	if err != nil {
		t.Fatal(err)
	}
	var plain, eves string
	for _, tc := range ds.Doc.Times {
		switch {
		case strings.Contains(tc.Label, "Christmas Eve") && eves == "":
			eves = tc.ID
		case strings.HasSuffix(tc.Label, "except public holidays") && plain == "":
			plain = tc.ID
		}
	}
	if plain == "" || eves == "" {
		t.Fatalf("rush classes: %q %q", plain, eves)
	}
	for day, want := range map[string]string{
		"2026-01-01": "h", "2026-04-01": "e", "2026-04-02": "h", "2026-04-03": "h", "2026-04-06": "h",
		"2026-05-01": "h", "2026-05-14": "h", "2026-05-17": "h", "2026-05-25": "h", "2026-12-24": "e", "2026-12-25": "h",
		"2026-12-31": "e", "2026-03-31": "", "2026-05-13": "", "2026-11-05": "", "2026-12-23": "",
	} {
		d, _ := time.ParseInLocation("2006-01-02 15:04", day+" 07:30", oslo)
		a, err1 := ds.InTimeClass(plain, d)
		b, err2 := ds.InTimeClass(eves, d)
		got := map[[2]bool]string{{false, false}: "h", {true, false}: "e", {true, true}: ""}[[2]bool{a, b}]
		if err1 != nil || err2 != nil || got != want {
			t.Errorf("%s: %v %v (%v %v), want %q", day, a, b, err1, err2, want)
		}
	}
}

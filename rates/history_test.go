package rates

import (
	"math"
	"sort"
	"testing"
	"time"
)

// HistoryFrom is the first day trips are priced for.
var HistoryFrom = time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

// historyGaps lists the areas whose tables don't yet cover every day
// from HistoryFrom to the end of 2026, with why. TestHistoryCoverage
// fails on a gap not listed here, and on a listed area that has none.
var historyGaps = map[string]string{
	"ES": "SEITT's 2024 tariffs (and the AP-41's of 2025) are neither served nor archived any more", "FR": "before February 2026 not yet added",
	"RS": "JP Putevi Srbije's price lists of April 2023 (to 9 July 2024), 10 January 2025 and 4 July 2025 weren't archived",
	"TR": "2024 to 12 January 2025 not yet added (KGM's 2024 bridge tariffs weren't archived)",
}

// gaps are an area's uncovered days from HistoryFrom to the end of 2026,
// as [first, last] ranges.
func gaps(tbs []Table, area string) [][2]string {
	end := time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC)
	var out [][2]string
	var open time.Time
	for d := HistoryFrom; !d.After(end); d = d.AddDate(0, 0, 1) {
		_, ok := Find(tbs, area, d)
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
	tbs, err := All()
	if err != nil {
		t.Fatal(err)
	}
	areas := map[string]bool{}
	for _, tb := range tbs {
		if !tb.Crossings {
			areas[tb.Area()] = true
		}
	}
	var names []string
	for a := range areas {
		names = append(names, a)
	}
	sort.Strings(names)
	for _, a := range names {
		g := gaps(tbs, a)
		why, listed := historyGaps[a]
		switch {
		case len(g) > 0 && !listed:
			t.Errorf("%s: no table for %v", a, g)
		case len(g) == 0 && listed:
			t.Errorf("%s: covered now; remove it from historyGaps (%s)", a, why)
		case len(g) > 0:
			t.Logf("%s: no table for %v (%s)", a, g, why)
		}
	}
}

// The Eurovignette years: a day's charge for a 40 t, 5-axle Euro VI
// truck in CO2 class 1.
func TestEurovignetteHistory(t *testing.T) {
	tbs, err := All()
	if err != nil {
		t.Fatal(err)
	}
	truck := Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	for _, tc := range []struct {
		area, date string
		want       float64
	}{
		{"SE", "2024-06-01", 138}, // SFS 2023:599
		{"SE", "2025-02-01", 138}, // SFS 2024:953
		{"SE", "2025-04-01", 147}, // SFS 2025:46
		{"LU", "2024-06-01", 12},  // RGD 21 May 2019, art. 1er 4°
		{"NL", "2025-04-01", 13},  // Wet BZM art. 10 (4), Stb. 2025, 445
		{"DK", "2024-06-01", 89},  // LBK 174/2020 § 3 stk. 4 nr. 5
	} {
		d, _ := time.Parse(time.DateOnly, tc.date)
		tb, ok := Find(tbs, tc.area, d)
		if !ok {
			t.Errorf("%s %s: no table", tc.area, tc.date)
			continue
		}
		rs, _, _ := tb.Rates(truck, d)
		if len(rs) != 1 || rs[0].PerKm != tc.want || !tb.PerDay {
			t.Errorf("%s %s: %+v, want %g a day", tc.area, tc.date, rs, tc.want)
		}
	}
	// Denmark's km toll in 2025: 1.10 kroner a km over 32 t, class 1.
	d, _ := time.Parse(time.DateOnly, "2025-06-01")
	tb, _ := Find(tbs, "DK", d)
	rs, _, _ := tb.Rates(truck, d)
	sum := 0.0
	for _, r := range rs {
		sum += r.PerKm
	}
	if math.Abs(sum-1.10) > 1e-9 {
		t.Errorf("DK 2025: %g kr/km, want 1.10", sum)
	}
}

package rates

import (
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
	"AT": "2024-2025 not yet added", "BE-BRU": "before 1 July 2026 not yet added", "BE-VLG": "before 1 July 2026 not yet added",
	"BE-WAL": "before 1 July 2026 not yet added", "BG": "before June 2026 not yet added", "CH": "2024 not yet added",
	"CZ": "2024-2025 not yet added", "DE": "January-June 2024 not yet added", "DK": "2024-2025 not yet added",
	"EE": "2024-2025 not yet added", "ES": "2024-2025 not yet added", "FR": "before February 2026 not yet added",
	"GB": "before April 2026 not yet added", "GR": "2024-2025 not yet added", "HR": "2024-2025 not yet added",
	"HU": "before July 2026 not yet added", "IE": "2024-2025 not yet added", "LI": "2024 not yet added",
	"LT": "before 25 August 2026 not yet added", "LU": "before 25 March 2025 not yet added", "LV": "before March 2026 not yet added",
	"MK": "before May 2025 not yet added", "NL": "before July 2026 not yet added", "NO": "before November 2026 not yet added",
	"PL": "before February 2026 not yet added", "PT": "2024-2025 not yet added", "RO": "before 8 October 2026 not yet added",
	"RS": "before July 2026 not yet added", "SE": "2024-2025 not yet added", "SI": "before April 2026 not yet added",
	"SK": "before July 2025 not yet added", "TR": "before July 2026 not yet added",
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

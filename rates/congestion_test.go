package rates

import (
	"testing"
	"time"
)

func TestCongestionDays(t *testing.T) {
	sto := Congestion{July: "first5", EveTaxed: []string{"good_friday", "ascension", "all_saints", "may_1", "june_6"},
		HighSeason: [][2]string{{"03-01", "midsummer_eve-1"}, {"08-15", "11-30"}}}
	gbg := Congestion{July: "free"}
	d := func(s string) time.Time { t, _ := time.Parse(time.DateOnly, s); return t }
	for _, tc := range []struct {
		day      string
		sto, gbg bool
	}{
		{"2026-11-05", true, true},   // Thursday
		{"2026-11-07", false, false}, // Saturday
		{"2026-04-02", true, false},  // Maundy Thursday: Stockholm taxes the eve of Good Friday
		{"2026-04-03", false, false}, // Good Friday
		{"2026-06-19", false, false}, // Midsummer Eve
		{"2026-12-24", false, false}, // Christmas Eve
		{"2026-12-31", false, false}, // New Year's Eve
		{"2026-01-05", false, false}, // eve of Epiphany
		{"2026-07-07", true, false},  // fifth weekday of July
		{"2026-07-08", false, false}, // sixth
		{"2026-10-30", true, false},  // eve of All Saints (Saturday 31 October)
	} {
		if got, _ := sto.Taxed(d(tc.day)); got != tc.sto {
			t.Errorf("Stockholm %s taxed %v, want %v", tc.day, got, tc.sto)
		}
		if got, _ := gbg.Taxed(d(tc.day)); got != tc.gbg {
			t.Errorf("Göteborg %s taxed %v, want %v", tc.day, got, tc.gbg)
		}
	}
	for day, want := range map[string]bool{"2026-03-01": true, "2026-06-18": true, "2026-06-19": false, "2026-08-14": false, "2026-08-15": true, "2026-11-30": true, "2026-12-01": false} {
		if got := sto.High(d(day)); got != want {
			t.Errorf("high season %s: %v, want %v", day, got, want)
		}
	}
}

func TestCongestionAmount(t *testing.T) {
	c := Congestion{Schedules: map[string][]TimeAmount{"inner": {{"06:00", "06:29", 15, 15}, {"07:00", "08:29", 35, 45}}},
		HighSeason: [][2]string{{"08-15", "11-30"}}}
	day, _ := time.Parse(time.DateOnly, "2026-11-05")
	for at, want := range map[string]float64{"06:29": 15, "06:30": 0, "08:29": 45, "05:59": 0} {
		if got, err := c.Amount("inner", day, at); err != nil || got != want {
			t.Errorf("%s: %v %v, want %v", at, got, err, want)
		}
	}
	if _, err := c.Amount("inner", day, "25:00"); err == nil {
		t.Error("bad time accepted")
	}
}

package rates

import (
	"testing"
	"time"
)

func TestZone(t *testing.T) {
	z := Zone{
		Polygons: [][][2]float64{{{0, 0}, {2, 0}, {2, 2}, {0, 2}}},
		Holes:    [][][2]float64{{{0.5, 0.5}, {1, 0.5}, {1, 1}, {0.5, 1}}},
		Weekdays: []string{"07:00", "18:00"}, Weekends: []string{"12:00", "18:00"},
		NoCharge: []string{"12-25", "01-01"},
	}
	for p, want := range map[[2]float64]bool{{1.5, 1.5}: true, {0.7, 0.7}: false, {3, 1}: false} {
		if z.Contains(p) != want {
			t.Errorf("Contains(%v) = %v", p, !want)
		}
	}
	at := func(s string) time.Time { v, _ := time.Parse("2006-01-02 15:04", s); return v }
	for s, want := range map[string]bool{
		"2026-11-11 08:00": true,  // Wednesday
		"2026-11-11 19:00": false, // after hours
		"2026-11-14 10:00": false, // Saturday morning
		"2026-11-14 13:00": true,  // Saturday afternoon
		"2026-12-28 10:00": false, // Christmas to New Year
		"2027-01-01 13:00": false,
		"2027-01-04 10:00": true,
	} {
		if z.Charging(at(s)) != want {
			t.Errorf("Charging(%s) = %v", s, !want)
		}
	}
	if _, err := ZonesAll(); err != nil {
		t.Fatal(err)
	}
}

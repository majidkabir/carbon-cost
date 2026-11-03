package rates

import (
	"math"
	"testing"
	"time"
)

func tables(t *testing.T) []Table {
	t.Helper()
	tbs, err := All()
	if err != nil {
		t.Fatal(err)
	}
	return tbs
}

func on(s string) time.Time { return day(s) }

func total(t *testing.T, tb Table, tr Truck, date time.Time) float64 {
	t.Helper()
	rs, exempt, ok := tb.Rates(tr, date)
	if !ok || exempt != "" {
		t.Fatalf("%s %+v: ok %v, exempt %q", tb.Country, tr, ok, exempt)
	}
	var s float64
	for _, r := range rs {
		s += r.PerKm
	}
	return math.Round(s*1000) / 1000
}

// The DK components (§ 5 stk. 3) add up to the published rates (§ 5
// stk. 1, Skatteministeriet's Tabel 1 for 2026 and 2027).
func TestDenmarkTotals(t *testing.T) {
	tb, ok := Find(tables(t), "DK", on("2026-11-03"))
	if !ok {
		t.Fatal("no DK table for 2026")
	}
	want := map[int][3]float64{1: {.86, 1.00, 1.10}, 2: {.79, .92, 1.01}, 3: {.69, .82, .91}, 4: {.46, .53, .58}, 5: {.13, .13, .13}}
	for cls, row := range want {
		for i, kg := range []int{15000, 26000, 40000} {
			if got := total(t, tb, Truck{MaxMassKg: kg, Axles: 5, Euro: 6, CO2Class: cls}, on("2026-06-01")); got != row[i] {
				t.Errorf("DK class %d, %d kg: %v DKK/km, want %v", cls, kg, got, row[i])
			}
		}
	}
	if got := tb.EnvZoneRate(Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}); got != .55 {
		t.Errorf("DK zone surcharge, >32 t class 1: %v, want 0.55", got)
	}
	// Boundaries: 18,000 and 32,000 kg are in the 18-32 t band.
	if got := total(t, tb, Truck{MaxMassKg: 32000, Axles: 4, Euro: 6, CO2Class: 1}, on("2026-06-01")); got != 1.00 {
		t.Errorf("DK 32,000 kg: %v, want 1.00", got)
	}
	if _, _, ok := tb.Rates(Truck{MaxMassKg: 11999, Axles: 2, Euro: 6, CO2Class: 1}, on("2026-06-01")); ok {
		t.Error("DK 2026: trucks under 12 t pay no toll")
	}
	if _, ok := Find(tables(t), "DK", on("2028-01-01")); ok {
		t.Error("DK: no table for 2028 yet (rates not published)")
	}
}

// German totals are the sums of the Anlage 1 parts; 34.8 ct/km is the
// widely quoted rate for a 40 t, 5-axle Euro VI truck in CO2 class 1.
func TestGermanyTotals(t *testing.T) {
	tb, ok := Find(tables(t), "DE", on("2026-11-03"))
	if !ok {
		t.Fatal("no DE table")
	}
	for _, tc := range []struct {
		tr   Truck
		want float64
	}{
		{Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, 0.348}, // .155 + .023 + .012 + .158
		{Truck{MaxMassKg: 40000, Axles: 4, Euro: 6, CO2Class: 1}, 0.324}, // .155 + .023 + .012 + .134
		{Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}, 0.303}, // .141 + .022 + .016 + .124
		{Truck{MaxMassKg: 40000, Axles: 5, Euro: 5, CO2Class: 1}, 0.389}, // .155 + .062 + .012 + .160
		{Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 4}, 0.269}, // .155 + .023 + .012 + .079
		{Truck{MaxMassKg: 16000, Axles: 2, Euro: 6, CO2Class: 1}, 0.238}, // .107 + .015 + .016 + .100
		{Truck{MaxMassKg: 7000, Axles: 2, Euro: 6, CO2Class: 1}, 0.151},  // .052 + .011 + .014 + .074
	} {
		if got := total(t, tb, tc.tr, on("2026-11-03")); got != tc.want {
			t.Errorf("DE %+v: %v EUR/km, want %v", tc.tr, got, tc.want)
		}
	}
	// Emission-free trucks are exempt until 30 June 2031, then pay.
	zev := Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}
	if _, note, ok := tb.Rates(zev, on("2031-06-30")); !ok || note == "" {
		t.Errorf("DE zero-emission 2031-06-30: want exempt, got %q", note)
	}
	if got := total(t, tb, zev, on("2031-07-01")); got != 0.168 { // .155 + .001 + .012 + 0
		t.Errorf("DE zero-emission after the exemption: %v, want 0.168", got)
	}
}

func TestTruckValidate(t *testing.T) {
	if err := (Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}).Validate(); err != nil {
		t.Error(err)
	}
	for _, tr := range []Truck{{Axles: 5, Euro: 6, CO2Class: 1}, {MaxMassKg: 1, Axles: 1, CO2Class: 1},
		{MaxMassKg: 1, Axles: 2, Euro: 7, CO2Class: 1}, {MaxMassKg: 1, Axles: 2, CO2Class: 6}} {
		if tr.Validate() == nil {
			t.Errorf("%+v: want an error", tr)
		}
	}
}

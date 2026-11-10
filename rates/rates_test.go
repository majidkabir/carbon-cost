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
	return math.Round(s*1e6) / 1e6
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

// The Austrian parts (BGBl. II Nr. 298/2025 §§ 2, 8, 9) add up to the 2026
// totals the WKO publishes, in cent/km.
func TestAustriaTotals(t *testing.T) {
	tb, ok := Find(tables(t), "AT", on("2026-11-03"))
	if !ok {
		t.Fatal("no AT table for 2026")
	}
	for _, tc := range []struct {
		euro, cls int
		want      [3]float64 // 2, 3, 4+ axles
	}{
		{6, 5, [3]float64{5.87, 8.06, 11.89}},   // E
		{6, 1, [3]float64{27.74, 38.56, 57.24}}, // A, CO2 class 1
		{5, 1, [3]float64{29.24, 40.86, 60.24}}, // B
		{4, 1, [3]float64{31.14, 42.96, 63.24}}, // C
		{3, 1, [3]float64{32.74, 45.36, 66.54}}, // D
	} {
		for i, ax := range []int{2, 3, 5} {
			got := total(t, tb, Truck{MaxMassKg: 40000, Axles: ax, Euro: tc.euro, CO2Class: tc.cls}, on("2026-06-01"))
			if math.Abs(got*100-tc.want[i]) > 1e-6 {
				t.Errorf("AT Euro %d class %d, %d axles: %.2f ct/km, want %.2f", tc.euro, tc.cls, ax, got*100, tc.want[i])
			}
		}
	}
	// Euro VI, CO2 class 4, 4+ axles: 45.91 + 1.00 + 4.00 = 50.91 ct/km.
	if got := total(t, tb, Truck{MaxMassKg: 40000, Axles: 4, Euro: 6, CO2Class: 4}, on("2026-06-01")); math.Abs(got-0.5091) > 1e-9 {
		t.Errorf("AT class 4: %v, want 0.5091", got)
	}
	if _, ok := Find(tables(t), "AT", on("2027-01-01")); ok {
		t.Error("AT 2027: no table until the 2027 ordinance is published")
	}
}

// Dutch sums from Staatscourant 2026, 3872; the >32 t totals match the
// widely quoted EUR 0.201 (Euro VI, class 1) and 0.038 (zero-emission).
func TestNetherlandsTotals(t *testing.T) {
	tb, ok := Find(tables(t), "NL", on("2026-07-15"))
	if !ok {
		t.Fatal("no NL table for July 2026")
	}
	for _, tc := range []struct {
		kg, euro, cls int
		want          float64
	}{
		{40000, 6, 1, 0.201}, // .089 + .020 + .092
		{40000, 6, 5, 0.038}, // .022 + .016 + 0
		{40000, 5, 1, 0.236}, // .098 + .046 + .092
		{26000, 6, 2, 0.165}, // .074 + .018 + .073
		{15000, 6, 1, 0.160}, // .087 + .016 + .057
		{7500, 0, 1, 0.272},  // .107 + .113 + .052
		{32000, 6, 4, 0.100}, // .043 + .018 + .039
	} {
		if got := total(t, tb, Truck{MaxMassKg: tc.kg, Axles: 5, Euro: tc.euro, CO2Class: tc.cls}, on("2026-07-15")); got != tc.want {
			t.Errorf("NL %d kg Euro %d class %d: %v, want %v", tc.kg, tc.euro, tc.cls, got, tc.want)
		}
	}
	// Before 1 July 2026 the Eurovignette's day charge applies.
	if tb, ok := Find(tables(t), "NL", on("2026-06-30")); !ok || !tb.PerDay {
		t.Error("NL: want the Eurovignette's day charge on 30 June 2026")
	}
}

// Dutch temporary rates, 1 September - 31 December 2026 (Staatscourant
// 2026, 18058), about 22.3% below the statutory ones.
func TestNetherlandsReduced(t *testing.T) {
	tb, ok := Find(tables(t), "NL", on("2026-11-03"))
	if !ok || tb.ValidFrom != "2026-09-01" {
		t.Fatalf("NL November 2026: got %q, want the reduced table", tb.ValidFrom)
	}
	for _, tc := range []struct {
		kg, euro, cls int
		want          float64
	}{
		{40000, 6, 1, 0.156}, // .069 + .016 + .071
		{40000, 6, 5, 0.030}, // .017 + .013 + 0
		{26000, 6, 2, 0.128}, // .057 + .014 + .057
		{7500, 0, 1, 0.211},  // .083 + .088 + .040
	} {
		if got := total(t, tb, Truck{MaxMassKg: tc.kg, Axles: 5, Euro: tc.euro, CO2Class: tc.cls}, on("2026-11-03")); got != tc.want {
			t.Errorf("NL reduced %d kg Euro %d class %d: %v, want %v", tc.kg, tc.euro, tc.cls, got, tc.want)
		}
	}
	if tb, _ := Find(tables(t), "NL", on("2026-08-31")); tb.ValidFrom != "2026-07-01" {
		t.Error("NL 31 August 2026: want the statutory table")
	}
	if tb, _ := Find(tables(t), "NL", on("2027-01-01")); tb.ValidFrom != "2027-01-01" {
		t.Error("NL 2027: want the 2027 indexed table (Staatscourant 2026, 33659)")
	}
}

func TestFindRegion(t *testing.T) {
	src := []Source{{URL: "x"}}
	tbs := []Table{
		{Country: "BE", Region: "BE-VLG", ValidFrom: "2026-01-01", Sources: src},
		{Country: "DE", ValidFrom: "2026-01-01", Sources: src},
	}
	d := on("2026-06-01")
	if tb, ok := Find(tbs, "BE-VLG", d); !ok || tb.Region != "BE-VLG" {
		t.Error("BE-VLG: want the Flemish table")
	}
	if _, ok := Find(tbs, "BE", d); ok {
		t.Error("BE: a regional table must not answer for the whole country")
	}
	if !Regional(tbs, "BE") || Regional(tbs, "DE") {
		t.Error("Regional: BE yes, DE no")
	}
	bad := Table{Country: "BE", Region: "NL-NH", Currency: "EUR", ValidFrom: "2026-01-01", Sources: src, Rows: []Row{{Component: "x"}}}
	if bad.check() == nil {
		t.Error("region outside its country: want an error")
	}
}

// Belgian rates from the Viapass grid (ed. 01/07/2026), spot-checked.
func TestBelgium(t *testing.T) {
	tbs := tables(t)
	d := on("2026-11-04")
	rate := func(area string, tr Truck, road string) float64 {
		t.Helper()
		tb, ok := Find(tbs, area, d)
		if !ok {
			t.Fatalf("no %s table", area)
		}
		rs, _, ok := tb.RatesOn(tr, d, road)
		if !ok || len(rs) != 1 {
			t.Fatalf("%s %+v %s: %v", area, tr, road, rs)
		}
		return rs[0].PerKm
	}
	e6 := Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	zev := Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}
	for _, tc := range []struct {
		area string
		tr   Truck
		road string
		want float64
	}{
		{"BE-VLG", e6, "", 0.285},
		{"BE-VLG", Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 4}, "", 0.203},
		{"BE-VLG", zev, "", 0.038},
		{"BE-VLG", Truck{MaxMassKg: 12000, Axles: 2, Euro: 0, CO2Class: 1}, "", 0.205}, // 12 t is in the 3.5-12 t band
		{"BE-WAL", e6, "", 0.205},
		{"BE-WAL", zev, "", 0.205}, // ZEV pays the Euro VI rate in Wallonia
		{"BE-WAL", Truck{MaxMassKg: 20000, Axles: 3, Euro: 4, CO2Class: 1}, "", 0.203},
		{"BE-BRU", e6, Motorway, 0.171},
		{"BE-BRU", e6, OtherRoad, 0.271},
		{"BE-BRU", zev, OtherRoad, 0.051},
		{"BE-BRU", Truck{MaxMassKg: 40000, Axles: 5, Euro: 3, CO2Class: 1}, Motorway, 0.241},
		{"BE-WAL", Truck{MaxMassKg: 40000, Axles: 5, Euro: 5, CO2Class: 2}, "", 0.221}, // Euro V in a class above 1 still gets a rate
	} {
		if got := rate(tc.area, tc.tr, tc.road); got != tc.want {
			t.Errorf("%s %+v %s: %v, want %v", tc.area, tc.tr, tc.road, got, tc.want)
		}
	}
	if tb, _ := Find(tbs, "BE-BRU", d); len(tb.Roads()) != 2 {
		t.Errorf("Brussels roads %v, want motorway and other", tb.Roads())
	}
	if !Regional(tbs, "BE") {
		t.Error("BE must be regional")
	}
}

// Find takes the first table in force, so an area's tables (not
// crossings, which add up) must not overlap in time.
func TestNoOverlaps(t *testing.T) {
	tbs, err := All()
	if err != nil {
		t.Fatal(err)
	}
	end := func(tb Table) string {
		if tb.ValidTo == "" {
			return "9999-12-31"
		}
		return tb.ValidTo
	}
	for i, a := range tbs {
		for _, b := range tbs[i+1:] {
			if a.Crossings || b.Crossings || a.Area() != b.Area() {
				continue
			}
			if a.ValidFrom <= end(b) && b.ValidFrom <= end(a) {
				t.Errorf("%s and %s overlap", a.File, b.File)
			}
		}
	}
}

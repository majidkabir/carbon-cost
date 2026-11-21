package cost

import (
	"math"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

func on(s string) time.Time {
	d, err := time.Parse(time.DateOnly, s)
	if err != nil {
		panic(err)
	}
	return d
}

// rateOf is what 100 km in an area cost a truck a km (or a day, for a
// time-based charge), in the area's currency: the sum of the rates of its
// toll lines. road is rates.Motorway or rates.OtherRoad where the rates
// differ by road, "" for all motorway. ok is false where nothing is due.
func rateOf(t *testing.T, area string, tr rates.Truck, day, road string) (sum float64, ok bool, notes []string) {
	t.Helper()
	cc, _, _ := strings.Cut(area, "-")
	leg := sootcase.LegResult{DistanceKm: 100, CountryKm: map[string]float64{cc: 100}}
	if area != cc {
		leg.RegionKm = map[string]float64{area: 100}
	}
	mw := 1.0
	if road == rates.OtherRoad {
		mw = 0
	}
	fx := map[string]float64{}
	for _, c := range []string{"DKK", "SEK", "NOK", "CHF", "GBP", "HUF", "CZK", "PLN"} {
		fx[c] = 10
	}
	r, err := Price(sootcase.Result{TTWKg: 50, Legs: []sootcase.LegResult{leg}}, all(t), Request{CargoKg: 1000, Truck: tr,
		TolledShare: map[string]float64{area: 1}, MotorwayShare: map[string]float64{area: mw}, FX: fx}, on(day))
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range r.Lines {
		if l.Charge == RoadToll && l.Country == cc && (area == cc || l.Region == area) {
			sum += l.Rate
			ok = true
		}
	}
	return math.Round(sum*1e6) / 1e6, ok, r.Notes
}

func found(t *testing.T, area, day string) string {
	t.Helper()
	ds, ok := all(t).Find(area, on(day))
	if !ok {
		return ""
	}
	return ds.ValidFrom
}

// The DK components (§ 5 stk. 3) add up to the published rates (§ 5
// stk. 1, Skatteministeriet's Tabel 1 for 2026 and 2027).
func TestDenmarkTotals(t *testing.T) {
	want := map[int][3]float64{1: {.86, 1.00, 1.10}, 2: {.79, .92, 1.01}, 3: {.69, .82, .91}, 4: {.46, .53, .58}, 5: {.13, .13, .13}}
	for cls, row := range want {
		for i, kg := range []int{15000, 26000, 40000} {
			if got, _, _ := rateOf(t, "DK", rates.Truck{MaxMassKg: kg, Axles: 5, Euro: 6, CO2Class: cls}, "2026-06-01", ""); got != row[i] {
				t.Errorf("DK class %d, %d kg: %v DKK/km, want %v", cls, kg, got, row[i])
			}
		}
	}
	// Boundaries: 18,000 and 32,000 kg are in the 18-32 t band.
	if got, _, _ := rateOf(t, "DK", rates.Truck{MaxMassKg: 32000, Axles: 4, Euro: 6, CO2Class: 1}, "2026-06-01", ""); got != 1.00 {
		t.Errorf("DK 32,000 kg: %v, want 1.00", got)
	}
	if _, ok, _ := rateOf(t, "DK", rates.Truck{MaxMassKg: 11999, Axles: 2, Euro: 6, CO2Class: 1}, "2026-06-01", ""); ok {
		t.Error("DK 2026: trucks under 12 t pay no toll")
	}
	if found(t, "DK", "2028-01-01") != "" {
		t.Error("DK: no dataset for 2028 yet (rates not published)")
	}
	// The environmental zone surcharge, over 32 t, class 1: 0.55 kr/km.
	r, err := Price(sootcase.Result{TTWKg: 50, Legs: []sootcase.LegResult{{DistanceKm: 100, CountryKm: map[string]float64{"DK": 100}}}}, all(t),
		Request{CargoKg: 1000, Truck: truck40, EnvZoneKm: map[string]float64{"DK": 10}}, on("2026-06-01"))
	if err != nil {
		t.Fatal(err)
	}
	var zone float64
	for _, l := range r.Lines {
		if l.Component == rates.EnvZoneSurcharge {
			zone = l.Rate
		}
	}
	if zone != .55 {
		t.Errorf("DK zone surcharge, >32 t class 1: %v, want 0.55", zone)
	}
}

// German totals are the sums of the Anlage 1 parts; 34.8 ct/km is the
// widely quoted rate for a 40 t, 5-axle Euro VI truck in CO2 class 1.
func TestGermanyTotals(t *testing.T) {
	for _, tc := range []struct {
		tr   rates.Truck
		want float64
	}{
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, 0.348}, // .155 + .023 + .012 + .158
		{rates.Truck{MaxMassKg: 40000, Axles: 4, Euro: 6, CO2Class: 1}, 0.324}, // .155 + .023 + .012 + .134
		{rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 1}, 0.303}, // .141 + .022 + .016 + .124
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 5, CO2Class: 1}, 0.389}, // .155 + .062 + .012 + .160
		{rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 4}, 0.269}, // .155 + .023 + .012 + .079
		{rates.Truck{MaxMassKg: 16000, Axles: 2, Euro: 6, CO2Class: 1}, 0.238}, // .107 + .015 + .016 + .100
		{rates.Truck{MaxMassKg: 7000, Axles: 2, Euro: 6, CO2Class: 1}, 0.151},  // .052 + .011 + .014 + .074
	} {
		if got, _, _ := rateOf(t, "DE", tc.tr, "2026-11-03", ""); got != tc.want {
			t.Errorf("DE %+v: %v EUR/km, want %v", tc.tr, got, tc.want)
		}
	}
	// Emission-free trucks are exempt until 30 June 2031, then pay.
	zev := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}
	if _, ok, notes := rateOf(t, "DE", zev, "2031-06-30", ""); ok || !strings.Contains(strings.Join(notes, " "), "DE: ") {
		t.Errorf("DE zero-emission 2031-06-30: want exempt, notes %v", notes)
	}
	if got, _, _ := rateOf(t, "DE", zev, "2031-07-01", ""); got != 0.168 { // .155 + .001 + .012 + 0
		t.Errorf("DE zero-emission after the exemption: %v, want 0.168", got)
	}
}

// The Austrian parts (BGBl. II Nr. 298/2025 §§ 2, 8, 9) add up to the 2026
// totals the WKO publishes, in cent/km.
func TestAustriaTotals(t *testing.T) {
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
			got, _, _ := rateOf(t, "AT", rates.Truck{MaxMassKg: 40000, Axles: ax, Euro: tc.euro, CO2Class: tc.cls}, "2026-06-01", "")
			if math.Abs(got*100-tc.want[i]) > 1e-6 {
				t.Errorf("AT Euro %d class %d, %d axles: %.2f ct/km, want %.2f", tc.euro, tc.cls, ax, got*100, tc.want[i])
			}
		}
	}
	// Euro VI, CO2 class 4, 4+ axles: 45.91 + 1.00 + 4.00 = 50.91 ct/km.
	if got, _, _ := rateOf(t, "AT", rates.Truck{MaxMassKg: 40000, Axles: 4, Euro: 6, CO2Class: 4}, "2026-06-01", ""); math.Abs(got-0.5091) > 1e-9 {
		t.Errorf("AT class 4: %v, want 0.5091", got)
	}
	if found(t, "AT", "2027-01-01") != "" {
		t.Error("AT 2027: no dataset until the 2027 ordinance is published")
	}
}

// Dutch sums from Staatscourant 2026, 3872; the >32 t totals match the
// widely quoted EUR 0.201 (Euro VI, class 1) and 0.038 (zero-emission).
func TestNetherlandsTotals(t *testing.T) {
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
		if got, _, _ := rateOf(t, "NL", rates.Truck{MaxMassKg: tc.kg, Axles: 5, Euro: tc.euro, CO2Class: tc.cls}, "2026-07-15", ""); got != tc.want {
			t.Errorf("NL %d kg Euro %d class %d: %v, want %v", tc.kg, tc.euro, tc.cls, got, tc.want)
		}
	}
	// Before 1 July 2026 the Eurovignette's day charge applies.
	ds, ok := all(t).Find("NL", on("2026-06-30"))
	if !ok || networkOf(ds).perDay == nil {
		t.Error("NL: want the Eurovignette's day charge on 30 June 2026")
	}
}

// Dutch temporary rates, 1 September - 31 December 2026 (Staatscourant
// 2026, 18058), about 22.3% below the statutory ones.
func TestNetherlandsReduced(t *testing.T) {
	if got := found(t, "NL", "2026-11-03"); got != "2026-09-01" {
		t.Fatalf("NL November 2026: got %q, want the reduced dataset", got)
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
		if got, _, _ := rateOf(t, "NL", rates.Truck{MaxMassKg: tc.kg, Axles: 5, Euro: tc.euro, CO2Class: tc.cls}, "2026-11-03", ""); got != tc.want {
			t.Errorf("NL reduced %d kg Euro %d class %d: %v, want %v", tc.kg, tc.euro, tc.cls, got, tc.want)
		}
	}
	if found(t, "NL", "2026-08-31") != "2026-07-01" {
		t.Error("NL 31 August 2026: want the statutory dataset")
	}
	if found(t, "NL", "2027-01-01") != "2027-01-01" {
		t.Error("NL 2027: want the 2027 indexed dataset (Staatscourant 2026, 33659)")
	}
}

// Belgian rates from the Viapass grid (ed. 01/07/2026), spot-checked.
func TestBelgium(t *testing.T) {
	e6 := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	zev := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 5}
	for _, tc := range []struct {
		area string
		tr   rates.Truck
		road string
		want float64
	}{
		{"BE-VLG", e6, "", 0.285},
		{"BE-VLG", rates.Truck{MaxMassKg: 26000, Axles: 3, Euro: 6, CO2Class: 4}, "", 0.203},
		{"BE-VLG", zev, "", 0.038},
		{"BE-VLG", rates.Truck{MaxMassKg: 12000, Axles: 2, Euro: 0, CO2Class: 1}, "", 0.205}, // 12 t is in the 3.5-12 t band
		{"BE-WAL", e6, "", 0.205},
		{"BE-WAL", zev, "", 0.205}, // ZEV pays the Euro VI rate in Wallonia
		{"BE-WAL", rates.Truck{MaxMassKg: 20000, Axles: 3, Euro: 4, CO2Class: 1}, "", 0.203},
		{"BE-BRU", e6, rates.Motorway, 0.171},
		{"BE-BRU", e6, rates.OtherRoad, 0.271},
		{"BE-BRU", zev, rates.OtherRoad, 0.051},
		{"BE-BRU", rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 3, CO2Class: 1}, rates.Motorway, 0.241},
		{"BE-WAL", rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 5, CO2Class: 2}, "", 0.221}, // Euro V in a class above 1 still gets a rate
	} {
		if got, _, _ := rateOf(t, tc.area, tc.tr, "2026-11-04", tc.road); got != tc.want {
			t.Errorf("%s %+v %s: %v, want %v", tc.area, tc.tr, tc.road, got, tc.want)
		}
	}
	ds, _ := all(t).Find("BE-BRU", on("2026-11-04"))
	if n := len(networkOf(ds).roadTypes); n != 2 {
		t.Errorf("Brussels road types %d, want motorway and other", n)
	}
	// From 1 January 2027 (Viapass grid ed. 01/01/2027): Flanders and
	// Wallonia indexed, Brussels unchanged but for zero-emission trucks,
	// which pay 60% of the infrastructure part in Flanders and Brussels.
	for _, tc := range []struct {
		area string
		tr   rates.Truck
		road string
		want float64
	}{
		{"BE-VLG", e6, "", 0.297},
		{"BE-VLG", zev, "", 0.078},
		{"BE-WAL", e6, "", 0.212},
		{"BE-WAL", zev, "", 0.212},
		{"BE-BRU", e6, rates.Motorway, 0.171},
		{"BE-BRU", zev, rates.OtherRoad, 0.103},
	} {
		if got, _, _ := rateOf(t, tc.area, tc.tr, "2027-03-01", tc.road); got != tc.want {
			t.Errorf("2027 %s %+v %s: %v, want %v", tc.area, tc.tr, tc.road, got, tc.want)
		}
	}
}

// The Eurovignette years: a day's charge for a 40 t, 5-axle Euro VI
// truck in CO2 class 1.
func TestEurovignetteHistory(t *testing.T) {
	for _, tc := range []struct {
		area, date string
		want       float64
	}{
		{"SE", "2024-06-01", 138}, // SFS 2023:599
		{"SE", "2025-02-01", 138}, // SFS 2024:953
		{"SE", "2025-04-01", 147}, // SFS 2025:46
		{"SE", "2027-06-01", 147}, // SFS 2026:1806
		{"LU", "2024-06-01", 12},  // RGD 21 May 2019, art. 1er 4°
		{"NL", "2025-04-01", 13},  // Wet BZM art. 10 (4), Stb. 2025, 445
		{"DK", "2024-06-01", 89},  // LBK 174/2020 § 3 stk. 4 nr. 5
	} {
		ds, ok := all(t).Find(tc.area, on(tc.date))
		if !ok || networkOf(ds).perDay == nil {
			t.Errorf("%s %s: no day charge", tc.area, tc.date)
			continue
		}
		if got, _, _ := rateOf(t, tc.area, truck40, tc.date, ""); got != tc.want {
			t.Errorf("%s %s: %v, want %g a day", tc.area, tc.date, got, tc.want)
		}
	}
	// Denmark's km toll in 2025: 1.10 kroner a km over 32 t, class 1.
	if got, _, _ := rateOf(t, "DK", truck40, "2025-06-01", ""); math.Abs(got-1.10) > 1e-9 {
		t.Errorf("DK 2025: %g kr/km, want 1.10", got)
	}
}

// A zone's polygon with a hole: inside the outer ring, not in the hole.
func TestInPolygons(t *testing.T) {
	polys := [][][][2]float64{{{{0, 0}, {2, 0}, {2, 2}, {0, 2}}, {{0.5, 0.5}, {1, 0.5}, {1, 1}, {0.5, 1}}}}
	for p, want := range map[[2]float64]bool{{1.5, 1.5}: true, {0.7, 0.7}: false, {3, 1}: false} {
		if inPolygons(polys, p) != want {
			t.Errorf("inPolygons(%v) = %v", p, !want)
		}
	}
}

// Stockholm's and Göteborg's congestion tax days (lag 2004:629, bilaga 1
// and 2): weekdays but public holidays, the days before them and July
// (Stockholm: its first five weekdays are taxed), Stockholm's eves of Good
// Friday, Ascension, All Saints, 1 May and 6 June taxed; Stockholm's high
// season from 1 March to the day before Midsummer Eve and 15 August to 30
// November.
func TestCongestionDays(t *testing.T) {
	sto := [][2]float64{{18.1034, 59.0}, {18.1034, 59.3130}, {18.1034, 59.3150}}
	gbg := [][2]float64{{11.9941, 57.7190}, {11.99404, 57.7199}, {11.9839, 57.7238}, {11.98, 57.725}}
	tax := func(path [][2]float64, day string) float64 {
		t.Helper()
		trip := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1, CountryKm: map[string]float64{"SE": 1}, Path: path}}}
		r, err := Price(trip, all(t), Request{CargoKg: 1000, Truck: truck40, Time: "07:00", AvgSpeedKmh: 70, FX: map[string]float64{"SEK": 11}}, on(day))
		if err != nil {
			t.Fatal(err)
		}
		sum := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Source, "trängselskatt") {
				sum += l.Amount
			}
		}
		return sum
	}
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
		if got := tax(sto, tc.day) > 0; got != tc.sto {
			t.Errorf("Stockholm %s taxed %v, want %v", tc.day, got, tc.sto)
		}
		if got := tax(gbg, tc.day) > 0; got != tc.gbg {
			t.Errorf("Göteborg %s taxed %v, want %v", tc.day, got, tc.gbg)
		}
	}
	for day, high := range map[string]bool{"2026-03-02": true, "2026-06-18": true, "2026-08-14": false, "2026-08-17": true, "2026-11-30": true, "2026-12-01": false} {
		if got := tax(sto, day); (got == 45) != high {
			t.Errorf("Stockholm %s at about 07:30: %v SEK; high season %v (45 SEK)", day, got, high)
		}
	}
}

// Slovenia: the Serminska vpadnica (G2-114) to the port of Koper is a
// toll section from 26 October 2026 (Uredba 1746/26, cenik 1771/26).
func TestSloveniaSerminska(t *testing.T) {
	for day, want := range map[string]string{"2026-10-25": "2026-04-01", "2026-10-26": "2026-10-26", "2027-06-01": "2026-10-26"} {
		if got := found(t, "SI", day); got != want {
			t.Errorf("SI on %s: the table from %s, want %s", day, got, want)
		}
	}
	for day, want := range map[string]bool{"2026-10-25": false, "2026-11-01": true} {
		ds, _ := all(t).Find("SI", on(day))
		has := false
		for _, o := range ds.Objects() {
			if strings.Contains(o.ID, "g2-114") {
				has = true
			}
		}
		if has != want {
			t.Errorf("SI on %s: Serminska vpadnica %v, want %v", day, has, want)
		}
	}
}

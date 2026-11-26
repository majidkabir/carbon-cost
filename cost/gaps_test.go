package cost

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math"
	"math/rand"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/sootcase/pkg/borders"
)

func priceLeg(t *testing.T, cc string, km float64, path [][2]float64, req Request, date string) Response {
	t.Helper()
	d, _ := time.Parse(time.DateOnly, date)
	req.CargoKg, req.Truck = 10000, rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{cc: km}, Path: dense(path), RouteParts: map[string]float64{"road": km}}}}
	out, err := Price(res, all(t), req, d)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// An entry and exit the table doesn't pair leave the toll out of the
// total: the result isn't complete.
func TestUnpricedPairIsMissing(t *testing.T) {
	// Serbia's A1 from the BEŠKA booths to MARADIK's.
	out := priceLeg(t, "RS", 9, [][2]float64{{20.075, 45.155}, {20.09016, 45.13511}, {20.10304, 45.0994}, {20.115, 45.08}},
		Request{TolledShare: map[string]float64{"RS": 1}, FX: map[string]float64{"RSD": 117}}, "2026-11-20")
	if out.Complete || len(out.Missing) != 1 || out.Missing[0].Reason != "unpriced" {
		t.Fatalf("complete %v, missing %+v; want the RS toll missing as unpriced", out.Complete, out.Missing)
	}
}

// Skurubron's gantries take the bridge charge only, not Stockholm's
// congestion tax.
func TestSkurubronIsABridge(t *testing.T) {
	out := priceLeg(t, "SE", 3, [][2]float64{{18.205, 59.3138}, {18.245, 59.3138}},
		Request{Time: "07:30", FX: map[string]float64{"SEK": 11}}, "2026-11-19")
	var got []string
	for _, l := range out.Lines {
		if strings.Contains(l.Section, "Skurubron") {
			got = append(got, l.Section)
		}
	}
	if len(got) != 1 {
		t.Fatalf("Skurubron lines %q; want the bridge's only", got)
	}
}

// ferryTrip is a short road to port a, the ferry to port b (by way of
// via) and a short road on (lon, lat).
func ferryTrip(t *testing.T, date string, a, b [2]float64, ca, cb string, via ...[2]float64) Response {
	t.Helper()
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	hav := func(p, q [2]float64) float64 { return haversine(p[1], p[0], q[1], q[0]) }
	before, after := [2]float64{a[0] - 0.03, a[1]}, [2]float64{b[0] + 0.03, b[1]}
	r1, f, r2 := hav(before, a), hav(a, b), hav(b, after)
	sea := append(append([][2]float64{a}, via...), b)
	path := append(dense([][2]float64{before, a}), dense(sea)[1:]...)
	path = append(path, dense([][2]float64{b, after})[1:]...)
	leg := sootcase.LegResult{DistanceKm: r1 + f + r2, TTWKg: 60, WTWKg: 70, CountryKm: map[string]float64{ca: r1, cb: r2}, Path: path,
		RouteParts: map[string]float64{"road": r1 + r2, "ferry": f},
		Parts:      []sootcase.Part{{Kind: "road", DistanceKm: r1}, {Kind: "ferry", DistanceKm: f, TTWKg: 50, WTWKg: 60}, {Kind: "road", DistanceKm: r2}}}
	req := Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, EUAEurPerT: 80,
		FX: map[string]float64{"GBP": 0.84, "DKK": 7.46}}
	day, _ := time.Parse(time.DateOnly, date)
	out, err := PriceWith(sootcase.Result{Legs: []sootcase.LegResult{leg}}, all(t), &fd, req, day)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// A crossing this tool knows, but has no fare table for, is missing from
// the total; one it has a table for isn't.
func TestFareWithNoTableIsMissing(t *testing.T) {
	dover := ferryTrip(t, "2026-11-20", [2]float64{1.332393, 51.123741}, [2]float64{1.854074, 50.967206}, "GB", "FR")
	want := Missing{Area: "GB", Charge: FerryFare, Name: dover.FerryCrossing, Reason: "no_table"}
	if dover.Complete || !slices.ContainsFunc(dover.Missing, func(m Missing) bool { m.Text = ""; return m == want }) {
		t.Errorf("Dover–Calais: crossing %q, complete %v, missing %+v; want %+v", dover.FerryCrossing, dover.Complete, dover.Missing, want)
	}
	// By the fare table's stations, 0.5 km out on the line.
	rodby := ferryTrip(t, "2026-11-20", [2]float64{11.3522, 54.6556}, [2]float64{11.2275, 54.5003}, "DK", "DE", [2]float64{11.34562, 54.650674}, [2]float64{11.231603, 54.506517})
	for _, m := range rodby.Missing {
		if m.Charge == FerryFare {
			t.Errorf("Rødby–Puttgarden: crossing %q, missing %+v; want its Scandlines fare", rodby.FerryCrossing, m)
		}
	}
	fare := false
	for _, l := range rodby.Lines {
		fare = fare || l.Charge == FerryFare
	}
	if !fare {
		t.Errorf("Rødby–Puttgarden: no fare line")
	}
}

// A trip with no charges has "lines": [], as the schema says, not null.
func TestNoLinesIsEmptyList(t *testing.T) {
	// Ukraine, with the diesel given: no charges and no sources.
	out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: map[string]float64{"UA": 100}, Date: "2026-11-20",
		CargoKg: 10000, DieselL: 30, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}})
	if err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(out)
	if !strings.Contains(string(b), `"lines":[]`) {
		t.Errorf("UA 100 km: %s; want \"lines\":[]", b)
	}
	// Nothing the schema calls a list or an object is null.
	if strings.Contains(string(b), ":null") {
		t.Errorf("UA 100 km: a null in %s", b)
	}
}

// A per-km toll's km driven after midnight on its table's last day are
// priced at the next table's rates: NL from 23:30 on 31 December 2026,
// 35 km at 2026's rate and 65 km at 2027's.
func TestKmAfterMidnightUseTheNextTable(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"NL": 100}, RouteParts: map[string]float64{"road": 100}}}}
	req := Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Time: "23:30", AvgSpeedKmh: 70,
		spans: map[string][][2]float64{"NL": {{0, 100}}}}
	out, err := Price(res, all(t), req, time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	km := map[float64]float64{}
	for _, l := range out.Lines {
		if l.Country == "NL" && l.Component == "infrastructure" {
			km[l.Rate] += l.Km
		}
	}
	if math.Abs(km[0.069]-35) > 0.5 || math.Abs(km[0.092]-65) > 0.5 {
		t.Errorf("NL infrastructure km by rate %v; want 35 at 0.069 and 65 at 0.092", km)
	}
}

// The Strait of Messina's fares include the EU ETS: no ETS line on top.
func TestETSInTheFare(t *testing.T) {
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	// Catania, Messina Tremestieri, the ferry to Villa San Giovanni, north.
	path := dense([][2]float64{{15.20, 37.60}, {15.45, 38.05}, {15.52959, 38.13635}, {15.61548, 38.21328}, {15.70, 38.40}})
	res := sootcase.Result{TTWKg: 100, WTWKg: 120, Legs: []sootcase.LegResult{{DistanceKm: 90, TTWKg: 100, WTWKg: 120, Path: path,
		RouteParts: map[string]float64{"ferry": 11}, CountryKm: map[string]float64{"IT": 79},
		Parts: []sootcase.Part{{Kind: "ferry", DistanceKm: 11, TTWKg: 25, WTWKg: 30}}}}}
	req := Request{CargoKg: 20000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1, LengthM: 16.5}, EUAEurPerT: 75}
	out, err := PriceWith(res, all(t), &fd, req, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	fare, ets := 0, 0
	for _, l := range out.Lines {
		switch l.Charge {
		case FerryFare:
			fare++
		case FerryETS:
			ets++
		}
	}
	if fare != 1 || ets != 0 {
		t.Errorf("Messina: %d fare lines, %d ETS lines; want the fare alone", fare, ets)
	}
}

// Before a crossing's first table here, the trip doesn't pay nothing:
// the fare is missing, as "before_table". A charge that only began with
// its first table (charged_from) isn't.
func TestBeforeTheFirstTable(t *testing.T) {
	rodby := ferryTrip(t, "2025-06-01", [2]float64{11.3522, 54.6556}, [2]float64{11.2275, 54.5003}, "DK", "DE", [2]float64{11.34562, 54.650674}, [2]float64{11.231603, 54.506517})
	found := false
	for _, m := range rodby.Missing {
		found = found || m.Charge == FerryFare && m.Reason == "before_table" && m.Starts == "2026-01-01"
	}
	if rodby.Complete || !found {
		t.Errorf("Rødby–Puttgarden on 2025-06-01: complete %v, missing %+v; want the fare before_table from 2026-01-01", rodby.Complete, rodby.Missing)
	}
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"LT": 100}, RouteParts: map[string]float64{"road": 100}}}}
	lt, err := Price(res, all(t), Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, DieselL: 30, FuelCountry: "LT"},
		time.Date(2024, 6, 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, m := range lt.Missing {
		if m.Charge == FuelCO2 {
			t.Errorf("LT fuel CO2 in 2024, before it began: missing %+v", m)
		}
	}
}

// Sootcase failing on the routes asked for is still Sootcase failing (a
// bad gateway), not a bad request.
func TestRoutesKeepTheErrorsKind(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// No country_km: Sootcase's answer can't be priced.
		res := sootcase.Result{TTWKg: 100, WTWKg: 120, Legs: []sootcase.LegResult{{DistanceKm: 300, TTWKg: 100, WTWKg: 120,
			Path:         [][2]float64{{12.5, 55.6}, {10, 53.5}},
			Alternatives: []sootcase.LegResult{{ID: "alt1", DistanceKm: 320, TTWKg: 110, WTWKg: 130, Path: [][2]float64{{12.5, 55.6}, {10, 53.5}}}}}}}
		json.NewEncoder(w).Encode(res)
	}))
	defer srv.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL}, Tariffs: all(t)}
	_, err := c.Calculate(context.Background(), Request{From: sootcase.Location{Code: "DKCPH"}, To: sootcase.Location{Code: "DEHAM"}, Date: "2026-11-03",
		CargoKg: 20000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Alternatives: 2})
	var fe *sootcase.Failed
	if !errors.As(err, &fe) {
		t.Errorf("alternatives 2, Sootcase's answer unusable: %v; want a sootcase.Failed", err)
	}
}

// A region's km are split by day by when that region is driven: Wallonia
// from 23:00 to midnight, Flanders after it, on 31 December 2026.
func TestRegionKmByTheirOwnDay(t *testing.T) {
	leg := sootcase.LegResult{DistanceKm: 140, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"BE": 140},
		RegionKm: map[string]float64{"BE-WAL": 70, "BE-VLG": 70}, RouteParts: map[string]float64{"road": 140},
		CountrySections: []sootcase.CountrySection{{Country: "BE", FromKm: 0, ToKm: 140, Regions: []sootcase.RegionSection{
			{Region: "BE-WAL", FromKm: 0, ToKm: 70}, {Region: "BE-VLG", FromKm: 70, ToKm: 140}}}}}
	req := Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Time: "23:00", AvgSpeedKmh: 70,
		TolledShare: map[string]float64{"BE-WAL": 1, "BE-VLG": 1}, spans: map[string][][2]float64{"BE": {{0, 140}}}}
	out, err := Price(sootcase.Result{Legs: []sootcase.LegResult{leg}}, all(t), req, time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	km := map[string]float64{} // region and rate: km
	for _, l := range out.Lines {
		if l.Charge == RoadToll && l.Country == "BE" {
			km[fmt.Sprintf("%s %g", l.Region, l.Rate)] += l.Km
		}
	}
	// 2026's rate for Wallonia, 2027's for Flanders.
	if want := map[string]float64{"BE-WAL 0.205": 70, "BE-VLG 0.297": 70}; !maps.Equal(km, want) {
		t.Errorf("BE km by region and rate: %v; want %v", km, want)
	}
}

// Stockholm's congestion tax goes by the time of day: without a time it
// is missing, not left out unseen.
func TestCongestionNeedsTime(t *testing.T) {
	path := [][2]float64{{18.095, 59.3139}, {18.112, 59.3139}}
	out := priceLeg(t, "SE", 1, path, Request{FX: map[string]float64{"SEK": 11}}, "2026-11-24")
	if out.Complete || !slices.ContainsFunc(out.Missing, func(m Missing) bool { return m.Reason == "needs_time" }) {
		t.Errorf("through Danvikstull without time: complete %v, missing %+v; want needs_time", out.Complete, out.Missing)
	}
	timed := priceLeg(t, "SE", 1, path, Request{Time: "08:00", FX: map[string]float64{"SEK": 11}}, "2026-11-24")
	if !timed.Complete {
		t.Errorf("at 08:00: missing %+v", timed.Missing)
	}
	// No tax on a Sunday, nor in Göteborg in July: nothing to miss.
	for _, c := range []struct {
		day  string
		path [][2]float64
	}{{"2026-11-22", path}, {"2026-11-22", [][2]float64{{11.9423, 57.670}, {11.9423, 57.690}}}, {"2026-07-15", [][2]float64{{11.9423, 57.670}, {11.9423, 57.690}}}} {
		if out := priceLeg(t, "SE", 2, c.path, Request{FX: map[string]float64{"SEK": 11}}, c.day); !out.Complete {
			t.Errorf("%s %v without time: missing %+v; want complete", c.day, c.path[0], out.Missing)
		}
	}
}

// A toll area before its first table here: before_table, not no_table.
func TestTollBeforeTheFirstTable(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"DE": 100}, RouteParts: map[string]float64{"road": 100}}}}
	out, err := Price(res, all(t), Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}}, time.Date(2023, 11, 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if !slices.ContainsFunc(out.Missing, func(m Missing) bool { return m.Charge == RoadToll && m.Reason == "before_table" && m.Starts != "" }) {
		t.Errorf("DE on 2023-11-01: missing %+v; want its tolls before_table", out.Missing)
	}
}

// The A 12's +25% stays a line of its own when its km run past midnight
// (two days merged into one line): the base line is its rate × km.
func TestSurchargeLineOverMidnight(t *testing.T) {
	pts := [][2]float64{{12.187, 47.607}, {12.1756, 47.5965}, {12.1408, 47.5675}, {12.0941, 47.5333}, {12.0572, 47.495}, {12.0235, 47.4838},
		{11.8842, 47.4411}, {11.8032, 47.4028}, {11.7016, 47.3577}, {11.6792, 47.3307}, {11.5838, 47.2998}, {11.5015, 47.2739},
		{11.4764, 47.271}, {11.4385, 47.2606}, {11.4202, 47.2547}}
	var km float64
	for i := 0; i+1 < len(pts); i++ {
		km += haversine(pts[i][1], pts[i][0], pts[i+1][1], pts[i+1][0])
	}
	res := sootcase.Result{TTWKg: 100, Legs: []sootcase.LegResult{{DistanceKm: km, CountryKm: map[string]float64{"AT": km}, Path: pts}}}
	req := Request{CargoKg: 1, Truck: truck40, Time: "23:30", AvgSpeedKmh: 70, spans: map[string][][2]float64{"AT": {{0, km}}}}
	out, err := Price(res, all(t), req, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range out.Lines {
		if l.Component == rates.Infrastructure && math.Abs(l.Amount-l.Rate*l.Km) > 0.02 {
			t.Errorf("%q: EUR %.2f for %.2f km at %g; want rate × km", l.Section, l.Amount, l.Km, l.Rate)
		}
	}
}

// A vignette over two days counts its km once: Sweden's 140 km from
// 23:00, on two days.
func TestVignetteKmOnce(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 140, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"SE": 140}, RouteParts: map[string]float64{"road": 140}}}}
	req := Request{CargoKg: 10000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Time: "23:00", AvgSpeedKmh: 70,
		FX: map[string]float64{"SEK": 11}, spans: map[string][][2]float64{"SE": {{0, 140}}}}
	out, err := Price(res, all(t), req, time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range out.Lines {
		if l.Country == "SE" && l.Charge == RoadToll && l.Days > 0 && l.Km != 140 {
			t.Errorf("SE vignette over %d days on %.1f km; want 140 km", l.Days, l.Km)
		}
	}
}

// With the path driven given, the driving bans go by its countries, not
// by Sootcase's route: a path in the Netherlands meets no German ban.
func TestOwnPathBans(t *testing.T) {
	bix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Sootcase's way from Venlo to Nijmegen, mostly in Germany.
		json.NewEncoder(w).Encode(sootcase.Result{TTWKg: 60, WTWKg: 70, Legs: []sootcase.LegResult{{DistanceKm: 70, TTWKg: 60, WTWKg: 70, DurationH: 0.2,
			CountryKm: map[string]float64{"NL": 15, "DE": 55}, Path: [][2]float64{{6.17, 51.37}, {6.25, 51.6}, {5.86, 51.84}},
			CountrySections: []sootcase.CountrySection{{Country: "NL", FromKm: 0, ToKm: 5}, {Country: "DE", FromKm: 5, ToKm: 60}, {Country: "NL", FromKm: 60, ToKm: 70}}}}})
	}))
	defer srv.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL}, Tariffs: all(t), Borders: bix}
	out, err := c.Calculate(context.Background(), Request{From: sootcase.Location{Code: "NLVEN"}, To: sootcase.Location{Code: "NLNIM"}, Date: "2026-11-22", Time: "10:00",
		CargoKg: 20000, Truck: rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}, Path: [][2]float64{{6.17, 51.37}, {6.0, 51.55}, {5.86, 51.84}}})
	if err != nil {
		t.Fatal(err)
	}
	if out.CountryKm["DE"] > 0 || slices.ContainsFunc(out.Bans, func(b BanHit) bool { return b.Country == "DE" }) {
		t.Errorf("country km %v, bans %+v; want no German ban", out.CountryKm, out.Bans)
	}
	// Nor Sootcase's driving time: the path's km at the average speed.
	if want := math.Round(out.Trip.RoadKm/DefaultAvgSpeedKmh*100) / 100; out.Trip.Hours != want {
		t.Errorf("hours %v; want %v", out.Trip.Hours, want)
	}
}

// A crossing whose fare table's ports the route given doesn't pass (a
// straight line between the terminals) isn't taken as priced.
func TestFareOffTheRoute(t *testing.T) {
	out := ferryTrip(t, "2026-11-20", [2]float64{11.3522, 54.6556}, [2]float64{11.2275, 54.5003}, "DK", "DE")
	if out.Complete || !slices.ContainsFunc(out.Missing, func(m Missing) bool { return m.Charge == FerryFare && m.Reason == "unpriced" }) {
		t.Errorf("Rødby–Puttgarden off the ferry line: complete %v, missing %+v; want the fare unpriced", out.Complete, out.Missing)
	}
}

// A very low average speed is refused; a trip of more than a month isn't
// checked for bans (it would take long, and isn't a drive to plan).
func TestSlowAndLongTrips(t *testing.T) {
	truck := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	c := Calculator{Tariffs: all(t)}
	if _, err := c.Calculate(context.Background(), Request{CountryKm: map[string]float64{"DE": 100}, CargoKg: 1000, Truck: truck, Time: "10:00", AvgSpeedKmh: 0.001}); err == nil {
		t.Errorf("avg_speed_kmh 0.001: no error")
	}
	start := time.Now()
	out, err := c.Calculate(context.Background(), Request{CountryKm: map[string]float64{"DE": 99999, "FR": 99999}, Date: "2026-11-20", CargoKg: 1000, Truck: truck, Time: "10:00", AvgSpeedKmh: 5})
	if err != nil {
		t.Fatal(err)
	}
	if !slices.ContainsFunc(out.Notes, func(n string) bool { return strings.Contains(n, "bans aren't checked") }) || time.Since(start) > 10*time.Second {
		t.Errorf("200,000 km at 5 km/h: %v, notes %q", time.Since(start), out.Notes)
	}
}

// A driven path that crosses the Storebælt bridge and back on one leg
// pays it both ways.
func TestOneLegPassesTwice(t *testing.T) {
	out := dense([][2]float64{{12.0, 55.45}, {11.2, 55.37}, {11.10879, 55.3498}, {10.87, 55.31}, {10.39, 55.40}})
	path := append(out, reversed(out)[1:]...)
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 280, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"DK": 280}, Path: path, RouteParts: map[string]float64{}}}}
	r, err := Price(res, all(t), Request{CargoKg: 10000, Truck: truck40}, time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	n := 0
	for _, l := range r.Lines {
		if strings.Contains(l.Section, "Storebælt") {
			n++
		}
	}
	if n != 2 {
		t.Errorf("Storebælt lines on one leg out and back: %d; want 2", n)
	}
}

// The same for a closed system: Benkovac to Bisko and back on one leg is
// two tickets.
func TestOneLegTwoTickets(t *testing.T) {
	there := dense([][2]float64{{15.55, 44.03}, {15.5809, 44.00868}, {16.0, 43.8}, {16.68549, 43.57016}, {16.72, 43.55}})
	price := func(path [][2]float64) float64 {
		res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"HR": 300}, Path: path, RouteParts: map[string]float64{}}}}
		r, err := Price(res, all(t), Request{CargoKg: 10000, Truck: truck40}, time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		sum := 0.0
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.RateUnit == "EUR/passage" {
				sum += l.Amount
			}
		}
		return sum
	}
	one, two := price(there), price(append(there, reversed(there)[1:]...))
	if one == 0 || math.Abs(two-2*one) > 0.01 {
		t.Errorf("Benkovac–Bisko: one way EUR %.2f, there and back on one leg EUR %.2f; want twice", one, two)
	}
}

// A ticket entered just before midnight on a table's last day and left
// after it is priced (by the table at the exit), not dropped.
func TestTicketOverATableChange(t *testing.T) {
	path := dense([][2]float64{{15.55, 44.03}, {15.5809, 44.00868}, {16.0, 43.8}, {16.68549, 43.57016}, {16.72, 43.55}})
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 120, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"HR": 120}, Path: path, RouteParts: map[string]float64{}}}}
	for _, at := range []string{"20:00", "23:30"} {
		r, err := Price(res, all(t), Request{CargoKg: 10000, Truck: truck40, Time: at}, time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		sum := 0.0
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.RateUnit == "EUR/passage" {
				sum += l.Amount
			}
		}
		if sum == 0 || !r.Complete {
			t.Errorf("Benkovac–Bisko on 2025-12-31 at %s: EUR %.2f, missing %+v; want it priced", at, sum, r.Missing)
		}
	}
}

// A bridge whose rates ended is missing whatever the departure time: at
// 23:55 on a day after its table ended the bridge is still reached.
func TestEndedWhateverTheTime(t *testing.T) {
	set := all(t)
	var last string
	for _, ds := range set.All {
		if ds.Scheme == "dk-bridges" && ds.ValidTo > last {
			last = ds.ValidTo
		}
	}
	if last == "" {
		t.Skip("dk-bridges has no last day")
	}
	day, _ := time.Parse(time.DateOnly, last)
	day = day.AddDate(0, 0, 12)
	res := sootcase.Result{Legs: []sootcase.LegResult{storebaelt()}}
	for _, at := range []string{"10:00", "23:55"} {
		r, err := Price(res, set, Request{CargoKg: 10000, Truck: truck40, Time: at}, day)
		if err != nil {
			t.Fatal(err)
		}
		if !slices.ContainsFunc(r.Missing, func(m Missing) bool { return m.Reason == "ended" }) {
			t.Errorf("Storebælt on %s at %s: missing %+v; want it ended", day.Format(time.DateOnly), at, r.Missing)
		}
	}
}

// A start time (telematics, UTC) is the trip's day where it starts:
// 22:30 UTC on 19 November is the 20th in Helsinki, the 19th in Lisbon.
func TestDateFromAStartTime(t *testing.T) {
	for cc, want := range map[string]string{"FI": "2026-11-20", "PT": "2026-11-19"} {
		out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: map[string]float64{cc: 10}, Date: "2026-11-19T22:30:00Z",
			CargoKg: 1000, Truck: truck40})
		if err != nil {
			t.Fatal(err)
		}
		if out.Date != want {
			t.Errorf("%s: date %s; want %s", cc, out.Date, want)
		}
	}
}

// A ticket over the October clock change: the exit (02:12+01:00) comes
// after the entry (02:23+02:00), though its text sorts first.
func TestTicketOverTheClockChange(t *testing.T) {
	path := dense([][2]float64{{16.20, 44.04}, {15.5809, 44.00868}, {16.0, 43.8}, {16.68549, 43.57016}, {16.72, 43.55}})
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 200, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"HR": 200}, Path: path, RouteParts: map[string]float64{}}}}
	r, err := Price(res, all(t), Request{CargoKg: 10000, Truck: truck40, Time: "01:59", AvgSpeedKmh: 130}, time.Date(2026, 10, 25, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if !r.Complete || r.TotalEUR == 0 {
		t.Errorf("Benkovac–Bisko on 2026-10-25 from 01:59: EUR %.2f, missing %+v", r.TotalEUR, r.Missing)
	}
}

// A port with points on two ferry lines (Vela Luka, 33 km out on the
// Split line and 3 km out on the Ubli one) is passed once on Split–Ubli:
// one fare from the first port to the last.
func TestPortOnTwoLinesIsOneVisit(t *testing.T) {
	path := dense([][2]float64{{16.4335, 43.5002}, {16.434624, 43.498295}, {16.435676, 43.164294}, {16.715, 42.963}, {16.6703, 42.962329}, {16.820807, 42.748651}})
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 120, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"HR": 10}, Path: path, RouteParts: map[string]float64{}}}}
	tr := truck40
	tr.CapacityKg = 25000
	r, err := Price(res, all(t), Request{CargoKg: 10000, Truck: tr}, time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	var fares []string
	for _, l := range r.Lines {
		if l.Charge == FerryFare {
			fares = append(fares, fmt.Sprintf("%s %.2f", l.Section, l.Amount))
		}
	}
	if len(fares) != 1 || !strings.Contains(fares[0], "SPLIT") || !strings.Contains(fares[0], "UBLI") {
		t.Errorf("fares %q; want one, Split to Ubli", fares)
	}
}

// A short turnaround (2 km past Bisko) still makes the way back a ticket
// of its own.
func TestShortTurnaround(t *testing.T) {
	there := dense([][2]float64{{15.55, 44.03}, {15.5809, 44.00868}, {16.0, 43.8}, {16.68549, 43.57016}, {16.70, 43.555}})
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"HR": 300},
		Path: append(there, reversed(there)[1:]...), RouteParts: map[string]float64{}}}}
	r, err := Price(res, all(t), Request{CargoKg: 10000, Truck: truck40}, time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if math.Abs(r.TotalEUR-2*18.88) > 0.05 {
		var ls []string
		for _, l := range r.Lines {
			ls = append(ls, fmt.Sprintf("%s %s %.2f", l.Charge, l.Section, l.Amount))
		}
		t.Logf("lines %q", ls)
	}
	n := 0
	for _, l := range r.Lines {
		if l.RateUnit == "EUR/passage" && l.Charge == RoadToll {
			n++
		}
	}
	if n != 2 {
		t.Errorf("Benkovac–Bisko and back with a 2 km turnaround: %d tickets; want 2", n)
	}
}

// On France's chained system, one leg driven Allaines–Ambérieu and back
// two or three times pays two or three times one round trip.
func TestChainedLaps(t *testing.T) {
	a, z := [2]float64{1.84618, 48.20516}, [2]float64{5.31252, 45.97777}
	// About 20 km past each end, and back.
	a0, z0 := [2]float64{a[0] - 0.25, a[1] + 0.12}, [2]float64{z[0] + 0.2, z[1] - 0.12}
	lap := dense([][2]float64{a0, a, z, z0, z, a, a0})
	price := func(n int) float64 {
		path := lap
		for i := 1; i < n; i++ {
			path = append(path, lap[1:]...)
		}
		res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 900 * float64(n), TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"FR": 900 * float64(n)}, Path: path, RouteParts: map[string]float64{}}}}
		r, err := Price(res, all(t), Request{CargoKg: 10000, Truck: truck40}, time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		sum := 0.0
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.Country == "FR" {
				sum += l.Amount
			}
		}
		return sum
	}
	one := price(1)
	if two, three := price(2), price(3); one == 0 || math.Abs(two-2*one) > 0.05 || math.Abs(three-3*one) > 0.05 {
		t.Errorf("FR round trips on one leg: %.2f, %.2f, %.2f; want multiples of the first", one, two, three)
	}
}

// A path with no km in any country is the caller's mistake, not
// Sootcase's.
func TestPathAtSea(t *testing.T) {
	bix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(sootcase.Result{TTWKg: 60, WTWKg: 70, Legs: []sootcase.LegResult{{DistanceKm: 120, TTWKg: 60, WTWKg: 70,
			CountryKm: map[string]float64{"DE": 120}, Path: [][2]float64{{9.99, 53.55}, {8.8, 53.08}}}}})
	}))
	defer srv.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL}, Tariffs: all(t), Borders: bix}
	_, err = c.Calculate(context.Background(), Request{From: sootcase.Location{Code: "DEHAM"}, To: sootcase.Location{Code: "DEBRE"}, Date: "2026-11-20",
		CargoKg: 1000, Truck: truck40, Path: [][2]float64{{3.0, 55.0}, {3.5, 55.2}}})
	var fe *sootcase.Failed
	if err == nil || errors.As(err, &fe) || !strings.Contains(err.Error(), "path") {
		t.Errorf("a path at sea: %v; want a path error", err)
	}
}

// The Elbe ferry's fare for the load goes by each leg's own: out with
// 20 t, back empty or with 1 t.
func TestElbeLoadPerLeg(t *testing.T) {
	path := [][2]float64{{9.42, 53.80}, {9.398622, 53.793962}, {9.352505, 53.78884}, {9.33, 53.785}}
	leg := func(p [][2]float64) sootcase.LegResult {
		return sootcase.LegResult{DistanceKm: 25, CountryKm: map[string]float64{"DE": 25}, Path: p}
	}
	res := sootcase.Result{Legs: []sootcase.LegResult{leg(path), leg(reversed(path))}}
	for back, want := range map[float64]float64{0: 25.20, 1000: 25.20 + 1.26} {
		req := Request{Truck: truck40, Stops: []sootcase.Location{{Code: "A"}, {Code: "B"}, {Code: "A"}},
			Shipments: []Shipment{{ID: "out", WeightKg: 20000, From: 0, To: 1}}}
		if back > 0 {
			req.Shipments = append(req.Shipments, Shipment{ID: "back", WeightKg: back, From: 1, To: 2})
		}
		req.legLoadKg = []float64{20000, back}
		r, err := Price(res, all(t), req, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range r.Lines {
			if strings.Contains(l.Source, "fare for loads") {
				got += l.Amount
			}
		}
		if math.Abs(got-want) > 0.01 {
			t.Errorf("back with %v kg: the loads' fares EUR %.2f; want %.2f", back, got, want)
		}
	}
}

// A toll point passed on the way to a stop 0.3 km past it and again on
// the way back is two passages.
func TestPointBothWaysNearAStop(t *testing.T) {
	pt := [2]float64{10.132119, 59.119744}
	from := [2]float64{pt[0] - 0.05, pt[1] - 0.02}
	// 0.3 km on past the point, the same way.
	d := [2]float64{pt[0] - from[0], pt[1] - from[1]}
	km := haversine(from[1], from[0], pt[1], pt[0])
	stop := [2]float64{pt[0] + d[0]*0.3/km, pt[1] + d[1]*0.3/km}
	there := dense([][2]float64{from, pt, stop})
	leg := func(p [][2]float64) sootcase.LegResult {
		return sootcase.LegResult{DistanceKm: 4, CountryKm: map[string]float64{"NO": 4}, Path: p}
	}
	r, err := Price(sootcase.Result{Legs: []sootcase.LegResult{leg(there), leg(reversed(there))}}, all(t),
		Request{Truck: truck40, CargoKg: 1000, Stops: []sootcase.Location{{Code: "A"}, {Code: "B"}, {Code: "A"}}, FX: map[string]float64{"NOK": 11.7}},
		time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	n := 0
	for _, l := range r.Lines {
		if strings.Contains(l.Section, "Skinmo") {
			n++
		}
	}
	if n != 2 {
		t.Errorf("E18 Skinmo there and back with a stop 0.3 km past it: %d passages; want 2", n)
	}
}

// A stop just past a toll point, its GPS fixes repeated and one a few
// metres back, is one pass, not a U-turn.
func TestStopJitterIsOnePass(t *testing.T) {
	p := rates.Place{Lat: 55.0, Lon: 11.0}
	at := func(m float64) [2]float64 { return [2]float64{11.0 + m/1000/(111.2*math.Cos(55*math.Pi/180)), 55.0} }
	var path [][2]float64
	for m := -500.0; m <= 0; m += 25 {
		path = append(path, at(m))
	}
	path = append(path, at(5), at(5), at(5), at(3), at(5))
	for m := 30.0; m <= 500; m += 25 {
		path = append(path, at(m))
	}
	if n := len(newTrack(path).passes(p, 0.05)); n != 1 {
		t.Errorf("a stop 5 m past the point: %d passes; want 1", n)
	}
}

// A leg ending by a toll point and the next going on the same way pass
// it once.
func TestLegEndingByAPoint(t *testing.T) {
	pt := [2]float64{10.132119, 59.119744}
	from := [2]float64{pt[0] - 0.05, pt[1] - 0.02}
	d := [2]float64{pt[0] - from[0], pt[1] - from[1]}
	km := haversine(from[1], from[0], pt[1], pt[0])
	on := func(m float64) [2]float64 { return [2]float64{pt[0] + d[0]*m/1000/km, pt[1] + d[1]*m/1000/km} }
	leg := func(p [][2]float64) sootcase.LegResult {
		return sootcase.LegResult{DistanceKm: 4, CountryKm: map[string]float64{"NO": 4}, Path: dense(p)}
	}
	for _, stop := range []float64{-30, 30} {
		r, err := Price(sootcase.Result{Legs: []sootcase.LegResult{leg([][2]float64{from, on(stop)}), leg([][2]float64{on(stop), on(2000)})}}, all(t),
			Request{Truck: truck40, CargoKg: 1000, Stops: []sootcase.Location{{Code: "A"}, {Code: "B"}, {Code: "C"}}, FX: map[string]float64{"NOK": 11.7}},
			time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		n := 0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Skinmo") {
				n++
			}
		}
		if n != 1 {
			t.Errorf("a stop %+.0f m from E18 Skinmo, going on the same way: %d passages; want 1", stop, n)
		}
	}
}

// Two records of one station at the same spot (Norway's FV 6612 Hofstad
// and NVDB 1025249143, 7 m apart), or the gantry of a road beside
// (Stockholm's Kristineberg by Essingeleden's), charge one passage.
func TestPointsAtTheSameSpot(t *testing.T) {
	set := all(t)
	pos := func(file, name string) [2]float64 {
		raw, _ := set.Raw(file)
		var d struct {
			Objects []struct {
				Name     string `json:"name"`
				Location struct {
					Geometry struct {
						Coordinates json.RawMessage `json:"coordinates"`
					} `json:"geometry"`
				} `json:"location"`
			} `json:"charge_objects"`
		}
		json.Unmarshal(raw, &d)
		for _, o := range d.Objects {
			if o.Name == name {
				var p [2]float64
				if json.Unmarshal(o.Location.Geometry.Coordinates, &p) != nil {
					var ps [][2]float64
					json.Unmarshal(o.Location.Geometry.Coordinates, &ps)
					p = ps[0]
				}
				return p
			}
		}
		t.Fatalf("%s: no %s", file, name)
		return [2]float64{}
	}
	count := func(cc string, p [2]float64, req Request, want int, what string) {
		// 60 m of road through it, northwards.
		path := dense([][2]float64{{p[0], p[1] - 0.0003}, p, {p[0], p[1] + 0.0003}})
		r, err := Price(sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 2, CountryKm: map[string]float64{cc: 2}, Path: path}}}, set, req,
			time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		n := 0
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.RateUnit != "" && strings.Contains(l.RateUnit, "passage") {
				n++
			}
		}
		if n != want {
			var ls []string
			for _, l := range r.Lines {
				ls = append(ls, l.Section+" "+l.RateUnit)
			}
			t.Errorf("%s: %d passages; want %d: %q", what, n, want, ls)
		}
	}
	count("NO", pos("no/no-2026-11-18.orct.json", "FV 6612 Hofstad"), Request{Truck: truck40, CargoKg: 1000, FX: map[string]float64{"NOK": 11.7}}, 1, "Hofstad")
	count("SE", pos("se/se-congestion-stockholm-2020-01-01.orct.json", "Essingeleden"), Request{Truck: truck40, CargoKg: 1000, Time: "08:00", FX: map[string]float64{"SEK": 11}}, 1, "Essingeleden")
}

// A barrier (a station priced to itself) by a stop, the trip going on the
// same way, is one ticket; there and back through it via the stop, two.
func TestBarrierByAStop(t *testing.T) {
	sb := storebaelt().Path
	mid := len(sb) / 2
	leg := func(p [][2]float64) sootcase.LegResult {
		return sootcase.LegResult{DistanceKm: 70, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"DK": 70}, Path: p}
	}
	tickets := func(legs ...sootcase.LegResult) int {
		stops := make([]sootcase.Location, len(legs)+1)
		r, err := Price(sootcase.Result{Legs: legs}, all(t), Request{Truck: truck40, CargoKg: 1000, Stops: stops}, time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		n := 0
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Storebælt") {
				n++
			}
		}
		return n
	}
	// The Storebælt plaza is on the Zealand side, at the path's third point.
	plaza := 0
	for i, p := range sb {
		if p == [2]float64{11.10879, 55.3498} {
			plaza = i
		}
	}
	if plaza == 0 {
		plaza = mid
	}
	for _, k := range []int{plaza - 3, plaza + 3} {
		if n := tickets(leg(sb[:k+1]), leg(sb[k:])); n != 1 {
			t.Errorf("a stop %d points from the plaza, going on: %d tickets; want 1", k-plaza, n)
		}
	}
	if n := tickets(leg(sb[:plaza+4]), leg(reversed(sb[:plaza+4]))); n != 2 {
		t.Errorf("there and back via a stop just past the plaza: %d tickets; want 2", n)
	}
}

// GPS fixes logged while parked add no km.
func TestParkedFixes(t *testing.T) {
	var path [][2]float64
	for m := 0.0; m <= 4000; m += 25 {
		path = append(path, [2]float64{9.0 + m/1000/(111.2*math.Cos(52*math.Pi/180)), 52.0})
	}
	rng := rand.New(rand.NewSource(1))
	stop := path[80]
	parked := [][2]float64{}
	for i := 0; i < 600; i++ { // 10 minutes at 1 Hz, about 2 m off
		parked = append(parked, [2]float64{stop[0] + rng.NormFloat64()*0.00003, stop[1] + rng.NormFloat64()*0.00002})
	}
	path = append(append(append([][2]float64{}, path[:81]...), parked...), path[81:]...)
	if km := pathKm(compactPath(path, parkedKm)); math.Abs(km-4) > 0.05 {
		t.Errorf("4 km with 10 minutes parked: %.2f km", km)
	}
}

// Two records of one name at one spot with different prices: the nearest,
// or the one that names its direction (Ring 3 Sinsenkrysset northbound,
// pt248 at 346.8°, not pt198 with none 9 m away).
func TestSameNameRecordsAtOneSpot(t *testing.T) {
	pt := [2]float64{10.781867, 59.940617}
	for _, deg := range []float64{346.8, 355, 5} {
		h := deg * math.Pi / 180
		// 80 m either side: not as far as the ramps' points.
		step := [2]float64{math.Sin(h) * 0.08 / (111.2 * math.Cos(59.94*math.Pi/180)), math.Cos(h) * 0.08 / 111.2}
		path := dense([][2]float64{{pt[0] - step[0], pt[1] - step[1]}, pt, {pt[0] + step[0], pt[1] + step[1]}})
		r, err := Price(sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 0.6, CountryKm: map[string]float64{"NO": 0.6}, Path: path}}}, all(t),
			Request{Truck: truck40, CargoKg: 1000, FX: map[string]float64{"NOK": 11.7}}, time.Date(2026, 11, 24, 12, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var got []string
		for _, l := range r.Lines {
			if strings.Contains(l.Section, "Ring 3 Sinsenkrysset") {
				got = append(got, fmt.Sprintf("%.0f", l.Amount))
			}
		}
		if len(got) != 1 || got[0] != "161" {
			var all []string
			for _, l := range r.Lines {
				all = append(all, fmt.Sprintf("%s %.0f", l.Section, l.Amount))
			}
			t.Errorf("Ring 3 Sinsenkrysset heading %g°: %q; want one passage at NOK 161 (%q)", deg, got, all)
		}
	}
}

// A driven path along a harbour road, past both terminals of a short
// crossing within reach, takes no ferry: Esbjerg 300 m east of the Fanø
// quay.
func TestNoPhantomFerry(t *testing.T) {
	bix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	east := 0.3 / (111.2 * math.Cos(55.46*math.Pi/180))
	path := dense([][2]float64{{8.44007 + east, 55.44}, {8.44007 + east, 55.485}})
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 5, CountryKm: map[string]float64{"DK": 5}, Path: [][2]float64{path[0], path[len(path)-1]}}}}
	ownPath(bix, &fd, &res, path)
	if f := res.Legs[0].RouteParts["ferry"]; f > 0 {
		t.Errorf("Esbjerg harbour road: %.1f ferry km; want none", f)
	}
}

// Driven paths on ferries: a ship calling at a port on the way keeps all
// of Sootcase's ferry part (Aberdeen to Lerwick via Kirkwall); a terminal
// placed a km or so off the quay still finds the crossing (Ios–Naxos).
func TestDrivenFerries(t *testing.T) {
	bix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	trip := func(path [][2]float64, ferryKm float64) sootcase.LegResult {
		res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: ferryKm + 2, TTWKg: 400, WTWKg: 480, CountryKm: map[string]float64{}, Path: [][2]float64{path[0], path[len(path)-1]},
			RouteParts: map[string]float64{"ferry": ferryKm, "road": 2},
			Parts:      []sootcase.Part{{Kind: "road", DistanceKm: 1}, {Kind: "ferry", DistanceKm: ferryKm, TTWKg: 380, WTWKg: 456}, {Kind: "road", DistanceKm: 1}}}}}
		ownPath(bix, &fd, &res, path)
		return res.Legs[0]
	}
	// Aberdeen quay, Kirkwall, Lerwick, the fixes a few km apart at sea.
	l := trip(dense([][2]float64{{-2.10, 57.145}, {-2.09175, 57.145287}, {-2.974082, 58.999691}, {-1.157663, 60.16292}, {-1.16, 60.17}}), 380)
	kg := 0.0
	for _, p := range l.Parts {
		kg += p.TTWKg
	}
	// Sootcase's 380 kg for its 380 km, by the path's ferry km.
	if want := 380 * l.RouteParts["ferry"] / 380; math.Abs(kg-want) > 1 {
		t.Errorf("Aberdeen–Kirkwall–Lerwick on a path: ferry TTW %.1f kg over %d parts; want %.1f", kg, len(l.Parts), want)
	}
	// From the quay the other Ios crossings share, 1.2 km from Ios–Naxos's
	// Ios, straight (fixes quay to quay) to Naxos.
	l = trip([][2]float64{{25.275, 36.722}, {25.272273, 36.723515}, {25.371443, 37.10619}, {25.375, 37.105}}, 43.5)
	if l.RouteParts["ferry"] < 40 {
		t.Errorf("Ios–Naxos on a path: %.1f ferry km; want about 43.5", l.RouteParts["ferry"])
	}
}

// The route's runs (for the map and the legs' sections) take the same
// crossings as the path's pricing: none along the Esbjerg harbour road.
func TestRouteRunsNoPhantomFerry(t *testing.T) {
	bix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	east := 0.3 / (111.2 * math.Cos(55.46*math.Pi/180))
	for _, r := range Route(bix, dense([][2]float64{{8.44007 + east, 55.44}, {8.44007 + east, 55.485}}), &fd) {
		if r.Kind == "ferry" {
			t.Errorf("Esbjerg harbour road: a ferry run of %.1f km", r.Km)
		}
	}
}

// On a Sootcase route, a ferry part is named for the crossing that fits
// it best, not one found first: Zadar–Preko, not Zadar–Ošljak (Ošljak is
// passed on the way).
func TestFerryPartBestFit(t *testing.T) {
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	path := dense([][2]float64{{15.26, 44.093}, {15.257666, 44.092329}, {15.194426, 44.076439}, {15.19, 44.074}})
	km := haversine(44.092329, 15.257666, 44.076439, 15.194426)
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: km + 1, Path: path, RouteParts: map[string]float64{"ferry": km},
		Parts: []sootcase.Part{{Kind: "ferry", DistanceKm: km, TTWKg: 38}}}}}
	ps := ferryParts(res, &fd, Request{})
	if len(ps) != 1 || ps[0].crossing == nil || ps[0].crossing.Name != "Zadar–Preko" {
		name := ""
		if len(ps) == 1 && ps[0].crossing != nil {
			name = ps[0].crossing.Name
		}
		t.Errorf("Zadar–Preko route: crossing %q", name)
	}
}

// A round trip on one crossing, out and back on two legs, is two ferry
// runs of the crossing's length, not one from a terminal on the way out
// to the other on the way back.
func TestRoundTripFerryRuns(t *testing.T) {
	bix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	out := cphHam.Legs[0]
	out.Path = dense([][2]float64{{12.57, 55.68}, {11.9, 55.0}, {11.3522, 54.6556}, {11.2275, 54.5003}, {10.7, 54.0}, {9.99, 53.55}})
	back := out
	back.Path = reversed(out.Path)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(sootcase.Result{TTWKg: 500, WTWKg: 600, Legs: []sootcase.LegResult{out, back}})
	}))
	defer srv.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL}, Tariffs: all(t), Borders: bix, Ferries: &fd}
	r, err := c.Calculate(context.Background(), Request{Stops: []sootcase.Location{{Code: "DKCPH"}, {Code: "DEHAM"}, {Code: "DKCPH"}}, Date: "2026-11-03",
		CargoKg: 10000, Truck: truck40})
	if err != nil {
		t.Fatal(err)
	}
	var ferry []float64
	for _, run := range r.Route {
		if run.Kind == "ferry" {
			ferry = append(ferry, run.Km)
		}
	}
	if len(ferry) != 2 || ferry[0] > 40 || ferry[1] > 40 {
		t.Errorf("CPH–HAM–CPH ferry runs %v km; want two of the crossing's length", ferry)
	}
}

// A fare table whose port is out on the ferry line (Samsø Rederi's Hou,
// 5.8 km from the terminal): its fare priced, the crossing isn't also
// missing.
func TestFarePortOnTheLine(t *testing.T) {
	r := ferryTrip(t, "2026-11-24", [2]float64{10.25911, 55.91246}, [2]float64{10.54889, 55.86433}, "DK", "DK", [2]float64{10.34828, 55.92655}, [2]float64{10.548473, 55.868734})
	fare := false
	for _, l := range r.Lines {
		fare = fare || l.Charge == FerryFare
	}
	if !fare || !r.Complete {
		t.Errorf("Hou–Sælvig along the line: fare %v, missing %+v", fare, r.Missing)
	}
}

// A crossing the driven path takes but Sootcase's route doesn't has no
// emissions here: the notes say so, not that a default factor is used or
// that the truck crosses empty.
func TestPathOnlyFerryNotes(t *testing.T) {
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	path := dense([][2]float64{{9.98, 57.59}, {9.97153, 57.593143}, {7.985934, 58.144283}, {7.99, 58.15}})
	km := haversine(57.593143, 9.97153, 58.144283, 7.985934)
	res := sootcase.Result{TTWKg: 10, WTWKg: 12, Legs: []sootcase.LegResult{{DistanceKm: km + 2, TTWKg: 10, WTWKg: 12, Path: path,
		CountryKm: map[string]float64{"DK": 1, "NO": 1}, RouteParts: map[string]float64{"ferry": km, "road": 2},
		Parts: []sootcase.Part{{Kind: "road", DistanceKm: 1}, {Kind: "ferry", DistanceKm: km}, {Kind: "road", DistanceKm: 1}}}}}
	r, err := PriceWith(res, all(t), &fd, Request{CargoKg: 20000, Truck: truck40, EUAEurPerT: 75, FX: map[string]float64{"NOK": 11.7, "DKK": 7.46}}, time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	notes := strings.Join(r.Notes, "\n")
	if strings.Contains(notes, "default ro-pax factor is used") || strings.Contains(notes, "empty") {
		t.Errorf("notes: %s", notes)
	}
}

// One Eurovignette day is valid in all its states: a trip through two of
// them on one day pays it once (Guichet.lu: the same e-vignette is valid
// on all the partner states' territories).
func TestEurovignetteOncePerDay(t *testing.T) {
	for _, c := range []struct {
		date string
		km   map[string]float64
	}{
		{"2024-06-03", map[string]float64{"DK": 30, "SE": 40}},
		{"2025-06-02", map[string]float64{"LU": 40, "NL": 150}},
	} {
		out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: c.km, Date: c.date,
			CargoKg: 10000, DieselL: 30, Truck: truck40, FX: map[string]float64{"DKK": 7.46, "SEK": 11.5}})
		if err != nil {
			t.Fatal(err)
		}
		var tolls []string
		for _, l := range out.Lines {
			if l.Charge == RoadToll {
				tolls = append(tolls, fmt.Sprintf("%s %.2f %s", l.Country, l.Amount, l.Currency))
			}
		}
		if len(tolls) != 1 || !out.Complete {
			t.Errorf("%s %v: road tolls %v (complete %v); want one day's Eurovignette", c.date, c.km, tolls, out.Complete)
		}
	}
	// Alone, each state still charges its day.
	out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: map[string]float64{"SE": 40}, Date: "2024-06-03",
		CargoKg: 10000, DieselL: 30, Truck: truck40, FX: map[string]float64{"SEK": 11.5}})
	if err != nil {
		t.Fatal(err)
	}
	if n := len(out.Lines); n == 0 || out.Lines[0].Charge != RoadToll {
		t.Errorf("SE alone: %+v", out.Lines)
	}
}

// ETS2 covers fuel released for consumption in the EU and the EEA's
// Iceland and Norway: none on fuel bought in Switzerland or the UK.
func TestETS2WhereFuelIsBought(t *testing.T) {
	for _, c := range []struct {
		km      map[string]float64
		country string
		want    float64
	}{
		{map[string]float64{"GB": 300}, "", 0},
		{map[string]float64{"DE": 300}, "CH", 0},
		{map[string]float64{"DE": 150, "CH": 150}, "", 0.5},
		{map[string]float64{"NO": 300}, "", 1},
	} {
		out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: c.km, FuelCountry: c.country, Date: "2028-03-01",
			CargoKg: 10000, DieselL: 100, ETS2EurPerT: 80, Truck: truck40, FX: map[string]float64{"GBP": 0.85, "CHF": 0.93, "NOK": 11.7}})
		if err != nil {
			t.Fatal(err)
		}
		got := 0.0
		for _, l := range out.Lines {
			if l.Charge == ETS2 {
				got += l.Amount
			}
		}
		if want := 100 * DieselKgCO2PerL / 1000 * 80 * c.want; math.Abs(got-want) > 0.02 {
			t.Errorf("%v fuel %q: ETS2 EUR %.2f, want %.2f", c.km, c.country, got, want)
		}
	}
}

// A surcharged stretch driven out and back, as two legs, is surcharged on
// both: Kufstein to Innsbruck/Amras on the A 12 and back.
func TestSurchargeOnEachLeg(t *testing.T) {
	pts := [][2]float64{{12.187, 47.607}, {12.1756, 47.5965}, {12.1408, 47.5675}, {12.0941, 47.5333}, {12.0572, 47.495}, {12.0235, 47.4838},
		{11.8842, 47.4411}, {11.8032, 47.4028}, {11.7016, 47.3577}, {11.6792, 47.3307}, {11.5838, 47.2998}, {11.5015, 47.2739},
		{11.4764, 47.271}, {11.4385, 47.2606}, {11.4202, 47.2547}}
	back := slices.Clone(pts)
	slices.Reverse(back)
	var km float64
	for i := 0; i+1 < len(pts); i++ {
		km += haversine(pts[i][1], pts[i][0], pts[i+1][1], pts[i+1][0])
	}
	leg := func(p [][2]float64) sootcase.LegResult {
		return sootcase.LegResult{DistanceKm: km, TTWKg: 50, CountryKm: map[string]float64{"AT": km}, Path: p}
	}
	res := sootcase.Result{TTWKg: 100, Legs: []sootcase.LegResult{leg(pts), leg(back)}}
	out, err := Price(res, all(t), Request{CargoKg: 1, Truck: truck40}, time.Date(2026, 11, 4, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	var infra, a12 float64
	for _, l := range out.Lines {
		if l.Component == rates.Infrastructure {
			if strings.Contains(l.Section, "A 12") {
				a12 += l.Km
			} else {
				infra += l.Km
			}
		}
	}
	if a12 < 1.8*km {
		t.Errorf("A 12 surcharge on %.1f km of %.1f there and back (infrastructure %.1f); want both legs", a12, 2*km, infra)
	}
}

// A crossing several lines sail stays on the ships' emissions, not one
// line's ETS surcharge: Tanger Med–Algeciras (DFDS and others, by
// OpenStreetMap), Dublin–Liverpool (Stena Line and Seatruck).
func TestSurchargeNotOnSharedCrossing(t *testing.T) {
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"Tanger Med–Algeciras", "Dublin–Liverpool"} {
		var c *ferries.Crossing
		for i := range fd.Crossings {
			if fd.Crossings[i].Name == name {
				c = &fd.Crossings[i]
			}
		}
		if c == nil {
			t.Fatalf("%s: no crossing", name)
		}
		if _, ok := fd.ETSSurcharge(c.ID, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)); !ok {
			t.Fatalf("%s: no surcharge to leave out", name)
		}
		var out Response
		done, err := ferrySurcharge(&out, &fd, *c, 30, Request{Truck: truck40}, time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC), func(Line) error { return nil })
		if err != nil {
			t.Fatal(err)
		}
		if done || !strings.Contains(strings.Join(out.Notes, " "), "more lines sail it") {
			t.Errorf("%s (%v): priced at one line's surcharge; notes %v", name, c.Lines(), out.Notes)
		}
	}
}

// An electric truck by country_km: its own kWh x Sootcase's grid factors,
// and without them its emissions are said not to be computed, not
// Sootcase's (which wasn't called).
func TestElectricTruckByCountryKm(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/factors" {
			t.Errorf("Sootcase called for %s", r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"fuels":[],"grids":[{"country":"DEU","year":2025,"g_per_kwh":330,"source":"Ember via Our World in Data: Germany"}]}`))
	}))
	defer srv.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL + "/kwh"}, Tariffs: all(t)}
	ev := truck40
	ev.CO2Class = 5
	req := Request{CountryKm: map[string]float64{"DE": 300}, Date: "2026-11-20", CargoKg: 10000, Truck: ev}
	r, err := c.Calculate(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	if r.DataType != "none" || !strings.HasPrefix(r.EmissionsBasis, "not computed") {
		t.Errorf("no kWh: %s: %s", r.DataType, r.EmissionsBasis)
	}
	req.ElectricityKWh = 300
	c.Sootcase.BaseURL = srv.URL
	if r, err = c.Calculate(context.Background(), req); err != nil {
		t.Fatal(err)
	}
	if r.DataType != "primary" || r.WTWKg != 99 {
		t.Errorf("300 kWh: %s %v: %s", r.DataType, r.WTWKg, r.EmissionsBasis)
	}
}

// A 24-hour vignette lasts 24 hours over the night the clocks go back:
// 24.5 hours in Lithuania from 10:00 on 24 October 2026 need two.
func TestRollingDayOverClocksBack(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 1715, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"LT": 1715}, RouteParts: map[string]float64{"road": 1715}}}}
	for _, day := range []int{17, 24} {
		req := Request{CargoKg: 10000, Truck: truck40, Time: "10:00", AvgSpeedKmh: 70, spans: map[string][][2]float64{"LT": {{0, 1715}}}}
		out, err := Price(res, all(t), req, time.Date(2026, 10, day, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		for _, l := range out.Lines {
			if l.Country == "LT" && l.Charge == RoadToll && l.Days != 2 {
				t.Errorf("from 10:00 on %d October: %d days, EUR %.2f; want 2", day, l.Days, l.Amount)
			}
		}
	}
}

// ETS2 is in the diesel price of the litres priced at a 2028 price, even
// when other litres have no price: with_fuel_eur doesn't count it twice.
func TestETS2InPriceOfPricedLitres(t *testing.T) {
	out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: map[string]float64{"DE": 400, "RS": 100}, Date: "2028-03-01",
		CargoKg: 10000, DieselL: 150, ETS2EurPerT: 100, DieselEURPerLByCountry: map[string]float64{"DE": 1.6}, Truck: truck40, FX: map[string]float64{"RSD": 117}})
	if err != nil {
		t.Fatal(err)
	}
	var ets2 float64
	for _, l := range out.Lines {
		if l.Charge == ETS2 {
			ets2 += l.AmountEUR
		}
	}
	if ets2 == 0 || out.Fuel == nil || math.Abs(out.Fuel.InPriceEUR-ets2) > 0.01 {
		t.Errorf("ETS2 EUR %.2f, in the price EUR %+v", ets2, out.Fuel)
	}
}

// By country_km, the notes and basis say why emissions aren't computed or
// come from EN 16258: the grid factor missing, Sootcase not asked.
func TestCountryKmEmissionsReasons(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"fuels":[],"grids":[{"country":"DEU","year":2025,"g_per_kwh":330,"source":"Ember via Our World in Data: Germany"}]}`))
	}))
	defer srv.Close()
	c := Calculator{Sootcase: sootcase.Client{BaseURL: srv.URL}, Tariffs: all(t)}
	ev := truck40
	ev.CO2Class = 5
	r, err := c.Calculate(context.Background(), Request{CountryKm: map[string]float64{"DE": 300, "AT": 100}, Date: "2026-11-20", CargoKg: 10000, Truck: ev, ElectricityKWh: 300})
	if err != nil {
		t.Fatal(err)
	}
	notes := strings.Join(r.Notes, "\n")
	if r.DataType != "none" || strings.Contains(r.EmissionsBasis, "need electricity_kwh") || strings.Contains(notes, "modelled ones") {
		t.Errorf("no AT grid: %s: %s\n%s", r.DataType, r.EmissionsBasis, notes)
	}
	if r, err = c.Calculate(context.Background(), Request{CountryKm: map[string]float64{"DE": 300}, Date: "2026-11-20", CargoKg: 10000, Truck: truck40, DieselL: 100}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(r.EmissionsBasis, "Sootcase gave no") {
		t.Errorf("diesel by country_km: %s", r.EmissionsBasis)
	}
}

// A Eurovignette state whose day another's covers isn't said to be priced
// at a day's rate.
func TestEurovignetteCoveredNote(t *testing.T) {
	out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: map[string]float64{"LU": 60, "SE": 620}, Date: "2026-11-20",
		CargoKg: 10000, DieselL: 300, Truck: truck40, FX: map[string]float64{"SEK": 11}})
	if err != nil {
		t.Fatal(err)
	}
	for _, n := range out.Notes {
		if strings.HasPrefix(n, "SE: a time-based charge, priced at one day's rate") {
			t.Errorf("SE, covered by LU's day: %q", n)
		}
	}
}

// Where a country's tolls are all crossings (Bosnia's motorway booths,
// Andorra's tunnel), it has tables: a route past none of them is
// complete, and country_km can't find them (no_route), not "no table".
func TestTollsThatAreCrossings(t *testing.T) {
	for _, cc := range []string{"AL", "AD", "BA", "FO"} {
		out, err := Calculator{Tariffs: all(t)}.Calculate(context.Background(), Request{CountryKm: map[string]float64{cc: 50}, Date: "2026-11-26",
			CargoKg: 10000, DieselL: 20, Truck: truck40, FX: map[string]float64{"BAM": 1.95583, "ALL": 97, "DKK": 7.46}})
		if err != nil {
			t.Fatal(err)
		}
		if len(out.NoRates) > 0 || len(out.Missing) != 1 || out.Missing[0].Reason != "no_route" {
			t.Errorf("%s by country_km: no_rates %v, missing %+v", cc, out.NoRates, out.Missing)
		}
	}
	// A path in Bosnia past no booth: nothing missing.
	path := dense([][2]float64{{17.80, 43.30}, {17.82, 43.32}})
	km := haversine(43.30, 17.80, 43.32, 17.82)
	res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{"BA": km}, RouteParts: map[string]float64{"road": km}}}}
	r, err := Price(res, all(t), Request{CargoKg: 1000, Truck: truck40, FX: map[string]float64{"BAM": 1.95583}}, time.Date(2026, 11, 26, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if len(r.NoRates) > 0 || !r.Complete {
		t.Errorf("BA path: no_rates %v, missing %+v", r.NoRates, r.Missing)
	}
}

// A station passed after midnight into the next version of its table is
// the same station there, whatever its id: Norway's numbers its stations
// (Minnesund - Hedmark grense is pt200 to 17 November 2026, pt66 from 18).
func TestNextVersionSameStation(t *testing.T) {
	path := dense([][2]float64{{11.215, 60.395}, {11.240759, 60.418983}, {11.26, 60.44}})
	var km float64
	for i := 0; i+1 < len(path); i++ {
		km += haversine(path[i][1], path[i][0], path[i+1][1], path[i+1][0])
	}
	res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{"NO": km}, RouteParts: map[string]float64{"road": km}}}}
	toll := func(at string, day int) float64 {
		req := Request{CargoKg: 1000, Truck: truck40, Time: at, AvgSpeedKmh: 70, origin: "NO", FX: map[string]float64{"NOK": 11.7}, spans: map[string][][2]float64{"NO": {{0, km}}}}
		r, err := PriceWith(res, all(t), nil, req, time.Date(2026, 11, day, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var nok float64
		for _, l := range r.Lines {
			if l.Charge == RoadToll && strings.Contains(l.Section, "Minnesund") {
				nok += l.Amount
			}
		}
		return nok
	}
	// Leaving at 23:58 on the 17th, it passes after midnight: the 18th's
	// table, at the station's own rate there.
	if after, own := toll("23:58", 17), toll("10:00", 18); after == 0 || after != own {
		t.Errorf("Minnesund after midnight: NOK %.0f; the 18th's own rate NOK %.0f", after, own)
	}
}

// Where a scheme turns from a vignette into a km charge at midnight (the
// Netherlands on 1 July 2026), the trip pays the vignette for its day
// before and the km charge on the km after.
func TestVignetteThenKmCharge(t *testing.T) {
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 140, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"NL": 140}, RouteParts: map[string]float64{"road": 140}}}}
	req := Request{CargoKg: 10000, Truck: truck40, Time: "23:30", AvgSpeedKmh: 70, origin: "NL", spans: map[string][][2]float64{"NL": {{0, 140}}}}
	r, err := PriceWith(res, all(t), nil, req, time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	var day, km float64
	for _, l := range r.Lines {
		switch {
		case l.Country == "NL" && l.Days > 0:
			day += l.Amount
		case l.Country == "NL" && l.Charge == RoadToll:
			km = math.Max(km, l.Km)
		}
	}
	if !r.Complete || day == 0 || math.Abs(km-105) > 2 {
		t.Errorf("NL from 23:30 on 30 June: vignette EUR %.2f, km charge on %.1f km (want 105); missing %+v", day, km, r.Missing)
	}
	// The vignette's line and note are its day's: 35 km, one day.
	for _, l := range r.Lines {
		if l.Country == "NL" && l.Days > 0 && math.Abs(l.Km-35) > 2 {
			t.Errorf("vignette on %.1f km; want the 35 km of its day", l.Km)
		}
	}
	if notes := strings.Join(r.Notes, "\n"); strings.Contains(notes, "on 2 calendar days") || strings.Contains(notes, "all 140.0 km") {
		t.Errorf("notes: %s", notes)
	}
	// Denmark's vignette to its km toll on 1 January 2025: the
	// environmental zones' km go to the km toll.
	dk := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 140, TTWKg: 50, WTWKg: 60, CountryKm: map[string]float64{"DK": 140}, RouteParts: map[string]float64{"road": 140}}}}
	req = Request{CargoKg: 10000, Truck: truck40, Time: "23:30", AvgSpeedKmh: 70, origin: "DK", EnvZoneKm: map[string]float64{"DK": 4}, spans: map[string][][2]float64{"DK": {{0, 140}}}}
	if r, err = PriceWith(dk, all(t), nil, req, time.Date(2024, 12, 31, 0, 0, 0, 0, time.UTC)); err != nil {
		t.Fatal(err)
	}
	env := false
	for _, l := range r.Lines {
		env = env || l.Country == "DK" && l.Km == 4
	}
	if !env || !r.Complete {
		t.Errorf("DK from 23:30 on 31 December 2024: no environmental zone line in %+v (missing %+v)", r.Lines, r.Missing)
	}
}

// A use that moves into a version charging nothing owes nothing:
// Romania's Danube bridge just after midnight on 30 September 2026.
func TestNoChargeNextVersion(t *testing.T) {
	path := dense([][2]float64{{28.00, 44.335}, {28.018083, 44.339525}, {28.04, 44.345}})
	km := haversine(44.335, 28.00, 44.345, 28.04)
	res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{"RO": km}, RouteParts: map[string]float64{"road": km}}}}
	req := Request{CargoKg: 1000, Truck: truck40, Time: "23:59", AvgSpeedKmh: 70, origin: "RO", FX: map[string]float64{"RON": 5}, spans: map[string][][2]float64{"RO": {{0, km}}}}
	r, err := PriceWith(res, all(t), nil, req, time.Date(2026, 9, 30, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, m := range r.Missing {
		if m.Reason == "unpriced" {
			t.Errorf("bridge after midnight: %+v", r.Missing)
		}
	}
	for _, l := range r.Lines {
		if strings.Contains(l.Section, "Danube") {
			t.Errorf("bridge after midnight charged: %+v", l)
		}
	}
}

// A station renamed in the next version ("A1 Pombal - Soure" to "A1
// Pombal – Soure"), its id the same, is still priced after midnight.
func TestNextVersionRenamedStation(t *testing.T) {
	path := dense([][2]float64{{-8.64, 39.97}, {-8.623918, 39.98436}, {-8.61, 40.0}})
	km := haversine(39.97, -8.64, 40.0, -8.61)
	res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{"PT": km}, RouteParts: map[string]float64{"road": km}}}}
	toll := func(at string, d time.Time) (float64, bool) {
		req := Request{CargoKg: 1000, Truck: truck40, Time: at, AvgSpeedKmh: 70, origin: "PT", spans: map[string][][2]float64{"PT": {{0, km}}}}
		r, err := PriceWith(res, all(t), nil, req, d)
		if err != nil {
			t.Fatal(err)
		}
		var eur float64
		for _, l := range r.Lines {
			if l.Charge == RoadToll {
				eur += l.Amount
			}
		}
		return eur, r.Complete
	}
	after, complete := toll("23:59", time.Date(2024, 12, 31, 0, 0, 0, 0, time.UTC))
	own, _ := toll("10:00", time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC))
	if !complete || after == 0 || after != own {
		t.Errorf("Pombal after midnight: EUR %.2f (complete %v); the next day EUR %.2f", after, complete, own)
	}
}

// A station passed on a later day than the trip's first is priced by its
// record of that day: Norway's Ranheim is pt1069 to 11 November 2026 and
// pt1070 from 12 November, each under its own dated charge.
func TestStationRecordOfItsDay(t *testing.T) {
	path := dense([][2]float64{{10.53, 63.42}, {10.554037, 63.422291}, {10.58, 63.425}})
	var km float64
	for i := 0; i+1 < len(path); i++ {
		km += haversine(path[i][1], path[i][0], path[i+1][1], path[i+1][0])
	}
	res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{"NO": km}, RouteParts: map[string]float64{"road": km}}}}
	toll := func(at string, day int) float64 {
		req := Request{CargoKg: 1000, Truck: truck40, Time: at, AvgSpeedKmh: 70, origin: "NO", FX: map[string]float64{"NOK": 11.7}, spans: map[string][][2]float64{"NO": {{0, km}}}}
		r, err := PriceWith(res, all(t), nil, req, time.Date(2026, 11, day, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		var nok float64
		for _, l := range r.Lines {
			if l.Charge == RoadToll {
				nok += l.Amount
			}
		}
		return nok
	}
	if after, own := toll("23:59", 11), toll("10:00", 12); own == 0 || after != own {
		t.Errorf("Ranheim just after midnight: NOK %.0f; on the 12th NOK %.0f", after, own)
	}
}

// A section the next version splits isn't priced as its first piece:
// Slovenia's Brezovica–Vrhnika (12.4 km) is Brezovica–Dragomer and more
// from 1 July 2025; just after midnight it's unpriced there, not 2.6 km.
func TestNextVersionSplitSection(t *testing.T) {
	path := dense([][2]float64{{14.46, 46.04}, {14.4322, 46.0253}, {14.3048, 45.968}, {14.29, 45.96}})
	var km float64
	for i := 0; i+1 < len(path); i++ {
		km += haversine(path[i][1], path[i][0], path[i+1][1], path[i+1][0])
	}
	res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{"SI": km}, RouteParts: map[string]float64{"road": km}}}}
	req := Request{CargoKg: 1000, Truck: truck40, Time: "23:59", AvgSpeedKmh: 70, origin: "SI", spans: map[string][][2]float64{"SI": {{0, km}}}}
	r, err := PriceWith(res, all(t), nil, req, time.Date(2025, 6, 30, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range r.Lines {
		if strings.Contains(l.Section, "Brezovica") && r.Complete {
			t.Errorf("split section after midnight priced as complete: %s EUR %.2f", l.Section, l.Amount)
		}
	}
}

// A use moved after midnight into the next version doesn't crash: an
// area's polygons aren't read as its points (London's Congestion Charge
// zone, its table ending on 1 January 2026), and a ticket priced under
// the next version's charge ids is noted by them (Spain's AP-7 Mazarrón
// to Las Palas, system3 from 2026; Turkey's YSS motorway, system17 from
// July 2026).
func TestNextVersionNoCrash(t *testing.T) {
	for _, c := range []struct {
		cc    string
		pts   [][2]float64
		day   time.Time
		cur   string
		perEU float64
	}{
		{"GB", [][2]float64{{-0.20, 51.51}, {-0.10, 51.51}, {0.0, 51.51}}, time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), "GBP", 0.85},
		{"ES", [][2]float64{{-1.38, 37.585}, {-1.336067, 37.599864}, {-1.178289, 37.647793}, {-1.15, 37.655}}, time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC), "", 0},
		{"TR", [][2]float64{{29.21, 41.19}, {29.202463, 41.19211}, {29.027875, 41.234945}, {29.02, 41.24}}, time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC), "TRY", 50},
	} {
		path := dense(c.pts)
		var km float64
		for i := 0; i+1 < len(path); i++ {
			km += haversine(path[i][1], path[i][0], path[i+1][1], path[i+1][0])
		}
		res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{c.cc: km}, RouteParts: map[string]float64{"road": km}}}}
		req := Request{CargoKg: 1000, Truck: truck40, Time: "23:55", AvgSpeedKmh: 70, origin: c.cc, spans: map[string][][2]float64{c.cc: {{0, km}}}}
		if c.cur != "" {
			req.FX = map[string]float64{c.cur: c.perEU}
		}
		if _, err := PriceWith(res, all(t), nil, req, c.day); err != nil {
			t.Errorf("%s: %v", c.cc, err)
		}
	}
}

// Around a table's last or first day: a ticket is priced by the table and
// the time at its entry, whatever day it exits (AP-36 entered at 23:35 on
// 31 December 2025, not free as at 00:00; the Basque A-15 entered before
// its table ends, its whole ticket); a crossing whose first table starts
// at midnight is priced when passed after it (AP-7 Calahonda).
func TestTicketsAndFirstTablesAtMidnight(t *testing.T) {
	toll := func(pts [][2]float64, day time.Time, at string) (float64, bool) {
		path := dense(pts)
		var km float64
		for i := 0; i+1 < len(path); i++ {
			km += haversine(path[i][1], path[i][0], path[i+1][1], path[i+1][0])
		}
		res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{"ES": km}, RouteParts: map[string]float64{"road": km}}}}
		req := Request{CargoKg: 1000, Truck: truck40, Time: at, AvgSpeedKmh: 70, origin: "ES", spans: map[string][][2]float64{"ES": {{0, km}}}}
		r, err := PriceWith(res, all(t), nil, req, day)
		if err != nil {
			t.Fatal(err)
		}
		var eur float64
		for _, l := range r.Lines {
			if l.Charge == RoadToll {
				eur += l.Amount
			}
		}
		return eur, r.Complete
	}
	for _, c := range []struct {
		name string
		pts  [][2]float64
		day  time.Time
		late string
		ref  string
	}{
		{"AP-36", [][2]float64{{-2.70, 39.47}, {-2.718178, 39.474381}, {-3.073759, 39.630588}, {-3.09, 39.635}}, time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC), "23:35", "12:00"},
		{"A-15", [][2]float64{{-2.215, 43.04}, {-2.206366, 43.045757}, {-2.18869, 43.047709}, {-2.102954, 43.100584}, {-2.091125, 43.114395}, {-2.085, 43.12}}, time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC), "23:52", "12:00"},
	} {
		late, complete := toll(c.pts, c.day, c.late)
		ref, _ := toll(c.pts, c.day, c.ref)
		if !complete || late == 0 || late != ref {
			t.Errorf("%s entered at %s: EUR %.2f (complete %v); at %s EUR %.2f", c.name, c.late, late, complete, c.ref, ref)
		}
	}
	cal := [][2]float64{{-4.74, 36.50}, {-4.717858, 36.505733}, {-4.70, 36.51}}
	late, complete := toll(cal, time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC), "23:59")
	ref, _ := toll(cal, time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), "00:01")
	if !complete || late == 0 || late != ref {
		t.Errorf("Calahonda just after midnight on its table's first day: EUR %.2f (complete %v); EUR %.2f the next minute", late, complete, ref)
	}
}

// A NaN or an infinity (a CSV's or a flag's) is refused, not priced.
func TestNonFiniteRefused(t *testing.T) {
	for _, req := range []Request{
		{CargoKg: 1000, Truck: truck40, TolledShare: map[string]float64{"DE": math.NaN()}},
		{CargoKg: 1000, Truck: truck40, AvgSpeedKmh: math.NaN()},
		{CargoKg: 1000, Truck: truck40, DriverEURPerH: math.Inf(1)},
		{CargoKg: math.NaN(), Truck: truck40},
	} {
		if err := check(req); err == nil || !strings.Contains(err.Error(), "not a finite number") {
			t.Errorf("%+v: %v", req, err)
		}
	}
	if err := check(Request{CargoKg: 1000, Truck: truck40, TolledShare: map[string]float64{"DE": 0.5}}); err != nil {
		t.Error(err)
	}
}

// A path that jumps across the map, or goes round it, is refused before
// it is indexed (each degree costs the index its cells).
func TestPathBounds(t *testing.T) {
	jump := [][2]float64{{-179, -89}, {179, 89}}
	var round [][2]float64
	for i := 0; i < 100; i++ {
		round = append(round, [2]float64{float64(i%2) * 10, 50})
	}
	for _, p := range [][][2]float64{jump, round} {
		if err := checkOwnRoute(Request{Path: p}); err == nil {
			t.Errorf("%d points: no error", len(p))
		}
	}
	if err := checkOwnRoute(Request{Path: [][2]float64{{9, 52}, {9.5, 52.3}, {10, 52}}}); err != nil {
		t.Error(err)
	}
}

// A day's maximum comes off that day's last passages, none below nothing:
// Stockholm's SEK 135, seven rush-hour passages of SEK 45.
func TestCongestionCapLines(t *testing.T) {
	sto := [][2]float64{{18.1034, 59.3130}, {18.1034, 59.3140}, {18.1034, 59.3150}}
	back := [][2]float64{sto[2], sto[1], sto[0]}
	var legs []sootcase.LegResult
	for i := 0; i < 7; i++ {
		p := sto
		if i%2 == 1 {
			p = back
		}
		legs = append(legs, sootcase.LegResult{DistanceKm: 0.2, CountryKm: map[string]float64{"SE": 0.2}, Path: p})
	}
	r, err := Price(sootcase.Result{Legs: legs}, all(t), Request{CargoKg: 1000, Truck: truck40, Time: "07:30", FX: map[string]float64{"SEK": 11}}, time.Date(2026, 5, 5, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	var sek float64
	for _, l := range r.Lines {
		if strings.Contains(l.Source, "trängselskatt") {
			sek += l.Amount
			if l.Amount < 0 {
				t.Errorf("line %s: SEK %.2f", l.Section, l.Amount)
			}
		}
	}
	if sek != 135 {
		t.Errorf("SEK %.2f, want the day's maximum 135", sek)
	}
}

// A use a ticket includes goes with the ticket's table across midnight:
// the Yavuz Sultan Selim bridge in the O-7 ticket (Turkey), not charged
// again by the next day's table.
func TestIncludedUseWithItsTicket(t *testing.T) {
	path := dense([][2]float64{{29.02, 41.2375}, {29.027875, 41.234945}, {29.111661, 41.202962}, {29.202463, 41.19211}, {29.21, 41.19}})
	var km float64
	for i := 0; i+1 < len(path); i++ {
		km += haversine(path[i][1], path[i][0], path[i+1][1], path[i+1][0])
	}
	res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{"TR": km}, RouteParts: map[string]float64{"road": km}}}}
	for _, c := range []struct {
		day time.Time
		at  string
	}{{time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC), "23:53"}, {time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC), "23:53"}, {time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC), "12:00"}} {
		req := Request{CargoKg: 1000, Truck: truck40, Time: c.at, AvgSpeedKmh: 70, origin: "TR", FX: map[string]float64{"TRY": 50}, spans: map[string][][2]float64{"TR": {{0, km}}}}
		r, err := PriceWith(res, all(t), nil, req, c.day)
		if err != nil {
			t.Fatal(err)
		}
		var paid []string
		for _, l := range r.Lines {
			if l.Charge == RoadToll && l.Amount > 0 {
				paid = append(paid, l.Section)
			}
		}
		if len(paid) != 1 {
			t.Errorf("%s %s: %q; want the O-7 ticket alone", c.day.Format(time.DateOnly), c.at, paid)
		}
	}
}

// With no toll table on the trip's day, its last or first table prices
// the uses on its own days and reports only those outside them: a route
// past none of Spain's state toll motorways misses none, before their
// first table or after their last; Italy's first table prices a trip
// reaching it after midnight.
func TestNoTableOnTheDay(t *testing.T) {
	priced := func(cc string, pts [][2]float64, day time.Time, at string) (*Response, float64) {
		path := dense(pts)
		var km float64
		for i := 0; i+1 < len(path); i++ {
			km += haversine(path[i][1], path[i][0], path[i+1][1], path[i+1][0])
		}
		res := sootcase.Result{TTWKg: 5, WTWKg: 6, Legs: []sootcase.LegResult{{DistanceKm: km, TTWKg: 5, WTWKg: 6, Path: path, CountryKm: map[string]float64{cc: km}, RouteParts: map[string]float64{"road": km}}}}
		req := Request{CargoKg: 1000, Truck: truck40, Time: at, AvgSpeedKmh: 70, origin: cc, spans: map[string][][2]float64{cc: {{0, km}}}}
		r, err := PriceWith(res, all(t), nil, req, day)
		if err != nil {
			t.Fatal(err)
		}
		var eur float64
		for _, l := range r.Lines {
			if l.Charge == RoadToll {
				eur += l.Amount
			}
		}
		return &r, eur
	}
	for _, day := range []time.Time{time.Date(2024, 6, 1, 0, 0, 0, 0, time.UTC), time.Date(2027, 1, 15, 0, 0, 0, 0, time.UTC)} {
		if r, _ := priced("ES", [][2]float64{{2.0, 41.5}, {1.5, 41.3}}, day, ""); slices.ContainsFunc(r.Missing, func(m Missing) bool { return strings.Contains(m.Name, "SEITT") }) {
			t.Errorf("ES off the SEITT roads on %s: missing %+v", day.Format(time.DateOnly), r.Missing)
		}
	}
	a1 := [][2]float64{{11.19187, 44.14234}, {11.19150, 44.13922}, {11.19156, 44.13688}, {11.19185, 44.13445}, {11.19230, 44.13252}, {11.19359, 44.12917}, {11.19467, 44.12720}, {11.19593, 44.12528}, {11.19760, 44.12325}, {11.20007, 44.12074}, {11.21426, 44.10865}, {11.21636, 44.10652}, {11.22021, 44.10219}, {11.22349, 44.09763}, {11.22840, 44.08950}, {11.23020, 44.08687}, {11.23555, 44.07763}, {11.23717, 44.07508}}
	r, late := priced("IT", a1, time.Date(2024, 12, 31, 0, 0, 0, 0, time.UTC), "23:59")
	_, own := priced("IT", a1, time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC), "00:01")
	// The km after midnight priced; the minute's before it, before the table.
	if late < 0.8*own || late >= own || len(r.Missing) != 1 || r.Missing[0].Reason != "before_table" {
		t.Errorf("IT from 23:59 on 31 December 2024: EUR %.2f (missing %+v); from 00:01 EUR %.2f", late, r.Missing, own)
	}
}

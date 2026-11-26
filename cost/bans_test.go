package cost

import (
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

func TestBans(t *testing.T) {
	sat := time.Date(2026, 11, 28, 0, 0, 0, 0, time.UTC)
	de := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 600, TTWKg: 960, WTWKg: 1200, CountryKm: map[string]float64{"DE": 600}}}}
	req := Request{CargoKg: 20000, Truck: truck40, Time: "20:00", origin: "DE"}
	// Saturday 20:00 at 70 km/h: still in Germany at midnight, when the
	// Sunday ban starts; it waits until 22:00.
	r, err := PriceWith(de, all(t), nil, req, sat)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Bans) != 1 || !r.Bans[0].Certain || r.Bans[0].WaitH != 22 || r.Trip.BanWaitH != 22 || !strings.HasPrefix(r.Bans[0].From, "2026-11-29T00:00:00+01:00") ||
		!slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "waits 22.0 h") && strings.Contains(n, "§ 30") }) {
		t.Fatalf("DE Sunday: %+v %q", r.Bans, r.Notes)
	}
	// Leaving Friday morning: none.
	if r, err = PriceWith(de, all(t), nil, Request{CargoKg: 20000, Truck: truck40, Time: "08:00", origin: "DE"}, sat.AddDate(0, 0, -1)); err != nil || len(r.Bans) != 0 {
		t.Errorf("Friday: %v %+v", err, r.Bans)
	}
	// No departure time: the trip may meet it.
	if r, err = PriceWith(de, all(t), nil, Request{CargoKg: 20000, Truck: truck40}, sat); err != nil || len(r.Bans) != 1 || r.Bans[0].Certain ||
		!slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "give the departure time") }) {
		t.Errorf("no time: %v %+v", err, r.Bans)
	}
	// A 7.5 t truck isn't covered.
	small := req
	small.Truck.MaxMassKg, small.Truck.Axles = 7500, 2
	if r, err = PriceWith(de, all(t), nil, small, sat); err != nil || len(r.Bans) != 0 {
		t.Errorf("7.5 t: %v %+v", err, r.Bans)
	}
	// A leg across Germany and Austria without Sootcase's country
	// sections: unordered, so it may run into them.
	deat := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 600, TTWKg: 960, WTWKg: 1200, CountryKm: map[string]float64{"DE": 300, "AT": 300}}}}
	if r, err = PriceWith(deat, all(t), nil, req, sat); err != nil || len(r.Bans) < 2 || r.Bans[0].Certain || r.Trip.BanWaitH != 0 {
		t.Errorf("DE-AT unordered: %v %+v", err, r.Bans)
	}
	// With its sections, the truck in Germany at midnight waits there until
	// 22:00 and reaches Austria after its Sunday ban.
	deat.Legs[0].CountrySections = []sootcase.CountrySection{{Country: "DE", FromKm: 0, ToKm: 300}, {Country: "AT", FromKm: 300, ToKm: 600}}
	if r, err = PriceWith(deat, all(t), nil, req, sat); err != nil || len(r.Bans) != 1 || r.Bans[0].Country != "DE" || r.Trip.BanWaitH != 22 {
		t.Errorf("DE-AT at 20:00: %v %+v", err, r.Bans)
	}
	// Leaving at 14:00: Austria from 18:17 on Saturday, banned until
	// midnight and then all Sunday until 22:00.
	early := req
	early.Time = "14:00"
	if r, err = PriceWith(deat, all(t), nil, early, sat); err != nil || len(r.Bans) != 2 || r.Bans[0].Country != "AT" || r.Bans[0].WaitH != 5.72 ||
		r.Bans[1].WaitH != 22 || r.Trip.BanWaitH != 27.72 {
		t.Errorf("DE-AT at 14:00: %v %+v", err, r.Bans)
	}
}

func TestHungarianWinterExemption(t *testing.T) {
	sat := time.Date(2026, 11, 28, 0, 0, 0, 0, time.UTC)
	// Budapest to Slovakia late on Saturday: Hungary's ban is in force
	// from 22:00.
	res := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 200, TTWKg: 320, WTWKg: 400, CountryKm: map[string]float64{"HU": 190, "SK": 10},
		CountrySections: []sootcase.CountrySection{{Country: "HU", FromKm: 0, ToKm: 190}, {Country: "SK", FromKm: 190, ToKm: 200}}}}}
	req := Request{CargoKg: 20000, Truck: truck40, Time: "23:00", origin: "HU", FX: map[string]float64{"HUF": 388.6}}
	req.Truck.Euro = 6
	r, err := PriceWith(res, all(t), nil, req, sat)
	if err != nil {
		t.Fatal(err)
	}
	if slices.ContainsFunc(r.Bans, func(b BanHit) bool { return b.Country == "HU" }) ||
		!slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "§ 2 (3)") }) {
		t.Errorf("Euro 6, international: %+v %q", r.Bans, r.Notes)
	}
	req.Truck.Euro = 2
	if r, err = PriceWith(res, all(t), nil, req, sat); err != nil || !slices.ContainsFunc(r.Bans, func(b BanHit) bool { return b.Country == "HU" && b.Certain && b.WaitH == 23 }) {
		t.Errorf("Euro 2: %v %+v", err, r.Bans)
	}
}

func TestListedRoadBan(t *testing.T) {
	// A Saturday in July in Germany: the Ferienreiseverordnung holds only
	// on the roads it lists, so the trip may run into it, without waiting.
	sat := time.Date(2026, 7, 11, 0, 0, 0, 0, time.UTC)
	de := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, TTWKg: 480, WTWKg: 600, CountryKm: map[string]float64{"DE": 300}}}}
	r, err := PriceWith(de, all(t), nil, Request{CargoKg: 20000, Truck: truck40, Time: "08:00", origin: "DE"}, sat)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Bans) != 1 || r.Bans[0].Certain || r.Trip.BanWaitH != 0 || !strings.Contains(r.Bans[0].Law, "Ferienreiseverordnung") {
		t.Errorf("%+v %v", r.Bans, r.Trip.BanWaitH)
	}
}

func TestCalendarYearMissing(t *testing.T) {
	it := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 300, TTWKg: 480, WTWKg: 600, CountryKm: map[string]float64{"IT": 300}}}}
	r, err := PriceWith(it, all(t), nil, Request{CargoKg: 20000, Truck: truck40, origin: "IT"}, time.Date(2027, 3, 7, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if !slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "IT's decree of bans for 2027 isn't in") }) {
		t.Errorf("%q", r.Notes)
	}
}

func TestRegionalHolidayWithRegions(t *testing.T) {
	// Reformation Day, Saturday 31 October 2026: kept in Schleswig-Holstein,
	// not in Bavaria. Leaving Friday 23:30, the truck is on the road at
	// midnight.
	fri := time.Date(2026, 10, 30, 0, 0, 0, 0, time.UTC)
	leg := func(region string) sootcase.Result {
		return sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 100, TTWKg: 160, WTWKg: 200, CountryKm: map[string]float64{"DE": 100},
			CountrySections: []sootcase.CountrySection{{Country: "DE", FromKm: 0, ToKm: 100, Regions: []sootcase.RegionSection{{Region: region, FromKm: 0, ToKm: 100}}}}}}}
	}
	req := Request{CargoKg: 20000, Truck: truck40, Time: "23:30", origin: "DE"}
	r, err := PriceWith(leg("DE-SH"), all(t), nil, req, fri)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Bans) != 1 || !r.Bans[0].Certain || r.Bans[0].WaitH != 22 || !strings.Contains(r.Bans[0].Holiday, "DE-SH") {
		t.Errorf("SH: %+v", r.Bans)
	}
	if r, err = PriceWith(leg("DE-BY"), all(t), nil, req, fri); err != nil || len(r.Bans) != 0 {
		t.Errorf("BY: %v %+v", err, r.Bans)
	}
}

func TestSpainListedRoads(t *testing.T) {
	// Wednesday 1 April 2026 (Semana Santa): the DGT restricts trucks over
	// 7.5 t on listed road sections. With the route's main roads, only
	// the A-3's sections are kept; without them, all, in one note.
	wed := time.Date(2026, 4, 1, 0, 0, 0, 0, time.UTC)
	leg := sootcase.LegResult{DistanceKm: 350, TTWKg: 560, WTWKg: 700, CountryKm: map[string]float64{"ES": 350},
		Summary: &sootcase.RouteSummary{Roads: []string{"A-3", "E 901"}}}
	req := Request{CargoKg: 20000, Truck: truck40, Time: "15:00", origin: "ES"}
	r, err := PriceWith(sootcase.Result{Legs: []sootcase.LegResult{leg}}, all(t), nil, req, wed)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Bans) != 2 {
		t.Fatalf("%+v", r.Bans)
	}
	for _, b := range r.Bans {
		if b.Certain || !b.Listed || !slices.Equal(b.Roads, []string{"A-3"}) || !strings.Contains(b.Law, "Dirección General de Tráfico") {
			t.Errorf("%+v", b)
		}
	}
	if !slices.ContainsFunc(r.Notes, func(n string) bool {
		return strings.Contains(n, "of ES's restrictions on listed roads") && strings.Contains(n, "(A-3, E 901)")
	}) {
		t.Errorf("%q", r.Notes)
	}
	leg.Summary = nil
	if r, err = PriceWith(sootcase.Result{Legs: []sootcase.LegResult{leg}}, all(t), nil, req, wed); err != nil {
		t.Fatal(err)
	}
	n := slices.IndexFunc(r.Notes, func(n string) bool { return strings.Contains(n, "may run into") && strings.Contains(n, "listed roads") })
	if len(r.Bans) < 20 || n < 0 || !strings.Contains(r.Notes[n], "and ") ||
		slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "(on the A-3 from") }) {
		t.Errorf("%d bans, %q", len(r.Bans), r.Notes)
	}
}

func TestLuxembourgTransit(t *testing.T) {
	// Saturday 14 November 2026, 22:00: Belgium, Luxembourg, then France
	// or Germany. Towards France the ban started at 21:30; towards Germany
	// it starts at 23:30, when the truck is out of Luxembourg.
	sat := time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	trip := func(next string) sootcase.Result {
		return sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 120, TTWKg: 190, WTWKg: 240,
			CountryKm:       map[string]float64{"BE": 50, "LU": 40, next: 30},
			CountrySections: []sootcase.CountrySection{{Country: "BE", FromKm: 0, ToKm: 50}, {Country: "LU", FromKm: 50, ToKm: 90}, {Country: next, FromKm: 90, ToKm: 120}}}}}
	}
	req := Request{CargoKg: 20000, Truck: truck40, Time: "21:00", origin: "BE"}
	r, err := PriceWith(trip("FR"), all(t), nil, req, sat)
	if err != nil {
		t.Fatal(err)
	}
	if !slices.ContainsFunc(r.Bans, func(b BanHit) bool { return b.Country == "LU" && b.Certain && strings.Contains(b.Ban, "France") }) {
		t.Errorf("to FR: %+v", r.Bans)
	}
	if r, err = PriceWith(trip("DE"), all(t), nil, req, sat); err != nil || slices.ContainsFunc(r.Bans, func(b BanHit) bool { return b.Country == "LU" }) {
		t.Errorf("to DE: %v %+v", err, r.Bans)
	}
	// Ending in Luxembourg: not transit.
	end := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 90, TTWKg: 150, WTWKg: 190, CountryKm: map[string]float64{"BE": 50, "LU": 40},
		CountrySections: []sootcase.CountrySection{{Country: "BE", FromKm: 0, ToKm: 50}, {Country: "LU", FromKm: 50, ToKm: 90}}}}}
	if r, err = PriceWith(end, all(t), nil, req, sat); err != nil || slices.ContainsFunc(r.Bans, func(b BanHit) bool { return b.Country == "LU" }) {
		t.Errorf("to LU: %v %+v", err, r.Bans)
	}
}

// A truck towing a trailer meets Austria's ban when the truck or the
// trailer is over 3.5 t: its own masses, or, without them, half the
// combination's at least.
func TestTrailerBanOnTheTrip(t *testing.T) {
	sun := time.Date(2026, 11, 22, 0, 0, 0, 0, time.UTC)
	at := sootcase.Result{Legs: []sootcase.LegResult{{DistanceKm: 200, TTWKg: 100, WTWKg: 120, CountryKm: map[string]float64{"AT": 200}}}}
	for _, tr := range []rates.Truck{
		{MaxMassKg: 7100, Axles: 4, MotorAxles: 2, MotorMassKg: 3500, TrailerMassKg: 3600, Euro: 6, CO2Class: 1},
		{MaxMassKg: 7100, Axles: 4, MotorAxles: 2, Euro: 6, CO2Class: 1},
		// A 3 t trailer: the truck is 4.5 t at least.
		{MaxMassKg: 7500, Axles: 4, MotorAxles: 2, TrailerMassKg: 3000, Euro: 6, CO2Class: 1},
		{MaxMassKg: 7500, Axles: 4, MotorAxles: 2, MotorMassKg: 3000, Euro: 6, CO2Class: 1},
	} {
		r, err := PriceWith(at, all(t), nil, Request{CargoKg: 2000, Truck: tr, Time: "10:00", origin: "AT"}, sun)
		if err != nil {
			t.Fatal(err)
		}
		if len(r.Bans) == 0 {
			t.Errorf("%+v on a Sunday in Austria: no ban", tr)
		}
	}
}

// The waits for driving bans move the times of the tolls after them:
// leaving Wörgl at 14:40 on a Saturday, the truck stands from 15:00 to
// Sunday 22:00, and drives the A 13 at night, at its night tariff.
func TestBanWaitMovesTolls(t *testing.T) {
	pts := [][2]float64{{12.0572, 47.495}, {12.0235, 47.4838}, {11.8842, 47.4411}, {11.8032, 47.4028}, {11.7016, 47.3577}, {11.6792, 47.3307},
		{11.5838, 47.2998}, {11.5015, 47.2739}, {11.4764, 47.271}, {11.4385, 47.2606}, {11.4202, 47.2547}, {11.3905, 47.2396}, {11.3934, 47.2276},
		{11.403, 47.2082}, {11.3982, 47.1841}, {11.4497, 47.1195}, {11.4801, 47.0615}, {11.5065, 47.0152}, {11.508, 47.003}}
	var km float64
	for i := 0; i+1 < len(pts); i++ {
		km += haversine(pts[i][1], pts[i][0], pts[i+1][1], pts[i+1][0])
	}
	res := sootcase.Result{TTWKg: 100, Legs: []sootcase.LegResult{{DistanceKm: km, CountryKm: map[string]float64{"AT": km}, Path: dense(pts)}}}
	a13 := func(day time.Time) (float64, *Response) {
		req := Request{CargoKg: 1, Truck: truck40, Time: "14:40", AvgSpeedKmh: 70, origin: "AT", spans: map[string][][2]float64{"AT": {{0, km}}}}
		out, err := PriceWith(res, all(t), nil, req, day)
		if err != nil {
			t.Fatal(err)
		}
		var eur float64
		for _, l := range out.Lines {
			if strings.HasPrefix(l.Section, "A 13") {
				eur += l.Amount
			}
		}
		return eur, &out
	}
	wed, _ := a13(time.Date(2026, 11, 25, 0, 0, 0, 0, time.UTC))
	sat, out := a13(time.Date(2026, 11, 28, 0, 0, 0, 0, time.UTC))
	if out.Trip.BanWaitH < 30 || wed == 0 || sat < 1.5*wed {
		t.Errorf("A 13: EUR %.2f on Wednesday afternoon, %.2f after the Saturday wait of %.1f h; want the night tariff", wed, sat, out.Trip.BanWaitH)
	}
}

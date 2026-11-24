package cost

import (
	"slices"
	"strings"
	"testing"
	"time"

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
	if !slices.ContainsFunc(r.Notes, func(n string) bool { return strings.Contains(n, "IT's calendar of bans for 2027 isn't in") }) {
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

package cost

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/fx"
	"github.com/majidkabir/carbon-cost/rates"
)

// With the ECB unreachable, a trip after the embedded days uses the last
// embedded day's rates and says so; a trip before them doesn't take
// today's rates for its own.
func TestFXWhenLiveRatesFail(t *testing.T) {
	_, last := fx.HistoryRange()
	day, err := time.Parse(time.DateOnly, last)
	if err != nil {
		t.Fatal(err)
	}
	down := func(context.Context) (fx.Rates, error) { return fx.Rates{}, errors.New("ECB unreachable") }
	c := Calculator{Tariffs: all(t), FX: down, FXOn: fx.OnDate, Now: func() time.Time { return day.AddDate(0, 0, 1) }}
	truck := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	out, err := c.Calculate(context.Background(), Request{CountryKm: map[string]float64{"CZ": 100}, CargoKg: 10000, Truck: truck})
	if err != nil {
		t.Fatalf("day after the embedded rates, ECB down: %v", err)
	}
	if !strings.Contains(strings.Join(out.Notes, "\n"), "the ECB's of "+last) {
		t.Errorf("no note on the rates of %s: %q", last, out.Notes)
	}
	today := func(context.Context) (fx.Rates, error) {
		return fx.Rates{Date: last, PerEUR: map[string]float64{"CZK": 25}}, nil
	}
	c = Calculator{Tariffs: all(t), FX: today, FXOn: fx.OnDate}
	if _, err := c.Calculate(context.Background(), Request{CountryKm: map[string]float64{"DE": 100}, CargoKg: 10000, Truck: truck,
		Date: "2023-06-01", Currency: "CZK"}); err == nil {
		t.Errorf("a trip of 2023-06-01 converted at today's rates; want no rate (give fx)")
	}
}

// With no date, the trip is on today where it starts: 00:30 in
// Copenhagen on 1 January is 1 January, though still 31 December in UTC.
func TestDefaultDateIsLocal(t *testing.T) {
	now := func() time.Time { return time.Date(2026, 12, 31, 23, 30, 0, 0, time.UTC) }
	c := Calculator{Tariffs: all(t), Now: now}
	truck := rates.Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}
	for cc, want := range map[string]string{"DK": "2027-01-01", "PT": "2026-12-31", "GB": "2026-12-31"} {
		out, err := c.Calculate(context.Background(), Request{CountryKm: map[string]float64{cc: 10}, CargoKg: 1000, Truck: truck,
			FX: map[string]float64{"DKK": 7.46, "GBP": 0.84}})
		if err != nil {
			t.Fatal(err)
		}
		if got := strings.Join(out.Provenance.Assumed, "; "); !strings.Contains(got, "today ("+want+")") {
			t.Errorf("%s at 23:30 UTC on 31 December: %s; want today (%s)", cc, got, want)
		}
	}
}

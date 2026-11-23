package fuel

import (
	"testing"
	"time"
)

func day(s string) time.Time { t, _ := time.Parse(time.DateOnly, s); return t }

func TestOn(t *testing.T) {
	// Germany, 16 November 2026: EUR 2,215 per 1,000 l with taxes, VAT 19%.
	b, latest, ok := On(day("2026-11-18"))
	if !ok || latest || b.Date != "2026-11-16" || b.EURPerL["DE"] != 1.8613 {
		t.Fatalf("2026-11-18: %v %v %v %v", b.Date, b.EURPerL["DE"], latest, ok)
	}
	// Spain cut VAT on fuel to 10% from 22 March 2026, back to 21% from 6 July.
	if b, _, _ := On(day("2026-07-06")); b.EURPerL["ES"] != 1.2686 {
		t.Errorf("ES 2026-07-06: %v", b.EURPerL["ES"])
	}
	if _, _, ok := On(day("2023-12-31")); ok {
		t.Error("before the first bulletin: want none")
	}
	if b, latest, ok := On(day("2030-01-01")); !ok || !latest || b.Date < "2026-11-16" {
		t.Errorf("a future day: %v %v %v", b.Date, latest, ok)
	}
	if b, _, _ := On(day("2026-11-16")); len(b.EURPerL) != 27 {
		t.Errorf("countries: %d", len(b.EURPerL))
	}
}

func TestRefunds(t *testing.T) {
	// Italy's excise on diesel: EUR 672.90 per 1,000 l from 1 January 2026,
	// 472.90 from 19 March; the refund is what is above 403.22.
	for _, c := range []struct {
		day  string
		want float64
	}{{"2026-01-07", 0.2697}, {"2026-03-25", 0.0697}, {"2026-07-08", 0.2697}, {"2026-08-05", 0.1297}} {
		r, ok := RefundOn("IT", day(c.day))
		if !ok || r.EURPerL != c.want || r.MinEuro != 5 || r.MinMassKg != 7500 {
			t.Errorf("IT %s: %v %+v", c.day, ok, r)
		}
	}
	// France: EUR 15.56/hl, set by law.
	if r, ok := RefundOn("FR", day("2026-11-18")); !ok || r.EURPerL != 0.1556 {
		t.Errorf("FR: %v %+v", ok, r)
	}
	if _, ok := RefundOn("DE", day("2026-11-18")); ok {
		t.Error("DE: want none")
	}
	if b, _, ok := DutiesOn(day("2026-11-18")); !ok || b.EURPerL["IT"] != 0.6329 {
		t.Errorf("duties: %v %v", ok, b.EURPerL["IT"])
	}
}

func TestSpainRefund(t *testing.T) {
	for _, c := range []struct {
		day  string
		want float64
	}{{"2025-05-05", 0.049}, {"2026-03-21", 0.049}, {"2026-03-22", 0}, {"2026-06-15", 0}, {"2026-08-01", 0}, {"2026-11-18", 0}, {"2027-02-01", 0.049}} {
		r, ok := RefundOn("ES", day(c.day))
		if !ok || r.EURPerL != c.want || r.MinMassKg != 7500 {
			t.Errorf("ES %s: %v %+v", c.day, ok, r)
		}
	}
}

func TestCroatiaRefund(t *testing.T) {
	// EUR 406.10 per 1,000 l in February 2026: 76.10 above the minimum;
	// none once the excise was cut to the minimum and below.
	if r, ok := RefundOn("HR", day("2026-02-25")); !ok || r.EURPerL != 0.0761 {
		t.Errorf("HR 2026-02-25: %v %+v", ok, r)
	}
	if r, ok := RefundOn("HR", day("2026-11-18")); !ok || r.EURPerL != 0 {
		t.Errorf("HR 2026-11-18: want zero: %v %+v", ok, r)
	}
}

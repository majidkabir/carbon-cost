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

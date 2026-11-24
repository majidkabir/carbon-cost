package fuel

import (
	"math"
	"testing"
	"time"
)

func TestNationalOn(t *testing.T) {
	for _, cc := range []string{"GB", "NO", "CH"} {
		n, _, ok := NationalOn(cc, time.Date(2026, 10, 15, 0, 0, 0, 0, time.UTC))
		if !ok || n.PerL <= 0 || n.VATPct <= 0 || n.Source == "" || NationalSources[cc][1] == "" {
			t.Errorf("%s: %+v %v", cc, n, ok)
		}
	}
	// Switzerland's October 2026 price, CHF 2.41 with 8.1% VAT.
	if n, latest, ok := NationalOn("CH", time.Date(2026, 10, 20, 0, 0, 0, 0, time.UTC)); !ok || latest || n.Date != "2026-10-01" || math.Abs(n.PerLExVAT()-2.41/1.081) > 1e-9 {
		t.Errorf("CH October: %+v latest %v", n, latest)
	}
	if _, _, ok := NationalOn("GB", time.Date(2023, 6, 1, 0, 0, 0, 0, time.UTC)); ok {
		t.Error("GB before the file")
	}
	if _, latest, ok := NationalOn("NO", time.Date(2027, 6, 1, 0, 0, 0, 0, time.UTC)); !ok || !latest {
		t.Error("NO past the file: latest")
	}
}

package ferries

import (
	"math"
	"testing"
)

func data(t *testing.T) Data {
	t.Helper()
	d, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	return d
}

// A road route over the Fehmarn Belt: points near both terminals.
var viaRodby = [][2]float64{{11.85, 55.0}, {11.355, 54.66}, {11.2276, 54.5001}, {10.9, 54.2}}

func TestDetect(t *testing.T) {
	d := data(t)
	if c, ok := d.Detect(viaRodby); !ok || c.ID != "rodby-puttgarden" {
		t.Errorf("via Rødby: got %q %v", c.ID, ok)
	}
	if _, ok := d.Detect([][2]float64{{11.355, 54.66}, {11.9, 55.2}}); ok {
		t.Error("only one terminal: want no crossing")
	}
	if c, ok := d.Detect([][2]float64{{11.93, 54.575}, {12.11, 54.156}}); !ok || c.ID != "gedser-rostock" {
		t.Errorf("Gedser-Rostock: got %q %v", c.ID, ok)
	}
}

// Rødby-Puttgarden from MRV 2025: the four ships' freight CO2e over their
// freight work, 18,595.15 t / 121,548,000 t·nm (rounded) = 136.53 g/t·nm.
func TestIntensity(t *testing.T) {
	d := data(t)
	c, _ := d.Detect(viaRodby)
	in, ok := d.Intensity(c, 2026)
	if !ok || in.Year.ReportingPeriod != 2025 || len(in.Ships) != 4 || math.Abs(in.GPerTNm-136.53) > 0.01 {
		t.Errorf("2026 trip: %.2f g from %d (%d ships), want 136.53 from 2025 (4 ships)", in.GPerTNm, in.Year.ReportingPeriod, len(in.Ships))
	}
	if in, _ := d.Intensity(c, 2025); in.Year.ReportingPeriod != 2024 {
		t.Errorf("2025 trip: MRV %d, want 2024", in.Year.ReportingPeriod)
	}
	if in, _ := d.Intensity(c, 2020); in.Year.ReportingPeriod != 2024 {
		t.Errorf("2020 trip: MRV %d, want the oldest year, 2024", in.Year.ReportingPeriod)
	}
}

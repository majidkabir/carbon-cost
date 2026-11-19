package ferries

import (
	"math"
	"strings"
	"testing"
	"time"
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

// The EU ETS share of the known crossings by law: ports in the EU/EEA,
// ships under 5,000 GT (not in the MRV reports though in service), and
// the island derogations of Implementing Decision (EU) 2023/2895.
func TestCoverage(t *testing.T) {
	d := data(t)
	byID := map[string]Crossing{}
	for _, c := range d.Crossings {
		byID[c.ID] = c
	}
	day := func(s string) time.Time { v, _ := time.Parse(time.DateOnly, s); return v }
	for _, tc := range []struct {
		id, day string
		share   float64
		basis   string
	}{
		{"rodby-puttgarden", "2026-11-20", 1, "Member States"},
		{"helsingor-helsingborg", "2026-11-20", 1, "Member States"},
		{"koge-ronne", "2024-03-01", 0, "2023/2895"},
		{"koge-ronne", "2030-12-31", 0, "2023/2895"},
		{"koge-ronne", "2031-01-01", 1, "Member States"},
		{"hou-saelvig", "2024-06-01", 1, "Member States"},
		{"hou-saelvig", "2025-01-01", 0, "2024/2924"},
		{"esbjerg-nordby", "2026-11-20", 0, "under 5000 GT"},
		{"bojden-fynshav", "2026-11-20", 1, "Member States"},
	} {
		c, ok := byID[tc.id]
		if !ok {
			t.Fatalf("no crossing %s", tc.id)
		}
		cov, ok := d.Coverage(c, day(tc.day))
		if !ok || cov.Share != tc.share || !strings.Contains(cov.Basis, tc.basis) {
			t.Errorf("%s on %s: %v %q, want %v (%s)", tc.id, tc.day, cov.Share, cov.Basis, tc.share, tc.basis)
		}
	}
	// One port outside the EU/EEA: half the emissions.
	c := Crossing{Name: "x", Terminals: []Point{{Country: "FR"}, {Country: "GB"}}}
	if cov, _ := d.Coverage(c, day("2026-01-01")); cov.Share != 0.5 {
		t.Errorf("FR-GB: %v, want 0.5", cov.Share)
	}
	// A ship newer than the MRV reports isn't taken as small.
	c = Crossing{Name: "y", Terminals: []Point{{Country: "DK"}, {Country: "DK"}}, Ships: []Ship{{Name: "NEW", Since: 2099}}}
	if cov, _ := d.Coverage(c, day("2026-01-01")); cov.Share != 1 {
		t.Errorf("new ship: %v, want 1", cov.Share)
	}
	// Each ship taken as under 5,000 GT really is missing from the
	// reports since it entered service, and each crossing's ports have a
	// country.
	for _, c := range d.Crossings {
		for _, s := range c.Ships {
			for _, y := range d.Listed {
				if s.Since > 0 && y.ReportingPeriod >= s.Since && y.lists(s) {
					t.Errorf("%s: %s is in the MRV report for %d", c.ID, s.Name, y.ReportingPeriod)
				}
			}
		}
		for _, p := range c.Terminals {
			if p.Country == "" {
				t.Errorf("%s: %s has no country", c.ID, p.Name)
			}
		}
	}
}

func TestDetectAll(t *testing.T) {
	d := data(t)
	// Rødby-Puttgarden from the south, then Helsingør-Helsingborg.
	route := [][2]float64{{10.9, 54.2}, {11.2276, 54.5001}, {11.355, 54.66}, {12.3, 55.6}, {12.61414, 56.03305}, {12.69152, 56.04331}}
	var ids []string
	for _, c := range d.DetectAll(route) {
		ids = append(ids, c.ID)
	}
	if strings.Join(ids, " ") != "rodby-puttgarden helsingor-helsingborg" {
		t.Errorf("got %v", ids)
	}
}

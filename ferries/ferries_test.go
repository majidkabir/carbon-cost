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
		{"hr-split-supetar", "2026-11-20", 0, "Croatia: Brač, Supetar"},
		{"virtsu-kuivastu", "2026-11-20", 0, "under 5000 GT"},
		{"hr-merag-valbiska", "2026-11-20", 0, "Croatia: Cres, Merag"},
		{"ystad-ronne", "2026-11-20", 1, "Member States"},
		{"sassnitz-ronne", "2026-11-20", 1, "Member States"},
		{"swinoujscie-ystad", "2026-11-20", 1, "Member States"},
		{"gdansk-nynashamn", "2026-11-20", 1, "Member States"},
		{"travemunde-trelleborg", "2026-11-20", 1, "Member States"},
		{"rostock-trelleborg", "2026-11-20", 1, "Member States"},
		{"gdynia-karlskrona", "2026-11-20", 1, "Member States"},
		{"hoek-van-holland-harwich", "2026-11-20", 0.5, "one outside"},
		{"belfast-cairnryan", "2026-11-20", 0, "outside the EU and the EEA"},
		{"travemunde-helsinki", "2026-11-20", 1, "Member States"},
		{"dover-calais", "2026-11-20", 0.5, "one outside"},
		{"aberdeen-lerwick", "2026-11-20", 0, "outside the EU and the EEA"},
		{"torshavn-hirtshals", "2026-11-20", 0.5, "one outside"},
		{"tanger-med-algeciras", "2026-11-20", 0.5, "one outside"},
		{"durres-bari", "2026-11-20", 0.5, "one outside"},
		{"klaipeda-karlshamn", "2026-11-20", 1, "Member States"},
		{"nynashamn-visby", "2026-11-20", 0, "Sweden: Gotland, Visby"},
		{"piombino-portoferraio", "2026-11-20", 0, "Italy: ISOLA D’ELBA, PORTOFERRAIO"},
		{"denia-eivissa", "2026-11-20", 0, "Spain: IBIZA, EIVISSA"},
		{"cirkewwa-mgarr", "2026-11-20", 0, "Malta: GOZO, MGARR"},
		{"barcelona-mao", "2031-01-01", 1, "Member States"},
		{"piraeus-chios", "2026-11-20", 0, "Greece: CHIOS, CHIOS"},
		{"igoumenitsa-lefkimmi", "2026-11-20", 0, "Greece: KERKYRA, LEFKIMI"},
		{"stinica-misnjak", "2026-11-20", 0, "Croatia: RAB, MIŠNJAK"},
		{"oskarshamn-visby", "2031-01-01", 1, "Member States"},
		{"paldiski-kapellskar", "2026-11-20", 1, "Member States"},
		{"tallinn-helsinki", "2026-11-20", 1, "Member States"},
		{"kiel-oslo", "2026-11-20", 1, "Member States"},
		{"odden-aarhus", "2026-11-20", 1, "Member States"},
		{"vaasa-umea", "2026-11-20", 1, "Member States"},
		{"stromstad-sandefjord", "2026-11-20", 1, "Member States"},
		{"hirtshals-kristiansand", "2026-11-20", 1, "Member States"},
		{"ijmuiden-newcastle", "2026-11-20", 0.5, "one outside"},
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
	// Corfu's town port isn't in the Decision's list (Lefkimmi is): no
	// Igoumenitsa–Corfu crossing under the derogation.
	for id := range byID {
		if strings.Contains(id, "corfu") {
			t.Errorf("crossing %s: Corfu's town port isn't under the island derogation", id)
		}
	}
	// A crossing whose ships aren't named says so.
	if cov, _ := d.Coverage(byID["portsmouth-caen"], day("2026-11-20")); !strings.Contains(cov.Note, "ships aren't known") {
		t.Errorf("portsmouth-caen note %q", cov.Note)
	}
	// The UK ETS: from 1 July 2026, half between Northern Ireland and
	// Great Britain, none on a Scottish ferry service; not between the UK
	// and France.
	for _, tc := range []struct {
		id, day string
		share   float64
		basis   string
	}{
		{"belfast-cairnryan", "2026-06-30", 0, "from 1 July 2026"},
		{"belfast-cairnryan", "2026-07-01", 0.5, "para 15(1)(a)"},
		{"belfast-liverpool", "2026-11-20", 0.5, "para 15(1)(a)"},
		{"aberdeen-lerwick", "2026-11-20", 0, "Scottish ferry service"},
		{"larne-cairnryan", "2026-11-20", 0.5, "para 15(1)(a)"},
	} {
		cov, ok := d.UKCoverage(byID[tc.id], day(tc.day))
		if !ok || cov.Share != tc.share || !strings.Contains(cov.Basis, tc.basis) {
			t.Errorf("UK ETS %s on %s: %v %q, want %v (%s)", tc.id, tc.day, cov.Share, cov.Basis, tc.share, tc.basis)
		}
	}
	// P&O Freight's page names Larne–Cairnryan's ships.
	if cov, _ := d.UKCoverage(byID["larne-cairnryan"], day("2026-11-20")); cov.Note != "" {
		t.Errorf("larne-cairnryan UK ETS note %q", cov.Note)
	}
	if _, ok := d.UKCoverage(byID["dover-calais"], day("2026-11-20")); ok {
		t.Error("UK ETS on Dover-Calais")
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

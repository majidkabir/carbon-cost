package site

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/majidkabir/carbon-cost/tariffs"
)

func testSite(t *testing.T) (*Site, http.Handler) {
	t.Helper()
	set, err := tariffs.Load()
	if err != nil {
		t.Fatal(err)
	}
	s, err := New(set, "https://example.org/carbon-cost", func() time.Time { return time.Date(2026, 11, 18, 10, 0, 0, 0, time.UTC) })
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	s.Register(mux)
	return s, mux
}

func get(t *testing.T, h http.Handler, path string) (int, string) {
	t.Helper()
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", path, nil))
	return rec.Code, rec.Body.String()
}

// TestDump writes the pages to $SITE_DUMP for a look.
func TestDump(t *testing.T) {
	dir := os.Getenv("SITE_DUMP")
	if dir == "" {
		t.Skip("SITE_DUMP not set")
	}
	s, _ := testSite(t)
	start := time.Now()
	b := s.get()
	t.Logf("built in %v", time.Since(start))
	for p, page := range b.pages {
		f := filepath.Join(dir, strings.TrimPrefix(p, "/"))
		if !strings.Contains(filepath.Base(f), ".") {
			f += ".html"
		}
		os.MkdirAll(filepath.Dir(f), 0o755)
		os.WriteFile(f, page, 0o644)
	}
	for p := range b.cards {
		img, _ := s.image(b, p)
		f := filepath.Join(dir, strings.TrimPrefix(p, "/")+".png")
		os.MkdirAll(filepath.Dir(f), 0o755)
		os.WriteFile(f, img, 0o644)
	}
}

func TestPages(t *testing.T) {
	_, h := testSite(t)
	code, de := get(t, h, "/tolls/de")
	if code != 200 {
		t.Fatalf("/tolls/de: %d", code)
	}
	for _, want := range []string{
		`<link rel="canonical" href="https://example.org/carbon-cost/tolls/de">`,
		`<meta name="description" content="Germany truck toll 2026 (Lkw-Maut): a 40 t Euro VI truck pays €0.348 per km (CO2 part 45%).`,
		`"@type":"Dataset"`, `"contentUrl":"https://example.org/carbon-cost/v1/rates/de/de-2024-07-01.orct.json"`,
		`<meta property="og:image" content="https://example.org/carbon-cost/tolls/de.png">`,
		"Germany truck toll 2026 (Lkw-Maut): rates per km by weight, Euro and CO2 class",
		// 100 km at the 2024 rates (BFStrMG Anlage 1): 15.50 + 2.30 + 1.20 + 15.80.
		"pays €34.80: infrastructure €15.50, air pollution €2.30, noise €1.20, CO2 €15.80.",
		"pay no toll until 30 June 2031",
		`href="/carbon-cost/?from=53.551,9.994&amp;from_name=Hamburg&amp;to=48.137,11.576&amp;to_name=Munich"`,
		"BFStrMG",
	} {
		if !strings.Contains(de, want) {
			t.Errorf("/tolls/de lacks %q", want)
		}
	}
	code, ov := get(t, h, "/tolls")
	if code != 200 || !strings.Contains(ov, `<a href="/carbon-cost/tolls/de">Germany</a>`) || !strings.Contains(ov, "Free until 2031") {
		t.Errorf("/tolls: %d, lacks Germany's row", code)
	}
	for _, p := range []string{"/tolls/zero-emission-trucks", "/tolls/ets2-diesel", "/tolls/co2-tax-diesel", "/tolls/fr", "/tolls/hr", "/tolls/no", "/tolls/gb"} {
		if code, body := get(t, h, p); code != 200 || !strings.Contains(body, `<link rel="canonical" href="https://example.org/carbon-cost`+p+`">`) {
			t.Errorf("%s: %d", p, code)
		}
	}
	if _, ets := get(t, h, "/tolls/ets2-diesel"); !strings.Contains(ets, "€0.1201") {
		t.Errorf("ets2: €45/t × 2.67 kg/l = €0.1201 per litre not shown")
	}
	if code, _ := get(t, h, "/tolls/xx"); code != 404 {
		t.Errorf("/tolls/xx: %d", code)
	}
	code, img := get(t, h, "/tolls/de.png")
	if code != 200 || !strings.HasPrefix(img, "\x89PNG") {
		t.Errorf("/tolls/de.png: %d", code)
	}
	if code, img := get(t, h, "/tolls.png"); code != 200 || !strings.HasPrefix(img, "\x89PNG") {
		t.Errorf("/tolls.png: %d", code)
	}
	_, sm := get(t, h, "/sitemap.xml")
	for _, want := range []string{"<loc>https://example.org/carbon-cost/tolls/de</loc>", "<loc>https://example.org/carbon-cost/tolls</loc>", "<loc>https://example.org/carbon-cost/</loc>"} {
		if !strings.Contains(sm, want) {
			t.Errorf("sitemap lacks %s", want)
		}
	}
	if _, rb := get(t, h, "/robots.txt"); !strings.Contains(rb, "Sitemap: https://example.org/carbon-cost/sitemap.xml") {
		t.Errorf("robots.txt: %s", rb)
	}
}

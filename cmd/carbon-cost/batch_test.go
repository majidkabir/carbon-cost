package main

import (
	"bytes"
	"context"
	"encoding/csv"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/majidkabir/carbon-cost/sootcase"
)

// fakeRoute answers Sootcase's calculate with 100 km in Germany, Hamburg
// to Berlin.
func fakeRoute(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/calculate" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.Write([]byte(`{"legs":[{"distance_km":100,"ttw_kg":80,"wtw_kg":100,"country_km":{"DE":100},"path":[[53.55,9.99],[52.52,13.40]]}],"ttw_kg":80,"wtw_kg":100}`))
	}))
}

func TestBatchHandler(t *testing.T) {
	fake := fakeRoute(t)
	defer fake.Close()
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, "none")
	trip := `{"from": {"code": "DEHAM"}, "to": {"code": "DEBER"}, "date": "2026-11-03", "cargo_kg": 20000, "truck": {"max_mass_kg": 40000, "axles": 5, "euro": 6, "co2_class": %d}}`
	body := `{"trips": [` + strings.Replace(trip, "%d", "1", 1) + `, ` + strings.Replace(trip, "%d", "9", 1) + `]}`
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost/batch", strings.NewReader(body)))
	if rec.Code != 200 {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
	var out BatchResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	// DE: 100 km x (0.155 + 0.023 + 0.012 + 0.158) EUR = 34.80 EUR of toll.
	if len(out.Results) != 2 || out.Results[0].Result == nil || out.Results[0].Result.TotalEUR < 34.8 || !out.Results[0].Result.Complete {
		t.Errorf("trip 1: %+v", out.Results)
	}
	if out.Results[1].Result != nil || !strings.Contains(out.Results[1].Error, "co2_class") {
		t.Errorf("trip 2: %+v", out.Results[1])
	}
	for _, tc := range []struct{ body, want string }{
		{`{"trips": []}`, "give 1 to 100"},
		{`{"trips": [{"nope": 1}]}`, "bad JSON"},
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost/batch", strings.NewReader(tc.body)))
		if rec.Code != 400 || !strings.Contains(rec.Body.String(), tc.want) {
			t.Errorf("%s: %d %s", tc.body, rec.Code, rec.Body.String())
		}
	}
}

func TestCalcCSV(t *testing.T) {
	fake := fakeRoute(t)
	defer fake.Close()
	in := filepath.Join(t.TempDir(), "trips.csv")
	os.WriteFile(in, []byte("from,to,date,co2-class,ref\nDEHAM,DEBER,2026-11-03,1,T1\nDEHAM,DEBER,2026-11-03,9,T2\nDEHAM,,2026-11-03,1,T3\n"), 0o644)
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	r, w, _ := os.Pipe()
	stdout := os.Stdout
	os.Stdout = w
	err = calcCSV(c, []string{"-cargo-kg", "20000", "-csv", in}, in)
	w.Close()
	os.Stdout = stdout
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(r)
	lines := strings.Split(strings.TrimSpace(string(b)), "\n")
	// ref names no flag: a label, kept as it is.
	if len(lines) != 4 || !strings.HasPrefix(lines[0], "from,to,date,co2-class,ref,trip_date,distance_km,country_km,total_eur") || !strings.HasPrefix(lines[1], "DEHAM,DEBER,2026-11-03,1,T1,") {
		t.Fatalf("output:\n%s", b)
	}
	if !strings.Contains(lines[1], ",DE=100.0,") || !strings.Contains(lines[1], ",true,") {
		t.Errorf("row 1: %s", lines[1])
	}
	if !strings.Contains(lines[2], "co2_class") {
		t.Errorf("row 2 (class 9): %s", lines[2])
	}
	if !strings.Contains(lines[3], "-to") {
		t.Errorf("row 3 (no destination): %s", lines[3])
	}
}

// POST /v1/carbon-cost/csv prices a CSV as calc -csv does, but no flag
// that reads a file or names a server.
func TestCSVHandler(t *testing.T) {
	fake := fakeRoute(t)
	defer fake.Close()
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	h := Handler(c, "none")
	body := "\ufefffrom,to,date,cargo-kg,ref,path,sootcase\nDEHAM,DEBER,2026-11-03,20000,T1,/etc/passwd,http://169.254.169.254\nDEHAM,DEBER,2026-11-03,x,T2,,\n"
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost/csv", strings.NewReader(body)))
	if rec.Code != 200 || rec.Header().Get("Content-Type") != "text/csv; charset=utf-8" || rec.Header().Get("X-CSV-Labels") != "ref,path,sootcase" {
		t.Fatalf("%d %v %s", rec.Code, rec.Header(), rec.Body.String())
	}
	lines := strings.Split(strings.TrimSpace(rec.Body.String()), "\n")
	if len(lines) != 3 || !strings.HasPrefix(lines[0], "from,to,date,cargo-kg,ref,path,sootcase,trip_date") ||
		!strings.Contains(lines[1], ",T1,/etc/passwd,") || !strings.HasSuffix(lines[1], "true,,") || !strings.Contains(lines[2], "cargo-kg") {
		t.Errorf("%q", lines)
	}
	big := "from,to\n" + strings.Repeat("DEHAM,DEBER\n", MaxBatch+1)
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("POST", "/v1/carbon-cost/csv", strings.NewReader(big)))
	if rec.Code != 400 || !strings.Contains(rec.Body.String(), "at most 100 rows") {
		t.Errorf("%d rows: %d %s", MaxBatch+1, rec.Code, rec.Body.String())
	}
}

// -shipment-rows gives a row per shipment, and report adds rows up by
// customer and month.
func TestShipmentRowsAndReport(t *testing.T) {
	fake := fakeRoute(t)
	defer fake.Close()
	c, err := calculator(&sootcase.Client{BaseURL: fake.URL})
	if err != nil {
		t.Fatal(err)
	}
	in := "from,to,date,shipments,customer\n" +
		"DEHAM,DEBER,2026-11-03,A:12000:0-1;B:6000:0-1,Acme\n" +
		"DEHAM,DEBER,2026-12-01,,Acme\n" +
		"DEHAM,DEBER,2026-11-20,,Bolt\n"
	var priced bytes.Buffer
	if _, err := priceCSV(context.Background(), c.Calculate, []string{"-cargo-kg", "10000"}, strings.NewReader(in), &priced, calcFlagNames(), 0, true); err != nil {
		t.Fatal(err)
	}
	rows, err := csv.NewReader(strings.NewReader(priced.String())).ReadAll()
	if err != nil {
		t.Fatal(err)
	}
	col := map[string]int{}
	for i, h := range rows[0] {
		col[h] = i
	}
	if len(rows) != 5 || rows[1][col["shipment_id"]] != "A" || rows[2][col["shipment_id"]] != "B" || rows[3][col["shipment_id"]] != "" {
		t.Fatalf("rows:\n%s", priced.String())
	}
	num := func(r []string, c string) float64 { v, _ := strconv.ParseFloat(r[col[c]], 64); return v }
	// A carries twice B's weight over the same km: twice its tonne-km, CO2e and charges.
	if a, b := num(rows[1], "tkm"), num(rows[2], "tkm"); a == 0 || math.Abs(a-2*b) > 0.2 {
		t.Errorf("tkm A %v, B %v", a, b)
	}
	if a, b := num(rows[1], "total_eur"), num(rows[2], "total_eur"); a == 0 || math.Abs(a-2*b) > 0.02 {
		t.Errorf("EUR A %v, B %v", a, b)
	}
	if rows[1][col["eur_by_country"]] == "" || rows[3][col["eur_by_country"]] == "" {
		t.Errorf("eur_by_country: %q, %q", rows[1][col["eur_by_country"]], rows[3][col["eur_by_country"]])
	}
	var rep bytes.Buffer
	if err := summarize([]io.Reader{strings.NewReader(priced.String())}, &rep, []string{"customer", "month"}); err != nil {
		t.Fatal(err)
	}
	r, _ := csv.NewReader(strings.NewReader(rep.String())).ReadAll()
	rc := map[string]int{}
	for i, h := range r[0] {
		rc[h] = i
	}
	if len(r) != 4 || r[1][0] != "Acme" || r[1][1] != "2026-11" || r[1][rc["rows"]] != "2" || r[1][rc["shipments"]] != "2" || r[3][0] != "Bolt" {
		t.Fatalf("report:\n%s", rep.String())
	}
	sum := num(rows[1], "wtw_kg") + num(rows[2], "wtw_kg")
	if got, _ := strconv.ParseFloat(r[1][rc["wtw_kg"]], 64); math.Abs(got-sum) > 0.2 {
		t.Errorf("Acme 2026-11 wtw %v, want %v", got, sum)
	}
	if r[1][rc["g_co2e_per_tkm"]] == "" || r[1][rc["primary_tkm_share"]] != "0.000" {
		t.Errorf("Acme 2026-11: %v", r[1])
	}
	if err := summarize([]io.Reader{strings.NewReader(priced.String())}, &rep, []string{"depot"}); err == nil || !strings.Contains(err.Error(), "depot") {
		t.Errorf("unknown column: %v", err)
	}
	if err := summarize([]io.Reader{strings.NewReader("from,to\nA,B\n")}, &rep, nil); err == nil {
		t.Error("an unpriced CSV: want an error")
	}
}

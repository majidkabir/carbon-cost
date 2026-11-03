// Command mrvferries extracts the ro-pax ships from the EU MRV public
// emission report (Regulation (EU) 2015/757, published by EMSA in
// THETIS-MRV) into a JSON file: per ship, the CO2 assigned to freight
// transport and the freight transport work, from which the freight
// intensity per tonne-nautical-mile follows.
//
//	go run ./tools/mrvferries -fetch -year 2025 -out ferries/data/mrv-ropax-2025.json
//
// Without -fetch it reads -in, the "EU MRV Publication of information"
// workbook from https://mrv.emsa.europa.eu/#public/emission-report.
package main

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"encoding/xml"
	"flag"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

const api = "https://mrv.emsa.europa.eu/api/public-emission-report"

// Ship is one ro-pax ship's yearly MRV report, freight part.
type Ship struct {
	IMO     string `json:"imo"`
	Name    string `json:"name"`
	Company string `json:"company,omitempty"`
	// FreightCO2T is the CO2 (CO2e where reported) assigned to freight
	// transport, tonnes.
	FreightCO2T float64 `json:"freight_co2_t"`
	// FreightWorkTNm is the freight transport work, tonne-nautical miles.
	FreightWorkTNm float64 `json:"freight_work_t_nm,omitempty"`
	// GPerTNm is the reported annual average CO2 per freight transport
	// work, g per tonne-nautical mile.
	GPerTNm float64 `json:"g_per_t_nm"`
}

// File is the output.
type File struct {
	Source          string `json:"source"`
	ReportingPeriod int    `json:"reporting_period"`
	Version         string `json:"version"`
	Ships           []Ship `json:"ships"`
}

func main() {
	fetch := flag.Bool("fetch", false, "download the workbook from EMSA")
	year := flag.Int("year", time.Now().Year()-1, "reporting period")
	in := flag.String("in", "", "workbook (without -fetch)")
	out := flag.String("out", "", "output JSON")
	flag.Parse()

	var raw []byte
	version := "local file"
	var err error
	if *fetch {
		raw, version, err = download(*year)
	} else {
		raw, err = os.ReadFile(*in)
	}
	if err != nil {
		log.Fatal(err)
	}
	rows, err := firstSheet(raw)
	if err != nil {
		log.Fatal(err)
	}
	ships, err := ropax(rows)
	if err != nil {
		log.Fatal(err)
	}
	f := File{Source: "EU MRV public emission report (EMSA THETIS-MRV), Regulation (EU) 2015/757 Art. 21",
		ReportingPeriod: *year, Version: version, Ships: ships}
	b, _ := json.MarshalIndent(f, "", " ")
	if *out == "" {
		os.Stdout.Write(b)
		return
	}
	if err := os.WriteFile(*out, append(b, '\n'), 0o644); err != nil {
		log.Fatal(err)
	}
	log.Printf("%d ro-pax ships -> %s", len(ships), *out)
}

func download(year int) ([]byte, string, error) {
	c := &http.Client{Timeout: 5 * time.Minute}
	get := func(u string) ([]byte, error) {
		resp, err := c.Get(u)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("%s: HTTP %d", u, resp.StatusCode)
		}
		return io.ReadAll(io.LimitReader(resp.Body, 200<<20))
	}
	b, err := get(api + "/downloadable-files")
	if err != nil {
		return nil, "", err
	}
	var list struct {
		Results []struct {
			ReportingPeriod int    `json:"reportingPeriod"`
			Version         int    `json:"version"`
			GenerationDate  string `json:"generationDate"`
		} `json:"results"`
	}
	if err := json.Unmarshal(b, &list); err != nil {
		return nil, "", fmt.Errorf("downloadable files: %w", err)
	}
	for _, r := range list.Results {
		if r.ReportingPeriod == year {
			data, err := get(fmt.Sprintf("%s/reporting-period-document/binary/%d/%d", api, year, r.Version))
			return data, fmt.Sprintf("version %d of %s", r.Version, strings.Fields(r.GenerationDate + " ?")[0]), err
		}
	}
	return nil, "", fmt.Errorf("no MRV publication for %d", year)
}

// ropax picks the ro-pax rows. The sheet has title rows, then a header
// row starting with "IMO Number".
func ropax(rows [][]string) ([]Ship, error) {
	h := -1
	for i, r := range rows {
		if len(r) > 0 && strings.TrimSpace(r[0]) == "IMO Number" {
			h = i
			break
		}
	}
	if h < 0 {
		return nil, fmt.Errorf("no header row")
	}
	for i, name := range rows[h] {
		if l := strings.ToLower(name); strings.Contains(l, "freight") || strings.Contains(l, "transport work") || strings.Contains(l, "company") {
			log.Printf("column %d: %q", i, name)
		}
	}
	col := func(prefixes ...string) int {
		for _, p := range prefixes {
			for i, name := range rows[h] {
				if strings.HasPrefix(strings.TrimSpace(name), p) {
					return i
				}
			}
		}
		return -1
	}
	cIMO, cName, cType, cComp := col("IMO Number"), col("Name"), col("Ship type"), col("Company name", "Company")
	cCO2 := col("CO₂eq emissions assigned to Freight transport", "CO₂ emissions assigned to Freight transport")
	cInt := col("Annual average CO₂eq emissions per transport work (freight)", "Annual average CO₂ emissions per transport work (freight)")
	if cIMO < 0 || cName < 0 || cType < 0 || cCO2 < 0 || cInt < 0 {
		return nil, fmt.Errorf("missing columns in header %q", rows[h])
	}
	get := func(r []string, c int) string {
		if c < 0 || c >= len(r) {
			return ""
		}
		return strings.TrimSpace(r[c])
	}
	var out []Ship
	for _, r := range rows[h+1:] {
		if !strings.EqualFold(get(r, cType), "Ro-pax ship") {
			continue
		}
		co2, err1 := strconv.ParseFloat(get(r, cCO2), 64)
		in, err2 := strconv.ParseFloat(get(r, cInt), 64)
		if err1 != nil || err2 != nil || co2 <= 0 || in <= 0 {
			continue // no freight part reported
		}
		s := Ship{IMO: get(r, cIMO), Name: get(r, cName), Company: get(r, cComp), FreightCO2T: co2, GPerTNm: in}
		// The intensity is reported in g per m tonnes x n miles.
		s.FreightWorkTNm = math.Round(co2 * 1e6 / in)
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].IMO < out[j].IMO })
	return out, nil
}

// firstSheet reads the first worksheet of an .xlsx as rows of strings.
func firstSheet(b []byte) ([][]string, error) {
	z, err := zip.NewReader(bytes.NewReader(b), int64(len(b)))
	if err != nil {
		return nil, err
	}
	read := func(name string) ([]byte, error) {
		for _, f := range z.File {
			if f.Name == name {
				rc, err := f.Open()
				if err != nil {
					return nil, err
				}
				defer rc.Close()
				return io.ReadAll(rc)
			}
		}
		return nil, os.ErrNotExist
	}
	var shared []string
	if ss, err := read("xl/sharedStrings.xml"); err == nil {
		var sst struct {
			SI []struct {
				T string `xml:"t"`
				R []struct {
					T string `xml:"t"`
				} `xml:"r"`
			} `xml:"si"`
		}
		if err := xml.Unmarshal(ss, &sst); err != nil {
			return nil, err
		}
		for _, si := range sst.SI {
			s := si.T
			for _, r := range si.R {
				s += r.T
			}
			shared = append(shared, s)
		}
	}
	sheet, err := read("xl/worksheets/sheet1.xml")
	if err != nil {
		return nil, fmt.Errorf("sheet1: %w", err)
	}
	var ws struct {
		Rows []struct {
			C []struct {
				R  string `xml:"r,attr"`
				T  string `xml:"t,attr"`
				V  string `xml:"v"`
				IS struct {
					T string `xml:"t"`
				} `xml:"is"`
			} `xml:"c"`
		} `xml:"sheetData>row"`
	}
	if err := xml.Unmarshal(sheet, &ws); err != nil {
		return nil, err
	}
	var rows [][]string
	for _, r := range ws.Rows {
		var row []string
		for _, c := range r.C {
			i := colIndex(c.R)
			for len(row) < i {
				row = append(row, "")
			}
			v := c.V
			switch c.T {
			case "s":
				if n, err := strconv.Atoi(v); err == nil && n < len(shared) {
					v = shared[n]
				}
			case "inlineStr":
				v = c.IS.T
			}
			row = append(row, v)
		}
		rows = append(rows, row)
	}
	return rows, nil
}

// colIndex is the 0-based column of a cell reference like "AB12".
func colIndex(ref string) int {
	n := 0
	for _, ch := range ref {
		if ch < 'A' || ch > 'Z' {
			break
		}
		n = n*26 + int(ch-'A'+1)
	}
	return n - 1
}

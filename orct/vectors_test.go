package orct

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// The conformance vectors of the ORCT repository (tests/vectors), with the
// datasets they name (spec 4.4).
func TestVectors(t *testing.T) {
	files, _ := filepath.Glob("testdata/vectors/*.json")
	if len(files) == 0 {
		t.Fatal("no vectors")
	}
	cache := map[string]*Dataset{}
	for _, f := range files {
		var v struct {
			Datasets []string `json:"datasets"`
			Usage    Usage    `json:"usage"`
			Expected struct {
				Complete bool    `json:"complete"`
				Totals   []Total `json:"totals"`
				Issues   []string
				Lines    []struct {
					Charge string `json:"charge"`
					Amount string `json:"amount"`
				} `json:"lines"`
			} `json:"expected"`
		}
		b, _ := os.ReadFile(f)
		if err := json.Unmarshal(b, &v); err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		var dss []*Dataset
		for _, p := range v.Datasets {
			ds := cache[p]
			if ds == nil {
				raw, err := os.ReadFile(filepath.Join("testdata", p))
				if err != nil {
					t.Fatal(err)
				}
				if ds, err = Load(raw); err != nil {
					t.Fatalf("%s: %v", p, err)
				}
				cache[p] = ds
			}
			dss = append(dss, ds)
		}
		st := Calculate(dss, &v.Usage)
		name := filepath.Base(f)
		if st.Complete != v.Expected.Complete {
			t.Errorf("%s: complete %v, want %v (%v)", name, st.Complete, v.Expected.Complete, st.Issues)
		}
		got := map[string]string{}
		for _, tt := range st.Totals {
			got[tt.Currency] = tt.Amount
		}
		for _, tt := range v.Expected.Totals {
			if g, ok := got[tt.Currency]; !ok || MustDec(g).Cmp(MustDec(tt.Amount)) != 0 {
				t.Errorf("%s: total %s %s, want %s", name, tt.Currency, g, tt.Amount)
			}
		}
		if len(got) != len(v.Expected.Totals) {
			t.Errorf("%s: totals %v, want %v", name, st.Totals, v.Expected.Totals)
		}
		codes := map[string]bool{}
		for _, i := range st.Issues {
			codes[i.Code] = true
		}
		for _, c := range v.Expected.Issues {
			if !codes[c] {
				t.Errorf("%s: issue %s missing (%v)", name, c, st.Issues)
			}
		}
		if v.Expected.Lines != nil {
			var g, w []string
			for _, l := range st.Lines {
				g = append(g, l.Charge+" "+l.Amount.String())
			}
			for _, l := range v.Expected.Lines {
				w = append(w, l.Charge+" "+MustDec(l.Amount).String())
			}
			sort.Strings(g)
			sort.Strings(w)
			if len(g) != len(w) {
				t.Errorf("%s: lines %v, want %v", name, g, w)
				continue
			}
			for i := range g {
				if g[i] != w[i] {
					t.Errorf("%s: lines %v, want %v", name, g, w)
					break
				}
			}
		}
	}
}

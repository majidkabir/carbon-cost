package orct

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// The reference calculator's statements for recorded usages (a JSONL file
// named by ORCT_RECORDED, the datasets in ORCT_DATA, as the ORCT
// repository's tools write them): every line, total and issue the same.
func TestRecordedStatements(t *testing.T) {
	recs, dir := os.Getenv("ORCT_RECORDED"), os.Getenv("ORCT_DATA")
	if recs == "" || dir == "" {
		t.Skip("ORCT_RECORDED or ORCT_DATA not set")
	}
	byID := map[string]*Dataset{}
	files, _ := filepath.Glob(filepath.Join(dir, "*", "*.orct.json"))
	for _, f := range files {
		b, _ := os.ReadFile(f)
		ds, err := Load(b)
		if err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		byID[ds.ID] = ds
	}
	f, err := os.Open(recs)
	if err != nil {
		t.Fatal(err)
	}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<26)
	n, bad := 0, 0
	for sc.Scan() {
		var r struct {
			Datasets  []string `json:"datasets"`
			Usage     Usage    `json:"usage"`
			Statement struct {
				Complete bool     `json:"complete"`
				Totals   []Total  `json:"totals"`
				Lines    [][]any  `json:"lines"`
				Issues   []string `json:"issues"`
			} `json:"statement"`
		}
		if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
			t.Fatal(err)
		}
		var dss []*Dataset
		for _, id := range r.Datasets {
			dss = append(dss, byID[id])
		}
		st := Calculate(dss, &r.Usage)
		n++
		var errs []string
		if st.Complete != r.Statement.Complete {
			errs = append(errs, fmt.Sprintf("complete %v, want %v", st.Complete, r.Statement.Complete))
		}
		if !reflect.DeepEqual(st.Totals, r.Statement.Totals) && !(len(st.Totals) == 0 && len(r.Statement.Totals) == 0) {
			errs = append(errs, fmt.Sprintf("totals %v, want %v", st.Totals, r.Statement.Totals))
		}
		var codes []string
		for _, i := range st.Issues {
			codes = append(codes, i.Code)
		}
		if fmt.Sprint(codes) != fmt.Sprint(r.Statement.Issues) {
			errs = append(errs, fmt.Sprintf("issues %v, want %v", codes, r.Statement.Issues))
		}
		if len(st.Lines) != len(r.Statement.Lines) {
			errs = append(errs, fmt.Sprintf("%d lines, want %d", len(st.Lines), len(r.Statement.Lines)))
		} else {
			for i, l := range st.Lines {
				w := r.Statement.Lines[i]
				row := any(nil)
				if l.Row != nil {
					row = float64(*l.Row)
				}
				objs := []any{}
				for _, o := range l.Objects {
					objs = append(objs, o)
				}
				wo, _ := w[2].([]any)
				if wo == nil {
					wo = []any{}
				}
				if l.Charge != w[0] || l.Amount.Cmp(MustDec(w[1].(string))) != 0 || !reflect.DeepEqual(objs, wo) || !reflect.DeepEqual(row, w[3]) {
					errs = append(errs, fmt.Sprintf("line %d: %s %s %v %v, want %v", i, l.Charge, l.Amount, l.Objects, row, w))
				}
			}
		}
		if len(errs) > 0 {
			bad++
			if bad <= 20 {
				t.Errorf("%v %s: %v", r.Datasets, sc.Text()[:min(300, len(sc.Text()))], errs)
			}
		}
	}
	if err := sc.Err(); err != nil {
		t.Fatal(err)
	}
	t.Logf("%d usages, %d differ", n, bad)
	if bad > 0 {
		t.Fail()
	}
}

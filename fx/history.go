package fx

import (
	"bytes"
	_ "embed"
	"encoding/csv"
	"fmt"
	"sort"
	"strconv"
	"sync"
	"time"
)

// histCSV is the ECB's reference rates of each working day since 1
// January 2024 for the currencies the rate tables use, built by
// tools/history/ecb.py from eurofxref-hist.zip (the History data
// workflow).
//
//go:embed data/ecb-hist.csv
var histCSV []byte

// HistSource names the embedded rates, for notes.
const HistSource = "ECB euro foreign exchange reference rates (eurofxref-hist)"

var (
	histOnce sync.Once
	hist     []Rates // by date, oldest first
	histErr  error
)

func loadHist() {
	r := csv.NewReader(bytes.NewReader(histCSV))
	recs, err := r.ReadAll()
	if err != nil || len(recs) < 2 {
		histErr = fmt.Errorf("fx: embedded history: %v", err)
		return
	}
	head := recs[0]
	for _, rec := range recs[1:] {
		day := Rates{Date: rec[0], PerEUR: map[string]float64{}}
		for i := 1; i < len(rec) && i < len(head); i++ {
			if v, err := strconv.ParseFloat(rec[i], 64); err == nil && v > 0 {
				day.PerEUR[head[i]] = v
			}
		}
		hist = append(hist, day)
	}
	sort.Slice(hist, func(i, j int) bool { return hist[i].Date < hist[j].Date })
}

// OnDate is the reference rates for a day: that day's, or those of the
// last working day before it (rates are published on TARGET working
// days). ok is false outside the embedded days: before the first, or
// after the last.
func OnDate(date time.Time) (Rates, bool) {
	histOnce.Do(loadHist)
	if histErr != nil || len(hist) == 0 {
		return Rates{}, false
	}
	d := date.Format(time.DateOnly)
	if d < hist[0].Date || d > hist[len(hist)-1].Date {
		return Rates{}, false
	}
	i := sort.Search(len(hist), func(i int) bool { return hist[i].Date > d }) - 1
	return hist[i], true
}

// HistoryRange is the first and last day embedded.
func HistoryRange() (string, string) {
	histOnce.Do(loadHist)
	if len(hist) == 0 {
		return "", ""
	}
	return hist[0].Date, hist[len(hist)-1].Date
}

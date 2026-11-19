package fx

import (
	"bytes"
	_ "embed"
	"encoding/csv"
	"sort"
	"strconv"
	"sync"
	"time"
)

// nbsCSV is the National Bank of Serbia's official middle rate of the
// dinar against the euro of each exchange rate list since 1 January 2024,
// with the day each applies from, built by tools/history/nbs.py from the
// NBS's exchange rate web app (the History data workflow). The ECB
// publishes no dinar rate.
//
//go:embed data/nbs-eur-rsd.csv
var nbsCSV []byte

// NBSSource names the dinar rates, for notes.
const NBSSource = "National Bank of Serbia, official middle exchange rate (zvanični srednji kurs)"

type nbsDay struct {
	date string
	rsd  float64
}

var (
	nbsOnce sync.Once
	nbs     []nbsDay // by date, oldest first
)

func loadNBS() {
	recs, err := csv.NewReader(bytes.NewReader(nbsCSV)).ReadAll()
	if err != nil || len(recs) < 2 {
		return
	}
	for _, rec := range recs[1:] {
		if v, err := strconv.ParseFloat(rec[1], 64); err == nil && v > 0 {
			nbs = append(nbs, nbsDay{rec[0], v})
		}
	}
	sort.Slice(nbs, func(i, j int) bool { return nbs[i].date < nbs[j].date })
}

// RSDOnDate is the dinars per euro of the NBS's middle rate list in force on
// the day (the last list applying from that day or before), and the day
// that list applies from. ok is false before the first list embedded; after
// the last, the last one is given (its day says how old it is).
func RSDOnDate(date time.Time) (perEUR float64, from string, ok bool) {
	nbsOnce.Do(loadNBS)
	d := date.Format(time.DateOnly)
	if len(nbs) == 0 || d < nbs[0].date {
		return 0, "", false
	}
	i := sort.Search(len(nbs), func(i int) bool { return nbs[i].date > d }) - 1
	return nbs[i].rsd, nbs[i].date, true
}

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

// Currencies the ECB publishes no reference rate for take the issuing
// central bank's official rate against the euro, of every day since 1
// January 2024 (a weekend's or holiday's is the last working day's), as
// tools/history builds them (the History data workflow).

// nbsCSV is the National Bank of Serbia's official middle rate of the
// dinar, with the day each list applies from (tools/history/nbs.py, from
// the NBS's exchange rate web app).
//
//go:embed data/nbs-eur-rsd.csv
var nbsCSV []byte

// boaCSV is the Bank of Albania's official exchange rate of the lek
// (tools/history/boa.py, from the official exchange rate page).
//
//go:embed data/boa-eur-all.csv
var boaCSV []byte

// NBSSource names the dinar rates, for notes.
const NBSSource = "National Bank of Serbia, official middle exchange rate (zvanični srednji kurs)"

// BoASource names the lek rates, for notes.
const BoASource = "Bank of Albania, official exchange rate (kursi zyrtar i këmbimit)"

type natDay struct {
	date string
	rate float64
}

type national struct {
	source string
	csv    []byte
	once   sync.Once
	days   []natDay // by date, oldest first
}

var nationals = map[string]*national{
	"RSD": {source: NBSSource, csv: nbsCSV},
	"ALL": {source: BoASource, csv: boaCSV},
}

func (n *national) load() {
	recs, err := csv.NewReader(bytes.NewReader(n.csv)).ReadAll()
	if err != nil || len(recs) < 2 {
		return
	}
	for _, rec := range recs[1:] {
		if v, err := strconv.ParseFloat(rec[1], 64); err == nil && v > 0 {
			n.days = append(n.days, natDay{rec[0], v})
		}
	}
	sort.Slice(n.days, func(i, j int) bool { return n.days[i].date < n.days[j].date })
}

// NationalOnDate is the units of the currency per euro of its central
// bank's official rate in force on the day (the last applying from that
// day or before), the day that rate applies from and the source. ok is
// false for a currency without such rates and before the first rate
// embedded; after the last, the last one is given (its day says how old
// it is).
func NationalOnDate(cur string, date time.Time) (perEUR float64, from, source string, ok bool) {
	n := nationals[cur]
	if n == nil {
		return 0, "", "", false
	}
	n.once.Do(n.load)
	d := date.Format(time.DateOnly)
	if len(n.days) == 0 || d < n.days[0].date {
		return 0, "", n.source, false
	}
	i := sort.Search(len(n.days), func(i int) bool { return n.days[i].date > d }) - 1
	return n.days[i].rate, n.days[i].date, n.source, true
}

// RSDOnDate is NationalOnDate for the dinar.
func RSDOnDate(date time.Time) (perEUR float64, from string, ok bool) {
	v, from, _, ok := NationalOnDate("RSD", date)
	return v, from, ok
}

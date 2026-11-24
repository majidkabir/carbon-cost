package fuel

import (
	"bytes"
	_ "embed"
	"encoding/csv"
	"sort"
	"strconv"
	"sync"
	"time"
)

// National diesel prices for countries the Weekly Oil Bulletin doesn't
// cover, from their own official statistics (built by
// tools/history/national_diesel.py; the National diesel prices workflow):
// the UK's weekly road fuel prices (DESNZ), Statistics Norway's table
// 09654 and the Swiss Federal Statistical Office's average fuel prices in
// the consumer price index (LIK), each a national average pump price with
// VAT, in the national currency.
//
//go:embed data/national-diesel.csv
var nationalCSV []byte

// National is one country's average pump price of road diesel on a date:
// the week's Monday (GB) or the month's first day (NO, CH).
type National struct {
	Date     string
	Country  string
	Currency string
	// PerL is the price per litre with VAT, in Currency; VATPct the VAT
	// rate in it.
	PerL, VATPct float64
	Source       string
}

// PerLExVAT is the price per litre without VAT, in Currency.
func (n National) PerLExVAT() float64 { return n.PerL / (1 + n.VATPct/100) }

// NationalSources are the statistics' pages, for sources.
var NationalSources = map[string][2]string{
	"GB": {"DESNZ: Weekly road fuel prices", "https://www.gov.uk/government/statistics/weekly-road-fuel-prices"},
	"NO": {"Statistics Norway: table 09654, prices on engine fuel", "https://www.ssb.no/en/statbank/table/09654"},
	"CH": {"Federal Statistical Office: LIK, average prices for energy and motor fuels", "https://www.bfs.admin.ch/bfs/en/home/statistics/prices/consumer-price-index.html"},
}

var national struct {
	once sync.Once
	rows map[string][]National // by country, oldest first
}

func loadNational() {
	national.rows = map[string][]National{}
	recs, err := csv.NewReader(bytes.NewReader(nationalCSV)).ReadAll()
	if err != nil || len(recs) < 2 {
		return
	}
	for _, r := range recs[1:] {
		if len(r) < 6 {
			continue
		}
		p, err1 := strconv.ParseFloat(r[3], 64)
		v, err2 := strconv.ParseFloat(r[4], 64)
		if err1 != nil || err2 != nil || p <= 0 {
			continue
		}
		national.rows[r[1]] = append(national.rows[r[1]], National{Date: r[0], Country: r[1], Currency: r[2], PerL: p, VATPct: v, Source: r[5]})
	}
	for _, rs := range national.rows {
		sort.Slice(rs, func(i, j int) bool { return rs[i].Date < rs[j].Date })
	}
}

// NationalOn is a country's price in force on a day: the latest week's or
// month's on or before it; latest says the day is past the newest one.
func NationalOn(country string, day time.Time) (n National, latest, ok bool) {
	national.once.Do(loadNational)
	rs := national.rows[country]
	d := day.Format(time.DateOnly)
	i := sort.Search(len(rs), func(i int) bool { return rs[i].Date > d })
	if i == 0 {
		return National{}, false, false
	}
	n = rs[i-1]
	// A week's price holds for 7 days, a month's for the month.
	next := time.Time{}
	if t, err := time.Parse(time.DateOnly, n.Date); err == nil {
		if n.Country == "GB" {
			next = t.AddDate(0, 0, 7)
		} else {
			next = t.AddDate(0, 1, 0)
		}
	}
	return n, i == len(rs) && !day.Before(next), true
}

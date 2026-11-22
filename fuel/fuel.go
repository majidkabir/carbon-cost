// Package fuel gives the European Commission's Weekly Oil Bulletin
// diesel prices: each EU country's national average pump price of
// automotive gas oil, without VAT, on each bulletin's Monday since 1
// January 2024 (built by tools/history/wob.py; the History data workflow).
package fuel

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

//go:embed data/wob-diesel.csv
var dieselCSV []byte

// Source names the prices, for notes.
const Source = "European Commission, Weekly Oil Bulletin: national average pump prices of automotive gas oil, without VAT"

// URL is the bulletin's page.
const URL = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"

// Bulletin is one week's prices, EUR per litre without VAT, by country
// (ISO 3166-1 alpha-2).
type Bulletin struct {
	Date    string // the Monday the prices are of
	EURPerL map[string]float64
}

var (
	once      sync.Once
	bulletins []Bulletin // oldest first
	loadErr   error
)

func load() {
	recs, err := csv.NewReader(bytes.NewReader(dieselCSV)).ReadAll()
	if err != nil || len(recs) < 2 {
		loadErr = fmt.Errorf("fuel: embedded prices: %v", err)
		return
	}
	head := recs[0]
	for _, rec := range recs[1:] {
		b := Bulletin{Date: rec[0], EURPerL: map[string]float64{}}
		for i := 1; i < len(rec) && i < len(head); i++ {
			if v, err := strconv.ParseFloat(rec[i], 64); err == nil && v > 0 {
				b.EURPerL[head[i]] = v
			}
		}
		bulletins = append(bulletins, b)
	}
	sort.Slice(bulletins, func(i, j int) bool { return bulletins[i].Date < bulletins[j].Date })
}

// On is the bulletin in force on a day: the last one of a Monday on or
// before it. latest is true when the day is past the last bulletin's week
// (a future trip, or one this release has no bulletin for yet): the last
// one is given. ok is false before the first.
func On(day time.Time) (b Bulletin, latest, ok bool) {
	once.Do(load)
	if loadErr != nil || len(bulletins) == 0 {
		return Bulletin{}, false, false
	}
	d := day.Format(time.DateOnly)
	i := sort.Search(len(bulletins), func(i int) bool { return bulletins[i].Date > d })
	if i == 0 {
		return Bulletin{}, false, false
	}
	b = bulletins[i-1]
	last, _ := time.Parse(time.DateOnly, bulletins[len(bulletins)-1].Date)
	return b, i == len(bulletins) && !day.Before(last.AddDate(0, 0, 7)), true
}

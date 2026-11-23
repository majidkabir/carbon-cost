// Package fuel gives the European Commission's Weekly Oil Bulletin
// diesel prices: each EU country's national average pump price of
// automotive gas oil, without VAT, on each bulletin's Monday since 1
// January 2024, and the duties other than VAT in it (built by
// tools/history/wob.py; the History data workflow); and the hauliers'
// refunds of the excise (Refunds).
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

//go:embed data/wob-diesel-duties.csv
var dutiesCSV []byte

//go:embed data/wob-diesel-excise.csv
var exciseCSV []byte

//go:embed data/eurostat-power.csv
var powerCSV []byte

// ExciseSource and PowerSource name the excise rates and the electricity
// prices, for notes.
const (
	ExciseSource = "European Commission, Weekly Oil Bulletin: excise duties on automotive gas oil, in national currency"
	PowerSource  = "Eurostat, electricity prices for non-household consumers (nrg_pc_205), band 500-2,000 MWh a year, without VAT and other recoverable taxes and levies"
	PowerURL     = "https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_205/default/table"
)

// Source names the prices, for notes.
const Source = "European Commission, Weekly Oil Bulletin: national average pump prices of automotive gas oil, without VAT"

// DutiesSource names the duties, for notes.
const DutiesSource = "European Commission, Weekly Oil Bulletin: duties and taxes other than VAT on automotive gas oil (the price with taxes without VAT, less the price without taxes)"

// URL is the bulletin's page.
const URL = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"

// Bulletin is one week's figures, EUR per litre, by country (ISO 3166-1
// alpha-2): the prices without VAT, or the duties other than VAT.
type Bulletin struct {
	Date    string // the Monday the figures are of
	EURPerL map[string]float64
}

type series struct {
	once      sync.Once
	csv       []byte
	bulletins []Bulletin // oldest first
	err       error
}

var (
	prices = &series{csv: dieselCSV}
	duties = &series{csv: dutiesCSV}
	excise = &series{csv: exciseCSV}
	power  = &series{csv: powerCSV}
)

func (s *series) load() {
	recs, err := csv.NewReader(bytes.NewReader(s.csv)).ReadAll()
	if err != nil || len(recs) < 2 {
		s.err = fmt.Errorf("fuel: embedded bulletins: %v", err)
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
		s.bulletins = append(s.bulletins, b)
	}
	sort.Slice(s.bulletins, func(i, j int) bool { return s.bulletins[i].Date < s.bulletins[j].Date })
}

// On is the bulletin in force on a day: the last one of a Monday on or
// before it. latest is true when the day is past the last bulletin's week
// (a future trip, or one this release has no bulletin for yet): the last
// one is given. ok is false before the first.
func On(day time.Time) (b Bulletin, latest, ok bool) { return prices.on(day) }

// DutiesOn is the duties other than VAT in force on a day, as On.
func DutiesOn(day time.Time) (b Bulletin, latest, ok bool) { return duties.on(day) }

// ExciseOn is each country's excise duty on diesel in force on a day, per
// litre in its national currency (EUR but for BG before 2026, CZ, DK, HU,
// PL, RO and SE): Bulletin.Date is the day the newest rate took effect.
func ExciseOn(day time.Time) (b Bulletin, latest, ok bool) { return excise.on(day) }

// PowerOn is each country's electricity price for businesses in force on
// a day, EUR per kWh without VAT: Bulletin.Date is the half year's first
// day (Eurostat publishes about five months after it ends).
func PowerOn(day time.Time) (b Bulletin, latest, ok bool) { return power.on(day) }

func (s *series) on(day time.Time) (b Bulletin, latest, ok bool) {
	s.once.Do(s.load)
	if s.err != nil || len(s.bulletins) == 0 {
		return Bulletin{}, false, false
	}
	d := day.Format(time.DateOnly)
	i := sort.Search(len(s.bulletins), func(i int) bool { return s.bulletins[i].Date > d })
	if i == 0 {
		return Bulletin{}, false, false
	}
	b = s.bulletins[i-1]
	last, _ := time.Parse(time.DateOnly, s.bulletins[len(s.bulletins)-1].Date)
	return b, i == len(s.bulletins) && !day.Before(last.AddDate(0, 0, 7)), true
}

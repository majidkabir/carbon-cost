package site

import (
	"sort"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// ferryPath is the page of the ferry crossings and their ETS shares. It is
// in English only: its notes paraphrase the laws, and other languages link
// to it.
const ferryPath = "/tolls/ferry-ets"

// ferryPage: each ferry crossing the calculator knows, the share of its
// emissions under the EU ETS and the UK ETS on the day by law (the same
// code the calculator prices with), and the ships its operators name.
func (s *Site) ferryPage(l *Loc, day string, today time.Time) (crossView, card) {
	v := crossView{H1: l.T("x.ferry.h1"), Cols: []string{l.T("x.ferry.col.crossing"), l.T("x.ferry.col.eu"), l.T("x.ferry.col.uk"),
		l.T("x.ferry.col.basis"), l.T("x.ferry.col.ships"), l.T("x.ferry.col.operator")}}
	cs := append([]ferries.Crossing(nil), s.fd.Crossings...)
	sort.SliceStable(cs, func(i, j int) bool { return cs[i].Name < cs[j].Name })
	full, half, none := 0, 0, 0
	for _, c := range cs {
		cov, ok := s.fd.Coverage(c, today)
		eu, why := "–", l.T("x.ferry.unknown")
		if ok {
			eu, why = l.PctOf(cov.Share), cov.Basis
			if cov.Note != "" {
				why += "; " + cov.Note
			}
			switch {
			case cov.Share == 1:
				full++
			case cov.Share == 0:
				none++
			default:
				half++
			}
		}
		uk := ""
		if u, applies := s.fd.UKCoverage(c, today); applies {
			uk = l.PctOf(u.Share)
			why += ". UK ETS: " + u.Basis
		}
		var ships []string
		for _, sh := range c.Ships {
			n := sh.Name
			if sh.IMO != "" {
				n += " (IMO " + sh.IMO + ")"
			}
			ships = append(ships, n)
		}
		v.Rows = append(v.Rows, crossRow{Cells: []string{c.Name, eu, uk, why, strings.Join(ships, ", "), c.Operator}, Href: c.Source.URL})
	}
	v.Lead = l.T("x.ferry.lead", "n", len(v.Rows), "date", l.Date(day), "full", full, "half", half, "none", none)
	v.Notes = []string{l.T("x.ferry.note1"), l.T("x.ferry.note2"), l.T("x.ferry.note3")}
	v.Sources = []tariffs.Source{
		{Title: "Directive 2003/87/EC (EU ETS), consolidated: Art. 3ga (maritime transport), Art. 12(3-d), Annex I", URL: "https://eur-lex.europa.eu/eli/dir/2003/87/oj"},
		{Title: "Commission Implementing Decision (EU) 2023/2895: the islands and ports under Art. 12(3-d)", URL: "https://eur-lex.europa.eu/eli/dec_impl/2023/2895/oj"},
		{Title: "The Greenhouse Gas Emissions Trading Scheme (Amendment) (Extension to Maritime Activities) Order 2026 (SI 2026/392)", URL: "https://www.legislation.gov.uk/uksi/2026/392/made"},
		{Title: "The crossings, their ships and sources (ferries/data, built by tools/tables/ferry_ships.py and ets_islands.py)", URL: "https://github.com/majidkabir/carbon-cost/tree/main/ferries/data"},
	}
	ld := s.datasetLD(ferryPath, l.T("x.ferry.link"), v.Lead, "Europe", nil, "", l.Code)
	v.Head = s.mkHead(l, ferryPath, l.T("x.ferry.title", "year", today.Year()), short(v.Lead, 300), ld,
		link{l.T("nav.tolls"), s.prefix + s.pagePath(l.Code, "/tolls")}, link{l.T("x.ferry.link"), s.prefix + ferryPath})
	v.Updated = l.Date(day)
	cd := card{Kicker: l.T("site.kicker"), Title: l.T("x.ferry.link"), Big: l.T("x.ferry.card.big", "n", len(v.Rows)),
		BigNote: l.T("x.ferry.card.note"), Footer: hostPath(s.base) + ferryPath}
	return v, cd
}

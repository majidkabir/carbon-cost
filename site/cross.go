package site

import (
	"html/template"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/fx"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// The pages across countries.

func fxOnDate(day time.Time) (string, bool) {
	r, ok := ratesOn(day)
	return r.Date, ok
}

// ratesOn is the ECB's rates of a day, or after the embedded days (a page
// built after the release's data) the last day's: the notes give the day.
func ratesOn(day time.Time) (fx.Rates, bool) {
	if _, last := fx.HistoryRange(); last != "" && day.Format(time.DateOnly) > last {
		day, _ = time.Parse(time.DateOnly, last)
	}
	return fx.OnDate(day)
}

func dayAfter(d string) string {
	t, err := time.Parse(time.DateOnly, d)
	if err != nil {
		return d
	}
	return t.AddDate(0, 0, 1).Format(time.DateOnly)
}

// zePage: what a zero-emission 40 t truck pays per km against a diesel
// one, in each country with a km toll, now and as the laws change it.
func (s *Site) zePage(l *Loc, cs []*country, data map[string]*countryData, day string, today time.Time) (crossView, card) {
	v := crossView{H1: l.T("x.ze.h1"), Cols: []string{l.T("ov.col.country"), l.T("x.ze.col.diesel"), l.T("x.ze.col.ze"), l.T("x.ze.col.saving"), l.T("x.ze.col.law")}}
	var all []*tariffs.Dataset
	free := 0
	for _, c := range cs {
		tolls := c.of(tariffs.Toll)
		for _, sc := range tolls {
			if sc.Current == nil {
				continue
			}
			ds := sc.Current
			objs := kmObjects(ds)
			if len(objs) == 0 {
				continue
			}
			obj := objs[0]
			d := perKm(ds, obj, truck40, day)
			z := perKm(ds, obj, zeTruck, day)
			if !d.OK || !z.OK {
				continue
			}
			all = append(all, ds)
			name := l.Country(c.Code)
			if len(tolls) > 1 {
				name += " (" + ds.Name + ")"
			}
			var law []string
			if until, _, ok := zeRule(ds); ok {
				law = append(law, l.T("c.ze.free", "date", l.Date(until)))
				after := dayAfter(until)
				if ds.ValidTo == "" || ds.ValidTo >= after {
					if za := perKm(ds, obj, zeTruck, after); za.OK {
						law = append(law, l.T("x.ze.after", "date", l.Date(after), "amount", l.Money(za.Total, za.Cur)))
					}
				}
			}
			for _, up := range sc.Upcoming {
				uo := kmObjects(up)
				if len(uo) == 0 {
					continue
				}
				zu, du := perKm(up, uo[0], zeTruck, up.ValidFrom), perKm(up, uo[0], truck40, up.ValidFrom)
				if zu.OK && du.OK {
					law = append(law, l.T("x.ze.from", "date", l.Date(up.ValidFrom), "amount", l.Money(zu.Total, zu.Cur), "diesel", l.Money(du.Total, du.Cur)))
				}
			}
			saving := l.Pct(d.Total-z.Total, d.Total)
			if z.Total == 0 {
				free++
				saving = l.T("x.ze.free")
			}
			v.Rows = append(v.Rows, crossRow{Cells: []string{name, l.Money(d.Total, d.Cur), l.Money(z.Total, z.Cur), saving, strings.Join(law, " ")},
				Href: s.prefix + s.pagePath(l.Code, "/tolls/"+c.Slug)})
		}
	}
	v.Lead = l.T("x.ze.lead", "n", len(v.Rows), "date", l.Date(day), "free", free)
	v.Notes = []string{l.T("x.ze.note1"), l.T("x.ze.note2")}
	v.Sources = sources(all...)
	p := s.pagePath(l.Code, "/tolls/zero-emission-trucks")
	ld := s.datasetLD(p, l.T("x.ze.link"), v.Lead, "Europe", nil, "", l.Code)
	v.Head = s.mkHead(l, p, l.T("x.ze.title", "year", today.Year()), short(v.Lead, 300), ld,
		link{l.T("nav.tolls"), s.prefix + s.pagePath(l.Code, "/tolls")}, link{l.T("x.ze.link"), s.prefix + p})
	v.Updated = l.Date(day)
	cd := card{Kicker: l.T("site.kicker"), Title: l.T("x.ze.link"), Big: l.T("x.ze.card.big", "free", free, "n", len(v.Rows)),
		BigNote: l.T("x.ze.card.note"), Footer: hostPath(s.base) + p}
	return v, cd
}

// ets2Page: the ETS2 price per litre of diesel.
func (s *Site) ets2Page(l *Loc, cs []*country, data map[string]*countryData, day string, today time.Time) (crossView, card) {
	k := cost.DieselKgCO2PerL
	v := crossView{H1: l.T("x.ets2.h1"), Cols: []string{l.T("x.ets2.col.price"), l.T("x.ets2.col.perl"), l.T("x.ets2.col.per1000")}}
	for _, p := range []float64{30, 45, 60, 80, 100, 150} {
		perL := p * k / 1000
		v.Rows = append(v.Rows, crossRow{Cells: []string{l.Money(p, "EUR") + " " + l.unitName("t_co2"), l.Money(perL, "EUR"), l.Money(perL*1000, "EUR")}})
	}
	v.Lead = l.T("x.ets2.lead", "kg", l.Dec(k), "per10", l.Money(10*k/1000, "EUR"))
	link1 := `<a href="https://eur-lex.europa.eu/eli/dir/2003/87/oj">` + template.HTMLEscapeString(l.T("x.ets2.directive")) + `</a>`
	link2 := `<a href="` + s.prefix + s.pagePath(l.Code, "/tolls/co2-tax-diesel") + `">` + template.HTMLEscapeString(l.T("x.fuel.link")) + `</a>`
	v.Body = []template.HTML{
		template.HTML(strings.ReplaceAll(template.HTMLEscapeString(l.T("x.ets2.body1")), "{directive}", link1)),
		template.HTML(template.HTMLEscapeString(l.T("x.ets2.body2", "kg", l.Dec(k)))),
		template.HTML(strings.ReplaceAll(template.HTMLEscapeString(l.T("x.ets2.body3")), "{link}", link2)),
	}
	v.Notes = []string{l.T("x.ets2.note")}
	v.Sources = []tariffs.Source{{Title: "Directive 2003/87/EC (EU ETS), consolidated: Chapter IVa (ETS2)", URL: "https://eur-lex.europa.eu/eli/dir/2003/87/oj"},
		{Title: "European Commission: ETS2: buildings, road transport and additional sectors", URL: "https://climate.ec.europa.eu/eu-action/carbon-markets/ets2-buildings-road-transport-and-additional-sectors_en"}}
	p := s.pagePath(l.Code, "/tolls/ets2-diesel")
	ld := s.datasetLD(p, l.T("x.ets2.link"), v.Lead, "European Union", nil, "2028-01-01", l.Code)
	v.Head = s.mkHead(l, p, l.T("x.ets2.title"), short(v.Lead, 300), ld,
		link{l.T("nav.tolls"), s.prefix + s.pagePath(l.Code, "/tolls")}, link{l.T("x.ets2.link"), s.prefix + p})
	v.Updated = l.Date(day)
	cd := card{Kicker: l.T("site.kicker.fuel"), Title: l.T("x.ets2.h1"), Big: l.T("x.ets2.card.big", "amount", l.Money(45*k/1000, "EUR")),
		BigNote: l.T("x.ets2.card.note"), Accent: l.T("x.ets2.card.accent", "amount", l.Money(10*k/1000, "EUR")), AccentCO: "carbon",
		Footer: hostPath(s.base) + p}
	return v, cd
}

// fuelPage: each country's national CO2 price on diesel, per litre.
func (s *Site) fuelPage(l *Loc, cs []*country, data map[string]*countryData, day string, today time.Time) (crossView, card) {
	v := crossView{H1: l.T("x.fuel.h1"), Cols: []string{l.T("ov.col.country"), l.T("x.fuel.col.law"), l.T("x.fuel.col.perl"), l.T("x.fuel.col.from"), l.T("x.fuel.col.coming")}}
	var all []*tariffs.Dataset
	for _, c := range cs {
		for _, f := range data[c.Code].Fuel {
			if f.Sc.Current == nil {
				continue
			}
			all = append(all, f.Ds)
			rate, perL := l.fuelText(f.Rate)
			var coming []string
			for _, up := range f.Sc.Upcoming {
				r, pl := l.fuelText(fuelRateOf(up, today))
				coming = append(coming, l.T("x.fuel.coming", "date", l.Date(up.ValidFrom), "rate", r, "perl", pl))
			}
			v.Rows = append(v.Rows, crossRow{Cells: []string{l.Country(c.Code) + ": " + f.Ds.Name, rate, perL, l.Date(f.Ds.ValidFrom), strings.Join(coming, "; ")},
				Href: s.prefix + s.pagePath(l.Code, "/tolls/"+c.Slug)})
		}
	}
	sortRows(v.Rows)
	v.Lead = l.T("x.fuel.lead", "n", len(v.Rows), "date", l.Date(day))
	v.Notes = []string{l.T("x.fuel.note1", "kg", l.Dec(cost.DieselKgCO2PerL)), l.T("x.fuel.note2")}
	v.Sources = sources(all...)
	p := s.pagePath(l.Code, "/tolls/co2-tax-diesel")
	ld := s.datasetLD(p, l.T("x.fuel.link"), v.Lead, "Europe", nil, "", l.Code)
	v.Head = s.mkHead(l, p, l.T("x.fuel.title", "year", today.Year()), short(v.Lead, 300), ld,
		link{l.T("nav.tolls"), s.prefix + s.pagePath(l.Code, "/tolls")}, link{l.T("x.fuel.link"), s.prefix + p})
	v.Updated = l.Date(day)
	cd := card{Kicker: l.T("site.kicker.fuel"), Title: l.T("x.fuel.link"), Big: l.T("ov.card.big", "n", len(v.Rows)),
		BigNote: l.T("x.fuel.card.note"), Footer: hostPath(s.base) + p}
	return v, cd
}

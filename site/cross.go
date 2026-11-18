package site

import (
	"fmt"
	"html/template"
	"strings"
	"time"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/fx"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// The pages across countries.

func fxOnDate(day time.Time) (string, bool) {
	r, ok := fx.OnDate(day)
	return r.Date, ok
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
func (s *Site) zePage(cs []*country, day string, today time.Time) (crossView, card) {
	v := crossView{H1: "Zero-emission truck toll exemptions and discounts in Europe",
		Cols: []string{"Country", "Diesel truck per km", "Zero-emission truck per km", "Saving", "What the law says"}}
	var all []*tariffs.Dataset
	free := 0
	for _, c := range cs {
		for _, sc := range c.of(tariffs.Toll) {
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
			name := c.Name
			if len(c.of(tariffs.Toll)) > 1 {
				name += " (" + ds.Name + ")"
			}
			law := ""
			if until, note, ok := zeRule(ds); ok {
				law = note
				after := dayAfter(until)
				if ds.ValidTo == "" || ds.ValidTo >= after {
					if za := perKm(ds, obj, zeTruck, after); za.OK {
						law += fmt.Sprintf(" From %s, as the law stands: %s per km.", dateName(after), money(za.Total, za.Cur))
					}
				}
			}
			for _, up := range sc.Upcoming {
				uo := kmObjects(up)
				if len(uo) == 0 {
					continue
				}
				zu := perKm(up, uo[0], zeTruck, up.ValidFrom)
				du := perKm(up, uo[0], truck40, up.ValidFrom)
				if zu.OK && du.OK {
					law += fmt.Sprintf(" From %s: %s per km (diesel %s).", dateName(up.ValidFrom), money(zu.Total, zu.Cur), money(du.Total, du.Cur))
				}
			}
			saving := pct(d.Total-z.Total, d.Total)
			if z.Total == 0 {
				free++
				saving = "100% (free)"
			}
			v.Rows = append(v.Rows, crossRow{Cells: []string{name, money(d.Total, d.Cur), money(z.Total, z.Cur), saving, strings.TrimSpace(law)},
				Href: s.prefix + "/tolls/" + c.Slug})
		}
	}
	v.Lead = fmt.Sprintf("What a zero-emission 40 t, 5-axle truck (CO2 class 5) pays per km against a Euro VI diesel truck (CO2 class 1) in the %d European km tolls, on %s, and what changes as the laws stand. %d of them charge zero-emission trucks nothing today.",
		len(v.Rows), dateName(day), free)
	v.Notes = []string{"Rates on each country's main tolled network (the first road type of its rate table), in its own currency. Each figure is priced from the law's rate table by the same code as the calculator.",
		"Vignette countries, closed toll systems, bridges and tunnels mostly don't distinguish zero-emission trucks; see each country's page."}
	v.Sources = sources(all...)
	ld := s.datasetLD("/tolls/zero-emission-trucks", "Zero-emission truck toll exemptions in Europe", v.Lead, "Europe", nil, "")
	v.Head = s.mkHead("/tolls/zero-emission-trucks", fmt.Sprintf("Zero-emission truck toll exemptions in Europe %d: what electric trucks pay per km", today.Year()),
		short(v.Lead, 300), ld, link{"Truck tolls", s.prefix + "/tolls"}, link{"Zero-emission trucks", s.prefix + "/tolls/zero-emission-trucks"})
	v.Updated = day
	cd := card{Kicker: "carbon-cost · truck tolls", Title: "Zero-emission truck tolls in Europe", Big: fmt.Sprintf("%d of %d free", free, len(v.Rows)),
		BigNote: "km tolls that charge a zero-emission 40 t truck nothing today", Footer: hostPath(s.base) + "/tolls/zero-emission-trucks"}
	return v, cd
}

// ets2Page: the ETS2 price per litre of diesel.
func (s *Site) ets2Page(cs []*country, day string, today time.Time) (crossView, card) {
	k := cost.DieselKgCO2PerL
	v := crossView{H1: "ETS2 from 2028: the cost per litre of diesel",
		Cols: []string{"ETS2 allowance price", "Per litre of diesel", "Per 1,000 litres"}}
	for _, p := range []float64{30, 45, 60, 80, 100, 150} {
		perL := p * k / 1000
		v.Rows = append(v.Rows, crossRow{Cells: []string{money(p, "EUR") + " per t CO2", money(perL, "EUR"), money(perL*1000, "EUR")}})
	}
	v.Lead = fmt.Sprintf("From 2028 the EU's second emissions trading system (ETS2) puts a price on the CO2 of road fuel: fuel suppliers buy an allowance per tonne of CO2 their fuel emits and pass it on in the price. At %.2f kg CO2 per litre of diesel, each €10 per tonne adds %s per litre.",
		k, money(10*k/1000, "EUR"))
	v.Body = []template.HTML{
		template.HTML(`ETS2 is Chapter IVa of the <a href="https://eur-lex.europa.eu/eli/dir/2003/87/oj">EU ETS Directive (2003/87/EC)</a>, added by Directive (EU) 2023/959. It covers fuel released for consumption for road transport, buildings and further sectors. The amended European Climate Law, adopted by the Council on 5 March 2026, moved its start from 2027 to 2028.`),
		template.HTML(fmt.Sprintf(`The price is set by the market; the table works it out for a range of prices. Per litre: price × %.2f kg ÷ 1,000. The %.2f kg is diesel's tank-to-wheel CO2 per litre in EN 16258:2012, Annex A, the factor the calculator uses for taxes per litre.`, k, k)),
		template.HTML(`For the CO2 prices on diesel that countries charge today, see <a href="` + s.prefix + `/tolls/co2-tax-diesel">national CO2 taxes on diesel</a>.`),
	}
	v.Notes = []string{"The calculator prices ETS2 on a trip's road fuel from 2028 at the price you give (ets2_eur_per_t)."}
	v.Sources = []tariffs.Source{{Title: "Directive 2003/87/EC (EU ETS), consolidated: Chapter IVa (ETS2)", URL: "https://eur-lex.europa.eu/eli/dir/2003/87/oj"},
		{Title: "European Commission: ETS2: buildings, road transport and additional sectors", URL: "https://climate.ec.europa.eu/eu-action/carbon-markets/ets2-buildings-road-transport-and-additional-sectors_en"}}
	ld := s.datasetLD("/tolls/ets2-diesel", "ETS2 cost per litre of diesel", v.Lead, "European Union", nil, "2028-01-01")
	v.Head = s.mkHead("/tolls/ets2-diesel", "ETS2 from 2028: what it adds per litre of diesel", short(v.Lead, 300), ld,
		link{"Truck tolls", s.prefix + "/tolls"}, link{"ETS2 per litre of diesel", s.prefix + "/tolls/ets2-diesel"})
	v.Updated = day
	cd := card{Kicker: "carbon-cost · fuel CO2", Title: "ETS2 from 2028: the cost per litre of diesel", Big: money(45*k/1000, "EUR") + " per litre",
		BigNote: "at €45 per tonne of CO2", Accent: fmt.Sprintf("%s per litre for each €10/t", money(10*k/1000, "EUR")), AccentCO: "carbon",
		Footer: hostPath(s.base) + "/tolls/ets2-diesel"}
	return v, cd
}

// fuelPage: each country's national CO2 price on diesel, per litre.
func (s *Site) fuelPage(cs []*country, day string, today time.Time) (crossView, card) {
	v := crossView{H1: "National CO2 taxes on diesel by country",
		Cols: []string{"Country", "What the law charges", "Per litre of diesel", "In force from", "Coming"}}
	var all []*tariffs.Dataset
	for _, c := range cs {
		for _, sc := range c.of(tariffs.FuelCO2) {
			ds := sc.Current
			if ds == nil {
				continue
			}
			all = append(all, ds)
			rate, perL := fuelRate(ds, today)
			var coming []string
			for _, up := range sc.Upcoming {
				r, l := fuelRate(up, today)
				coming = append(coming, fmt.Sprintf("%s: %s (%s per litre)", dateName(up.ValidFrom), r, l))
			}
			v.Rows = append(v.Rows, crossRow{Cells: []string{c.Name + ": " + ds.Name, rate, perL, dateName(ds.ValidFrom), strings.Join(coming, "; ")},
				Href: s.prefix + "/tolls/" + c.Slug})
		}
	}
	v.Lead = fmt.Sprintf("%d European countries put a CO2 price on diesel of their own, on top of fuel excise duty: per tonne of CO2 or per litre. The rates in force on %s, per litre of diesel in euros.", len(v.Rows), dateName(day))
	v.Notes = []string{fmt.Sprintf("Per tonne of CO2 converts to per litre at %.2f kg CO2 per litre of diesel (EN 16258:2012, Annex A). Other currencies at the ECB reference rate (DKK at its ERM II central rate).", cost.DieselKgCO2PerL),
		"The calculator charges these on the fuel a trip burns in each country (or where you say the fuel is bought)."}
	v.Sources = sources(all...)
	ld := s.datasetLD("/tolls/co2-tax-diesel", "National CO2 taxes on diesel in Europe", v.Lead, "Europe", nil, "")
	v.Head = s.mkHead("/tolls/co2-tax-diesel", fmt.Sprintf("CO2 taxes on diesel by country %d: the rate per litre", today.Year()), short(v.Lead, 300), ld,
		link{"Truck tolls", s.prefix + "/tolls"}, link{"CO2 taxes on diesel", s.prefix + "/tolls/co2-tax-diesel"})
	v.Updated = day
	sortRows(v.Rows)
	cd := card{Kicker: "carbon-cost · fuel CO2", Title: "National CO2 taxes on diesel", Big: fmt.Sprintf("%d countries", len(v.Rows)),
		BigNote: "the CO2 price per litre of diesel, from the law", Footer: hostPath(s.base) + "/tolls/co2-tax-diesel"}
	return v, cd
}

package fuel

import (
	"fmt"
	"math"
	"time"
)

// Refund is a country's partial refund of the excise duty on diesel for
// road hauliers (Directive 2003/96/EC, Art. 7(2), commercial gas oil):
// EUR per litre bought there, for trucks of at least MinMassKg (their
// technically permissible maximum laden mass) and Euro class MinEuro,
// from From to To (inclusive; "" open). The rate is EURPerL, set by law;
// or, where the law refunds the excise above a floor, the Weekly Oil
// Bulletin's duties of the week less Floor.
type Refund struct {
	Country   string
	From, To  string
	EURPerL   float64
	Floor     float64
	MinMassKg int
	MinEuro   int
	// Note says what the rate leaves out (regional rates, conditions).
	Note  string
	Law   string
	Title string
	URL   string
}

// Refunds are the schemes in: a rate set by law, or a floor under the
// excise. Other countries' refunds aren't here yet: give
// diesel_eur_per_l_by_country net of their refund.
var Refunds = []Refund{
	{Country: "ES", From: "2024-01-01", To: "2026-03-21", EURPerL: 0.049, MinMassKg: 7500,
		Note:  "EUR 49 per 1,000 litres: the general rate of epígrafe 1.3 (EUR 307) less 306, plus 48 of the special rate; paid only on litres bought with a gasóleo profesional card, up to 50,000 litres a vehicle a year",
		Law:   "Ley 38/1992 de Impuestos Especiales, art. 52 bis.6",
		Title: "Diputación Foral de Bizkaia: Gasóleo profesional",
		URL:   "https://www.bizkaia.eus/es/gasoleo-profesional"},
	{Country: "ES", From: "2026-03-22", To: "2026-06-30", MinMassKg: 7500,
		Note:  "zero while the excise on diesel was cut (June's conditional EUR 49 did not apply: the cut went on)",
		Law:   "Real Decreto-ley 7/2026, art. 39",
		Title: "BOE: Real Decreto-ley 7/2026, de 20 de marzo (consolidated text)",
		URL:   "https://www.boe.es/buscar/pdf/2026/BOE-A-2026-6544-consolidado.pdf"},
	{Country: "ES", From: "2026-07-01", To: "2026-09-30", MinMassKg: 7500,
		Note:  "zero while the excise on diesel was cut",
		Law:   "Real Decreto-ley 18/2026, art. 8",
		Title: "BOE: Real Decreto-ley 18/2026, de 29 de junio (consolidated text)",
		URL:   "https://www.boe.es/buscar/pdf/2026/BOE-A-2026-14112-consolidado.pdf"},
	{Country: "ES", From: "2026-10-01", To: "2026-12-31", MinMassKg: 7500,
		Note:  "zero while the excise on diesel is cut",
		Law:   "Real Decreto-ley 25/2026, art. 16",
		Title: "BOE: Real Decreto-ley 25/2026, de 29 de septiembre (consolidated text)",
		URL:   "https://www.boe.es/buscar/pdf/2026/BOE-A-2026-20265-consolidado.pdf"},
	{Country: "ES", From: "2027-01-01", EURPerL: 0.049, MinMassKg: 7500,
		Note:  "EUR 49 per 1,000 litres again when the 2026 decree-laws end, unless a new one changes it; paid only on litres bought with a gasóleo profesional card, up to 50,000 litres a vehicle a year",
		Law:   "Ley 38/1992 de Impuestos Especiales, art. 52 bis.6",
		Title: "Diputación Foral de Bizkaia: Gasóleo profesional",
		URL:   "https://www.bizkaia.eus/es/gasoleo-profesional"},
	{Country: "IT", From: "2024-01-01", Floor: 0.40322, MinMassKg: 7500, MinEuro: 5,
		Note:  "the excise of the bulletin's week above EUR 403.22 per 1,000 litres; the Customs and Monopolies Agency refunds by the day the excise changed, each quarter",
		Law:   "Decreto legislativo 504/1995, art. 24-ter and Tabella A, punto 4-bis: the excise on commercial gas oil, EUR 403.22 per 1,000 litres",
		Title: "Agenzia delle Dogane e dei Monopoli: Benefici sul gasolio commerciale utilizzato nel settore del trasporto (informativa, prot. 0611759, 26 September 2025)",
		URL:   "https://www.bo.cna.it/wp-content/uploads/2025/10/ACCISA-CIRCOLARE-ADM-PROT-0611759-DEL-26-SETTEMBRE-2025.pdf"},
	{Country: "FR", From: "2025-01-01", To: "2025-12-31", EURPerL: 0.1556, MinMassKg: 7500,
		Note:  "the rate for diesel bought in the regions other than Île-de-France (EUR 17.45/hl) and Corsica (EUR 14.21/hl)",
		Law:   "Code des impositions sur les biens et services, art. L.312-53: the difference between the excise on diesel and EUR 45.19/hl",
		Title: "impots.gouv.fr: Accise sur les produits pétroliers (ex-TICPE), remboursements des taxis et transporteurs",
		URL:   "https://www.impots.gouv.fr/accise-sur-les-produits-petroliers-ex-ticpe-remboursements-des-taxis-et-transporteurs"},
	{Country: "FR", From: "2026-01-01", EURPerL: 0.1556, MinMassKg: 7500,
		Note:  "the rate for diesel bought in mainland France (Corsica: EUR 14.21/hl)",
		Law:   "Code des impositions sur les biens et services, art. L.312-53: the difference between the excise on diesel and EUR 45.19/hl",
		Title: "impots.gouv.fr: Accise sur les produits pétroliers (ex-TICPE), remboursements des taxis et transporteurs",
		URL:   "https://www.impots.gouv.fr/accise-sur-les-produits-petroliers-ex-ticpe-remboursements-des-taxis-et-transporteurs"},
}

// RefundOn is a country's refund for diesel bought on a day, if any, with
// its rate: for a floor, the duties of the bulletin in force less it
// (none when the duties are at or below the floor, or unknown).
func RefundOn(country string, day time.Time) (Refund, bool) {
	d := day.Format(time.DateOnly)
	for _, r := range Refunds {
		if r.Country != country || d < r.From || r.To != "" && d > r.To {
			continue
		}
		if r.Floor > 0 {
			b, _, ok := DutiesOn(day)
			v := b.EURPerL[country] - r.Floor
			if !ok || b.EURPerL[country] == 0 || v <= 0 {
				return Refund{}, false
			}
			r.EURPerL = math.Round(v*10000) / 10000
			r.Note = fmt.Sprintf("%s: EUR %.4f per litre in the bulletin of %s", r.Note, b.EURPerL[country], b.Date)
		}
		return r, true
	}
	return Refund{}, false
}

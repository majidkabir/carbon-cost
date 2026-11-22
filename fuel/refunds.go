package fuel

import "time"

// Refund is a country's partial refund of the excise duty on diesel for
// road hauliers (Directive 2003/96/EC, Art. 7(2), commercial gas oil):
// EUR per litre bought there, for trucks of at least MinMassKg (their
// technically permissible maximum laden mass) and Euro class MinEuro,
// from From to To (inclusive; "" open).
type Refund struct {
	Country   string
	From, To  string
	EURPerL   float64
	MinMassKg int
	MinEuro   int
	// Note says what the rate leaves out (regional rates, conditions).
	Note  string
	Law   string
	Title string
	URL   string
}

// Refunds are the schemes with a rate set by law. Countries whose refund
// follows a monthly or weekly excise rate aren't here yet: give
// diesel_eur_per_l_by_country net of their refund.
var Refunds = []Refund{
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

// RefundOn is a country's refund for diesel bought on a day, if any.
func RefundOn(country string, day time.Time) (Refund, bool) {
	d := day.Format(time.DateOnly)
	for _, r := range Refunds {
		if r.Country == country && d >= r.From && (r.To == "" || d <= r.To) {
			return r, true
		}
	}
	return Refund{}, false
}

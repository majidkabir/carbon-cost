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
// or, where the law refunds the excise above a floor, the excise in force
// (the Weekly Oil Bulletin's) less Floor, for countries on the euro.
type Refund struct {
	// Country (ISO 3166-1 alpha-2), From and To, EURPerL and Floor: see
	// Refund.
	Country  string
	From, To string
	EURPerL  float64
	Floor    float64
	// Duties: the floor is under all the duties other than VAT (the
	// bulletin's), not the excise alone.
	Duties bool
	// LocalPerL is the rate where the law sets it in another currency
	// (Currency, ISO 4217): the caller converts it, as the trip's other
	// amounts in that currency.
	LocalPerL float64
	Currency  string
	// MinMassKg and MinEuro: see Refund.
	MinMassKg int
	MinEuro   int
	// Note says what the rate leaves out (regional rates, conditions).
	Note string
	// Law cites the law that sets the refund, and Title and URL the
	// document it is published in.
	Law   string
	Title string
	URL   string
}

// Refunds are the schemes in: a rate set by law, or a floor under the
// excise. Other countries' refunds aren't here yet: give
// diesel_eur_per_l_by_country net of their refund.
var Refunds = []Refund{
	{Country: "SI", From: "2024-01-01", Floor: 0.33, MinMassKg: 7500,
		Note:  "FURS takes the month's average excise; this is the one in force on the day",
		Law:   "Zakon o trošarinah (ZTro-1), 95. člen: the month's average excise on diesel less the minimum of Directive 2003/96/EC, art. 7",
		Title: "Finančna uprava Republike Slovenije: Vračilo trošarine za komercialni prevoz",
		URL:   "https://www.fu.gov.si/poslovni_dogodki_podjetja/vracilo_trosarine_za_komercialni_prevoz/"},
	{Country: "HR", From: "2024-01-01", Floor: 0.33, MinMassKg: 7500,
		Note:  "on diesel paid for cashless in Croatia",
		Law:   "Zakon o trošarinama (Narodne novine 106/2018), čl. 104: the excise on diesel less the EU minimum of EUR 330 per 1,000 litres",
		Title: "Narodne novine 2019: Pravilnik o ostvarivanju prava na povrat dijela plaćene trošarine za dizelsko gorivo u komercijalnom prijevozu robe i putnika",
		URL:   "https://narodne-novine.nn.hr/clanci/sluzbeni/2019_02_12_241.html"},
	{Country: "HU", From: "2025-01-01", To: "2025-12-31", LocalPerL: 17, Currency: "HUF", MinMassKg: 7500,
		Note:  "HUF 17 per litre, set by NAV for each quarter of 2025",
		Law:   "2016. évi LXVIII. törvény (Jöt.), 113. § (5)",
		Title: "Nemzeti Adó- és Vámhivatal: Adó-visszaigénylés (kereskedelmi gázolaj)",
		URL:   "https://nav.gov.hu/ugyfeliranytu/adokulcsok_jarulekmertekek/valorizalt-adomertekek/jovedeki-ado/ado-visszaigenyles"},
	{Country: "HU", From: "2026-01-01", To: "2026-03-09", LocalPerL: 20, Currency: "HUF", MinMassKg: 7500,
		Note:  "HUF 20 per litre, set by NAV for the first quarter of 2026",
		Law:   "2016. évi LXVIII. törvény (Jöt.), 113. § (5)",
		Title: "Nemzeti Adó- és Vámhivatal: Adó-visszaigénylés (kereskedelmi gázolaj)",
		URL:   "https://nav.gov.hu/ugyfeliranytu/adokulcsok_jarulekmertekek/valorizalt-adomertekek/jovedeki-ado/ado-visszaigenyles"},
	{Country: "HU", From: "2026-03-10", To: "2026-05-13", Currency: "HUF", MinMassKg: 7500,
		Note:  "zero for MSZ-EN 590 diesel taxed at the crisis rate",
		Law:   "51/2026. (III. 9.) Korm. rendelet, 1. § b); 2016. évi LXVIII. törvény (Jöt.), 113. § (5)",
		Title: "Nemzeti Adó- és Vámhivatal: Adó-visszaigénylés (kereskedelmi gázolaj)",
		URL:   "https://nav.gov.hu/ugyfeliranytu/adokulcsok_jarulekmertekek/valorizalt-adomertekek/jovedeki-ado/ado-visszaigenyles"},
	{Country: "HU", From: "2026-05-14", Currency: "HUF", MinMassKg: 7500,
		Note:  "zero while MSZ-EN 590 diesel is taxed at the EU minimum",
		Law:   "2016. évi LXVIII. törvény (Jöt.), 110. § (6) b) and 113. § (5)",
		Title: "Nemzeti Adó- és Vámhivatal: Adó-visszaigénylés (kereskedelmi gázolaj)",
		URL:   "https://nav.gov.hu/ugyfeliranytu/adokulcsok_jarulekmertekek/valorizalt-adomertekek/jovedeki-ado/ado-visszaigenyles"},
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
		Note:  "Euro V and VI; the Customs and Monopolies Agency refunds by the day the excise changed",
		Law:   "Decreto legislativo 504/1995, art. 24-ter and Tabella A, punto 4-bis: the excise on commercial gas oil, EUR 403.22 per 1,000 litres",
		Title: "Agenzia delle Dogane e dei Monopoli: Benefici sul gasolio commerciale utilizzato nel settore del trasporto (informativa, prot. 0611759, 26 September 2025)",
		URL:   "https://www.bo.cna.it/wp-content/uploads/2025/10/ACCISA-CIRCOLARE-ADM-PROT-0611759-DEL-26-SETTEMBRE-2025.pdf"},
	{Country: "PT", From: "2024-10-30", Floor: 0.33, Duties: true, MinMassKg: 35000,
		Note:  "for trucks for hire registered in the EU, on diesel bought with a fleet card at stations the AT authorises, up to 40,000 litres a vehicle a year; the taxes are the bulletin's duties other than VAT (the ISP and the CO2 adicionamento)",
		Law:   "Código dos Impostos Especiais de Consumo, art. 93.º-A, and Portaria n.º 246-A/2016: the ISP and CO2 adicionamento above the EU minimum of EUR 330 per 1,000 litres",
		Title: "Autoridade Tributária e Aduaneira: Ofício Circulado n.º 25041/2024, regime de reembolso parcial de impostos – gasóleo profissional",
		URL:   "https://info-aduaneiro.portaldasfinancas.gov.pt/pt/legislacao_aduaneira/oficios_circulados_doclib/Documents/Oficio_Circulado_25041_2024.pdf"},
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
// (zero when the duties are at or below the floor; none when unknown).
func RefundOn(country string, day time.Time) (Refund, bool) {
	d := day.Format(time.DateOnly)
	for _, r := range Refunds {
		if r.Country != country || d < r.From || r.To != "" && d > r.To {
			continue
		}
		if r.Floor > 0 {
			on, what := ExciseOn, "the excise"
			if r.Duties {
				on, what = DutiesOn, "the duties other than VAT"
			}
			b, _, ok := on(day)
			if !ok || b.EURPerL[country] == 0 {
				return Refund{}, false
			}
			r.EURPerL = math.Round(math.Max(0, b.EURPerL[country]-r.Floor)*10000) / 10000
			r.Note = fmt.Sprintf("%s: %s EUR %.4f per litre (the Weekly Oil Bulletin, in force from %s)", r.Note, what, b.EURPerL[country], b.Date)
		}
		return r, true
	}
	return Refund{}, false
}

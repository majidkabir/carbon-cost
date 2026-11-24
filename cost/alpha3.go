package cost

// alpha3 maps ISO 3166-1 alpha-2 codes to alpha-3, for Sootcase's grid
// factors: the countries the tool prices.
var alpha3 = map[string]string{
	"AD": "AND", "AL": "ALB", "AT": "AUT", "BA": "BIH", "BE": "BEL", "BG": "BGR", "BY": "BLR", "CH": "CHE", "CY": "CYP", "CZ": "CZE",
	"DE": "DEU", "DK": "DNK", "EE": "EST", "ES": "ESP", "FI": "FIN", "FO": "FRO", "FR": "FRA", "GB": "GBR", "GR": "GRC", "HR": "HRV",
	"HU": "HUN", "IE": "IRL", "IS": "ISL", "IT": "ITA", "LI": "LIE", "LT": "LTU", "LU": "LUX", "LV": "LVA", "MD": "MDA", "ME": "MNE",
	"MK": "MKD", "MT": "MLT", "NL": "NLD", "NO": "NOR", "PL": "POL", "PT": "PRT", "RO": "ROU", "RS": "SRB", "SE": "SWE", "SI": "SVN",
	"SK": "SVK", "TR": "TUR", "UA": "UKR", "XK": "XKX",
}

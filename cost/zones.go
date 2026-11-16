package cost

import (
	"time"
	_ "time/tzdata" // the zones below, also where the system has none
)

// zones are the countries' time zones (IANA), for the local time at a
// toll station: the free hours, rush hours and days the tolls count by.
var zones = map[string]string{
	"AL": "Europe/Tirane", "AT": "Europe/Vienna", "BA": "Europe/Sarajevo", "BE": "Europe/Brussels",
	"BG": "Europe/Sofia", "CH": "Europe/Zurich", "CZ": "Europe/Prague", "DE": "Europe/Berlin",
	"DK": "Europe/Copenhagen", "EE": "Europe/Tallinn", "ES": "Europe/Madrid", "FI": "Europe/Helsinki",
	"FR": "Europe/Paris", "GB": "Europe/London", "GR": "Europe/Athens", "HR": "Europe/Zagreb",
	"HU": "Europe/Budapest", "IE": "Europe/Dublin", "IT": "Europe/Rome", "LI": "Europe/Vaduz",
	"LT": "Europe/Vilnius", "LU": "Europe/Luxembourg", "LV": "Europe/Riga", "MD": "Europe/Chisinau",
	"ME": "Europe/Podgorica", "MK": "Europe/Skopje", "NL": "Europe/Amsterdam", "NO": "Europe/Oslo",
	"PL": "Europe/Warsaw", "PT": "Europe/Lisbon", "RO": "Europe/Bucharest", "RS": "Europe/Belgrade",
	"SE": "Europe/Stockholm", "SI": "Europe/Ljubljana", "SK": "Europe/Bratislava", "TR": "Europe/Istanbul",
	"UA": "Europe/Kyiv", "XK": "Europe/Belgrade",
}

// zone is the country's time zone, UTC if not known.
func zone(country string) *time.Location {
	if z, ok := zones[country]; ok {
		if l, err := time.LoadLocation(z); err == nil {
			return l
		}
	}
	return time.UTC
}

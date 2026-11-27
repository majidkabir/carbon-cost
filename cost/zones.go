package cost

import (
	"sync"
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
	"UA": "Europe/Kyiv", "XK": "Europe/Belgrade", "IS": "Atlantic/Reykjavik", "AD": "Europe/Andorra",
	"FO": "Atlantic/Faroe", "BY": "Europe/Minsk", "MC": "Europe/Monaco", "SM": "Europe/San_Marino",
	"VA": "Europe/Vatican", "GI": "Europe/Gibraltar", "MT": "Europe/Malta", "CY": "Asia/Nicosia",
	"RU": "Europe/Moscow", "GE": "Asia/Tbilisi", "AM": "Asia/Yerevan", "AZ": "Asia/Baku",
	"MA": "Africa/Casablanca", "DZ": "Africa/Algiers", "TN": "Africa/Tunis", "IM": "Europe/Isle_of_Man",
	"JE": "Europe/Jersey", "GG": "Europe/Guernsey",
}

// zone is the country's time zone, UTC if not known.
func zone(country string) *time.Location {
	if l, ok := loaded.Load(country); ok {
		return l.(*time.Location)
	}
	l := time.UTC
	if z, ok := zones[country]; ok {
		if x, err := time.LoadLocation(z); err == nil {
			l = x
		}
	}
	loaded.Store(country, l)
	return l
}

// loaded are the zones read (a trip's days are counted at each departure
// minute).
var loaded sync.Map

// LocalZone is the country's time zone, Central European Time where it
// isn't known: the day a trip there is on.
func LocalZone(country string) *time.Location {
	if l := zone(country); l != time.UTC {
		return l
	}
	return zone("BE")
}

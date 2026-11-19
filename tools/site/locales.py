"""Writes site/i18n/locales.json from the Unicode CLDR (Python's babel):
for each language the toll pages are in, its own name, the countries'
names, its decimal and group separators, its currency and percent
patterns, its long date pattern and its months (in a date's form).

Usage: python3 tools/site/locales.py site/i18n/locales.json
"""
import json, sys

import babel
from babel import Locale
from babel.dates import get_date_format, get_month_names

# The pages' language codes (BCP 47) and their CLDR locales.
LANGS = {"en": "en_GB", "ca": "ca", "sq": "sq", "de": "de", "bs": "bs", "nl": "nl", "fr": "fr", "bg": "bg", "ru": "ru", "it": "it",
         "cs": "cs", "da": "da", "et": "et", "es": "es", "fi": "fi", "sv": "sv", "fo": "fo", "el": "el", "hr": "hr", "hu": "hu",
         "is": "is", "lt": "lt", "lv": "lv", "ro": "ro", "sr": "sr_Latn", "mk": "mk", "nb": "nb", "pl": "pl", "pt": "pt_PT",
         "sl": "sl", "sk": "sk", "tr": "tr"}
COUNTRIES = ["AD", "AL", "AT", "BA", "BE", "BG", "BY", "CH", "CZ", "DE", "DK", "EE", "ES", "FI", "FO", "FR", "GB", "GR", "HR", "HU",
             "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MD", "ME", "MK", "NL", "NO", "PL", "PT", "RO", "RS", "SE", "SI", "SK", "TR"]


def main(out):
    data = {"cldr": f"Unicode CLDR via babel {babel.__version__}", "languages": {}}
    for code, cl in LANGS.items():
        loc = Locale.parse(cl)
        sym = loc.number_symbols["latn"]
        name = loc.language_name if code != "sr" else Locale.parse("sr_Latn").language_name
        data["languages"][code] = {
            "locale": cl, "name": name[:1].upper() + name[1:],
            "countries": {c: loc.territories[c] for c in COUNTRIES},
            "decimal": sym["decimal"], "group": sym["group"],
            "currency": loc.currency_formats["standard"].pattern.split(";")[0],
            "percent": loc.percent_formats[None].pattern.split(";")[0],
            "date": get_date_format("long", locale=cl).pattern,
            "months": [get_month_names("wide", context="format", locale=cl)[m] for m in range(1, 13)],
        }
    json.dump(data, open(out, "w"), ensure_ascii=False, indent=1)
    print(out, len(data["languages"]), "languages")


if __name__ == "__main__":
    main(*sys.argv[1:])

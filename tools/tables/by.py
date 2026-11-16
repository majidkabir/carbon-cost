"""Builds Belarus's BelToll table (by-<valid_from>.json) from the Ministry of
Transport and Communications' resolution on toll road tariffs, as the
National Centre of Legislation and Legal Information publishes it on
ETALON-online (fetched as by-mintrans-42-2026.html; else the text read in
Chrome, browser/by-mintrans-42-2026.txt).

Table 1 of annex 1: euro per km on the toll roads for vehicles over 3.5 t,
by axles (2, 3, 4 or more); BelToll counts the axles of the vehicle with its
trailers. Table 2 raises the rate tenfold on stretches of the roads into
Minsk when a vehicle drives two or more of them within an hour (transit
through Minsk): not modelled, said in the table's text.

The toll roads are those of the list in the Regulation approved by Council
of Ministers resolution No. 340 of 30 April 2013; carbon-cost places them on
the ways OpenStreetMap tags as toll roads (roads/data/by.json.gz, built by
tools/roads/build.py), priced at the "motorway" rows.

Usage: python3 by.py <fetched dir> <out dir>
"""
import html
import json
import os
import re
import sys

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
          "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
SOURCE = "https://etalonline.by/document/?regnum=Y226w0876c"
HELP = "https://beltoll.by/ru/help"


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def main(fetched, out):
    p = os.path.join(fetched, "by-mintrans-42-2026.html")
    t = text(p) if os.path.exists(p) else ""
    if "Таблица 1 Категория транспортного средства" not in t:
        # The workflow's copy is missing or not the document: the text read in Chrome.
        cap = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser", "by-mintrans-42-2026.txt")
        t = re.sub(r"\s+", " ", "\n".join(l for l in open(cap, encoding="utf-8") if not l.startswith("#")))
        print("Belarus: read from", cap)
    head = re.search(r"ПОСТАНОВЛЕНИЕ МИНИСТЕРСТВА ТРАНСПОРТА И КОММУНИКАЦИЙ РЕСПУБЛИКИ БЕЛАРУСЬ (\d+) (\w+) (\d{4}) г\. ?№ ?(\d+)", t)
    force = re.search(r"Настоящее постановление вступает в силу с (\d+) (\w+) (\d{4}) г\.", t)
    t1 = re.search(r"Таблица 1 Категория транспортного средства Количество осей Тариф за 1 км/евро "
                   r"Транспортное средство с допустимой общей массой более 3,5 тонны 2 (\d+,\d+) 3 (\d+,\d+) 4 и более (\d+,\d+) ", t)
    t2 = re.search(r"Таблица 2 Идентификация дороги Начало расчетного сегмента, от километра Конец расчетного сегмента, до километра Тариф за 1 км/евро (.{0,600}?) Приложение 2", t)
    if not (head and force and t1 and t2) or force.group(2) not in MONTHS or head.group(2) not in MONTHS:
        sys.exit("Belarus: the resolution's date, entry into force or tables 1 and 2 not read")
    factor = re.search(r"с повышающим коэффициентом (\d+,\d+)", t2.group(1))
    segs = re.findall(r"([МР]-\d+(?:/Е \d+)?) (\d+,\d+) (\d+,\d+)", t2.group(1))
    if not factor or len(segs) < 5:
        sys.exit("Belarus: table 2's stretches not read")
    start = f"{force.group(3)}-{MONTHS[force.group(2)]:02d}-{int(force.group(1)):02d}"
    r2, r3, r4 = (float(x.replace(",", ".")) for x in t1.groups())
    stretches = ", ".join(f"{r} km {a}-{b}" for r, a, b in segs)
    law = (f"Resolution of the Ministry of Transport and Communications No. {head.group(4)} of {head.group(3)}-{MONTHS[head.group(2)]:02d}-{int(head.group(1)):02d}, "
                     f"in force from {start}, annex 1, table 1: EUR {r2} per km for vehicles over 3.5 t with 2 axles, {r3} with 3, {r4} with 4 or more; "
                     "BelToll counts the axles of the vehicle with its trailers and semi-trailers. "
                     f"Table 2 (not modelled): the rate times {factor.group(1)} on {stretches} when a vehicle drives two or more of them within an hour. "
                     "Toll roads: the list of the Regulation approved by Council of Ministers resolution No. 340 of 30 April 2013, "
                     "placed on the ways OpenStreetMap tags as toll roads.")
    write(out, table(start, (r2, r3, r4), law,
                     [{"title": f"Постановление Министерства транспорта и коммуникаций Республики Беларусь от {int(head.group(1))} {head.group(2)} {head.group(3)} г. № {head.group(4)} (ETALON-online)", "url": SOURCE}]))


def table(start, rates, law, sources):
    """A BelToll table: EUR per km on the toll roads by axles (2, 3, 4+)."""
    r2, r3, r4 = rates
    return {"country": "BY", "currency": "EUR", "valid_from": start, "name": "BelToll", "law": law,
            "sources": sources + [{"title": "BelToll: Помощь (the number of axles includes trailers)", "url": HELP}],
            "vehicles": "Vehicles over 3.5 t", "min_kg": 3501,
            "tolled_roads": "BelToll toll roads (the list of the Regulation approved by resolution No. 340), as OpenStreetMap tags them.",
            "motorway_share": 1,
            "rows": [{"component": "toll", "road": "motorway", "min_kg": 3501, "max_axles": 2, "rate": r2},
                     {"component": "toll", "road": "motorway", "min_kg": 3501, "min_axles": 3, "max_axles": 3, "rate": r3},
                     {"component": "toll", "road": "motorway", "min_kg": 3501, "min_axles": 4, "rate": r4}]}


def write(out, t):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"by-{t['valid_from']}.json")
    json.dump(t, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, [r["rate"] for r in t["rows"]])


if __name__ == "__main__":
    main(*sys.argv[1:])

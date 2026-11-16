"""Builds the Estonian road user charge table from the Liiklusseadus in
force, as Riigi Teataja's public API gives it (fetch.py's ee-ls.json and
ee-ls-text.html).

Usage: python3 ee.py fetched/ out-dir -> out-dir/ee-<date>.json

§ 190^3 sets the charge in euro for 24 hours, 7, 30, 90 and 365 days, by
the summed maximum masses of the truck and its trailer (over 3.5 to 12 t,
over 12 t), their total axles and the truck's EURO class; zero-emission
trucks (Regulation (EU) 2019/1242 Art. 3(11)) have their own rates. The
table keeps the 24-hour rate. Each paragraph is read from its own text
("Kui ... on teekasutustasu määrad ...: 1) 24 tunni määr on N eurot"),
and the table is valid from the latest entry-into-force date noted in
§ 190^3 ("jõust. dd.mm.yyyy").
"""
import datetime, html, json, os, re, sys

EURO = [("EURO 0, EURO I või EURO II", [0, 1, 2]), ("EURO III", [3]), ("EURO IV, EURO V või EEV", [4, 5]),
        ("EURO VI või vähem saastavasse", [6])]


def text(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<sup>(\d+)</sup>", r"^\1", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def main(fetched, out):
    t = text(os.path.join(fetched, "ee-ls-text.html"))
    sec = t[t.index("§ 190^3."):t.index("§ 190^4.")]
    paras = re.split(r" \((\d+(?:\^\d+)?)\) ", sec)
    rows = []
    for no, p in zip(paras[1::2], paras[2::2]):
        m = re.search(r"1\) 24 tunni määr on (\d+) eurot", p)
        if not m:
            continue
        rate = int(m.group(1))
        head = p[:p.index("on teekasutustasu määrad")]
        row = {"component": "toll"}
        if "ei ületa 12 000 kilogrammi" in head:
            row.update(min_kg=3501, max_kg=12000)
        elif "üle 12 000 kilogrammi" in head:
            row["min_kg"] = 12001
        else:
            sys.exit(f"§ 190^3 ({no}): no mass")
        if "kuni kolm telge" in head:
            row["max_axles"] = 3
        elif "vähemalt kolm telge" in head:
            row["min_axles"] = 3
        elif "vähemalt neli telge" in head:
            row["min_axles"] = 4
        if "heiteta" in head:
            row["co2_class"] = [5]
        else:
            for label, euro in EURO:
                if "heitgaasiklassi " + label in head:
                    row["euro"] = euro
            if "euro" not in row and "iga heitgaasiklassi" not in p:
                sys.exit(f"§ 190^3 ({no}): no EURO class")
        row["rate"] = rate
        # The paragraph's wording is in force from its latest amendment.
        when = sorted(f"{y}-{m}-{d}" for d, m, y in re.findall(r"jõust\. (\d\d)\.(\d\d)\.(\d{4})", p))
        rows.append((when[-1] if when else "", row))
    if len(rows) != 12:
        sys.exit(f"§ 190^3: {len(rows)} rate paragraphs, want 12")
    dates = sorted(f"{y}-{m}-{d}" for d, m, y in re.findall(r"jõust\. (\d\d)\.(\d\d)\.(\d{4})", sec))
    write(out, dates[-1], None, [r for _, r in rows], "zero-emission trucks pay lower rates from 1 January 2026")
    # The text notes when each paragraph's wording came into force. Before
    # the latest date, the rates are those of the paragraphs already in
    # force then, if the later ones only added zero-emission rates (which
    # trucks without them paid by EURO class).
    later = [r for d, r in rows if d == dates[-1]]
    earlier = [d for d in dates if d < dates[-1]]
    if earlier and all("co2_class" in r for r in later):
        to = (datetime.date.fromisoformat(dates[-1]) - datetime.timedelta(days=1)).isoformat()
        write(out, earlier[-1], to, [r for d, r in rows if d < dates[-1]], f"the zero-emission rates came into force on {dates[-1]}; until then zero-emission trucks paid by EURO class")


def write(out, valid_from, valid_to, rows, zev):
    # Zero-emission rows first, the more axles first.
    rows.sort(key=lambda r: ("co2_class" not in r, -r.get("min_axles", 0)))
    tb = {
        "country": "EE", "currency": "EUR", "valid_from": valid_from,
        "name": "Estonian road user charge (teekasutustasu)",
        "law": "Liiklusseadus § 190^1-190^13; rates in § 190^3 (as amended, RT I, 22.12.2023, 1): a time-based charge in euro for 24 hours, 7, 30, 90 or 365 days, by the summed maximum masses of the truck and trailer (over 3.5 to 12 t, over 12 t), their total axles and the truck's EURO class; " + zev + ". The table keeps the 24-hour rate. A fee, without VAT.",
        "sources": [{"title": "Liiklusseadus, version in force (Riigi Teataja)", "url": "https://www.riigiteataja.ee/akt/113032019015?leiaKehtiv"}],
        "vehicles": "Trucks over 3.5 t maximum mass, with their trailers",
        "min_kg": 3501,
        "tolled_roads": "All public roads (§ 190^1).",
        "per_day": True,
        "day": "24h",
        "rows": rows,
    }
    if valid_to:
        tb["valid_to"] = valid_to
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"ee-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])

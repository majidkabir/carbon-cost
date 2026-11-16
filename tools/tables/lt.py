"""Builds the Lithuanian road user charge table from the text of
Government resolution No 447 read in the browser
(tools/tables/browser/lt-447.txt; e-TAR refuses scripted requests).

Usage: python3 lt.py browser/lt-447.txt out-dir -> out-dir/lt-<date>.json

Point 1 of the annex gives the charge in euro for a year, a month, a week
and a day, by category (N1, N2, N3 for goods vehicles), the motor
vehicle's axles (no more than three, at least four; point 2.2: the axles
of the motor vehicle itself) and EURO class 0-VI. The table keeps the
daily rate, for N2 (over 3.5 t to 12 t) and N3 (over 12 t). The dates
are the consolidated edition's ("Suvestinė redakcija nuo ... iki ...").
Point 6 lists the roads the charge covers.
"""
import json, os, re, sys

MASS = {"N2": {"min_kg": 3501, "max_kg": 12000}, "N3": {"min_kg": 12001}}


def main(src, out):
    lines = open(src, encoding="utf-8").read().splitlines()
    ed = next(l for l in lines if l.startswith("# Edition:"))
    m = re.search(r"nuo (\d{4}-\d\d-\d\d) iki (\d{4}-\d\d-\d\d)", ed)
    valid_from, valid_to = m.group(1), m.group(2)
    body = [l.strip() for l in lines if not l.startswith("#")]
    rows = []
    for cat, mass in MASS.items():
        # The block: "Krovininės kelių transporto priemonės", cat, cat, the
        # header, then 7 EURO rows of 8 numbers (4 for <= 3 axles, 4 for >= 4).
        i = next(k for k in range(len(body) - 2) if body[k] == "Krovininės kelių transporto priemonės" and body[k + 1] == cat and body[k + 2] == cat)
        k = i + 3
        while not body[k].startswith("EURO"):
            k += 1
        header = body[i + 3:k]
        assert header[1:5] == ["metų tarifas", "mėnesio tarifas", "savaitės (7 dienų) tarifas", "dienos tarifas"], header
        for e, roman in enumerate(["0", "I", "II", "III", "IV", "V", "VI"]):
            assert body[k] == "EURO " + roman, body[k]
            nums = [int(x) for x in body[k + 1:k + 9]]
            rows.append({"component": "toll", **mass, "max_axles": 3, "euro": [e], "rate": nums[3]})
            rows.append({"component": "toll", **mass, "min_axles": 4, "euro": [e], "rate": nums[7]})
            k += 9
    roads = [re.sub(r"^6\.\d+\. ", "", l).rstrip(";.") for l in body if re.match(r"^6\.\d+\. ", l)]
    tb = {
        "country": "LT", "currency": "EUR", "valid_from": valid_from, "valid_to": valid_to,
        "name": "Lithuanian road user charge (kelių naudotojo mokestis)",
        "law": "Kelių priežiūros ir plėtros programos finansavimo įstatymas; Government resolution No 447 of 21 April 2005, annex point 1 (as amended by No 540 of 2023 and No 237 of 2026): a time-based charge in euro for a year, a month, a week or a day, by category (N2 over 3.5 to 12 t, N3 over 12 t), the motor vehicle's own axles (no more than three, or four or more; point 2.2) and EURO class. The table keeps the daily rate. Paid as an e-vignette, without VAT.",
        "sources": [{"title": "Nutarimas Nr. 447, consolidated (e-TAR)", "url": "https://www.e-tar.lt/portal/lt/legalAct/TAR.479B13E87700/asr"},
                    {"title": "Via Lietuva: User charge (electronic vignettes): a daily vignette expires 24 hours after its validity starts", "url": "https://vialietuva.lt/?p=1504"}],
        "vehicles": "Goods vehicles over 3.5 t (categories N2 and N3)",
        "min_kg": 3501,
        "tolled_roads": "The roads listed in point 6 of the annex: " + "; ".join(roads) + ".",
        "per_day": True,
        "day": "24h",
        "motor_axles": True,
        "rows": rows,
    }
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"lt-{valid_from}.json")
    json.dump(tb, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(rows), "rows,", len(roads), "roads")


if __name__ == "__main__":
    main(*sys.argv[1:])

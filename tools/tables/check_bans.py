"""Checks the driving-ban calendars transcribed into bans/data/*.json
against the text of the decrees fetch.py saved (pdftotext -layout of
<source id>.pdf): each transcribed day must be on a line of its month's
part of the text with its day number and both hours. Prints a warning
for each day it can't find, and for a source it can't read.

Usage: python3 check_bans.py fetched/ bans/data/
"""
import glob, json, os, re, sys

MONATE = ["jänner", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"]
MINES = ["ιανουαρίου", "φεβρουαρίου", "μαρτίου", "απριλίου", "μαΐου", "ιουνίου", "ιουλίου", "αυγούστου", "σεπτεμβρίου", "οκτωβρίου", "νοεμβρίου", "δεκεμβρίου"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def hours(hm):
    h, m = hm.split(":")
    h = int(h)
    # 9:00, 09:00, 9.00, 09.00, 9,00
    return {f"{h}{sep}{m}" for sep in ":.,"} | {f"{h:02d}{sep}{m}" for sep in ":.,"}


def main(fetched, folder):
    bad = 0
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        cal = json.load(open(path, encoding="utf-8"))
        name = os.path.basename(path)
        txt = os.path.join(fetched, cal["source"]["id"] + ".txt")
        if not os.path.exists(txt):
            print(f"::warning title={name}::{cal['source']['id']}.txt not fetched ({cal['source']['url']})")
            continue
        text = open(txt, encoding="utf-8", errors="replace").read().lower()
        if cal.get("check") == "words-de":
            # An Austrian decree names its days ("am Samstag 28. März
            # 2026", "an allen Samstagen vom 10. Jänner 2026 bis
            # einschließlich 14. März 2026") and hours ("von 7 bis 15 Uhr").
            flat = re.sub(r"\s+", " ", text)
            def said(d):
                y, m, dd = d.split("-")
                return re.search(rf"(?<!\d){int(dd)}\. {MONATE[int(m) - 1]} {y}", flat) or f"{dd}.{m}.{y}" in flat
            for d in cal["days"]:
                dates = [d["date"]] if d.get("date") else [d["from_date"], d["to_date"]]
                hrs = f"{int(d['from'][:2])} bis {int(d['to'][:2])} uhr"
                if not all(said(x) for x in dates) or hrs not in flat:
                    bad += 1
                    print(f"::warning title={name}::{'/'.join(dates)} {d['from']}-{d['to']} not found in {cal['source']['id']}.txt")
            print(f"{name}: {len(cal['days']) - bad} of {len(cal['days'])} days found in the decree's text")
            bad = 0
            continue
        if cal.get("check") == "words-gr":
            # A Greek ΦΕΚ names its days ("Παρασκευή 20 Φεβρουαρίου 2026",
            # "01 Ιουλίου 2026", "14/08/2026") and hours ("από ώρα 16:00
            # έως 21:00", "από ώρες 08.00 έως 22.00").
            flat = re.sub(r"\s+", " ", text)
            def said(d):
                y, m, dd = d.split("-")
                return re.search(rf"(?<!\d)0?{int(dd)} {MINES[int(m) - 1]} {y}", flat) or f"{dd}/{m}/{y}" in flat
            for d in cal["days"]:
                dates = ([d["date"]] if d.get("date") else [d["from_date"], d["to_date"]]) + d.get("except", [])
                f, t = (re.escape(x).replace(":", "[:.]") for x in (d["from"], d["to"]))
                if not all(said(x) for x in dates) or not re.search(rf"{f} έως {t}", flat):
                    bad += 1
                    print(f"::warning title={name}::{'/'.join(dates)} {d['from']}-{d['to']} not found in {cal['source']['id']}.txt")
            print(f"{name}: {len(cal['days']) - bad} of {len(cal['days'])} days found in the decision's text")
            bad = 0
            continue
        if cal.get("check") == "es-generated":
            # Spain's calendar is generated from the resolution's tables
            # (es_bans.py): generate it again and compare, both ways.
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import es_bans
            try:
                again = es_bans.calendar(open(txt, encoding="utf-8", errors="replace").read())
            except Exception as e:
                print(f"::warning title={name}::{cal['source']['id']}.txt not read: {e}; not found in it")
                continue
            have = {json.dumps(d, sort_keys=True, ensure_ascii=False) for d in cal["days"]}
            want = {json.dumps(d, sort_keys=True, ensure_ascii=False) for d in again}
            for d in sorted(have - want):
                print(f"::warning title={name}::{d[:200]} not found in {cal['source']['id']}.txt")
            for d in sorted(want - have):
                print(f"::warning title={name}::{d[:200]} of {cal['source']['id']}.txt not found in {name}: run es_bans.py")
            print(f"{name}: {len(have & want)} of {len(have)} days found in the resolution's tables, {len(want - have)} of them missing")
            continue
        if cal.get("check") == "words-fr":
            # A French arrêté names the dates in its sentences ("les
            # samedis 7 février, 14 février ... 2026") and the hours as
            # "de 7 h à 18 h": each date and each hour must be in it.
            flat = re.sub(r"\s+", " ", text)
            for d in cal["days"]:
                month, day = int(d["date"][5:7]), int(d["date"][8:10])
                words = (f"{day}er {MOIS[month - 1]}", f"1 {MOIS[month - 1]}") if day == 1 else (f"{day} {MOIS[month - 1]}",)
                h = [f"{int(x[:2])} h" for x in (d["from"], d["to"])]
                if not any(re.search(rf"(?<!\d){w}", flat) for w in words) or not all(x in flat for x in h):
                    bad += 1
                    print(f"::warning title={name}::{d['date']} {d['from']}-{d['to']} not found in {cal['source']['id']}.txt")
            print(f"{name}: {len(cal['days']) - bad} of {len(cal['days'])} days found in the decree's text")
            bad = 0
            continue
        # The text from each month's name to the next one's.
        starts = [(m.start(), MONTHS.index(m.group(1)) + 1) for m in re.finditer(r"\b(" + "|".join(MONTHS) + r")\b", text)]
        for d in cal["days"]:
            month, day = int(d["date"][5:7]), int(d["date"][8:10])
            parts = [text[s:(starts[i + 1][0] if i + 1 < len(starts) else len(text))] for i, (s, m) in enumerate(starts) if m == month]
            found = False
            for part in parts:
                for line in part.splitlines():
                    if re.search(rf"(?<!\d){day}(?!\d)", line) and any(h in line for h in hours(d["from"])) and any(h in line for h in hours(d["to"])):
                        found = True
                        break
                if found:
                    break
            if not found:
                bad += 1
                print(f"::warning title={name}::{d['date']} {d['from']}-{d['to']} not found in {cal['source']['id']}.txt")
        print(f"{name}: {len(cal['days']) - bad} of {len(cal['days'])} days found in the decree's text")
        bad = 0


if __name__ == "__main__":
    main(*sys.argv[1:])

"""Checks the driving-ban calendars transcribed into bans/data/*.json
against the text of the decrees fetch.py saved (pdftotext -layout of
<source id>.pdf): each transcribed day must be on a line of its month's
part of the text with its day number and both hours. Prints a warning
for each day it can't find, and for a source it can't read.

Usage: python3 check_bans.py fetched/ bans/data/
"""
import glob, json, os, re, sys

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


if __name__ == "__main__":
    main(*sys.argv[1:])

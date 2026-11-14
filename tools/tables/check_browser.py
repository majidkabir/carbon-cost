"""Warns when a page read in Chrome (browser/*.txt) is due to be read
again: its prices change on a known day each year, or it is older than
its operator's review cycle. Prints GitHub Actions ::warning lines; never
fails the run, since the workflow can't read these pages itself.

Usage: python3 check_browser.py [--strict] [YYYY-MM-DD]  (today by default)
--strict exits 1 when a page is due (the weekly workflow, so its failure
mails the repository's owner).
"""
import datetime, glob, os, re, sys

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser")

# Capture -> (yearly change day as MM-DD or None, maximum age in days).
RULES = {
    "al-atrako": (None, 92),           # tariff under review (concessionaire asked for a rise in Oct 2026)
    "at-nehg-10": ("01-01", 366),      # NEHG prices by calendar year
    "be-liefkenshoek": ("12-01", 366),  # next year's tariffs appear before 1 January
    "de-warnow-mauthvo": ("10-15", 366),  # the Anlage is reset each autumn, from 1 November
    "gb-m6toll-zones": (None, 92),      # the operator reviews prices quarterly
    "gb-tfl-lez-pay": (None, 183),
    "gb-tfl-tunnels": (None, 183),
    "gr-attiki": ("01-01", 366),        # yearly indexation from 1 January
    "gr-egnatia": ("01-01", 366),
    "lt-447": (None, 183),
    "gb-humber": (None, 183),
    "gb-tamar": (None, 183),
    "nl-kiltunnel": (None, 183),
    "md-evinieta": (None, 183),
}


def read_on(path):
    head = [l for l in open(path, encoding="utf-8") if l.startswith("#")]
    for l in head:
        if re.search(r"read|opened", l, re.I) and (m := re.search(r"\d{4}-\d\d-\d\d", l)):
            return datetime.date.fromisoformat(m.group(0))
    dates = [datetime.date.fromisoformat(d) for l in head for d in re.findall(r"\d{4}-\d\d-\d\d", l)]
    return max(dates) if dates else None


def main(*args):
    strict = "--strict" in args
    rest = [a for a in args if a != "--strict"]
    today = rest[0] if rest else None
    today = datetime.date.fromisoformat(today) if today else datetime.date.today()
    due = 0
    for path in sorted(glob.glob(os.path.join(HERE, "*.txt"))):
        name = os.path.basename(path)[:-4]
        day = read_on(path)
        change, age = RULES.get(name, (None, 183))
        why = []
        if day is None:
            why.append("no date read in its header")
        else:
            if (today - day).days > age:
                why.append(f"read {day}, over {age} days ago")
            if change:
                last = datetime.date(today.year, *map(int, change.split("-")))
                if last > today:
                    last = datetime.date(today.year - 1, *map(int, change.split("-")))
                if day < last:
                    why.append(f"read {day}, before its yearly change ({last})")
        if why:
            due += 1
            print(f"::warning title=browser/{name}.txt::read the page again in Chrome: {'; '.join(why)}")
        else:
            print(f"browser/{name}.txt: read {day}, fine")
    print(f"{due} page(s) to read again")
    if strict and due:
        sys.exit(1)


if __name__ == "__main__":
    main(*sys.argv[1:])

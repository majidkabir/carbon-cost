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
# France's pages and brochures read in Chrome (tools/fr): the motorways'
# tariffs change each 1 February.
FR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fr")

# Capture -> (yearly change day as MM-DD or None, maximum age in days).
RULES = {
    "al-atrako": (None, 92),
    "al-g2infra": (None, 92),            # G2 Infra's price list, no date           # tariff under review (concessionaire asked for a rise in Oct 2026)
    "at-nehg-10": ("01-01", 366),      # NEHG prices by calendar year
    "be-liefkenshoek": ("12-01", 366),  # next year's tariffs appear before 1 January
    "de-warnow-mauthvo": ("10-15", 366),  # the Anlage is reset each autumn, from 1 November
    "gb-m6toll-zones": (None, 92),      # the operator reviews prices quarterly
    "gb-tfl-lez-pay": (None, 183),
    "gb-tfl-tunnels": (None, 183),
    "gr-attiki": ("01-01", 366),        # yearly indexation from 1 January
    "gr-egnatia": ("01-01", 366),
    "lt-447": (None, 183),
    "lt-viatoll-2027": ("06-30", 366),  # LTSA reviews the Via Toll rates each year by 30 June
    "gb-humber": (None, 183),
    "gb-tamar": (None, 183),
    "nl-kiltunnel": (None, 183),
    "md-evinieta": (None, 183),
    "by-mintrans-42-2026": ("08-15", 366),  # BelToll tariffs have changed on 1 September
    "me-autoput": (None, 183),          # Monteput's pages carry no date; read when the workflow gets a bot check
    "me-sozina": (None, 183),
    "it-aspi-barriers": ("01-01", 366),  # Italian tolls change on 1 January
    "it-aspi-routes": ("01-01", 366),
    "it-aspi-closed-barriers": ("01-01", 366),
    "it-aspi-mountain": ("01-01", 366),
}


def read_on(path):
    # A brochure's text positions (tools/fr/sanef) carry no read date: its
    # name gives the tariffs' month (2026_02-Grille-Sanef).
    if m := re.match(r"(\d{4})_(\d\d)-", os.path.basename(path)):
        return datetime.date(int(m.group(1)), int(m.group(2)), 1)
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
    fr = sorted(glob.glob(os.path.join(FR, "browser", "*.txt")) + glob.glob(os.path.join(FR, "sanef", "*.items.txt")))
    for path in sorted(glob.glob(os.path.join(HERE, "*.txt"))) + fr:
        name, shown = os.path.basename(path)[:-4], "browser/" + os.path.basename(path)
        if path in fr:
            # A page can change on another day too (the Normandie bridges'
            # on 1 May 2026): read within half a year.
            shown = "tools/fr/" + os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
        day = read_on(path)
        said = "tariffs from" if shown.endswith(".items.txt") else "read"
        change, age = (("02-01", 366) if "sanef" in shown else ("02-01", 183)) if path in fr else RULES.get(name, (None, 183))
        why = []
        if day is None:
            why.append("no date read in its header")
        else:
            if (today - day).days > age:
                why.append(f"{said} {day}, over {age} days ago")
            if change:
                last = datetime.date(today.year, *map(int, change.split("-")))
                if last > today:
                    last = datetime.date(today.year - 1, *map(int, change.split("-")))
                if day < last:
                    why.append(f"{said} {day}, before its yearly change ({last})")
        if why:
            due += 1
            print(f"::warning title={shown}::read the page again in Chrome: {'; '.join(why)}")
        else:
            print(f"{shown}: {said} {day}, fine")
    print(f"{due} page(s) to read again")
    if strict and due:
        sys.exit(1)


if __name__ == "__main__":
    main(*sys.argv[1:])

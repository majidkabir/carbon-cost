"""Lists the schemes whose rates run out: the last dataset of a scheme
ends within the next N days (default 45), or ended already with nothing
after it. A trip after that day leaves the scheme's charges out (the
result is incomplete), so the next version (often a new year's tariffs,
published in December) is due before then. A scheme that really ends
has a next version that says so (ORCT no_charge).

Usage: python3 tools/orct/expiring.py [tariffs/data] [days] [YYYY-MM-DD]
Prints one ::warning per scheme (GitHub Actions annotations) and exits 0.
"""
import datetime, json, os, sys


def expiring(index, today, days):
    """[(scheme, country, name, last day, days left)] for the schemes whose
    last dataset ends within days of today, or before it."""
    last = {}
    for d in index["datasets"]:
        s = d["scheme"]
        if s not in last or d["valid_from"] > last[s]["valid_from"]:
            last[s] = d
    out = []
    horizon = today + datetime.timedelta(days=days)
    for s, d in sorted(last.items()):
        if not d.get("valid_to"):
            continue
        end = datetime.date.fromisoformat(d["valid_to"])
        if end <= horizon:
            out.append((s, d["country"], d["name"], d["valid_to"], (end - today).days))
    return out


def main(data="tariffs/data", days="45", day=None):
    today = datetime.date.fromisoformat(day) if day else datetime.date.today()
    index = json.load(open(os.path.join(data, "index.json"), encoding="utf-8"))
    rows = expiring(index, today, int(days))
    for s, cc, name, end, left in rows:
        when = f"ended on {end}" if left < 0 else f"end on {end} ({left} days)"
        print(f"::warning title=Rates run out: {cc} {s}::{name}: the rates here {when}, and no next version is here")
    print(f"{len(rows)} schemes run out by {today + datetime.timedelta(days=int(days))}")


if __name__ == "__main__":
    main(*sys.argv[1:])

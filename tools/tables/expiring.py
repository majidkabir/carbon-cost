"""Lists the tariffs that run out soon with nothing after them.

Each scheme's latest dataset in tariffs/data/index.json: when it has a
valid_to within the next DAYS days (or already past) and no dataset of the
same scheme starts after it, the tool would have no table for that scheme
from the day after. Prints a GitHub warning for each, so the nightly Tables
run shows what to look for next (a new year's tariff, decree or price).

Usage: python3 expiring.py tariffs/data/index.json [DAYS] [TODAY]
"""
import datetime as dt
import json
import sys
from collections import defaultdict


def expiring(index, days, today):
    by = defaultdict(list)
    for d in index["datasets"]:
        by[(d["country"], d["scheme"])].append(d)
    out = []
    horizon = today + dt.timedelta(days=days)
    for (country, scheme), ds in sorted(by.items()):
        last = max(ds, key=lambda d: d["valid_from"])
        if not last.get("valid_to"):
            continue
        end = dt.date.fromisoformat(last["valid_to"])
        if end <= horizon:
            out.append((end, country, scheme, last["id"]))
    return sorted(out)


def main(path, days="45", today=None):
    index = json.load(open(path, encoding="utf-8"))
    today = dt.date.fromisoformat(today) if today else dt.date.today()
    rows = expiring(index, int(days), today)
    for end, country, scheme, id_ in rows:
        when = "ran out" if end < today else "runs out"
        print(f"::warning title={scheme}::{id_} {when} on {end} and nothing follows it: look for the next tariff")
    print(f"{len(rows)} schemes run out by {today + dt.timedelta(days=int(days))} with nothing after them")


if __name__ == "__main__":
    main(*sys.argv[1:])

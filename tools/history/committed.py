"""What the history builders know of the datasets carbon-cost keeps
(tariffs/data, ORCT): each one's table name and dates, from its index,
for ending a historical table the day before the next version starts.

The builders that rebuild an older version from the current table's
structure (stations, sections, rows) take it as the data workflow that
builds it last did (the history workflow copies those tables into
fetched/current), else from templates/ (tools/orct/check_templates.py
keeps those equal, once converted, to the committed datasets).
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
INDEX = os.path.join(ROOT, "tariffs", "data", "index.json")
TEMPLATES = os.path.join(HERE, "templates")


def tables(index=INDEX):
    """(table file name, {"valid_from", "valid_to"}) of each committed dataset."""
    with open(index, encoding="utf-8") as fh:
        idx = json.load(fh)
    return [(os.path.basename(e["file"])[:-len(".orct.json")] + ".json", {"valid_from": e["valid_from"], "valid_to": e.get("valid_to")})
            for e in idx["datasets"]]


def prefix(name):
    """A table's scheme: its file name without the date."""
    return re.sub(r"-\d{4}-\d\d-\d\d\.json$", "", name)


def starts(scheme, index=INDEX):
    """The valid_from of each committed version of the scheme."""
    return sorted(tb["valid_from"] for name, tb in tables(index) if prefix(name) == scheme)


def template(name, fetched=None):
    """The current table a builder takes its structure from: as a data
    workflow last built it (the history workflow puts those in
    fetched/current), else the copy in templates/."""
    for d in ([os.path.join(fetched, "current")] if fetched else []) + [TEMPLATES]:
        path = os.path.join(d, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    raise SystemExit(f"no current table {name} (fetched/current or templates/)")

"""What the history builders know of the datasets carbon-cost keeps
(tariffs/data, ORCT): each one's table name and dates, from its index,
for ending a historical table the day before the next version starts.

The builders that rebuild an older version from the current table's
structure (stations, sections, rows) take it from templates/: the current
table as it was built, which tools/orct/check_templates.py keeps equal,
once converted, to the committed dataset.
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


def template(name):
    """The current table a builder takes its structure from."""
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as fh:
        return json.load(fh)

"""Reads Czechia's tolled network from the law into tools/roads/cz-network.json.

Usage: python3 cz_network.py law.txt > cz-network.json

law.txt: pdftotext -layout of vyhláška č. 527/2025 Sb., which replaces
annexes 1 and 2 of vyhláška č. 470/2012 Sb. (o užívání pozemních
komunikací zpoplatněných mýtným) from 1 January 2026: annex 1 lists the
tolled motorways (dálnice, D), annex 2 the tolled class I roads (silnice
I. třídy) by section ("Označení | Úsek | Délka (km)"). A section runs
between two places, or junctions of the motorway (its exits, "exity
58–62", "exit 6 až km 377"), or the state border ("státní hranice");
its length is given. tools/roads/build.py finds them in OpenStreetMap
(tools/roads/plnet.py) and reports the length found against the law's.
"""
import json, re, sys

ROW = re.compile(r"^(D\d+|I/\d+)\s+(.+?)\s+(\d+,\d+)$")
EXITS = re.compile(r"\s*\((.*?)\)\s*$")


def point(name, how, note=None):
    """A point of a section, as tools/roads/plnet.py takes it: a motorway
    junction by its exit number ("exit 58") and name; the state border
    ("státní hranice", after a place or alone: the road's end at the
    border); a junction with another road near a place ("Všestary (MÚK
    s D11)"); else a place or a junction of that name ("near")."""
    name = name.strip()
    if name.endswith("státní hranice"):
        place = name[: -len("státní hranice")].strip(" -–,")
        return {"border": place or None}
    if note:
        m = re.fullmatch(r"MÚK s (D\d+|I/\d+)", note)
        if not m:
            raise ValueError(f"point {name!r} ({note})")
        return {"place": name, "street": None, "crosses": [m.group(1).replace("I/", "")]}
    if how and how.startswith("exit"):
        return {"exit": how.split()[-1], "junction": name}
    return {"near": name}


def ends(s):
    """The from and to ways the law marks a section's ends: "exity 58–62",
    "exit 6 až km 377", "km 62 až exit 165", "km 34,5 až km 51"."""
    m = re.fullmatch(r"exity\s+(\d+)\s*[–-]\s*(\d+)", s)
    if m:
        return f"exit {m.group(1)}", f"exit {m.group(2)}"
    m = re.fullmatch(r"((?:exit|km)\s+-?[\d,]+)\s+až\s+((?:exit|km)\s+-?[\d,]+)", s)
    if m:
        return m.group(1), m.group(2)
    return None


def parse(text):
    lines = [l.strip() for l in text.splitlines()]
    body = "\n".join(l for l in lines if l and not re.match(r"^(Sbírka zákonů|Strana \d+|Částka \d+)", l))
    a1 = body.index("Příloha č. 1")
    a2 = body.index("Příloha č. 2", a1)
    end = body.find("Čl. II", a2)
    out = []
    for cls, part in (("mw", body[a1:a2]), ("nat", body[a2:end if end > 0 else len(body)])):
        pending = ""
        for l in part.splitlines()[1:]:
            l = re.sub(r"\s+", " ", l)
            if re.match(r"^(Seznam|Označení|Úsek|Délka)", l):
                continue
            cur = (pending + " " + l).strip() if pending else l
            m = ROW.match(cur)
            if not m:
                # A row wrapped onto the next line; or text after the table.
                pending = cur if re.match(r"^(D\d+|I/\d+)\s", cur) else ""
                continue
            pending = ""
            road, sec, km = m.group(1), m.group(2), float(m.group(3).replace(",", "."))
            how = EXITS.search(sec)
            marks = ends(how.group(1)) if how else None
            span = sec[: how.start()] if how else sec
            a, b = re.split(r"\s+–\s+", span, maxsplit=1)
            fa, fb = marks or (None, None)
            note = how.group(1) if how and not marks else None  # "(MÚK s D11)": the to point's
            ref = road[2:] if road.startswith("I/") else road  # OpenStreetMap: class I road 12 is ref 12
            out.append({"class": cls, "ref": ref, "from": point(a, fa), "to": point(b, fb, note), "km": km, "text": f"{road} {sec}"})
    return out


if __name__ == "__main__":
    secs = parse(open(sys.argv[1], encoding="utf-8").read())
    doc = {
        "source": "Vyhláška č. 527/2025 Sb. (annexes 1 and 2 of vyhláška č. 470/2012 Sb. from 1 January 2026): https://www.epravo.cz/_dataPublic/sbirky/2025/Sb_2025_527_PZZ.pdf",
        "sections": secs,
    }
    json.dump(doc, sys.stdout, ensure_ascii=False, indent=1)
    print()

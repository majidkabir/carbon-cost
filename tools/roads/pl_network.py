"""Reads Poland's e-TOLL network from the law into tools/roads/pl-network.json.

Usage: python3 pl_network.py law.txt > pl-network.json

law.txt: pdftotext -layout of the regulation on the national roads with
the electronic toll (rozporządzenie Rady Ministrów w sprawie dróg
krajowych lub ich odcinków, na których pobiera się opłatę elektroniczną),
as last amended: Dz. U. 2026 poz. 33, https://eli.gov.pl/api/acts/DU/2026/33/text/O/D20260033.pdf.
Annex 1 lists the tolled motorway and expressway (A, S) sections, annex
2 the other national road (GP, G) sections. Each section runs between
two points (§ 4): a junction ("węzeł X"), the state border, a city's
border ("granica m. X", a city with county rights), or a crossing with
or joining of another road near a place ("X (skrzyżowanie z drogą
krajową nr N)"). tools/roads/build.py finds them in OpenStreetMap.
"""
import json, re, sys

ROAD = re.compile(r"^(autostrada (A\d+)|droga ekspresowa (S\d+)|droga krajowa nr (\d+)) na odcink(?:u|ach):?\s*(.*)$")
# The other road at a crossing or joining: its number as OpenStreetMap
# refs it (A1, S7, 92 for a national or regional road, 1971D for a county
# road, 482003P for a municipal one).
OTHER = re.compile(r"(?:drog[ąa] (?:krajową|wojewódzką|powiatową|gminną|ekspresową)|autostradą)(?: nr)? ([0-9A-Z]+)")


def point(s):
    s = s.strip().rstrip(",;.")
    if s.startswith("węzeł "):
        return {"junction": s[len("węzeł "):].strip()}
    if s.startswith("granica m. "):
        return {"city": s[len("granica m. "):].strip()}
    m = re.match(r"^(.*?)\s*\((.*)\)$", s)
    if not m:
        raise ValueError(f"point {s!r}")
    place, how = m.group(1).strip(), m.group(2)
    if how == "granica państwowa":
        return {"border": place}
    refs = OTHER.findall(how)
    if not refs or not re.match(r"^(skrzyżowanie|połączenie) z ", how):
        raise ValueError(f"point {s!r}")
    return {"place": place.split(",")[0].strip(), "street": place.split(",")[1].strip() if "," in place else None, "crosses": refs}


def parse(text):
    lines = []
    for l in text.splitlines():
        l = l.strip()
        if not l or re.match(r"^Dziennik Ustaw\s*[–-]", l):
            continue
        lines.append(l)
    body = "\n".join(lines)
    a1 = body.index("Załącznik nr 1")
    a2 = body.index("Załącznik nr 2")
    a3 = body.index("Załącznik nr 3")
    out = []
    for cls, part in (("mw", body[a1:a2]), ("nat", body[a2:a3])):
        # One entry per numbered item; wrapped lines join their item.
        items, cur = [], None
        for l in part.splitlines()[1:]:
            if l.startswith("*)"):
                break  # the annex's footnote
            m = re.match(r"^(\d+)\)\s+(.*)$", l)
            if m:
                cur = [m.group(2)]
                items.append(cur)
            elif cur is not None:
                cur.append(l)
        for it in items:
            text = " ".join(it)
            text = re.sub(r"(\w)- (\w)", r"\1\2", text)  # kra- jową
            text = re.sub(r"\s+", " ", text)
            m = ROAD.match(text)
            if not m:
                raise ValueError(f"item {text!r}")
            ref = m.group(2) or m.group(3) or m.group(4)
            rest = m.group(5).rstrip(";.")
            parts = re.split(r"(?:^|,\s*)[a-z]\)\s+", rest)
            parts = [p for p in parts if p.strip()]
            for p in parts:
                a, b = re.split(r"\s+–\s+", p.strip().rstrip(","), maxsplit=1)
                out.append({"class": cls, "ref": ref, "from": point(a), "to": point(b), "text": f"{ref} {p.strip().rstrip(',')}"})
    return out


if __name__ == "__main__":
    secs = parse(open(sys.argv[1], encoding="utf-8").read())
    doc = {
        "source": "Dz. U. 2026 poz. 33, annexes 1 and 2: https://eli.gov.pl/api/acts/DU/2026/33/text/O/D20260033.pdf",
        "sections": secs,
    }
    json.dump(doc, sys.stdout, ensure_ascii=False, indent=1)
    print()

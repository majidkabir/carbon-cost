"""Reads Czechia's tolled network from the law into tools/roads/cz-network.json.

Usage: python3 cz_network.py law.txt > cz-network.json

law.txt: pdftotext -layout of vyhláška č. 527/2025 Sb., which replaces
annexes 1 and 2 of vyhláška č. 470/2012 Sb. (o užívání pozemních
komunikací zpoplatněných mýtným) from 1 January 2026: annex 1 lists the
tolled motorways (dálnice, D), annex 2 the tolled class I roads (silnice
I. třídy) by section ("Označení | Úsek | Délka (km)"). The law names
each section's ends (places, exits, km posts, the state border) and its
length. tools/roads/build.py takes the class I roads that are tolled from
here and checks each road's tolled km against the law's; where on the
road the sections lie comes from the toll operator's map
(tools/roads/cz_myto.py).
"""
import json, re, sys

ROW = re.compile(r"^(D\d+|I/\d+)\s+(.+?)\s+(\d+,\d+)$")


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
            ref = road[2:] if road.startswith("I/") else road  # OpenStreetMap: class I road 12 is ref 12
            out.append({"class": cls, "ref": ref, "km": km, "text": f"{road} {sec}"})
    return out


if __name__ == "__main__":
    secs = parse(open(sys.argv[1], encoding="utf-8").read())
    doc = {
        "source": "Vyhláška č. 527/2025 Sb. (annexes 1 and 2 of vyhláška č. 470/2012 Sb. from 1 January 2026): https://www.epravo.cz/_dataPublic/sbirky/2025/Sb_2025_527_PZZ.pdf",
        "sections": secs,
    }
    json.dump(doc, sys.stdout, ensure_ascii=False, indent=1)
    print()

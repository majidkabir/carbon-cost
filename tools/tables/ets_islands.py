"""Builds the ferry crossings under the EU ETS island derogation that
carbon-cost recognises (crossings-islands.json, for ferries/data), from

- Commission Implementing Decision (EU) 2023/2895, Annex I, the list of
  islands and ports under Article 12(3-d) of Directive 2003/87/EC
  (ets-islands-2023-2895.html, the Publications Office's copy of the
  Official Journal text): no allowances are
  surrendered for emissions before 31 December 2030 from voyages by
  passenger and ro-pax ships between such a port and a port of the same
  Member State;
- Jadrolinija's lines (the price lists and OpenStreetMap places that
  hr_jadrolinija.py reads): each pair of ports on a line where one port is
  in the Decision's list for Croatia becomes a crossing with that
  derogation, its terminals the ports' places on the car ferry lines.

JADROLINIJA maps each of Jadrolinija's ports to the Decision's island and
port; a port Jadrolinija names after its island is the island's one port
in the list (Koločep: Donje Čelo; Žirje: Muna; Premuda: Krijal; Silba:
Žalić; Molat: Molat (Lučina)), or one of its two (Ist: Kosirača, Široka).
The builder stops if the Decision's text no longer lists a port mapped
here. Ports on islands with a road link (Krk, Pag) and on the mainland
or a peninsula (Pelješac) aren't in the list.

Usage: python3 ets_islands.py <fetched dir> <out dir>
"""
import json, os, re, sys, unicodedata

import hr_jadrolinija as hr
from ferry_osm import lines_of

DECISION = ("Directive 2003/87/EC, Art. 12(3-d); Commission Implementing Decision (EU) 2023/2895, Annex I", "https://eur-lex.europa.eu/eli/dec_impl/2023/2895/oj")
FROM, UNTIL = "2024-01-01", "2030-12-31"
# Jadrolinija's port -> the Decision's (island, port) for Croatia.
JADROLINIJA = {
    "TKON": ("PAŠMAN", "TKON"), "POROZINA": ("CRES", "POROZINA"), "MERAG": ("CRES", "MERAG"), "SUĆURAJ": ("HVAR", "SUĆURAJ"),
    "STARI GRAD": ("HVAR", "STARI GRAD"), "SUĐURAĐ": ("ŠIPAN", "SUĐURAĐ"), "KOLOČEP": ("KOLOČEP", "DONJE ČELO"),
    "DOMINČE": ("KORČULA", "DOMINČE"), "VELA LUKA": ("KORČULA", "VELA LUKA"), "SOBRA": ("MLJET", "SOBRA"), "ZLARIN": ("ZLARIN", "ZLARIN"),
    "OBONJAN": ("OBONJAN", "OBONJAN"), "KAPRIJE": ("KAPRIJE", "KAPRIJE"), "ŽIRJE": ("ŽIRJE", "MUNA"), "ROGAČ": ("ŠOLTA", "ROGAČ"),
    "SUPETAR": ("BRAČ", "SUPETAR"), "SUMARTIN": ("BRAČ", "SUMARTIN"), "UBLI": ("LASTOVO", "UBLI"), "VIS": ("VIS", "VIS"),
    "DRVENIK VELI": ("DRVENIK VELI", "DRVENIK VELIKI"), "DRVENIK MALI": ("DRVENIK MALI", "DRVENIK MALI"), "LOPAR": ("RAB", "LOPAR"),
    "BRBINJ": ("DUGI OTOK", "BRBINJ"), "PREKO": ("UGLJAN", "PREKO"), "OŠLJAK": ("OŠLJAK", "OŠLJAK"), "PREMUDA": ("PREMUDA", "KRIJAL"),
    "SILBA": ("SILBA", "ŽALIĆ"), "OLIB": ("OLIB", "OLIB"), "IST": ("IST", "ŠIROKA"), "MALI LOŠINJ": ("LOŠINJ", "MALI LOŠINJ"),
    "RIVANJ": ("RIVANJ", "RIVANJ"), "SESTRUNJ": ("SESTRUNJ", "SESTRUNJ"), "ZVERINAC": ("ZVERINAC", "ZVERINAC"),
    "MOLAT": ("MOLAT", "MOLAT (LUČINA)"), "BRŠANJ": ("IŽ", "BRŠANJ"), "RAVA": ("RAVA", "RAVA"), "MALA RAVA": ("RAVA", "MALA RAVA"),
}


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def slug(s):
    s = unicodedata.normalize("NFKD", s.lower().replace("đ", "d")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def croatia(decision):
    """The Decision's Croatian section: its text between CROATIA and ITALY."""
    i, j = decision.find(" CROATIA "), decision.find(" ITALY ")
    if i < 0 or j < i:
        sys.exit("ETS islands: the Decision's list for Croatia not found")
    return decision[i:j]


def main(fetched, out):
    try:
        decision = text(os.path.join(fetched, "ets-islands-2023-2895.html"))
        osm = json.load(open(os.path.join(fetched, "hr-jadrolinija-osm.json")))
        texts = {n: open(os.path.join(fetched, f"hr-jadro-{n}.txt"), encoding="utf-8").read() for n in hr.LINES}
    except (OSError, ValueError) as e:
        print(f"ETS islands: not built ({e})")
        return
    if "List of islands and ports as referred to in Article 12(3-d)" not in decision:
        sys.exit("ETS islands: not the Decision's Annex I")
    hrlist = croatia(decision)
    for port, (island, dport) in JADROLINIJA.items():
        if f" {island} " not in hrlist or f" {dport}" not in hrlist:
            sys.exit(f"ETS islands: the Decision no longer lists {island}, {dport} (Jadrolinija's {port})")
    src = {s["id"]: s for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")))["sources"]}
    lines, _ = lines_of(osm)
    pos = hr.places(osm, lines)
    crossings, seen = [], set()
    for n in hr.LINES:
        _, blocks = hr.parse(texts[n], n)
        for pairs, _ in blocks:
            for a, b in pairs:
                key = tuple(sorted((a, b)))
                listed = [p for p in key if p in JADROLINIJA]
                if key in seen or not listed or a not in pos or b not in pos:
                    continue
                seen.add(key)
                island, dport = JADROLINIJA[listed[0]]
                crossings.append({
                    "id": "hr-" + "-".join(slug(p) for p in key),
                    "name": f"{a.title()}–{b.title()}", "operator": "Jadrolinija",
                    "terminals": [{"name": p.title(), "lat": round(pos[p][0], 6), "lon": round(pos[p][1], 6), "country": "HR"} for p in (a, b)],
                    "ships": [],
                    "exemptions": [{"from": FROM, "until": UNTIL, "law": f"{DECISION[0]} (Croatia: {island.title()}, {dport.title()})", "url": DECISION[1]}],
                    "source": {"title": f"Jadrolinija: line {n}, timetable and price list", "url": src[f"hr-jadro-{n}"]["url"]}})
    crossings.sort(key=lambda c: c["id"])
    os.makedirs(out, exist_ok=True)
    doc = {"note": "Ferry crossings under the EU ETS island derogation (Directive 2003/87/EC, Art. 12(3-d); Implementing Decision (EU) 2023/2895, Annex I), "
                   "built by tools/tables/ets_islands.py from the Decision and the lines' data.", "crossings": crossings}
    path = os.path.join(out, "crossings-islands.json")
    json.dump(doc, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, len(crossings), "crossings")


if __name__ == "__main__":
    main(*sys.argv[1:])

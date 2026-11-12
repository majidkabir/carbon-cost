"""Builds the national CO2 prices on road fuel (rates/data/fuelco2-*.json)
from the fetched law texts (sources.json, table fuelco2-*):

- Germany, BEHG § 10 (2): the fixed certificate price of 2024 and 2025,
  and for 2026 the corridor of 55 to 65 euro; the 2026 price is the
  auctions' clearing price, 65 euro when every auction applied the
  "65 EUR rule" (BEHV § 12 (4): more volume allotted because the price
  reached the ceiling), read from EEX's auction calendar;
- Austria, NEHG 2022 § 10 (1): the certificate value by calendar year
  (to 2025; the law sets none for later years);
- Ireland, the carbon component of Mineral Oil Tax on auto-diesel by
  period, from Revenue's Excise Duty Rates manual;
- Portugal, the "adicionamento sobre as emissões de CO2" (CIEC art.
  92.º-A): each portaria's rate from its entry into force, and the rate
  the Autoridade Tributária publishes for the next year (art. 92.º-A n.º 3)
  from 1 January, unless that ofício says the portaria's rate still applies;
- Slovenia, the okoljska dajatev za onesnaževanje zraka z emisijo CO2 on
  plinsko olje (diesel): 17.3 euro per unit (1 tonne of CO2) under Uredba
  48/18 until the government's first sklep, then each sklep from its entry
  into force (point I, and point III's later date) until the next one.

Usage: python3 fuel_co2.py fetched/ out-dir"""
import html, json, os, re, sys


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def src(srcs, sid):
    return {"title": srcs[sid]["what"], "url": srcs[sid]["url"]}


def write(out, f):
    path = os.path.join(out, f"fuelco2-{f['country'].lower()}-{f['valid_from']}.json")
    json.dump(f, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, f["rate_per_t"])


def germany(fetched, out, srcs):
    t = text(os.path.join(fetched, "de-behg-10.html"))
    for y in (2024, 2025):
        m = re.search(rf"im Zeitraum vom 1\. Januar {y} bis zum 31\. Dezember {y}: (\d+) Euro", t)
        if not m:
            sys.exit(f"BEHG § 10: no fixed price for {y}")
        write(out, {"country": "DE", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "Brennstoffemissionshandel (nEHS) certificate price", "rate_per_t": float(m.group(1)),
                    "law": f"BEHG § 10 (2): fixed price of {m.group(1)} euro per certificate (one tonne of CO2) in {y}. Fuel suppliers buy a certificate for each tonne of CO2 their fuel emits and pass the cost on in the fuel price.",
                    "sources": [src(srcs, "de-behg-10")]})
    m = re.search(r"Für das Jahr 2026 wird ein Preiskorridor mit einem Mindestpreis von (\d+) Euro pro Emissionszertifikat und einem Höchstpreis von (\d+) Euro", t)
    if not m:
        sys.exit("BEHG § 10: no 2026 price corridor")
    lo, hi = float(m.group(1)), float(m.group(2))
    rows = []
    for line in open(os.path.join(fetched, "de-eex-nehs-auctions.csv"), encoding="utf-8-sig").read().splitlines()[1:]:
        f = line.split(";")
        if len(f) > 5 and f[3] == "2026":
            rows.append((f[0], float(f[4]), int(f[5])))
    if not rows or any(not lo <= p <= hi for _, p, _ in rows):
        sys.exit(f"EEX: no 2026 auctions in the corridor ({rows[:3]})")
    vol = sum(v for _, _, v in rows)
    avg = round(sum(p * v for _, p, v in rows) / vol, 2)
    prices = sorted({p for _, p, _ in rows})
    write(out, {"country": "DE", "currency": "EUR", "valid_from": "2026-01-01", "valid_to": "2026-12-31",
                "name": "Brennstoffemissionshandel (nEHS) certificate price", "rate_per_t": avg,
                "law": f"BEHG § 10 (2): 2026 certificates are auctioned in a corridor of {m.group(1)} to {m.group(2)} euro. This is the volume-weighted clearing price of the {len(rows)} auctions EEX held ({rows[-1][0]} to {rows[0][0]}; clearing prices {', '.join(f'{p:g}' for p in prices)} euro). Certificates bought after the auctions cost 68 euro (the excess quantity price), so a supplier's average may be a little higher.",
                "sources": [src(srcs, "de-behg-10"), src(srcs, "de-eex-nehs-auctions")]})


def austria(fetched, out, srcs):
    p = os.path.join(fetched, "at-nehg.html")
    t = text(p) if os.path.exists(p) else ""
    if "Ausgabewert" not in t:
        # RIS refuses the workflow (503) and the Internet Archive has no
        # copy yet: Austria isn't priced until the page can be read.
        print("NEHG 2022: the RIS page wasn't fetched; Austria not built")
        return
    m = re.search(r"Die nationalen Emissionszertifikate haben einen Ausgabewert von: ?Kalenderjahr ?Betrag (.*?) \(2\)", t)
    if not m:
        sys.exit("NEHG 2022 § 10 (1) not found")
    vals = dict(re.findall(r"(20\d\d) (\d+(?:,\d+)?) Euro", m.group(1)))
    for y in ("2024", "2025"):
        if y not in vals:
            sys.exit(f"NEHG 2022 § 10 (1): no value for {y}")
        write(out, {"country": "AT", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "Nationaler Emissionszertifikatehandel certificate value", "rate_per_t": float(vals[y].replace(",", ".")),
                    "law": f"NEHG 2022 § 10 (1): certificate value of {vals[y]} euro per tonne of CO2 in {y}. Fuel suppliers pay it for the CO2 their fuel emits and pass it on in the fuel price. The law sets no value for 2026 or later, so those years aren't priced.",
                    "sources": [src(srcs, "at-nehg")]})


MONTHS = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}


def irish_date(d):
    day, month, year = d.split()
    return f"{year}-{MONTHS[month]:02d}-{int(day):02d}"


def ireland(fetched, out, srcs):
    """Mineral Oil Tax's carbon component on auto-diesel ("heavy oil used as
    a propellant"), as Revenue's Excise Duty Rates manual gives the amount
    charged per tonne of CO2 for each period (Finance Act 1999 Schedule 2A)."""
    p = os.path.join(fetched, "ie-revenue-energy-rates.txt")
    if not os.path.exists(p):
        print("Ireland: Revenue's rates manual wasn't fetched; not built")
        return
    t = open(p, encoding="utf-8").read()
    periods = []
    for m in re.finditer(r"Mineral Oil Tax \(MOT\) rates effective from (\d+ \w+ \d{4})(?: to (\d+ \w+ \d{4}))?\n", t):
        if m.group(2) and irish_date(m.group(2)) < "2024-01-01":
            continue  # older tables, laid out differently
        seg = t[m.end():m.end() + 6000]
        h = seg.find("Heavy Oil:")
        r = re.search(r"Used as a propellant[.…\s]*€([\d.]+)\*?\s", seg[h:])
        if h < 0 or not r:
            sys.exit(f"Ireland: no auto-diesel rate in the period from {m.group(1)}")
        periods.append((irish_date(m.group(1)), irish_date(m.group(2)) if m.group(2) else "", float(r.group(1))))
    periods.sort()
    for a, b in zip(periods, periods[1:]):
        if a[1] and a[1] >= b[0]:
            sys.exit(f"Ireland: overlapping periods {a} {b}")
    # From 2024, merging consecutive periods at the same rate.
    merged = []
    for vf, vt, rate in periods:
        if (vt or "9999") < "2024-01-01":
            continue
        vf = max(vf, "2024-01-01")
        if merged and merged[-1][2] == rate:
            merged[-1][1] = vt
        else:
            merged.append([vf, vt, rate])
    for vf, vt, rate in merged:
        f = {"country": "IE", "currency": "EUR", "valid_from": vf,
             "name": "Carbon tax (carbon component of Mineral Oil Tax) on auto-diesel", "rate_per_t": rate,
             "law": f"Finance Act 1999 Schedule 2A, as Revenue's Excise Duty Rates manual gives it: the carbon component of Mineral Oil Tax on heavy oil used as a propellant (auto-diesel) charges {rate:.2f} euro per tonne of CO2 its burning emits. Fuel suppliers pay it with the Mineral Oil Tax and pass it on in the fuel price.",
             "sources": [src(srcs, "ie-revenue-energy-rates")]}
        if vt:
            f["valid_to"] = vt
        write(out, f)


PT_MONTHS = {"janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
             "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
# Fixed public holidays (Código do Trabalho art. 234.º), for "dia útil".
PT_HOLIDAYS = {"01-01", "04-25", "05-01", "06-10", "08-15", "10-05", "11-01", "12-01", "12-08", "12-25"}


def pt_next_day(d, working):
    import datetime
    d = datetime.date.fromisoformat(d) + datetime.timedelta(days=1)
    while working and (d.weekday() >= 5 or d.strftime("%m-%d") in PT_HOLIDAYS):
        d += datetime.timedelta(days=1)
    return d.isoformat()


def portugal(fetched, out, srcs):
    """Adicionamento sobre as emissões de CO2 (CIEC art. 92.º-A), euro per
    tonne of CO2, from the portarias that fix it and the Autoridade
    Tributária's yearly ofícios circulados."""
    steps = []  # (valid_from, rate, source id, note)
    for sid in sorted(k for k in srcs if k.startswith("pt-portaria-")):
        p = os.path.join(fetched, sid + ".txt")
        if not os.path.exists(p):
            sys.exit(f"Portugal: {sid} wasn't fetched")
        t = re.sub(r"\s+", " ", open(p, encoding="utf-8").read())
        pub = re.search(r"Publicação: Diário da República [^:]*?de (\d{4}-\d\d-\d\d)", t)
        rate = re.search(r"A taxa do adicionamento sobre as emissões de CO ?2 é de ([\d,]+) euros ?/ ?tonelada", t)
        if not pub or not rate:
            sys.exit(f"Portugal: no publication date or rate in {sid}")
        if m := re.search(r"entra em vigor no dia (\d+) de (\w+) de (\d{4})", t):
            vf = f"{m.group(3)}-{PT_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
            rule = f"in force from {vf}"
        elif re.search(r"entra em vigor no dia útil seguinte ao da sua publicação", t):
            vf = pt_next_day(pub.group(1), True)
            rule = f"published {pub.group(1)}, in force the next working day"
        elif re.search(r"entra em vigor no dia seguinte ao da sua publicação", t):
            vf = pt_next_day(pub.group(1), False)
            rule = f"published {pub.group(1)}, in force the next day"
        else:
            sys.exit(f"Portugal: no entry into force in {sid}")
        name = re.search(r"Portaria n\.º ([\w/-]+), de", t).group(1)
        steps.append((vf, float(rate.group(1).replace(",", ".")), sid, f"Portaria {name} ({rule})"))
    kept = {}  # year -> (source id, ofício number): the portaria in force keeps applying
    for sid in sorted(k for k in srcs if k.startswith("pt-oficio-")):
        p = os.path.join(fetched, sid + ".txt")
        if not os.path.exists(p):
            sys.exit(f"Portugal: {sid} wasn't fetched")
        t = re.sub(r"\s+", " ", open(p, encoding="utf-8").read())
        m = re.search(r"emissões de CO ?2 para o ano de (\d{4}), nos termos do n\.º 2 do artigo 92\.º-A do CIEC, de ([\d,]+) euros ?/ ?tonelada", t)
        if not m:
            sys.exit(f"Portugal: no yearly rate in {sid}")
        year = m.group(1)
        no = re.search(r"Ofício Circulado N\.º: (\d+)", t).group(1)
        if re.search(rf"taxa do adicionamento sobre as emissões de CO ?2 a aplicar no ano de {year} é a taxa prevista na Portaria", t):
            kept[year] = (sid, no)  # a despacho kept the portaria's rate
            continue
        steps.append((f"{year}-01-01", float(m.group(2).replace(",", ".")), sid, f"the Autoridade Tributária's Ofício Circulado {no}, which publishes the rate for {year} under art. 92.º-A n.º 2 and 3"))
    steps.sort()
    # From 2024, merging consecutive steps at the same rate.
    start = max((s for s in steps if s[0] <= "2024-01-01"), default=None)
    if not start:
        sys.exit("Portugal: no rate in force on 2024-01-01")
    merged = []
    for vf, rate, sid, note in [("2024-01-01",) + start[1:]] + [s for s in steps if s[0] > "2024-01-01"]:
        if merged and merged[-1][1] == rate:
            continue
        merged.append([vf, rate, sid, note])
    import datetime
    for i, (vf, rate, sid, note) in enumerate(merged):
        f = {"country": "PT", "currency": "EUR", "valid_from": vf,
             "name": "Adicionamento sobre as emissões de CO2 (carbon tax on road diesel)", "rate_per_t": rate,
             "law": f"Código dos Impostos Especiais de Consumo art. 92.º-A: the adicionamento sobre as emissões de CO2 is {rate:g} euro per tonne of CO2, from {note}. It is charged with the ISP on gasóleo rodoviário, the product's CO2 factor times this rate, and passed on in the fuel price.",
             "sources": [src(srcs, sid)]}
        if vf[:4] in kept and vf.endswith("-01-01") and not sid.startswith("pt-oficio-"):
            ks, no = kept[vf[:4]]
            f["law"] += f" The Autoridade Tributária's Ofício Circulado {no} says this rate applies in {vf[:4]}."
            f["sources"].append(src(srcs, ks))
        if i + 1 < len(merged):
            f["valid_to"] = (datetime.date.fromisoformat(merged[i + 1][0]) - datetime.timedelta(days=1)).isoformat()
        write(out, f)


SI_MONTHS = {"januarja": 1, "februarja": 2, "marca": 3, "aprila": 4, "maja": 5, "junija": 6, "julija": 7,
             "avgusta": 8, "septembra": 9, "oktobra": 10, "novembra": 11, "decembra": 12}


def si_text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    if path.endswith(".html"):
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)  # words hyphenated across lines
    return re.sub(r"\s+", " ", t)


def si_rate(v):
    return float(v.replace(",", "."))


def slovenia(fetched, out, srcs):
    """Okoljska dajatev za onesnaževanje zraka z emisijo CO2 on diesel
    (plinsko olje), euro per unit of burden (enota obremenitve, 1 tonne of
    CO2), from the Uredba and the government's sklepi in the Uradni list."""
    import datetime
    p = os.path.join(fetched, "si-uredba-48-2018.html")
    if not os.path.exists(p):
        sys.exit("Slovenia: the Uredba wasn't fetched")
    t = si_text(p)
    if not re.search(r"enota obremenitve in je enaka emisiji 1 tone CO ?2", t):
        sys.exit("Slovenia: the Uredba doesn't define the unit as 1 tonne of CO2")
    m = re.search(r"znesek na enoto obremenitve zraka z emisijo CO ?2 ([\d,]+) eura", t)
    if not m:
        sys.exit("Slovenia: no amount in the Uredba")
    base = si_rate(m.group(1))
    sklepi = []  # (entry into force, [(from, rate)], source id, gazette)
    for sid in sorted(k for k in srcs if k.startswith("si-sklep-")):
        p = next((os.path.join(fetched, sid + e) for e in (".txt", ".html") if os.path.exists(os.path.join(fetched, sid + e))), None)
        if not p:
            sys.exit(f"Slovenia: {sid} wasn't fetched")
        t = si_text(p)
        ul = re.search(r"(?:URADNI LIST REPUBLIKE SLOVENIJE ŠT\.|Uradni list RS, št\.) (\d+)/(\d{4}) Z DNE (\d+)\. (\d+)\. (\d{4})", t, re.I)
        if not ul:
            sys.exit(f"Slovenia: no gazette number and date in {sid}")
        pub = datetime.date(int(ul.group(5)), int(ul.group(4)), int(ul.group(3)))
        if m := re.search(r"Ta sklep začne veljati (\d+)\. (\w+) (\d{4})", t):
            entry = datetime.date(int(m.group(3)), SI_MONTHS[m.group(2)], int(m.group(1)))
        elif re.search(r"Ta sklep začne veljati naslednji dan po objavi", t):
            entry = pub + datetime.timedelta(days=1)
        else:
            sys.exit(f"Slovenia: no entry into force in {sid}")
        m = re.search(r"plinsko olje[^.]{0,200}? znaša ([\d,]+) eur", t) or re.search(r"za enoto obremenitve je ([\d,]+) eura", t)
        if not m:
            sys.exit(f"Slovenia: no diesel amount in {sid}")
        steps = [(entry, si_rate(m.group(1)))]
        for m in re.finditer(r"Ne glede na točk[oi] [^.]{0,200}? za enoto obremenitve od (\d+)\. (\w+) (\d{4}) znaša ([\d,]+) eur", t):
            steps.append((datetime.date(int(m.group(3)), SI_MONTHS[m.group(2)], int(m.group(1))), si_rate(m.group(4))))
        sklepi.append((entry, steps, sid, f"{ul.group(1)}/{ul.group(2)}"))
    sklepi.sort()
    timeline = [(datetime.date(2018, 8, 1), base, "si-uredba-48-2018", "Uredba 48/18 (until the government's sklep)")]
    for i, (entry, steps, sid, ul) in enumerate(sklepi):
        end = sklepi[i + 1][0] if i + 1 < len(sklepi) else datetime.date.max
        for d, r in steps:
            if d < end:
                timeline.append((d, r, sid, f"the government's sklep in Uradni list RS {ul}"))
    timeline.sort(key=lambda x: x[0])
    start = max((x for x in timeline if x[0] <= datetime.date(2024, 1, 1)), key=lambda x: x[0])
    merged = []
    for d, r, sid, note in [(datetime.date(2024, 1, 1),) + start[1:]] + [x for x in timeline if x[0] > datetime.date(2024, 1, 1)]:
        if merged and merged[-1][1] == r:
            continue
        merged.append((d, r, sid, note))
    for i, (d, r, sid, note) in enumerate(merged):
        f = {"country": "SI", "currency": "EUR", "valid_from": d.isoformat(),
             "name": "Okoljska dajatev za onesnaževanje zraka z emisijo CO2 on diesel", "rate_per_t": r,
             "law": f"Uredba o okoljski dajatvi za onesnaževanje zraka z emisijo ogljikovega dioksida (Uradni list RS 48/18) art. 3: the charge is an amount per unit of burden, one tonne of CO2; for plinsko olje (diesel) it is {r:g} euro, from {note}. Fuel suppliers pay it and pass it on in the fuel price.",
             "sources": [src(srcs, sid)]}
        if i + 1 < len(merged):
            f["valid_to"] = (merged[i + 1][0] - datetime.timedelta(days=1)).isoformat()
        write(out, f)


def main(fetched, out):
    os.makedirs(out, exist_ok=True)
    srcs = {s["id"]: s for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json"), encoding="utf-8"))["sources"]}
    germany(fetched, out, srcs)
    austria(fetched, out, srcs)
    ireland(fetched, out, srcs)
    portugal(fetched, out, srcs)
    slovenia(fetched, out, srcs)


if __name__ == "__main__":
    main(*sys.argv[1:])

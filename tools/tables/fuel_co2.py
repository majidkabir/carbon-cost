"""Builds the national CO2 prices on road fuel (fuelco2-*.json tables)
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
  into force (point I, and point III's later date) until the next one;
- Denmark, the CO2 tax on gas and diesel oil (CO2-afgiftsloven § 2, stk.
  1, indexed under stk. 7), per litre at day temperature, for the two
  years Skatteministeriet's rate table gives, and 2024 and 2025 from the
  Internet Archive's copy of its 2025 table;
- Sweden, the koldioxidskatt on unmarked diesel of environmental class 1
  (lag (1994:1776) om skatt på energi, 2 kap. 1 §), per cubic metre, for
  each period on Skatteverket's rate page from 2024 (consecutive periods
  at the same rate joined);
- Norway, the CO2-avgift on mineral oil (Stortingets vedtak om CO2-avgift
  på mineralske produkter, generell sats; særavgiftsloven), per litre:
  2024 and 2025 from the Finance Ministry's 2025 rate table, 2026 from its
  2026 table, with the temporary reduction for road diesel from 1 May to
  31 August 2026 from its press release (the Internet Archive's copies:
  regjeringen.no refuses the workflow);
- Finland, the hiilidioksidivero on diesel oil (product group 50) in the
  liquid fuels excise tax act's table (laki nestemäisten polttoaineiden
  valmisteverosta 1472/1994, liite), per litre, for each period of
  Verohallinto's tax tables from 2024 (consecutive periods at the same
  rate joined);
- Lithuania, the CO2 dedamoji (component) of the excise duty on gas oils
  (Akcizų įstatymas Nr. IX-569, 37 str. 1 d. and 3 priedas), per 1,000
  litres, from its introduction on 1 January 2025: the customs notice
  that 2026 keeps the 2025 amount (law XV-679);
- Luxembourg, the droit d'accise autonome « taxe CO2 » on gas oil used as
  motor fuel (règlement grand-ducal modifié du 17 décembre 2010, art. 3),
  per 1,000 litres, from the customs' yearly rate sheets (the row's parts
  checked to add up to its total);
- Albania, the taksa e karbonit on gazoil (Ligj nr. 9975/2008 për taksat
  kombëtare, neni 4 pika 6), per litre, from the Qendra e Botimeve
  Zyrtare's consolidated versions 7 and 8 (the two in force since 2024),
  while QBZ lists no later version.

Taxes per litre (rate_per_l) are priced on litres of fossil diesel: the
calculator divides the trip's tank-to-wheel CO2 by 2.67 kg per litre
unless the request gives the litres.

Usage: python3 fuel_co2.py fetched/ out-dir"""
import datetime, html, json, os, re, sys


def text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def src(srcs, sid):
    # "page": the human-readable page of a source fetched from an API.
    return {"title": srcs[sid]["what"], "url": srcs[sid].get("page", srcs[sid]["url"])}


def write(out, f):
    path = os.path.join(out, f"fuelco2-{f['country'].lower()}-{f['valid_from']}.json")
    json.dump(f, open(path, "w"), ensure_ascii=False, indent=1)
    print(path, f.get("rate_per_t", f.get("rate_per_l")))


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
    # § 10 (2) sentence 4: "Für das Jahr 2026 wird ein Preiskorridor ..."; the
    # Dritte Gesetz zur Änderung des BEHG (Bundestag 15 October 2026)
    # makes it "Für die Jahre 2026 und 2027 ...".
    m = re.search(r"Für (?:das Jahr (2026)|die Jahre (2026) und (2027)) wird ein Preiskorridor mit einem Mindestpreis von (\d+) Euro pro Emissionszertifikat und einem Höchstpreis von (\d+) Euro", t)
    if not m:
        sys.exit("BEHG § 10: no price corridor for 2026")
    years = [y for y in m.group(1, 2, 3) if y]
    lo, hi = float(m.group(4)), float(m.group(5))
    auctions = []
    for line in open(os.path.join(fetched, "de-eex-nehs-auctions.csv"), encoding="utf-8-sig").read().splitlines()[1:]:
        f = line.split(";")
        if len(f) > 5:
            auctions.append((f[0], f[3], float(f[4]), int(f[5])))
    for y in years:
        rows = [(d, p, v) for d, yr, p, v in auctions if yr == y]
        if not rows:
            if y == "2026":
                sys.exit("EEX: no 2026 auctions")
            print(f"BEHG § 10: the {y} corridor is in the law, but EEX has held no {y} auction yet")
            continue
        if any(not lo <= p <= hi for _, p, _ in rows):
            sys.exit(f"EEX: {y} auctions outside the corridor ({rows[:3]})")
        vol = sum(v for _, _, v in rows)
        avg = round(sum(p * v for _, p, v in rows) / vol, 2)
        prices = sorted({p for _, p, _ in rows})
        excess = {"2026": 68, "2027": 73}.get(y)
        write(out, {"country": "DE", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "Brennstoffemissionshandel (nEHS) certificate price", "rate_per_t": avg,
                    "law": f"BEHG § 10 (2): {y} certificates are auctioned in a corridor of {m.group(4)} to {m.group(5)} euro. This is the volume-weighted clearing price of the {len(rows)} auctions EEX held ({rows[-1][0]} to {rows[0][0]}; clearing prices {', '.join(f'{p:g}' for p in prices)} euro)."
                           + (f" Certificates bought after the auctions cost {excess} euro (the excess quantity price), so a supplier's average may be a little higher." if excess else ""),
                    "sources": [src(srcs, "de-behg-10"), src(srcs, "de-eex-nehs-auctions")]})


def austria(fetched, out, srcs):
    """NEHG 2022 § 10 (1): the certificate value for 2024 and 2025, from
    RIS (via the Internet Archive, as RIS refuses the workflow). The law's
    table ends at 2025; the Federal Ministry of Finance, which runs the
    system, gives 55 euro for 2025 to 2027 (the fixed-price phase until EU
    ETS 2), so 2026 and 2027 are priced from its page."""
    vals, law_src = {}, None
    # The consolidated law read in Chrome (browser/at-nehg-10.txt), else
    # an archived RIS page.
    bp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser", "at-nehg-10.txt")
    bt = " ".join(l.strip() for l in open(bp, encoding="utf-8") if not l.startswith("#")) if os.path.exists(bp) else ""
    m = re.search(r"Die nationalen Emissionszertifikate haben einen Ausgabewert von: ?Kalenderjahr ?Betrag (.*?)(?: \(2\)|$| Anm)", bt)
    if m and "Fassung vom" in open(bp, encoding="utf-8").read():
        vals = dict(re.findall(r"(20\d\d) (\d+(?:,\d+)?) Euro", m.group(1)))
        law_src = "at-nehg-ris"
    for sid in ("at-nehg-current", "at-nehg") if not law_src else ():
        p = os.path.join(fetched, sid + ".html")
        t = text(p) if os.path.exists(p) else ""
        m = re.search(r"Die nationalen Emissionszertifikate haben einen Ausgabewert von: ?Kalenderjahr ?Betrag (.*?) \(2\)", t)
        if m:
            vals = dict(re.findall(r"(20\d\d) (\d+(?:,\d+)?) Euro", m.group(1)))
            law_src = sid
            break
    p = os.path.join(fetched, "at-bmf-nehg.html")
    t = text(p) if os.path.exists(p) else ""
    bmf = {}
    for m in re.finditer(r"(20\d\d)(?: - (20\d\d))? EUR (\d+), ?(\d\d)", t):
        for y in range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1):
            bmf[str(y)] = f"{m.group(3)},{m.group(4)}"
    if not law_src and not bmf:
        print("NEHG 2022: neither RIS nor the ministry's page was fetched; Austria not built")
        return
    for y in ("2024", "2025", "2026", "2027"):
        if law_src and y in vals:
            v, sid = vals[y], law_src
            law = f"NEHG 2022 § 10 (1): certificate value of {v} euro per tonne of CO2 in {y}."
        elif y in bmf:
            v, sid = bmf[y], "at-bmf-nehg"
            law = f"NEHG 2022 § 10: certificate value of {float(v.replace(',', '.')):g} euro per tonne of CO2 in {y}, as the Federal Ministry of Finance gives it for the fixed-price phase" + (" (the law's table ends at 2025)." if y > "2025" else ".")
        else:
            sys.exit(f"NEHG 2022: no value for {y}")
        write(out, {"country": "AT", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "Nationaler Emissionszertifikatehandel certificate value", "rate_per_t": float(v.replace(",", ".")),
                    "law": law + " Fuel suppliers pay it for the CO2 their fuel emits and pass it on in the fuel price.",
                    "sources": [src(srcs, sid)]})


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
    # A legislated increase postponed to a day: the last rate ends before it
    # (the new amount is in the law, not the manual).
    flat = re.sub(r"\s+", " ", t)
    m = re.search(r"postpone carbon tax increases, which had been legislated to come into effect in \d{4}, until (\d+ \w+ \d{4})", flat)
    ends = ""
    if m and merged and not merged[-1][1] and irish_date(m.group(1)) > merged[-1][0]:
        import datetime
        merged[-1][1] = (datetime.date.fromisoformat(irish_date(m.group(1))) - datetime.timedelta(days=1)).isoformat()
        ends = f" The manual says the increase legislated for 2026 is postponed to {m.group(1)}, so this rate ends the day before."
    for vf, vt, rate in merged:
        f = {"country": "IE", "currency": "EUR", "valid_from": vf,
             "name": "Carbon tax (carbon component of Mineral Oil Tax) on auto-diesel", "rate_per_t": rate,
             "law": f"Finance Act 1999 Schedule 2A, as Revenue's Excise Duty Rates manual gives it: the carbon component of Mineral Oil Tax on heavy oil used as a propellant (auto-diesel) charges {rate:.2f} euro per tonne of CO2 its burning emits. Fuel suppliers pay it with the Mineral Oil Tax and pass it on in the fuel price." + (ends if vt == merged[-1][1] and ends else ""),
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
        else:
            # The rate is published for a year (art. 92.º-A n.º 2 and 3):
            # the last is known to the end of the last year a source gives.
            f["valid_to"] = max([s[0][:4] for s in steps] + list(kept)) + "-12-31"
        write(out, f)


SI_MONTHS = {"januarja": 1, "februarja": 2, "marca": 3, "aprila": 4, "maja": 5, "junija": 6, "julija": 7,
             "avgusta": 8, "septembra": 9, "oktobra": 10, "novembra": 11, "decembra": 12}


def si_text(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    if t.lstrip().startswith("{"):
        # PISRS's API: the text's paragraphs in data.besedilo[].vsebina.
        t = " ".join(p.get("vsebina") or "" for p in json.loads(t)["data"]["besedilo"])
        t = html.unescape(re.sub(r"<[^>]+>", "", t))
    elif path.endswith(".html"):
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
    p = next((os.path.join(fetched, "si-uredba-48-2018" + e) for e in (".json", ".html") if os.path.exists(os.path.join(fetched, "si-uredba-48-2018" + e))), "")
    if not p:
        print("Slovenia: the Uredba wasn't fetched; not built")
        return
    t = si_text(p)
    if not re.search(r"enota obremenitve in je enaka emisiji 1 tone CO ?2", t):
        sys.exit("Slovenia: the Uredba doesn't define the unit as 1 tonne of CO2")
    m = re.search(r"znesek na enoto obremenitve zraka z emisijo CO ?2 ([\d,]+) eura", t)
    if not m:
        sys.exit("Slovenia: no amount in the Uredba")
    base = si_rate(m.group(1))
    sklepi = []  # (entry into force, [(from, rate)], source id, gazette)
    for sid in sorted(k for k in srcs if k.startswith("si-sklep-") and not k.endswith("-meta")):
        p = next((os.path.join(fetched, sid + e) for e in (".txt", ".html", ".json") if os.path.exists(os.path.join(fetched, sid + e))), None)
        if not p:
            print(f"Slovenia: {sid} wasn't fetched; not built")
            return
        t = si_text(p)
        # The gazette's header: "ŠT. 103/2026" and "Z DNE 20. 3. 2026" (two
        # columns in the PDF's text, so matched apart).
        no, dt = re.search(r"\bŠT\. (\d+)/(\d{4})\b", t), re.search(r"\bZ DNE (\d+)\. (\d+)\. (\d{4})\b", t)
        ul = re.match(r"(\d+)/(\d{4}) (\d+)\. (\d+)\. (\d{4})", f"{no.group(1)}/{no.group(2)} {dt.group(1)}. {dt.group(2)}. {dt.group(3)}") if no and dt else None
        meta = next((os.path.join(fetched, sid + "-meta" + e) for e in (".json", ".html") if os.path.exists(os.path.join(fetched, sid + "-meta" + e))), "")
        if not ul and meta:
            # PISRS's record of the act: gazette number and publication date.
            e = json.load(open(meta, encoding="utf-8"))["data"]["evidencniPodatki"]
            no, yy = e["ulStLeto"].split("/")
            y, mo, d = e["objavljeno"].split("-")
            ul = re.match(r"(\d+)/(\d{4}) (\d+)\. (\d+)\. (\d{4})", f"{no}/20{yy[-2:]} {int(d)}. {int(mo)}. {y}")
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


def dk_rates(path):
    """{year: (day temperature, 15 °C, 2015 base)} from a copy of the
    ministry's CO2-afgiftsloven rate table (two years a page)."""
    t = text(path)
    head = re.search(r"Afgiftssatser Grundbeløb i 2015 niveau ?(?:\d\) )?(\d{4}) (\d{4})", t)
    # The row's first line is the rate at day temperature, the second
    # ("afgiftssatsen ved 15 C udgør") at 15 °C; a cell may add a figure in
    # brackets with a note.
    v = r"(\d+,\d)(?: / \(\d+,\d\) ?\d? ?\)?)?"
    m = re.search(rf"Gas- og dieselolie ?- ?afgiftssatsen ved 15 C udgør øre/l {v} {v} {v} øre/l {v} {v} {v}", t)
    if not head or not m:
        sys.exit(f"CO2-afgiftsloven: no rate table for gas and diesel oil in {os.path.basename(path)}")
    x = [float(g.replace(",", ".")) for g in m.groups()]
    if not (x[0] > x[3] and x[1] > x[4] and x[2] > x[5]):
        sys.exit(f"CO2-afgiftsloven: day-temperature rates not above the 15 °C ones: {x}")
    return {int(head.group(1)): (x[1], x[4], x[0]), int(head.group(2)): (x[2], x[5], x[0])}


def denmark(fetched, out, srcs):
    # The current table (this year and next), then the Internet Archive's
    # copy of the 2025 one (2024 and 2025).
    rates = {}
    for sid in ("dk-svmn-co2afgift", "dk-skm-co2afgift-2025"):
        for y, r in dk_rates(os.path.join(fetched, sid + ".html")).items():
            rates.setdefault(y, (r, sid))
    for y, ((day, c15, base), sid) in sorted(rates.items()):
        # The table's 2015 base is the law's as it stands for its later
        # year; the earlier year's rate may rest on the law before (2024's
        # 51.9 øre on the base before the 2025 reform): the base is named
        # only where the rate is it indexed (about 1.2 since 2015).
        based = f"{base:.1f} øre per litre at day temperature in 2015 prices, indexed with the net price index (stk. 7)" if 1 <= day / base <= 1.6 else "indexed with the net price index (stk. 7)"
        write(out, {"country": "DK", "currency": "DKK", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31",
                    "name": "CO2-afgift on gas and diesel oil", "rate_per_l": round(day / 100, 4),
                    "law": f"CO2-afgiftsloven (lov om kuldioxidafgift af visse energiprodukter) § 2, stk. 1: the CO2 tax on gas and diesel oil, {based}: {day:.1f} øre per litre in {y} ({c15:.1f} øre at 15 °C), as Skatteministeriet's rate table gives it. "
                           "The supplier pays it on the fuel it sells and passes it on in the pump price, so a trip pays it where its fuel is bought. This is the rate for fossil diesel; diesel blended with 6.8 or 7.6% biofuel pays a little less per litre of blend. "
                           "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012).",
                    "sources": [src(srcs, sid)]})


SV_MONTHS = {m: i + 1 for i, m in enumerate(["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december"])}


def sweden(fetched, out, srcs):
    t = text(os.path.join(fetched, "se-skv-bransle.html"))
    periods = []
    for part in t.split("Skattesatser på bränsle från ")[1:]:
        d = re.match(r"(\d+) (\w+)(?: (\d{4}))?(?: till (\d+) (\w+) (\d{4}))? ", part)
        m = re.search(r"som inte har försetts med märk- och färgämnen och ger minst 85 volymprocent destillat vid 350 grader C, tillhörig miljöklass 1\.? ?([\d ]+) kronor per kubikmeter ([\d ]+) kronor per kubikmeter", part)
        if not d or not m or d.group(2) not in SV_MONTHS:
            continue  # a link to the section, not the section
        y1 = d.group(3) or d.group(6)
        start = f"{y1}-{SV_MONTHS[d.group(2)]:02d}-{int(d.group(1)):02d}"
        end = f"{d.group(6)}-{SV_MONTHS[d.group(5)]:02d}-{int(d.group(4)):02d}" if d.group(4) else None
        periods.append((start, end, int(m.group(2).replace(" ", ""))))
    periods = sorted(set(periods))
    if not any(e is None for _, e, _ in periods) or len(periods) < 4:
        sys.exit(f"Skatteverket's rate page: periods not found ({periods})")
    # From 2024, consecutive periods at the same rate joined.
    joined = []
    for s, e, r in periods:
        if (e or "9999") < "2024-01-01":
            continue
        if joined and joined[-1][2] == r and joined[-1][1] and (datetime.date.fromisoformat(joined[-1][1]) + datetime.timedelta(days=1)).isoformat() == s:
            joined[-1] = (joined[-1][0], e, r)
        else:
            joined.append((s, e, r))
    for s, e, r in joined:
        f = {"country": "SE", "currency": "SEK", "valid_from": s,
             "name": "Koldioxidskatt on diesel (environmental class 1)", "rate_per_l": r / 1000,
             "law": f"Lag (1994:1776) om skatt på energi, 2 kap. 1 §: the koldioxidskatt on unmarked diesel of environmental class 1, {r:,} kronor per cubic metre".replace(f"{r:,}", f"{r:,}".replace(",", " "))
                    + f" from {s}{' to ' + e if e else ''}, as Skatteverket's rate page gives it (the law's amounts, recalculated each year with the consumer price index, and the temporary reductions set by Parliament). "
                    "The supplier pays it on the fuel it sells and passes it on in the pump price, so a trip pays it where its fuel is bought. "
                    "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012).",
             "sources": [src(srcs, "se-skv-bransle")]}
        if e:
            f["valid_to"] = e
        write(out, f)


NO_MONTHS = {m: i + 1 for i, m in enumerate(["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "desember"])}


def norway(fetched, out, srcs):
    rates = {}
    for sid in ("no-avgiftssatser-2025", "no-avgiftssatser-2026"):
        t = text(os.path.join(fetched, sid + ".html"))
        h = re.search(r"Avgiftskategori (\d{4})-regler \D*?(\d{4})", t)
        m = re.search(r"CO ?2 ?-avgift på mineralske produkter Bensin, kr/liter [\d,]+ [\d,]+ [-\d,]+ Mineralolje, kr/liter generell sats (\d,\d\d) (\d,\d\d)", t)
        if not h or not m:
            sys.exit(f"{sid}: no CO2-avgift on mineral oil")
        for y, v in zip(h.groups(), m.groups()):
            v = float(v.replace(",", "."))
            if rates.get(int(y), (v,))[0] != v:
                sys.exit(f"{sid}: {y} CO2-avgift {v}, the other table {rates[int(y)][0]}")
            rates.setdefault(int(y), (v, sid))
    t = text(os.path.join(fetched, "no-co2-mai-2026.html"))
    m = re.search(r"Avgiftssatser (\d{4})\. Sats før 1\. (\w+) Sats fra 1\. (\w+) Sats fra 1\. (\w+) .{0,200}?Autodiesel, kr/liter (\d,\d\d) (\d,\d\d) (\d,\d\d)", t)
    if not m or int(m.group(1)) not in rates or m.group(3) != m.group(2) or m.group(3) not in NO_MONTHS or m.group(4) not in NO_MONTHS:
        sys.exit("no-co2-mai-2026: no road diesel rates by date")
    y = int(m.group(1))
    before, cut, after = (float(v.replace(",", ".")) for v in m.groups()[4:])
    if before != rates[y][0] or after != rates[y][0]:
        sys.exit(f"no-co2-mai-2026: {before}/{after}, the {y} table {rates[y][0]}")
    cut_from = datetime.date(y, NO_MONTHS[m.group(3)], 1)
    cut_to = datetime.date(y, NO_MONTHS[m.group(4)], 1)
    periods = [(datetime.date(yy, 1, 1), datetime.date(yy, 12, 31), v, [sid]) for yy, (v, sid) in sorted(rates.items()) if yy != y]
    periods += [(datetime.date(y, 1, 1), cut_from - datetime.timedelta(days=1), before, [rates[y][1]]),
                (cut_from, cut_to - datetime.timedelta(days=1), cut, [rates[y][1], "no-co2-mai-2026"]),
                (cut_to, datetime.date(y, 12, 31), after, [rates[y][1], "no-co2-mai-2026"])]
    for s, e, v, sids in periods:
        write(out, {"country": "NO", "currency": "NOK", "valid_from": s.isoformat(), "valid_to": e.isoformat(),
                    "name": "CO2-avgift on mineral oil", "rate_per_l": v,
                    "law": "Stortingets vedtak om CO2-avgift på mineralske produkter (under særavgiftsloven): "
                           + (f"the CO2-avgift on road diesel (autodiesel), temporarily reduced by regulation to kr {cut:.2f} per litre from {s} to {e} (the generell sats on mineral oil: kr {before:.2f})"
                              if s == cut_from else f"the CO2-avgift on mineral oil, generell sats, kr {v:.2f} per litre from {s} to {e}")
                           + ", as the Ministry of Finance's tables and press release give it. The importer or producer pays it and passes it on in the pump price, so a trip pays it where its fuel is bought. "
                           "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012).",
                    "sources": [src(srcs, sid) for sid in sids]})


def finland(fetched, out, srcs):
    raw = open(os.path.join(fetched, "fi-vero-verotaulukot.html"), encoding="utf-8", errors="replace").read()
    # Since November 2026 the page gives each table as JSON in an attribute
    # ({"column_0": {"text": "50 Dieselöljy"}, "column_1": ..., "column_2": ...});
    # before, as an HTML table. Both: the headings' text, then the table's rows
    # as "50 Dieselöljy <energy> <CO2> ".
    raw = html.unescape(raw)
    # (A row's first cell closes the tag the JSON sits in, so the rows stay as text.)
    raw = re.sub(r'\{"column_\d+":\{"text":"([^"]*)"[^}]*\}', lambda m: "> " + m.group(1) + " ", raw)
    raw = re.sub(r',"column_\d+":\{"text":"([^"]*)"[^}]*\}', lambda m: " " + m.group(1) + " ", raw)
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S)))
    periods = []
    for part in re.split(r"(?=Verotaulukko \d)", t):
        h = re.match(r"Verotaulukko 1a?: (\d+)\. ?(\d+)? ?\.? ?(\d{4})? ?[–-] ?(\d+)\.(\d+)\.(\d{4})", part)
        m = re.search(r"\b50 Dieselöljy (\d+,\d+) (\d+,\d+) ", part)
        if not h or not m:
            continue  # a link to the table, or table 2 (combined heat and power)
        s = datetime.date(int(h.group(3) or h.group(6)), int(h.group(2)), int(h.group(1)))
        e = datetime.date(int(h.group(6)), int(h.group(5)), int(h.group(4)))
        periods.append((s, e, round(float(m.group(2).replace(",", ".")), 2)))
    periods = sorted(set(periods))
    if len(periods) < 3:
        sys.exit(f"Verohallinto's tax tables: periods not found ({periods})")
    joined = []
    for s, e, v in periods:
        if e < datetime.date(2024, 1, 1):
            continue
        if joined and joined[-1][2] == v and joined[-1][1] + datetime.timedelta(days=1) == s:
            joined[-1] = (joined[-1][0], e, v)
        else:
            joined.append((s, e, v))
    for s, e, v in joined:
        write(out, {"country": "FI", "currency": "EUR", "valid_from": s.isoformat(), "valid_to": e.isoformat(),
                    "name": "Hiilidioksidivero on diesel oil", "rate_per_l": round(v / 100, 4),
                    "law": f"Laki nestemäisten polttoaineiden valmisteverosta (1472/1994), liite (tax table): the hiilidioksidivero (carbon dioxide tax) on diesel oil, product group 50, {v:.2f} cents per litre from {s} to {e}, as Verohallinto's tax tables give it. "
                           "The excise warehouse keeper pays it on the fuel it releases and passes it on in the pump price, so a trip pays it where its fuel is bought. This is the rate for fossil diesel oil; blends with renewable diesel pay less. "
                           "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012).",
                    "sources": [src(srcs, "fi-vero-verotaulukot")]})


def lithuania(fetched, out, srcs):
    p = os.path.join(fetched, "lt-muitine-akcizai-2026.txt")
    t = re.sub(r"\s+", " ", open(p, encoding="utf-8", errors="replace").read()) if os.path.exists(p) else ""
    source = src(srcs, "lt-muitine-akcizai-2026")
    if "anglies dioksido" not in t:
        # The workflow's copy is the site's bot check: the paragraph read in Chrome.
        cap = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser", "lt-muitine-akcizai-2026.txt")
        t = re.sub(r"\s+", " ", "\n".join(l for l in open(cap, encoding="utf-8") if not l.startswith("#")))
        source = dict(source, title=source["title"] + " (read in Chrome: tools/tables/browser/lt-muitine-akcizai-2026.txt)")
        print("Lithuanian customs notice: read from", cap)
    m = re.search(r"laikinai, t\. ?y\. (\d{4}) metais, nebus didinama anglies dioksido.{0,600}?bus taikoma (\d{4}) metais galiojusi CO2 dedamoji: .{0,3}gazoliams ir šildymui skirtiems gazoliams ?[–-] ?(\d+,\d+) euro už 1 000 litrų", t)
    if not m or int(m.group(1)) != int(m.group(2)) + 1:
        sys.exit("Lithuanian customs notice: no CO2 component for gas oils")
    v = float(m.group(3).replace(",", "."))
    for y in (m.group(2), m.group(1)):
        # Introduced in the first year: none before.
        write(out, {"country": "LT", "currency": "EUR", "valid_from": f"{y}-01-01", "valid_to": f"{y}-12-31", "charged_from": f"{m.group(2)}-01-01",
                    "name": "CO2 dedamoji of the excise duty on gas oils", "rate_per_l": round(v / 1000, 5),
                    "law": f"Akcizų įstatymas Nr. IX-569, 37 straipsnio 1 dalis and 3 priedas: the excise duty on gas oils (diesel) has a fixed part and a variable CO2 part (CO2 dedamoji), EUR {v:.1f} per 1,000 litres in {y}"
                           + (f" (introduced on 1 January {y})" if y == m.group(2) else f" (kept at the {m.group(2)} amount by law XV-679 instead of rising)")
                           + ", as the customs department's notice gives it. The excise payer passes it on in the pump price, so a trip pays it where its fuel is bought. "
                           "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012).",
                    "sources": [source]})


LU_SHEETS = ["lu-douanes-taux-2024", "lu-douanes-taux-2025", "lu-douanes-taux-2026"]


def luxembourg(fetched, out, srcs):
    for sid in LU_SHEETS:
        t = re.sub(r"\s+", " ", open(os.path.join(fetched, sid + ".txt"), encoding="utf-8", errors="replace").read())
        y = re.search(r"Taux d'accises applicables pour l'année (\d{4})", t)
        # UEBL, ¹ accise autonome, total, VAT; ² contribution sociale; ³ taxe CO2.
        m = re.search(r"Gasoil /1000 l.{0,300}?contenant ≤ 10 mg/kg soufre (\d+,\d{4}) € \D{0,3}(\d+,\d{4}) € (\d+,\d{4}) € 17%.{0,300}?(\d+,\d{4}) €.{0,300}?(\d+,\d{4}) €", t)
        if not y or not m:
            sys.exit(f"{sid}: no gas oil motor fuel row")
        uebl, auto, total, social, co2 = (float(v.replace(",", ".")) for v in m.groups())
        if abs(uebl + auto + social + co2 - total) > 0.001:
            sys.exit(f"{sid}: gas oil parts {uebl} + {auto} + {social} + {co2} don't make {total}")
        yr = y.group(1)
        write(out, {"country": "LU", "currency": "EUR", "valid_from": f"{yr}-01-01", "valid_to": f"{yr}-12-31",
                    "name": "Taxe CO2 on gas oil used as motor fuel", "rate_per_l": round(co2 / 1000, 5),
                    "law": f"Règlement grand-ducal modifié du 17 décembre 2010 fixant les taux applicables en matière de droits d'accise autonomes sur les produits énergétiques, art. 3: the droit d'accise autonome additionnel « taxe CO2 » on gas oil used as motor fuel, EUR {co2:.2f} per 1,000 litres at 15 °C in {yr}, as the customs' rate sheet for {yr} gives it (part of EUR {total:.2f} of excise in all). "
                           "The excise payer passes it on in the pump price, so a trip pays it where its fuel is bought. "
                           "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012).",
                    "sources": [src(srcs, sid)]})


IS_VERSIONS = ("is-althingi-129-2009-154b", "is-althingi-129-2009-156b", "is-althingi-129-2009-158a")
IS_MONTHS = {"jan": 1, "feb": 2, "mars": 3, "mar": 3, "apr": 4, "apríl": 4, "maí": 5, "júní": 6, "jún": 6, "júlí": 7, "júl": 7,
             "ágúst": 8, "ág": 8, "sept": 9, "sep": 9, "okt": 10, "nóv": 11, "des": 12}


def iceland(fetched, out, srcs):
    """Kolefnisgjald on gas and diesel oil, from three versions of Lög um
    umhverfis- og auðlindaskatta nr. 129/2009 in Alþingi's lagasafn: each
    gives the amount, the law that set it (the footnote) and that law's
    entry into force (the "Breytt með" list)."""
    found = []
    for sid in IS_VERSIONS:
        t = text(os.path.join(fetched, sid + ".html"))
        v = re.search(r"Íslensk lög (\d+\. \w+ \d{4})\. Útgáfa (\w+)\.", t)
        # The amount is in 1. gr.: the article that follows it is 2. gr. (Gjaldskyldir aðilar).
        m = re.search(r"Fjárhæð kolefnisgjalds skal vera \[(\d+,\d+) kr\.\] ?1\) á hvern lítra af gas- og dísilolíu.{0,400}?1\) ?L\. (\d+/\d{4}), (\d+)\. gr\..{0,60}?Gjaldskyldir aðilar\. 2\. gr\.", t)
        if not v or not m:
            sys.exit(f"Lög nr. 129/2009 ({sid}): kolefnisgjald on gas and diesel oil not read")
        law = m.group(2)
        f = re.search(rf"L\. {re.escape(law)} \(tók[iu] gildi (\d+)\. (\w+)\.? (\d{{4}})", t)
        if not f or f.group(2).lower() not in IS_MONTHS:
            sys.exit(f"Lög nr. 129/2009 ({sid}): entry into force of L. {law} not read")
        start = datetime.date(int(f.group(3)), IS_MONTHS[f.group(2).lower()], int(f.group(1)))
        found.append((start, float(m.group(1).replace(",", ".")), law, m.group(3), v.group(2), v.group(1), sid))
    found = sorted(set(found))
    for i, (start, rate, law, art, ver, asof, sid) in enumerate(found):
        if i and found[i - 1][1] == rate:
            sys.exit(f"Lög nr. 129/2009: {ver} gives the same amount as {found[i - 1][4]}")
        end = found[i + 1][0] - datetime.timedelta(days=1) if i + 1 < len(found) else None
        if end and end < datetime.date(2024, 1, 1):
            continue
        f = {"country": "IS", "currency": "ISK", "valid_from": start.isoformat(),
             "name": "Kolefnisgjald on gas and diesel oil", "rate_per_l": rate,
             "law": f"Lög um umhverfis- og auðlindaskatta nr. 129/2009, 1. gr. (kolefnisgjald, the carbon tax on fossil fuel): {rate:.2f} kr. per litre of gas and diesel oil, as amended by L. {law}, {art}. gr. (in force {start}), in Alþingi's lagasafn útgáfa {ver} ({asof}). "
                    "The importer or producer pays it on the fuel it sells and passes it on in the pump price, so a trip pays it where its fuel is bought. "
                    "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012).",
             "sources": [src(srcs, sid)]}
        if end:
            f["valid_to"] = end.isoformat()
        write(out, f)


PL_TEXTS = (("pl-dzu-2024-54", "2024-01-01", "Dz.U. 2024 poz. 54"), ("pl-dzu-2025-647", "2025-05-09", "Dz.U. 2025 poz. 647"))


def poland(fetched, out, srcs):
    """Opłata emisyjna on diesel (Prawo ochrony środowiska, art. 321f), from
    the consolidated texts of 2024 and 2025: one table while the amount is
    the same."""
    found = []
    for sid, frm, cite in PL_TEXTS:
        p = os.path.join(fetched, sid + ".txt")
        if not os.path.exists(p):
            print(f"Poland: {sid} not fetched")
            return
        t = re.sub(r"\s+", " ", open(p, encoding="utf-8", errors="replace").read())
        m = re.search(r"Art\. 321f\.\S* ?Stawka opłaty emisyjnej dla: ?1\) ?benzyn silnikowych ?[–-] ?wynosi (\d+) zł za 1000 litrów; ?"
                      r"2\) ?olejów napędowych ?[–-] ?wynosi (\d+) zł za 1000 litrów", t)
        if not m:
            # Not fatal: the other countries' tables are still built.
            print(f"::warning title=fuel_co2 Poland::art. 321f not read in {sid}; no Polish table")
            return
        found.append((frm, int(m.group(2)), cite, sid))
    tables = []
    for frm, v, cite, sid in found:
        if tables and tables[-1][1] == v:
            tables[-1][2].append((cite, sid))
        else:
            tables.append((frm, v, [(cite, sid)]))
    for i, (frm, v, cites) in enumerate(tables):
        f = {"country": "PL", "currency": "PLN", "valid_from": max(frm, "2024-01-01"),
             "name": "Opłata emisyjna on diesel", "rate_per_l": round(v / 1000, 4),
             "law": (f"Ustawa Prawo ochrony środowiska, art. 321f pkt 2: the opłata emisyjna (emission fee) on diesel oil, PLN {v} per 1,000 litres, "
                     f"in the consolidated texts {' and '.join(c for c, _ in cites)}. It is a fixed amount per litre, not priced on CO2; the producer or importer pays it "
                     "with the excise duty and passes it on in the pump price, so a trip pays it where its fuel is bought. "
                     "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012)."),
             "sources": [src(srcs, sid) for _, sid in cites]}
        if i + 1 < len(tables):
            f["valid_to"] = (datetime.date.fromisoformat(tables[i + 1][0]) - datetime.timedelta(days=1)).isoformat()
        write(out, f)


AL_VERSIONS = {7: "8d0003921e21dac195d23ab5752446ffe3127d084dfff35955eeec44c11418ee",
               8: "b5907d93045650237acd40393290f7e12189d9b62ee3f417533db37139f5dcc7"}  # as QBZ gives them


def albania(fetched, out, srcs):
    """Taksa e karbonit on gazoil (Ligj 9975/2008, neni 4 pika 6), from the
    consolidated versions in force since 2024 (7: ligj 38/2023; 8: ligj
    96/2023, whose 15 days to entry into force ran into January 2024). Both
    must give the same rate; QBZ's list of versions must hold no later one,
    or the table ends the day before it."""
    import hashlib
    vers = json.load(open(os.path.join(fetched, "al-qbz-9975-versions.json"), encoding="utf-8"))
    rates = {}
    for n, sha in AL_VERSIONS.items():
        pdf, txt = os.path.join(fetched, f"al-qbz-9975-v{n}.pdf"), os.path.join(fetched, f"al-qbz-9975-v{n}.txt")
        if hashlib.sha256(open(pdf, "rb").read()).hexdigest() != sha:
            sys.exit(f"Ligj 9975 version {n}: the PDF's sha256 is not the one QBZ gives")
        if not any(v.get("versionNo") == n and (v.get("pdf") or {}).get("sha256") == sha for v in vers):
            sys.exit(f"Ligj 9975 version {n}: not in QBZ's list of versions")
        t = re.sub(r"\s+", " ", open(txt, encoding="utf-8", errors="replace").read())
        # (A page number may fall between the lines: "masën: 4 a) 1,5 lekë".)
        m = re.search(r"Taksa e karbonit caktohet në masën:? ?(?:\d{1,3} )?(?:a\) ?)?(\d+(?:,\d+)?) lekë për litër për benzinën[;,] ?(?:\d{1,3} )?(?:b\) ?)?(\d+(?:,\d+)?) lekë për litër për gazoilin", t)
        if not m:
            sys.exit(f"Ligj 9975 version {n}: neni 4 pika 6 (taksa e karbonit) not read")
        rates[n] = float(m.group(2).replace(",", "."))
    if len(set(rates.values())) != 1:
        sys.exit(f"Ligj 9975: versions 7 and 8 give different rates on gazoil ({rates}); split the table")
    v = rates[8]
    f = {"country": "AL", "currency": "ALL", "valid_from": "2024-01-01",
         "name": "Taksa e karbonit on gazoil", "rate_per_l": v,
         "law": f"Ligj nr. 9975, datë 28.7.2008, Për taksat kombëtare, neni 4 pika 6 shkronja b: the taksa e karbonit (carbon tax) on gazoil (diesel), {v:g} lekë per litre, "
                "the same in the consolidated versions 7 (ligj nr. 38/2023) and 8 (ligj nr. 96/2023) that QBZ publishes. It is a fixed amount per litre, not priced on CO2; "
                "customs collects it on imported gazoil and the tax administration on gazoil produced in Albania (neni 5), and it is passed on in the pump price, so a trip pays it where its fuel is bought. "
                "Litres are the trip's road fuel as given (diesel_l), or its tank-to-wheel CO2 at 2.67 kg per litre of diesel (EN 16258:2012).",
         "sources": [src(srcs, "al-qbz-9975-v7"), src(srcs, "al-qbz-9975-v8")]}
    later = sorted((v for v in vers if v.get("versionNo", 0) > max(AL_VERSIONS)), key=lambda v: v["versionNo"])
    if later:
        f["valid_to"] = (datetime.date.fromisoformat(later[0]["validFrom"]) - datetime.timedelta(days=1)).isoformat()
        print(f"::warning title=fuel_co2 Albania::QBZ lists version {later[0]['versionNo']} of ligj 9975 (from {later[0]['validFrom']}); add it to AL_VERSIONS and sources.json")
    write(out, f)


def main(fetched, out):
    os.makedirs(out, exist_ok=True)
    srcs = {s["id"]: s for s in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json"), encoding="utf-8"))["sources"]}
    # One country's source failing doesn't stop the others; the builder
    # still fails at the end, naming them.
    failed = []
    for country in (germany, austria, ireland, portugal, slovenia, denmark, sweden, norway, finland, lithuania, luxembourg, iceland, poland, albania):
        try:
            country(fetched, out, srcs)
        except (SystemExit, Exception) as e:  # a missing copy raises OSError
            print(f"{country.__name__}: {type(e).__name__ if not isinstance(e, SystemExit) else ''} {e}".replace("  ", " "), file=sys.stderr, flush=True)
            failed.append(country.__name__)
    if failed:
        sys.exit("fuel CO2: not built for " + ", ".join(failed))

if __name__ == "__main__":
    main(*sys.argv[1:])

"""Transcribes Spain's driving restrictions for trucks over 7.5 t from the
DGT's yearly resolution (anexo II, apartado B.1.1) into a ban calendar,
bans/data/es-<year>.json, from the text fetch.py saved
(pdftotext -layout of the BOE's consolidated PDF).

Each table row is a road section, its hours and its direction; a heading
gives its days: "Todos los domingos del mes de junio" (every such weekday
in the range) or "Viernes 27 y domingo 29 de marzo" (those days). Rows
whose road cell spans several lines (the N-230's three sections) and
hours stacked over a row (two windows) are read as one row. Days marked
(*) also hold on the national holidays in their range (HOLIDAYS) and,
says the note, on the affected autonomous community's.

Usage: python3 es_bans.py fetched/es-bans-2026.txt [out.json]
check_bans.py runs it on the fetched text and compares the result with
the committed calendar.
"""
import datetime as dt
import json
import re
import sys

YEAR = 2026
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = {"lunes": "mon", "martes": "tue", "miércoles": "wed", "jueves": "thu", "viernes": "fri", "sábado": "sat", "domingo": "sun"}
# The national holidays of the year (Resolución de 17 de octubre de 2025,
# de la Dirección General de Trabajo, BOE-A-2025-21667, the days all
# communities keep), for the days marked (*).
HOLIDAYS = {2026: ["2026-01-01", "2026-01-06", "2026-04-03", "2026-05-01", "2026-08-15", "2026-10-12", "2026-12-08", "2026-12-25"]}

ROAD = r"[A-Z]{1,3}(?:-[A-Z])?-\d+[A-Z]?(?:\s?/\s?[A-Z]{1,3}-\d+[A-Z]?)?"
PK = r"\d+(?:,\s?\d+)?"
HOURS = r"\d{2}[,:]\d{2}\s?-\s?\d{2}[,:]\d{2}"
ROW = re.compile(rf"^\s*(?P<road>{ROAD})?\s+(?P<pk1>{PK})\s+(?P<p1>\S.*?)\s{{2,}}(?P<pk2>{PK})\s+(?P<p2>\S.*?)"
                 rf"(?:\s{{2,}}(?P<hours>{HOURS}))?(?:\s{{2,}}(?P<dir>\S.*?))?\s*$")
HOURS_ONLY = re.compile(rf"^\s*(?P<hours>{HOURS})\s*$")


def hm(s):
    a, b = re.split(r"\s?-\s?", s.strip())
    return tuple(x.replace(",", ":") for x in (a, b))


def pk(s):
    return re.sub(r",\s?", ".", s)


def place(s):
    return re.sub(r"\s+", " ", s.strip().rstrip("."))


def direction_en(s):
    """The table's Sentido in English: Ambos sentidos, Entrada / Salida
    Madrid, Sentido Sevilla, or a place it goes towards."""
    s = place(s)
    if s.lower() == "ambos sentidos":
        return "both directions"
    if m := re.match(r"(?i)sentido creciente(.*)", s):
        return "in the direction of rising km" + m[1]
    s = re.sub(r"(?i)^(entrada|salida) de ", r"\1 ", s)
    s = re.sub(r"(?i)\bfrontera francia\b", "the French border", s)
    s = re.sub(r"(?i)\bfrontera portugal\b", "the Portuguese border", s)
    for es, en in (("Entrada ", "into "), ("Salida ", "out of "), ("Sentido ", "towards ")):
        if s.startswith(es):
            return en + s[len(es):]
    return "towards " + s


def months_in(text):
    return [MESES.index(m) + 1 for m in re.findall("|".join(MESES), text)]


def period_days(head):
    """The days of a heading of a) periodos genéricos: [(from, to,
    weekday)] and whether holidays (*) count."""
    h = head.lower()
    weekdays = [w for word, w in (("viernes", "fri"), ("sábados", "sat"), ("domingos", "sun")) if word in h]
    ranges = []
    for part in re.split(r",\s*y\s+(?=entre)", h):
        if m := re.search(rf"entre el (\d+) de ({'|'.join(MESES)}) y el (\d+) de ({'|'.join(MESES)})", part):
            ranges.append((dt.date(YEAR, MESES.index(m[2]) + 1, int(m[1])), dt.date(YEAR, MESES.index(m[4]) + 1, int(m[3]))))
        elif m := re.search(rf"entre el (\d+) y (\d+) de ({'|'.join(MESES)})", part):
            mo = MESES.index(m[3]) + 1
            ranges.append((dt.date(YEAR, mo, int(m[1])), dt.date(YEAR, mo, int(m[2]))))
        elif ms := months_in(part):
            a, b = min(ms), max(ms)
            if f"entre {MESES[a - 1]} y {MESES[b - 1]}" in part or len(ms) > 1 or "mes de" in part:
                ranges.append((dt.date(YEAR, a, 1), dt.date(YEAR, b + 1, 1) - dt.timedelta(days=1) if b < 12 else dt.date(YEAR, 12, 31)))
    if not weekdays or not ranges:
        raise ValueError(f"can't read the period {head!r}")
    return [(a, b, w) for a, b in ranges for w in weekdays], "festivos" in h


def dated_days(head):
    """The days of a heading of b) por fechas."""
    h = head.lower()
    h = re.sub(r"\(.*?\)", "", h)
    if m := re.search(rf"del \w+ (\d+) al \w+ (\d+) de ({'|'.join(MESES)})", h):
        mo = MESES.index(m[3]) + 1
        a, b = dt.date(YEAR, mo, int(m[1])), dt.date(YEAR, mo, int(m[2]))
        return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]
    days, pending = [], []
    for tok in re.findall(rf"\d+|{'|'.join(MESES)}", h):
        if tok.isdigit():
            pending.append(int(tok))
        else:
            days += [dt.date(YEAR, MESES.index(tok) + 1, d) for d in pending]
            pending = []
    if pending or not days:
        raise ValueError(f"can't read the dates {head!r}")
    return days


def heading(line):
    s = line.strip()
    if s.startswith("Todos los"):
        return s
    if re.match(r"^(Del )?(Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo)\b", s, re.I) and not ROW.match(line):
        return s
    return None


def parse(text):
    a = re.search(r"\n\s*ANEXO II\s*\n", text)
    b = re.search(r"\n\s*ANEXO III\s*\n", text[a.end():])
    lines = text[a.end():a.end() + b.start()].replace("\f", "\n").splitlines()
    entries, head, generic = [], None, True
    rows, pending, need_after = [], [], 0

    def flush():
        nonlocal rows, pending, need_after
        if pending and rows:
            rows[-1]["after"] += pending
        for r in rows:
            entries.append((head, generic, r))
        rows, pending, need_after = [], [], 0

    for line in lines:
        s = line.strip()
        if "Restricciones por fechas" in s:
            flush()
            generic = False
            continue
        if h := heading(line):
            flush()
            head = h
            continue
        if s.startswith("(Excepto"):
            flush()
            entries[-1][2]["except"] = s.strip("().")
            continue
        m = ROW.match(line)
        hours_only = HOURS_ONLY.match(line)
        if not (m or hours_only):
            if head is None:
                continue  # the annex's title
            if s and not s.startswith(("Inicio", "Ctra.", "P.K.", "Página", "BOLETÍN", "LEGISLACIÓN", "(*)", "a) ", "b) ")):
                raise ValueError(f"unread line under {head!r}: {s!r}")
            if not s or s.startswith(("Inicio", "Página", "(*)")):
                flush()
            continue
        if m and m["road"]:
            # A row with its road: it takes the continuation lines just
            # above it, and as many just below (a cell centred on it).
            rows.append({"m": m, "before": pending, "after": []})
            need_after, pending = len(pending), []
        elif need_after > 0 and rows:
            rows[-1]["after"].append(m or hours_only)
            need_after -= 1
        else:
            pending.append(m or hours_only)
    flush()
    return entries


def calendar(text):
    days = []
    seen = set()
    for head, generic, r in parse(text):
        m = r["m"]
        lines = r["before"] + [m] + r["after"]
        hours = [hm(x["hours"]) for x in lines if x["hours"]]
        if not hours:
            raise ValueError(f"no hours for {m['road']} under {head!r}")
        dirs = [x["dir"] for x in lines if x.groupdict().get("dir")]
        direction = direction_en(dirs[0]) if dirs else ""
        sections = ", ".join(f"{place(x['p1'])} (km {pk(x['pk1'])}) to {place(x['p2'])} (km {pk(x['pk2'])})"
                             for x in lines if "pk1" in x.groupdict())
        road = re.sub(r"\s", "", m["road"])
        roads = road.split("/")
        note = f"on the {road} from {sections}" + (f", {direction}" if direction else "")
        if r.get("except"):
            note += " (except trips to the driver's home, the vehicle's registered base or the company's base)"
        specs = []
        if generic:
            ranges, holidays = period_days(head)
            for a, b, w in ranges:
                specs.append({"from_date": a.isoformat(), "to_date": b.isoformat(), "weekday": w})
            if holidays:
                for d in HOLIDAYS[YEAR]:
                    day = dt.date.fromisoformat(d)
                    if any(a <= day <= b for a, b, _ in ranges) and day.strftime("%a").lower()[:3] not in [w for _, _, w in ranges]:
                        specs.append({"date": d, "holiday": True})
        else:
            specs = [{"date": d.isoformat()} for d in dated_days(head)]
        for spec in specs:
            for f, t in hours:
                day = {k: v for k, v in spec.items() if k != "holiday"}
                day.update({"from": f, "to": t, "listed": True, "roads": roads,
                            "note": note + (", a national holiday (and the affected autonomous community's holidays)" if spec.get("holiday") else ""),
                            "heading": head})
                key = json.dumps(day, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    days.append(day)
    return days


def main(path, out=None):
    text = open(path, encoding="utf-8", errors="replace").read()
    cal = {
        "about": f"Spain's {YEAR} restrictions for trucks over 7.5 t on the roads the DGT's yearly resolution lists (apartado B.1.1, anexo II), "
                 "generated from the BOE's consolidated text by tools/tables/es_bans.py; tools/tables/check_bans.py regenerates it and compares. "
                 "Each holds only on its road section and direction, so a trip is said to may run into it. The DGT's resolution doesn't cover "
                 "Catalonia and the Basque Country, which set their own.",
        "country": "ES", "year": YEAR, "check": "es-generated",
        "law": f"Resolución de 14 de enero de {YEAR}, de la Dirección General de Tráfico, por la que se establecen medidas especiales de regulación de tráfico durante el año {YEAR}, B.1.1 and anexo II",
        "source": {"id": f"es-bans-{YEAR}", "title": f"BOE-A-{YEAR}-1255 (consolidated text): medidas especiales de regulación de tráfico durante el año {YEAR}",
                   "url": f"https://boe.es/buscar/pdf/{YEAR}/BOE-A-{YEAR}-1255-consolidado.pdf"},
        "days": calendar(text),
    }
    # One day a line, for diffs.
    days = cal.pop("days")
    head = json.dumps(cal, ensure_ascii=False, indent=1)
    s = head[:-2] + ',\n "days": [\n' + ",\n".join("  " + json.dumps(d, ensure_ascii=False) for d in days) + "\n ]\n}\n"
    if out:
        open(out, "w", encoding="utf-8").write(s)
    else:
        sys.stdout.write(s)


if __name__ == "__main__":
    main(*sys.argv[1:])

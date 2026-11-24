"""Builds fuel/data/national-diesel.csv: the official average pump price of
road diesel in countries the EU's Weekly Oil Bulletin doesn't cover, in
the national currency per litre with VAT, with the VAT rate to take out:

- GB: the Department for Energy Security and Net Zero's weekly road fuel
  prices (UK average ULSD pump price, pence per litre, and its VAT rate),
  the CSV attachment of
  https://www.gov.uk/government/statistics/weekly-road-fuel-prices, found
  through GOV.UK's content API; each Monday;
- NO: Statistics Norway's table 09654, prices on engine fuel (NOK per
  litre, average retail prices with taxes), taxed auto diesel, each month;
  VAT 25% (merverdiavgiftsloven § 5-1, the general rate);
- CH: the Federal Statistical Office's average prices for energy and
  motor fuels in the consumer price index (LIK, Durchschnittspreise für
  Energie und Treibstoffe), diesel, CHF per litre, each month; VAT 8.1%
  (MWSTG Art. 25, the normal rate from 2024).

From FROM on. A country whose source can't be read keeps the rows of
the committed file (the previous one, given as the third argument).

Usage: python3 national_diesel.py out.csv [previous.csv]
"""
import csv, io, json, re, sys, urllib.request

FROM = "2024-01-01"
UA = {"User-Agent": "carbon-cost (github.com/majidkabir/carbon-cost)"}
FIELDS = ["date", "country", "currency", "per_l", "vat_pct", "source"]


def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data, {**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def gb():
    meta = json.loads(get("https://www.gov.uk/api/content/government/statistics/weekly-road-fuel-prices"))
    docs = meta.get("details", {}).get("attachments") or []
    urls = [a.get("url") for a in docs if (a.get("url") or "").lower().endswith(".csv")]
    if not urls:
        # A statistics announcement points to the data set's page.
        raise ValueError(f"no CSV attachment; keys {sorted(meta.get('details', {}))}")
    text = get(urls[0]).decode("utf-8-sig", "replace")
    rows = list(csv.reader(io.StringIO(text)))
    head = [h.lower() for h in rows[0]]
    col = lambda *words: next(i for i, h in enumerate(head) if all(w in h for w in words))
    di, pi, vi = col("date"), col("ulsd", "pump price"), col("ulsd", "vat")
    out = []
    for r in rows[1:]:
        if len(r) <= max(di, pi, vi) or not r[pi].strip():
            continue
        d, m, y = r[di].strip().split("/")
        date = f"{y}-{m}-{d}"
        if date >= FROM:
            out.append({"date": date, "country": "GB", "currency": "GBP", "per_l": round(float(r[pi]) / 100, 4), "vat_pct": float(r[vi]),
                        "source": "DESNZ weekly road fuel prices, UK average ULSD pump price (" + urls[0].rsplit("/", 1)[-1] + ")"})
    return out


def no():
    base = "https://data.ssb.no/api/v0/en/table/09654"
    meta = json.loads(get(base))
    query, prod = [], None
    for v in meta["variables"]:
        if v["code"].lower() in ("tid", "time"):
            continue
        texts = [t.lower() for t in v["valueTexts"]]
        hit = [i for i, t in enumerate(texts) if "diesel" in t and "tax" in t and "free" not in t and "exempt" not in t] or [i for i, t in enumerate(texts) if "diesel" in t]
        if hit and v["code"] != "ContentsCode":
            prod = v["valueTexts"][hit[0]]
            query.append({"code": v["code"], "selection": {"filter": "item", "values": [v["values"][hit[0]]]}})
        elif v["code"] == "ContentsCode":
            query.append({"code": v["code"], "selection": {"filter": "item", "values": [v["values"][0]]}})
    body = json.dumps({"query": query, "response": {"format": "json-stat2"}}).encode()
    d = json.loads(get(base, body, {"Content-Type": "application/json"}))
    times = d["dimension"]["Tid"]["category"]["index"]
    vals = d["value"]
    out = []
    for t, i in sorted(times.items(), key=lambda x: x[1]):
        y, m = t.split("M")
        date = f"{y}-{int(m):02d}-01"
        v = vals[i] if isinstance(vals, list) else vals.get(str(i))
        if v is not None and date >= FROM:
            out.append({"date": date, "country": "NO", "currency": "NOK", "per_l": v, "vat_pct": 25.0,
                        "source": f"Statistics Norway, table 09654, {prod}, monthly average retail price with taxes"})
    return out


def ch():
    import openpyxl
    lst = json.loads(get("https://dam-api.bfs.admin.ch/hub/api/dam/assets?orderNr=cc-d-05.02.91&limit=5"))
    items = lst.get("data") or lst.get("items") or lst if isinstance(lst, list) else lst.get("data", [])
    if not items:
        raise ValueError(f"no asset: {str(lst)[:300]}")
    a = items[0]
    aid = a.get("ipath") or a.get("id") or a.get("assetId")
    link = next((l["href"] for l in a.get("links", []) if l.get("rel") == "master"), f"https://dam-api.bfs.admin.ch/hub/api/dam/assets/{aid}/master")
    wb = openpyxl.load_workbook(io.BytesIO(get(link)), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        hdr = next(((i, r) for i, r in enumerate(rows) if any(isinstance(c, str) and "diesel" in c.lower() for c in r)), None)
        if not hdr:
            continue
        hi, h = hdr
        dc = next(j for j, c in enumerate(h) if isinstance(c, str) and "diesel" in c.lower())
        for r in rows[hi + 1:]:
            d, v = r[0], r[dc] if dc < len(r) else None
            if hasattr(d, "year") and isinstance(v, (int, float)):
                date = f"{d.year}-{d.month:02d}-01"
                if date >= FROM:
                    out.append({"date": date, "country": "CH", "currency": "CHF", "per_l": round(float(v), 4), "vat_pct": 8.1,
                                "source": f"Federal Statistical Office, LIK average prices for energy and motor fuels, diesel (asset {aid})"})
        if out:
            break
    if not out:
        raise ValueError(f"no diesel column in asset {aid}")
    return out


def main(dst, prev=None):
    old = list(csv.DictReader(open(prev, encoding="utf-8"))) if prev else []
    rows = []
    for cc, fn in [("GB", gb), ("NO", no), ("CH", ch)]:
        try:
            got = fn()
            print(f"{cc}: {len(got)} rows, {got[0]['date']} to {got[-1]['date']}, last {got[-1]['per_l']} {got[-1]['currency']}")
            rows += got
        except Exception as e:
            kept = [r for r in old if r["country"] == cc]
            print(f"::warning title=national diesel {cc}::not read ({e}); keeping {len(kept)} committed rows")
            rows += kept
    rows.sort(key=lambda r: (r["country"], r["date"]))
    w = csv.DictWriter(open(dst, "w", newline="", encoding="utf-8"), fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)


if __name__ == "__main__":
    main(*sys.argv[1:])

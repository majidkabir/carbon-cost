"""Reads JP Putevi Srbije's toll price list (cene_putarina_lat.pdf, as
pdftotext -layout text): from each entry station it heads a table with
(Beograd, Dimitrovgrad, Preševo, Šid, Stara Pazova, Obrenovac; earlier
lists Šimanovci), the toll to each station on its section, in RSD (the
decision's amounts) and in EUR. Serbia's tables are the decision's
(tools/rs/gazette.py); the list's RSD amounts check them.

Names are matched to OpenStreetMap's toll booths as key() gives them.
"""
import json, re, sys
from collections import defaultdict

CYR = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџшАБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШ",
               ["a","b","v","g","d","đ","e","ž","z","i","j","k","l","lj","m","n","nj","o","p","r","s","t","ć","u","f","h","c","č","dž","š",
                "A","B","V","G","D","Đ","E","Ž","Z","I","J","K","L","Lj","M","N","Nj","O","P","R","S","T","Ć","U","F","H","C","Č","Dž","Š"]))
# The price list's names (some misspelt) -> OpenStreetMap's.
FIX = {
    "KRUŠEVAC east": "kruševac istok", "KRUŠEVAC west": "kruševac zapad",
    "NIČ Malča": "malča", "NIŠ Malča": "malča", "NIŠ MALČA": "malča", "NiŠ istok": "niš istok", "BELA PALANK": "bela palanka",
    "VLAČICIN HAN": "vladičin han", "MEROČINA": "merošina", "MOROVIĆ / ADAŠEVCI": "adaševci",
    "ČAČAK (Pakovraće)": "pakovraće", "PRELJINA JUG": "preljina konjevići", "PRESEVO": "preševo",
    # Earlier lists' spellings.
    "ADAŠEVCI": "adaševci", "BUJANOVAC jud": "bujanovac jug", "PRELJINA": "preljina konjevići", "ČAĆAK (Pakovraće)": "pakovraće",
}
# One price-list name for several stations.
MANY = {"novi sad": ["novi sad - sever", "novi sad - jug"]}
# Canonical display names.
DISPLAY = {"BELA PALANK": "BELA PALANKA", "VLAČICIN HAN": "VLADIČIN HAN", "MEROČINA": "MEROŠINA", "NIČ Malča": "NIŠ Malča",
           "NiŠ istok": "NIŠ istok", "KRUŠEVAC east": "KRUŠEVAC istok", "KRUŠEVAC west": "KRUŠEVAC zapad", "PRESEVO": "PREŠEVO"}
SYSTEMS = {"BEOGRAD": "A1, A4 Beograd – Niš – Preševo / Dimitrovgrad", "DIMITROVGRAD": "A1, A4 Beograd – Niš – Preševo / Dimitrovgrad",
           "PRESEVO": "A1, A4 Beograd – Niš – Preševo / Dimitrovgrad", "ŠID": "A3 Beograd – Šid",
           "STARA PAZOVA": "A1 Beograd – Subotica", "OBRENOVAC": "A2 Beograd – Požega"}


def lat(s):
    return "".join(CYR.get(c, c) for c in s)


def key(s):
    s = FIX.get(s.strip(), s.strip())
    s = re.sub(r"\s+", " ", lat(s)).strip().lower()
    for p in ("naplatna stanica ",):
        if s.startswith(p):
            s = s[len(p):]
    return s


def name(s):
    s = s.strip()
    return DISPLAY.get(s, s)


def num(s):
    return float(s.replace(".", "").replace(",", "."))


def keys_of(n):
    """The booths' keys a list's station name is (Novi Sad: both)."""
    k = key(n)
    return MANY.get(k, [k])


def prices(path, rsd=False):
    """{entry station: {"ENTRY|EXIT": {"K3": ..., "K4": ...}}}: categories
    3 and 4, in RSD (rsd) or EUR."""
    origin, out = None, defaultdict(dict)
    for line in open(path, encoding="utf-8"):
        t = line.strip()
        if re.fullmatch(r"[A-ZČĆŠĐŽ ]{3,}", t) and t not in ("PUTARINA",):
            origin = t
            continue
        m = re.match(r"^\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s+(\d+,\d\d)\s*$", line)
        if m and origin:
            k3, k4 = (4, 5) if rsd else (10, 11)
            out[origin][origin + "|" + m.group(6).strip()] = {"K3": num(m.group(k3)), "K4": num(m.group(k4))}
    return out

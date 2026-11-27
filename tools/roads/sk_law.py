"""Sums Slovakia's tolled class I road sections by road: vyhláška
228/2020 Z. z., annex 1 part 2 (pdftotext -layout), section identifiers
"018-101a" (road I/18; "018-A102a" a section parallel to a motorway) and
their tolled length in km.

Usage: python3 sk_law.py annex.txt
"""
import re, sys
from collections import Counter

km, par = Counter(), Counter()
for l in open(sys.argv[1], encoding="utf-8"):
    m = re.match(r"^\s*(\d{3})-(A?)\S*\s.*?(\d+,\d{3})\s*$", l)
    if m:
        v = float(m.group(3).replace(",", "."))
        km[int(m.group(1))] += v
        if m.group(2):
            par[int(m.group(1))] += v
for r in sorted(km):
    print(f"SKLAW I/{r} {km[r]:.1f} parallel {par[r]:.1f}")
print(f"SKLAW total {sum(km.values()):.1f} parallel {sum(par.values()):.1f}")

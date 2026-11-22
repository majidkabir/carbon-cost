"""Tests expiring.py: python3 tools/orct/test_expiring.py"""
import datetime, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from expiring import expiring

IDX = {"datasets": [
    {"scheme": "at", "country": "AT", "name": "GO-Maut", "valid_from": "2026-01-01", "valid_to": "2026-12-31"},
    {"scheme": "dk", "country": "DK", "name": "Vejafgift", "valid_from": "2026-01-01", "valid_to": "2026-12-31"},
    {"scheme": "dk", "country": "DK", "name": "Vejafgift", "valid_from": "2027-01-01", "valid_to": "2027-12-31"},
    {"scheme": "fi", "country": "FI", "name": "No charge", "valid_from": "2026-11-20"},
    {"scheme": "ro-b", "country": "RO", "name": "Bridges", "valid_from": "2025-09-08", "valid_to": "2026-09-30"},
]}
CASES = [
    ("2026-11-21", 45, [("at", 40), ("ro-b", -52)]),
    ("2026-11-21", 30, [("ro-b", -52)]),
    ("2027-12-01", 45, [("at", -335), ("dk", 30), ("ro-b", -427)]),
]
bad = 0
for day, days, want in CASES:
    got = [(s, left) for s, _, _, _, left in expiring(IDX, datetime.date.fromisoformat(day), days)]
    if got != want:
        bad += 1
        print(f"{day} +{days}: {got}, want {want}")
print(f"{len(CASES) - bad}/{len(CASES)} ok")
sys.exit(1 if bad else 0)

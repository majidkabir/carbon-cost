"""Builds rates/data/hu-2026-07-01.json from 25/2013 NFM § 1 and annexes 1-2."""
import json, os
seg = json.load(open(os.path.join(os.path.dirname(__file__), 'hu-annex1.json')))
fbar = {}
for lv in ('motorway', 'main'):
    s = [r for r in seg if r['level'] == lv]
    fbar[lv] = sum(r['m'] * r['f'] for r in s) / sum(r['m'] for r in s)
EUR_HUF = 388.6
VAT = 1.27
# 25/2013 NFM § 1 (2)-(4a), gross HUF/km: motorway, main road
infra = {'J2': (65.89, 36.03), 'J3': (105.32, 59.59), 'J4': (163.26, 102.05), 'J5': (170.94, 106.16)}
# 25/2013 NFM annex 2, eurocent/km excl. VAT: air+noise suburban/interurban
# columns E0..EVI, then cleaner than EURO VI (low- and zero-emission)
an = {
 'J2': [(18.6,9.9),(12.6,6.4),(12.5,6.3),(9.6,4.8),(7.3,3.4),(4.4,1.8),(2.3,0.5),(2.0,0.3)],
 'J3': [(24.6,13.7),(15.8,8.4),(15.8,8.4),(12.5,6.6),(9.2,4.5),(5.6,2.7),(2.8,0.7),(2.3,0.3)],
 'J4': [(27.8,15.8),(20.4,11.3),(20.4,11.2),(16.3,8.9),(11.8,6.0),(6.6,3.4),(3.1,0.8),(2.5,0.3)],
 'J5': [(33.5,19.4),(25.0,14.1),(24.9,13.9),(20.1,11.1),(14.2,7.5),(7.6,3.8),(3.4,0.8),(2.8,0.3)],
}
# CO2 eurocent/km: E0, EI-III, EIV-VI, low-emission (ZEV 0)
co2 = {'J2': (4.5, 4.0, 4.0, 2.0), 'J3': (6.0, 5.2, 5.0, 2.5), 'J4': (7.9, 6.9, 6.7, 3.4), 'J5': (9.1, 8.1, 8.0, 4.0)}
axles = {'J2': dict(max_axles=2), 'J3': dict(min_axles=3, max_axles=3), 'J4': dict(min_axles=4, max_axles=4), 'J5': dict(min_axles=5)}
huf = lambda c: round(c / 100 * EUR_HUF, 2)
rows = []
def row(comp, cat, rate, road=None, **f):
    r = {'component': comp}
    if road: r['road'] = road
    r.update(axles[cat]); r.update(f); r['rate'] = round(rate, 4); rows.append(r)
for cat in ('J2', 'J3', 'J4', 'J5'):
    mw, mr = infra[cat]
    row('infrastructure', cat, mw / VAT, 'motorway')
    row('infrastructure', cat, mr / VAT, 'other')
    for area, i in (('suburban', 0), ('interurban', 1)):
        row('air_noise', cat, huf(an[cat][7][i]), area=area, co2_class=[4, 5])
        for e in range(7):
            row('air_noise', cat, huf(an[cat][e][i]), area=area, euro=[e])
    c = co2[cat]
    row('co2', cat, 0, co2_class=[5])
    row('co2', cat, huf(c[3]), co2_class=[4])
    row('co2', cat, huf(c[0]), euro=[0])
    row('co2', cat, huf(c[1]), euro=[1, 2, 3])
    row('co2', cat, huf(c[2]), euro=[4, 5, 6])
# check against HU-GO gross table 2025 (same EUR/HUF rate): J2 E0 suburban 91.80, interurban 48.86, CO2 22.21
assert round(huf(18.6) * VAT, 2) == 91.80 and round(huf(9.9) * VAT, 2) == 48.86 and round(huf(4.5) * VAT, 2) == 22.21
assert round(huf(3.4) * VAT, 2) == 16.78 and round(huf(2.8) * VAT, 2) == 13.82 and round(huf(0.8) * VAT, 2) == 3.95 and round(huf(4.0) * VAT, 2) == 19.74
t = {
 "country": "HU", "currency": "HUF", "valid_from": "2026-07-01", "valid_to": "2026-12-31",
 "name": "Hungarian distance-based toll (HU-GO)",
 "law": ("25/2013. (V. 31.) NFM rendelet (in force from 1 July 2026): § 1 (2)-(4a) as set by 46/2025. (XII. 23.) ÉKM gives the infrastructure charge in HUF/km including 27% VAT by category "
         "(J2-J5 by axles, 209/2013. (VI. 18.) Korm. rendelet § 2) and road level (expressway or main road); annex 2 gives the external-cost charge in eurocent/km excluding VAT "
         "(air and noise for suburban and interurban roads by EURO class, CO2 by EURO class, low- and zero-emission); annex 1 as set by 34/2025. (XI. 30.) ÉKM lists the 2,639 tolled elementary sections with their level and suburban share. "
         "Rates here exclude VAT: the infrastructure charge is divided by 1.27; the external-cost charge is converted at 388.60 HUF/EUR (ECB rate of 2 October 2023, kept because later 1 October rates moved it by 5% or less, 209/2013 § 3/A (2)-(3)), rounded to 0.01 HUF."),
 "sources": [
  {"title": "25/2013. (V. 31.) NFM rendelet (Nemzeti Jogszabálytár, in force from 1 July 2026)", "url": "https://njt.jog.gov.hu/jogszabaly/2013-25-20-2W"},
  {"title": "Magyar Közlöny 2025/143: 34/2025. (XI. 30.) ÉKM rendelet, annex 1 (tolled sections from 1 July 2026)", "url": "https://magyarkozlony.hu/dokumentumok/ffc3529aaa9c6075ef082089b3ec049444bc554a/letoltes"},
  {"title": "46/2025. (XII. 23.) ÉKM rendelet (its March 2026 step did not enter into force, 2/2026. (II. 26.) ÉKM 3. §)", "url": "https://njt.jog.gov.hu/jogszabaly/2025-46-20-8X"},
  {"title": "209/2013. (VI. 18.) Korm. rendelet § 3/A (EUR/HUF conversion)", "url": "https://njt.jog.gov.hu/jogszabaly/2013-209-20-22"},
  {"title": "HU-GO toll rate table (gross HUF/km, same EUR/HUF rate)", "url": "https://hu-go.hu/articles/article/e-tolls-the-table-of-toll-rates-applicable-from-january-is-now-available"}
 ],
 "vehicles": "Vehicles over 3.5 t maximum authorised mass (buses have their own rates)",
 "min_kg": 3501,
 "tolled_roads": ("Expressways (%.0f km) and main roads (%.0f km) listed in annex 1. Km on other roads are priced at the main-road rate. The air and noise charge has suburban and interurban rates; each route km takes its section's suburban share from annex 1 where OpenStreetMap places the section, else the network share (%.1f%% on expressways, %.1f%% on main roads). Low-emission means CO2 class 4."
                  % (sum(r['m'] for r in seg if r['level']=='motorway')/1000, sum(r['m'] for r in seg if r['level']=='main')/1000, fbar['motorway']*100, fbar['main']*100)),
 "motorway_share": 1,
 "suburban_share": {"motorway": round(fbar['motorway'], 4), "other": round(fbar['main'], 4)},
 "rows": rows,
}
json.dump(t, open(os.path.join(os.path.dirname(__file__), '..', '..', 'rates', 'data', 'hu-2026-07-01.json'), 'w'), ensure_ascii=False, indent=1)
print(len(rows), fbar)
for r in rows[:12]: print(r)

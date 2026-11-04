# carbon-cost

What carbon and road charges does a truck trip pay? carbon-cost works it out per country and per charge, and shows the carbon part separately:

- **Km-based road tolls:** Denmark (vejafgift), Germany (Lkw-Maut), Austria (GO-Maut), the Netherlands (vrachtwagenheffing), Belgium (kilometerheffing, by region), Switzerland and Liechtenstein (LSVA), Czechia (mýtné), Poland (e-TOLL), Bulgaria (BG TOLL), Slovenia (DarsGo), Slovakia (mýto), Hungary (HU-GO) and Romania (TollRo), split into their legal parts (infrastructure, air, noise and CO2) where the law gives them.
- **Entry-to-exit motorway tolls:** Croatia (Hrvatske autoceste and Bina-Istra), Serbia (Putevi Srbije) and France (APRR, AREA, ADELAC, ALIAE, VINCI Autoroutes' ASF, Escota and Cofiroute, Sanef and SAPN, A'liénor, the Millau viaduct, ATMB's A40, Atlandes, ALBEA, SFTRF's A43, Alicorne, ALiS and the Normandie and Tancarville bridges), priced from the station where the route enters a toll system to the one where it leaves.
- **Time-based road user charges:** Latvia (autoceļu lietošanas nodeva), Lithuania (kelių naudotojo mokestis), Estonia (teekasutustasu) and Sweden (vägavgift, Eurovignette), priced at one day's rate per trip. Lithuania counts the motor vehicle's own axles: give `motor_axles` (e.g. 2 for a tractor).
- **Bridge tolls:** Storebælt and Øresund, a fixed price per crossing by the truck's length (`length_m`, default 16.5 m).
- **Electronic toll discounts:** give `etc` when the truck pays by toll box or account agreement: Croatia's ENC (21.74%, plus 3% EURO V/EEV or 7% EURO VI on HAC; 30% on Bina-Istra), Storebælt's Grøn rabat (13%, EURO VI or zero-emission), and ØresundBUSINESS prices.
- **EU ETS on ferry crossings:** the cargo's share of the crossing's emissions × the allowance price.
- **ETS2 on road fuel** from 2028: the trip's fuel emissions × the ETS2 price.

The route, the km per country and the emissions come from [Sootcase](https://github.com/majidkabir/sootcase) (GLEC Framework and ISO 14083). The rates come from the laws, and each rate file names the law and the page it uses. There are no estimates or fitted factors: every number is a published rate, a price you give, or Sootcase's result.

## Example

```
$ carbon-cost calc -from DKCPH -to DEHAM -cargo-kg 20000 -mass-kg 40000 -axles 5 -euro 6 -co2-class 1 -eua 75
Trip on 2026-11-03: 300.0 km (19.0 km by ferry)
     Charge  Country            Part         Basis           Rate     Amount    EUR
  road_toll       DE  infrastructure      141.0 km   0.155 EUR/km  21.86 EUR  21.86
  road_toll       DE             air      141.0 km   0.023 EUR/km   3.24 EUR   3.24
  road_toll       DE           noise      141.0 km   0.012 EUR/km   1.69 EUR   1.69
  road_toll       DE             co2      141.0 km   0.158 EUR/km  22.28 EUR  22.28
  road_toll       DK  infrastructure      140.0 km    0.44 DKK/km  61.60 DKK   8.26
  road_toll       DK             co2      140.0 km     0.6 DKK/km  84.00 DKK  11.26
  road_toll       DK       air_noise      140.0 km    0.06 DKK/km   8.40 DKK   1.13
  ferry_ets                      co2  0.030 t CO2e  75 EUR/t CO2e   2.25 EUR   2.25
Total: EUR 71.97, of which carbon EUR 35.79
```

The numbers are this repo's worked test case (`cost/cost_test.go`).

### Compare trucks

`-compare 1,4,5` prices the same trip for trucks in other CO2 classes, and `-trips-per-year` turns the savings per trip into savings per year:

```
$ carbon-cost calc -from DKCPH -to DEHAM -cargo-kg 20000 -eua 75 -compare 1,4,5 -trips-per-year 200
...
  CO2 class  Tolls EUR  Total EUR  Carbon EUR  Saving/trip  Saving/year
          1      69.72      71.97       35.79         0.00
          4      48.82      51.07       19.02        20.90      4180.00
          5       2.44       4.69        2.25        67.28     13456.00
```

The route and the cargo's emissions stay the same. The exception is a class 5 (zero-emission) truck, which burns no road fuel and so pays no ETS2. In 2026 the class 5 truck pays only the DK class 5 rate, because Germany exempts it.

## Rates included

| Country | Charge | In force | Source |
|---|---|---|---|
| DK | Vejafgift, trucks of 12 t and over | 2026–2027 | Vejafgiftsloven, LBK nr. 647 af 28/05/2025, § 5; [Skatteministeriet's rate table](https://svmn.dk/tal-og-metode/satser/satser-og-beloebsgraenser-i-lovgivningen/vejafgiftsloven) |
| DK, SE | Storebælt and Øresund bridges, over 3.5 t | 2026 | [Storebælt business prices 2026](https://storebaelt.dk/priser-rabatter/erhverv/) (by length: up to 10 m, 10–20 m, over 20 m; excluding 25% VAT; Grøn rabat with `etc`) and [Øresundsbron's truck prices](https://www.oresundsbron.com/da/erhverv/lastbil) (up to 9 m or over; ØresundBUSINESS price with `etc`), per crossing, on top of the vejafgift Rebuilt from the fetched source by [tools/tables](tools/tables/README.md). |
| DE | Lkw-Maut, over 3.5 t | from 1 July 2024 | [BFStrMG Anlage 1](https://www.gesetze-im-internet.de/bfstrmg/anlage_1.html); emission-free trucks are exempt until 30 June 2031 |
| AT | GO-Maut, over 3.5 t | 2026 | [Mauttarifverordnung 2025, BGBl. II Nr. 298/2025](https://ris.bka.gv.at/Dokumente/BgblAuth/BGBLA_2025_II_298/BGBLA_2025_II_298.rtf) §§ 2–5, 8, 9. The special toll sections (A 9 Pyhrn/Gleinalm, A 10 Tauern, A 11 Karawanken, A 13 Brenner, S 16 Arlberg) charge their fixed infrastructure amount when the route passes both ends (from OpenStreetMap junctions), with the night rate on the A 13 when you give `night`; the A 12 Kufstein–Innsbruck adds 25% to the infrastructure rate |
| NL | Vrachtwagenheffing, over 3.5 t | from 1 July 2026 to the end of 2026 | [Staatscourant 2026, 3872](https://zoek.officielebekendmakingen.nl/stcrt-2026-3872.pdf) (statutory amounts, 1 July – 31 August) and [Staatscourant 2026, 18058](https://zoek.officielebekendmakingen.nl/stcrt-2026-18058.html) (22.3% lower, 1 September – 31 December) |
| BE | Kilometre charge by region: Flanders (`BE-VLG`), Wallonia (`BE-WAL`), Brussels (`BE-BRU`), over 3.5 t | 1 July – 31 December 2026 | [Viapass rate grid, ed. 01/07/2026](https://viapass.be/en/news/kilometer-charge-changes-planned-from-july-1-2026-1.html). Rates are totals: Flanders' CO2 element isn't published separately, so it isn't shown as a carbon part. Wallonia is excluding VAT. Brussels has motorway and urban-area rates: give `motorway_share.BE-BRU`, otherwise all km use the urban rate |
| CH, LI | LSVA (heavy vehicle fee), over 3.5 t, all roads | from 1 January 2025 | [SVAV (SR 641.811)](https://www.fedlex.admin.ch/eli/cc/2024/150/de) Art. 8 (AS 2024 522): 2.39 Rappen per tonne-km for Euro VI, 3.26 for Euro 0–V, on the truck's maximum mass up to 40 t; [Liechtenstein SVAV, LGBl. 2024 Nr. 452](https://www.gesetze.li/konso/pdf/2024452000) Art. 7, the same rates. Electric trucks are exempt (to the end of 2030) |
| CZ | Mýtné, over 3.5 t | 2026 | [Nařízení vlády č. 240/2014 Sb.](https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2014/240) Annexes 1–2 as set by [č. 327/2025 Sb.](https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2025/327): by motorway or class I road, mass, axles and EURO / CO2 class. One rate with no separate CO2 part |
| PL | e-TOLL, over 3.5 t | 1 February – 31 December 2026 | [Dz. U. 2026 poz. 33](https://eli.gov.pl/eli/DU/2026/33/ogl/pol/pdf) Annexes 3–4: by A/S or GP/G road, mass (with trailer) and EURO class. The concession motorways (parts of the A1, A2 and A4) charge separately and aren't included |
| BG | BG TOLL, over 3.5 t | 1 June – 31 December 2026 | [ПМС № 64/2026, ДВ бр. 49/2026](https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=243642), Tariff art. 25(1): EUR/km by CO2 class, category, EURO class and road class, split into infrastructure, air, noise and CO2. Km off motorways use the class I rate; EEV is priced as Euro V here (Bulgaria prices it as Euro VI) |
| SI | DarsGo, over 3.5 t, per toll section | from 1 April 2026 | [DARS price list](https://pisrs.si/pregledNpb?idPredpisa=AKT_1550&idPredpisaChng=ANJP333) (Uradni list RS 76/25, 102/25, 139/26, 1771/26): a fixed infrastructure price for each of 128 sections by axles and EURO / CO2 class; the [external-cost charge](https://pisrs.si/pregledPredpisa?id=SKLE14332) (air and noise, Uradni list RS 130/26) and the [Divača–Koper rail surcharge](https://pisrs.si/pregledNpb?idPredpisa=SKLE11574&idPredpisaChng=SKLE14128) per km of each section's official length and suburban/interurban type ([Uredba o cestninskih cestah in cestnini](https://pisrs.si/pregledPredpisa?id=URED9382)). The Karavanke tunnel's Slovenian toll is a fixed amount per passage ([Uredba, Uradni list RS 109/24 and 76/25](https://pisrs.si/pregledPredpisa?id=URED9295)). Excluding 22% VAT. A section counts when the route passes both of its junctions (OpenStreetMap; a few placed by official lengths) |
| SK | Mýto, over 3.5 t | from 1 July 2025 | [Nariadenie vlády č. 418/2024 Z. z.](https://static.slov-lex.sk/static/SK/ZZ/2024/418/20250701.html) Annexes 5 and 6 (part 2): EUR/km excluding VAT by motorway or class I road, category, EURO and CO2 class; Annex 3 gives the CO2 and air-pollution parts. Km off motorways use the class I rate |
| HU | HU-GO, over 3.5 t | 1 July – 31 December 2026 | [25/2013. (V. 31.) NFM rendelet](https://njt.jog.gov.hu/jogszabaly/2013-25-20-2W) § 1 (infrastructure, HUF/km by J2–J5 and expressway or main road, as set by 46/2025 ÉKM) and annex 2 (air, noise and CO2 in eurocent/km, converted at 388.60 HUF/EUR under [209/2013 Korm. rendelet](https://njt.jog.gov.hu/jogszabaly/2013-209-20-22) § 3/A). Air and noise have suburban and interurban rates; each km takes its section's suburban share from [annex 1 (34/2025 ÉKM)](https://magyarkozlony.hu/dokumentumok/ffc3529aaa9c6075ef082089b3ec049444bc554a/letoltes), else the network average. Excluding 27% VAT Rebuilt from the fetched source by [tools/tables](tools/tables/README.md). |
| RO | TollRo, over 3.5 t | 8 October – 31 December 2026 | [Ordinul MTI nr. 1.925/2025](https://legislatie.just.ro/Public/DetaliiDocument/302972) as replaced by OMTI 959/2026, rates as published by CNAIR on [eToll](https://portal.etoll.ro/web/guest/tollro): lei/km by mass (over 3.5–7.5 t, 7.5–12 t, 12 t and over), motorway/expressway or national road, and EURO class; electric trucks pay 25% of the EURO VI rate. Excluding 21% VAT. National roads inside municipalities aren't tolled: the tool leaves out national-road km inside a municipality's built-up area (OpenStreetMap) Rebuilt from the fetched source by [tools/tables](tools/tables/README.md). |
| LV | Road user charge, from 3001 kg | from 1 March 2026 | [Autoceļu lietošanas nodevas likums](https://likumi.lv/ta/id/185656-autocelu-lietosanas-nodevas-likums) Annex 2: euro per day (also 7 days, 30 days, a year) by mass (3001–3500 kg, 3501–12000 kg, over 12 t), axles over 12 t (2–3, 4+) and EURO class; zero-emission vehicles pay nothing. A trip on the Annex 1 roads pays one day's charge. A fee, no VAT. Rebuilt from the fetched source by [tools/tables](tools/tables/README.md). |
| LT | Road user charge, over 3.5 t (N2, N3) | 25 August – 31 December 2026 | [Nutarimas Nr. 447](https://www.e-tar.lt/portal/lt/legalAct/TAR.479B13E87700/asr) annex point 1: euro per day (also week, month, year) by category, the motor vehicle's own axles (up to 3, 4 or more; point 2.2) and EURO class, on the roads in point 6. e-TAR refuses scripted requests: the text was read in a browser into [tools/tables/browser/lt-447.txt](tools/tables/browser/lt-447.txt) and is built by [tools/tables](tools/tables/README.md). |
| EE | Road user charge, over 3.5 t | from 1 January 2026 | [Liiklusseadus](https://www.riigiteataja.ee/akt/113032019015?leiaKehtiv) § 190^3: euro per 24 hours (also 7, 30, 90, 365 days) by the truck and trailer's summed mass (up to or over 12 t), total axles and EURO class; zero-emission trucks have lower rates. All public roads. Rebuilt from the fetched source by [tools/tables](tools/tables/README.md). |
| SE | Vägavgift (Eurovignette), 12 t and over | 2026 | [Lag (1997:1137)](https://data.riksdagen.se/dokument/sfs-1997-1137.text) 11 and 23 §§, kronor for 2026 from [SFS 2025:918](https://svenskforfattningssamling.se/sites/default/files/sfs/2025-10/SFS2025-918.pdf): per day (also week, month, year) by axles (up to 3, 4 or more), CO2 class and, in class 1, EURO class. A foreign truck pays per day on motorways and the annex 1 roads; a Swedish one pays yearly. Rebuilt from the fetched source by [tools/tables](tools/tables/README.md). |
| HR | Motorway toll, groups III and IV | 2026 | [Hrvatske autoceste's price lists](https://www.hac.hr/en/toll/toll-rates/a1) (A1/A6/A10, A2, A3/A5, A4, A11, and the open stations Bregana and Rupa) and [Bina-Istra's](https://bina-istra.com/karta/hamburger.html) (Istrian Y, A8/A9), vehicle groups by [Pravilnik o cestarini](https://narodne-novine.nn.hr/clanci/sluzbeni/2013_10_130_2833.html): from entry to exit station, matched to the route by OpenStreetMap toll booths and junctions. Full price excluding 25% VAT; with `etc` the [ENC discounts](https://www.hac.hr/en/toll/etc) |
| RS | Motorway toll (putarina), categories 3 and 4 | 1 July – 31 December 2026 | [JP Putevi Srbije's price list](https://www.putevi-srbije.rs/images/pdf/cene_putarina_lat.pdf) (EUR column): from Beograd, Dimitrovgrad, Preševo, Šid, Stara Pazova and Obrenovac to each station on their sections; other entry–exit pairs aren't in the list and get a note. The Belgrade bypass (category 4, RSD) isn't included |
| FR | Motorway tolls, classes 3 and 4 (APRR, AREA, ADELAC, ALIAE; from 1 June 2026 also ASF, Escota, Cofiroute, Sanef, SAPN, A'liénor, Millau, ATMB's A40, Atlandes, ALBEA, SFTRF's A43, Alicorne, ALiS and the Normandie and Tancarville bridges; Atlandes and ALBEA by EURO class) | 1 February 2026 – 31 January 2027 | Each operator's published tariffs ([APRR and AREA](https://voyage.aprr.fr/tarifs-de-peage), [ADELAC](https://www.a41-adelac.com), [ALIAE](https://www.aliae.com), [VINCI Autoroutes](https://www.vinci-autoroutes.com/fr/tarifs-peage-reseaux-vinci-autoroutes), [Sanef and SAPN](https://www.autoroutes.sanef.com/fr/grilles-tarifs-de-peage)) under the arrêtés of 28 January 2026, excluding 20% VAT. Stations are placed with the ministry's [toll station dataset](https://www.data.gouv.fr/datasets/gares-de-peage-du-reseau-routier-national-concede), else OpenStreetMap. Along the route, a trip pays the published entry–exit pairs, one after another, that together cover the most of it. How the data is gathered, and what isn't covered yet (the A355): [tools/fr/README.md](tools/fr/README.md) |
| FR, IT | Fréjus road tunnel, over 3.5 t | 2026 | [SFTRF price list](https://www.sftrf.fr/tarifs-tunnel/), French platform, one way: class 3 (two axles) and 4 (three or more), trucks EURO 5–6, excluding 20% VAT; charged when the route passes the French plaza, whichever the direction. Rebuilt from the fetched source by [tools/tables](tools/tables/README.md). |
| FR, IT | Mont Blanc tunnel, over 3.5 t | 2026 | [ATMB prices for heavy vehicles](https://www.atmb.com/telepeage-tarifs/les-tarifs-au-tunnel-du-mont-blanc-pour-les-poids-lourds/), one way: class 3 (two axles) and 4 (three or more), excluding 20% VAT (Italy to France is the same before Italy's VAT); goods vehicles of EURO 0–4 aren't admitted. Charged when the route passes the French plaza. Rebuilt from the fetched source by [tools/tables](tools/tables/README.md). |

Run `carbon-cost rates` for the full list. Countries on a route that have no table are listed under `no_rates`, and their charges are not included.

## Things to know

- **Tolled roads:** Where the tool has no road classes for a country (see Road types), all its km are counted as tolled by default. In Denmark the 2025–2027 tolled network covers about 100% of foreign trucks' driving and about 70% of Danish trucks' ([Skatteministeriet's answer to Folketinget](https://eu.dk/samling/20222/lovforslag/l74/spm/35/svar/1958301/2708151.pdf)), and from 2028 every public road is tolled. Germany tolls motorways and federal roads. If part of a trip is on untolled roads, give `tolled_share`.
- **Regional tolls:** where a country's toll differs by region (Belgium), the tool prices the km per region from Sootcase's `region_km` (ISO 3166-2, e.g. `BE-VLG`). `country_km` still covers the whole country. `tolled_share` and `env_zone_km` take a region code or a country code. 
- **Environmental zones:** the Danish surcharge applies to the km you give in `env_zone_km`.
- **Ferry ETS:** this is the ETS cost of the cargo's share of the crossing. On a crossing the tool knows (Rødby–Puttgarden, Gedser–Rostock), and when you give the truck's `tare_kg`, the emissions come from that crossing's own ships in the EU MRV report: their freight CO2e per tonne-nautical mile × (truck + cargo) × the crossing's distance. MRV counts the vehicle in the freight mass, which is why the tare is needed. Otherwise the emissions come from Sootcase's ferry part, which uses the GLEC ro-pax default. The share of emissions under the ETS is 40% for 2024, 70% for 2025 and 100% from 2026, all for crossings between EU/EEA ports. A ferry line's own surcharge is based on its ships' real emissions and its own pricing.
- **Prices:** EUA and ETS2 prices are yours to give, since they move every day. DKK converts at the ERM II central rate of 7.46038 unless you give `dkk_per_eur`. CHF, CZK, PLN, HUF and RON convert at the latest [ECB euro reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) unless you give `fx` (units per euro, e.g. `{"CHF": 0.93}`).
- **Road types:** Czechia, Poland, Bulgaria, Slovakia, Hungary and Romania charge less off motorways and don't toll local roads. The tool reads the road class of each km of the route from OpenStreetMap (embedded in `roads/data`, built by `tools/roads`): the toll law's motorway class (CZ D, PL A and S, BG A, SK D and R, HU M, RO A and DEx), other national roads (1–2 digit refs; RO DN), and local roads, which aren't charged. Hungary's air and noise charge also takes each km's suburban share from its toll section (OpenStreetMap relations tagged `ref:HU:edid`). `motorway_share` and `tolled_share` override this.

## Use

```
go install github.com/majidkabir/carbon-cost/cmd/carbon-cost@latest
carbon-cost calc -h
carbon-cost serve -addr :8090   # web page at /, POST /v1/carbon-cost, GET /v1/rates, GET /v1/places?q=
```

Or with Docker (images are published for each release tag):

```
docker run -p 8090:8090 -e SOOTCASE_URL=https://sootcase.org -e SOOTCASE_API_KEY=... ghcr.io/majidkabir/carbon-cost
```

Release binaries for Linux, macOS and Windows are on the [releases page](https://github.com/majidkabir/carbon-cost/releases). To release, change the version in `RELEASE`; merging that to main publishes it.

`calc` and `serve` call `https://sootcase.org` by default. Set `SOOTCASE_URL` to use another server, and set `SOOTCASE_API_KEY` to send an API key. The server must run Sootcase v0.9.0 or later, which adds `country_km`.

API request:

```json
{
  "from": {"code": "DKCPH"},
  "to": {"code": "DEHAM"},
  "date": "2026-11-03",
  "cargo_kg": 20000,
  "truck": {"max_mass_kg": 40000, "axles": 5, "euro": 6, "co2_class": 1, "tare_kg": 15000},
  "eua_eur_per_t": 75
}
```

Optional fields: `vehicle_type` (Sootcase), `tolled_share`, `motorway_share`, `env_zone_km`, `ferry_ets_share`, `ets2_eur_per_t`, `dkk_per_eur`, `fx`, `night`, `compare_co2_classes` (e.g. `[1, 4, 5]`, giving `compare[]` in the response) and `trips_per_year`.

## License

MIT (see `LICENSE`). The toll rates in `rates/data` are copied from laws, which are not protected by copyright in Denmark (Ophavsretsloven § 9) or Germany (UrhG § 5). Route, distance and emission results come from the Sootcase server at run time and are not part of this repo; they follow that server's terms.

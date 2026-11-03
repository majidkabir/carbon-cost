# carbon-cost

What carbon and road charges does a truck trip pay? carbon-cost works it out per country and per charge, and shows the carbon part separately:

- **Km-based road tolls:** Denmark (vejafgift), Germany (Lkw-Maut), Austria (GO-Maut) and the Netherlands (vrachtwagenheffing), split into their legal parts: infrastructure, air, noise and CO2.
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
| DE | Lkw-Maut, over 3.5 t | from 1 July 2024 | [BFStrMG Anlage 1](https://www.gesetze-im-internet.de/bfstrmg/anlage_1.html); emission-free trucks are exempt until 30 June 2031 |
| AT | GO-Maut, over 3.5 t | 2026 | [Mauttarifverordnung 2025, BGBl. II Nr. 298/2025](https://ris.bka.gv.at/Dokumente/BgblAuth/BGBLA_2025_II_298/BGBLA_2025_II_298.rtf) §§ 2, 8, 9; not included: the special toll sections (Brenner, Tauern, Arlberg, Karawanken, Pyhrn/Gleinalm) and the A 12 surcharge |
| NL | Vrachtwagenheffing, over 3.5 t | from 1 July 2026 to the end of 2026 | [Staatscourant 2026, 3872](https://zoek.officielebekendmakingen.nl/stcrt-2026-3872.pdf) (statutory amounts, 1 July – 31 August) and [Staatscourant 2026, 18058](https://zoek.officielebekendmakingen.nl/stcrt-2026-18058.html) (22.3% lower, 1 September – 31 December) |

Run `carbon-cost rates` for the full list. Countries on a route that have no table are listed under `no_rates`, and their charges are not included.

## Things to know

- **Tolled roads:** Sootcase gives km per country but not road classes yet, so all km in a country are counted as tolled by default. In Denmark the 2025–2027 tolled network covers about 100% of foreign trucks' driving and about 70% of Danish trucks' ([Skatteministeriet's answer to Folketinget](https://eu.dk/samling/20222/lovforslag/l74/spm/35/svar/1958301/2708151.pdf)), and from 2028 every public road is tolled. Germany tolls motorways and federal roads. If part of a trip is on untolled roads, give `tolled_share`.
- **Regional tolls:** where a country's toll differs by region (Belgium), the tool prices the km per region from Sootcase's `region_km` (ISO 3166-2, e.g. `BE-VLG`). `country_km` still covers the whole country. `tolled_share` and `env_zone_km` take a region code or a country code. Belgium's regional rates are not in yet.
- **Environmental zones:** the Danish surcharge applies to the km you give in `env_zone_km`.
- **Ferry ETS:** this is the ETS cost of the cargo's share of the crossing. Emissions come from Sootcase's ferry part, which uses the GLEC ro-pax default. The share of emissions under the ETS is 40% for 2024, 70% for 2025 and 100% from 2026, all for crossings between EU/EEA ports. A ferry line's own surcharge is based on its ships' real emissions and its own pricing.
- **Prices:** EUA and ETS2 prices are yours to give, since they move every day. DKK converts at the ERM II central rate of 7.46038 unless you give `dkk_per_eur`.

## Use

```
go install github.com/majidkabir/carbon-cost/cmd/carbon-cost@latest
carbon-cost calc -h
carbon-cost serve -addr :8090   # POST /v1/carbon-cost, GET /v1/rates
```

Or with Docker (images are published for each release tag):

```
docker run -p 8090:8090 -e SOOTCASE_URL=https://sootcase.org -e SOOTCASE_API_KEY=... ghcr.io/majidkabir/carbon-cost
```

Release binaries for Linux, macOS and Windows are on the [releases page](https://github.com/majidkabir/carbon-cost/releases).

`calc` and `serve` call `https://sootcase.org` by default. Set `SOOTCASE_URL` to use another server, and set `SOOTCASE_API_KEY` to send an API key. The server must run Sootcase v0.9.0 or later, which adds `country_km`.

API request:

```json
{
  "from": {"code": "DKCPH"},
  "to": {"code": "DEHAM"},
  "date": "2026-11-03",
  "cargo_kg": 20000,
  "truck": {"max_mass_kg": 40000, "axles": 5, "euro": 6, "co2_class": 1},
  "eua_eur_per_t": 75
}
```

Optional fields: `vehicle_type` (Sootcase), `tolled_share`, `env_zone_km`, `ferry_ets_share`, `ets2_eur_per_t`, `dkk_per_eur`, `compare_co2_classes` (e.g. `[1, 4, 5]`, giving `compare[]` in the response) and `trips_per_year`.

## License

MIT (see `LICENSE`). The toll rates in `rates/data` are copied from laws, which are not protected by copyright in Denmark (Ophavsretsloven § 9) or Germany (UrhG § 5). Route, distance and emission results come from the Sootcase server at run time and are not part of this repo; they follow that server's terms.

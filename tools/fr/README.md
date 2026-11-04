# French motorway tolls: how the data is gathered

Everything here runs in the **France data** workflow (`.github/workflows/fr-data.yml`, started by pushing to the `fr-data` branch). Its output goes to the `fr-out` branch, and `fr.json` from there is copied to `rates/data/fr-<date>.json`.

1. **Sources** (`sources.json`). France has no national price list: each motorway concessionaire publishes its own tariffs. The operators and their tariff pages come from the list the transport ministry sends the European Commission under article 11 of Directive 1999/62/EC (`source_index`). The legal basis is in `legal`.
2. **Fetch** (`fetch.py`). Downloads each page and the tariff documents linked from it, plus the ministry's toll station dataset from data.gouv.fr. PDFs are converted to text with `pdftotext -layout`. `manifest.json` records every file's URL, sha256, size and fetch time, and any errors.
3. **Parse** (`documents.json`, `parse.py`). `documents.json` lists the documents that are parsed and their format. `parse.py` writes `pairs.csv`, one row per entry–exit pair, with the class 3 and 4 prices including VAT, the document's URL and sha256, and the date it says it applies from. It prints the pairs it read next to the price rows in the text, so a format change shows up.
4. **Stations** (`stations.py`, `aliases.json`). Puts each tariff station on the map from the ministry's toll station dataset, matching by normalised name. `aliases.json` holds the names the dataset spells differently (decided by hand, one line each). If a name is in neither, the script falls back to OpenStreetMap's toll booths and motorway junctions. `stations-report.txt` lists the stations it couldn't place.
5. **Build** (`build.py`). Writes the rate table. All pairs go into one chained toll system: along the route, a truck pays for the longest published pair from the first station it passes, then starts again from the next station. Prices exclude 20% VAT.

Covered so far: APRR, AREA, ADELAC (A41 Nord) and ALIAE (A79).

Not covered yet:
- **VINCI Autoroutes** (ASF, Escota, Cofiroute, Arcour, Arcos). Their class grids are rotated triangular tables, which need a PDF layout parser.
- **Sanef and SAPN**. Their site blocks automated downloads.
- **ATMB, SFTRF, ALiS, A'liénor, ALBEA, Alicorne, Atlandes, CEVM (Millau) and CCI Seine-Estuaire**. Their tariffs are in their own formats, or the pages refuse the fetch.

# Romanian, Danish bridge, Hungarian, Baltic, Swedish, Fréjus and Mont Blanc tunnel rate tables: how the data is gathered

Everything here runs in the **Tables data** workflow (`.github/workflows/tables-data.yml`, started by pushing to the `tables-data` branch). It fetches the sources, rebuilds the tables, says whether each one is the same as the committed file, and pushes the fetched pages, `manifest.json` (URL, sha256, size, fetch time and HTTP status of every file) and the rebuilt tables to the `tables-out` branch.

1. **Sources** (`sources.json`), fetched by `fetch.py`:
   - **Romania**: CNAIR's eToll TollRo page. Its tariff widget reads the pricing offer in force from the page's portlet (`rest_path=/pricing-offers/active-pricing-offer`, `productClass=PER_KM`); `fetch.py` finds the portlet's resource URL in the page and saves that JSON.
   - **Denmark**: A/S Storebælt's business price page and Øresundsbron's truck price page.
   - **Fréjus tunnel**: SFTRF's price list for the French platform (PDF, converted with `pdftotext -layout`).
   - **Mont Blanc tunnel**: ATMB's price page for heavy vehicles.
   - **Latvia**: likumi.lv's consolidated Autoceļu lietošanas nodevas likums (Annex 2 is in the page).
   - **Estonia**: the Liiklusseadus in force from Riigi Teataja's public API, which its pages are built from: `/public-api/api/v1/akt/113032019015?leiaKehtiv=true` names the version in force (`kehtivId`), whose text is `/public-api/api/v1/akt/<kehtivId>/blob-html`.
   - **Lithuania**: e-TAR and e-seimas refuse scripted requests (Cloudflare, status 403; `sources.json` keeps the URLs so the manifest shows it). The consolidated resolution No 447 was opened in Chrome instead: its page's text is in a frame (`/rs/actualedition/TAR.479B13E87700/<edition code>/`), whose text was read and saved, from the annex heading to point 6, as `browser/lt-447.txt` with the URL, date and edition in its header.
   - **Sweden**: Riksdagen's open-data text of Lag (1997:1137) and the PDF of SFS 2025:918 (the year's amounts in kronor, converted with `pdftotext -layout`).
   - **Hungary**: the Nemzeti Jogszabálytár's consolidated text of 25/2013. (V. 31.) NFM rendelet. The site sends long parts (the annexes) separately; `fetch.py` asks for them as its page script does (`/ajax/njtGetBlock.json`).
2. **Build**:
   - `ro.py` → `rates/data/ro-<date>.json`: lei/km including 21% VAT by mass category, road category and emission class, from the offer JSON; the date and order number from the offer's name.
   - `dk_bridges.py` → `rates/data/dk-bridges-<year>-01-01.json`: Storebælt's express prices for trucks by length (including 25% VAT) and its green discount; Øresund's normal and ØresundBUSINESS prices (excluding VAT).
   - `frejus.py` → `rates/data/frejus-<date>.json`: one-way class 3 and 4 prices for trucks (EURO 5-6), a crossing priced at the French plaza.
   - `mont_blanc.py` → `rates/data/mont-blanc-<date>.json`: one-way class 3 and 4 prices (France to Italy; Italy to France is the same before VAT), a crossing priced at the French plaza.
   - `lv.py` → `rates/data/lv-<date>.json`: Annex 2's 1-day rates by mass, axles and EURO class (zero-emission as CO2 class 5), a `per_day` table; the date from the annex heading.
   - `ee.py` → `rates/data/ee-<date>.json`: § 190^3's 24-hour rates, each paragraph read for its mass, axles and EURO class (zero-emission as CO2 class 5); valid from the latest entry-into-force date in § 190^3.
   - `lt.py` → `rates/data/lt-<date>.json` from `browser/lt-447.txt`: point 1's daily rates for N2 and N3 by the motor vehicle's axles and EURO class, a `per_day` and `motor_axles` table; dates from the edition line; point 6's roads.
   - `se.py` → `rates/data/se-<year>-01-01.json`: the förordning's daily amounts (the last number of each row) by axles, CO2 class and EURO class.
   - `hu.py` → `rates/data/hu-<date>.json` and `tools/roads/hu-annex1.json`: § 1 (2)-(4a) (infrastructure charge), annex 1 (tolled sections, with each one's suburban share) and annex 2 (external-cost charge).
3. **Transcribed images**: Atlandes (A63) and ALBEA (A150) publish their prices only as images. Those are transcribed by hand into `tools/fr/transcribed/*.json`, each with the image's URL and sha256; the workflow fetches the images (`sources.json`) and `check_transcribed.py` says whether each is still the one transcribed.
4. **Compare**: the workflow prints, for each rebuilt file, whether it is the same as the committed one, or the difference. A new file means a new price list: copy it into `rates/data` (with an end date on the previous one if they overlap).

The Danish plazas' coordinates are fixed in `dk_bridges.py` (OpenStreetMap toll booths). The Hungarian EUR/HUF rate (388.60, 209/2013. Korm. rendelet § 3/A) and the HU-GO checks are in `hu.py`.

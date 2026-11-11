"""Builds the Hungarian HU-GO tables from 1 January 2024 to 30 June 2026
from the Nemzeti Jogszabálytár's time states of 25/2013. (V. 31.) NFM
rendelet (https://njt.jog.gov.hu/jogszabaly/2013-25-20-2W.<state>, as
fetch.py saved them with their parts: hu-25-2013-v<state>.html and
hu-25-2013-v<state>-block-*.html), each read by tools/tables/hu.py.

Usage: python3 build_hu.py fetched/ out-dir

Each table runs from its time state's first day to its last (the page's
"Hatályos: ... – ..."). The tolled sections (annex 1) placed on the roads
are today's; each state's own annex 1 gives the suburban shares."""
import glob, json, os, shutil, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tables"))
import hu  # noqa: E402

STATES = [(20, "2024-01-01", "2024-03-31"), (21, "2024-04-01", "2024-08-31"), (22, "2024-09-01", "2025-06-07"),
          (23, "2025-06-08", "2025-12-31"), (24, "2026-01-01", "2026-06-30")]


def main(fetched, out):
    for v, frm, to in STATES:
        page = os.path.join(fetched, f"hu-25-2013-v{v}.html")
        if not os.path.exists(page):
            print("missing", page)
            continue
        tmp = tempfile.mkdtemp()
        shutil.copy(page, os.path.join(tmp, "hu-25-2013.html"))
        for f in glob.glob(os.path.join(fetched, f"hu-25-2013-v{v}-block-*.html")):
            shutil.copy(f, os.path.join(tmp, os.path.basename(f).replace(f"-v{v}", "")))
        url = f"https://njt.jog.gov.hu/jogszabaly/2013-25-20-2W.{v}"
        hu.main(tmp, tmp, law=f"25/2013. (V. 31.) NFM rendelet as in force from {frm} to {to} (Nemzeti Jogszabálytár time state {v}): § 1 gives the infrastructure charge in HUF/km including 27% VAT by category (J2-J5 by axles, 209/2013. (VI. 18.) Korm. rendelet § 2) and road level (expressway or main road); annex 2 gives the external-cost charge in eurocent/km excluding VAT (air and noise for suburban and interurban roads by EURO class, CO2 by EURO class, low- and zero-emission); annex 1 lists the tolled elementary sections with their level and suburban share.",
                sources=[{"title": f"25/2013. (V. 31.) NFM rendelet, in force {frm} to {to} (Nemzeti Jogszabálytár)", "url": url}])
        tb = json.load(open(os.path.join(tmp, f"hu-{frm}.json")))
        tb["valid_to"] = to
        os.makedirs(out, exist_ok=True)
        json.dump(tb, open(os.path.join(out, f"hu-{frm}.json"), "w"), ensure_ascii=False, indent=1)
        print(os.path.join(out, f"hu-{frm}.json"), len(tb["rows"]), "rows")


if __name__ == "__main__":
    main(*sys.argv[1:])

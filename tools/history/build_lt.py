"""Builds Lithuania's road user charge tables from 1 January 2024 to
24 August 2026 from the consolidated editions of Government resolution
No 447 read in a browser (tools/history/browser/lt-447-<date>.txt: the
N2 and N3 blocks of point 1 and point 6 of the annex), each read by
tools/tables/lt.py.

Usage: python3 build_lt.py fetched/ out-dir"""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tables"))
import lt  # noqa: E402


def main(fetched, out):
    for f in sorted(glob.glob(os.path.join(HERE, "browser", "lt-447-*.txt"))):
        frame = re.search(r"Edition frame: (\S+)", open(f, encoding="utf-8").read()).group(1)
        lt.main(f, out)
        frm = re.search(r"lt-447-(\d{4}-\d\d-\d\d)", f).group(1)
        p = os.path.join(out, f"lt-{frm}.json")
        tb = json.load(open(p))
        tb["law"] = tb["law"].replace("(as amended by No 540 of 2023 and No 237 of 2026)", f"(consolidated edition in force {tb['valid_from']} to {tb['valid_to']}, read in a browser into tools/history/browser/{os.path.basename(f)})")
        tb["sources"][0] = {"title": f"Nutarimas Nr. 447, consolidated edition {tb['valid_from']} to {tb['valid_to']} (e-TAR)", "url": frame}
        json.dump(tb, open(p, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])

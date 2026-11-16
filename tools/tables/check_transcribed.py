"""Says whether the images that tools/fr/transcribed/*.json were
transcribed from are still the ones published (their sha256 against
fetch.py's manifest), or, where the publisher doesn't serve the workflow,
the Internet Archive's copy named as the source's "archived". A changed
image means new prices to transcribe.

Usage: python3 check_transcribed.py fetched/ tools/fr/transcribed/
"""
import glob, json, os, sys


def main(fetched, folder):
    files = {f["url"]: f for f in json.load(open(os.path.join(fetched, "manifest.json")))["files"]}
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        src = json.load(open(path, encoding="utf-8"))["source"]
        # The published copy, else the Internet Archive's copy of it.
        f = files.get(src["url"]) or files.get(src.get("archived"))
        if f is not None and f.get("status", 200) != 200:
            f = None
        name = os.path.basename(path)
        if f is None:
            print(f"::warning title={name}::image not fetched ({src['url']})")
        elif f["sha256"] == src["sha256"]:
            print(f"{name}: image unchanged")
        else:
            print(f"::warning title={name}::image changed (sha256 {f['sha256']}): transcribe it again")


if __name__ == "__main__":
    main(*sys.argv[1:])

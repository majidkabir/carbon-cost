#!/usr/bin/env python3
"""Checks that each table in tools/history/templates converts (convert.py)
to the dataset committed in tariffs/data, byte for byte: the history
builders take the current tables' structure from there.

Usage: check_templates.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    src = os.path.join(ROOT, "tools", "history", "templates")
    bad = 0
    with tempfile.TemporaryDirectory() as out:
        subprocess.run([sys.executable, os.path.join(HERE, "convert.py"), src, out], check=True, stdout=subprocess.DEVNULL)
        for name in sorted(os.listdir(src)):
            cc = name[:2]
            rel = os.path.join(cc, name[:-5] + ".orct.json")
            with open(os.path.join(out, rel), "rb") as a:
                got = a.read()
            try:
                with open(os.path.join(ROOT, "tariffs", "data", rel), "rb") as b:
                    want = b.read()
            except FileNotFoundError:
                want = None
            if got != want:
                bad += 1
                print(f"{name}: converts to other than tariffs/data/{rel}")
            else:
                print(f"{name}: same as tariffs/data/{rel}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

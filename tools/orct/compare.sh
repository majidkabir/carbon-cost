#!/bin/sh
# Compares the datasets a workflow converted (<dir>/<cc>/<name>.orct.json)
# with the committed ones (tariffs/data): "same", or a warning with the
# start of the difference. Usage: compare.sh <dir> (from the repo root).
root=$(pwd)
cd "$1" || exit 1
for f in */*.orct.json; do
  [ -e "$f" ] || continue
  c="$root/tariffs/data/$f"
  if [ ! -f "$c" ]; then echo "::warning title=$f::new dataset (none in tariffs/data)"
  elif cmp -s "$f" "$c"; then echo "$f: same as committed"
  else echo "::warning title=$f::differs from tariffs/data/$f"; diff "$c" "$f" | head -40; fi
done

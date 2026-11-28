"""Tests that the builders still give valid tables when the year turns:
nothing in them may hold a year or a yearly rate written in.

- HU (tables/hu.py): the EUR/HUF rate of the external-cost charge follows
  209/2013 § 3/A on any ECB history: kept while October's first working
  day's rate is within 5%, replaced from the next 1 January when not.
- FR (fr/build.py): the tariff periods run from the 1 February of the
  newest documents' tariff year to the next 31 January, whatever year.

Usage: python3 tools/test_next_year.py
"""
import contextlib, csv, io, json, os, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "tables"))
sys.path.insert(0, os.path.join(here, "fr"))
import hu  # noqa: E402
import build as fr  # noqa: E402
import gr  # noqa: E402


def test_hu():
    d = tempfile.mkdtemp()
    hu.ECB = os.path.join(d, "ecb.csv")
    rows = [("2024-10-01", 397.83), ("2025-10-01", 388.70), ("2026-10-01", 367.18), ("2027-10-01", 370.0), ("2028-10-02", 400.0)]
    with open(hu.ECB, "w") as f:
        f.write("date,CHF,HUF\n" + "".join(f"{day},0.94,{r}\n" for day, r in rows))
    want = {"2026-12-31": 388.60, "2027-01-01": 367.18, "2028-06-01": 367.18, "2029-01-01": 400.0}
    got = {day: hu.eur_huf(day)[0] for day in want}
    os.remove(hu.ECB)
    os.rmdir(d)
    assert got == want, got


def test_fr():
    d = tempfile.mkdtemp()
    pairs = os.path.join(d, "pairs.csv")
    for year in (2026, 2027, 2031):
        with open(pairs, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["url", "valid_from"])
            w.writerows([["a", f"{year - 1}-02-01"], ["b", f"{year}-02-01"], ["c", f"{year}-05-01"], ["d", ""]])
        tables = []
        real, fr.main = fr.main, lambda *a: tables.append((os.path.basename(a[3]), a[5]))
        try:
            fr.periods(pairs, None, None, d)
        finally:
            fr.main = real
        want = [(f"fr-{year}-02-01.json", f"{year}-04-30"), (f"fr-{year}-05-01.json", f"{year + 1}-01-31")]
        assert tables == want, (year, tables)
    os.remove(pairs)
    os.rmdir(d)


def test_fr_stale():
    """No table for a tariff year an operator's document doesn't reach:
    its prices would be the last year's."""
    d = tempfile.mkdtemp()
    pairs, stations = os.path.join(d, "pairs.csv"), os.path.join(d, "stations.json")
    json.dump({n: [{"gare": n, "lat": 48 + i, "lon": 2.0}] for i, n in enumerate("ABCD")}, open(stations, "w"))
    for y_from, y_read, wrote in (("2026-02-01", "", False), ("2026-02-01", "2027-03-01", True), ("2027-02-01", "", True), ("", "2026-11-04", False)):
        with open(pairs, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["operator", "document", "url", "sha256", "valid_from", "entry", "exit", "class3", "class4", "read_on"])
            w.writerow(["X", "x.pdf", "x", "0" * 64, "2027-02-01", "A", "B", "12", "18", ""])
            w.writerow(["Y", "y.txt", "y", "1" * 64, y_from, "C", "D", "6", "9", y_read])
        out = os.path.join(d, "fr-2027-02-01.json")
        with contextlib.redirect_stdout(io.StringIO()) as said:
            fr.periods(pairs, stations, None, d)
        assert os.path.exists(out) == wrote and ("::warning" in said.getvalue()) != wrote, (y_from, y_read, said.getvalue())
        if wrote:
            os.remove(out)
    for f in (pairs, stations):
        os.remove(f)
    os.rmdir(d)


def test_gr():
    """Greece's year is the one its dated pages give; when they disagree
    (one has next year's prices, another not yet: Attiki Odos's new
    article not in sources.json yet), the build stops."""
    d = tempfile.mkdtemp()
    real, gr.BROWSER = gr.BROWSER, d
    try:
        for aegean, want in (("2027", "2027"), ("2026", None)):
            for sid, text in (("olympia", "Όπως ισχύουν από 01/01/2027"), ("aegean", f"Έναρξη ισχύος του τρέχοντος τιμοκαταλόγου 01 Ιανουαρίου {aegean} – 00:01"),
                              ("attiki", "Νέα Αττική Οδός: Τιμαριθμική προσαρμογή διοδίων τελών 2027")):
                open(os.path.join(d, f"gr-{sid}.html"), "w", encoding="utf-8").write(f"<html><p>{text}</p></html>")
            try:
                got = gr.year_of(d)
            except SystemExit:
                got = None
            assert got == want, (aegean, got)
        # Attiki Odos from its Chrome copy (gr-attiki.html not fetched).
        os.remove(os.path.join(d, "gr-attiki.html"))
        open(os.path.join(d, "gr-attiki.txt"), "w", encoding="utf-8").write("# read in Chrome\nΗ «Νέα Αττική Οδός Παραχώρηση Α.Ε.» ανακοινώνει ότι το 2027 και σύμφωνα με το άρθρο 18.4.1\n")
        open(os.path.join(d, "gr-aegean.html"), "w", encoding="utf-8").write("<p>Έναρξη ισχύος του τρέχοντος τιμοκαταλόγου 01 Ιανουαρίου 2027 – 00:01</p>")
        assert gr.price_year(d) == "2027"
        open(os.path.join(d, "gr-attiki.txt"), "w", encoding="utf-8").write("# read in Chrome\nΗ «Νέα Αττική Οδός Παραχώρηση Α.Ε.» ανακοινώνει ότι το 2026 και\n")
        try:
            gr.price_year(d)
            raise AssertionError("Attiki's Chrome copy of 2026 among 2027's pages")
        except SystemExit:
            pass
    finally:
        gr.BROWSER = real
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        os.rmdir(d)


def test_fr_read_on():
    """The day each FR page was read, from its capture, as parse.py writes
    it to pairs.csv (build.py's in_force_to goes by it), and how long it
    keeps a page's tariffs: to the end of the tariff year, or 92 days after
    it was read where that is later than its own tariff year's end, not
    past the read's."""
    import parse
    for name in ("alicorne", "alis", "ccise"):
        raw = open(os.path.join(here, "fr", "browser", name + ".txt"), encoding="utf-8").read()
        assert parse.read_day(parse.browser_head(raw)) == "2026-11-04", name
    cases = [({"valid_from": "2025-02-01", "read_on": "2026-11-04"}, "2027-01-31"),
             ({"valid_from": "", "read_on": "2026-11-04"}, "2027-01-31"),
             ({"valid_from": "2026-05-01", "read_on": "2027-02-10"}, "2027-05-13"),
             ({"valid_from": "2026-02-01", "read_on": ""}, "2027-01-31"),
             ({"valid_from": "", "read_on": ""}, "")]
    for r, want in cases:
        assert fr.in_force_to(r) == want, (r, fr.in_force_to(r), want)


def test_es():
    """Spain's Ministry tables: the newest year sources.json has, not one
    written in."""
    import es_ap53, es_ap68, es_stretch
    real = es_stretch.source_years
    es_stretch.source_years = lambda key, since="0": ["2025", "2026", "2027"]
    try:
        d = tempfile.mkdtemp()
        # (AP-68's builder reads its concession's end first.)
        open(os.path.join(d, "es-ap68-concession-end.txt"), "w", encoding="utf-8").write(
            "se gestiona, actualmente y hasta el 10 de noviembre de 2026, a través de un contrato de concesión ... Madrid, 23 de febrero de 2026")
        for b, key in ((es_ap53, "ap53"), (es_ap68, "ap68")):
            try:
                b.main(d, d)
            except FileNotFoundError as e:
                assert f"es-min-{key}-2027.txt" in str(e), (key, e)
            else:
                raise AssertionError(key)
        os.remove(os.path.join(d, "es-ap68-concession-end.txt"))
        os.rmdir(d)
    finally:
        es_stretch.source_years = real


def test_sources_missing():
    """A source a table needs, missing: the build stops (AP-68's concession
    end, London's bank holidays), and London's other zone is still built."""
    import es_ap68, gb_london
    d = tempfile.mkdtemp()
    try:
        es_ap68.main(d, d)
        raise AssertionError("AP-68 built without its concession's end")
    except SystemExit:
        pass
    for f in ("gb-tfl-cc.html", "gb-gazette-cc-2026.html", "gb-london-ccz-osm.json"):
        open(os.path.join(d, f), "w").write("")
    lez = []
    real, gb_london.lez = gb_london.lez, lambda *a: lez.append(1)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            gb_london.main(d, d)
        raise AssertionError("London built without GOV.UK's bank holidays")
    except SystemExit:
        assert lez == [1], "the LEZ wasn't built"
    finally:
        gb_london.lez = real
    # GOV.UK's page fetched but no longer saying a weekend's bank holiday moves.
    open(os.path.join(d, "gb-bank-holidays.html"), "w").write("<p>Bank holidays</p>")
    try:
        gb_london.ccz(d, d)
        raise AssertionError("London built without GOV.UK's substitute day")
    except SystemExit as e:
        assert "GOV.UK" in str(e), e
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    os.rmdir(d)
    # An open table lists the substitute days to 2099; a closed one its own years.
    assert gb_london.substitute_years("2030-03-04", None) == (2030, 2099) and gb_london.substitute_years("2026-01-02", "2030-03-03") == (2026, 2030)


def test_check_browser_fr():
    """An FR page read 2027-02-10 is kept by build.py to 2027-05-13; check_browser
    asks for it two weeks before."""
    import check_browser
    keep = fr.in_force_to({"valid_from": "", "read_on": "2027-02-10"})
    import datetime
    due = datetime.date.fromisoformat(keep) + datetime.timedelta(days=1 - 14)  # 14 days before the first day not kept
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "browser"))
    open(os.path.join(d, "browser", "x.txt"), "w").write("# read 2027-02-10 in a browser\n")
    real = check_browser.FR
    check_browser.FR = d
    try:
        for day, warn in ((due - datetime.timedelta(days=1), False), (due, True)):
            with contextlib.redirect_stdout(io.StringIO()) as said:
                check_browser.main(day.isoformat())
            assert ("::warning title=tools/fr/browser/x.txt" in said.getvalue()) == warn, (day, [l for l in said.getvalue().splitlines() if "x.txt" in l])
    finally:
        check_browser.FR = real
        os.remove(os.path.join(d, "browser", "x.txt"))
        os.rmdir(os.path.join(d, "browser"))
        os.rmdir(d)


if __name__ == "__main__":
    test_hu()
    test_fr()
    test_fr_stale()
    test_gr()
    test_fr_read_on()
    test_es()
    test_sources_missing()
    test_check_browser_fr()
    print("test_next_year: ok")

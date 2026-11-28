# Review of a change

Every change gets, before it is pushed, a review for each area it touches,
by a reviewer who didn't write it, against that area's list below. A
finding counts only with evidence: a request whose result is wrong, a
document the code contradicts, or committed data off its source or the
law's figures. Each mistake that gets past a review becomes a test and a
line here, so the next change is checked for it.

## Pricing (cost, rates, fuel, ferries, bans, fx)

- An input can be missing or partial (a diesel price, a day count, a
  route, emissions): the result says so (`missing`, `complete`, a null),
  and nothing built on it counts it as free or as one.
- A note, or a missing charge's text, never asks for what the request
  gives.
- What depends on an input not given (the departure time, a table's day
  basis, the route's positions) is taken over every value it can take,
  not one or two samples (every departure minute, so DST days too); the
  test case enters the country mid-trip. What stands for the input (a
  departure of 00:00 for the charges by the day) is the same in every
  country of the trip; a change to how an untimed trip is timed is
  checked against lapsed() and an origin whose time zone is ahead.
- The request and its result are in `TestInvariants` (cost); a new class
  of mistake is a new invariant there.

## API, CLI and documents

- A behaviour is described the same in the README, the doc comments
  (openapi.json is built from them), `--help` and the web page; the change
  updates every one.
- A document that says how to call something has a test that calls it so.
- An input format a change accepts is accepted everywhere the value goes
  in (a flag, a CSV cell, every list that holds such a value, the page),
  what it reads it also writes (`calc -csv`, `report`), and everything that
  reads the value back reads it so (`report`'s date column); a test gives
  each, one case a row.
- A number is read only where it reads one way: 1,200 is refused (in a ;
  CSV, whose decimal symbol is the comma, it is 1.2), and 12.500 where
  the list or file uses decimal commas or counts km or litres (a decimal
  point stays one for prices, rates and shares); an error's advice is
  itself accepted; the
  Go and page parsers run the same cases (testdata/countryvalues.json).
- A CSV row is read whole: more cells than the header names (a list cell
  unquoted) is an error, not cut.
- A claim that a tool's output is read ("as Excel writes it") has a test
  with that output as the tool writes it, quotes and all.

## Data pipelines (tools/tables, history, fr, orct, ...)

- No year, yearly rate or date a law sets is written in the code: it comes
  from the source, or from the rule the law gives (`tools/test_next_year.py`
  runs next year's case).
- A value is checked against its captured source, not against itself.
- A yearly rate ends with its year (valid_to), the newest too
  (TestYearlyRatesEnd); a concession or law that ends sets its end; prices
  a page gives with no date never change under the same valid_from.
- A rule with exceptions by date (Christmas Day, a substitute bank
  holiday) has a test on the exception's day.
- A workflow step is run on the empty case (no tables built) and on a
  crash (a step piped into tee runs with pipefail: shell: bash) before it
  is pushed.
- A source added for a table, not fetched, stops its build loudly, and
  the builder's other tables are still built, on a stop or a crash
  (older sources fall back on reuse.py's last copy).
- Dates a builder generates (substitute days) cover every year the table
  can be used in; a reminder to read a page again comes before a page
  kept past its tariff year stops, and on the yearly change's day
  (test_next_year.py runs both).

## Road classes (tools/roads)

- A change is judged by the tolled km against the law's (per class, per
  road), measured on the real extract before and after; a rule that only a
  made-up case needs is not added.

## Web page

- Each input or output the change touches has a case in
  `tools/web/test_page.cjs`.

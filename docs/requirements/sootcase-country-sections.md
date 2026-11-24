# Requirements for Sootcase: the route's countries in order

**For:** the agent working on Sootcase (github.com/majidkabir/sootcase, sootcase.org).
**From:** carbon-cost (github.com/majidkabir/carbon-cost).
**Status:** requested 2026-11-24; in Sootcase main on 2026-11-24. Checked as a black box that
day by the Sootcase country sections workflow (`tools/livecheck/sections.py`, Denmark,
Schleswig-Holstein and Hamburg): C1 (Kolding–Hamburg DK then DE; Copenhagen–Hamburg DK, the
Rødby–Puttgarden ferry section, DE), R2 (DE-SH and DE-HH in order) and R3 (the same with
`path=full`) pass; C3 passes for Kiel–Hamburg; C2 (Austria–Germany–Austria) isn't on that map.
carbon-cost reads the sections, their ferry flag and their regions.

## 1. Why

carbon-cost checks trips against the countries' driving bans for trucks (Sunday, public holiday,
weekend and night bans: Germany's StVO § 30, Austria's StVO 1960 § 42, and more to come). For
that it needs to know *when* the truck is in each country, so it needs *where along the route*
each country starts and ends.

Sootcase gives each leg's `country_km` (and `region_km` for some countries), which are totals in
no order. For a leg within one country that is enough. For a leg across several (Copenhagen to
Munich runs through Denmark, then Germany), carbon-cost can't tell whether the truck is in
Germany or Austria when a ban starts, and can only say that the trip *may* run into it.

Some holidays count only in some regions: Germany's Corpus Christi (6 states), Reformation Day
(9 states) and All Saints' Day (5 states). For those, carbon-cost needs the first-level region
too.

## 2. What to build

### R1. Country sections

Each road leg result (and each alternative in `alternatives`) gains `country_sections`: the
leg's stretches by country, **in route order**, km from the leg's start:

```json
"country_sections": [
  {"country": "DK", "from_km": 0, "to_km": 163.2},
  {"country": "DE", "from_km": 163.2, "to_km": 345.3, "regions": [
    {"region": "DE-SH", "from_km": 163.2, "to_km": 300.1},
    {"region": "DE-HH", "from_km": 300.1, "to_km": 345.3}]}
]
```

- `country`: ISO 3166-1 alpha-2, as in `country_km`.
- `from_km` and `to_km`: along the leg's own `distance_km`; the first starts at 0, the last ends
  at `distance_km`, each starts where the one before ends.
- A ferry crossing is a section of its own with `"country": ""` (or the flag state, if known) and
  `"ferry": true`, so the times on land stay right.
- The sum of a country's sections equals its `country_km` (to 0.01 km).
- A country the route enters twice (Germany, then Austria, then Germany) has two sections.

### R2. Regions

Where Sootcase knows the first-level regions (ISO 3166-2, as in `region_km`), each section has
`regions` the same way. Germany's states are needed first (the holidays above); other countries'
regions are welcome but not needed.

### R3. Speed and size

- No extra routing: the sections come from the path already split for `country_km`.
- With `path=full` or not, the same sections.

### R4. Documentation

Document `country_sections` in the API docs and OpenAPI, and say from which version.

## 3. Acceptance checks

| # | Request | Must hold |
|---|---|---|
| C1 | DKCPH to DEMUC by road | `country_sections` is DK, then DE (with the ferry section between if the route takes Rødby–Puttgarden); the km add up to `distance_km`; DE's matches `country_km.DE`. |
| C2 | Salzburg (AT) to Rosenheim (DE) to Kufstein (AT), one leg via the German corner | AT, DE, AT in that order. |
| C3 | Hamburg to Munich | DE only, with regions HH, NI, ..., BY in order. |
| C4 | Any trip | The response is otherwise unchanged, field for field. |

## 4. What carbon-cost does with it

With a departure time, carbon-cost works out when the truck enters and leaves each section (its
passage times, with the driver's breaks and rests when asked), checks each country's bans and
public holidays for those hours, and says how long the truck waits for a ban to end. Without
sections it reports the bans a multi-country leg *may* run into.

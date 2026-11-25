# Requirements for Sootcase: alternative truck routes

**For:** the agent working on Sootcase (github.com/majidkabir/sootcase, sootcase.org).
**From:** carbon-cost (github.com/majidkabir/carbon-cost), which prices a truck trip's tolls,
ferry fares and carbon charges on the route Sootcase returns.
**Status:** requested 2026-11-22; shipped in Sootcase v0.14.0 (`alternatives=N`, `avoid=ferries`).
carbon-cost prices the alternatives since v0.106.0 (`alternatives`, `route`, `avoid_ferries`).
Section 2 is how carbon-cost called Sootcase before.

**Gap found 2026-11-24 (v0.17.0):** without `alternatives`, the primary leg has no `summary`
(check S1 in `tools/livecheck/sections.py`: Kolding–Hamburg gives `roads None`). R2 asks for the
primary's `summary` always. carbon-cost now needs it on every call: Spain's driving restrictions
hold only on the road sections the DGT lists, and carbon-cost keeps only those on the route's
main roads (`summary.roads`). Without it, every Spanish restriction of the day is reported as
one the trip may run into. Acceptance: S1 passes with no `alternatives` in the query.

## 1. Why

carbon-cost prices only the one route Sootcase returns, and the charges depend heavily on the
route. Example, live on sootcase.org/carbon-cost on 2026-11-22: Copenhagen (DKCPH) → Munich
(DEMUC), 40 t truck, Euro VI, CO2 class 1. Sootcase routes it over the Gedser–Rostock ferry,
982 km. The trip prices at EUR 703.61, of which EUR 342.45 is the ferry fare and EUR 12.75
its ETS surcharge. A planner would also check Rødby–Puttgarden, and the land route over the
Storebælt bridge and through Jutland (A7 at Flensburg). Each of these has different tolls,
fares and km. Real users need several sensible routes priced side by side, and the cheapest
one picked. Competing tools offer this: HERE's routing can compute the cost-optimised route
from toll and vehicle costs.

Sootcase doesn't need to know any toll or fare. It should return a few different, legal
truck routes with the same detail it gives now. carbon-cost prices each one and picks.

## 2. How carbon-cost calls Sootcase today (keep this working unchanged)

`POST /v1/calculate?country_km=true&path=full`, with this body:

```json
{"id": "trip", "weight_kg": 20000, "add_road_legs": false,
 "legs": [{"id": "road", "mode": "road", "vehicle_type": "glec/road/eu_sa/artic_34_40t/diesel",
           "from": {"code": "DKCPH"}, "to": {"code": "DEMUC"}}]}
```

A trip with stops sends one road leg per stop pair, with ids `leg1`, `leg2` and so on.
carbon-cost reads these fields from each leg result: `distance_km`, `ttw_kg`, `wtw_kg`,
`route_parts_km` (`road`, `ferry`), `country_km`, `region_km` (ISO 3166-2, e.g. `BE-VLG`),
`path` (every `[lon, lat]` point; toll stations and gantries are matched within 30 m, so a
thinned line won't do) and `parts` (`kind`, `distance_km`, `ttw_kg`, `wtw_kg`). From the
whole result it also reads `ttw_kg`, `wtw_kg`, `dataset` and `warnings`. carbon-cost
recognises ferry crossings itself by matching `path` against its own crossing list.

## 3. What to build

### R1. Ask for alternatives

- New query parameter `alternatives=N`, N from 1 to 5, default 1.
- N = 1, or no parameter at all, gives exactly today's response, field for field.
- N outside 1–5 gives HTTP 400 with `{"error": "..."}`.
- It applies to every road leg of the request.

### R2. Return them on each leg

- Each road leg result keeps today's fields for the **primary** route, the one Sootcase would
  return today.
- It gains `alternatives`: an array of up to N − 1 **other** routes. Each one has the same
  fields as a leg result (`distance_km`, `ttw_kg`, `wtw_kg`, `route_parts_km`, `country_km`,
  `region_km`, `path` at full detail, `parts`), worked out exactly the way the primary's are.
- Each alternative also has:
  - `id`: stable within the response, e.g. `alt1`, `alt2`.
  - `summary`: what tells it apart, for a person. For example `{"roads": ["E47", "A1", "A7"],
    "ferries": [{"name": "Rødby–Puttgarden", "from": "Rødby", "to": "Puttgarden",
    "distance_km": 18.5}]}`, with `ferries: []` for a land-only route. Road refs and ferry names
    come from OSM (`ref` on the main roads, and `name` or the ports of the `route=ferry` way or
    relation).
  - `duration_h` (wanted, not required): driving time at truck speeds, ferry time included.
- Give the primary the same `summary` (and `duration_h` if built), as top-level fields of the
  leg, so all routes can be shown alike.
- The whole result's `ttw_kg` and `wtw_kg` stay the primary routes' totals.

### R3. Which routes count as alternatives

- **Legal for the truck:** the same vehicle profile and restrictions as the primary.
- **Really different:** two routes are the same if they share 80% or more of their length,
  unless they use a different set of ferry crossings. Never return near-duplicates. If there
  are fewer real alternatives than asked for, return fewer.
- **Sensible:** no alternative is longer than 1.5 × the primary's `distance_km`.
- **Ferry against land:** where the primary uses a ferry and a land-only route exists within
  the 1.5 × limit, the best land-only route is among the alternatives. Where the primary is
  land-only and a ferry route exists within the limit, the best ferry route is among them.
  Where several ferry crossings serve the trip, include the best route over each distinct
  crossing, as far as N allows. This rule outranks plain shortest-next ordering.
- **Order:** the primary first, then alternatives by Sootcase's own cost (time or distance,
  as it ranks routes now).
- **Repeatable:** the same request on the same map data gives the same alternatives in the
  same order.

### R4. Avoiding ferries

- New query parameter `avoid=ferries`: route every leg on land only. If a leg has no land
  route, give HTTP 422 saying which leg.
- It combines with `alternatives`.

### R5. Limits and speed

- With `alternatives=3`, a single-leg trip of up to 2,500 km answers within 3 × the time of
  the same request with `alternatives=1`.
- The response with full paths stays under 32 MB, the most carbon-cost reads.
- A server that may refuse N > 1 under load answers HTTP 429 or 503, not a silently shorter
  list.

### R6. Documentation

- Document `alternatives`, `avoid=ferries`, the `alternatives` array, `summary` and
  `duration_h` in Sootcase's API docs and OpenAPI, and say in the changelog from which version
  they are available.

## 4. Acceptance checks

Run each against sootcase.org (or a local server on the same map), with the body in §2
(40 t artic, `weight_kg` 20000), `country_km=true&path=full&alternatives=3`. For each, record
the routes' `distance_km`, `country_km`, `summary` and the ferry parts.

| # | From → To | Must hold |
|---|---|---|
| A1 | DKCPH → DEMUC | At least one land-only route over the Storebælt bridge (DK→DE at Padborg/Flensburg, no ferry part), and at least one ferry route over a crossing other than the primary's (Gedser–Rostock or Rødby–Puttgarden). |
| A2 | SEGOT → DEHAM | Among the routes: a ferry route (e.g. Gothenburg–Kiel, or Trelleborg–Rostock/Travemünde) and a land-only route over the Øresund and Storebælt bridges. |
| A3 | DEHAM → ITMIL | At least two routes over different Alpine crossings (e.g. Brenner through Austria, and Gotthard or San Bernardino through Switzerland). |
| A4 | DEHAM → DEBRE | No near-duplicates: whatever comes back shares less than 80% of its length with the primary, or there are no alternatives at all. |
| A5 | Any of the above, no `alternatives` parameter | Response identical to today's (compare the JSON field by field). |
| A6 | A1 with `avoid=ferries` | The primary has no ferry part and `route_parts_km` has no `ferry`. |
| A7 | A1 with `alternatives=6` and `alternatives=0` | HTTP 400. |
| A8 | A1 run twice | The same routes in the same order. |
| A9 | A trip with two legs (DKCPH → DEHAM → DEMUC) | Each leg has its own `alternatives`, and each obeys R3. |

Each alternative's `ttw_kg` and `wtw_kg` must equal what Sootcase gives when that same route
is the primary. For instance, add a via stop that forces it and compare; small differences
from point snapping are fine.

## 5. Out of scope here

- Tolls, fares and charges: carbon-cost prices them.
- Truck dimension restrictions (height, width, weight per axle, hazardous goods): a separate
  request, if wanted later.
- Picking the cheapest route: carbon-cost does it once the alternatives come back.

## 6. What carbon-cost will do with it (for context)

- New request field `alternatives` (1–5): carbon-cost asks Sootcase for that many and prices
  each route in full. Its response gains `alternatives`, each with `summary`, `distance_km`,
  `country_km`, the ferry crossing, `total_eur`, `carbon_eur`, `complete` and the difference
  from the primary.
- New request field `route`: `"primary"` (default) or `"cheapest"` (price and return the
  cheapest complete route).
- The web page shows an "Other routes" table under the result, with a button to price one of
  them.
- `ferry: "avoid"` maps to Sootcase's `avoid=ferries`.

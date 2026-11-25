# Requirements for Sootcase: routes legal for the truck's size, weight and load

**For:** the agent working on Sootcase (github.com/majidkabir/sootcase, sootcase.org).
**From:** carbon-cost (github.com/majidkabir/carbon-cost), which prices a truck trip's tolls,
ferry fares, diesel and carbon charges on the route Sootcase returns.
**Status:** requested 2026-11-23; shipped in Sootcase v0.15.1. The black-box check (Sootcase truck
restrictions workflow, `tools/livecheck/restrictions.py`, Hamburg map) passes on v0.15.1: 11
passed, 0 failed, 4 skipped. carbon-cost sends the vehicle since v0.110.0 (`truck.height_m`,
`width_m`, `axle_load_kg`, `hazmat`, `adr_tunnel_code`; `trip.routed_for`). Section 2 is how
carbon-cost called Sootcase before.

## 1. Why

carbon-cost sends Sootcase only a vehicle type (`glec/road/eu_sa/artic_34_40t/diesel`) and
the cargo weight. It never says how tall, wide, long or heavy the truck is, or whether it
carries dangerous goods. So the route, and every charge priced on it, can run under a bridge
the truck doesn't fit, over a bridge it may not cross, or through a tunnel its load is barred
from. A planner can't use a price for a route the truck may not drive.

Route planners for trucks take these as inputs. HERE's routing, for example, avoids roads by
the vehicle's height, width, length, weight, axle load, hazardous goods and ADR tunnel
category. Real users need the same before they trust a price.

The limits come from law and road signs:

- **Directive 96/53/EC** (maximum dimensions and weights in international traffic): height
  4.00 m, width 2.55 m (2.60 m refrigerated), length 16.50 m for a tractor with semi-trailer
  and 18.75 m for a road train, 40 t for a five- or six-axle combination, 11.5 t on a drive
  axle. Most trucks carrying normal goods are at or under these, but national roads are signed
  lower (bridges, town centres, old tunnels).
- **ADR** (Agreement concerning the International Carriage of Dangerous Goods by Road),
  1.9.5: road tunnels are put in categories A to E, and each dangerous load has a tunnel
  restriction code (B, C, D or E) that says which tunnel categories it may not enter.
- **OpenStreetMap** maps the signs: `maxheight`, `maxwidth`, `maxlength`, `maxweight`
  (and `maxweight:hgv`), `maxaxleload`, `hgv=no|destination|delivery`, `hazmat=no`, and
  `hazmat:B` to `hazmat:E` (keyed by the load's tunnel restriction code, as the OSM wiki's
  Key:hazmat page explains), with `:conditional` variants.

## 2. How carbon-cost calls Sootcase today (keep this working unchanged)

`POST /v1/calculate?country_km=true&path=full` (plus `alternatives=N` and `avoid=ferries`
since Sootcase v0.14.0), with this body:

```json
{"id": "trip", "weight_kg": 20000, "add_road_legs": false,
 "legs": [{"id": "road", "mode": "road", "vehicle_type": "glec/road/eu_sa/artic_34_40t/diesel",
           "from": {"code": "DKCPH"}, "to": {"code": "DEMUC"}}]}
```

carbon-cost reads, per leg: `distance_km`, `ttw_kg`, `wtw_kg`, `route_parts_km`,
`country_km`, `region_km`, `path` (full detail), `parts`, `summary`, `duration_h` and
`alternatives`; per result: `ttw_kg`, `wtw_kg`, `dataset` and `warnings`.

## 3. What to build

### R1. Say what the truck is

A road leg may carry a new object `vehicle`. Every field is optional; a field left out puts
no limit on the route for that dimension, exactly as today.

```json
"vehicle": {"height_m": 4.0, "width_m": 2.55, "length_m": 16.5,
            "gross_weight_kg": 40000, "axle_load_kg": 11500, "axles": 5,
            "trailer": "semi", "tunnel_code": "D", "hazmat": true}
```

| Field | Meaning | Allowed |
|---|---|---|
| `height_m` | height with load | 1.5 to 5.0 |
| `width_m` | width without mirrors | 1.5 to 3.5 |
| `length_m` | length of the whole combination | 4 to 30 |
| `gross_weight_kg` | actual gross weight (truck, trailer and cargo) | 3,500 to 60,000 |
| `axle_load_kg` | heaviest axle load | 1,000 to 15,000 |
| `axles` | axles of the combination | 2 to 12 |
| `trailer` | `none`, `semi` (semi-trailer) or `drawbar` | |
| `hazmat` | carries dangerous goods under ADR | true / false |
| `tunnel_code` | the load's ADR tunnel restriction code (implies `hazmat`) | `B`, `C`, `D`, `E` |

A value out of range answers HTTP 400 with `{"error": "..."}` naming the field.

### R2. Route only where the truck may drive

With `vehicle` given, the primary route and every alternative avoid each way, node or turn
where OSM says the truck may not go:

- `maxheight` below `height_m`, `maxwidth` below `width_m`, `maxlength` below `length_m`.
- `maxweight` or `maxweight:hgv` below `gross_weight_kg`; `maxaxleload` below
  `axle_load_kg`.
- `hgv=no`. `hgv=destination` and `hgv=delivery` only on the first and last km of a leg
  (the way to the stop itself), as now for other access tags.
- With `hazmat`: `hazmat=no`. With `tunnel_code` X: `hazmat:X=no` (OSM tags every code the
  tunnel bars, so a category D tunnel carries `hazmat:B=no`, `hazmat:C=no` and
  `hazmat:D=no`).
- `:conditional` restrictions may be treated as always on; say so in the docs.
- Values in other units (`maxheight=13'6"`, `maxweight=7.5 st`) are converted; values that
  can't be read (`maxheight=default`, `below_default`) put no limit.

The request's `vehicle_type` still picks the emission factors; `vehicle` only restricts the
roads.

### R3. Say when it can't

- If no route on the map obeys R2, answer HTTP 422 naming the leg and the limit that blocks
  it (for example `leg2: no route under maxheight 4.0 m`), not a route that breaks it.
- If the route obeys R2 only by leaving the road network for its first or last km (a stop on
  a restricted street), add a `warnings` entry for that leg.

### R4. Tell carbon-cost what was applied

- Each leg result gains `restrictions`: the `vehicle` fields that Sootcase applied, as it
  read them (so carbon-cost can show "routed for 4.0 m, 40 t, tunnel code D").
- The result's `dataset` (or a new `map_date`) says the OSM extract's date, as now.

### R5. Alternatives and ferries

- `vehicle` combines with `alternatives=N` and `avoid=ferries`. Every alternative obeys R2,
  and the existing rules for alternatives (different, sensible, ferry against land) apply to
  the routes that obey it.
- A ferry crossing is not restricted by these fields (the ship's own rules are carbon-cost's
  business).

### R6. Speed

- A request with `vehicle` answers within 2 × the time of the same request without it.
- If the routing engine can only restrict by a fixed set of profiles (OSRM's contraction
  hierarchies are built per profile), it is fine to offer a few profiles and pick the
  smallest one that covers the request, as long as R2 holds for the values sent. For
  example: height 4.0 m / 2.55 m / 16.5 m / 40 t / 11.5 t, and the same with tunnel codes
  B, C, D and E. Say in the docs which profiles exist; a request that no profile covers
  answers HTTP 422 saying so.

### R7. Documentation

- Document `vehicle`, `restrictions` and the new 400 and 422 answers in Sootcase's API docs
  and OpenAPI, with the OSM tags used, and say in the changelog from which version they are
  available.

## 4. Acceptance checks

Run each against sootcase.org (or a local server on the same map) with the body in §2. For
each, record the routes' `distance_km`, `summary` and `restrictions`. The OSM ways named
below must be picked from the map extract Sootcase runs on (Overpass or osmium on the same
`.osm.pbf`), so the checks stay true when the map changes:

| # | Request | Must hold |
|---|---|---|
| B1 | No `vehicle` | Response identical to today's, field for field. |
| B2 | A trip whose primary route today crosses a way tagged `maxheight` < 4.0 (pick one from the extract, e.g. a low railway bridge on a national road), with `height_m: 4.0` | The new route uses no way with `maxheight` < 4.0. |
| B3 | A trip whose primary route today crosses a way tagged `maxweight` (or `maxweight:hgv`) < 40 t, with `gross_weight_kg: 40000` | The new route uses no way with a `maxweight` below 40 t. |
| B4 | A trip whose primary route today runs through a tunnel tagged `hazmat:D=no`, with `tunnel_code: "D"` | The new route uses no way tagged `hazmat:D=no` (category D and E tunnels). A category B or C tunnel (`hazmat:C=no` with `hazmat:D=yes` or no `hazmat:D`) may be used. |
| B5 | B4 with `tunnel_code: "E"` | Ways tagged `hazmat:E=no` are avoided; a `hazmat:D=no` way that is not also `hazmat:E=no` may be used. |
| B6 | A stop that can only be reached under a `maxheight` < 4.0, with `height_m: 4.0` | HTTP 422 naming the leg and the limit, or a route with a `warnings` entry as in R3. |
| B7 | `height_m: 9` | HTTP 400 naming `height_m`. |
| B8 | B2 with `alternatives=3` | Every route returned obeys B2. |
| B9 | B2 run twice | The same route. |

## 5. Out of scope here

- Driving bans by day and hour (Sunday and holiday bans, night bans): wanted later, as time
  windows on the route; carbon-cost already knows the departure time.
- Low-emission and city access zones by Euro class: carbon-cost prices the zones it knows.
- Special permits for abnormal loads.

## 6. What carbon-cost will do with it (for context)

- Request fields under `truck`: `height_m`, `width_m` (with `length_m`, `max_mass_kg`,
  `axles` already there), an optional heaviest axle load, and `adr_tunnel_code`. carbon-cost
  sends them on every road leg as `vehicle`, with `gross_weight_kg` as the tare plus the
  cargo on the leg (or the maximum mass when the tare isn't given).
- The web page gets height, width and "dangerous goods (tunnel code)" fields, and shows the
  restrictions applied under the route.
- A 422 is shown as is: the trip can't be driven by that truck on the map.

# What happens to a request

This follows one `POST /v1/carbon-cost` request through the code. `carbon-cost calc` takes the same path after it has turned its flags into a `cost.Request` (`parseCalcWith` in `cmd/carbon-cost/main.go`). A CSV upload (`POST /v1/carbon-cost/csv`), a JSON batch (`POST /v1/carbon-cost/batch`) and `calc -csv` run each row through it too (`priceAll` and `priceCSV` in `cmd/carbon-cost/batch.go`).

```mermaid
sequenceDiagram
  participant H as HTTP handler (cmd/carbon-cost)
  participant C as cost.Calculator.Calculate
  participant S as Sootcase
  participant P as cost.PriceWith
  H->>C: cost.Request (JSON, unknown fields refused)
  C->>C: date, check, defaults (vehicle type, alternatives)
  C->>S: GET /v1/factors (own diesel or electricity only)
  C->>S: POST calculation: legs at the heaviest load (Calculator.trip)
  C->>S: one more per shipment that doesn't ride stop to stop
  C->>C: Route: runs by country, ferries; RoadKm: road classes
  C->>P: the result, the tables, the request
  P->>P: emissions, tolls, crossings, ferry ETS, ETS2, fuel CO2, zones
  P->>P: lapsed rates, fuel or power cost, comparisons, running cost, bans, shipments, currency
  P-->>H: cost.Response
```

## 1. The handler

`handlerAt` in `cmd/carbon-cost/main.go` decodes the body into `cost.Request` with `DisallowUnknownFields` (8 MB at most, for a path of up to `cost.MaxPathPoints` points) and calls `Calculator.Calculate`. A bad request is 400. A Sootcase error is passed on by its kind (`sootcase.HTTPError`): Sootcase refusing the request itself is the caller's 400 (`HTTPError.CallerError`), Sootcase failing or refusing this server is 502, and Sootcase limiting it (429) is 503.

The `Calculator` is built once at start (`calculator` in `cmd/carbon-cost/main.go`): the embedded datasets (`tariffs.Load`), the ferry data (`ferries.Load`), Sootcase's Natural Earth borders (`borders.Default`, from the `github.com/majidkabir/sootcase` module), the road network (`roads.Default`), and the exchange rates: the embedded history (`fx.OnDate`) and the ECB's daily file for days past it (`fx.Cache`).

## 2. Calculate: inputs and the route

`Calculator.Calculate` in `cost/cost.go`:

1. **Date** (`Calculator.date`): the request's `date`, else today. Every rate is looked up for that day.
2. **Check** (`check` in `cost/cost.go`, `checkTrip` in `cost/trip.go`, `checkOwnRoute` in `cost/ownroute.go`): every field's range and the fields that need each other. Errors name the field.
3. **Defaults**, each listed in `provenance.assumed`: the date, the Sootcase vehicle type (`DefaultVehicleType`, or `ElectricVehicleType` for CO2 class 5), and 3 or 5 alternatives when a `route` other than the primary is asked for.
4. **Factors** (`factorsOf` in `cost/factors.go`): when the truck's own diesel or electricity is given, Sootcase's `/v1/factors` for its GLEC diesel factor and the grids' intensity by country. Cached for a day per Sootcase URL.
5. **Exchange rates**: the day's ECB rates from the embedded history, else today's from the ECB.
6. **The route**, one of three ways:
   - **`country_km`**: no route. `kmTrip` in `cost/ownroute.go` makes a one-leg result from the km by country. Point tolls, crossings, zones and ferries can't be priced; the response says so.
   - **Sootcase** (`Calculator.trip` in `cost/cost.go`): one calculation with a road leg per pair of stops, every leg at the heaviest load on board, then each leg's emissions scaled to its own load (Sootcase's emissions are its intensity times tonne-km). A shipment that isn't loaded and unloaded at consecutive stops gets its own calculation, for its own distance and emissions.
   - **`path`** (the truck's own track): Sootcase still routes the stops, for the emissions, and `ownPath` in `cost/ownroute.go` puts the path in place of Sootcase's route for the km, km by country and region, and ferries.
7. **One route or several**: with `alternatives` above 1, `Calculator.priceRoutes` (`cost/routes.go`) prices each route (`variants`) and answers for the one asked for in `route` (`primary`, `cheapest`, or a route's id such as `alt1` or `leg2:alt1`), listing them all under `routes`. Otherwise `Calculator.priceRoute`.

`Calculator.priceRoute` splits the route into runs by country (`Route` in `cost/route.go`, Sootcase's borders and rule, with the ferry crossings of `ferries/data` cut out), sums each country's road classes (`RoadKm`, package `roads`) where it has the network, and calls `PriceWith`.

## 3. PriceWith: the charges

`PriceWith` in `cost/cost.go` builds the `Response` in this order:

1. **Emissions** (`tripEmissions` in `cost/trip.go`): Sootcase's, or the truck's own diesel or electricity (primary data comes first under EN ISO 14083 and Regulation (EU) 2026/1030): litres times Sootcase's GLEC factor (EN 16258's where it has none), or kWh times the grid of the countries where the truck charges. Shared out to the shipments by tonne-km (`shareEmissions`). The method and the basis are in `emissions_standard`, `certification` and `provenance`.
2. **The trip** (`tripOf`, `tripFuel`, `tripHours` in `cost/trip.go`): legs, loads, road km, the diesel (given, bought, `l_per_100km`, or the VECTO default for the vehicle group and load) and the hours.
3. **Distances**: km, ferry km, km by country and region, from Sootcase's legs.
4. **Tolls by area** (`areas` in `cost/cost.go`, then `pricer.priceArea` in `cost/tolls_price.go`): for each country, or region where tolls are set by region, the dataset in force that day (`tariffs.Set.Find`). Each ORCT charge is priced through package `orct`: per-km charges on the area's km (by road class where the dataset has them), per-day charges on the trip's days there, sections and closed systems along the route (`pricer.sectionsOn`, `pricer.matchSystems`) and toll points (`pricer.matchPoints`), at the times the truck passes them (`passage`, with `withRest` when `driver_rest` is set). A country with km but no dataset in force is listed under `no_rates` and under `missing` (reason `no_table`, or `ended` when its rates ran out with nothing after them).
5. **Crossings** (`pricer.priceCrossings`): bridges and tunnels the route passes.
6. **Ferry ETS** (`priceFerryETS`, `priceFerryUKETS` in `cost/cost.go`): each crossing's emissions for the truck (its ships' EU MRV intensity times tare and cargo where `tare_kg` is given, `mrvFerry`; else Sootcase's), times the share under the EU or UK ETS by law (`ferries.Data.Coverage`, `ferries.Data.UKCoverage`), times the phase-in, at the allowance price. Or the line's own ETS surcharge where it publishes one (`ferrySurcharge`).
7. **ETS2** from `ETS2Start` (2028), when `ets2_eur_per_t` is given: the trip's road diesel times `DieselKgCO2PerL`, at that price.
8. **National CO2 prices on fuel** (`pricer.priceFuel`): where the fuel is bought (`fuelShares`).
9. **Zones** (`pricer.priceZones`): environmental and congestion zones the route enters, on the days it is in them.
10. **Lapsed rates** (`lapsed`): crossings, zones and fuel CO2 prices whose rates ended with nothing after them, priced on their last day to say whether the trip would pay. `complete` is false when anything is missing.
11. **Fuel or electricity cost** (`fuelCost`, `electricityCost` in `cost/fuelcost.go`): the price given, else the Weekly Oil Bulletin's national average of the trip's week (national sources for GB, NO and CH, package `fuel`), less the hauliers' excise refund with `diesel_refunds`; Eurostat's power price for businesses for electricity.
12. **Comparisons** (`compare`): the same trip priced again for each CO2 class in `compare_co2_classes`.
13. **Running cost** (`runningCost`): driver per hour and vehicle per road km, at the rates given.
14. **Driving bans** (`checkBans` in `cost/bans.go`): each stretch of the trip by country and region (`segments`) against package `bans`, at the times it is there. A sure ban makes the truck wait (`wait_h`); a ban that holds only on listed roads, in some regions or in some transit is reported as one the trip may run into.
15. **Shipments** (`allocate` in `cost/trip.go`): each shipment's share of every charge, by tonne-km, or by loading metres or pallet places (`cost_share_by`); emissions are always by tonne-km.
16. **Currency** (`convert` in `cost/currency.go`): totals in `currency`, at the ECB rate of the day or the request's `fx`.
17. **Rounding and sources**: amounts to the cent, distances to the metre; each source once (`addSource`).

## 4. The response

`cost.Response` carries the lines (`cost.Line`: charge, country, amount in the table's currency and in euros, whether it is a carbon charge, the rate and its source), the totals, the trip, the fuel, the bans, the shipments, the routes, the notes and the `provenance` (versions, tables used, exchange rates, assumptions). Its fields and the request's are documented in `cmd/carbon-cost/web/openapi.json`, written from the Go types and their comments by `internal/apidoc` (`go run ./tools/openapi`); `TestOpenAPIUpToDate` fails when it is stale.

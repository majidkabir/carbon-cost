# Checks, releases and live checks

## CI

CI (`.github/workflows/ci.yml`) runs on every push to main and on pull requests:

| Job | What it checks |
|---|---|
| test | `gofmt` leaves nothing to change, `go vet ./...`, `go test ./...`, every exported Go name has a doc comment (`go run ./tools/docs/godoc`), and every name this documentation gives exists (`python3 tools/docs/check.py`) |
| tables | What Publish data may publish on its own (`tools/orct/test_publish.py`), the expiring rates list (`tools/orct/test_expiring.py`), Poland's network matching (`tools/roads/test_plnet.py`), and the converter: the synthetic test tables (`cost/testdata/synthetic/tables`) convert to exactly the datasets the Go tests price (`cost/testdata/synthetic/orct`) |
| docker | The image builds and lists the rate tables (`carbon-cost rates`) |

The Go tests need no network: Sootcase is a fake server (`httptest`), and the rate tables, exchange rates and fuel prices are the embedded ones.

## The tests that hold the figures to their sources

- `cost/data_test.go`: the laws' own worked figures (each test names its law and clause).
- `cost/official_test.go`: totals from the governments' own toll calculators, read in Chrome (`tools/tables/browser`): the km they route, priced here, give their total.
- `orct/vectors_test.go`: the ORCT conformance vectors; `orct/record_test.go`, when `ORCT_RECORDED` names a file, the reference calculator's statements line for line.
- `tariffs/history_test.go`: a scheme's versions don't overlap and every date is a day.
- `TestOpenAPIUpToDate`: `cmd/carbon-cost/web/openapi.json` is what `go run ./tools/openapi` writes.

## Releases

The version is the one line of `RELEASE` (vMAJOR.MINOR.PATCH); builds set it as `main.version`.

1. **Release** (`.github/workflows/release.yml`) runs when `RELEASE` changes on main, or by hand. It builds `carbon-cost` for Linux, macOS (amd64, arm64) and Windows, attaches them to a GitHub release with the version's tag, and pushes the image `ghcr.io/majidkabir/carbon-cost` (the version and `latest`; `Dockerfile`: a static binary on distroless, `serve` on port 8090). When the repository variable `DEPLOY_DISPATCH_REPO` and the secret `DEPLOY_DISPATCH_TOKEN` are set, it then sends that repository a `repository_dispatch` event, `carbon-cost-release`, with the version and image. The deployment itself is not in this repository.
2. **Data release** (`.github/workflows/data-release.yml`, Mondays 05:47 UTC, or by hand): when the embedded data changed since the last release (`tariffs/data`, `fx/data`, `fuel/data`, `ferries/data`, `bans/data`, `roads/data`) and no code did, it raises the patch number and starts Release. With code changes not yet released it does nothing: those are released by raising `RELEASE` by hand.

## Live checks against Sootcase

The tests fake Sootcase; these run the real one, as a black box, with real OSRM routing on small OpenStreetMap extracts:

| Workflow | Run | What it checks |
|---|---|---|
| Live check (`.github/workflows/live-check.yml`) | Actions tab, or push to `live-check` | Sootcase as on sootcase.org (else main); carbon-cost prices real trips and prints them as annotations (`live-out`) |
| Sootcase country sections (`.github/workflows/sootcase-sections.yml`) | Actions tab (`sootcase_ref`) | Country sections, the result's basis and certification, the road vehicle types, the route summary with and without alternatives, and the driving bans on a Copenhagen to Hamburg trip (`tools/livecheck/sections.py`, `tools/livecheck/vehicle_types.py`) |
| Sootcase truck restrictions (`.github/workflows/sootcase-restrictions.yml`) | Actions tab | Routing for the truck's size, weight and dangerous goods around the extract's low bridges, weight limits and tunnels (`tools/livecheck/restrictions.py`) |

What carbon-cost needs from Sootcase, and what these found, is in `docs/requirements/`.

## Warnings that come by mail

GitHub mails the owner when a scheduled run fails:

- a data builder failed (Tables data, Croatia data, France data, History data);
- a page read in Chrome is due to be read again (Pages read in Chrome, `.github/workflows/browser-pages.yml`);
- a driving-ban calendar no longer matches its decree (`tools/tables/check_bans.py`).

Publish data's summary lists datasets with real changes for review and the schemes whose rates run out within 45 days (`tools/orct/expiring.py`).

## Branches

`main` holds the code and the committed data. The data workflows' trigger branches (`tables-data`, `hr-data`, `fr-data`, `history-data`, `roads-data`, `mrv-data-run`, `live-check`, `bans-check`) only start a run when pushed to; their output branches (`tables-out`, `hr-out`, `fr-out`, `history-out`, `roads-out`, `mrv-data`, `live-out`) are force-pushed by each run and hold only its last output.

## Documentation

These pages, `README.md` (what carbon-cost does and how to use it), `docs/requirements/` (what it needs from Sootcase), and the doc comments, which `go doc` shows and the OpenAPI file is written from. `tools/docs/check.py` and `tools/docs/godoc` keep them in step with the code.

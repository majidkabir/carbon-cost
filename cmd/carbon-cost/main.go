// Command carbon-cost prices the carbon and road charges of a truck trip:
// km-based road tolls by country (with their CO2 part), the EU ETS on
// ferry crossings and ETS2 on road fuel from 2028.
//
//	carbon-cost calc -from DKCPH -to DEHAM -mass-kg 40000 -axles 5 -euro 6 -co2-class 1 -cargo-kg 20000
//	carbon-cost serve -addr :8090
//	carbon-cost rates
package main

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io/fs"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"text/tabwriter"
	"time"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/fx"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/carbon-cost/sootcase"
	"github.com/majidkabir/sootcase/pkg/borders"
)

const usage = `carbon-cost prices the carbon and road charges of a truck trip.

Commands:
  calc   price one trip
  serve  run the HTTP API (POST /v1/carbon-cost, GET /v1/rates)
  rates  list the toll tables

Run "carbon-cost <command> -h" for a command's flags.
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "calc":
		err = calc(os.Args[2:])
	case "serve":
		err = serve(os.Args[2:])
	case "rates":
		err = listRates()
	default:
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

// sootcaseFlags adds the flags for reaching Sootcase.
func sootcaseFlags(fs *flag.FlagSet) *sootcase.Client {
	c := &sootcase.Client{APIKey: os.Getenv("SOOTCASE_API_KEY")}
	fs.StringVar(&c.BaseURL, "sootcase", envOr("SOOTCASE_URL", sootcase.DefaultURL), "Sootcase server URL (env SOOTCASE_URL)")
	return c
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func calculator(sc *sootcase.Client) (cost.Calculator, error) {
	tbs, err := rates.All()
	if err != nil {
		return cost.Calculator{}, err
	}
	fd, err := ferries.Load()
	if err != nil {
		return cost.Calculator{}, err
	}
	bix, err := borders.Default()
	if err != nil {
		return cost.Calculator{}, err
	}
	fxCache := &fx.Cache{URL: os.Getenv("FX_URL")}
	rx, err := roads.Default()
	if err != nil {
		return cost.Calculator{}, err
	}
	return cost.Calculator{Sootcase: *sc, Tables: tbs, Ferries: &fd, Borders: bix, Roads: rx, FX: fxCache.Get}, nil
}

func calc(args []string) error {
	fs := flag.NewFlagSet("calc", flag.ExitOnError)
	sc := sootcaseFlags(fs)
	var req cost.Request
	from := fs.String("from", "", "origin: UN/LOCODE (DKCPH), IATA code or lat,lon")
	to := fs.String("to", "", "destination, as -from")
	fs.StringVar(&req.Date, "date", "", "trip date YYYY-MM-DD (default today)")
	fs.Float64Var(&req.CargoKg, "cargo-kg", 0, "cargo weight in kg")
	fs.StringVar(&req.VehicleType, "vehicle", cost.DefaultVehicleType, "Sootcase vehicle type")
	fs.IntVar(&req.Truck.MaxMassKg, "mass-kg", 40000, "truck's technically permissible maximum mass, kg")
	fs.IntVar(&req.Truck.Axles, "axles", 5, "axles (truck and trailer)")
	fs.IntVar(&req.Truck.Euro, "euro", 6, "Euro emission standard 0-6 (EEV = 5)")
	fs.IntVar(&req.Truck.CO2Class, "co2-class", 1, "EU CO2 emission class 1-5 (5 = zero-emission)")
	fs.IntVar(&req.Truck.TareKg, "tare-kg", 0, "truck's own weight with trailer, kg (lets ferries use their MRV data)")
	fs.Float64Var(&req.Truck.LengthM, "length-m", 0, "truck length with trailer, m, for bridge tolls (default 16.5)")
	fs.Float64Var(&req.EUAEurPerT, "eua", 0, "EU ETS allowance price, EUR/t, for ferry crossings")
	fs.Float64Var(&req.FerryETSShare, "ferry-ets-share", 0, "share of ferry emissions under the ETS (default 1; 0.5 to/from a non-EEA port)")
	fs.Float64Var(&req.ETS2EurPerT, "ets2", 0, "ETS2 allowance price, EUR/t, for trips from 2028")
	fs.Float64Var(&req.DKKPerEUR, "dkk-per-eur", 0, "DKK per EUR (default the ERM II central rate 7.46038)")
	tolled := fs.String("tolled-share", "", "share of each country's km on tolled roads, e.g. DK=1,DE=0.9 (default 1)")
	mway := fs.String("motorway-share", "", "share of tolled km on motorways where rates differ by road type, e.g. CZ=0.9,BE-BRU=0.2")
	fxs := fs.String("fx", "", "exchange rates in units per euro, e.g. CHF=0.93,CZK=24.3 (default the ECB reference rates)")
	zone := fs.String("env-zone-km", "", "km in environmental zones by country, e.g. DK=4")
	cmp := fs.String("compare", "", "also price the trip for these CO2 classes, e.g. 1,4,5")
	fs.Float64Var(&req.TripsPerYear, "trips-per-year", 0, "trips per year, for yearly savings in the comparison")
	fs.BoolVar(&req.ETC, "etc", false, "pays tolls by electronic toll device or agreement (operators' discounts)")
	fs.BoolVar(&req.Night, "night", false, "the trip passes night-tariff sections at night (22:00-05:00, Austria's A 13)")
	asJSON := fs.Bool("json", false, "print the result as JSON")
	fs.Parse(args)

	var err error
	if req.From, err = location(*from); err != nil {
		return fmt.Errorf("-from: %w", err)
	}
	if req.To, err = location(*to); err != nil {
		return fmt.Errorf("-to: %w", err)
	}
	if req.TolledShare, err = byCountry(*tolled); err != nil {
		return fmt.Errorf("-tolled-share: %w", err)
	}
	if req.MotorwayShare, err = byCountry(*mway); err != nil {
		return fmt.Errorf("-motorway-share: %w", err)
	}
	if req.FX, err = byCountry(*fxs); err != nil {
		return fmt.Errorf("-fx: %w", err)
	}
	if req.EnvZoneKm, err = byCountry(*zone); err != nil {
		return fmt.Errorf("-env-zone-km: %w", err)
	}
	if req.CompareCO2Classes, err = ints(*cmp); err != nil {
		return fmt.Errorf("-compare: %w", err)
	}
	c, err := calculator(sc)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	res, err := c.Calculate(ctx, req)
	if err != nil {
		return err
	}
	if *asJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		return enc.Encode(res)
	}
	printResult(res)
	return nil
}

// location reads a code (DKCPH, CPH) or "lat,lon".
func location(s string) (sootcase.Location, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return sootcase.Location{}, errors.New("required")
	}
	if lat, lon, ok := strings.Cut(s, ","); ok {
		la, err1 := strconv.ParseFloat(strings.TrimSpace(lat), 64)
		lo, err2 := strconv.ParseFloat(strings.TrimSpace(lon), 64)
		if err1 != nil || err2 != nil || la < -90 || la > 90 || lo < -180 || lo > 180 {
			return sootcase.Location{}, fmt.Errorf("%q is not lat,lon", s)
		}
		return sootcase.Location{Lat: la, Lon: lo}, nil
	}
	return sootcase.Location{Code: strings.ToUpper(s)}, nil
}

// ints reads "1,4,5".
func ints(s string) ([]int, error) {
	if strings.TrimSpace(s) == "" {
		return nil, nil
	}
	var out []int
	for _, f := range strings.Split(s, ",") {
		n, err := strconv.Atoi(strings.TrimSpace(f))
		if err != nil {
			return nil, fmt.Errorf("%q is not a number", f)
		}
		out = append(out, n)
	}
	return out, nil
}

// byCountry reads "DK=1,DE=0.9".
func byCountry(s string) (map[string]float64, error) {
	if strings.TrimSpace(s) == "" {
		return nil, nil
	}
	out := map[string]float64{}
	for _, kv := range strings.Split(s, ",") {
		k, v, ok := strings.Cut(kv, "=")
		f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
		if !ok || err != nil {
			return nil, fmt.Errorf("%q is not COUNTRY=number", kv)
		}
		out[strings.ToUpper(strings.TrimSpace(k))] = f
	}
	return out, nil
}

func printResult(r cost.Response) {
	fmt.Printf("Trip on %s: %.1f km", r.Date, r.DistanceKm)
	if r.FerryKm > 0 {
		fmt.Printf(" (%.1f km by ferry)", r.FerryKm)
	}
	fmt.Println()
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', tabwriter.AlignRight)
	fmt.Fprintln(w, "Charge\tCountry\tPart\tBasis\tRate\tAmount\tEUR\t")
	for _, l := range r.Lines {
		basis := fmt.Sprintf("%.1f km", l.Km)
		if l.TonnesCO2 > 0 {
			basis = fmt.Sprintf("%.3f t CO2e", l.TonnesCO2)
		}
		where := l.Country
		if l.Region != "" {
			where = l.Region
		}
		part := l.Component
		if l.Carbon && part == "" {
			part = "co2"
		}
		if l.Road != "" || l.Area != "" {
			part += " (" + strings.TrimPrefix(l.Road+", "+l.Area, ", ")
			part = strings.TrimSuffix(part, ", ") + ")"
		}
		if l.Section != "" {
			part += ": " + l.Section
		}
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%g %s\t%.2f %s\t%.2f\t\n", l.Charge, where, part, basis, l.Rate, l.RateUnit, l.Amount, l.Currency, l.AmountEUR)
	}
	w.Flush()
	fmt.Printf("Total: EUR %.2f, of which carbon EUR %.2f\n", r.TotalEUR, r.CarbonEUR)
	if len(r.Compare) > 0 {
		fmt.Println()
		w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', tabwriter.AlignRight)
		fmt.Fprintln(w, "CO2 class\tTolls EUR\tTotal EUR\tCarbon EUR\tSaving/trip\tSaving/year\t")
		for _, c := range r.Compare {
			year := ""
			if c.SavingPerYearEUR != 0 {
				year = fmt.Sprintf("%.2f", c.SavingPerYearEUR)
			}
			fmt.Fprintf(w, "%d\t%.2f\t%.2f\t%.2f\t%.2f\t%s\t\n", c.CO2Class, c.TollEUR, c.TotalEUR, c.CarbonEUR, c.SavingEUR, year)
		}
		w.Flush()
	}
	if len(r.NoRates) > 0 {
		fmt.Printf("Not included (no toll table yet): %s\n", strings.Join(r.NoRates, ", "))
	}
	for _, n := range r.Notes {
		fmt.Println("- " + n)
	}
}

func listRates() error {
	tbs, err := rates.All()
	if err != nil {
		return err
	}
	for _, tb := range tbs {
		to := tb.ValidTo
		if to == "" {
			to = "until replaced"
		}
		fmt.Printf("%s  %s  %s to %s  (%s)\n", tb.Area(), tb.Name, tb.ValidFrom, to, tb.Law)
		for _, s := range tb.Sources {
			fmt.Printf("    %s\n    %s\n", s.Title, s.URL)
		}
	}
	return nil
}

func serve(args []string) error {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	sc := sootcaseFlags(fs)
	addr := fs.String("addr", envOr("ADDR", ":8090"), "listen address (env ADDR)")
	tiles := fs.String("tiles", envOr("TILE_URL", DefaultTiles), "map tile URL template, {z}/{x}/{y}; \"none\" for no base map (env TILE_URL)")
	fs.Parse(args)
	c, err := calculator(sc)
	if err != nil {
		return err
	}
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	srv := &http.Server{Addr: *addr, Handler: Handler(c, *tiles), ReadHeaderTimeout: 10 * time.Second}
	log.Info("listening", "addr", *addr, "sootcase", sc.BaseURL)
	return srv.ListenAndServe()
}

//go:embed web/index.html
var indexHTML string

//go:embed web/leaflet
var leafletFS embed.FS

// DefaultTiles is OpenStreetMap's standard tile layer. Its usage policy
// (https://operations.osmfoundation.org/policies/tiles/) allows light use
// with attribution; a busy deployment should set its own tile server.
const DefaultTiles = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

// Handler serves the web page and the HTTP API. tiles is the map's tile
// URL template ("" or "none": no base map).
func Handler(c cost.Calculator, tiles string) http.Handler {
	if tiles == "none" {
		tiles = ""
	}
	imgSrc := "'self' data:"
	if u, err := url.Parse(strings.ReplaceAll(tiles, "{s}", "x")); err == nil && u.Host != "" {
		host := u.Host
		if strings.Contains(tiles, "{s}.") {
			_, rest, _ := strings.Cut(host, ".")
			host = "*." + rest
		}
		imgSrc += " " + u.Scheme + "://" + host
	}
	tj, _ := json.Marshal(tiles)
	page := strings.Replace(indexHTML, "const TILES = \"\";", "const TILES = "+string(tj)+";", 1)
	csp := "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src " + imgSrc +
		"; connect-src 'self'; form-action 'none'; base-uri 'none'"
	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Content-Security-Policy", csp)
		w.Write([]byte(page))
	})
	static, _ := fs.Sub(leafletFS, "web")
	files := http.FileServerFS(static)
	mux.HandleFunc("GET /leaflet/{file}", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "public, max-age=86400")
		files.ServeHTTP(w, r)
	})
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok\n")) })
	mux.HandleFunc("GET /v1/rates", func(w http.ResponseWriter, _ *http.Request) { writeJSON(w, http.StatusOK, c.Tables) })
	mux.HandleFunc("GET /v1/places", func(w http.ResponseWriter, r *http.Request) {
		q := strings.TrimSpace(r.URL.Query().Get("q"))
		if len(q) < 2 || len(q) > 100 {
			writeJSON(w, http.StatusOK, map[string]any{"places": []sootcase.Place{}})
			return
		}
		ps, err := c.Sootcase.Places(r.Context(), q, 8)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
			return
		}
		if ps == nil {
			ps = []sootcase.Place{}
		}
		w.Header().Set("Cache-Control", "public, max-age=86400")
		writeJSON(w, http.StatusOK, map[string]any{"places": ps})
	})
	mux.HandleFunc("POST /v1/carbon-cost", func(w http.ResponseWriter, r *http.Request) {
		var req cost.Request
		dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad JSON: " + err.Error()})
			return
		}
		res, err := c.Calculate(r.Context(), req)
		if err != nil {
			// Bad input (ours or Sootcase's 4xx) is the caller's; anything
			// else from Sootcase is a bad gateway.
			status := http.StatusBadRequest
			if msg := err.Error(); strings.HasPrefix(msg, "sootcase") && !strings.HasPrefix(msg, "sootcase: HTTP 4") {
				status = http.StatusBadGateway
			}
			writeJSON(w, status, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, res)
	})
	return mux
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(v)
}

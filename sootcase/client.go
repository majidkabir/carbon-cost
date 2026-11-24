// Package sootcase calls a Sootcase server (https://sootcase.org,
// github.com/majidkabir/sootcase) for a road leg's route, its distance by
// country and its emissions.
package sootcase

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// DefaultURL is the public Sootcase server.
const DefaultURL = "https://sootcase.org"

// Location is a place: a UN/LOCODE or IATA code, or coordinates.
type Location struct {
	Name string  `json:"name,omitempty"`
	Code string  `json:"code,omitempty"`
	Lat  float64 `json:"lat,omitempty"`
	Lon  float64 `json:"lon,omitempty"`
}

// Shipment is the part of Sootcase's shipment input this tool uses: one
// road leg.
type Shipment struct {
	ID       string  `json:"id"`
	WeightKg float64 `json:"weight_kg"`
	Legs     []Leg   `json:"legs"`
	// AddRoadLegs false: the leg is the whole trip.
	AddRoadLegs *bool `json:"add_road_legs,omitempty"`
}

// Leg is a Sootcase leg.
type Leg struct {
	ID          string   `json:"id"`
	Mode        string   `json:"mode"`
	VehicleType string   `json:"vehicle_type"`
	From        Location `json:"from"`
	To          Location `json:"to"`
	// Vehicle keeps the route to roads the truck may drive (Sootcase
	// v0.15.0): every field optional.
	Vehicle *Vehicle `json:"vehicle,omitempty"`
}

// Vehicle is the truck's size, weight and dangerous goods, for routing.
type Vehicle struct {
	HeightM       float64 `json:"height_m,omitempty"`
	WidthM        float64 `json:"width_m,omitempty"`
	LengthM       float64 `json:"length_m,omitempty"`
	GrossWeightKg float64 `json:"gross_weight_kg,omitempty"`
	AxleLoadKg    float64 `json:"axle_load_kg,omitempty"`
	Axles         int     `json:"axles,omitempty"`
	Hazmat        bool    `json:"hazmat,omitempty"`
	TunnelCode    string  `json:"tunnel_code,omitempty"`
}

// Part is a part of a leg calculated separately, e.g. a ferry crossing.
type Part struct {
	Kind       string  `json:"kind"`
	DistanceKm float64 `json:"distance_km"`
	TTWKg      float64 `json:"ttw_kg"`
	WTWKg      float64 `json:"wtw_kg"`
}

// LegResult is the part of Sootcase's leg result this tool uses.
type LegResult struct {
	DistanceKm float64            `json:"distance_km"`
	TTWKg      float64            `json:"ttw_kg"`
	WTWKg      float64            `json:"wtw_kg"`
	RouteParts map[string]float64 `json:"route_parts_km"`
	CountryKm  map[string]float64 `json:"country_km"`
	// RegionKm splits some countries' km by region (ISO 3166-2, e.g.
	// BE-VLG), where tolls differ by region. CountryKm still has the
	// whole country.
	RegionKm map[string]float64 `json:"region_km"`
	// Path is the route as [lon, lat] points, every point of it (asked
	// for with path=full): toll stations, gantries and sections are found
	// along it, some within 30 m, which a thinned line misses on curves.
	Path [][2]float64 `json:"path"`
	// CountrySections are the leg's stretches by country in route order,
	// km from the leg's start (when Sootcase gives them).
	CountrySections []CountrySection `json:"country_sections,omitempty"`
	// Restrictions is what Sootcase applied of the leg's vehicle.
	Restrictions map[string]any `json:"restrictions,omitempty"`
	Parts        []Part         `json:"parts"`
	// ID names an alternative route (alt1, alt2, ...; Sootcase v0.14.0).
	ID string `json:"id,omitempty"`
	// Summary is what tells the route apart: its main roads and ferries.
	Summary *RouteSummary `json:"summary,omitempty"`
	// DurationH is its driving time at truck speeds, ferries included,
	// when Sootcase gives it.
	DurationH float64 `json:"duration_h,omitempty"`
	// Alternatives are other routes of the leg (asked for with
	// alternatives=N), each with the fields above.
	Alternatives []LegResult `json:"alternatives,omitempty"`
}

// RouteSummary is a route's main roads (OSM refs) and its ferries.
type RouteSummary struct {
	Roads   []string   `json:"roads,omitempty"`
	Ferries []FerryUse `json:"ferries"`
}

// FerryUse is a ferry a route takes.
type FerryUse struct {
	Name       string  `json:"name,omitempty"`
	From       string  `json:"from,omitempty"`
	To         string  `json:"to,omitempty"`
	DistanceKm float64 `json:"distance_km,omitempty"`
}

// Options ask Sootcase for more than its one route.
type Options struct {
	// Alternatives is how many routes a leg may come back with, 1 to 5
	// (the primary and up to N-1 others); 0 or 1: the primary only.
	Alternatives int
	// AvoidFerries routes on land only.
	AvoidFerries bool
}

// Result is the part of Sootcase's result this tool uses.
type Result struct {
	Legs  []LegResult `json:"legs"`
	TTWKg float64     `json:"ttw_kg"`
	WTWKg float64     `json:"wtw_kg"`
	// Dataset names Sootcase's emission factor dataset, when it says.
	Dataset string `json:"dataset,omitempty"`
	// Warnings are Sootcase's notes on what may make its result too low.
	Warnings []string `json:"warnings,omitempty"`
}

// Client calls a Sootcase server.
type Client struct {
	BaseURL string // default DefaultURL
	APIKey  string // optional; sent as a bearer token
	HTTP    *http.Client
}

// Calculate calculates a shipment with each leg's distance by country
// (?country_km=true, Sootcase v0.9.0 or later) and its route
// (path=full).
func (c Client) Calculate(ctx context.Context, s Shipment) (Result, error) {
	return c.CalculateWith(ctx, s, Options{})
}

// CalculateWith is Calculate with alternative routes or without ferries
// (alternatives=N, avoid=ferries: Sootcase v0.14.0 or later).
func (c Client) CalculateWith(ctx context.Context, s Shipment, o Options) (Result, error) {
	body, err := json.Marshal(s)
	if err != nil {
		return Result{}, err
	}
	base := strings.TrimRight(c.BaseURL, "/")
	if base == "" {
		base = DefaultURL
	}
	q := "country_km=true&path=full"
	if o.Alternatives > 1 {
		q += "&alternatives=" + strconv.Itoa(o.Alternatives)
	}
	if o.AvoidFerries {
		q += "&avoid=ferries"
	}
	raw, err := c.do(ctx, http.MethodPost, base+"/v1/calculate?"+q, body)
	if err != nil {
		return Result{}, err
	}
	var r Result
	if err := json.Unmarshal(raw, &r); err != nil {
		return Result{}, fmt.Errorf("sootcase: unreadable result: %w", err)
	}
	return r, nil
}

// Place is one match from Sootcase's place search (GET /v1/places).
type Place struct {
	ID          string   `json:"id"`
	Code        string   `json:"code,omitempty"`
	Kinds       []string `json:"kinds,omitempty"`
	Name        string   `json:"name"`
	AltName     string   `json:"alt_name,omitempty"`
	Region      string   `json:"region,omitempty"`
	Country     string   `json:"country,omitempty"`
	CountryName string   `json:"country_name,omitempty"`
	Lat         float64  `json:"lat"`
	Lon         float64  `json:"lon"`
}

// Places finds cities, ports, terminals and airports by name or code,
// best match first.
func (c Client) Places(ctx context.Context, q string, limit int) ([]Place, error) {
	base := strings.TrimRight(c.BaseURL, "/")
	if base == "" {
		base = DefaultURL
	}
	v := url.Values{"q": {q}, "limit": {strconv.Itoa(limit)}}
	raw, err := c.do(ctx, http.MethodGet, base+"/v1/places?"+v.Encode(), nil)
	if err != nil {
		return nil, err
	}
	var r struct {
		Places []Place `json:"places"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, fmt.Errorf("sootcase: unreadable places: %w", err)
	}
	return r.Places, nil
}

// do sends one request and returns the body of a 200 answer.
func (c Client) do(ctx context.Context, method, u string, body []byte) ([]byte, error) {
	var rd io.Reader
	if body != nil {
		rd = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, u, rd)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.APIKey)
	}
	hc := c.HTTP
	if hc == nil {
		hc = &http.Client{Timeout: 60 * time.Second}
	}
	resp, err := hc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("sootcase: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 32<<20))
	if err != nil {
		return nil, fmt.Errorf("sootcase: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		var e struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(raw, &e)
		if e.Error == "" {
			e.Error = strings.TrimSpace(string(raw))
		}
		if len(e.Error) > 300 {
			e.Error = e.Error[:300] + "…"
		}
		return nil, &HTTPError{Status: resp.StatusCode, Message: e.Error}
	}
	return raw, nil
}

// HTTPError is a Sootcase answer other than 200.
type HTTPError struct {
	Status  int
	Message string
}

func (e *HTTPError) Error() string { return fmt.Sprintf("sootcase: HTTP %d: %s", e.Status, e.Message) }

// CallerError says whether Sootcase refused the request itself (bad
// input: 400, 404, 422), rather than failing or refusing this server.
func (e *HTTPError) CallerError() bool {
	return e.Status == 400 || e.Status == 404 || e.Status == 422
}

// CountrySection is a stretch of a leg in one country, or a ferry
// crossing (Ferry, with no country or the flag state).
type CountrySection struct {
	Country string  `json:"country"`
	FromKm  float64 `json:"from_km"`
	ToKm    float64 `json:"to_km"`
	Ferry   bool    `json:"ferry,omitempty"`
	// Regions are its first-level regions (ISO 3166-2) in route order,
	// where Sootcase knows them.
	Regions []RegionSection `json:"regions,omitempty"`
}

// RegionSection is a stretch of a country section in one region.
type RegionSection struct {
	Region string  `json:"region"`
	FromKm float64 `json:"from_km"`
	ToKm   float64 `json:"to_km"`
}

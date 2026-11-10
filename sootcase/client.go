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
	// Path is the route as [lon, lat] points (asked for with
	// path=detailed), to tell which ferry crossing it uses.
	Path  [][2]float64 `json:"path"`
	Parts []Part       `json:"parts"`
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
// (path=detailed, at most 1,000 points).
func (c Client) Calculate(ctx context.Context, s Shipment) (Result, error) {
	body, err := json.Marshal(s)
	if err != nil {
		return Result{}, err
	}
	base := strings.TrimRight(c.BaseURL, "/")
	if base == "" {
		base = DefaultURL
	}
	raw, err := c.do(ctx, http.MethodPost, base+"/v1/calculate?country_km=true&path=detailed", body)
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
		return nil, fmt.Errorf("sootcase: HTTP %d: %s", resp.StatusCode, e.Error)
	}
	return raw, nil
}

package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math"
	"os"
	"slices"
	"sort"
	"strings"
	"time"
)

// rFMS is the truck makers' common API for fleet data (rFMS vehicle data
// 4.0.0, FMS-Standard, 2021-09-17, and its rFMS_4_0.yaml). From its
// /vehiclepositions and /vehiclestatuses responses for the trip's hours
// the trip takes the way driven (gnssPosition), the diesel burnt
// (engineTotalFuelUsed, "the total fuel the vehicle has used during its
// lifetime in MilliLitres"), an electric truck's energy
// (totalElectricEnergyUsed, in Wh) and the odometer km
// (hrTotalVehicleDistance, in meter).
type rfmsTrip struct {
	VIN        string
	Path       [][2]float64
	DieselL    float64 // last engineTotalFuelUsed minus the first, litres
	KWh        float64 // last totalElectricEnergyUsed minus the first (Wh), kWh
	OdometerKm float64 // last hrTotalVehicleDistance minus the first
	Positions  int
	Statuses   int
	From, To   time.Time
	Notes      []string
}

type rfmsGNSS struct {
	Latitude         *float64 `json:"latitude"`
	Longitude        *float64 `json:"longitude"`
	PositionDateTime string   `json:"positionDateTime"`
}

type rfmsRecord struct {
	VIN      string    `json:"vin"`
	Created  string    `json:"createdDateTime"`
	GNSS     *rfmsGNSS `json:"gnssPosition"`
	Distance *int64    `json:"hrTotalVehicleDistance"`
	Fuel     *int64    `json:"engineTotalFuelUsed"`
	Gaseous  *int64    `json:"totalFuelUsedGaseous"`
	Electric *int64    `json:"totalElectricEnergyUsed"`
	Snapshot *struct {
		GNSS *rfmsGNSS `json:"gnssPosition"`
	} `json:"snapshotData"`
}

type rfmsPage struct {
	Positions *struct {
		List []rfmsRecord `json:"vehiclePositions"`
	} `json:"vehiclePositionResponse"`
	Statuses *struct {
		List []rfmsRecord `json:"vehicleStatuses"`
	} `json:"vehicleStatusResponse"`
	MoreDataAvailable bool `json:"moreDataAvailable"`
}

// isRFMS tells an rFMS response from other JSON.
func isRFMS(b []byte) bool {
	return bytes.Contains(b, []byte(`"vehiclePositionResponse"`)) || bytes.Contains(b, []byte(`"vehicleStatusResponse"`))
}

// readRFMS reads rFMS responses, one or a JSON array of them a file.
func readRFMS(names []string, vin string) (rfmsTrip, error) {
	var docs [][]byte
	for _, n := range names {
		b, err := os.ReadFile(n)
		if err != nil {
			return rfmsTrip{}, err
		}
		docs = append(docs, b)
	}
	return parseRFMS(docs, vin)
}

func parseRFMS(docs [][]byte, vin string) (rfmsTrip, error) {
	var pages []rfmsPage
	for i, b := range docs {
		b = bytes.TrimSpace(b)
		if !isRFMS(b) {
			return rfmsTrip{}, fmt.Errorf("file %d: not an rFMS vehiclepositions or vehiclestatuses response", i+1)
		}
		if len(b) > 0 && b[0] == '[' {
			var ps []rfmsPage
			if err := json.Unmarshal(b, &ps); err != nil {
				return rfmsTrip{}, fmt.Errorf("file %d: %w", i+1, err)
			}
			pages = append(pages, ps...)
			continue
		}
		var p rfmsPage
		if err := json.Unmarshal(b, &p); err != nil {
			return rfmsTrip{}, fmt.Errorf("file %d: %w", i+1, err)
		}
		pages = append(pages, p)
	}
	var pos, st []rfmsRecord
	partial := false
	for _, p := range pages {
		if p.Positions != nil {
			pos = append(pos, p.Positions.List...)
		}
		if p.Statuses != nil {
			st = append(st, p.Statuses.List...)
		}
		partial = partial || p.MoreDataAvailable
	}
	vins := map[string]bool{}
	for _, r := range slices.Concat(pos, st) {
		vins[r.VIN] = true
	}
	if vin == "" {
		if len(vins) > 1 {
			return rfmsTrip{}, fmt.Errorf("vehicles %s: say which with -vin", strings.Join(slices.Sorted(maps.Keys(vins)), ", "))
		}
		for v := range vins {
			vin = v
		}
	} else if !vins[vin] {
		return rfmsTrip{}, fmt.Errorf("no records for VIN %s", vin)
	}
	out := rfmsTrip{VIN: vin}
	if partial {
		out.Notes = append(out.Notes, "a response has moreDataAvailable: its next pages aren't in the files")
	}

	type pt struct {
		t   time.Time
		lon float64
		lat float64
	}
	var pts []pt
	add := func(r rfmsRecord, g *rfmsGNSS) error {
		if g == nil || g.Latitude == nil || g.Longitude == nil {
			return nil
		}
		if math.Abs(*g.Latitude) > 90 || math.Abs(*g.Longitude) > 180 {
			return fmt.Errorf("position %v,%v: not WGS84", *g.Latitude, *g.Longitude)
		}
		t, err := rfmsTime(g.PositionDateTime, r.Created)
		if err != nil {
			return err
		}
		pts = append(pts, pt{t, *g.Longitude, *g.Latitude})
		return nil
	}
	type reading struct {
		t    time.Time
		fuel *int64
		dist *int64
		wh   *int64
	}
	var reads []reading
	gaseous := false
	for _, r := range pos {
		if r.VIN != vin {
			continue
		}
		out.Positions++
		if err := add(r, r.GNSS); err != nil {
			return out, err
		}
	}
	for _, r := range st {
		if r.VIN != vin {
			continue
		}
		out.Statuses++
		if r.Snapshot != nil {
			if err := add(r, r.Snapshot.GNSS); err != nil {
				return out, err
			}
		}
		t, err := rfmsTime(r.Created, "")
		if err != nil {
			return out, err
		}
		reads = append(reads, reading{t, r.Fuel, r.Distance, r.Electric})
		gaseous = gaseous || (r.Fuel == nil && (r.Gaseous != nil || r.Electric != nil))
	}
	sort.SliceStable(pts, func(i, j int) bool { return pts[i].t.Before(pts[j].t) })
	for _, p := range pts {
		q := [2]float64{p.lon, p.lat}
		if n := len(out.Path); n > 0 && out.Path[n-1] == q {
			continue
		}
		out.Path = append(out.Path, q)
	}
	if len(pts) > 0 {
		out.From, out.To = pts[0].t, pts[len(pts)-1].t
	}
	sort.SliceStable(reads, func(i, j int) bool { return reads[i].t.Before(reads[j].t) })
	if len(reads) > 0 {
		if out.From.IsZero() || reads[0].t.Before(out.From) {
			out.From = reads[0].t
		}
		if last := reads[len(reads)-1].t; last.After(out.To) {
			out.To = last
		}
	}
	delta := func(get func(reading) *int64, name string) (float64, error) {
		var first, last *int64
		for _, r := range reads {
			v := get(r)
			if v == nil {
				continue
			}
			if last != nil && *v < *last {
				return 0, fmt.Errorf("%s goes down from %d to %d at %s: the counter was reset; give the trip's hours after it", name, *last, *v, r.t.Format(time.RFC3339))
			}
			if first == nil {
				first = v
			}
			last = v
		}
		if first == nil || first == last {
			return 0, nil
		}
		return float64(*last - *first), nil
	}
	ml, err := delta(func(r reading) *int64 { return r.fuel }, "engineTotalFuelUsed")
	if err != nil {
		return out, err
	}
	m, err := delta(func(r reading) *int64 { return r.dist }, "hrTotalVehicleDistance")
	if err != nil {
		return out, err
	}
	wh, err := delta(func(r reading) *int64 { return r.wh }, "totalElectricEnergyUsed")
	if err != nil {
		return out, err
	}
	out.DieselL, out.OdometerKm, out.KWh = ml/1000, m/1000, wh/1000
	if out.DieselL == 0 && out.KWh == 0 && gaseous {
		out.Notes = append(out.Notes, "no engineTotalFuelUsed (a gas truck): the fuel isn't taken from rFMS")
	}
	if out.Statuses > 0 && out.DieselL == 0 && out.KWh == 0 && !gaseous {
		out.Notes = append(out.Notes, "engineTotalFuelUsed needs two statuses of the trip, at its start and end")
	}
	if len(out.Path) < 2 && out.DieselL == 0 && out.KWh == 0 {
		return out, errors.New("neither 2 positions nor 2 fuel readings for the vehicle")
	}
	return out, nil
}

func rfmsTime(s, fallback string) (time.Time, error) {
	if s == "" {
		s = fallback
	}
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		return t, fmt.Errorf("time %q: give ISO 8601 in UTC (rFMS 4.0 section 4)", s)
	}
	return t.UTC(), nil
}

// summary is one line on what the trip took from rFMS.
func (r rfmsTrip) summary() string {
	s := fmt.Sprintf("rFMS: VIN %s, %s to %s UTC", r.VIN, r.From.Format("2006-01-02 15:04"), r.To.Format("2006-01-02 15:04"))
	if len(r.Path) >= 2 {
		s += fmt.Sprintf(", %d positions", len(r.Path))
	}
	if r.DieselL > 0 {
		s += fmt.Sprintf(", %.1f l diesel (engineTotalFuelUsed)", r.DieselL)
	}
	if r.KWh > 0 {
		s += fmt.Sprintf(", %.1f kWh (totalElectricEnergyUsed)", r.KWh)
	}
	if r.OdometerKm > 0 {
		s += fmt.Sprintf(", odometer %.1f km", r.OdometerKm)
	}
	for _, n := range r.Notes {
		s += "; " + n
	}
	return s
}

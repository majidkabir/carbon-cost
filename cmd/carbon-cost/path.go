package main

import (
	"bytes"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"os"
)

// readPath reads the way driven from a GPX file (its track points, else
// its route points) or JSON: [[lon, lat], ...] or a GeoJSON LineString,
// Feature or FeatureCollection of them, joined in order.
func readPath(name string) ([][2]float64, error) {
	b, err := os.ReadFile(name)
	if err != nil {
		return nil, err
	}
	return parsePath(b)
}

func parsePath(b []byte) ([][2]float64, error) {
	b = bytes.TrimSpace(b)
	if len(b) == 0 {
		return nil, errors.New("empty")
	}
	if b[0] == '<' {
		var g struct {
			Trk []struct {
				Seg []struct {
					Pt []gpxPt `xml:"trkpt"`
				} `xml:"trkseg"`
			} `xml:"trk"`
			Rte []struct {
				Pt []gpxPt `xml:"rtept"`
			} `xml:"rte"`
		}
		if err := xml.Unmarshal(b, &g); err != nil {
			return nil, fmt.Errorf("GPX: %w", err)
		}
		var out [][2]float64
		for _, t := range g.Trk {
			for _, s := range t.Seg {
				for _, p := range s.Pt {
					out = append(out, [2]float64{p.Lon, p.Lat})
				}
			}
		}
		if len(out) == 0 {
			for _, r := range g.Rte {
				for _, p := range r.Pt {
					out = append(out, [2]float64{p.Lon, p.Lat})
				}
			}
		}
		if len(out) < 2 {
			return nil, errors.New("GPX: fewer than 2 track or route points")
		}
		return out, nil
	}
	var plain [][]float64
	if err := json.Unmarshal(b, &plain); err == nil {
		return lonLats(plain)
	}
	var g geo
	if err := json.Unmarshal(b, &g); err != nil {
		return nil, fmt.Errorf("give GPX, [[lon, lat], ...] or a GeoJSON LineString: %w", err)
	}
	var out [][2]float64
	var walk func(g geo) error
	walk = func(g geo) error {
		switch g.Type {
		case "FeatureCollection":
			for _, f := range g.Features {
				if err := walk(f); err != nil {
					return err
				}
			}
		case "Feature":
			if g.Geometry == nil {
				return nil
			}
			return walk(*g.Geometry)
		case "LineString":
			var c [][]float64
			if err := json.Unmarshal(g.Coordinates, &c); err != nil {
				return err
			}
			pts, err := lonLats(c)
			if err != nil {
				return err
			}
			out = append(out, pts...)
		case "MultiLineString":
			var cs [][][]float64
			if err := json.Unmarshal(g.Coordinates, &cs); err != nil {
				return err
			}
			for _, c := range cs {
				pts, err := lonLats(c)
				if err != nil {
					return err
				}
				out = append(out, pts...)
			}
		}
		return nil
	}
	if err := walk(g); err != nil {
		return nil, fmt.Errorf("GeoJSON: %w", err)
	}
	if len(out) < 2 {
		return nil, errors.New("GeoJSON: no LineString of 2 points or more")
	}
	return out, nil
}

type gpxPt struct {
	Lat float64 `xml:"lat,attr"`
	Lon float64 `xml:"lon,attr"`
}

type geo struct {
	Type        string          `json:"type"`
	Features    []geo           `json:"features"`
	Geometry    *geo            `json:"geometry"`
	Coordinates json.RawMessage `json:"coordinates"`
}

func lonLats(c [][]float64) ([][2]float64, error) {
	out := make([][2]float64, 0, len(c))
	for i, p := range c {
		if len(p) < 2 {
			return nil, fmt.Errorf("point %d: give [lon, lat]", i)
		}
		out = append(out, [2]float64{p[0], p[1]})
	}
	return out, nil
}

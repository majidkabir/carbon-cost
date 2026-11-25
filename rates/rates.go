// Package rates holds what a toll depends on and the names carbon-cost's
// lines use: the truck, places, sources, components and road types. The
// rates themselves are ORCT datasets (package tariffs).
package rates

import (
	"fmt"
	"strconv"
	"strings"
)

// Component names. CO2 is the carbon part of a toll.
const (
	Infrastructure   = "infrastructure"
	Toll             = "toll" // one rate with no legal split
	CO2              = "co2"
	Air              = "air"
	Noise            = "noise"
	AirNoise         = "air_noise"
	EnvZoneSurcharge = "env_zone_surcharge"
)

// Areas for rates that differ by suburban or interurban road.
const (
	Suburban   = "suburban"
	Interurban = "interurban"
)

// Road types for rates that differ by road.
const (
	Motorway  = "motorway"
	OtherRoad = "other"
)

// Source is a document the rates come from.
type Source struct {
	// Title names the document (a law, a table, a dataset), and URL is
	// where it is published.
	Title string `json:"title"`
	URL   string `json:"url"`
}

// Place is a point on a road.
type Place struct {
	Name string  `json:"name"`
	Lat  float64 `json:"lat"`
	Lon  float64 `json:"lon"`
	// Heading, for a closed system's station point: the direction of
	// travel (degrees clockwise from north) in which a route passes it.
	Heading *float64 `json:"heading,omitempty"`
}

// Truck is what a toll rate depends on.
type Truck struct {
	MaxMassKg int `json:"max_mass_kg"` // technically permissible maximum mass
	Axles     int `json:"axles"`       // of the truck with its trailer
	// MotorAxles is the motor vehicle's own axles, optional: Lithuania's
	// charge counts those (a tractor's, without the semi-trailer's).
	MotorAxles int `json:"motor_axles,omitempty"`
	// MotorMassKg and TrailerMassKg are the motor vehicle's and the
	// trailer's own technically permissible maximum mass, optional:
	// Iceland's km fee charges each vehicle of a combination on its own.
	// They need MotorAxles.
	MotorMassKg   int `json:"motor_mass_kg,omitempty"`
	TrailerMassKg int `json:"trailer_mass_kg,omitempty"`
	Euro          int `json:"euro"`      // emission standard 0-6 (EEV counts as 5)
	CO2Class      int `json:"co2_class"` // EU CO2 emission class 1-5 (5 = zero-emission)
	// TareKg is the truck's own weight (with trailer), optional: ferries
	// report freight emissions per tonne of vehicle and cargo.
	TareKg int `json:"tare_kg,omitempty"`
	// LengthM is the vehicle's length with trailer, optional: bridge tolls
	// are priced by length (default DefaultLengthM).
	LengthM float64 `json:"length_m,omitempty"`
	// CapacityKg is the load capacity (permissible mass less the mass in
	// running order) a ferry charges by, optional: the semi-trailer's for a
	// tractor with semi-trailer, else the truck's and its trailer's
	// together. Croatia's state ferries charge goods vehicles with more than
	// 5 t of it a fare per tonne of it.
	CapacityKg int `json:"capacity_kg,omitempty"`
	// HeightM, WidthM, AxleLoadKg, Hazmat and ADRTunnelCode (B, C, D or
	// E, the load's tunnel restriction code under ADR 1.9.5; it implies
	// Hazmat) are optional: with any of them, the route keeps to roads
	// the truck may drive (Sootcase's vehicle), its length and weight too.
	HeightM       float64 `json:"height_m,omitempty"`
	WidthM        float64 `json:"width_m,omitempty"`
	AxleLoadKg    int     `json:"axle_load_kg,omitempty"`
	Hazmat        bool    `json:"hazmat,omitempty"`
	ADRTunnelCode string  `json:"adr_tunnel_code,omitempty"`
}

// Restricted says the truck's route is to keep to roads it may drive.
func (t Truck) Restricted() bool {
	return t.HeightM > 0 || t.WidthM > 0 || t.AxleLoadKg > 0 || t.Hazmat || t.ADRTunnelCode != ""
}

// DefaultLengthM is the length assumed when a truck's isn't given: a
// tractor with semi-trailer (EU maximum 16.50 m, Directive 96/53/EC).
const DefaultLengthM = 16.5

// Length is the truck's length, DefaultLengthM if not given.
func (t Truck) Length() float64 {
	if t.LengthM > 0 {
		return t.LengthM
	}
	return DefaultLengthM
}

// Validate checks a truck's fields.
func (t Truck) Validate() error {
	switch {
	case t.MaxMassKg <= 0:
		return fmt.Errorf("max_mass_kg must be > 0")
	case t.Axles < 2 || t.Axles > 10:
		return fmt.Errorf("axles must be 2-10")
	case t.MotorAxles != 0 && (t.MotorAxles < 2 || t.MotorAxles > t.Axles):
		return fmt.Errorf("motor_axles must be 2 to axles")
	case t.Euro < 0 || t.Euro > 6:
		return fmt.Errorf("euro must be 0-6")
	case t.CO2Class < 1 || t.CO2Class > 5:
		return fmt.Errorf("co2_class must be 1-5")
	case t.TareKg < 0 || (t.TareKg > 0 && t.TareKg >= t.MaxMassKg):
		return fmt.Errorf("tare_kg must be >= 0 and below max_mass_kg")
	case t.LengthM < 0 || t.LengthM > 50:
		return fmt.Errorf("length_m must be 0-50")
	case t.CapacityKg < 0 || t.CapacityKg > t.MaxMassKg:
		return fmt.Errorf("capacity_kg must be 0 to max_mass_kg")
	case t.MotorMassKg < 0 || t.MotorMassKg > t.MaxMassKg || t.TrailerMassKg < 0 || t.TrailerMassKg > t.MaxMassKg:
		return fmt.Errorf("motor_mass_kg and trailer_mass_kg must be 0 to max_mass_kg")
	case (t.MotorMassKg > 0 || t.TrailerMassKg > 0) && t.MotorAxles == 0:
		return fmt.Errorf("motor_axles is needed with motor_mass_kg or trailer_mass_kg")
	case t.TrailerMassKg > 0 && t.MotorAxles == t.Axles:
		return fmt.Errorf("trailer_mass_kg needs a trailer: motor_axles below axles")
	}
	return nil
}

// ValidTime checks an HH:MM time.
func ValidTime(s string) error {
	h, m, ok := strings.Cut(s, ":")
	hh, err1 := strconv.Atoi(h)
	mm, err2 := strconv.Atoi(m)
	if !ok || err1 != nil || err2 != nil || hh < 0 || hh > 23 || mm < 0 || mm > 59 {
		return fmt.Errorf("bad time %q (HH:MM)", s)
	}
	return nil
}

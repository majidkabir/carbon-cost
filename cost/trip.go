package cost

import (
	"fmt"
	"math"
	"regexp"
	"strings"

	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/sootcase"
)

// MaxStops is the most stops a trip may have.
const MaxStops = 25

var ccRE = regexp.MustCompile(`^[A-Z]{2}$`)

// Shipment is cargo on the trip: loaded at one stop and unloaded at a
// later one. The truck pays the trip's charges; each shipment's share of
// them is its tonne-km over all the shipments' (EN ISO 14083:2023, the
// method of Regulation (EU) 2026/1030, CountEmissionsEU).
type Shipment struct {
	// ID names it in the result; default its number, from 1.
	ID string `json:"id,omitempty"`
	// WeightKg is its gross mass.
	WeightKg float64 `json:"weight_kg"`
	// From is the stop it is loaded at, 0 being the first.
	From int `json:"from,omitempty"`
	// To is the stop it is unloaded at; 0 means the last.
	To int `json:"to,omitempty"`
}

// FuelPurchase is fuel bought for the trip in a country, for the
// national CO2 prices on fuel, which are paid where it is bought.
type FuelPurchase struct {
	Country string  `json:"country"` // ISO 3166-1 alpha-2
	Litres  float64 `json:"litres"`
}

// Trip is the truck's trip: its legs between stops, what was on board,
// and the diesel it burned, on which the CO2 prices on fuel and ETS2 are
// charged.
type Trip struct {
	Legs []TripLeg `json:"legs"`
	// RoadKm is the km on the road (not on ferries).
	RoadKm float64 `json:"road_km"`
	// EmptyKm is the road km with nothing on board.
	EmptyKm float64 `json:"empty_km,omitempty"`
	// FuelL is the litres of diesel on the road.
	FuelL float64 `json:"fuel_l"`
	// FuelBasis says where FuelL comes from: diesel_l, fuel_purchases,
	// l_per_100km, or the default by vehicle group and load.
	FuelBasis string `json:"fuel_basis"`
	// Hours is the trip's driving time: Sootcase's at truck speeds
	// (ferries included) where it gives it, else the road km at
	// avg_speed_kmh; HoursBasis says which. ElapsedH, with driver_rest,
	// adds a single driver's breaks and daily rests (Regulation (EC) No
	// 561/2006, Arts. 6-8).
	Hours      float64 `json:"hours"`
	HoursBasis string  `json:"hours_basis"`
	ElapsedH   float64 `json:"elapsed_h,omitempty"`
}

// TripLeg is the trip between two consecutive stops.
type TripLeg struct {
	From   int     `json:"from"`
	To     int     `json:"to"`
	Km     float64 `json:"km"`
	RoadKm float64 `json:"road_km"`
	LoadKg float64 `json:"load_kg"`
	FuelL  float64 `json:"fuel_l"`
}

// ShipmentCost is a shipment's share of the trip.
type ShipmentCost struct {
	ID       string  `json:"id"`
	WeightKg float64 `json:"weight_kg"`
	From     int     `json:"from"`
	To       int     `json:"to"`
	// DistanceKm is its transport activity distance: the road route from
	// its loading stop to its unloading stop (EN ISO 14083's shortest
	// feasible distance), not the truck's way between them.
	DistanceKm float64 `json:"distance_km"`
	TKm        float64 `json:"tkm"`
	// Share is its tonne-km over all the shipments'.
	Share     float64 `json:"share"`
	TotalEUR  float64 `json:"total_eur"`
	CarbonEUR float64 `json:"carbon_eur"`
	// ByCharge is its share of each kind of charge, in EUR.
	ByCharge map[string]float64 `json:"by_charge"`
	// ByCountry is its share of the charges of each country (a line's
	// country: where a toll or tax is paid; a ferry's ETS, paid to no
	// country, under its charge), in EUR: what an invoice passing the
	// tolls on by country needs.
	ByCountry map[string]float64 `json:"by_country"`
	// EURPer100Kg and CarbonEURPer100Kg are its amounts per 100 kg, as
	// surcharges are quoted.
	EURPer100Kg       float64 `json:"eur_per_100kg"`
	CarbonEURPer100Kg float64 `json:"carbon_eur_per_100kg"`
	// FuelEUR, WithFuelEUR and TripCostEUR are its tonne-km share of the
	// trip's fuel, with_fuel_eur and trip_cost_eur.
	FuelEUR     float64 `json:"fuel_eur,omitempty"`
	WithFuelEUR float64 `json:"with_fuel_eur,omitempty"`
	TripCostEUR float64 `json:"trip_cost_eur,omitempty"`
	// TTWKg and WTWKg are its emissions, kg CO2e: its tonne-km share of
	// the truck's diesel plus its share by weight of the ferries it is on,
	// when the diesel is given; else Sootcase's (GLEC default intensity x
	// its tonne-km).
	TTWKg float64 `json:"ttw_kg"`
	WTWKg float64 `json:"wtw_kg"`
	// IntensityG is its well-to-wheel g CO2e per tonne-km.
	IntensityG float64 `json:"intensity_g_co2e_per_tkm"`
}

// stops is the request's stops: stops, or from and to.
func (r Request) stops() []sootcase.Location {
	if len(r.Stops) > 0 {
		return r.Stops
	}
	return []sootcase.Location{r.From, r.To}
}

// shipments is the request's shipments, with their stops resolved: the
// shipments given, or cargo_kg from the first stop to the last.
func (r Request) shipments() []Shipment {
	last := len(r.stops()) - 1
	if len(r.Shipments) == 0 {
		return []Shipment{{ID: "1", WeightKg: r.CargoKg, From: 0, To: last}}
	}
	out := make([]Shipment, len(r.Shipments))
	for i, s := range r.Shipments {
		if s.To == 0 {
			s.To = last
		}
		if s.ID == "" {
			s.ID = fmt.Sprint(i + 1)
		}
		out[i] = s
	}
	return out
}

// legLoads is the load on board on each leg, kg.
func legLoads(ships []Shipment, legs int) []float64 {
	out := make([]float64, legs)
	for _, s := range ships {
		for i := s.From; i < s.To && i < legs; i++ {
			out[i] += s.WeightKg
		}
	}
	return out
}

func checkTrip(r Request) error {
	if len(r.Stops) > 0 && (r.From != (sootcase.Location{}) || r.To != (sootcase.Location{})) {
		return fmt.Errorf("give stops or from and to, not both")
	}
	st := r.stops()
	if len(r.Stops) == 1 || len(st) > MaxStops {
		return fmt.Errorf("stops: give 2 to %d", MaxStops)
	}
	if len(r.Shipments) == 0 {
		if r.CargoKg <= 0 {
			return fmt.Errorf("cargo_kg must be > 0 (or give shipments)")
		}
	} else if r.CargoKg != 0 {
		return fmt.Errorf("give shipments or cargo_kg, not both")
	}
	ids := map[string]bool{}
	for i, s := range r.shipments() {
		if s.WeightKg <= 0 {
			return fmt.Errorf("shipments[%d].weight_kg must be > 0", i)
		}
		if s.From < 0 || s.To <= s.From || s.To >= len(st) {
			return fmt.Errorf("shipments[%d]: from and to must be stops (0-%d), from before to", i, len(st)-1)
		}
		if ids[s.ID] {
			return fmt.Errorf("shipments[%d]: id %q twice", i, s.ID)
		}
		ids[s.ID] = true
	}
	for _, p := range r.FuelPurchases {
		if !ccRE.MatchString(p.Country) || p.Litres <= 0 {
			return fmt.Errorf("fuel_purchases: each needs a country (ISO 3166-1 alpha-2) and litres > 0")
		}
	}
	if r.LPer100Km < 0 || r.LPer100Km > 100 {
		return fmt.Errorf("l_per_100km must be 0-100")
	}
	if r.FuelCountry != "" && len(r.FuelPurchases) > 0 {
		return fmt.Errorf("give fuel_purchases or fuel_country, not both")
	}
	return nil
}

// ---------------------------------------------------------------- fuel

// The default diesel of a truck, by its VECTO vehicle group: the CO2 per
// km the Commission reports for new heavy-duty vehicles (COM(2024) 313,
// reporting period 2021, from VECTO simulations under Regulation (EU)
// 2017/2400). For sub-group 5-LH, the 4x2 tractor with a semi-trailer in
// long haul, Table 6 gives 632 g/km at the low payload and 826 g/km at
// the representative one; their g/tkm (243 and 43) put those payloads
// at 2.6 t and 19.2 t, and the CO2 per km is taken as linear in the load
// through them. For the other groups Table 1's average at its average
// payload is used.
const (
	vectoSource = "COM(2024) 313, the Commission's report on new heavy-duty vehicles' CO2 (VECTO, reporting period 2021)"
	vectoURL    = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52024DC0313"
)

var vecto5LH = struct{ lowT, lowG, refT, refG float64 }{2.6, 632, 19.2, 826}

// vehicleGroup is the truck's VECTO group and its CO2 per km with
// loadT tonnes on board.
func vehicleGroup(t rates.Truck, loadT float64) (string, float64) {
	motor := t.MotorAxles
	if motor == 0 {
		motor = t.Axles
	}
	switch m := t.MaxMassKg; {
	case m > 32000 || (m >= 26000 && t.Axles >= 4 && motor <= 3):
		v := vecto5LH
		return "5-LH (tractor with semi-trailer, long haul)", v.lowG + (math.Max(0, loadT)-v.lowT)*(v.refG-v.lowG)/(v.refT-v.lowT)
	case m > 16000 && motor >= 3:
		return "9-LH (rigid 6x2, long haul; average 13.4 t on board)", 843
	case m > 16000:
		return "4-LH (rigid 4x2, long haul; average 7.4 t on board)", 730
	case m > 12000:
		return "3 (rigid 4x2, 12-16 t; average 3.4 t on board)", 700
	case m > 10000:
		return "2 (rigid 4x2, 10-12 t; average 2.3 t on board)", 627
	default:
		return "1 (rigid 4x2, 7.5-10 t; average 1.4 t on board)", 610
	}
}

// tripFuel is the trip's road diesel, leg by leg: the litres given, or
// bought, or l_per_100km over the road km, or the default by vehicle
// group and load; none for a zero-emission truck.
func tripFuel(legs []TripLeg, req Request) (float64, string) {
	var roadKm float64
	for _, l := range legs {
		roadKm += l.RoadKm
	}
	spread := func(total float64) {
		for i := range legs {
			if roadKm > 0 {
				legs[i].FuelL = round2(total * legs[i].RoadKm / roadKm)
			}
		}
	}
	switch {
	case req.Truck.CO2Class == 5 || req.noFuel:
		return 0, "zero-emission truck (CO2 class 5): no diesel"
	case req.DieselL > 0:
		spread(req.DieselL)
		return req.DieselL, "diesel_l (given)"
	case req.LPer100Km > 0:
		// Burnt at the truck's own rate; fuel_purchases, if given, only say
		// where it was bought.
		spread(roadKm * req.LPer100Km / 100)
		return roadKm * req.LPer100Km / 100, fmt.Sprintf("l_per_100km: %g (given) x %.1f road km", req.LPer100Km, roadKm)
	case len(req.FuelPurchases) > 0:
		var total float64
		for _, p := range req.FuelPurchases {
			total += p.Litres
		}
		spread(total)
		return total, "fuel_purchases (given): the litres bought for the trip"
	}
	var total float64
	var groups []string
	for i, l := range legs {
		g, gkm := vehicleGroup(req.Truck, l.LoadKg/1000)
		litres := gkm * l.RoadKm / (DieselKgCO2PerL * 1000)
		legs[i].FuelL = round2(litres)
		total += litres
		if !containsStr(groups, g) {
			groups = append(groups, g)
		}
	}
	return total, fmt.Sprintf("default: VECTO group %s, by the load on each leg (%s), at %.2f kg CO2 per litre (EN 16258:2012); give l_per_100km or diesel_l for the truck's own",
		strings.Join(groups, ", "), vectoSource, DieselKgCO2PerL)
}

func containsStr(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}

// tripOf is the trip's legs from Sootcase's legs and the loads on them.
func tripOf(res sootcase.Result, req Request) *Trip {
	loads := req.legLoadKg
	tr := &Trip{}
	for i, l := range res.Legs {
		load := req.CargoKg
		if i < len(loads) {
			load = loads[i]
		}
		road := math.Max(0, l.DistanceKm-l.RouteParts["ferry"])
		tr.Legs = append(tr.Legs, TripLeg{From: i, To: i + 1, Km: round3(l.DistanceKm), RoadKm: round3(road), LoadKg: load})
		tr.RoadKm += road
		if load == 0 {
			tr.EmptyKm += road
		}
	}
	tr.FuelL, tr.FuelBasis = tripFuel(tr.Legs, req)
	tr.FuelL, tr.RoadKm, tr.EmptyKm = round2(tr.FuelL), round3(tr.RoadKm), round3(tr.EmptyKm)
	tr.Hours, tr.HoursBasis = tripHours(res, tr.RoadKm, req)
	if req.DriverRest {
		tr.ElapsedH = math.Round(withRest(tr.Hours)*100) / 100
	}
	return tr
}

// tripHours is the trip's driving time, and on what basis.
func tripHours(res sootcase.Result, roadKm float64, req Request) (float64, string) {
	var h float64
	all := len(res.Legs) > 0
	for _, l := range res.Legs {
		if l.DurationH <= 0 {
			all = false
		}
		h += l.DurationH
	}
	if all {
		return math.Round(h*100) / 100, "Sootcase's driving time at truck speeds, ferries included"
	}
	v := req.AvgSpeedKmh
	if v <= 0 {
		v = DefaultAvgSpeedKmh
	}
	return math.Round(roadKm/v*100) / 100, fmt.Sprintf("%.0f road km at %g km/h (avg_speed_kmh); ferry crossings not counted", roadKm, v)
}

// fuelShares is where the trip's fuel is bought: fuel_purchases by their
// litres, fuel_country, or along the route by road km.
func fuelShares(req Request, countryKm map[string]float64) map[string]float64 {
	share := map[string]float64{}
	switch {
	case len(req.FuelPurchases) > 0:
		var total float64
		for _, p := range req.FuelPurchases {
			total += p.Litres
		}
		for _, p := range req.FuelPurchases {
			share[p.Country] += p.Litres / total
		}
	case req.FuelCountry != "":
		share[req.FuelCountry] = 1
	default:
		var total float64
		for _, km := range countryKm {
			total += km
		}
		for cc, km := range countryKm {
			if total > 0 {
				share[cc] = km / total
			}
		}
	}
	return share
}

// ---------------------------------------------------------------- allocation

// allocate shares the trip's charges out to its shipments by tonne-km
// (EN ISO 14083:2023): each shipment's mass x its transport activity
// distance, over all of theirs. A trip's empty running is part of it,
// shared out with the rest.
func allocate(out *Response, res sootcase.Result, req Request) {
	ships := req.shipments()
	dist := make([]float64, len(ships))
	var tkm float64
	for i, s := range ships {
		if i < len(req.shipDistKm) && req.shipDistKm[i] > 0 {
			dist[i] = req.shipDistKm[i]
		} else {
			for j := s.From; j < s.To && j < len(res.Legs); j++ {
				dist[i] += res.Legs[j].DistanceKm
			}
		}
		tkm += s.WeightKg / 1000 * dist[i]
	}
	byCharge, byCountry := map[string]float64{}, map[string]float64{}
	for _, l := range out.Lines {
		byCharge[l.Charge] += l.AmountEUR
		where := l.Country
		if where == "" {
			where = l.Charge // a ferry's ETS, paid to no country
		}
		byCountry[where] += l.AmountEUR
	}
	out.Shipments = nil
	for i, s := range ships {
		t := s.WeightKg / 1000 * dist[i]
		share := 1.0
		if tkm > 0 {
			share = t / tkm
		}
		c := ShipmentCost{ID: s.ID, WeightKg: s.WeightKg, From: s.From, To: s.To, DistanceKm: round3(dist[i]), TKm: round3(t),
			Share: math.Round(share*1e6) / 1e6, TotalEUR: round2(out.TotalEUR * share), CarbonEUR: round2(out.CarbonEUR * share),
			ByCharge: map[string]float64{}, ByCountry: map[string]float64{}}
		for k, v := range byCharge {
			c.ByCharge[k] = round2(v * share)
		}
		for k, v := range byCountry {
			c.ByCountry[k] = round2(v * share)
		}
		if s.WeightKg > 0 {
			c.EURPer100Kg, c.CarbonEURPer100Kg = round2(out.TotalEUR*share*100/s.WeightKg), round2(out.CarbonEUR*share*100/s.WeightKg)
		}
		if energyPriced(out) {
			c.FuelEUR, c.WithFuelEUR = round2(energyEUR(out)*share), round2(out.WithFuelEUR*share)
		}
		c.TripCostEUR = round2(out.TripCostEUR * share)
		if i < len(req.shipTTW) {
			c.TTWKg, c.WTWKg = round3(req.shipTTW[i]), round3(req.shipWTW[i])
		} else if len(ships) == 1 {
			c.TTWKg, c.WTWKg = round3(out.TTWKg), round3(out.WTWKg)
		}
		if t > 0 {
			c.IntensityG = round2(c.WTWKg * 1000 / t)
		}
		out.Shipments = append(out.Shipments, c)
	}
	if tkm > 0 {
		out.IntensityG = round2(out.WTWKg * 1000 / tkm)
		out.EURPerTkm, out.CarbonEURPerTkm = math.Round(out.TotalEUR/tkm*1e4)/1e4, math.Round(out.CarbonEUR/tkm*1e4)/1e4
	}
}

// fuelGiven is whether the request gives the truck's own diesel.
func (r Request) fuelGiven() bool {
	return r.DieselL > 0 || r.LPer100Km > 0 || len(r.FuelPurchases) > 0
}

// tripEmissions sets the trip's emissions. With the truck's own diesel
// (primary data: EN ISO 14083 and Regulation (EU) 2026/1030 put it before
// default values), or with no route (country_km): the road's are the
// litres x EN 16258's factors, shared out by tonne-km, and a ferry's are
// Sootcase's for the load on board, shared by weight among the shipments
// on it. Else they stay Sootcase's. It returns req with the shipments'.
func tripEmissions(out *Response, res sootcase.Result, req Request) Request {
	out.DataType, out.EmissionsBasis = "modelled", "Sootcase: GLEC default intensities x each shipment's tonne-km on its own route"
	if !req.fuelGiven() && len(req.CountryKm) == 0 || out.Trip.FuelL <= 0 {
		return req
	}
	if req.fuelGiven() {
		out.DataType = "primary"
	}
	fuel := out.Trip.FuelL
	roadTTW, roadWTW := fuel*DieselKgCO2PerL, fuel*DieselKgCO2ePerLWTW
	out.EmissionsBasis = fmt.Sprintf("the truck's diesel, %.1f l (%s), x %.2f kg CO2/l tank-to-wheel and %.2f kg CO2e/l well-to-wheel (EN 16258:2012, Table A.1), shared out by tonne-km",
		fuel, out.Trip.FuelBasis, DieselKgCO2PerL, DieselKgCO2ePerLWTW)
	ships := req.shipments()
	dist := make([]float64, len(ships))
	var tkm float64
	for i, s := range ships {
		if i < len(req.shipDistKm) && req.shipDistKm[i] > 0 {
			dist[i] = req.shipDistKm[i]
		} else {
			for j := s.From; j < s.To && j < len(res.Legs); j++ {
				dist[i] += res.Legs[j].DistanceKm
			}
		}
		tkm += s.WeightKg / 1000 * dist[i]
	}
	ttw, wtw := make([]float64, len(ships)), make([]float64, len(ships))
	for i, s := range ships {
		share := 1.0
		if tkm > 0 {
			share = s.WeightKg / 1000 * dist[i] / tkm
		}
		ttw[i], wtw[i] = roadTTW*share, roadWTW*share
	}
	out.TTWKg, out.WTWKg = roadTTW, roadWTW
	var ferry bool
	for j, l := range res.Legs {
		var ft, fw float64
		for _, p := range l.Parts {
			if p.Kind == "ferry" {
				ft, fw = ft+p.TTWKg, fw+p.WTWKg
			}
		}
		if ft == 0 && fw == 0 {
			continue
		}
		ferry = true
		out.TTWKg, out.WTWKg = out.TTWKg+ft, out.WTWKg+fw
		var load float64
		for _, s := range ships {
			if s.From <= j && j < s.To {
				load += s.WeightKg
			}
		}
		for i, s := range ships {
			if s.From <= j && j < s.To && load > 0 {
				ttw[i] += ft * s.WeightKg / load
				wtw[i] += fw * s.WeightKg / load
			}
		}
	}
	if ferry {
		out.EmissionsBasis += "; ferries: Sootcase's for the load on board, shared by weight"
	}
	out.TTWKg, out.WTWKg = round3(out.TTWKg), round3(out.WTWKg)
	req.shipTTW, req.shipWTW = ttw, wtw
	return req
}

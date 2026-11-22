package cost

import (
	"encoding/json"
	"fmt"
	"math"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/majidkabir/carbon-cost/orct"
	"github.com/majidkabir/carbon-cost/rates"
	"github.com/majidkabir/carbon-cost/tariffs"
)

// Tolls are priced from ORCT datasets (package tariffs): the route is
// matched to a dataset's charge objects (its network by road class, its
// stations, toll points, sections, zones) and each use becomes an ORCT
// event; package orct prices the events as the specification says and
// each statement line becomes a Line.

// vehicleOf is the truck as ORCT vehicle parameters.
// Vehicle is a truck as the rate tables' vehicle parameters (ORCT 6.6),
// as the calculator prices it.
func Vehicle(t rates.Truck) map[string]any { return vehicleOf(t) }

func vehicleOf(t rates.Truck) map[string]any {
	axles := t.Axles
	if t.MotorAxles > 0 {
		axles = t.MotorAxles
	}
	// carbon-cost prices road fuel as diesel; a zero-emission truck (CO2
	// class 5) counts as electric.
	energy := "diesel"
	if t.CO2Class == 5 {
		energy = "electric"
	}
	v := map[string]any{"train_mass_kg": float64(t.MaxMassKg), "train_axles": float64(t.Axles), "axles": float64(axles),
		"euro_class": strconv.Itoa(t.Euro), "co2_class": float64(t.CO2Class), "train_length_m": t.Length(), "energy": energy}
	if t.MotorMassKg > 0 {
		v["mass_kg"] = float64(t.MotorMassKg)
	}
	if t.TrailerMassKg > 0 {
		v["trailer_mass_kg"] = float64(t.TrailerMassKg)
	}
	if t.CapacityKg > 0 {
		v["load_capacity_kg"] = float64(t.CapacityKg)
	}
	return v
}

// lineMeta is what a Line takes from the use an event stands for.
type lineMeta struct {
	charge                               string // RoadToll, FerryFare, AreaCharge or FuelCO2
	country, region, road, area, section string
	km, tonnesCO2                        float64
	hasKm                                bool
	// key: the lines of events with the same key and row are one Line (a
	// part's km split by area, a period's days).
	key string
}

// batch is one dataset's events for a trip, priced together.
type batch struct {
	ds     *tariffs.Dataset
	events []orct.Event
	quants []orct.Quantity
}

func stamp(t time.Time) string { return t.Format(time.RFC3339) }

func (b *batch) event(obj string, at time.Time, m *lineMeta) *orct.Event {
	b.events = append(b.events, orct.Event{Dataset: b.ds.ID, Object: obj, Time: stamp(at), Ref: m})
	return &b.events[len(b.events)-1]
}

func (b *batch) km(obj string, at time.Time, km float64, overlays map[string]float64, m *lineMeta) {
	e := b.event(obj, at, m)
	d := orct.FloatStr(km)
	e.Km = &d
	for k, v := range overlays {
		if e.Overlays == nil {
			e.Overlays = map[string]orct.Dec{}
		}
		e.Overlays[k] = orct.FloatStr(v)
	}
}

// pricer prices one trip's tolls.
type pricer struct {
	req     Request
	date    time.Time
	out     *Response
	add     func(Line) error
	vehicle map[string]any
	payment []string
}

func newPricer(req Request, date time.Time, out *Response, add func(Line) error) *pricer {
	p := &pricer{req: req, date: date, out: out, add: add, vehicle: vehicleOf(req.Truck)}
	// The load carried on the trip, for fares per tonne of it (the Elbe
	// ferry's per started 1,000 kg).
	if req.CargoKg > 0 {
		p.vehicle["load_kg"] = req.CargoKg
	}
	if req.ETC {
		p.payment = []string{"electronic"}
	}
	return p
}

func (p *pricer) note(format string, a ...any) {
	p.out.Notes = append(p.out.Notes, fmt.Sprintf(format, a...))
}

// noon is the time an untimed use is priced at: noon local time on the
// trip's date, so day rates apply.
func (p *pricer) noon(ds *tariffs.Dataset) time.Time {
	return time.Date(p.date.Year(), p.date.Month(), p.date.Day(), 12, 0, 0, 0, ds.TZ())
}

// at is when the trip reaches pos km along the route in the dataset's
// country, and whether a departure time was given (else noon).
func (p *pricer) at(ds *tariffs.Dataset, pos float64, country string) (time.Time, bool) {
	if t, ok := passage(p.req, p.date, pos, country); ok {
		return t, true
	}
	return p.noon(ds), false
}

// componentOf is the Line component of an ORCT charge.
func componentOf(ch *orct.Charge) string {
	switch ch.Type {
	case "point", "od", "area":
		return rates.Toll
	}
	if ch.ComponentLabel != "" {
		return ch.ComponentLabel
	}
	switch ch.Component {
	case "infrastructure":
		return rates.Infrastructure
	case "air_pollution":
		return rates.Air
	case "noise":
		return rates.Noise
	case "air_pollution_noise":
		return rates.AirNoise
	case "co2", "carbon_price":
		return rates.CO2
	case "unspecified":
		return rates.Toll
	}
	return ch.Component
}

// sourceText is a charge's legal basis: its own method, else the dataset's.
func sourceText(ds *tariffs.Dataset, ch *orct.Charge) string {
	var s string
	if len(ch.Method) > 0 && json.Unmarshal(ch.Method, &s) == nil && s != "" {
		return s
	}
	return ds.Method()
}

func srcs(ds *tariffs.Dataset) []rates.Source {
	var out []rates.Source
	for _, s := range ds.Sources() {
		out = append(out, rates.Source{Title: s.Title, URL: s.URL})
	}
	return out
}

// price prices the batch and adds its lines; it returns the statement.
func (p *pricer) price(b *batch, src string, extra func(*Line, *orct.Line)) (*orct.Statement, error) {
	if len(b.events) == 0 && len(b.quants) == 0 {
		return &orct.Statement{}, nil
	}
	u := &orct.Usage{ORCTUsage: "0.3", Vehicle: p.vehicle, Payment: p.payment, Events: b.events, Quantities: b.quants}
	st := orct.Calculate([]*orct.Dataset{b.ds.Dataset}, u)
	cur := b.ds.Doc.Header.Currency
	var lines []*Line
	merged := map[string]*Line{}
	for _, ol := range st.Lines {
		ch := b.ds.Charge(ol.Charge)
		var m *lineMeta
		if ol.Event != nil {
			m, _ = ol.Event.Ref.(*lineMeta)
		}
		if m == nil {
			m = &lineMeta{charge: RoadToll, country: b.ds.Country}
		}
		amount := ol.Amount.Float()
		key := ""
		if m.key != "" && ol.Row != nil && (ch.Type == "distance" || ch.Type == "period" || ch.Type == "area") {
			key = fmt.Sprintf("%s|%s|%d", m.key, ol.Charge, *ol.Row)
		}
		if l, ok := merged[key]; ok && key != "" {
			l.Amount += amount
			if l.Area != m.area {
				l.Area = ""
			}
			switch ch.Type {
			case "period":
				l.Days++
				fallthrough
			case "distance":
				if m.hasKm {
					l.Km += m.km
				}
			case "area": // another day in the zone: the same km
				l.Days++
			}
			continue
		}
		rate, _ := orct.ParseDec(ol.Rate)
		l := &Line{Charge: m.charge, Country: m.country, Region: m.region, Road: m.road, Area: m.area, Section: m.section,
			Component: componentOf(ch), Rate: rate.Float(), Currency: cur, Amount: amount, Source: src, Sources: srcs(b.ds)}
		if src == "" {
			l.Source = sourceText(b.ds, ch)
		}
		if m.hasKm {
			l.Km = m.km
		}
		l.Carbon = l.Component == rates.CO2
		switch ch.Type {
		case "distance":
			l.RateUnit = cur + "/" + ch.Unit
			if ch.Unit == "tkm" && m.km > 0 {
				l.Tonnes = ol.Quantity.Float() / m.km
			}
		case "period":
			l.RateUnit, l.Days = cur+"/day", 1
		case "section":
			l.RateUnit = cur + "/section"
			if ch.Unit == "km" {
				l.RateUnit = cur + "/km"
				l.Km = ol.Quantity.Float()
			}
		case "point", "od":
			l.RateUnit = cur + "/passage"
		case "area":
			l.RateUnit, l.Days = cur+"/day", 1
		case "quantity":
			if ch.Unit == "litre" {
				l.RateUnit, l.Litres = cur+"/l", ol.Quantity.Float()
			} else {
				l.RateUnit, l.TonnesCO2 = cur+"/t CO2", ol.Quantity.Float()
			}
		}
		if ol.Unit == "rule" {
			// A rule's adjustment (a cap, a minimum): it adds to the line
			// of the use it adjusts.
			if prev := lastOf(lines, m); prev != nil {
				prev.Amount += amount
				continue
			}
			l.Rate, l.Km = amount, 0
		}
		if extra != nil {
			extra(l, ol)
		}
		lines = append(lines, l)
		if key != "" {
			merged[key] = l
		}
		// A factor rule's surcharge on part of the km (a surcharged
		// stretch) is a line of its own.
		for _, r := range b.ds.Doc.Rules {
			if r.Kind != "factor" || !slices.Contains(r.AppliesTo, ol.Charge) || ol.Event == nil {
				continue
			}
			obj, _ := r.Params["object"].(string)
			okm, ok := ol.Event.Overlays[obj]
			if !ok || okm.Sign() == 0 {
				continue
			}
			base := rate.Mul(ol.Quantity).Float()
			f, _ := orct.ParseDec(fmt.Sprint(r.Params["factor"]))
			s := *l
			s.Section, s.Km = b.ds.Object(obj).Name, okm.Float()
			s.Rate = rate.Mul(f.Sub(orct.DecInt(1))).Float()
			s.Amount = l.Amount - base
			l.Amount = base
			sk := key + "|" + obj
			if prev, ok := merged[sk]; ok && key != "" {
				prev.Amount += s.Amount
				prev.Km += s.Km
				continue
			}
			lines = append(lines, &s)
			if key != "" {
				merged[sk] = &s
			}
		}
	}
	for _, l := range lines {
		if math.Abs(l.Amount) < 0.005 && l.Charge != FuelCO2 {
			continue
		}
		l.Km = round3(l.Km)
		l.TonnesCO2 = round3(l.TonnesCO2)
		l.Litres = round3(l.Litres)
		if err := p.add(*l); err != nil {
			return st, err
		}
	}
	return st, nil
}

// lastOf is the last line priced from the same use (meta), if any.
func lastOf(lines []*Line, m *lineMeta) *Line {
	for i := len(lines) - 1; i >= 0; i-- {
		l := lines[i]
		if l.Section == m.section && l.Country == m.country {
			return l
		}
	}
	return nil
}

// ---------------------------------------------------------------- networks

// network is a dataset's network objects by what they cover.
type network struct {
	root, env string
	sections  string
	byType    map[string]string // road type -> object
	byArea    map[string]string // area -> object
	cells     map[[2]string]string
	ops       []*orct.Object
	roadTypes []string // the road types its rates differ by
	areas     []string
	hasRows   bool // distance or period charges
	perDay    *orct.Charge
	tkm       bool
}

func networkOf(ds *tariffs.Dataset) *network {
	n := &network{byType: map[string]string{}, byArea: map[string]string{}, cells: map[[2]string]string{}}
	rowObj := map[string]bool{}
	for _, ch := range ds.Charges() {
		switch ch.Type {
		case "distance", "period":
			if ch.ComponentLabel == rates.EnvZoneSurcharge {
				for o := range ch.RowObjects() {
					n.env = o
				}
				continue
			}
			n.hasRows = true
			for o := range ch.RowObjects() {
				rowObj[o] = true
			}
			if ch.Type == "period" {
				n.perDay = ch
			}
			if ch.Unit == "tkm" {
				n.tkm = true
			}
		}
	}
	for _, o := range ds.Objects() {
		if o.Type != "network" {
			continue
		}
		switch {
		case o.ID == n.env:
		case o.Operator != "":
			n.ops = append(n.ops, o)
		case o.Network != nil && len(o.Network.RoadTypes) == 1 && o.Network.Area != "":
			n.cells[[2]string{roadTypeOf(o), o.Network.Area}] = o.ID
		case o.Network != nil && len(o.Network.RoadTypes) == 1:
			n.byType[roadTypeOf(o)] = o.ID
		case o.Network != nil && o.Network.Area != "":
			n.byArea[o.Network.Area] = o.ID
		case len(o.Parents) == 0 && n.root == "" && o.Location == nil:
			n.root = o.ID
		case o.Location == nil && len(o.Parents) > 0 && n.sections == "" && strings.HasPrefix(o.Name, "Sections with a toll"):
			n.sections = o.ID
		}
	}
	for rt := range n.byType {
		n.roadTypes = append(n.roadTypes, rt)
	}
	sort.Strings(n.roadTypes)
	if len(n.byType) == 1 && len(n.ops) > 0 {
		// Only operators' rows: the rates don't differ by road type
		// unless rows name one.
		n.roadTypes = n.roadTypesNamed(ds)
	}
	for a := range n.byArea {
		n.areas = append(n.areas, a)
	}
	sort.Strings(n.areas)
	return n
}

// roadTypesNamed are the road types rows are keyed by (not through an
// operator).
func (n *network) roadTypesNamed(ds *tariffs.Dataset) []string {
	var out []string
	for _, ch := range ds.Charges() {
		for o := range ch.RowObjects() {
			for rt, id := range n.byType {
				if id == o && !slices.Contains(out, rt) {
					out = append(out, rt)
				}
			}
			for k, id := range n.cells {
				if id == o && !slices.Contains(out, k[0]) {
					out = append(out, k[0])
				}
			}
		}
	}
	sort.Strings(out)
	return out
}

// roadTypeOf is a network object's road type as carbon-cost names it.
func roadTypeOf(o *orct.Object) string {
	if o.Network.RoadTypes[0] == "motorway" {
		return rates.Motorway
	}
	return rates.OtherRoad
}

// object is the most specific network object for km on a road type (""
// for any), in an area ("" for any), on an operator's ways (op as
// roads.Km keys them, "operator|ref|name").
func (n *network) object(road, area, op string) string {
	if op != "" {
		parts := strings.Split(op, "|")
		for k := min(len(parts), 3); k >= 1; k-- {
			r, name := "", ""
			if k >= 2 {
				r = parts[1]
			}
			if k >= 3 {
				name = parts[2]
			}
			for _, o := range n.ops {
				if o.Operator == parts[0] && o.Road == r && o.Name == name {
					return o.ID
				}
			}
		}
	}
	if id, ok := n.cells[[2]string{road, area}]; ok && road != "" && area != "" {
		return id
	}
	if id, ok := n.byType[road]; ok && road != "" {
		return id
	}
	if id, ok := n.byArea[area]; ok && area != "" {
		return id
	}
	return n.root
}

// ---------------------------------------------------------------- geometry

func placeOf(coord []float64) rates.Place { return rates.Place{Lon: coord[0], Lat: coord[1]} }

// geometry caches the places and polygons read from objects' locations.
var geometry sync.Map // *orct.Object -> []rates.Place or [][][][2]float64

// pointsOf are a location's points, each with its heading and name.
func pointsOf(o *orct.Object) []rates.Place {
	if v, ok := geometry.Load(o); ok {
		return v.([]rates.Place)
	}
	pts := readPoints(o)
	geometry.Store(o, pts)
	return pts
}

func readPoints(o *orct.Object) []rates.Place {
	if o.Location == nil || o.Location.Geometry == nil {
		return nil
	}
	g := o.Location.Geometry
	var out []rates.Place
	switch g.Type {
	case "Point":
		var c []float64
		json.Unmarshal(g.Coordinates, &c)
		p := placeOf(c)
		p.Heading = o.Location.Heading
		out = append(out, p)
	case "MultiPoint", "LineString":
		var cs [][]float64
		json.Unmarshal(g.Coordinates, &cs)
		for i, c := range cs {
			p := placeOf(c)
			if i < len(o.Location.Headings) {
				p.Heading = o.Location.Headings[i]
			}
			if i < len(o.Location.PointNames) {
				p.Name = o.Location.PointNames[i]
			}
			out = append(out, p)
		}
	}
	return out
}

func endOf(pl *orct.Place) rates.Place {
	var c []float64
	json.Unmarshal(pl.Geometry.Coordinates, &c)
	p := placeOf(c)
	p.Name, p.Heading = pl.Name, pl.Heading
	return p
}

type polys [][][][2]float64

// polygonsOf are an area's polygons, each its outer ring and holes.
func polygonsOf(o *orct.Object) [][][][2]float64 {
	if v, ok := geometry.Load(o); ok {
		return v.(polys)
	}
	p := readPolygons(o)
	geometry.Store(o, polys(p))
	return p
}

func readPolygons(o *orct.Object) [][][][2]float64 {
	if o.Location == nil || o.Location.Geometry == nil {
		return nil
	}
	var out [][][][2]float64
	switch o.Location.Geometry.Type {
	case "MultiPolygon":
		json.Unmarshal(o.Location.Geometry.Coordinates, &out)
	case "Polygon":
		var p [][][2]float64
		json.Unmarshal(o.Location.Geometry.Coordinates, &p)
		out = append(out, p)
	}
	return out
}

func inPolygons(polys [][][][2]float64, pt [2]float64) bool {
	for _, poly := range polys {
		if len(poly) == 0 || !inRing(poly[0], pt) {
			continue
		}
		hole := false
		for _, h := range poly[1:] {
			hole = hole || inRing(h, pt)
		}
		if !hole {
			return true
		}
	}
	return false
}

func inRing(r [][2]float64, p [2]float64) bool {
	in := false
	for i, j := 0, len(r)-1; i < len(r); j, i = i, i+1 {
		if (r[i][1] > p[1]) != (r[j][1] > p[1]) && p[0] < (r[j][0]-r[i][0])*(p[1]-r[i][1])/(r[j][1]-r[i][1])+r[i][0] {
			in = !in
		}
	}
	return in
}

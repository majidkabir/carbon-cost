# Rate tables (the builders' format)

The builders under `tools/tables`, `tools/history`, `tools/fr`, `tools/hr`
and `tools/rs` write one JSON file per table. A table is not data
carbon-cost keeps: `tools/orct/convert.py` turns it into an ORCT 0.3
dataset right after it is built, and only the datasets are committed
(`tariffs/data`) and priced with.

A table's file name is `<scheme>-<valid_from>.json`; `zone-*` files are
zones (`Zone`), `fuelco2-*` files national CO2 prices on fuel (`FuelCO2`),
the rest tolls (`Table`). The fields, as the Go types carbon-cost read the
tables with before ORCT (JSON names in the tags; `omitempty` fields are
optional):

```go
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

// Source is a document the rates come from.
type Source struct {
	Title string `json:"title"`
	URL   string `json:"url"`
}

// Row is one component rate for the trucks it matches. Zero or empty
// conditions match any truck; MaxKg and MaxAxles 0 mean no upper limit.
type Row struct {
	Component string `json:"component"`
	MinKg     int    `json:"min_kg,omitempty"`
	MaxKg     int    `json:"max_kg,omitempty"`
	MinAxles  int    `json:"min_axles,omitempty"`
	MaxAxles  int    `json:"max_axles,omitempty"`
	Euro      []int  `json:"euro,omitempty"`
	CO2Class  []int  `json:"co2_class,omitempty"`
	// Road is set where the rate depends on the road type (Motorway or
	// OtherRoad): the row applies only to km on that type.
	Road string `json:"road,omitempty"`
	// Area is set where the rate depends on whether the road is
	// suburban or interurban (Suburban or Interurban): the row applies to
	// that share of the km (Table.SuburbanShare).
	Area string `json:"area,omitempty"`
	// Operator is set where the rate depends on who runs the road (Italy's
	// concessions): the row applies only to Motorway km on ways of that
	// operator, "operator" or "operator|ref" as roads.Km.MotorwayOp keys
	// them; rows without one apply to the other operators' km.
	Operator string  `json:"operator,omitempty"`
	// VehicleUnit is set where each vehicle of a combination pays on its
	// own ("motor" or "trailer", Iceland's kílómetragjald): MinKg, MaxKg and
	// the axle bounds apply to that vehicle's own mass and axles (ORCT
	// mass_kg and axles, or trailer_mass_kg and trailer_axles), and each unit
	// is its own charge; a trailer's is free where no row matches.
	VehicleUnit string `json:"vehicle_unit,omitempty"`
	// Energy limits the row to trucks of these energies (ORCT energy).
	Energy []string `json:"energy,omitempty"`
	Rate     float64 `json:"rate"` // currency per km, per tonne-km in a PerTonneKm table, per day in a PerDay table
}

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

// Exemption makes trucks of the given CO2 classes toll-free until a date.
type Exemption struct {
	CO2Class []int  `json:"co2_class"`
	Until    string `json:"until"` // inclusive, YYYY-MM-DD
	Note     string `json:"note"`
}

// Table is one country's toll for one validity period.
type Table struct {
	Country string `json:"country"` // ISO 3166-1 alpha-2
	// Region is set for a regional toll (ISO 3166-2, e.g. BE-VLG): the
	// table then applies to that region's km, not the country's.
	Region    string   `json:"region,omitempty"`
	Currency  string   `json:"currency"`
	ValidFrom string   `json:"valid_from"`         // inclusive, YYYY-MM-DD
	ValidTo   string   `json:"valid_to,omitempty"` // inclusive; "" = until replaced
	Name      string   `json:"name"`
	Law       string   `json:"law"`
	Sources   []Source `json:"sources"`
	// OSMExtract is the date of the OpenStreetMap extract the table's
	// stations or sections were placed from, where they were.
	OSMExtract string `json:"osm_extract,omitempty"`
	// File is the table's file in data/.
	File        string `json:"-"`
	Vehicles    string `json:"vehicles"`
	MinKg       int    `json:"min_kg"` // lighter trucks pay no toll
	TolledRoads string `json:"tolled_roads"`
	// PerTonneKm tables charge their rates per tonne-km of the truck's
	// maximum mass, up to MaxChargeableKg (Switzerland's LSVA).
	PerTonneKm      bool `json:"per_tonne_km,omitempty"`
	MaxChargeableKg int  `json:"max_chargeable_kg,omitempty"`
	// PerDay tables charge their rates per day of use, whatever the km
	// (time-based vignettes): a trip is priced for each day it is there.
	PerDay bool `json:"per_day,omitempty"`
	// Day is what a day of a PerDay charge is: "calendar" (00:00 to
	// 24:00) or "24h" (24 hours from when it starts); "" not known, so a
	// trip is priced by 24 hours (the fewest), days_unknown where calendar
	// days are more.
	Day string `json:"day,omitempty"`
	// MotorAxles tables count the axles of the motor vehicle alone (the
	// truck or tractor), not of the combination: rows' axle bounds apply
	// to Truck.MotorAxles, or to Axles when that isn't given.
	MotorAxles bool `json:"motor_axles,omitempty"`
	// MotorwayShare is the share of km priced at motorway rates when the
	// rates differ by road type and the request doesn't say (default 0).
	MotorwayShare float64 `json:"motorway_share,omitempty"`
	// SuburbanShare is the share of km on suburban roads, by road type
	// ("" for any), for rows with an Area, where the route doesn't tell.
	SuburbanShare    map[string]float64 `json:"suburban_share,omitempty"`
	EnvZoneSurcharge string             `json:"env_zone_surcharge,omitempty"`
	Exemptions       []Exemption        `json:"exemptions,omitempty"`
	Rows             []Row              `json:"rows"`
	// Sections are road sections with a fixed infrastructure charge per
	// passage instead of the per-km one (Austria's special toll sections).
	Sections *Sections `json:"sections,omitempty"`
	// Crossings marks a table of fixed-charge crossings (bridges) only:
	// its closed systems are priced wherever the route passes them, on top
	// of the countries' own tolls.
	Crossings bool `json:"crossings,omitempty"`
	// Ferry marks a crossings table whose systems are ferry crossings: their
	// charges are fares (ferry_fare), not tolls.
	Ferry bool `json:"ferry,omitempty"`
	// Closed are toll systems priced from entry to exit station
	// (Croatia's motorways).
	Closed []TollSystem `json:"closed_systems,omitempty"`
	// Surcharges raise a component's per-km rate on a stretch of road.
	Surcharges []Surcharge `json:"surcharges,omitempty"`
	// TollPoints are toll stations charged per passage, each on its own
	// (Norway's AutoPASS stations).
	TollPoints []TollPoint `json:"toll_points,omitempty"`
	// PointMatchKm is how close the route must pass a toll point to pay it.
	PointMatchKm float64 `json:"point_match_km,omitempty"`
	// Congestion prices the toll points that name a Schedule by the time
	// of day (Sweden's congestion tax).
	Congestion *Congestion `json:"congestion,omitempty"`
}

// PointClass is a toll point's price for the trucks it matches; ETCRate,
// if set, for trucks paying by tag (Request.ETC).
type PointClass struct {
	MinKg    int `json:"min_kg,omitempty"`
	MaxKg    int `json:"max_kg,omitempty"`
	MinAxles int `json:"min_axles,omitempty"`
	MaxAxles int `json:"max_axles,omitempty"`
	// MinLengthM (more than) and MaxLengthM (up to) bound the truck's
	// length with trailer (Truck.LengthM), where the price goes by length.
	MinLengthM float64 `json:"min_length_m,omitempty"`
	MaxLengthM float64 `json:"max_length_m,omitempty"`
	// Trailer, where set, limits the class to trucks with (true) or
	// without (false) a trailer (Poland's concession motorways' categories
	// go by the motor vehicle's axles and whether it tows one).
	Trailer *bool   `json:"trailer,omitempty"`
	Rate       float64 `json:"rate"`
	ETCRate    float64 `json:"etc_rate,omitempty"`
	// HighRate is the price on the point's HighSeason days; HighETCRate
	// the tag's price then, where it differs from ETCRate.
	HighRate    float64 `json:"high_rate,omitempty"`
	HighETCRate float64 `json:"high_etc_rate,omitempty"`
	// NightRate and NightETCRate are the prices in the point's
	// NightHours, where they differ.
	NightRate    float64 `json:"night_rate,omitempty"`
	NightETCRate float64 `json:"night_etc_rate,omitempty"`
}

// Season is a set of days: in Months (1-12), on Weekdays (0 Sunday to
// 6 Saturday), or from EasterFrom to EasterTo days after Easter Sunday
// (negative before it), when that window is set.
type Season struct {
	Months     []int `json:"months,omitempty"`
	Weekdays   []int `json:"weekdays,omitempty"`
	EasterFrom int   `json:"easter_from,omitempty"`
	EasterTo   int   `json:"easter_to,omitempty"`
}

// TollPoint is a toll station charged per passage.
type TollPoint struct {
	Name    string  `json:"name"`
	Project string  `json:"project,omitempty"` // the toll project (bompengeanlegg)
	Lat     float64 `json:"lat"`
	Lon     float64 `json:"lon"`
	// Heading is the direction of travel that pays, in degrees clockwise
	// from north; nil when both directions pay.
	Heading  *float64 `json:"heading,omitempty"`
	Rate     float64  `json:"rate"`                // per passage, outside rush hours
	PeakRate float64  `json:"peak_rate,omitempty"` // per passage in rush hours, where it differs
	// Rush is when PeakRate applies; without it the station is priced at
	// Rate, with a note.
	Rush *Rush `json:"rush,omitempty"`
	// Classes price the station by truck where its price differs by mass
	// or axles: the first class the truck matches, instead of Rate.
	Classes []PointClass `json:"classes,omitempty"`
	// Group is the passage group of an hour rule: after a paid passage,
	// the group's other stations are free for GroupMinutes.
	Group        int `json:"group,omitempty"`
	GroupMinutes int `json:"group_minutes,omitempty"`
	// GroupPays "highest": the passages within the group's minutes pay the
	// highest of their prices; otherwise the first passage pays.
	GroupPays string `json:"group_pays,omitempty"`
	// Within names a closed system of the same table whose tickets
	// include this station's charge: a route with a ticket of that system
	// from one side of the station to the other doesn't pay it again.
	Within string `json:"within,omitempty"`
	// Schedule names the table's Congestion schedule that prices this
	// station by the time of day, instead of Rate.
	Schedule string `json:"schedule,omitempty"`
	// FreeHours: from and to (HH:MM, both included) the station charges
	// nothing; FreeDates: days of the year (MM-DD) it charges nothing
	// (Christmas Day).
	FreeHours []string `json:"free_hours,omitempty"`
	FreeDates []string `json:"free_dates,omitempty"`
	// NightHours: from and to (HH:MM, both included) its classes charge
	// their NightRate (NightETCRate by tag).
	NightHours []string `json:"night_hours,omitempty"`
	// HighSeason: the days its classes charge their HighRate.
	HighSeason *Season `json:"high_season,omitempty"`
	// ValidFrom and ValidTo (YYYY-MM-DD, both included, either may be
	// empty) limit the point to part of the table's time: a table can
	// then hold each version of a station that changed its price.
	ValidFrom string `json:"valid_from,omitempty"`
	ValidTo   string `json:"valid_to,omitempty"`
}

// TollSystem is a closed toll system: the price from the station where
// a truck enters to the one where it leaves, by vehicle group. An open
// toll station (a barrier on the road) is priced from itself to itself.
type TollSystem struct {
	Name string `json:"name"`
	Law  string `json:"law"`
	// Chain prices a trip that passes many stations as consecutive
	// published entry-exit pairs that together cover the most of it
	// (France); otherwise one ticket from the first to the last station.
	Chain    bool      `json:"chain,omitempty"`
	Groups   []Group   `json:"groups"`
	Stations []Station `json:"stations"`
	// StationMatchKm: how near a route must pass a station, where not
	// the default 0.5 km.
	StationMatchKm float64                       `json:"station_match_km,omitempty"`
	Prices         map[string]map[string]float64 `json:"prices"` // "entry|exit" -> group -> price
	// ETCPrices replace Prices for trucks paying by an electronic toll
	// device or agreement (Request.ETC), where the operator sets them.
	ETCPrices map[string]map[string]float64 `json:"etc_prices,omitempty"`
	// Discounts in percent of the price, added up over those that apply.
	Discounts []Discount `json:"discounts,omitempty"`
	// FreeHours: from and to (HH:MM, both included) the system charges
	// nothing, for a trip entering it then.
	FreeHours []string `json:"free_hours,omitempty"`
	// NightHours: from and to (HH:MM, both included) NightPrices replace
	// Prices for a trip entering the system then (AP-71's night tariff).
	NightHours  []string                      `json:"night_hours,omitempty"`
	NightPrices map[string]map[string]float64 `json:"night_prices,omitempty"`
	// Directed: the prices are per direction, entry|exit; a pair with no
	// price that way has none (no trip), instead of the other way's.
	Directed bool `json:"directed,omitempty"`
	// Season: date ranges ([from, to], YYYY-MM-DD) in which SeasonPrices
	// replace Prices (Jadrolinija's season).
	Season       [][]string                    `json:"season,omitempty"`
	SeasonPrices map[string]map[string]float64 `json:"season_prices,omitempty"`
	// TimePrices replace Prices on weekdays' hours (Estonia's ferries:
	// Friday from 13:00 towards the islands).
	TimePrices []TimePrice `json:"time_prices,omitempty"`
	// Unit "t": the prices are per tonne of MassBasis (an ORCT vehicle
	// parameter, default train_mass_kg; Jadrolinija's load_capacity_kg),
	// per started MassStepKg where given (the Elbe ferry's load, per
	// started 1,000 kg of load_kg).
	Unit       string `json:"unit,omitempty"`
	MassBasis  string `json:"mass_basis,omitempty"`
	MassStepKg int    `json:"mass_step_kg,omitempty"`
	// Unmatched "free": a truck no group matches pays nothing here
	// (ORCT unmatched), instead of the system being unpriced for it.
	Unmatched string `json:"unmatched,omitempty"`
}

// TimePrice is a toll system's prices on some weekdays' hours.
type TimePrice struct {
	Label    string                        `json:"label,omitempty"`
	Weekdays []int                         `json:"weekdays"` // 1 Monday ... 7 Sunday
	Times    [][]string                    `json:"times"`    // [from, to], HH:MM
	Prices   map[string]map[string]float64 `json:"prices"`   // as TollSystem.Prices
}

// Discount is a percentage off a toll system's price for the trucks it
// matches; ETC ones only for trucks paying electronically.
type Discount struct {
	Name     string  `json:"name"`
	ETC      bool    `json:"etc,omitempty"`
	Euro     []int   `json:"euro,omitempty"`
	CO2Class []int   `json:"co2_class,omitempty"`
	Percent  float64 `json:"percent"`
}

// Group is a vehicle group of a toll system; the first a truck matches
// is its group.
type Group struct {
	Name       string  `json:"name"`
	MinKg      int     `json:"min_kg,omitempty"`
	MinAxles   int     `json:"min_axles,omitempty"`
	MaxAxles   int     `json:"max_axles,omitempty"`
	MinLengthM float64 `json:"min_length_m,omitempty"` // more than this
	MaxLengthM float64 `json:"max_length_m,omitempty"` // up to this
	// Euro: the EURO classes the group is for (any if empty).
	Euro []int `json:"euro,omitempty"`
	// Trailer, where set: only trucks with (true) or without (false) a
	// trailer. In a MotorAxles table the axles are the motor vehicle's.
	Trailer *bool `json:"trailer,omitempty"`
	// Base: the group whose price a pair has when it has none for this
	// one (an operator that prices by EURO class in a system where the
	// others don't).
	Base string `json:"base,omitempty"`
	// MinCapacityKg (more than this) and MaxCapacityKg (up to this): the
	// truck's load capacity (Jadrolinija's groups; Request truck.capacity_kg).
	MinCapacityKg int `json:"min_capacity_kg,omitempty"`
	MaxCapacityKg int `json:"max_capacity_kg,omitempty"`
}

// Station is a toll station: where a route passes one of its points (the
// motorway junction or the toll booths), it uses the station.
type Station struct {
	Name   string  `json:"name"`
	Points []Place `json:"points"`
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

// Sections lists the fixed-charge sections and the law they come from.
type Sections struct {
	Law          string    `json:"law"`
	TariffGroups string    `json:"tariff_groups"`
	List         []Section `json:"list"`
	// PerKm are charges per km of a section's official length (Km), on
	// top of its fixed charge: Slovenia's rail surcharge and external-cost
	// charge.
	PerKm []SectionPerKm `json:"per_km,omitempty"`
}

// SectionPerKm is a per-km charge on sections. Rates are keyed by
// TollClass and, as Key says, the truck's emission key (EmissionKey) and
// the section's Area ("class/emission/area"), or the section's Tier
// ("class/tier"). Sections with no rate for their key don't pay it.
type SectionPerKm struct {
	Component string             `json:"component"`
	Name      string             `json:"name"`
	Law       string             `json:"law"`
	Key       string             `json:"key"` // "class/emission/area" or "class/tier"
	Rates     map[string]float64 `json:"rates"`
}

// Section is a road section from one place to another with a fixed
// infrastructure charge: per tariff group (E for CO2 class 5, A for the
// rest), for 2, 3 and 4+ axles, and optionally a night charge for 4+
// axles.
type Section struct {
	ID        string                `json:"id"`
	Road      string                `json:"road"`
	Name      string                `json:"name"`
	From      Place                 `json:"from"`
	To        Place                 `json:"to"`
	Tariff    map[string][3]float64 `json:"tariff,omitempty"`
	NightKat4 map[string]float64    `json:"night_kat4,omitempty"`
	// Km is the section's official length, where the law gives one.
	Km float64 `json:"km,omitempty"`
	// Area is suburban or interurban, for charges that differ by it.
	Area string `json:"area,omitempty"`
	// Tier picks the section's per-km surcharge rates, if any.
	Tier string `json:"tier,omitempty"`
	// Classes are Slovenia's charges per toll class (R2, R3, R4) in nine
	// columns: EURO 0-III, IV, V, EEV and VI with CO2 class 1, then EURO
	// VI with CO2 classes 2, 3, 4 and 5.
	Classes map[string][9]float64 `json:"classes,omitempty"`
}

// Surcharge raises Component's per-km rate by Factor on a stretch of
// road given as its junctions in order: the km between consecutive
// junctions a route passes count.
type Surcharge struct {
	ID        string  `json:"id"`
	Name      string  `json:"name"`
	Points    []Place `json:"points"`
	Component string  `json:"component"`
	Factor    float64 `json:"factor"`
	Law       string  `json:"law"`
}

// Truck is what a toll rate depends on.
type Truck struct {
	MaxMassKg int `json:"max_mass_kg"` // technically permissible maximum mass
	Axles     int `json:"axles"`       // of the truck with its trailer
	// MotorAxles is the motor vehicle's own axles, optional: Lithuania's
	// charge counts those (a tractor's, without the semi-trailer's).
	MotorAxles int `json:"motor_axles,omitempty"`
	Euro       int `json:"euro"`      // emission standard 0-6 (EEV counts as 5)
	CO2Class   int `json:"co2_class"` // EU CO2 emission class 1-5 (5 = zero-emission)
	// TareKg is the truck's own weight (with trailer), optional: ferries
	// report freight emissions per tonne of vehicle and cargo.
	TareKg int `json:"tare_kg,omitempty"`
	// LengthM is the vehicle's length with trailer, optional: bridge tolls
	// are priced by length (default DefaultLengthM).
	LengthM float64 `json:"length_m,omitempty"`
}

// DefaultLengthM is the length assumed when a truck's isn't given: a
// tractor with semi-trailer (EU maximum 16.50 m, Directive 96/53/EC).
const DefaultLengthM = 16.5

// Rush is when a toll point charges its PeakRate: within Hours, Monday to
// Friday, except its FreeDays.
type Rush struct {
	// Hours: each from and to (HH:MM, both included).
	Hours [][]string `json:"hours"`
	// FreeDays, besides Saturdays and Sundays: "norwegian_holidays"
	// (NorwegianHoliday), "norwegian_eves" (NorwegianEve) and "july".
	FreeDays []string `json:"free_days,omitempty"`
}

// Congestion is a time-based congestion tax (Sweden's trängselskatt): its
// toll points charge, per passage, the amount of their schedule at the
// time of day, on taxed days only.
type Congestion struct {
	// Schedules are the amounts by time of day, by schedule name (a toll
	// point's Schedule).
	Schedules map[string][]TimeAmount `json:"schedules"`
	// HighSeason are the date ranges of the high season, where amounts
	// differ by season: "MM-DD", or "midsummer_eve-1" (the day before
	// Midsummer Eve).
	HighSeason [][2]string `json:"high_season,omitempty"`
	// DayCap is the most one vehicle pays in a day (DayCapHigh in high
	// season).
	DayCap     float64 `json:"day_cap,omitempty"`
	DayCapHigh float64 `json:"day_cap_high,omitempty"`
	// MultiPassMinutes: passages within this many minutes of a taxed one
	// pay once, the highest amount among them.
	MultiPassMinutes int `json:"multi_pass_minutes,omitempty"`
	// July: "free" (no tax in July) or "first5" (only on its first five
	// weekdays).
	July string `json:"july,omitempty"`
	// EveTaxed: the public holidays whose eve is taxed anyway (the day
	// before a public holiday is otherwise free): good_friday, ascension,
	// all_saints, may_1, june_6.
	EveTaxed []string `json:"eve_taxed,omitempty"`
}

// TimeAmount is a schedule's amount from From to To (HH:MM, both
// included: the hour and started minute), High in high season.
type TimeAmount struct {
	From   string  `json:"from"`
	To     string  `json:"to"`
	Amount float64 `json:"amount"`
	High   float64 `json:"high,omitempty"`
}

// ZonePrefix starts the name of each area charge's file in data/.
const ZonePrefix = "zone-"

// Zone is an area charged per day a truck drives in it (London's
// Congestion Charge and Low Emission Zone): Charge once per day, for a
// truck of at least MinKg below the ExemptEuro emission standard (0: any),
// when it is in the zone in the charging hours.
type Zone struct {
	Country   string   `json:"country"`
	Currency  string   `json:"currency"`
	ValidFrom string   `json:"valid_from"`
	ValidTo   string   `json:"valid_to,omitempty"`
	Name      string   `json:"name"`
	Law       string   `json:"law"`
	Sources   []Source `json:"sources"`
	MinKg     int      `json:"min_kg"`
	Charge    float64  `json:"charge"` // per day
	// ExemptEuro: trucks meeting this Euro standard or a later one pay
	// nothing (0: none exempt).
	ExemptEuro int `json:"exempt_euro,omitempty"`
	// EuroCharges: lower charges for trucks meeting a Euro standard (the
	// highest MinEuro the truck meets), Charge for the rest.
	EuroCharges []EuroCharge `json:"euro_charges,omitempty"`
	// Hours the zone charges, from and to (HH:MM, both included), on
	// weekdays (Monday to Friday) and weekends; none: all day, every day.
	Weekdays []string `json:"weekdays,omitempty"`
	Weekends []string `json:"weekends,omitempty"`
	// NoCharge: days of the year (MM-DD, from and to, both included,
	// wrapping past the year's end) when the zone charges nothing;
	// NoChargeDates: days besides (YYYY-MM-DD: a substitute bank holiday).
	NoCharge      []string `json:"no_charge,omitempty"`
	NoChargeDates []string `json:"no_charge_dates,omitempty"`
	// Polygons: the zone's outer rings, [lon, lat] points; Holes: inner
	// rings cut out of them.
	Polygons [][][2]float64 `json:"polygons"`
	Holes    [][][2]float64 `json:"holes,omitempty"`
	OSM      string         `json:"osm_extract"`
	File     string         `json:"-"`
}

// EuroCharge is a zone's daily charge for trucks of MinEuro or later.
type EuroCharge struct {
	MinEuro int     `json:"min_euro"`
	Charge  float64 `json:"charge"`
}

// FuelCO2Prefix starts the names of the files in data/ that hold a
// country's CO2 price on road fuel.
const FuelCO2Prefix = "fuelco2-"

// FuelCO2 is a country's CO2 price on road diesel in force for a period:
// a national emissions trading system's certificate price (Germany's
// BEHG, Austria's NEHG 2022) or a carbon tax, per tonne of CO2, or a CO2
// tax per litre of diesel (Denmark's, Sweden's...). The fuel supplier pays
// it and passes it on in the price of the fuel, so a trip pays it where
// its fuel is bought.
type FuelCO2 struct {
	Country   string   `json:"country"` // ISO 3166-1 alpha-2
	Currency  string   `json:"currency"`
	ValidFrom string   `json:"valid_from"`         // inclusive, YYYY-MM-DD
	ValidTo   string   `json:"valid_to,omitempty"` // inclusive; "" = until replaced
	Name      string   `json:"name"`
	RatePerT  float64  `json:"rate_per_t,omitempty"` // per tonne of CO2, or
	RatePerL  float64  `json:"rate_per_l,omitempty"` // per litre of diesel (ORCT unit "litre")
	Law       string   `json:"law"`
	Sources   []Source `json:"sources"`
	File      string   `json:"-"`
}

```

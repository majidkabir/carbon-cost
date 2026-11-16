package orct

import "time"

// Queries for a tool that matches a route to a dataset's objects: which
// vehicles a dataset charges, and whether a charge prices a use at all.

// Liable says whether the dataset charges the vehicle (6.5); an error
// says a parameter it tests is missing.
func (ds *Dataset) Liable(vehicle map[string]any) (ok bool, err error) {
	if u := catch(func() { ok = meets(ds.Doc.Liable.Criteria, vehicle) }); u != nil {
		return false, u
	}
	return ok, nil
}

// Meets says whether the vehicle meets criteria (6.6.2).
func Meets(criteria, vehicle map[string]any) (ok bool, err error) {
	if u := catch(func() { ok = meets(criteria, vehicle) }); u != nil {
		return false, u
	}
	return ok, nil
}

// Rate is the amount of the row the charge selects for a use of an
// object (or a trip from entry to exit) at a time, by a vehicle paying by
// the given means; ok is false when no row matches. An error says the
// data or the vehicle does not decide the row.
func (ds *Dataset) Rate(charge, object, entry, exit string, at time.Time, vehicle map[string]any, payment []string) (amount Dec, ok bool, err error) {
	ch := ds.charges[charge]
	if ch == nil {
		return Dec{}, false, nil
	}
	c := &Calc{ds: map[string]*Dataset{ds.ID: ds}, usage: &Usage{Vehicle: vehicle, Payment: payment}, vehicle: vehicle, complete: true}
	c.vclass, c.held = ds.classify(vehicle), c.heldOf(ds)
	var r *row
	if u := catch(func() {
		r = c.lookup(ds, ch, &Use{Object: object, Entry: entry, Exit: exit, Time: at.In(ds.tz)})
	}); u != nil {
		return Dec{}, false, u
	}
	if r == nil {
		return Dec{}, false, nil
	}
	return r.amount, true, nil
}

// HasPair says whether any row of an od charge prices the trip from entry
// to exit (either way unless the charge is directed), for any vehicle.
func (ds *Dataset) HasPair(charge, entry, exit string) bool {
	ch := ds.charges[charge]
	if ch == nil {
		return false
	}
	for _, r := range ch.rows {
		a, _ := r.str("entry")
		b, _ := r.str("exit")
		if (a == entry && b == exit) || (!ch.Directed && a == exit && b == entry) {
			return true
		}
	}
	return false
}

// InTimeClass says whether the time is in the time class; an error says
// the data does not decide it.
func (ds *Dataset) InTimeClass(id string, t time.Time) (in bool, err error) {
	if u := catch(func() { in = ds.inTimeClass(id, t.In(ds.tz)) }); u != nil {
		return false, u
	}
	return in, nil
}

// TimeClass is the time class with the id, or nil.
func (ds *Dataset) TimeClass(id string) *TimeClass { return ds.times[id] }

// RowObjects lists, for each object a charge has rows for, the time
// classes of those rows ("" for a row without one).
func (ch *Charge) RowObjects() map[string][]string {
	out := map[string][]string{}
	for _, r := range ch.rows {
		o, _ := r.str("object")
		if o == "" {
			continue
		}
		tc, _ := r.str("time_class")
		out[o] = append(out[o], tc)
	}
	return out
}

// RowValues is a row's value in each column.
func (ch *Charge) RowValues(n int) map[string]any {
	if n < 0 || n >= len(ch.rows) {
		return nil
	}
	return ch.rows[n].vals
}

// Classify is the vehicle's class in each class set (6.6.3): "" where it
// is in none, an error where a parameter the set tests is missing.
func (ds *Dataset) Classify(vehicle map[string]any) (map[string]string, error) {
	out := map[string]string{}
	var err error
	for set, c := range ds.classify(vehicle) {
		if c.unk != nil && err == nil {
			err = c.unk
		}
		out[set] = c.id
	}
	return out, err
}

// Class is the vehicle class with the id, or nil.
func (ds *Dataset) Class(id string) *Class { return ds.classes[id] }

// SetOf is the class set of a class.
func (ds *Dataset) SetOf(class string) string { return ds.setOf[class] }

// Charges are the dataset's charges in order.
func (ds *Dataset) Charges() []*Charge {
	out := make([]*Charge, len(ds.Doc.Charges))
	for i := range ds.Doc.Charges {
		out[i] = &ds.Doc.Charges[i]
	}
	return out
}

// Objects are the dataset's objects in order.
func (ds *Dataset) Objects() []*Object {
	out := make([]*Object, len(ds.Doc.Objects))
	for i := range ds.Doc.Objects {
		out[i] = &ds.Doc.Objects[i]
	}
	return out
}

// Rater prices single uses for one vehicle, classifying it once.
type Rater struct {
	ds *Dataset
	c  *Calc
}

// Rater is a Rater for the vehicle paying by the given means.
func (ds *Dataset) Rater(vehicle map[string]any, payment []string) *Rater {
	c := &Calc{ds: map[string]*Dataset{ds.ID: ds}, usage: &Usage{Vehicle: vehicle, Payment: payment}, vehicle: vehicle, complete: true}
	c.vclass, c.held = ds.classify(vehicle), c.heldOf(ds)
	return &Rater{ds, c}
}

// Rate is Dataset.Rate with the Rater's vehicle.
func (r *Rater) Rate(charge, object, entry, exit string, at time.Time) (amount Dec, ok bool, err error) {
	ch := r.ds.charges[charge]
	if ch == nil {
		return Dec{}, false, nil
	}
	var rw *row
	if u := catch(func() {
		rw = r.c.lookup(r.ds, ch, &Use{Object: object, Entry: entry, Exit: exit, Time: at.In(r.ds.tz)})
	}); u != nil {
		return Dec{}, false, u
	}
	if rw == nil {
		return Dec{}, false, nil
	}
	return rw.amount, true, nil
}

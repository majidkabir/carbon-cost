package rates

import "testing"

func TestTruckValidate(t *testing.T) {
	if err := (Truck{MaxMassKg: 40000, Axles: 5, Euro: 6, CO2Class: 1}).Validate(); err != nil {
		t.Error(err)
	}
	for _, tr := range []Truck{{Axles: 5, Euro: 6, CO2Class: 1}, {MaxMassKg: 1, Axles: 1, CO2Class: 1},
		{MaxMassKg: 1, Axles: 2, Euro: 7, CO2Class: 1}, {MaxMassKg: 1, Axles: 2, CO2Class: 6}} {
		if tr.Validate() == nil {
			t.Errorf("%+v: want an error", tr)
		}
	}
}

func TestValidTime(t *testing.T) {
	for s, ok := range map[string]bool{"00:00": true, "23:59": true, "24:00": false, "7:5": true, "": false, "12": false} {
		if (ValidTime(s) == nil) != ok {
			t.Errorf("%q: valid %v", s, !ok)
		}
	}
}

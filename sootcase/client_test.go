package sootcase

import (
	"encoding/json"
	"testing"
)

// A place on the prime meridian keeps its longitude of 0.
func TestLocationZeroCoordinate(t *testing.T) {
	for _, tc := range []struct {
		l    Location
		want string
	}{
		{Location{Lat: 51.48, Lon: 0}, `{"lat":51.48,"lon":0}`},
		{Location{Name: "x", Lat: 0, Lon: 9.5}, `{"name":"x","lat":0,"lon":9.5}`},
		{Location{Code: "DEHAM"}, `{"code":"DEHAM"}`},
	} {
		if b, _ := json.Marshal(tc.l); string(b) != tc.want {
			t.Errorf("%+v: %s; want %s", tc.l, b, tc.want)
		}
	}
}

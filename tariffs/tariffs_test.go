package tariffs

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"testing"
	"time"
)

func TestLoad(t *testing.T) {
	s, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	kinds := map[string]int{}
	for _, d := range s.All {
		kinds[d.Kind]++
	}
	if kinds[Toll] < 100 || kinds[Crossings] < 10 || kinds[Zone] < 2 || kinds[FuelCO2] < 10 {
		t.Errorf("kinds %v", kinds)
	}
	if d, ok := s.Find("NO", time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)); !ok || d.Scheme != "no" {
		t.Errorf("NO: %v %v", d, ok)
	}
	if !s.Regional("BE") || s.Regional("DE") {
		t.Error("regional")
	}
}

// index.json lists every dataset as it is (tools/orct/convert.py --index).
func TestIndex(t *testing.T) {
	b, err := files.ReadFile("data/index.json")
	if err != nil {
		t.Fatal(err)
	}
	var idx struct {
		Datasets []struct{ ID, File, SHA256 string }
	}
	if err := json.Unmarshal(b, &idx); err != nil {
		t.Fatal(err)
	}
	s, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	listed := map[string]bool{}
	for _, e := range idx.Datasets {
		raw, ok := s.Raw(e.File)
		if !ok {
			t.Errorf("index lists %s: no such dataset", e.File)
			continue
		}
		if sum := sha256.Sum256(raw); hex.EncodeToString(sum[:]) != e.SHA256 {
			t.Errorf("%s: sha256 differs from the index; run tools/orct/convert.py --index tariffs/data", e.File)
		}
		listed[e.File] = true
	}
	for _, d := range s.All {
		if !listed[d.File] {
			t.Errorf("%s not in index.json; run tools/orct/convert.py --index tariffs/data", d.File)
		}
	}
}

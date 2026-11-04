package cost

import (
	"testing"

	"github.com/majidkabir/carbon-cost/ferries"
	"github.com/majidkabir/carbon-cost/roads"
	"github.com/majidkabir/sootcase/pkg/borders"
)

func TestRoute(t *testing.T) {
	ix, err := borders.Default()
	if err != nil {
		t.Fatal(err)
	}
	fd, err := ferries.Load()
	if err != nil {
		t.Fatal(err)
	}
	// Copenhagen - Rødby, ferry to Puttgarden, Lübeck - Hamburg.
	path := [][2]float64{{12.57, 55.68}, {11.9, 55.2}, {11.4, 54.7}, {11.3522, 54.6556}, {11.29, 54.58}, {11.2275, 54.5003},
		{10.69, 53.87}, {9.99, 53.55}}
	runs := Route(ix, path, &fd)
	var got []string
	for _, r := range runs {
		got = append(got, r.Kind+":"+r.Country)
	}
	want := []string{"road:DK", "ferry:", "road:DE"}
	if len(got) != len(want) {
		t.Fatalf("runs %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("runs %v, want %v", got, want)
		}
	}
	if runs[0].Points[len(runs[0].Points)-1] != runs[1].Points[0] || len(runs[1].Points) != 3 {
		t.Errorf("runs don't join at the terminal: %v", runs)
	}
	if runs[1].Km < 18 || runs[1].Km > 20 {
		t.Errorf("ferry km %.1f, want about 19", runs[1].Km)
	}
	if Route(nil, path, &fd) != nil || Route(ix, path[:1], &fd) != nil {
		t.Error("no index or no line should give no route")
	}
	// Without ferry data the crossing counts for the nearest coast.
	if r := Route(ix, path, nil); r[0].Country != "DK" || r[len(r)-1].Country != "DE" {
		t.Errorf("without ferries: %v", r)
	}
}

func TestRoadKmSums(t *testing.T) {
	rx, err := roads.Default()
	if err != nil {
		t.Fatal(err)
	}
	// The M1 west of Budapest, near Biatorbágy: an expressway in toll
	// sections.
	runs := []Run{{Kind: "road", Country: "HU", Points: [][2]float64{{18.83, 47.47}, {18.80, 47.49}}}}
	path, ok := rx.Classify("HU", runs[0].Points)
	k := RoadKm(rx, runs)["HU"]
	if !ok || k != path {
		t.Errorf("RoadKm %+v, Classify %+v", k, path)
	}
}

package orct

import (
	"encoding/json"
	"os"
	"testing"
)

// The decimal operations against Python's decimal module (cases written by
// a script into a file named by ORCT_DEC_CASES; skipped without it).
func TestDecAgainstPython(t *testing.T) {
	f := os.Getenv("ORCT_DEC_CASES")
	if f == "" {
		t.Skip("ORCT_DEC_CASES not set")
	}
	var cases []map[string]string
	b, _ := os.ReadFile(f)
	if err := json.Unmarshal(b, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		a, b := MustDec(c["a"]), MustDec(c["b"])
		for op, got := range map[string]Dec{"add": a.Add(b), "sub": a.Sub(b), "mul": a.Mul(b)} {
			if want := MustDec(c[op]); got.Cmp(want) != 0 {
				t.Errorf("%s %s %s = %s, want %s", c["a"], op, c["b"], got.Plain(), c[op])
			}
		}
		if w, ok := c["quo"]; ok {
			if got := a.Quo(b); got.Cmp(MustDec(w)) != 0 {
				t.Errorf("%s / %s = %s, want %s", c["a"], c["b"], got.Plain(), w)
			}
		}
	}
}

func TestDecString(t *testing.T) {
	for in, want := range map[string]string{"25.000": "25", "3.10": "3.1", "-0": "0", "0.00": "0", "1E+2": "100", "-0.050": "-0.05", "7": "7"} {
		if got := MustDec(in).String(); got != want {
			t.Errorf("%s: %s, want %s", in, got, want)
		}
	}
	if got := MustDec("27.995").Quantize(MustDec("0.01"), "half_up").Plain(); got != "28.00" {
		t.Errorf("quantize: %s", got)
	}
	if got := MustDec("-0.125").Quantize(MustDec("0.01"), "half_even").Plain(); got != "-0.12" {
		t.Errorf("quantize half_even: %s", got)
	}
	if got := DecFloat(0.1).Plain(); got != "0.1000000000000000055511151231257827021181583404541015625" {
		t.Errorf("DecFloat: %s", got)
	}
}

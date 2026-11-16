package orct

import (
	"fmt"
	"math/big"
	"strings"
)

// Prec is the number of significant digits every result keeps, rounded
// half to even, as the reference calculator's decimal context does.
const Prec = 28

// Dec is a decimal number: coef × 10^exp. The zero value is 0.
type Dec struct {
	coef *big.Int
	exp  int
}

var (
	bigTen = big.NewInt(10)
	pow10s = map[int]*big.Int{}
)

func pow10(n int) *big.Int {
	if p, ok := pow10s[n]; ok {
		return p
	}
	p := new(big.Int).Exp(bigTen, big.NewInt(int64(n)), nil)
	if n < 64 {
		pow10s[n] = p
	}
	return p
}

func (d Dec) c() *big.Int {
	if d.coef == nil {
		return new(big.Int)
	}
	return d.coef
}

// ParseDec reads a decimal literal ("12", "-0.05", "1e-05", "3.0E+2").
func ParseDec(s string) (Dec, error) {
	s = strings.TrimSpace(s)
	exp := 0
	if i := strings.IndexAny(s, "eE"); i >= 0 {
		var e int
		if _, err := fmt.Sscanf(s[i+1:], "%d", &e); err != nil {
			return Dec{}, fmt.Errorf("bad decimal %q", s)
		}
		exp, s = e, s[:i]
	}
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimLeft(s, "+-")
	if i := strings.IndexByte(s, '.'); i >= 0 {
		exp -= len(s) - i - 1
		s = s[:i] + s[i+1:]
	}
	if s == "" {
		return Dec{}, fmt.Errorf("bad decimal")
	}
	c, ok := new(big.Int).SetString(s, 10)
	if !ok {
		return Dec{}, fmt.Errorf("bad decimal %q", s)
	}
	if neg {
		c.Neg(c)
	}
	return Dec{c, exp}.round(), nil
}

// MustDec is ParseDec for literals known to be good.
func MustDec(s string) Dec {
	d, err := ParseDec(s)
	if err != nil {
		panic(err)
	}
	return d
}

// DecInt is the integer n.
func DecInt(n int64) Dec { return Dec{big.NewInt(n), 0} }

// DecFloat is the exact value of a float64, as Decimal(float) gives it.
func DecFloat(f float64) Dec {
	r := new(big.Rat)
	r.SetFloat64(f)
	num, den := new(big.Int).Set(r.Num()), r.Denom()
	exp := 0
	// den is a power of two: multiply by 5^k to make it a power of ten.
	for den.Cmp(big.NewInt(1)) != 0 {
		den = new(big.Int).Quo(den, big.NewInt(2))
		num.Mul(num, big.NewInt(5))
		exp--
	}
	return Dec{num, exp} // exact, not rounded to the context, as Python
}

// round keeps Prec significant digits, half to even.
func (d Dec) round() Dec {
	c := d.c()
	n := len(new(big.Int).Abs(c).String())
	if c.Sign() == 0 || n <= Prec {
		return d
	}
	drop := n - Prec
	return Dec{roundDiv(c, pow10(drop), "half_even"), d.exp + drop}
}

// roundDiv is a/b rounded to an integer by mode.
func roundDiv(a, b *big.Int, mode string) *big.Int {
	q, r := new(big.Int).QuoRem(a, b, new(big.Int))
	if r.Sign() == 0 {
		return q
	}
	neg := (a.Sign() < 0) != (b.Sign() < 0)
	away := func() {
		if neg {
			q.Sub(q, big.NewInt(1))
		} else {
			q.Add(q, big.NewInt(1))
		}
	}
	twice := new(big.Int).Abs(new(big.Int).Lsh(r, 1))
	cmp := twice.Cmp(new(big.Int).Abs(b))
	switch mode {
	case "up":
		away()
	case "down":
	case "half_up":
		if cmp >= 0 {
			away()
		}
	default: // half_even
		if cmp > 0 || (cmp == 0 && q.Bit(0) == 1) {
			away()
		}
	}
	return q
}

func align(a, b Dec) (*big.Int, *big.Int, int) {
	ca, cb := a.c(), b.c()
	switch {
	case a.exp > b.exp:
		return new(big.Int).Mul(ca, pow10(a.exp-b.exp)), cb, b.exp
	case b.exp > a.exp:
		return ca, new(big.Int).Mul(cb, pow10(b.exp-a.exp)), a.exp
	}
	return ca, cb, a.exp
}

// Add is d + e.
func (d Dec) Add(e Dec) Dec {
	x, y, exp := align(d, e)
	return Dec{new(big.Int).Add(x, y), exp}.round()
}

// Sub is d - e.
func (d Dec) Sub(e Dec) Dec {
	x, y, exp := align(d, e)
	return Dec{new(big.Int).Sub(x, y), exp}.round()
}

// Mul is d × e.
func (d Dec) Mul(e Dec) Dec {
	return Dec{new(big.Int).Mul(d.c(), e.c()), d.exp + e.exp}.round()
}

// Quo is d / e, exact where it fits in Prec digits, else rounded half to
// even.
func (d Dec) Quo(e Dec) Dec {
	if e.c().Sign() == 0 {
		panic("orct: division by zero")
	}
	if d.c().Sign() == 0 {
		return Dec{}
	}
	// Scale so the quotient has Prec+1 integer digits at least, then round.
	num, den := d.c(), e.c()
	exp := d.exp - e.exp
	nd := len(new(big.Int).Abs(num).String())
	dd := len(new(big.Int).Abs(den).String())
	shift := Prec + 2 - (nd - dd)
	if shift < 0 {
		shift = 0
	}
	n := new(big.Int).Mul(num, pow10(shift))
	q, r := new(big.Int).QuoRem(n, den, new(big.Int))
	if r.Sign() == 0 {
		return Dec{q, exp - shift}.trim().round()
	}
	// Inexact: round to Prec significant digits, taking the remainder into
	// account (a sticky digit below the last).
	q.Mul(q, bigTen)
	if r.Sign() != 0 {
		if q.Sign() < 0 || (q.Sign() == 0 && (num.Sign() < 0) != (den.Sign() < 0)) {
			q.Sub(q, big.NewInt(1))
		} else {
			q.Add(q, big.NewInt(1))
		}
	}
	return Dec{q, exp - shift - 1}.round()
}

// trim drops trailing zeros of the coefficient (the value is unchanged).
func (d Dec) trim() Dec {
	c := new(big.Int).Set(d.c())
	exp := d.exp
	if c.Sign() == 0 {
		return Dec{c, 0}
	}
	r := new(big.Int)
	for {
		q, m := new(big.Int).QuoRem(c, bigTen, r)
		if m.Sign() != 0 {
			break
		}
		c, exp = q, exp+1
	}
	return Dec{c, exp}
}

// Cmp compares d and e: -1, 0 or 1.
func (d Dec) Cmp(e Dec) int {
	x, y, _ := align(d, e)
	return x.Cmp(y)
}

// Sign is -1, 0 or 1.
func (d Dec) Sign() int { return d.c().Sign() }

// IsInt says whether d is a whole number.
func (d Dec) IsInt() bool {
	t := d.trim()
	return t.exp >= 0 || t.c().Sign() == 0
}

// Quantize rounds d to a multiple of inc by mode (half_up, half_even, up,
// down), with inc's decimal places.
func (d Dec) Quantize(inc Dec, mode string) Dec {
	x, y, _ := align(d, inc)
	k := roundDiv(x, y, mode) // the number of increments
	return Dec{new(big.Int).Mul(k, inc.c()), inc.exp}
}

// Float is d as a float64.
func (d Dec) Float() float64 {
	r := new(big.Rat).SetInt(d.c())
	if d.exp > 0 {
		r.Mul(r, new(big.Rat).SetInt(pow10(d.exp)))
	} else if d.exp < 0 {
		r.Quo(r, new(big.Rat).SetInt(pow10(-d.exp)))
	}
	f, _ := r.Float64()
	return f
}

// Plain is d in fixed notation with its own decimal places ("28.00").
func (d Dec) Plain() string {
	c := d.c()
	neg := c.Sign() < 0
	s := new(big.Int).Abs(c).String()
	if d.exp >= 0 {
		s += strings.Repeat("0", d.exp)
	} else {
		n := -d.exp
		if len(s) <= n {
			s = strings.Repeat("0", n-len(s)+1) + s
		}
		s = s[:len(s)-n] + "." + s[len(s)-n:]
	}
	if neg {
		s = "-" + s
	}
	return s
}

// String is d as the statement writes amounts and quantities: whole
// numbers without decimals, others without trailing zeros ("0" for zero).
func (d Dec) String() string {
	var s string
	if d.IsInt() {
		s = d.trim().Plain()
	} else {
		s = strings.TrimRight(d.Plain(), "0")
	}
	if s == "-0" || s == "" {
		return "0"
	}
	return s
}

// MarshalJSON writes d as a JSON string.
func (d Dec) MarshalJSON() ([]byte, error) { return []byte(`"` + d.String() + `"`), nil }

package cost

import (
	"context"
	"strings"
	"sync"
	"time"

	"github.com/majidkabir/carbon-cost/sootcase"
)

// Sootcase's emission factors, read once in a while per server: a day
// when read, ten minutes when they couldn't be.
var factorCache struct {
	sync.Mutex
	by map[string]cachedFactors
}

type cachedFactors struct {
	f     sootcase.Factors
	ok    bool
	until time.Time
}

func factorsOf(ctx context.Context, c sootcase.Client) (sootcase.Factors, bool) {
	key := strings.TrimRight(c.BaseURL, "/")
	factorCache.Lock()
	defer factorCache.Unlock()
	if e, hit := factorCache.by[key]; hit && time.Now().Before(e.until) {
		return e.f, e.ok
	}
	ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	f, err := c.Factors(ctx)
	e := cachedFactors{f: f, ok: err == nil, until: time.Now().Add(24 * time.Hour)}
	if err != nil {
		e.until = time.Now().Add(10 * time.Minute)
	}
	if factorCache.by == nil {
		factorCache.by = map[string]cachedFactors{}
	}
	factorCache.by[key] = e
	return e.f, e.ok
}

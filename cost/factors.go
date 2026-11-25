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
	by map[string]*cachedFactors
}

type cachedFactors struct {
	sync.Mutex
	f     sootcase.Factors
	ok    bool
	until time.Time
}

func factorsOf(ctx context.Context, c sootcase.Client) (sootcase.Factors, bool) {
	key := strings.TrimRight(c.BaseURL, "/")
	factorCache.Lock()
	if factorCache.by == nil {
		factorCache.by = map[string]*cachedFactors{}
	}
	e := factorCache.by[key]
	if e == nil {
		e = &cachedFactors{}
		factorCache.by[key] = e
	}
	factorCache.Unlock()
	// One read per server at a time: requests to the same server wait for
	// it, others don't.
	e.Lock()
	defer e.Unlock()
	if time.Now().Before(e.until) {
		return e.f, e.ok
	}
	// The read is for all requests, so a client that goes away doesn't end
	// it and its failure isn't kept for the others.
	rctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 20*time.Second)
	defer cancel()
	f, err := c.Factors(rctx)
	e.f, e.ok, e.until = f, err == nil, time.Now().Add(24*time.Hour)
	if err != nil {
		e.until = time.Now().Add(10 * time.Minute)
	}
	return e.f, e.ok
}

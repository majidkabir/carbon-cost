package fx

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

const sample = `<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
	<gesmes:subject>Reference rates</gesmes:subject>
	<Cube>
		<Cube time='2026-11-03'>
			<Cube currency='CZK' rate='24.321'/>
			<Cube currency='CHF' rate='0.9312'/>
		</Cube>
	</Cube>
</gesmes:Envelope>`

func TestParse(t *testing.T) {
	r, err := Parse(strings.NewReader(sample))
	if err != nil {
		t.Fatal(err)
	}
	if r.Date != "2026-11-03" || r.PerEUR["CHF"] != 0.9312 || r.PerEUR["CZK"] != 24.321 {
		t.Errorf("got %+v", r)
	}
	if _, err := Parse(strings.NewReader("<x/>")); err == nil {
		t.Error("want an error for a file without rates")
	}
}

func TestCache(t *testing.T) {
	calls, fail := 0, false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls++
		if fail {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.Write([]byte(sample))
	}))
	defer srv.Close()
	clock := time.Date(2026, 11, 4, 12, 0, 0, 0, time.UTC)
	c := &Cache{URL: srv.URL, now: func() time.Time { return clock }}
	for range 2 {
		if r, err := c.Get(context.Background()); err != nil || r.PerEUR["CHF"] != 0.9312 {
			t.Fatal(r, err)
		}
	}
	if calls != 1 {
		t.Errorf("fetched %d times, want 1", calls)
	}
	clock, fail = clock.Add(7*time.Hour), true
	if r, err := c.Get(context.Background()); err != nil || r.Date != "2026-11-03" || calls != 2 {
		t.Errorf("stale rates should be kept when a refresh fails: %v %v, %d calls", r, err, calls)
	}
}

func TestCacheSingleFlight(t *testing.T) {
	var calls atomic.Int32
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		<-release
		w.Write([]byte(sample))
	}))
	defer srv.Close()
	clock := time.Date(2026, 11, 4, 12, 0, 0, 0, time.UTC)
	c := &Cache{URL: srv.URL, now: func() time.Time { return clock }}
	var wg sync.WaitGroup
	errs := make(chan error, 10)
	for range 10 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if r, err := c.Get(context.Background()); err != nil || r.Date == "" {
				errs <- fmt.Errorf("%v %v", r, err)
			}
		}()
	}
	time.Sleep(50 * time.Millisecond)
	close(release)
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Error(err)
	}
	if n := calls.Load(); n != 1 {
		t.Errorf("fetched %d times, want 1", n)
	}

	// While a refresh of stale rates runs, callers get the stale rates at once.
	clock = clock.Add(7 * time.Hour)
	block := make(chan struct{})
	srv.Config.Handler = http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		<-block
		w.Write([]byte(sample))
	})
	done := make(chan struct{})
	go func() { c.Get(context.Background()); close(done) }()
	time.Sleep(50 * time.Millisecond)
	start := time.Now()
	if r, err := c.Get(context.Background()); err != nil || r.Date != "2026-11-03" || time.Since(start) > time.Second {
		t.Errorf("want stale rates without waiting: %v %v", r, err)
	}
	close(block)
	<-done
}

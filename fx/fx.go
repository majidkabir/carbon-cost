// Package fx gets the euro foreign exchange reference rates the European
// Central Bank publishes each working day around 16:00 CET, for converting
// tolls in other currencies to euros.
package fx

import (
	"context"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"sync"
	"time"
)

// ECBURL is the ECB's daily reference rates.
const ECBURL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

// Source names the rates, for notes.
const Source = "ECB euro foreign exchange reference rates"

// Rates are units of each currency per euro on a date.
type Rates struct {
	Date   string             `json:"date"`
	PerEUR map[string]float64 `json:"per_eur"`
}

// Parse reads the ECB's eurofxref XML.
func Parse(r io.Reader) (Rates, error) {
	var doc struct {
		Cube struct {
			Cube []struct {
				Time  string `xml:"time,attr"`
				Rates []struct {
					Currency string `xml:"currency,attr"`
					Rate     string `xml:"rate,attr"`
				} `xml:"Cube"`
			} `xml:"Cube"`
		} `xml:"Cube"`
	}
	if err := xml.NewDecoder(r).Decode(&doc); err != nil {
		return Rates{}, fmt.Errorf("fx: %w", err)
	}
	if len(doc.Cube.Cube) == 0 {
		return Rates{}, fmt.Errorf("fx: no rates in the file")
	}
	day := doc.Cube.Cube[0]
	out := Rates{Date: day.Time, PerEUR: map[string]float64{}}
	for _, r := range day.Rates {
		v, err := strconv.ParseFloat(r.Rate, 64)
		if err != nil || v <= 0 {
			return Rates{}, fmt.Errorf("fx: bad rate %q for %s", r.Rate, r.Currency)
		}
		out.PerEUR[r.Currency] = v
	}
	return out, nil
}

// Fetch gets the latest rates from url (default ECBURL).
func Fetch(ctx context.Context, hc *http.Client, url string) (Rates, error) {
	if url == "" {
		url = ECBURL
	}
	if hc == nil {
		hc = &http.Client{Timeout: 15 * time.Second}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return Rates{}, err
	}
	resp, err := hc.Do(req)
	if err != nil {
		return Rates{}, fmt.Errorf("fx: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return Rates{}, fmt.Errorf("fx: %s: HTTP %d", url, resp.StatusCode)
	}
	return Parse(io.LimitReader(resp.Body, 1<<20))
}

// Cache keeps the rates for TTL (default 6 hours); on a failed refresh it
// keeps serving the last rates it got.
type Cache struct {
	URL  string
	HTTP *http.Client
	TTL  time.Duration

	mu  sync.Mutex
	r   Rates
	at  time.Time
	now func() time.Time
}

// Get returns the rates, fetching them when the cached ones are stale.
func (c *Cache) Get(ctx context.Context) (Rates, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now
	if c.now != nil {
		now = c.now
	}
	ttl := c.TTL
	if ttl == 0 {
		ttl = 6 * time.Hour
	}
	if c.r.Date != "" && now().Sub(c.at) < ttl {
		return c.r, nil
	}
	r, err := Fetch(ctx, c.HTTP, c.URL)
	if err != nil {
		if c.r.Date != "" {
			return c.r, nil
		}
		return Rates{}, err
	}
	c.r, c.at = r, now()
	return r, nil
}

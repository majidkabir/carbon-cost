// Package site renders public pages on truck tolls from the rate tables
// (package tariffs): a page per country (/tolls/<cc>), an overview
// (/tolls), pages across countries (zero-emission trucks, ETS2 per litre
// of diesel, national CO2 taxes on diesel), share images, a sitemap and
// robots.txt. Every figure comes from the embedded datasets, priced by the
// calculator's own code (package orct), so the pages follow the data the
// workflows commit. Pages are built for the day of the request (rates in
// force and to come move with the date) and kept for that day.
package site

import (
	"bytes"
	"embed"
	"encoding/json"
	"fmt"
	"html/template"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/fx"
	"github.com/majidkabir/carbon-cost/tariffs"
)

//go:embed templates/*.html
var templateFS embed.FS

// DefaultBase is the public address of the service's root.
const DefaultBase = "https://sootcase.org/carbon-cost"

// Site serves the pages.
type Site struct {
	base   string // public URL of the service's root, without a trailing slash
	prefix string // its path, e.g. "/carbon-cost"
	set    *tariffs.Set
	now    func() time.Time
	tmpl   *template.Template

	mu    sync.Mutex
	day   string
	built *built
}

type built struct {
	pages  map[string][]byte // by path under the root, e.g. "/tolls/de"
	cards  map[string]card   // share images, by path
	images map[string][]byte
	paths  []string // the sitemap's
	mod    map[string]string
}

// New prepares the pages for the datasets; base is the service's public
// URL (DefaultBase when empty).
func New(set *tariffs.Set, base string, now func() time.Time) (*Site, error) {
	if base == "" {
		base = DefaultBase
	}
	base = strings.TrimRight(base, "/")
	u, err := url.Parse(base)
	if err != nil || u.Scheme == "" || u.Host == "" {
		return nil, fmt.Errorf("site: public URL %q: want scheme://host[/path]", base)
	}
	if now == nil {
		now = time.Now
	}
	t, err := template.New("").Funcs(template.FuncMap{
		"json": func(v any) template.JS { b, _ := json.Marshal(v); return template.JS(b) },
	}).ParseFS(templateFS, "templates/*.html")
	if err != nil {
		return nil, err
	}
	return &Site{base: base, prefix: strings.TrimRight(u.Path, "/"), set: set, now: now, tmpl: t}, nil
}

// Register adds the pages to the mux.
func (s *Site) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /tolls", s.serve)
	mux.HandleFunc("GET /tolls.png", s.serve)
	mux.HandleFunc("GET /tolls/{$}", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, s.prefix+"/tolls", http.StatusMovedPermanently)
	})
	mux.HandleFunc("GET /tolls/{name}", s.serve)
	mux.HandleFunc("GET /sitemap.xml", s.serve)
	mux.HandleFunc("GET /robots.txt", s.serve)
}

func (s *Site) get() *built {
	day := s.now().UTC().Format(time.DateOnly)
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.built == nil || s.day != day {
		s.built, s.day = s.build(day), day
	}
	return s.built
}

func (s *Site) serve(w http.ResponseWriter, r *http.Request) {
	b := s.get()
	p := r.URL.Path
	switch {
	case p == "/sitemap.xml":
		w.Header().Set("Content-Type", "application/xml; charset=utf-8")
		w.Write(b.pages[p])
		return
	case p == "/robots.txt":
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		fmt.Fprintf(w, "User-agent: *\nAllow: /\nDisallow: /v1/\nSitemap: %s/sitemap.xml\n", s.base)
		return
	case strings.HasSuffix(p, ".png"):
		img, ok := s.image(b, strings.TrimSuffix(p, ".png"))
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "image/png")
		w.Header().Set("Cache-Control", "public, max-age=86400")
		w.Write(img)
		return
	}
	page, ok := b.pages[p]
	if !ok {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "public, max-age=3600")
	w.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; form-action 'none'")
	w.Write(page)
}

func (s *Site) image(b *built, path string) ([]byte, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if img, ok := b.images[path]; ok {
		return img, true
	}
	c, ok := b.cards[path]
	if !ok {
		return nil, false
	}
	img := c.render()
	b.images[path] = img
	return img, true
}

// head is what every page's <head> says.
type Head struct {
	Title, Description, Canonical, Image, Prefix, Path string
	Crumbs                                             []link
	LD, CrumbLD                                        any
}

type link struct{ Name, Href string }

func (s *Site) mkHead(path, title, desc string, ld any, crumbs ...link) Head {
	h := Head{Title: title, Description: desc, Canonical: s.base + path, Image: s.base + path + ".png", Prefix: s.prefix, Path: path,
		Crumbs: crumbs, LD: ld}
	var items []map[string]any
	for i, c := range crumbs {
		items = append(items, map[string]any{"@type": "ListItem", "position": i + 1, "name": c.Name, "item": s.base + strings.TrimPrefix(c.Href, s.prefix)})
	}
	if len(items) > 0 {
		h.CrumbLD = map[string]any{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}
	}
	return h
}

func (s *Site) render(name string, data any) []byte {
	var b bytes.Buffer
	if err := s.tmpl.ExecuteTemplate(&b, name, data); err != nil {
		return []byte("<!DOCTYPE html><title>error</title><p>" + template.HTMLEscapeString(err.Error()))
	}
	return b.Bytes()
}

// toEUR converts an amount at the day's rate: the ERM II central rate for
// DKK, the NBS middle rate for RSD, else the ECB reference rate.
func toEUR(v float64, cur string, day time.Time) (float64, bool) {
	switch cur {
	case "EUR":
		return v, true
	case "DKK":
		return v / cost.DKKPerEUR, true
	case "RSD":
		if r, _, ok := fx.RSDOnDate(day); ok {
			return v / r, true
		}
		return 0, false
	}
	if r, ok := fx.OnDate(day); ok {
		if p := r.PerEUR[cur]; p > 0 {
			return v / p, true
		}
	}
	return 0, false
}

// sitemap lists the pages.
func sitemap(base string, paths []string, mod map[string]string) []byte {
	var b bytes.Buffer
	b.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n" + `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">` + "\n")
	sort.Strings(paths)
	for _, p := range paths {
		fmt.Fprintf(&b, "  <url><loc>%s%s</loc>", base, template.HTMLEscapeString(p))
		if m := mod[p]; m != "" {
			fmt.Fprintf(&b, "<lastmod>%s</lastmod>", m)
		}
		b.WriteString("</url>\n")
	}
	b.WriteString("</urlset>\n")
	return b.Bytes()
}

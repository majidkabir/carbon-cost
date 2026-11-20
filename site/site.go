// Package site renders public pages on truck tolls from the rate tables
// (package tariffs): a page per country (/tolls/<cc>), an overview
// (/tolls), pages across countries (zero-emission trucks, ETS2 per litre
// of diesel, national CO2 taxes on diesel, the EU and UK ETS on ferry
// crossings), share images, a sitemap and
// robots.txt. Every figure comes from the embedded datasets, priced by the
// calculator's own code (package orct), so the pages follow the data the
// workflows commit. Pages are built for the day of the request (rates in
// force and to come move with the date) and kept for that day.
package site

import (
	"bytes"
	"compress/gzip"
	"embed"
	"encoding/json"
	"fmt"
	"html/template"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/majidkabir/carbon-cost/cost"
	"github.com/majidkabir/carbon-cost/ferries"
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
	fd     ferries.Data
	now    func() time.Time
	tmpl   *template.Template
	locs   map[string]*Loc

	mu       sync.Mutex
	day      string
	built    *built
	building bool
}

type built struct {
	pages  map[string][]byte // gzipped, by path under the root, e.g. "/tolls/de"
	cards  map[string]card   // share images, by path
	images map[string][]byte // the share images drawn so far (at most maxImages)
	paths  []string          // the sitemap's
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
		// stop ends a sentence, unless it ends in a date's own full stop ("1. srpnja 2024.").
		"stop": func(s string) string {
			if strings.HasSuffix(s, ".") {
				return s
			}
			return s + "."
		},
	}).ParseFS(templateFS, "templates/*.html")
	if err != nil {
		return nil, err
	}
	locs, err := loadLocs()
	if err != nil {
		return nil, err
	}
	fd, err := ferries.Load()
	if err != nil {
		return nil, err
	}
	return &Site{base: base, prefix: strings.TrimRight(u.Path, "/"), set: set, fd: fd, now: now, tmpl: t, locs: locs}, nil
}

// Register adds the pages to the mux.
func (s *Site) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /tolls", s.serve)
	mux.HandleFunc("GET /tolls.png", s.serve)
	mux.HandleFunc("GET /tolls/{$}", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, s.prefix+"/tolls", http.StatusMovedPermanently)
	})
	mux.HandleFunc("GET /tolls/{name}", s.serve)
	for code := range s.locs {
		if code == "en" {
			continue
		}
		mux.HandleFunc("GET /"+code+"/tolls", s.serve)
		mux.HandleFunc("GET /"+code+"/tolls.png", s.serve)
		mux.HandleFunc("GET /"+code+"/tolls/{name}", s.serve)
	}
	mux.HandleFunc("GET /sitemap.xml", s.serve)
	mux.HandleFunc("GET /robots.txt", s.serve)
}

func (s *Site) get() *built {
	day := s.now().UTC().Format(time.DateOnly)
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.built == nil {
		s.built, s.day = s.build(day), day
	} else if s.day != day && !s.building {
		// A new day: keep serving the day before while the new pages build.
		s.building = true
		go func() {
			b := s.build(day)
			s.mu.Lock()
			s.built, s.day, s.building = b, day, false
			s.mu.Unlock()
		}()
	}
	return s.built
}

// Warm builds the pages in the background, so the first visitor doesn't
// wait for them.
func (s *Site) Warm() { go s.get() }

// gz compresses a page; pages are kept compressed.
func gz(b []byte) []byte {
	var out bytes.Buffer
	w, _ := gzip.NewWriterLevel(&out, gzip.BestCompression)
	w.Write(b)
	w.Close()
	return out.Bytes()
}

// writePage sends a gzipped page as is to clients that take gzip, else
// unzipped.
func writePage(w http.ResponseWriter, r *http.Request, page []byte) {
	w.Header().Add("Vary", "Accept-Encoding")
	if strings.Contains(r.Header.Get("Accept-Encoding"), "gzip") {
		w.Header().Set("Content-Encoding", "gzip")
		w.Write(page)
		return
	}
	zr, err := gzip.NewReader(bytes.NewReader(page))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	io.Copy(w, zr)
}

func (s *Site) serve(w http.ResponseWriter, r *http.Request) {
	b := s.get()
	p := r.URL.Path
	switch {
	case p == "/sitemap.xml":
		w.Header().Set("Content-Type", "application/xml; charset=utf-8")
		writePage(w, r, b.pages[p])
		return
	case p == "/robots.txt":
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		fmt.Fprintf(w, "User-agent: *\nAllow: /\nDisallow: %[1]s/v1/places\nDisallow: %[1]s/v1/carbon-cost\nSitemap: %[2]s/sitemap.xml\n", s.prefix, s.base)
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
	writePage(w, r, page)
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
	if len(b.images) >= maxImages {
		clear(b.images)
	}
	b.images[path] = img
	return img, true
}

// maxImages bounds the share images kept drawn; the rest are drawn again
// when asked for (crawlers and caches keep them a day).
const maxImages = 200

// Head is what every page's <head> says, and its language.
type Head struct {
	Title, Description, Canonical, Image, Prefix, Path string
	Crumbs                                             []link
	LD, CrumbLD                                        any
	L                                                  *Loc
	Lang                                               string
	Alternates                                         []alt // the page in other languages (hreflang)
}

type link struct{ Name, Href string }

// alt is a page in a language.
type alt struct{ Lang, Name, Href, Path string }

func (s *Site) mkHead(l *Loc, path, title, desc string, ld any, crumbs ...link) Head {
	h := Head{Title: title, Description: desc, Canonical: s.base + path, Image: s.base + path + ".png", Prefix: s.prefix, Path: path,
		Crumbs: crumbs, LD: ld, L: l, Lang: l.Code}
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

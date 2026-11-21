package site

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"strings"
	"sync"
)

// The share images (og:image, 1200x630) are drawn with Inter's glyphs from
// an atlas (tools/site/font_atlas.py; site/font/OFL.txt).

//go:embed font/atlas.png
var atlasPNG []byte

//go:embed font/atlas.json
var atlasJSON []byte

type face struct {
	Ascent, Descent int
	Glyphs          map[string][7]float64 // x, y, w, h, left, top, advance
}

var (
	atlasOnce  sync.Once
	atlasAlpha *image.Alpha
	faces      map[string]*face
)

func loadAtlas() {
	img, err := png.Decode(bytes.NewReader(atlasPNG))
	if err != nil {
		panic("site: font atlas: " + err.Error())
	}
	b := img.Bounds()
	atlasAlpha = image.NewAlpha(b)
	for y := b.Min.Y; y < b.Max.Y; y++ {
		for x := b.Min.X; x < b.Max.X; x++ {
			g := color.GrayModel.Convert(img.At(x, y)).(color.Gray)
			atlasAlpha.SetAlpha(x, y, color.Alpha{A: g.Y})
		}
	}
	var raw map[string]struct {
		Ascent  int                   `json:"ascent"`
		Descent int                   `json:"descent"`
		Glyphs  map[string][7]float64 `json:"glyphs"`
	}
	if err := json.Unmarshal(atlasJSON, &raw); err != nil {
		panic("site: font atlas: " + err.Error())
	}
	faces = map[string]*face{}
	for k, v := range raw {
		faces[k] = &face{Ascent: v.Ascent, Descent: v.Descent, Glyphs: v.Glyphs}
	}
}

// width is the text's advance in pixels.
func (f *face) width(s string) float64 {
	w := 0.0
	for _, r := range s {
		if g, ok := f.Glyphs[string(r)]; ok {
			w += g[6]
		} else if g, ok := f.Glyphs["?"]; ok {
			w += g[6]
		}
	}
	return w
}

// text draws s with its baseline at y, from x; it returns the pen's end.
func text(dst *image.RGBA, f *face, x, y float64, c color.Color, s string) float64 {
	src := image.NewUniform(c)
	for _, r := range s {
		g, ok := f.Glyphs[string(r)]
		if !ok {
			g = f.Glyphs["?"]
		}
		if g[2] > 0 && g[3] > 0 {
			gx, gy := int(x+g[4]+0.5), int(y-float64(f.Ascent)+g[5]+0.5)
			r := image.Rect(gx, gy, gx+int(g[2]), gy+int(g[3]))
			draw.DrawMask(dst, r, src, image.Point{}, atlasAlpha, image.Pt(int(g[0]), int(g[1])), draw.Over)
		}
		x += g[6]
	}
	return x
}

// wrap breaks s into lines no wider than w.
func (f *face) wrap(s string, w float64) []string {
	var lines []string
	cur := ""
	for _, word := range strings.Fields(s) {
		next := word
		if cur != "" {
			next = cur + " " + word
		}
		if cur != "" && f.width(next) > w {
			lines = append(lines, cur)
			cur = word
			continue
		}
		cur = next
	}
	if cur != "" {
		lines = append(lines, cur)
	}
	return lines
}

// card is what a share image says.
type card struct {
	Kicker   string // small line on top
	Title    string
	Big      string // the headline figure
	BigNote  string // what the figure is for
	Accent   string // a second figure (the CO2 part)
	Footer   string
	AccentCO string // colour of Accent: "carbon" or ""
}

var (
	cInk    = color.RGBA{0x1d, 0x23, 0x27, 0xff}
	cMuted  = color.RGBA{0x5f, 0x6b, 0x73, 0xff}
	cAccent = color.RGBA{0x1f, 0x6f, 0x5c, 0xff}
	cCarbon = color.RGBA{0xb4, 0x53, 0x2a, 0xff}
	cBg     = color.RGBA{0xf6, 0xf8, 0xf9, 0xff}
	cLine   = color.RGBA{0xdd, 0xe3, 0xe7, 0xff}
)

// render draws the card as a 1200x630 PNG.
func (c card) render() []byte {
	atlasOnce.Do(loadAtlas)
	const W, H, pad = 1200, 630, 72.0
	img := image.NewRGBA(image.Rect(0, 0, W, H))
	draw.Draw(img, img.Bounds(), image.NewUniform(cBg), image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(0, 0, 16, H), image.NewUniform(cAccent), image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(int(pad), H-96, W-int(pad), H-94), image.NewUniform(cLine), image.Point{}, draw.Src)
	small, title, big, mid := faces["regular-28"], faces["bold-64"], faces["bold-112"], faces["bold-44"]
	y := pad + 28
	text(img, small, pad, y, cMuted, c.Kicker)
	y += 28
	for _, l := range title.wrap(c.Title, W-2*pad) {
		y += 74
		text(img, title, pad, y, cInk, l)
	}
	if c.Big != "" {
		bf := big
		if big.width(c.Big) > W-2*pad {
			bf = title
		}
		y += 30 + float64(bf.Ascent)
		text(img, bf, pad, y, cAccent, c.Big)
	}
	if c.BigNote != "" {
		y += 54
		text(img, faces["regular-32"], pad, y, cMuted, c.BigNote)
	}
	if c.Accent != "" {
		y += 66
		col := cInk
		if c.AccentCO == "carbon" {
			col = cCarbon
		}
		text(img, mid, pad, y, col, c.Accent)
	}
	text(img, small, pad, H-46, cMuted, c.Footer)
	var b bytes.Buffer
	png.Encode(&b, img)
	return b.Bytes()
}

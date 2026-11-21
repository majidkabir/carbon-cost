// Package apidoc writes the HTTP API's OpenAPI 3.1 description from the Go
// types it sends and takes, with each field's doc comment as its
// description, so the description can't drift from the code
// (cmd/carbon-cost's test compares the served file with a fresh one).
package apidoc

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
)

// sources are the packages whose types the API uses: import path suffix
// and directory under the module root.
var sources = map[string]string{"cost": "cost", "rates": "rates", "sootcase": "sootcase", "tariffs": "tariffs", "main": "cmd/carbon-cost"}

type typeDecl struct {
	pkg  string
	doc  string
	spec *ast.TypeSpec
}

type gen struct {
	types   map[string]typeDecl // "pkg.Name"
	schemas map[string]any
	names   map[string]string // "pkg.Name" -> schema name
}

// Generate reads the module at root and returns the OpenAPI document.
func Generate(root, version string) ([]byte, error) {
	g := &gen{types: map[string]typeDecl{}, schemas: map[string]any{}, names: map[string]string{}}
	fset := token.NewFileSet()
	for pkg, dir := range sources {
		files, err := filepath.Glob(filepath.Join(root, dir, "*.go"))
		if err != nil {
			return nil, err
		}
		for _, f := range files {
			if strings.HasSuffix(f, "_test.go") {
				continue
			}
			src, err := os.ReadFile(f)
			if err != nil {
				return nil, err
			}
			file, err := parser.ParseFile(fset, f, src, parser.ParseComments)
			if err != nil {
				return nil, err
			}
			for _, d := range file.Decls {
				gd, ok := d.(*ast.GenDecl)
				if !ok || gd.Tok != token.TYPE {
					continue
				}
				for _, s := range gd.Specs {
					ts := s.(*ast.TypeSpec)
					doc := ts.Doc.Text()
					if doc == "" && len(gd.Specs) == 1 {
						doc = gd.Doc.Text()
					}
					g.types[pkg+"."+ts.Name.Name] = typeDecl{pkg: pkg, doc: doc, spec: ts}
				}
			}
		}
	}
	ref := func(t string) (map[string]any, error) { return g.ref(t) }
	req, err := ref("cost.Request")
	if err != nil {
		return nil, err
	}
	res, _ := ref("cost.Response")
	breq, _ := ref("main.BatchRequest")
	bres, _ := ref("main.BatchResponse")
	sum, _ := ref("tariffs.Summary")
	place, _ := ref("sootcase.Place")
	errSchema := map[string]any{"type": "object", "properties": map[string]any{"error": map[string]any{"type": "string"}}, "required": []string{"error"}}
	g.schemas["Error"] = errSchema
	errRef := map[string]any{"$ref": "#/components/schemas/Error"}
	jsonBody := func(s any, desc string) map[string]any {
		return map[string]any{"description": desc, "content": map[string]any{"application/json": map[string]any{"schema": s}}}
	}
	errs := map[string]any{
		"400": jsonBody(errRef, "The request is wrong: its JSON, a field, or a place Sootcase doesn't know."),
		"502": jsonBody(errRef, "Sootcase (routes and emissions) failed or refused this server."),
		"503": jsonBody(errRef, "Sootcase is busy (it limits requests); try again later."),
	}
	with := func(ok map[string]any) map[string]any {
		out := map[string]any{"200": ok}
		for k, v := range errs {
			out[k] = v
		}
		return out
	}
	doc := map[string]any{
		"openapi": "3.1.0",
		"info": map[string]any{
			"title":       "carbon-cost",
			"version":     version,
			"description": "What carbon and road charges a truck trip pays, per country and per charge, with the carbon part apart. Rates come from the laws and official tariffs (each result names its datasets and sources); routes, km by country and emissions from Sootcase. Generated from the Go types (internal/apidoc).",
			"license":     map[string]any{"name": "MIT", "identifier": "MIT"},
		},
		"paths": map[string]any{
			"/v1/carbon-cost": map[string]any{"post": map[string]any{
				"summary":     "Price one trip",
				"operationId": "price",
				"requestBody": map[string]any{"required": true, "content": map[string]any{"application/json": map[string]any{"schema": req}}},
				"responses":   with(jsonBody(res, "The priced trip. Check complete: when false, missing lists the charges the total leaves out.")),
			}},
			"/v1/carbon-cost/batch": map[string]any{"post": map[string]any{
				"summary":     "Price up to 100 trips",
				"operationId": "priceBatch",
				"requestBody": map[string]any{"required": true, "content": map[string]any{"application/json": map[string]any{"schema": breq}}},
				"responses":   with(jsonBody(bres, "Each trip's result or error, in the order asked.")),
			}},
			"/v1/rates": map[string]any{"get": map[string]any{
				"summary":     "List the rate datasets (ORCT)",
				"operationId": "listRates",
				"responses":   map[string]any{"200": jsonBody(map[string]any{"type": "array", "items": sum}, "Every dataset, past, current and future.")},
			}},
			"/v1/rates/{cc}/{file}": map[string]any{"get": map[string]any{
				"summary":     "One dataset, as published (ORCT 0.3)",
				"operationId": "getRates",
				"parameters": []any{
					map[string]any{"name": "cc", "in": "path", "required": true, "schema": map[string]any{"type": "string"}, "description": "Country code, lower case (e.g. dk)."},
					map[string]any{"name": "file", "in": "path", "required": true, "schema": map[string]any{"type": "string"}, "description": "The dataset's file (e.g. dk-2026-01-01.orct.json), as /v1/rates lists it."},
				},
				"responses": map[string]any{
					"200": jsonBody(map[string]any{"type": "object", "description": "An ORCT dataset: https://github.com/majidkabir/orct"}, "The dataset."),
					"404": jsonBody(errRef, "No such dataset."),
				},
			}},
			"/v1/places": map[string]any{"get": map[string]any{
				"summary":     "Find a place to start or end a trip",
				"operationId": "places",
				"parameters":  []any{map[string]any{"name": "q", "in": "query", "required": true, "schema": map[string]any{"type": "string", "minLength": 2, "maxLength": 100}, "description": "A city, port, code (UN/LOCODE, IATA) or lat,lon."}},
				"responses": map[string]any{
					"200": jsonBody(map[string]any{"type": "object", "properties": map[string]any{"places": map[string]any{"type": "array", "items": place}}}, "Up to 8 places, best first."),
					"502": errs["502"],
				},
			}},
		},
		"components": map[string]any{"schemas": g.schemas},
	}
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", " ")
	if err := enc.Encode(doc); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

// ref is a reference to the named type's schema, made the first time.
func (g *gen) ref(full string) (map[string]any, error) {
	if n, ok := g.names[full]; ok {
		return map[string]any{"$ref": "#/components/schemas/" + n}, nil
	}
	td, ok := g.types[full]
	if !ok {
		return nil, fmt.Errorf("apidoc: no type %s", full)
	}
	name := td.spec.Name.Name
	pkg, _, _ := strings.Cut(full, ".")
	if pkg != "cost" && pkg != "main" {
		name = strings.ToUpper(pkg[:1]) + pkg[1:] + name // RatesSource, TariffsSource, SootcasePlace
	}
	g.names[full] = name
	g.schemas[name] = nil // reserved while it's made (recursive types)
	s, err := g.schemaOf(td, td.spec.Type)
	if err != nil {
		return nil, err
	}
	if d := clean(td.doc); d != "" {
		s["description"] = d
	}
	g.schemas[name] = s
	return map[string]any{"$ref": "#/components/schemas/" + name}, nil
}

func (g *gen) schemaOf(td typeDecl, e ast.Expr) (map[string]any, error) {
	switch t := e.(type) {
	case *ast.Ident:
		switch t.Name {
		case "string":
			return map[string]any{"type": "string"}, nil
		case "bool":
			return map[string]any{"type": "boolean"}, nil
		case "int", "int64", "int32":
			return map[string]any{"type": "integer"}, nil
		case "float64", "float32":
			return map[string]any{"type": "number"}, nil
		case "any":
			return map[string]any{}, nil
		}
		return g.ref(td.pkg + "." + t.Name)
	case *ast.SelectorExpr:
		pkg := t.X.(*ast.Ident).Name
		if pkg == "json" && t.Sel.Name == "RawMessage" {
			return map[string]any{}, nil
		}
		return g.ref(pkg + "." + t.Sel.Name)
	case *ast.StarExpr:
		return g.schemaOf(td, t.X)
	case *ast.ArrayType:
		items, err := g.schemaOf(td, t.Elt)
		if err != nil {
			return nil, err
		}
		s := map[string]any{"type": "array", "items": items}
		if t.Len != nil {
			if n, ok := t.Len.(*ast.BasicLit); ok {
				s["minItems"], s["maxItems"] = json.Number(n.Value), json.Number(n.Value)
			}
		}
		return s, nil
	case *ast.MapType:
		v, err := g.schemaOf(td, t.Value)
		if err != nil {
			return nil, err
		}
		return map[string]any{"type": "object", "additionalProperties": v}, nil
	case *ast.StructType:
		props, req := map[string]any{}, []string{}
		for _, f := range t.Fields.List {
			if len(f.Names) == 0 || !f.Names[0].IsExported() || f.Tag == nil {
				continue
			}
			tag := reflect.StructTag(strings.Trim(f.Tag.Value, "`")).Get("json")
			name, opts, _ := strings.Cut(tag, ",")
			if name == "-" || name == "" {
				continue
			}
			s, err := g.schemaOf(td, f.Type)
			if err != nil {
				return nil, err
			}
			doc := clean(f.Doc.Text())
			if doc == "" {
				doc = clean(f.Comment.Text())
			}
			if doc != "" {
				if _, isRef := s["$ref"]; isRef {
					s = map[string]any{"allOf": []any{s}, "description": doc}
				} else {
					s["description"] = doc
				}
			}
			props[name] = s
			if !strings.Contains(opts, "omitempty") {
				req = append(req, name)
			}
		}
		sort.Strings(req)
		out := map[string]any{"type": "object", "properties": props, "additionalProperties": false}
		if len(req) > 0 {
			out["required"] = req
		}
		return out, nil
	}
	return nil, fmt.Errorf("apidoc: %s: can't describe %T", td.spec.Name.Name, e)
}

// clean makes a doc comment one paragraph.
func clean(s string) string { return strings.Join(strings.Fields(s), " ") }

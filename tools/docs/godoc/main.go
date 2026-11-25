// Command godoc checks that the module's Go code is documented: every
// exported function, method, type, variable and constant has a doc
// comment, and every exported field of an exported struct has one, or a
// line comment, or is named in the comment of a field before it ("TTWKg
// and WTWKg are ...") or in its type's comment. A struct that mirrors a
// specification's JSON says so in its comment ("Each field is the member
// its JSON tag names", with the clause): its tagged fields need no
// comment of their own.
//
// Run from the repository root: go run ./tools/docs/godoc
package main

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"strings"
)

// mirror marks a struct whose fields are a specification's JSON members.
const mirror = "Each field is the member its JSON tag names"

func main() {
	var bad []string
	report := func(fset *token.FileSet, pos token.Pos, what string) {
		bad = append(bad, fmt.Sprintf("%s: %s has no doc comment", fset.Position(pos), what))
	}
	err := filepath.WalkDir(".", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if n := d.Name(); n == ".git" || n == "testdata" || n == "node_modules" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		fset := token.NewFileSet()
		f, err := parser.ParseFile(fset, p, nil, parser.ParseComments)
		if err != nil {
			return err
		}
		for _, decl := range f.Decls {
			switch d := decl.(type) {
			case *ast.FuncDecl:
				if !d.Name.IsExported() || d.Doc != nil {
					continue
				}
				if d.Recv != nil {
					if t := recvType(d.Recv.List[0].Type); t == "" || !ast.IsExported(t) {
						continue // a method of an unexported type isn't in the package's docs
					} else {
						report(fset, d.Pos(), t+"."+d.Name.Name)
					}
					continue
				}
				report(fset, d.Pos(), d.Name.Name)
			case *ast.GenDecl:
				for _, spec := range d.Specs {
					switch s := spec.(type) {
					case *ast.TypeSpec:
						if !s.Name.IsExported() {
							continue
						}
						doc := text(s.Doc)
						if doc == "" {
							doc = text(d.Doc)
						}
						if doc == "" {
							report(fset, s.Pos(), s.Name.Name)
						}
						if st, ok := s.Type.(*ast.StructType); ok {
							fields(fset, s.Name.Name, doc, st, report)
						}
					case *ast.ValueSpec:
						if d.Doc != nil || s.Doc != nil || s.Comment != nil {
							continue
						}
						for _, n := range s.Names {
							if n.IsExported() {
								report(fset, n.Pos(), n.Name)
							}
						}
					}
				}
			}
		}
		return nil
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	for _, b := range bad {
		fmt.Println(b)
	}
	if len(bad) > 0 {
		fmt.Printf("%d undocumented\n", len(bad))
		os.Exit(1)
	}
	fmt.Println("every exported name is documented")
}

// fields checks a struct's exported fields.
func fields(fset *token.FileSet, typ, doc string, st *ast.StructType, report func(*token.FileSet, token.Pos, string)) {
	group := ""
	for _, f := range st.Fields.List {
		if f.Doc != nil {
			group = text(f.Doc)
		}
		if f.Doc != nil || f.Comment != nil {
			continue
		}
		tagged := false
		if f.Tag != nil {
			name, _, _ := strings.Cut(reflect.StructTag(strings.Trim(f.Tag.Value, "`")).Get("json"), ",")
			tagged = name != "" && name != "-"
		}
		for _, n := range f.Names {
			if !n.IsExported() || names(group, n.Name) || names(doc, n.Name) || tagged && strings.Contains(doc, mirror) {
				continue
			}
			report(fset, n.Pos(), typ+"."+n.Name)
		}
	}
}

func recvType(e ast.Expr) string {
	switch t := e.(type) {
	case *ast.StarExpr:
		return recvType(t.X)
	case *ast.IndexExpr:
		return recvType(t.X)
	case *ast.Ident:
		return t.Name
	}
	return ""
}

func text(g *ast.CommentGroup) string {
	if g == nil {
		return ""
	}
	return strings.Join(strings.Fields(g.Text()), " ")
}

// names says whether a comment names the identifier as a word.
func names(comment, ident string) bool {
	for _, w := range strings.FieldsFunc(comment, func(r rune) bool {
		return !(r == '_' || r >= '0' && r <= '9' || r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z')
	}) {
		if w == ident {
			return true
		}
	}
	return false
}

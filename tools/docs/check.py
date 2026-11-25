#!/usr/bin/env python3
"""Checks the code documentation (docs/code/*.md) against the code.

Every name in backticks must exist:
- a path (has a "/" or a file extension): the file or directory, with
  <cc>, <lang>, {cc} and the like as wildcards; one outside the
  repository's top directories (a file a tool writes, a module, an image)
  must at least be named in the code;
- an HTTP route ("GET /v1/rates", "/tolls/<cc>"): its path in the Go code;
- a command flag ("-addr"): the flag in cmd/carbon-cost;
- a Go name ("Calculate", "Calculator.trip", "cost.Request"): its
  definition, a func, method, type, var, const or struct field;
- a workflow ("Tables data"): a workflow of that name;
- anything else (JSON fields, environment variables, values): the text
  somewhere in the repository's code or data.
Every relative link must name a file that exists.

Run from the repository root: python3 tools/docs/check.py
"""

import glob
import os
import re
import sys

DOCS = "docs/code"
SKIP_DIRS = {".git", "node_modules"}
CODE_EXT = (".go", ".py", ".yml", ".yaml", ".json", ".html", ".sh", ".md", ".txt", ".csv", ".js")


def files(ext):
    out = []
    for root, dirs, names in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if n.endswith(ext):
                out.append(os.path.join(root, n)[2:])
    return out


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def go_index():
    """Names defined in the module's Go code, by package directory."""
    defs = {}  # dir -> set of names (funcs, types, vars, consts, fields)
    methods = {}  # (dir, type) -> set of methods
    types = {}  # type -> set of dirs
    text = {}  # dir -> all source text
    pkgnames = {}  # package clause name -> dirs
    for p in files(".go"):
        d = os.path.dirname(p)
        src = read(p)
        m = re.search(r"^package (\w+)", src, re.M)
        if m and not m.group(1).endswith("_test"):
            pkgnames.setdefault(m.group(1), set()).add(d)
        text[d] = text.get(d, "") + src
        names = defs.setdefault(d, set())
        for m in re.finditer(r"^func (\w+)\s*[\[(]", src, re.M):
            names.add(m.group(1))
        for m in re.finditer(r"^func \(\w*\s*\*?(\w+)(?:\[[^\]]*\])?\) (\w+)\(", src, re.M):
            methods.setdefault((d, m.group(1)), set()).add(m.group(2))
        for m in re.finditer(r"^(?:type|var|const) (\w+)", src, re.M):
            names.add(m.group(1))
        for block in re.finditer(r"^(type|var|const) \((.*?)^\)", src, re.M | re.S):
            for m in re.finditer(r"^\t(\w+)", block.group(2), re.M):
                names.add(m.group(1))
        for m in re.finditer(r"^type (\w+) ", src, re.M):
            types.setdefault(m.group(1), set()).add(d)
        for block in re.finditer(r"^type (\w+) struct \{(.*?)^\}", src, re.M | re.S):
            fields = set()
            for f in re.findall(r"^\t(\w+(?:,\s*\w+)*)[ \t]", block.group(2), re.M):
                fields.update(x.strip() for x in f.split(","))
            fields |= set(re.findall(r"^\t\*?(\w+)$", block.group(2), re.M))  # embedded
            methods.setdefault((d, block.group(1)), set()).update(fields)
    return defs, methods, types, text, pkgnames


def main():
    defs, methods, types, gotext, pkgnames = go_index()
    pkgs = {}  # name a doc may use for a package -> dirs
    for d in defs:
        pkgs.setdefault(os.path.basename(d), set()).add(d)
        pkgs.setdefault(d, set()).add(d)
    for n, ds in pkgnames.items():
        pkgs.setdefault(n, set()).update(ds)
    top = set(os.listdir("."))
    all_go = "\n".join(gotext.values())
    corpus = "\n".join(read(p) for p in files(CODE_EXT) if not p.startswith(DOCS + "/"))
    flags = set(re.findall(r'\.(?:String|Bool|Int|Float64|Duration|Var|Func)\w*\([^,]*?,?\s*"([\w-]+)"', gotext.get("cmd/carbon-cost", "")))
    workflows = {}
    for p in glob.glob(".github/workflows/*.yml"):
        m = re.search(r"^name:\s*(.+)$", read(p), re.M)
        if m:
            workflows[m.group(1).strip().strip("'\"")] = p

    def defined(name):
        return any(name in s for s in defs.values()) or any(name in s for s in methods.values())

    def go_name(tok):
        parts = tok.split(".")
        if len(parts) == 1:
            return defined(tok)
        if len(parts) == 2:
            a, b = parts
            if a in pkgs:  # pkg.Name
                return any(b in defs.get(d, set()) for d in pkgs[a])
            for d in types.get(a, ()):  # Type.Method or Type.Field
                if b in methods.get((d, a), set()):
                    return True
            return False
        if len(parts) == 3 and parts[0] in pkgs:  # pkg.Type.Method
            return any(parts[2] in methods.get((d, parts[1]), set()) for d in pkgs[parts[0]])
        return False

    def path_exists(tok):
        tok = tok.rstrip("/")
        pat = re.sub(r"<[^>]+>|\{[^}]+\}", "*", tok)
        if "/" not in tok or tok.split("/")[0] not in top:
            # a bare file name, or a path inside a directory the text names: anywhere
            return bool(glob.glob("**/" + pat, recursive=True))
        return bool(glob.glob(pat))

    def route(tok):
        p = tok.split(" ", 1)[1] if tok.startswith(("GET ", "POST ")) else tok
        if p.startswith("/<lang>"):
            p = p[len("/<lang>"):]
        p = re.split(r"[<{]", p)[0].rstrip("/") or "/"
        return p in all_go

    bad = []
    for doc in sorted(glob.glob(DOCS + "/*.md")):
        src = read(doc)
        body = re.sub(r"^```.*?^```", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.M | re.S)
        for m in re.finditer(r"\]\(([^)#:]+)(?:#[^)]*)?\)", body):
            target = os.path.normpath(os.path.join(os.path.dirname(doc), m.group(1)))
            if not os.path.exists(target):
                bad.append((doc, body[: m.start()].count("\n") + 1, m.group(1), "link to a file that doesn't exist"))
        for m in re.finditer(r"`([^`\n]+)`", body):
            tok = m.group(1).strip()
            line = body[: m.start()].count("\n") + 1
            why = None
            if tok.startswith(("go ", "python3 ", "docker ", "gh ", "git ", "carbon-cost ")):
                for arg in tok.split()[1:]:
                    if arg in (".", "./..."):
                        continue
                    if ("/" in arg or arg.endswith(".py")) and not arg.startswith(("-", "http")) and not path_exists(arg.removeprefix("./").replace("/...", "")):
                        why = "command names a path that doesn't exist"
            elif tok.startswith(("GET /", "POST /")) or (tok.startswith("/") and " " not in tok):
                if not route(tok):
                    why = "route not in the Go code"
            elif re.fullmatch(r"-[a-z][\w-]*", tok):
                if tok[1:] not in flags:
                    why = "no such flag in cmd/carbon-cost"
            elif re.fullmatch(r"[\w.\-]*/[\w./<>{}*\-]*|[\w<>{}*\-]+\.(go|py|yml|json|md|csv|gz|html|txt|sh)", tok):
                if tok.split("/")[0] in top:
                    if not path_exists(tok):
                        why = "path doesn't exist"
                elif not path_exists(tok) and tok not in corpus:
                    # a file in a directory the text names, a file a tool
                    # writes, a module, a repository or an image
                    why = "path not in the repository, nor named in its code"
            elif re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", tok):
                # a JSON path: each name a field
                if not all(f'json:"{p}' in all_go or p in corpus for p in tok.split(".")):
                    why = "JSON field not found"
            elif re.fullmatch(r"[A-Za-z_]\w*(\.\w+){0,2}", tok) and (tok[:1].isupper() or re.search(r"[a-z][A-Z]", tok) or "." in tok) and not re.fullmatch(r"[A-Z0-9_]+", tok):
                # defined in the module, or an outside package's name the code uses
                if not go_name(tok) and not re.search(r"\b" + re.escape(tok) + r"\b", all_go):
                    why = "Go name not defined"
            elif tok in workflows:
                pass
            elif tok not in corpus:
                why = "not found in the code or data"
            if why:
                bad.append((doc, line, tok, why))
    for doc, line, tok, why in bad:
        print(f"{doc}:{line}: `{tok}`: {why}")
    print(f"{len(bad)} problems" if bad else "docs/code: every name checked exists")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

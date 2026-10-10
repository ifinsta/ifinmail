#!/usr/bin/env python3
"""Remove CSS declarations that can never apply because a later rule overrides them.

A declaration is dead when, for every selector of its rule, a LATER rule
declares the same property with the same or higher specificity and an
equal-or-wider media context:

  * the same selector text (later source order wins at equal specificity), or
  * `html.ifinmail-shell <selector>` (the redesign layer, higher specificity).

!important is respected, dark-mode / reduced-motion / print contexts are never
pruned, and duplicate declarations inside one rule (fallbacks such as
`height: 100vh; height: 100dvh`) are left alone.

Usage: prune_css.py [--apply] [--skip-file NAME ...]
Prints a per-file summary; without --apply nothing is written.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

CSS_DIR = Path(__file__).resolve().parents[4] / 'frontend' / 'static' / 'css'
ORDER = [
    'ifinmail-reset.css',
    'ifinmail-utilities.css',
    'ifinmail-layout.css',
    'ifinmail-components.css',
    'ifinmail-admin.css',
    'ifinmail-redesign.css',
]
REDESIGN_PREFIX = 'html.ifinmail-shell '
KEEP_CTX = re.compile(r'prefers-color-scheme|prefers-reduced-motion|print|prefers-contrast')


@dataclass
class Decl:
    prop: str
    value: str
    important: bool
    start: int
    end: int
    dead: bool = False


@dataclass
class Rule:
    file: str
    ctx: str
    selectors: list[str]
    decls: list[Decl]
    start: int
    end: int
    order: int = 0


def skip_ws_comments(s: str, i: int) -> int:
    n = len(s)
    while i < n:
        if s[i].isspace():
            i += 1
        elif s.startswith('/*', i):
            j = s.find('*/', i + 2)
            i = n if j < 0 else j + 2
        else:
            break
    return i


def scan_until(s: str, i: int, stops: str) -> int:
    """Index of the first char in `stops` at depth 0 (parens/brackets/strings/comments skipped)."""
    n, depth = len(s), 0
    while i < n:
        c = s[i]
        if s.startswith('/*', i):
            j = s.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in '"\'':
            q = c
            i += 1
            while i < n and s[i] != q:
                i += 2 if s[i] == '\\' else 1
            i += 1
            continue
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif depth == 0 and c in stops:
            return i
        i += 1
    return n


def match_brace(s: str, i: int) -> int:
    """`i` is at '{'; return index of the matching '}'."""
    n, depth = len(s), 0
    while i < n:
        c = s[i]
        if s.startswith('/*', i):
            j = s.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in '"\'':
            q = c
            i += 1
            while i < n and s[i] != q:
                i += 2 if s[i] == '\\' else 1
            i += 1
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def parse_decls(s: str, a: int, b: int) -> list[Decl]:
    out: list[Decl] = []
    i = a
    while i < b:
        i = skip_ws_comments(s, i)
        if i >= b:
            break
        end = scan_until(s, i, ';')
        if end > b:
            end = b
        chunk = s[i:end]
        colon = chunk.find(':')
        if colon > 0:
            prop = chunk[:colon].strip().lower()
            value = chunk[colon + 1:].strip()
            important = bool(re.search(r'!\s*important\s*$', value, re.I))
            if important:
                value = re.sub(r'!\s*important\s*$', '', value, flags=re.I).strip()
            stop = end + 1 if end < b and s[end] == ';' else end
            out.append(Decl(prop, value, important, i, stop))
        i = end + 1
    return out


def parse(s: str, fname: str, a: int = 0, b: int | None = None, ctx: str = '') -> list[Rule]:
    b = len(s) if b is None else b
    rules: list[Rule] = []
    i = a
    while i < b:
        i = skip_ws_comments(s, i)
        if i >= b:
            break
        stop = scan_until(s, i, '{;')
        if stop >= b:
            break
        prelude = s[i:stop].strip()
        if s[stop] == ';':
            i = stop + 1
            continue
        close = match_brace(s, stop)
        if prelude.startswith('@'):
            name = prelude.split(None, 1)[0].lower()
            if name in ('@media', '@supports', '@layer'):
                rules += parse(s, fname, stop + 1, close, (ctx + ' ' + prelude).strip())
        else:
            sels = [re.sub(r'\s+', ' ', x.strip()) for x in split_selectors(prelude)]
            rules.append(Rule(fname, ctx, sels, parse_decls(s, stop + 1, close), i, close + 1))
        i = close + 1
    return rules


def split_selectors(prelude: str) -> list[str]:
    parts, depth, cur = [], 0, ''
    for c in prelude:
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        if c == ',' and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += c
    parts.append(cur)
    return [p for p in parts if p.strip()]


def main() -> int:
    apply = '--apply' in sys.argv
    skip = {sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == '--skip-file'}
    texts = {f: (CSS_DIR / f).read_text(encoding='utf-8', newline='') for f in ORDER}
    all_rules: list[Rule] = []
    for f in ORDER:
        for r in parse(texts[f], f):
            r.order = len(all_rules)
            all_rules.append(r)

    # cover[(ctx, selector)] -> list of (order, {prop: important})
    cover: dict[tuple[str, str], list[tuple[int, dict[str, bool]]]] = {}
    for r in all_rules:
        props = {d.prop: d.important for d in r.decls}
        for sel in r.selectors:
            key_sel = sel[len(REDESIGN_PREFIX):] if sel.startswith(REDESIGN_PREFIX) else sel
            cover.setdefault((r.ctx, key_sel), []).append((r.order, props))

    def covered(r: Rule, d: Decl) -> bool:
        for sel in r.selectors:
            if sel.startswith(REDESIGN_PREFIX):
                return False
            ok = False
            for ctx in {r.ctx, ''}:
                for order, props in cover.get((ctx, sel), []):
                    if order > r.order and d.prop in props and (props[d.prop] or not d.important):
                        ok = True
                        break
                if ok:
                    break
            if not ok:
                return False
        return True

    removed: dict[str, int] = {}
    for r in all_rules:
        if r.file in skip or r.file == 'ifinmail-redesign.css' or KEEP_CTX.search(r.ctx):
            continue
        seen: dict[str, int] = {}
        for d in r.decls:
            seen[d.prop] = seen.get(d.prop, 0) + 1
        for d in r.decls:
            if seen[d.prop] == 1 and covered(r, d):
                d.dead = True
                removed[r.file] = removed.get(r.file, 0) + 1

    for f in ORDER:
        edits: list[tuple[int, int]] = []
        for r in (x for x in all_rules if x.file == f):
            if r.decls and all(d.dead for d in r.decls):
                edits.append((r.start, r.end))
            else:
                edits += [(d.start, d.end) for d in r.decls if d.dead]
        if apply and edits:
            t = texts[f]
            for a, b in sorted(edits, reverse=True):
                # also eat the line's leading indentation and trailing newline
                a2 = t.rfind('\n', 0, a) + 1
                if t[a2:a].strip() == '':
                    a = a2
                m = re.match(r'[ \t]*\r?\n', t[b:])
                if m:
                    b += m.end()
                t = t[:a] + t[b:]
            t = re.sub(r'(\r?\n){3,}', lambda m: m.group(0)[:2 if '\r' not in m.group(0) else 4], t)
            (CSS_DIR / f).write_text(t, encoding='utf-8', newline='')
        print(f'{f:28} declarations pruned: {removed.get(f, 0):4}  rules emptied: '
              f'{sum(1 for r in all_rules if r.file == f and r.decls and all(d.dead for d in r.decls)):4}')
    print('applied' if apply else 'dry run (use --apply)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

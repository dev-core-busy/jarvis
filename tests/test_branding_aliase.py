#!/usr/bin/env python3
"""Branding-Aliase muessen auf <body> aufgeloest werden (2026-08-18).

DIE REGEL, die dieser Test durchsetzt:

    Wird in einem ``:root``-Block eine Variable deklariert, deren WERT eine der
    Variablen referenziert, die ``branding.js`` per Inline-Style auf **<body>**
    setzt, dann muss dieselbe Deklaration ZUSAETZLICH auf ``body`` stehen.

WARUM: Eine Custom Property wird auf dem Element BERECHNET, auf dem sie
deklariert ist; danach wird nur noch der fertige Wert vererbt. ``:root`` ist
<html> – eine Ebene UEBER <body>. Ein Alias dort friert also auf dem
Jarvis-Standard ein, obwohl die Marke auf <body> laengst gesetzt ist.

Im Browser gemessen (Markenfarbe #b80f2e auf body), VOR dem Fix:
    --accent       #b80f2e                  ✓
    --purple       #9B59B6                  ✗ Jarvis-Violett
    --purple-light #BB86FC                  ✗
    --purple-dark  #6A0DAD                  ✗
    --bubble-user  rgba(155, 89, 182, .45)  ✗ die eigene Chat-Blase
    --shadow-glow  rgba(155, 89, 182, .4)   ✗
NACH dem Fix folgen alle sechs der Markenfarbe; OHNE Branding kommt exakt
dasselbe heraus wie vorher (gegengeprueft).

Derselbe Fehler war am 2026-08-17 bei ``--gradient`` behoben worden – dort
allein. Dieser Test macht daraus eine Regel, damit der naechste Alias nicht
wieder einzeln auffaellt.

    python3 tests/test_branding_aliase.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


BRANDJS = (ROOT / "frontend" / "js" / "branding.js").read_text(encoding="utf-8")

# Die Liste wird AUS branding.js GELESEN, nicht abgetippt: eine zweite Fassung
# liefe beim naechsten neuen Branding-Feld auseinander und der Waechter wuerde
# genau den neuen Fall nicht sehen.
BRAND_VARS = sorted(set(re.findall(r"setProperty\(\s*'(--[\w-]+)'", BRANDJS)))
print("\nVon branding.js auf <body> gesetzt: %s" % ", ".join(BRAND_VARS))
check(len(BRAND_VARS) >= 5, "Branding-Variablen aus branding.js gelesen (%d)" % len(BRAND_VARS))
check("document.body" in BRANDJS, "branding.js setzt sie wirklich auf <body>")


def bloecke(css: str, selektor: str):
    """Alle Deklarationen eines Selektors: {name: wert}."""
    out = {}
    for m in re.finditer(r"(?:^|[\s,}])%s\s*\{(.*?)\}" % re.escape(selektor), css, re.S):
        for z in m.group(1).splitlines():
            d = re.match(r"\s*(--[\w-]+)\s*:\s*(.+?);", z)
            if d:
                out[d.group(1)] = d.group(2).strip()
    return out


DATEIEN = [p for p in list((ROOT / "frontend").rglob("*.css")) + list((ROOT / "frontend").rglob("*.html"))
           if "vendor" not in str(p) and "novnc" not in str(p)]
check(len(DATEIEN) > 10, "CSS/HTML-Dateien gefunden (%d)" % len(DATEIEN))

geprueft = 0
for f in sorted(DATEIEN):
    css = f.read_text(encoding="utf-8", errors="replace")
    root_decl = bloecke(css, ":root")
    if not root_decl:
        continue
    body_decl = bloecke(css, "body")
    for name, wert in root_decl.items():
        if not any(("var(%s)" % b) in wert or ("var(%s," % b) in wert for b in BRAND_VARS):
            continue
        geprueft += 1
        rel = f.relative_to(ROOT)
        check(name in body_decl,
              "%s: %s wird auch auf <body> aufgeloest" % (rel, name),
              "in :root steht '%s', auf body fehlt es" % wert[:44])
        if name in body_decl:
            # Beide Deklarationen muessen DIESELBE Formel tragen – sonst sieht
            # ein Betrachter zwei Wahrheiten und aendert nur eine davon.
            check(body_decl[name] == wert,
                  "%s: %s traegt auf body dieselbe Formel" % (rel, name),
                  "root=%r body=%r" % (wert[:40], body_decl[name][:40]))

check(geprueft >= 6, "es wurden wirklich Alias-Deklarationen geprueft (%d)" % geprueft)

# Gegenprobe in die andere Richtung: die vier bekannten Namen MUESSEN in der
# Pruefung aufgetaucht sein. Ohne das waere der Test gruen, wenn jemand die
# :root-Deklaration ersatzlos loescht und die Aliase damit ganz verschwinden.
CHAT = (ROOT / "frontend" / "css" / "chat.css").read_text(encoding="utf-8")
for name in ("--purple", "--purple-light", "--purple-dark", "--bubble-user"):
    check(name in bloecke(CHAT, "body"), "chat.css: %s steht im body-Block" % name)
THEME = (ROOT / "frontend" / "css" / "theme.css").read_text(encoding="utf-8")
for name in ("--gradient", "--shadow-glow"):
    check(name in bloecke(THEME, "body"), "theme.css: %s steht im body-Block" % name)

print(f"\n{'=' * 62}")
print(f"  {_ok} OK, {_fail} FAIL")
print(f"{'=' * 62}")
sys.exit(1 if _fail else 0)

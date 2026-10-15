#!/usr/bin/env python3
"""Waechter: erzeugte Bilder (``/api/generated/<32 Hex>``) nur MIT Anmeldung.

Bis 2026-10-15 war die Adresse eine Capability-URL ohne Anmeldung: jedes
erzeugte Bild war 30 Tage fuer jeden abrufbar, der die Adresse kannte.
Entscheidung des Betreibers: Anmeldung, sofort, ohne Uebergangsfrist.

  [A] Server (AST ueber main.py): der Endpunkt haengt an
      ``require_auth_or_query`` (Bearer ODER Abruf-Schluessel), Cache privat;
      ``zugang_regel`` fuehrt ihn nicht mehr als oeffentlich.
  [B] Die drei nativen Clients schicken ihr Token beim Bildabruf mit –
      gemessen im RUMPF genau der Funktion, die das Bild holt, ohne Kommentare
      (sonst bestaende der Waechter auf einer Begruendung im Kommentar):
      Android ``GeneratedImage``, Windows-Client ``fetchImageBytes``,
      AI-Maus ``BildHolenAsync``. Fuer Kotlin/Go/C# gibt es hier keinen Parser;
      der Rumpf wird ueber die Klammerebene geschnitten, mit Positivkontrolle.
  Der Browser-Teil (``chatlib._withToken``) steht in
  ``test_generated_anmeldung_ui.js``.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name: str, bed: bool, detail: str = "") -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


# ── [A] Server ──────────────────────────────────────────────────────────────
print("\n[A] Server")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
fn = None
for n in BAUM.body:
    if isinstance(n, ast.AsyncFunctionDef):
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "get" and d.args
                    and isinstance(d.args[0], ast.Constant)
                    and d.args[0].value == "/api/generated/{name}"):
                fn = n
if fn is None:
    abbruch("Route GET /api/generated/{name} nicht gefunden")
check("(Positivkontrolle) Route gefunden: %s" % fn.name, True)

abh = []
for arg, default in zip(fn.args.args[-len(fn.args.defaults):] if fn.args.defaults else [],
                        fn.args.defaults):
    if (isinstance(default, ast.Call) and getattr(default.func, "id", "") == "Depends"
            and default.args and isinstance(default.args[0], ast.Name)):
        abh.append(default.args[0].id)
check("der Endpunkt haengt an require_auth_or_query (Bearer ODER Abruf-Schluessel)",
      "require_auth_or_query" in abh, "Abhaengigkeiten: %s" % abh)
konst = [c.value for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
check("Zwischenspeicher privat, nicht oeffentlich",
      any(s.startswith("private") for s in konst) and not any(s.startswith("public") for s in konst))

ZR = (ROOT / "backend" / "zugang_regel.py").read_text(encoding="utf-8")
zr_baum = ast.parse(ZR)
schluessel = [k for node in ast.walk(zr_baum) if isinstance(node, ast.Dict)
              for k in node.keys if isinstance(k, ast.Tuple) and len(k.elts) == 2
              and all(isinstance(e, ast.Constant) for e in k.elts)]
pfade = {(k.elts[0].value, k.elts[1].value) for k in schluessel}
check("(Positivkontrolle) Zugangsregel gelesen (%d Eintraege)" % len(pfade), len(pfade) > 10)
check("zugang_regel fuehrt /api/generated nicht mehr als Ausnahme",
      ("GET", "/api/generated/{name}") not in pfade)


# ── [B] Native Clients ──────────────────────────────────────────────────────
print("\n[B] Native Clients")


def ohne_kommentare(src: str) -> str:
    """//- und /* */-Kommentare durch Leerzeichen ersetzen (Zeichenketten bleiben)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1]); i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i); j = n if j < 0 else j
            out.append(" " * (j - i)); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j])); i = j
        else:
            out.append(c); i += 1
    return "".join(out)


def rumpf(src: str, kopf_re: str) -> str:
    """Rumpf der Funktion, deren Kopf ``kopf_re`` trifft (Klammerebene)."""
    m = re.search(kopf_re, src)
    if not m:
        return ""
    i = src.find("{", m.end())
    if i < 0:
        return ""
    tiefe = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            tiefe += 1
        elif src[j] == "}":
            tiefe -= 1
            if tiefe == 0:
                return src[i:j + 1]
    return ""


CLIENTS = [
    ("Android GeneratedImage",
     "android/app/src/main/java/info/jarvisai/app/ui/chat/ChatImage.kt",
     r"fun\s+GeneratedImage\s*\(",
     r'header\(\s*"Authorization"\s*,\s*"Bearer \$'),
    ("Windows-Client fetchImageBytes", "windows-app-go/chatimage.go",
     r"func\s+fetchImageBytes\s*\(",
     r'Header\.Set\(\s*"Authorization"\s*,\s*"Bearer "\s*\+'),
    ("AI-Maus BildHolenAsync", "ai-mouse/src/AiMouse/Vision/JarvisClient.cs",
     r"Task<byte\[\]\?>\s+BildHolenAsync\s*\(",
     r'Headers\.Authorization\s*=\s*new\s+AuthenticationHeaderValue\(\s*"Bearer"'),
]
for name, datei, kopf, muster in CLIENTS:
    p = ROOT / datei
    if not p.is_file():
        abbruch("%s fehlt: %s" % (name, datei))
    r = rumpf(ohne_kommentare(p.read_text(encoding="utf-8")), kopf)
    check("(Positivkontrolle) %s: Rumpf geschnitten (%d Zeichen)" % (name, len(r)), len(r) > 80)
    check("%s schickt das Token mit" % name, bool(re.search(muster, r)))

# Go: kein tokenloser Abruf mehr daneben (client.Get umgeht den Kopfsatz)
go = rumpf(ohne_kommentare((ROOT / "windows-app-go/chatimage.go").read_text(encoding="utf-8")),
           r"func\s+fetchImageBytes\s*\(")
check("Windows-Client: kein tokenloses client.Get(url) mehr", "client.Get(" not in go)
cs = rumpf(ohne_kommentare((ROOT / "ai-mouse/src/AiMouse/Vision/JarvisClient.cs").read_text(encoding="utf-8")),
           r"Task<byte\[\]\?>\s+BildHolenAsync\s*\(")
check("AI-Maus: kein tokenloses GetByteArrayAsync mehr", "GetByteArrayAsync(" not in cs)

# Kommentar-Filter selbst: eine Zusage NUR im Kommentar darf nicht zaehlen
probe = 'func f() {\n  // req.Header.Set("Authorization", "Bearer "+t)\n  x := 1\n}'
check("(Positivkontrolle) Kommentar-Filter: Zusage nur im Kommentar zaehlt nicht",
      not re.search(CLIENTS[1][3], rumpf(ohne_kommentare(probe), r"func\s+f\s*\(")))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)

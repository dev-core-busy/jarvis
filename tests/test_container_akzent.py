#!/usr/bin/env python3
"""Container-Kopfzeilen: Titel beim Ueberfahren in der Akzentfarbe – auf ALLEN
Seiten, auch fuer kuenftige Container (Vorgabe des Betreibers 2026-10-31).

Die Regel steht EINMAL in ``frontend/css/theme.css`` (das jede Seite laedt).
Dieser Waechter sorgt dafuer, dass sie nicht von einem neuen Container
unterlaufen wird:

  1. Die Regel existiert, faerbt mit ``var(--accent)`` und greift nur beim
     Ueberfahren (``:hover``) – Positivkontrolle, sonst Exit 2.
  2. Jeder Klapp-Container im Frontend – gefunden nach BAUFORM, nicht nach
     einer gepflegten Liste – steht in der Regel:
       * Kopfzeilen ``<x>-card-head``, ``<x>-sect-head``, ``…-collapse-header``
         (in HTML und in JS-Vorlagen),
       * aufklappbare Abschnitte ``<details class="<x>-sect|<x>-sub">``.
     Eine neue Bauform mit diesem Namensschema faellt hier auf, bis sie in der
     Regel steht.
  3. Jede Seite mit einem solchen Container laedt theme.css.
  4. Die Titel-Elemente der Kopfzeilen sind von der Regel erfasst (h1–h4) –
     gemessen am Markup der Einstellungen (49 Kopfzeilen).

Bewusst NICHT erfasst (Listeneintraege, keine Seitenabschnitte): ``*-job-head``,
``*-log-head``, ``*-block-head``, ``*-dump-head``, Abgabe-Koepfe – und die
namentlichen ``AUSNAHMEN`` unten, jede mit Grund. Gemessen wird je ELEMENT
(alle Klassen zusammen), nicht je Klasse.

    python3 tests/test_container_akzent.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
_ok = _fail = 0


def check(name, cond, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))


def ohne_kommentare(css: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


# ─── 1. Die Regel ────────────────────────────────────────────────────────────
print("\n1. Die Regel in theme.css")
THEME = ohne_kommentare((FRONT / "css" / "theme.css").read_text(encoding="utf-8"))
dunkel = hell = None
for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", THEME):
    sel, rumpf = " ".join(m.group(1).split()), m.group(2)
    if ":hover" not in sel or not ("card-head" in sel or "collapse-header" in sel):
        continue
    mx = re.search(r"color:\s*color-mix\(in srgb,\s*var\(--accent\)\s*(\d+)%,\s*#fff\)", rumpf)
    if mx and "body.light" not in sel:
        dunkel, ANTEIL = sel, int(mx.group(1))
    elif re.search(r"color:\s*var\(--accent\)", rumpf) and "body.light" in sel:
        hell = sel
if dunkel is None or hell is None:
    # Ein BEFUND ueber das Produkt (Regel entfernt oder ihre Farbe), kein
    # Messproblem – also FAIL mit Bilanz, nicht Exit 2 (Register: Guards mit
    # Exit 2 muessen zwei Ursachen trennen).
    check("die Container-Regel steht in theme.css (dunkel aufgehellter Akzent, hell --accent)", False, (dunkel, hell))
    print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
    sys.exit(1)
SEL = dunkel
check("Positivkontrolle: Regel fuer beide Themen gefunden", True, SEL[:100])
# 65 % ist GEMESSEN (schlechtester Fall 4,68:1 ueber fuenf Hausfarben und vier
# dunkle Flaechen); mehr Akzent faellt bei Rot unter 4,5:1.
check("dunkles Thema: Akzent hoechstens 65 % (Rest Weiss – lesbar)", ANTEIL <= 65, ANTEIL)


def klassen_in(teil: str) -> set:
    return set(re.findall(r"\.([a-z][a-z0-9-]*)", teil))


# Kopfzeilen: alles in ':is(...)', dem ':hover >' folgt; Abschnitte: ':is(...) > summary:hover'.
KOEPFE = set()
for m in re.finditer(r":is\(([^)]*)\):hover\s*>", SEL):
    KOEPFE |= klassen_in(m.group(1))
ABSCHNITTE = set()
for m in re.finditer(r":is\(([^)]*)\)\s*>\s*summary:hover", SEL):
    ABSCHNITTE |= klassen_in(m.group(1))
check("Positivkontrolle: Kopfzeilen- und Abschnittsliste gelesen", len(KOEPFE) >= 5 and len(ABSCHNITTE) >= 5,
      (sorted(KOEPFE), sorted(ABSCHNITTE)))
K_HELL = set().union(*[klassen_in(m.group(1)) for m in re.finditer(r":is\(([^)]*)\):hover\s*>", hell)])
A_HELL = set().union(*[klassen_in(m.group(1)) for m in re.finditer(r":is\(([^)]*)\)\s*>\s*summary:hover", hell)])
check("helles und dunkles Thema erfassen DIESELBEN Container", K_HELL == KOEPFE and A_HELL == ABSCHNITTE,
      (sorted(K_HELL ^ KOEPFE), sorted(A_HELL ^ ABSCHNITTE)))
titel = re.search(r"\):hover\s*>\s*:is\(([^)]*)\)", SEL)
TITEL = set(re.findall(r"\bh[1-6]\b", titel.group(1))) if titel else set()
check("Titel-Elemente h1–h4 erfasst", {"h1", "h2", "h3", "h4"} <= TITEL, TITEL)
check("nur beim Ueberfahren (kein Dauerzustand)", SEL.count(":hover") >= 2, SEL[:200])

# ─── 2. Jeder Container im Frontend steht in der Regel ───────────────────────
print("\n2. Jeder Klapp-Container ist erfasst")
KOPF_MUSTER = re.compile(r"^[a-z][a-z0-9]*-(?:card|sect|section)-head(?:er)?$|^[a-z][a-z0-9-]*collapse-header$")
NICHT = re.compile(r"-(?:job|log|block|dump)-head$")
# Namentliche Ausnahmen – eine neue Bauform braucht eine bewusste Entscheidung.
AUSNAHMEN = {
    "instr-card-header": "Listeneintrag je Anweisungsdatei (Name hat eigene Farbe)",
    "mcp-card-header": "Listeneintrag je MCP-Server",
    "welcome-card-head": "Ueberschrift der Willkommenskarte im Chat, klappt nicht",
}
dateien = sorted(FRONT.rglob("*.html")) + sorted((FRONT / "js").glob("*.js"))
dateien = [d for d in dateien if "/vendor/" not in str(d)]
gef_koepfe: dict[str, set] = {}
gef_abschnitte: dict[str, set] = {}
for d in dateien:
    t = d.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"""class(?:Name)?\s*=\s*["'`]([^"'`]+)["'`]""", t):
        toks = m.group(1).split()
        kopf = [k for k in toks if KOPF_MUSTER.match(k) and not NICHT.search(k)]
        if not kopf:
            continue
        # Ein Element zaehlt EINMAL: als die erfasste Klasse, wenn es eine traegt,
        # sonst als seine erste Kopf-Klasse.
        erfasst = [k for k in toks if k in KOEPFE]
        gef_koepfe.setdefault(erfasst[0] if erfasst else kopf[0], set()).add(d.name)
    for m in re.finditer(r"""<details\b[^>]*\bclass\s*=\s*["']([^"']+)["']""", t):
        for k in m.group(1).split():
            if re.search(r"-(?:sect|section|sub)$|^sec-sub$", k):
                gef_abschnitte.setdefault(k, set()).add(d.name)
check("Positivkontrolle: die bekannten Bauformen werden gefunden",
      {"ja-card-head", "em-card-head", "kb-collapse-header"} <= set(gef_koepfe)
      and {"sp-sect", "vm-sect", "sec-sub"} <= set(gef_abschnitte),
      (sorted(gef_koepfe), sorted(gef_abschnitte)))
fehlen_k = {k: sorted(v) for k, v in gef_koepfe.items() if k not in KOEPFE and k not in AUSNAHMEN}
fehlen_a = {k: sorted(v) for k, v in gef_abschnitte.items() if k not in ABSCHNITTE}
check("jede Container-Kopfzeile steht in der Regel", not fehlen_k, fehlen_k)
check("jeder aufklappbare Abschnitt steht in der Regel", not fehlen_a, fehlen_a)
check("jede Ausnahme gibt es noch (sonst ist sie eine tote Freigabe)",
      not [a for a in AUSNAHMEN if a not in gef_koepfe], [a for a in AUSNAHMEN if a not in gef_koepfe])
check("keine tote Klasse in der Regel (jede kommt im Frontend vor)",
      not ((KOEPFE - set(gef_koepfe)) | (ABSCHNITTE - set(gef_abschnitte))),
      sorted((KOEPFE - set(gef_koepfe)) | (ABSCHNITTE - set(gef_abschnitte))))

# ─── 2b. Keine zweite Quelle ─────────────────────────────────────────────────
print("\n2b. Keine Einzelregel neben der zentralen")
KLASSEN = KOEPFE | ABSCHNITTE
quellen_css = [(f.name, f.read_text(encoding="utf-8")) for f in sorted((FRONT / "css").glob("*.css")) if f.name != "theme.css"]
for f in sorted(FRONT.rglob("*.html")):
    for st_ in re.findall(r"<style[^>]*>(.*?)</style>", f.read_text(encoding="utf-8"), flags=re.S):
        quellen_css.append((f.name, st_))
zweit = []
for name, css in quellen_css:
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", ohne_kommentare(css)):
        sel, rumpf = m.group(1), m.group(2)
        if ":hover" in sel and klassen_in(sel) & KLASSEN and re.search(r"(^|[;\s])color\s*:", rumpf):
            zweit.append(f"{name}: {' '.join(sel.split())[:80]}")
check("Positivkontrolle: Seiten-CSS gelesen (Dateien und <style>-Bloecke)", len(quellen_css) > 10, len(quellen_css))
check("keine Seite setzt die Titelfarbe beim Ueberfahren selbst", not zweit, zweit)

# ─── 3. Jede betroffene Seite laedt theme.css ────────────────────────────────
print("\n3. Seiten laden theme.css")
seiten = {s for v in list(gef_koepfe.values()) + list(gef_abschnitte.values()) for s in v if s.endswith(".html")}
ohne = []
for s in sorted(seiten):
    pf = next(FRONT.rglob(s))
    if not re.search(r'href="/static/css/theme\.css\?v=\d+"', pf.read_text(encoding="utf-8")):
        ohne.append(s)
check("Positivkontrolle: Seiten mit Containern gefunden", len(seiten) >= 8, sorted(seiten))
check("jede davon laedt theme.css", not ohne, ohne)

# ─── 4. Titel der Einstellungs-Kopfzeilen sind h1–h4 ─────────────────────────
print("\n4. Titel-Elemente der Einstellungs-Kopfzeilen")
st = (FRONT / "settings.html").read_text(encoding="utf-8")
koepfe = re.findall(r'<div class="[^"]*kb-collapse-header[^"]*"[^>]*>\s*<(\w+)', st)
check("Positivkontrolle: Kopfzeilen in den Einstellungen gefunden", len(koepfe) >= 40, len(koepfe))
fremd = sorted({t for t in koepfe if t not in TITEL})
check("Titel ist jeweils ein erfasstes Element", not fremd, fremd)

print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)

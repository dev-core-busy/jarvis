"""Waechter: die Container der Kachel-Seiten tragen den Schatten der Portal-Kacheln.

Vorgabe 2026-11-15: "den Schatteneffekt der Portal-Kacheln fuer die Container
innerhalb der Kacheln (auch unter Einstellungen -> Container) uebernehmen".

Gemessen wird nicht "steht irgendwo box-shadow", sondern die WIRKUNG an der
Kaskade:
  1. der Bezugswert wird aus der Portal-Kachel GELESEN (`.pt-card` in
     portal.html) – aendert jemand den Kachelschatten, muss dieser Waechter das
     melden, statt einen abgetippten Wert weiter fuer richtig zu halten;
  2. jede Container-Klasse traegt ihn in theme.css;
  3. kein spaeter geladenes Stylesheet derselben Seite (Inline-<style>,
     style.css, jira_addon.css ...) ueberstimmt ihn mit derselben Klasse –
     genau das tat `.wi-section { box-shadow: var(--shadow-sm) }` in wissen.html;
  4. jede Klasse kommt auf ihrer Seite wirklich vor (Markup oder ein Modul der
     Seite) – eine Liste mit toten Namen saehe gruen aus und wirkte nirgends.

Die Liste der Container ist bewusst eine Liste: "Container" ist eine
Gestaltungsentscheidung (Hinweiskaesten IN einer Karte bleiben flach), keine
Eigenschaft, die sich aus dem CSS ableiten liesse.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FE = os.path.join(ROOT, "frontend")

# Klasse -> Seiten, auf denen sie als Container vorkommt
CONTAINER = {
    "cs-card": ["claude"],
    "em-card": ["email"],
    "xp-card": ["excel"],
    "sq-card": ["sql"],
    "sq-schemabar": ["sql"],
    "st-card": ["tracks"],
    "ep": ["api"],
    "ad-search": ["api"],
    "wi-section": ["wissen"],
    "ja-card": ["ai_mouse", "feedback", "jira_addon", "wissensgraph"],
    "ja-sect": ["confluence_addon", "jira_addon"],
    "sup-ai-card": ["support"],
    "kb-section": ["settings"],
}

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def abbruch(grund):
    print(f"ABBRUCH: {grund}")
    sys.exit(2)


def lies(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def ohne_kommentare(css):
    return re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), css, flags=re.S)


def regeln(css):
    """(Selektorliste, Rumpf) je Regel, @media-Bloecke flach mitgenommen."""
    css = ohne_kommentare(css)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = [s.strip() for s in m.group(1).split(",")]
        out.append((sel, m.group(2)))
    return out


def schatten(rumpf):
    m = re.search(r"box-shadow\s*:\s*([^;]+)", rumpf)
    return m.group(1).strip() if m else None


def inline_css(html):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))


def stylesheets(html):
    return re.findall(r'href="/static/css/([A-Za-z0-9_.-]+\.css)\?v=\d+"', html)


# ── 1. Bezugswert aus der Portal-Kachel ─────────────────────────────────
print("\n\033[1m1. Bezugswert\033[0m")
portal = lies(os.path.join(FE, "portal.html"))
bezug = None
for sel, rumpf in regeln(inline_css(portal)):
    if ".pt-card" in sel and schatten(rumpf):
        bezug = schatten(rumpf)
if not bezug:
    abbruch("Schatten der Portal-Kachel (.pt-card) nicht gefunden")
check(f"Portal-Kachel: box-shadow {bezug}", True)

theme = lies(os.path.join(FE, "css", "theme.css"))
theme_regeln = regeln(theme)
# Positivkontrolle der Zerlegung: eine bekannte Regel muss gefunden werden
if not any(".hidden" in s or ":root" in s for s, _ in theme_regeln):
    abbruch("theme.css laesst sich nicht in Regeln zerlegen")

# ── 2. theme.css traegt den Wert fuer jede Klasse ───────────────────────
print("\n\033[1m2. theme.css\033[0m")
for kl in CONTAINER:
    werte = [schatten(r) for s, r in theme_regeln if f".{kl}" in s and schatten(r)]
    check(f".{kl} traegt {bezug}", bezug in werte, f"gefunden: {werte or 'nichts'}")

# ── 3./4. je Seite: kommt vor, wird nicht ueberstimmt ──────────────────
print("\n\033[1m3. Seiten\033[0m")
seiten = sorted({s for v in CONTAINER.values() for s in v})
for name in seiten:
    pfad = os.path.join(FE, f"{name}.html")
    if not os.path.exists(pfad):
        check(f"{name}.html existiert", False)
        continue
    html = lies(pfad)
    blaetter = stylesheets(html)
    check(f"{name}: laedt theme.css", "theme.css" in blaetter)
    # spaeter als theme.css geladen: die weiteren Stylesheets + Inline-<style>
    spaeter = []
    for b in blaetter:
        if b != "theme.css" and os.path.exists(os.path.join(FE, "css", b)):
            spaeter.append((b, lies(os.path.join(FE, "css", b))))
    spaeter.append(("inline", inline_css(html)))
    # Module der Seite (fuer per JS erzeugte Container)
    js = ""
    for m in re.findall(r'src="/static/js/([A-Za-z0-9_.-]+\.js)\?v=\d+"', html):
        p = os.path.join(FE, "js", m)
        if os.path.exists(p):
            js += lies(p)
    for kl, wo in CONTAINER.items():
        if name not in wo:
            continue
        muster = re.compile(r"""(class=["'][^"']*\b|["'\s.]|className\s*=\s*["'])""" + re.escape(kl) + r"""(?![\w-])""")
        check(f"{name}: .{kl} kommt vor", bool(muster.search(html) or muster.search(js)))
        for quelle, css in spaeter:
            for sel, rumpf in regeln(css):
                w = schatten(rumpf)
                if w is None:
                    continue
                for s in sel:
                    if s == f".{kl}" and w != bezug:
                        check(f"{name}: {quelle} ueberstimmt .{kl}", False, f"box-shadow {w}")

print()
ok = sum(res)
print(f"\033[1mErgebnis: {ok} OK, {len(res) - ok} FAIL\033[0m")
sys.exit(0 if all(res) else 1)

#!/usr/bin/env python3
"""Waechter: Abruf-Schluessel statt Sitzungstoken in Datei-Adressen (2026-09-02).

DIE ZUSAGE, die hier gemessen wird: eine weitergegebene Datei-Adresse traegt
kein Merkmal mehr, mit dem sich die SITZUNG des Benutzers uebernehmen laesst.

Nachgewiesen wurde am 2026-09-02, dass das vorher moeglich war: das Token aus
``/api/documents/<cap>.pptx?token=…`` liefert als ``Authorization: Bearer``
``/api/me``, ``/api/chat/sessions``, ``/api/knowledge/groups`` und
``/api/sessions`` je 200 – und lebt 30 Tage ab Ausstellung.

Vier Eigenschaften, jede einzeln:
1. Der Abruf-Schluessel ist als Sitzungstoken WERTLOS (``verify_token`` nimmt
   ihn nicht an) – und zwar schon von der FORM her, nicht durch die
   Reihenfolge irgendwelcher Pruefungen.
2. Er laeuft ab, ist an den Benutzer gebunden und faellt bei jeder Manipulation
   durch (fail-closed).
3. KEINE Stelle im Frontend baut noch eine Adresse mit dem Sitzungstoken –
   geprueft als REGEL ueber alle Dateien, nicht als gepflegte Liste.
4. Jede Seite, die eine solche Stelle laedt, laedt auch ``dlkey.js`` – sonst
   greift dort still der Rueckfall auf das Sitzungstoken.
"""
import ast
import pathlib
import re
import sys
import time
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import quell_ausschnitt  # noqa: E402  (linear statt ast.get_source_segment)

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

_ok = 0
_fail = 0


def check(beschreibung, bedingung, zusatz=""):
    """check(TEXT, BEDINGUNG) – vertauscht waere jede nicht-leere Zeichenkette
    wahr und der Lauf meldete lauter OK, ohne etwas auszuwerten. Exit 2."""
    global _ok, _fail
    if not isinstance(beschreibung, str) or isinstance(bedingung, str):
        print("ABBRUCH: check(beschreibung, bedingung) vertauscht")
        sys.exit(2)
    if bedingung:
        _ok += 1
        print(f"  \033[32m✓\033[0m {beschreibung}")
    else:
        _fail += 1
        print(f"  \033[31m✗\033[0m {beschreibung}" + (f"  [{zusatz}]" if zusatz else ""))


def sicher(fn, *a, **kw):
    """Macht eine Ausnahme zu einem MESSWERT statt zum Abbruch – ein Waechter,
    der beim Melden abbricht, ist von "nicht gelaufen" nicht zu unterscheiden."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return ("__FEHLER__", f"{type(e).__name__}: {e}")


# ── Sandkasten: backend.config NICHT echt importieren ───────────────────────
# Der echte Import migriert Profile und schreibt die LIVE-settings.json zurueck.
_cfg = types.ModuleType("backend.config")


_EINST = {"download_key_ttl_min": 15}   # download_key_strict NICHT gesetzt: die Vorgabe wird gemessen


class _C:
    SECRET_KEY = "testgeheimnis-fuer-den-waechter"

    def get_setting(self, k, d=None):
        return _EINST.get(k, d)


_cfg.config = _C()
sys.modules["backend.config"] = _cfg
_bp = types.ModuleType("backend")
_bp.__path__ = [str(WURZEL / "backend")]
sys.modules.setdefault("backend", _bp)

from backend import download_key as dk  # noqa: E402
import hashlib as _hl  # noqa: E402
import hmac as _hmac  # noqa: E402

# Pentest F-20 (2026-11-17): jeder Schluessel gilt fuer GENAU EIN Ziel.
ZIEL = dk.ziel_kanon("/api/documents/0123abcd__bericht.pdf", [])


def _sig_7(user, exp, art="v", sitz="0", ziel=ZIEL):
    """Gueltige Signatur der 7-teiligen Form – fuer selbst gebaute Proben."""
    return dk._sig(user, exp, art, sitz, dk.ziel_hash(ziel))


def _sig_alt(inhalt):
    """Gueltige Signatur einer ALTEN Form (ohne Ziel) – so, wie sie der Code bis
    2026-11-17 ausstellte. Ohne gueltige Signatur fiele die alte Form aus dem
    falschen Grund durch, und die Pruefung "alte Form abgewiesen" waere trivial."""
    return _hmac.new(_C.SECRET_KEY.encode(), inhalt.encode(), _hl.sha256).hexdigest()


print("\n\033[1m1. Der Schluessel ist als Sitzungstoken wertlos\033[0m")
key, exp = dk.erzeugen("firma\\s.fischer", ziel=ZIEL)
check("erzeugen liefert einen Schluessel", isinstance(key, str) and key.startswith("JDL1."), key[:24])
check("und einen Ablaufzeitpunkt in der Zukunft", exp > int(time.time()))

# verify_token per ast aus main.py schneiden – ein Import von main zoege
# fastapi und den halben Dienst nach.
QUELLE = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(QUELLE)
vt = None
for k in baum.body:
    if isinstance(k, ast.FunctionDef) and k.name == "verify_token":
        vt = quell_ausschnitt.segment(QUELLE, k)
_ew = next((quell_ausschnitt.segment(QUELLE, k) for k in baum.body
            if isinstance(k, ast.FunctionDef) and k.name == "_epoche_widerrufen"), "")
check("verify_token ist auffindbar (Positivkontrolle)", bool(vt))
if vt:
    ns = {"time": time, "hmac": __import__("hmac"), "hashlib": __import__("hashlib"),
          "config": _C(), "_revoked_logins": {}, "_norm_login": lambda x: (x or "").lower(),
          "_WIDERRUF_ALLE": "*",
          "_sitzung_herkunft": __import__("contextvars").ContextVar("_sh", default=None),
          # seit 2026-09-30 (BSI H3) fragt verify_token die Sitzungs-Buchhaltung;
          # Laufzeit/Leerlauf prueft tests/test_sitzung_h3.py, hier nur "gilt".
          "_sitzung": types.SimpleNamespace(
              pruefe_und_beruehre=lambda sig, ts, jetzt=None: True,
              mit_2fa=lambda sig: False, ohne_admin=lambda sig: False,
              # seit 2026-11-20: Admin-Rechte erst nach dem Zahnrad
              admin_erhoeht=lambda sig: False,
              # seit 2026-10-27: AI-Maus-Sitzungen gelten nur auf ihren Pfaden
              pfad_erlaubt=lambda sig: True,
              schluessel=lambda sig: "k" * 32),
          # seit 2026-10-04 (BSI M3) setzt verify_token den Sitzungskontext
          "_sitzung_kontext": __import__("contextvars").ContextVar("_sk", default=None),
          # BSI M2: verify_token meldet die Sitzung an den Protokoll-Halter
          "_admin_anfrage": __import__("contextvars").ContextVar("_aa", default=None)}
    exec(_ew, ns)  # noqa: S102
    exec(vt, ns)  # noqa: S102
    check("verify_token weist den Abruf-Schluessel ab",
          ns["verify_token"](key) is None, str(ns["verify_token"](key)))
    # Positivkontrolle: dieselbe Funktion nimmt ein echtes Sitzungstoken an –
    # sonst waere die Zeile darueber trivial wahr.
    import hashlib as _h
    import hmac as _hm
    ts = str(int(time.time()))
    sig = _hm.new(_C.SECRET_KEY.encode(), f"jarvis:{ts}".encode(), _h.sha256).hexdigest()
    check("… nimmt aber ein echtes Sitzungstoken an (Positivkontrolle)",
          ns["verify_token"](f"jarvis:{ts}:{sig}") == "jarvis")

print("\n\033[1m2. Gueltigkeit, Bindung, fail-closed\033[0m")
check("pruefen gibt den Benutzer zurueck", dk.pruefen(key, ZIEL) == "firma\\s.fischer",
      dk.pruefen(key, ZIEL))
check("ein veraenderter Benutzer faellt durch",
      dk.pruefen(key.replace(dk._b64("firma\\s.fischer"), dk._b64("firma\\fremd")), ZIEL) is None)
check("eine veraenderte Signatur faellt durch",
      dk.pruefen(key[:-1] + ("a" if key[-1] != "a" else "b"), ZIEL) is None)
check("ein verlaengerter Ablauf faellt durch",
      dk.pruefen(key.replace(str(exp), str(exp + 99999)), ZIEL) is None)
# ⚠ Der Ablauf muss mit GUELTIGER Signatur geprueft werden. Die erste Fassung
# ersetzte nur den Zeitstempel – damit stimmte die Signatur nicht mehr, und der
# Schluessel fiel aus dem falschen Grund durch: die Gegenprobe "Ablaufpruefung
# entfernt" blieb gruen (0 FAIL). Jetzt wird der abgelaufene Schluessel richtig
# signiert.
_exp_alt = int(time.time()) - 10
_zh = dk.ziel_hash(ZIEL)
abgelaufen = (f"{dk.PRAEFIX}.{dk._b64('jarvis')}.{_exp_alt}.v.0.{_zh}."
              f"{_sig_7('jarvis', _exp_alt)}")
check("ein KORREKT signierter, aber abgelaufener Schluessel faellt durch",
      dk.pruefen(abgelaufen, ZIEL) is None, abgelaufen[:40])
# Positivkontrolle: derselbe Bau mit Zukunfts-Ablauf wird angenommen – sonst
# waere die Zeile darueber trivial wahr (z.B. bei einem Tippfehler im Aufbau).
_exp_neu = int(time.time()) + 600
check("… derselbe Aufbau mit Zukunfts-Ablauf wird angenommen (Positivkontrolle)",
      dk.pruefen(f"{dk.PRAEFIX}.{dk._b64('jarvis')}.{_exp_neu}.v.0.{_zh}."
                 f"{_sig_7('jarvis', _exp_neu)}", ZIEL) == "jarvis")
check("ein Sitzungstoken ist kein Abruf-Schluessel",
      dk.pruefen("jarvis:1786692855:abc", ZIEL) is None)
check("Muell faellt durch, ohne zu werfen",
      dk.pruefen("JDL1.@@@.x.y", ZIEL) is None and dk.pruefen("", ZIEL) is None
      and dk.pruefen(None, ZIEL) is None)
check("die Form ist erkennbar (fuer die Weiche in der Dependency)",
      dk.ist_abrufschluessel(key) and not dk.ist_abrufschluessel("jarvis:1:2"))
check("die Lebensdauer ist eine FUNKTION, keine Modulkonstante",
      callable(dk.ttl_minuten) and 1 <= dk.ttl_minuten() <= 120, dk.ttl_minuten())

print("\n\033[1m3. REGEL: keine Adresse mehr mit dem Sitzungstoken\033[0m")
# Gesucht wird das MUSTER "?token= / &token= gefolgt von etwas, das nach dem
# Sitzungstoken riecht". Ausgenommen sind dlkey.js selbst (dort steht der
# Rueckfall) und der WebSocket (eigener Auth-Weg, keine kopierbare Adresse).
# Die Regel ist bewusst UMGEKEHRT formuliert: nicht "welche Variablennamen sind
# verboten" (eine Liste, die genau den naechsten Namen nicht kennt – `tk` fehlte
# in der ersten Fassung und liess den Altstand durch), sondern "JEDE
# ?token=-Stelle muss aus dem Abruf-Schluessel gespeist sein".
# vnc.js ist ausgenommen: ein WebSocket hat einen eigenen Auth-Weg und seine
# Adresse ist nichts, was jemand in eine Mail kopiert.
AUSNAHMEN = {"dlkey.js", "vnc.js"}
# Seit Pentest F-20 (2026-11-17) gilt ein Schluessel nur fuer EINE Adresse und
# entsteht in dlkey.js aus der GANZEN Adresse (``JarvisDL.url``). Damit ist die
# Regel schaerfer als vorher: ausserhalb von dlkey.js wird ueberhaupt KEIN
# ``?token=`` mehr von Hand gebaut – auch nicht aus einem Schluessel, denn einen
# Schluessel ohne Adresse gibt es nicht mehr. SPEISER bleibt nur fuer die
# Gegenprobe des Kommentarfilters unten.
SPEISER = re.compile(r"JarvisDL\.url")


def _leerraum(treffer):
    """Ein Kommentarbereich wird durch LEERZEICHEN ersetzt, nicht entfernt.

    Wer Zeilen herausnimmt, baut den Quelltext um: mehrteilige Ausdruecke
    rutschen zusammen (Register), und JEDE gemeldete Zeilennummer stimmt nicht
    mehr. Die alte Fassung loeschte die ``/* */``-Bereiche von settings.html und
    meldete den Treffer deshalb als Zeile 3776, waehrend er in Zeile 4064 steht.
    Zeilenumbrueche bleiben stehen, alles andere wird zu Leerraum.
    """
    return re.sub(r"[^\n]", " ", treffer.group(0))


def _js_ohne_kommentare(text):
    """JS-Kommentare ausleeren.

    ``//`` wird NUR am Zeilenanfang erkannt: ein ``//`` mitten in der Zeile
    steht hier fast immer in einer Adresse (``https://``) oder in einer
    Zeichenkette, und ein Scanner, der Zeichenketten, Template-Literale und
    Regex-Literale nicht unterscheidet, verschluckt dann den Rest der Zeile –
    also womoeglich genau die ``?token=``-Stelle, die gesucht ist.
    """
    text = re.sub(r"/\*[\s\S]*?\*/", _leerraum, text)
    return re.sub(r"^[ \t]*//.*$", _leerraum, text, flags=re.M)


def ohne_kommentare(text, html=False):
    """Begruendungstexte vor dem Vergleich ausleeren.

    ⚠ In HTML stehen die Begruendungen dieses Projekts in ``<!-- … -->``, und
    die alte Fassung kannte nur JS-Kommentare. Am 2026-10-02 hat der Waechter
    dadurch SEINE EIGENE Erklaerung gelesen – den Kommentar in settings.html
    ("ueber einen Link mit ?token= – ein <a href> kann keinen
    Authorization-Header setzen") – und daraus einen FAIL gemacht, den es im
    Code nicht gab. Derselbe Fehler ist im Register mehrfach vermerkt.

    JS-Kommentare gelten in HTML nur INNERHALB von ``<script>``: ausserhalb ist
    ``/* */`` CSS oder Prosa, und ein ``//`` am Zeilenanfang kann der Rest einer
    umbrochenen Adresse sein.
    """
    if not html:
        return _js_ohne_kommentare(text)
    text = re.sub(r"<!--[\s\S]*?-->", _leerraum, text)
    return re.sub(r"(<script\b[^>]*>)([\s\S]*?)(</script\s*>)",
                  lambda m: m.group(1) + _js_ohne_kommentare(m.group(2)) + m.group(3),
                  text, flags=re.I)


def gefiltert(datei):
    """Dateiinhalt ohne Kommentarbereiche – die Gattung entscheidet der Suffix."""
    return ohne_kommentare(datei.read_text(encoding="utf-8"),
                           html=datei.suffix.lower() == ".html")


def token_stellen(text):
    """(Fundstelle, Wertausdruck) je ?token=.

    ⚠ Das Fenster reicht ueber ZWEI FOLGEZEILEN. Ein Wertausdruck wird oft
    umbrochen – in settings.html steht der ``JarvisDL``-Aufruf eine Zeile unter
    dem ``&token=``. Eine zeilenweise Pruefung meldete dort einen Fehler, den es
    nicht gibt (dieselbe Falle wie im Symbol-Waechter am 2026-08-19).
    """
    zeilen = text.splitlines()
    out = []
    for nr, zeile in enumerate(zeilen):
        fenster = " ".join(zeilen[nr:nr + 3])
        i = 0
        while True:
            a, b = zeile.find("?token=", i), zeile.find("&token=", i)
            kand = [x for x in (a, b) if x >= 0]
            if not kand:
                break
            i = min(kand)
            j = fenster.find("token=", fenster.find(zeile[i:i + 7]))
            out.append((f"{nr + 1}: {zeile.strip()[:70]}", fenster[j:j + 140]))
            i += 7
    return out


treffer = []
for datei in sorted(list((WURZEL / "frontend" / "js").glob("*.js"))
                    + list((WURZEL / "frontend").glob("*.html"))):
    if datei.name in AUSNAHMEN:
        continue
    for fund, wert in token_stellen(gefiltert(datei)):
        treffer.append(f"{datei.name}: {fund}")
check("KEINE ?token=-Adresse ausserhalb von dlkey.js (F-20: Schluessel je Adresse)",
      not treffer, " | ".join(treffer[:4]))
# Positivkontrolle: dieselbe Suche trifft auf ECHTEN Dateien – ungefiltert stehen
# dort Begruendungen mit ?token= (jira_addon.js, settings.html). Sonst waere die
# Zeile darueber gruen, weil das Muster nichts trifft. (Nicht dlkey.js: dort steht
# kein woertliches ?token=, das Trennzeichen wird berechnet.)
_roh = sum(len(token_stellen(d.read_text(encoding="utf-8")))
           for d in sorted(list((WURZEL / "frontend" / "js").glob("*.js"))
                           + list((WURZEL / "frontend").glob("*.html")))
           if d.name not in AUSNAHMEN)
check("die Suche trifft auf echten Dateien (ungefiltert, Positivkontrolle)", _roh >= 2, _roh)
check("und sie wuerde den Altstand melden (Probe im Test selbst)",
      len(token_stellen("u = base + '?token=' + encodeURIComponent(_dlk());")) == 1)
# Jeder Helfer _dlUrl muss wirklich JarvisDL.url rufen – ein Name ist keine Wirkung.
_dlurl_rumpf = []
for d in sorted((WURZEL / "frontend" / "js").glob("*.js")):
    _t = gefiltert(d)
    # ^[ \t]* statt ^\s*: \s frisst Zeilenumbrueche, und ueber den zu Leerraum
    # gemachten Kommentarbloecken lief die Suche ab JEDEM Zeilenanfang bis ans
    # Blockende und zurueck - quadratisch, 18 von 21 s (2026-11-22). Das Ende
    # eines Treffers (und damit der Rumpf) ist in beiden Fassungen dasselbe.
    for m in re.finditer(r"(?:function\s+|^[ \t]*)_dlUrl\s*\(\s*u\s*\)\s*\{", _t, re.M):
        _dlurl_rumpf.append((d.name, _t[m.end():_t.find("}", m.end())]))
check("_dlUrl ist definiert (Positivkontrolle zur naechsten Zeile)",
      len(_dlurl_rumpf) >= 7, [n for n, _ in _dlurl_rumpf])
check("jede _dlUrl-Definition ruft JarvisDL.url mit der Adresse",
      all("JarvisDL.url(u)" in r for _, r in _dlurl_rumpf),
      " | ".join(n for n, r in _dlurl_rumpf if "JarvisDL.url(u)" not in r))
_alt_api = [d.name for d in (WURZEL / "frontend" / "js").glob("*.js")
            if d.name != "dlkey.js" and "JarvisDL.schluessel" in gefiltert(d)]
check("niemand fragt mehr einen Schluessel OHNE Adresse ab (JarvisDL.schluessel)",
      not _alt_api, ", ".join(_alt_api))

# ── Der Kommentarfilter selbst ──────────────────────────────────────────────
# Positivkontrolle zur Regel darueber: sie ist nur dann eine Aussage, wenn der
# Filter ueberhaupt etwas WEGZUNEHMEN hat. Gezaehlt wird ueber alle Seiten, als
# Eigenschaft – nicht an einem Satz, der beim naechsten Umformulieren einen
# Fehler meldete, den es nicht gibt.
_html_vor = sum(len(token_stellen(p.read_text(encoding="utf-8")))
                for p in (WURZEL / "frontend").glob("*.html"))
_html_nach = sum(len(token_stellen(gefiltert(p)))
                 for p in (WURZEL / "frontend").glob("*.html"))
check("in HTML steht ?token= nachweislich in Kommentaren, und der Filter nimmt "
      "sie weg (Positivkontrolle)",
      _html_vor > _html_nach, f"vor={_html_vor} nach={_html_nach}")

# Gegenprobe im Test selbst, auf eigenem Material: der Filter darf NUR die
# Begruendung treffen. Drei ?token=-Stellen – eine im HTML-Kommentar, eine im
# JS-Kommentar, eine echte Adresse mit Sitzungstoken. Uebrig bleiben muss genau
# die echte, und sie muss als unversorgt gemeldet werden.
PROBE_HTML = (
    '<!-- Der Export geht ueber einen Blob, NICHT ueber einen Link mit\n'
    '     ?token= - ein <a href> kann keinen Authorization-Header setzen. -->\n'
    '<script>\n'
    '  // Hinweis: eine Adresse mit ?token= waere hier falsch.\n'
    '  const u = "/api/documents/" + cap + "?token=" + encodeURIComponent(tok);\n'
    '  oeffne(u);\n'
    '</script>\n'
)
_probe_stellen = token_stellen(ohne_kommentare(PROBE_HTML, html=True))
_probe_offen = [w for _f, w in _probe_stellen]
check("der Filter trifft HTML- UND JS-Kommentar, laesst die echte Adresse aber "
      "stehen (Gegenprobe im Test selbst)",
      len(token_stellen(PROBE_HTML)) == 3 and len(_probe_stellen) == 1,
      f"ungefiltert={len(token_stellen(PROBE_HTML))} gefiltert={len(_probe_stellen)}")
check("… und die echte Adresse wird weiterhin als unversorgt gemeldet",
      len(_probe_offen) == 1 and "encodeURIComponent" in _probe_offen[0],
      f"offen={_probe_offen}")

VERBRAUCHER = ["chatlib.js", "info_files.js", "kbmatrix.js", "knowledge.js",
               "wissen.js", "tracks.js", "issues.js", "vision.js"]
ohne = [n for n in VERBRAUCHER
        if "JarvisDL" not in (WURZEL / "frontend" / "js" / n).read_text(encoding="utf-8")]
check("jeder Verbraucher benutzt JarvisDL", not ohne, ", ".join(ohne))

print("\n\033[1m4. REGEL: wer einen Verbraucher laedt, laedt dlkey.js\033[0m")
fehlend = []
for seite in sorted((WURZEL / "frontend").glob("*.html")):
    inhalt = seite.read_text(encoding="utf-8")
    braucht = [n for n in VERBRAUCHER if f"js/{n}" in inhalt] or (
        ["settings-inline"] if "JarvisDL" in inhalt else [])
    if braucht and "js/dlkey.js" not in inhalt:
        fehlend.append(f"{seite.name} (braucht {braucht[0]})")
check("keine Seite laedt einen Verbraucher ohne dlkey.js", not fehlend, ", ".join(fehlend))
check("dlkey.js wird ueberhaupt eingebunden (Positivkontrolle)",
      len([p for p in (WURZEL / "frontend").glob("*.html")
           if "js/dlkey.js" in p.read_text(encoding="utf-8")]) >= 10)

print("\n\033[1m5. Die Dependency nimmt den Schluessel – und meldet den Alt-Weg\033[0m")
check("_query_benutzer existiert", "def _query_benutzer(" in QUELLE)
check("sie prueft den Abruf-Schluessel ZUERST",
      QUELLE.index("_dlkey.ist_abrufschluessel(wert)") < QUELLE.index('name = verify_token(wert)'))
check("require_auth_or_query benutzt sie",
      re.search(r"async def require_auth_or_query.*?_query_benutzer\(request\)", QUELLE, re.S) is not None)
check("require_admin_or_query benutzt sie",
      re.search(r"async def require_admin_or_query.*?_query_benutzer\(request\)", QUELLE, re.S) is not None)
check("die Alt-Nutzung wird protokolliert",
      "ALT-WEG: Sitzungstoken in ?token=" in QUELLE)
check("es gibt einen Schalter, der den Alt-Weg abstellt", callable(dk.streng))
check("und der ist per Vorgabe AN (BSI M4, Android holt seit 2026-10-05 Abruf-Schluessel)",
      dk.streng() is True)
for _w, _soll in ((False, False), ("false", False), ("0", False), ("nein", False), ("off", False),
                  (True, True), ("true", True), ("tru", True), ("", True), (None, True)):
    _EINST["download_key_strict"] = _w
    check("download_key_strict=%r -> streng %s (nur ausdrueckliches Nein schaltet ab)" % (_w, _soll),
          dk.streng() is _soll)
_EINST.pop("download_key_strict", None)
# Am Syntaxbaum statt an der Schreibweise der Signatur: seit Pentest A7
# (2026-11-08) traegt der Endpunkt zusaetzlich ``request`` (Programmschluessel-
# Zweig) und haengt an require_auth_or_agent – ein ZIEL nimmt er weiterhin nicht.
_dkh = next((k for k in ast.parse(QUELLE).body if isinstance(k, ast.AsyncFunctionDef)
             and k.name == "download_key_holen"), None)
# Seit F-20 (2026-11-17) ist es umgekehrt: OHNE Ziel gibt es keinen Schluessel.
# Am Syntaxbaum: JEDER erzeugen()-Aufruf in main.py traegt ``ziel=``. Die
# Wirkung (400 ohne Ziel, Bindung) misst live_download_key_dev.py.
_alle_erz = [c for c in ast.walk(ast.parse(QUELLE)) if isinstance(c, ast.Call)
             and ast.unparse(c.func) == "_dlkey.erzeugen"]
check("Positivkontrolle: erzeugen() wird in main.py aufgerufen", len(_alle_erz) >= 3, len(_alle_erz))
check("JEDER erzeugen()-Aufruf bindet an ein Ziel (ziel=…)",
      all(any(kw.arg == "ziel" for kw in c.keywords) for c in _alle_erz),
      [ast.unparse(c)[:80] for c in _alle_erz if not any(kw.arg == "ziel" for kw in c.keywords)])

print("\n\033[1m6. Der Schluessel traegt die Einschraenkung seiner Sitzung (Review 2026-10-07)\033[0m")
# Vorher galten beim Einloesen die Admin-Rechte des KONTOS: eine App-Sitzung
# eines Admins (ohne_admin) holte sich einen Schluessel und bekam damit
# Kamerabild, Gesichtsdaten und die Dokumente aller Benutzer.
# Ziel der Einloese-Proben unten: die Attrappen-Anfrage ruft "/x" ab.
ZX = dk.ziel_kanon("/x", [])
_kv, _ = dk.erzeugen("chef", ziel=ZX)
_ke, _ = dk.erzeugen("chef", eingeschraenkt=True, ziel=ZX)
check("volle Sitzung -> nicht eingeschraenkt", dk.pruefen_mit_art(_kv, ZX) == ("chef", False),
      dk.pruefen_mit_art(_kv, ZX))
check("eingeschraenkte Sitzung -> eingeschraenkt", dk.pruefen_mit_art(_ke, ZX) == ("chef", True),
      dk.pruefen_mit_art(_ke, ZX))
_teile = _ke.split(".")
check("Art-Feld von e auf v umgeschrieben -> faellt durch (signiert)",
      dk.pruefen_mit_art(".".join(_teile[:3] + ["v"] + _teile[4:]), ZX)[0] is None)
_x = int(time.time()) + 600
# Die ALTEN Formen, gueltig signiert wie bis 2026-11-17 ausgestellt: seit F-20
# werden sie abgewiesen (vorher galt die 4-teilige als eingeschraenkt).
_alt = f"{dk.PRAEFIX}.{dk._b64('chef')}.{_x}.{_sig_alt(f'jdl1:chef:{_x}')}"
_alt6 = f"{dk.PRAEFIX}.{dk._b64('chef')}.{_x}.v.0.{_sig_alt(f'jdl1:chef:{_x}:v:0')}"
check("alte 4-teilige Form (gueltig signiert) wird ABGEWIESEN (F-20)",
      dk.pruefen_mit_art(_alt, ZX)[0] is None, dk.pruefen_mit_art(_alt, ZX))
check("alte 6-teilige Form ohne Ziel (gueltig signiert) wird ABGEWIESEN (F-20)",
      dk.pruefen_mit_art(_alt6, ZX)[0] is None, dk.pruefen_mit_art(_alt6, ZX))
check("unbekannte Art faellt durch",
      dk.pruefen_mit_art(".".join(_teile[:3] + ["x"] + _teile[4:]), ZX)[0] is None)

# Die KETTE in main.py: _query_benutzer setzt den Sitzungskontext, und
# _sitzung_ohne_admin (daran haengt _user_is_admin) sieht ihn.
import contextvars as _cv  # noqa: E402
_fns = {}
# _routing_pfad gehoert MIT in den Schnitt: seit d246ae87 holt _abruf_ziel den
# Pfad dort und nicht mehr aus request.url.path. Ohne sie lief der Namensraum in
# einen NameError - als Absturz, nicht als FAIL (gefunden erst im CI-Lauf
# 2026-11-19, lokal nicht mitgemessen).
# Den Schalter "_admin_2fa_pflicht" gibt es seit 2026-11-20 nicht mehr
# (Admin-Rechte nur am Zahnrad) – _sitzung_ohne_admin braucht ihn nicht.
_GESCHNITTEN = ("_query_benutzer", "_sitzung_ohne_admin",
                "_abruf_ziel", "_routing_pfad")
for k in baum.body:
    if isinstance(k, ast.FunctionDef) and k.name in _GESCHNITTEN:
        _fns[k.name] = quell_ausschnitt.segment(QUELLE, k)
check(f"Positivkontrolle: {len(_GESCHNITTEN)} Funktionen aus main.py geschnitten",
      len(_fns) == len(_GESCHNITTEN), sorted(_fns))


class _Abfrage(dict):
    """Attrappe von Starlettes QueryParams – mit der ECHTEN Schnittstelle
    (``get`` und ``multi_items``), die _abruf_ziel benutzt."""

    def multi_items(self):
        return list(self.items())


if len(_fns) == len(_GESCHNITTEN):
    _KX = _cv.ContextVar("_sk", default=None)
    _BEENDET = set()        # Kennungen beendeter Sitzungen (Attrappe sitzung_token)
    _ns6 = {"_dlkey": dk, "verify_token": lambda t: None, "_sitzung_kontext": _KX,
            "_norm_login": lambda x: (x or "").split("\\")[-1].lower(), "config": _C(),
            "Request": object, "_revoked_logins": {}, "_WIDERRUF_ALLE": "*",
            "_sitzung_herkunft": _cv.ContextVar("_sh", default=None),
            "_sitzung": types.SimpleNamespace(
                sitzung_besteht=lambda kennung, ts, jetzt=None: kennung not in _BEENDET)}
    exec(_ew, _ns6)  # noqa: S102
    for _q in _fns.values():
        exec(_q, _ns6)  # noqa: S102

    def _einloesen(schluessel):
        def lauf():
            # scope["path"] = der Routing-Pfad (/x, dafuer ist ZX erzeugt);
            # url.path traegt bewusst einen ANDEREN Wert: wer den nimmt, bildet
            # ein anderes Ziel und loest den Schluessel nicht ein. So misst die
            # Probe, WOHER der Pfad kommt (BadHost, CVE-2026-48710).
            req = types.SimpleNamespace(query_params=_Abfrage(token=schluessel),
                                        scope={"path": "/x"},
                                        url=types.SimpleNamespace(path="/aus-dem-host-header"))
            name = _ns6["_query_benutzer"](req)
            return name, (_ns6["_sitzung_ohne_admin"](name) if name else None)
        return _cv.Context().run(lauf)
    check("Positivkontrolle: voller Schluessel -> Benutzer, KEINE Einschraenkung",
          _einloesen(_kv) == ("chef", False), _einloesen(_kv))
    check("eingeschraenkter Schluessel -> Sitzung ohne Admin-Rechte",
          _einloesen(_ke) == ("chef", True), _einloesen(_ke))
    _EINST["admin_2fa_pflicht"] = False
    check("… auch wenn die 2FA-Pflicht AUS ist (App-Sitzungen haben nie Admin-Rechte)",
          _einloesen(_ke) == ("chef", True), _einloesen(_ke))
    _EINST.pop("admin_2fa_pflicht", None)
    check("alter Schluessel (ohne Ziel) -> abgewiesen", _einloesen(_alt)[0] is None, _einloesen(_alt))

    print("\n\033[1m3. Schluessel endet mit seiner Sitzung (Code-Review 2026-10-07)\033[0m")
    _ts0 = int(time.time()) - 60
    _ks, _ = dk.erzeugen("chef", sitzung=(_ts0, "a" * 32), ziel=ZX)
    check("Positivkontrolle: an eine lebende Sitzung gebundener Schluessel gilt",
          _einloesen(_ks) == ("chef", False), _einloesen(_ks))
    check("die Bindung steht IM Schluessel (7 Teile, mit Ziel)", len(_ks.split(".")) == 7, _ks.count("."))
    _BEENDET.add("a" * 32)
    check("⚠ Sitzung abgemeldet -> Schluessel abgewiesen", _einloesen(_ks)[0] is None,
          _einloesen(_ks))
    _BEENDET.clear()
    _ns6["_revoked_logins"]["chef"] = _ts0
    check("⚠ Kennwortwechsel/Zwangsabmeldung (Epoche) -> Schluessel abgewiesen",
          _einloesen(_ks)[0] is None, _einloesen(_ks))
    _ns6["_revoked_logins"].clear()
    _ns6["_revoked_logins"]["*"] = _ts0 + 1
    check("⚠ unlesbare Widerrufsdatei (alle vorher) -> Schluessel abgewiesen",
          _einloesen(_ks)[0] is None, _einloesen(_ks))
    _ns6["_revoked_logins"].clear()
    _ns6["_revoked_logins"]["chef"] = _ts0 - 5
    check("Positivkontrolle: Epoche VOR der Sitzung trifft sie nicht",
          _einloesen(_ks) == ("chef", False), _einloesen(_ks))
    _ns6["_revoked_logins"].clear()
    _gefaelscht = _ks.split(".")
    _gefaelscht[4] = str(_ts0 + 3600) + "-" + "b" * 32
    check("⚠ ausgetauschte Sitzungsangabe -> Signatur passt nicht",
          _einloesen(".".join(_gefaelscht))[0] is None)
    _o, _ = dk.erzeugen("api", ziel=ZX)
    check("ohne Sitzung (API-Key): Form 0, gilt", _o.split(".")[4] == "0"
          and _einloesen(_o)[0] == "api", _o)

for _n in ("_openapi_url", "download_key_holen"):
    _k = next((k for k in baum.body if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
               and k.name == _n), None)
    _alle = [c for c in ast.walk(_k) if isinstance(c, ast.Call)
             and ast.unparse(c.func) == "_dlkey.erzeugen"] if _k else []
    # Art "p" (Programmschluessel, Pentest A7) hat keine Sitzung – sie bindet an
    # die Kennung des Programmschluessels (tests/test_pentest_programm_abruf.py).
    _prog = [c for c in _alle if any(kw.arg == "programm" and ast.unparse(kw.value) == "True"
                                     for kw in c.keywords)]
    _aufrufe = [c for c in _alle if c not in _prog]
    if _n == "download_key_holen":
        check(f"{_n}: genau ein Programm-Aufruf, fest an 'api' und eine Kennung gebunden",
              len(_prog) == 1 and ast.unparse(_prog[0].args[0]) == "'api'"
              and any(kw.arg == "sitzung" for kw in _prog[0].keywords),
              [ast.unparse(c) for c in _prog])
    check(f"{_n}: jedes erzeugen() gibt die Sitzungs-Einschraenkung mit",
          bool(_aufrufe) and all(any(kw.arg == "eingeschraenkt" and "_sitzung_ohne_admin" in ast.unparse(kw.value)
                                     for kw in c.keywords) for c in _aufrufe),
          [ast.unparse(c) for c in _aufrufe])
    check(f"{_n}: jedes erzeugen() bindet an die Sitzung (_abruf_sitzung)",
          bool(_aufrufe) and all(any(kw.arg == "sitzung" and "_abruf_sitzung" in ast.unparse(kw.value)
                                     for kw in c.keywords) for c in _aufrufe),
          [ast.unparse(c) for c in _aufrufe])

print("\n\033[1m8. Pentest F-20: ein Schluessel gilt fuer GENAU EINE Adresse\033[0m")
_kd, _ = dk.erzeugen("chef", ziel=ZIEL)
check("Positivkontrolle: Schluessel gilt fuer sein Ziel", dk.pruefen(_kd, ZIEL) == "chef")
check("⚠ fuer eine ANDERE Datei abgewiesen",
      dk.pruefen(_kd, dk.ziel_kanon("/api/documents/fremd__x.pdf", [])) is None)
_zq = dk.ziel_kanon("/api/wissen/file", [("path", "a/b.pdf")])
_kq, _ = dk.erzeugen("chef", ziel=_zq)
check("⚠ gleicher Pfad, anderer Parameter abgewiesen",
      dk.pruefen(_kq, dk.ziel_kanon("/api/wissen/file", [("path", "a/c.pdf")])) is None)
check("⚠ OHNE Ziel gibt es keinen Zugang (fail-closed)",
      dk.pruefen(_kq) is None and dk.pruefen(_kq, "") is None)
check("Reihenfolge und Kodierung der Parameter sind gleichgueltig",
      dk.ziel_aus_adresse("/api/wissen/file?x=1&path=a%20b")
      == dk.ziel_kanon("/api/wissen/file", [("path", "a b"), ("x", "1")]))
check("token und der Cache-Buster t zaehlen nicht zum Ziel",
      dk.ziel_aus_adresse("/api/vision/snapshot?t=1&token=JDL1.x")
      == dk.ziel_aus_adresse("/api/vision/snapshot?t=99"))
check("… andere Parameter schon (Positivkontrolle)",
      dk.ziel_aus_adresse("/api/vision/face-crop/0?i=1") != dk.ziel_aus_adresse("/api/vision/face-crop/0?i=2"))
check("ein kodierter Pfad ist dasselbe Ziel wie der dekodierte (request.url.path)",
      dk.ziel_aus_adresse("/api/documents/a%20b.pdf") == dk.ziel_kanon("/api/documents/a b.pdf", []))
for _fremd in ("/etc/passwd", "relativ/api/x", ""):
    try:
        dk.ziel_aus_adresse(_fremd)
        _ok_fremd = False
    except ValueError:
        _ok_fremd = True
    check(f"kein Schluessel fuer eine Adresse ausserhalb der Abruf-Pfade: {_fremd!r}", _ok_fremd)
try:
    dk.erzeugen("chef")
    _ohne_ziel = "ausgestellt"
except TypeError:
    _ohne_ziel = "TypeError"
check("erzeugen() OHNE Ziel ist ein Programmierfehler (TypeError), kein ungebundener Schluessel",
      _ohne_ziel == "TypeError", _ohne_ziel)
try:
    dk.erzeugen("chef", ziel="")
    _leer = "ausgestellt"
except ValueError:
    _leer = "ValueError"
check("… und ein leeres Ziel ebenso wenig", _leer == "ValueError", _leer)
check("Grund fuer die alte Form ist benannt", "ohne Zielbindung" in dk.grund(_alt))
check("Grund fuer eine fremde Adresse ist benannt",
      "andere Adresse" in dk.grund(_kd, dk.ziel_kanon("/api/documents/fremd__x.pdf", [])))
_pk, _ = dk.erzeugen("api", sitzung=(0, "abc123"), programm=True, ziel=ZIEL)
check("Programmschluessel: gilt fuer sein Ziel (Positivkontrolle)",
      dk.programm_kennung(_pk, ZIEL) == "abc123")
check("⚠ Programmschluessel: fuer ein anderes Ziel abgewiesen",
      dk.programm_kennung(_pk, dk.ziel_kanon("/api/documents/fremd__x.pdf", [])) is None)

print(f"\n\033[1mErgebnis: {_ok}/{_ok + _fail}\033[0m")
sys.exit(1 if _fail else 0)

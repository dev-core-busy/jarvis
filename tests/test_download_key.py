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

print("\n\033[1m1. Der Schluessel ist als Sitzungstoken wertlos\033[0m")
key, exp = dk.erzeugen("firma\\s.fischer")
check("erzeugen liefert einen Schluessel", isinstance(key, str) and key.startswith("JDL1."), key[:24])
check("und einen Ablaufzeitpunkt in der Zukunft", exp > int(time.time()))

# verify_token per ast aus main.py schneiden – ein Import von main zoege
# fastapi und den halben Dienst nach.
QUELLE = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(QUELLE)
vt = None
for k in baum.body:
    if isinstance(k, ast.FunctionDef) and k.name == "verify_token":
        vt = ast.get_source_segment(QUELLE, k)
_ew = next((ast.get_source_segment(QUELLE, k) for k in baum.body
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
check("pruefen gibt den Benutzer zurueck", dk.pruefen(key) == "firma\\s.fischer", dk.pruefen(key))
check("ein veraenderter Benutzer faellt durch",
      dk.pruefen(key.replace(dk._b64("firma\\s.fischer"), dk._b64("firma\\fremd"))) is None)
check("eine veraenderte Signatur faellt durch", dk.pruefen(key[:-1] + ("a" if key[-1] != "a" else "b")) is None)
check("ein verlaengerter Ablauf faellt durch",
      dk.pruefen(key.replace(str(exp), str(exp + 99999))) is None)
# ⚠ Der Ablauf muss mit GUELTIGER Signatur geprueft werden. Die erste Fassung
# ersetzte nur den Zeitstempel – damit stimmte die Signatur nicht mehr, und der
# Schluessel fiel aus dem falschen Grund durch: die Gegenprobe "Ablaufpruefung
# entfernt" blieb gruen (0 FAIL). Jetzt wird der abgelaufene Schluessel richtig
# signiert.
_exp_alt = int(time.time()) - 10
abgelaufen = f"{dk.PRAEFIX}.{dk._b64('jarvis')}.{_exp_alt}.{dk._sig('jarvis', _exp_alt)}"
check("ein KORREKT signierter, aber abgelaufener Schluessel faellt durch",
      dk.pruefen(abgelaufen) is None, abgelaufen[:40])
# Positivkontrolle: derselbe Bau mit Zukunfts-Ablauf wird angenommen – sonst
# waere die Zeile darueber trivial wahr (z.B. bei einem Tippfehler im Aufbau).
_exp_neu = int(time.time()) + 600
check("… derselbe Aufbau mit Zukunfts-Ablauf wird angenommen (Positivkontrolle)",
      dk.pruefen(f"{dk.PRAEFIX}.{dk._b64('jarvis')}.{_exp_neu}."
                 f"{dk._sig('jarvis', _exp_neu)}") == "jarvis")
check("ein Sitzungstoken ist kein Abruf-Schluessel",
      dk.pruefen("jarvis:1786692855:abc") is None)
check("Muell faellt durch, ohne zu werfen",
      dk.pruefen("JDL1.@@@.x.y") is None and dk.pruefen("") is None and dk.pruefen(None) is None)
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
# ``_dlKey(`` ist die Methode in knowledge.js (seit 2026-10-21, viewFile braucht
# sie ausserhalb von _bindFilePreview). Ein Name ist keine Wirkung – dass sie
# wirklich aus JarvisDL liest, prueft die Zeile unter dem Fundstellen-Check.
SPEISER = re.compile(r"_dlk\s*\(|_dlKey\s*\(|JarvisDL")


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
        if not SPEISER.search(wert):
            treffer.append(f"{datei.name}: {fund}")
check("JEDE ?token=-Adresse wird aus dem Abruf-Schluessel gespeist",
      not treffer, " | ".join(treffer[:4]))
# Der Name _dlKey ist oben als Speiser zugelassen – also muss jede Definition
# davon den Abruf-Schluessel holen. Sonst genuegte es, eine Methode so zu
# nennen und darin das Sitzungstoken zurueckzugeben.
_dlkey_rumpf = []
for d in sorted((WURZEL / "frontend" / "js").glob("*.js")):
    _t = gefiltert(d)
    for m in re.finditer(r"^\s*_dlKey\s*\(\s*\)\s*\{", _t, re.M):
        _dlkey_rumpf.append((d.name, _t[m.end():_t.find("}", m.end())]))
check("_dlKey ist definiert (Positivkontrolle zur naechsten Zeile)",
      bool(_dlkey_rumpf), "keine Definition gefunden")
check("jede _dlKey-Definition liest JarvisDL.schluessel()",
      all("JarvisDL.schluessel()" in r for _, r in _dlkey_rumpf),
      " | ".join(n for n, r in _dlkey_rumpf if "JarvisDL.schluessel()" not in r))
# Positivkontrolle: die Suche findet ueberhaupt Stellen – sonst waere die
# Zeile darueber gruen, weil das Muster nichts trifft.
gefunden = sum(len(token_stellen(gefiltert(d)))
               for d in (WURZEL / "frontend" / "js").glob("*.js") if d.name not in AUSNAHMEN)
check("die Suche findet die Adressen ueberhaupt (Positivkontrolle)",
      gefunden >= 8, f"gefunden={gefunden}")
check("und sie wuerde den Altstand melden (Gegenprobe im Test selbst)",
      not SPEISER.search("?token=' + encodeURIComponent(tk)"))

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
_probe_offen = [w for _f, w in _probe_stellen if not SPEISER.search(w)]
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
check("der Endpunkt nimmt KEIN Ziel entgegen (er bindet an den Benutzer, nicht an eine Datei)",
      re.search(r'@app\.get\("/api/download-key"\)\s*\nasync def download_key_holen\('
                r'user: str = Depends\(require_auth\)\)', QUELLE) is not None)

print("\n\033[1m6. Der Schluessel traegt die Einschraenkung seiner Sitzung (Review 2026-10-07)\033[0m")
# Vorher galten beim Einloesen die Admin-Rechte des KONTOS: eine App-Sitzung
# eines Admins (ohne_admin) holte sich einen Schluessel und bekam damit
# Kamerabild, Gesichtsdaten und die Dokumente aller Benutzer.
_kv, _ = dk.erzeugen("chef")
_ke, _ = dk.erzeugen("chef", eingeschraenkt=True)
check("volle Sitzung -> nicht eingeschraenkt", dk.pruefen_mit_art(_kv) == ("chef", False), dk.pruefen_mit_art(_kv))
check("eingeschraenkte Sitzung -> eingeschraenkt", dk.pruefen_mit_art(_ke) == ("chef", True), dk.pruefen_mit_art(_ke))
_teile = _ke.split(".")
check("Art-Feld von e auf v umgeschrieben -> faellt durch (signiert)",
      dk.pruefen_mit_art(".".join(_teile[:3] + ["v"] + _teile[4:]))[0] is None)
_x = int(time.time()) + 600
_alt = f"{dk.PRAEFIX}.{dk._b64('chef')}.{_x}.{dk._sig('chef', _x)}"
check("alte 4-teilige Form (gueltig signiert) gilt als EINGESCHRAENKT (fail-closed)",
      dk.pruefen_mit_art(_alt) == ("chef", True), dk.pruefen_mit_art(_alt))
check("unbekannte Art faellt durch", dk.pruefen_mit_art(".".join(_teile[:3] + ["x"] + _teile[4:]))[0] is None)

# Die KETTE in main.py: _query_benutzer setzt den Sitzungskontext, und
# _sitzung_ohne_admin (daran haengt _user_is_admin) sieht ihn.
import contextvars as _cv  # noqa: E402
_fns = {}
for k in baum.body:
    if isinstance(k, ast.FunctionDef) and k.name in ("_query_benutzer", "_sitzung_ohne_admin",
                                                       "_admin_2fa_pflicht"):
        _fns[k.name] = ast.get_source_segment(QUELLE, k)
check("Positivkontrolle: drei Funktionen aus main.py geschnitten", len(_fns) == 3, sorted(_fns))
if len(_fns) == 3:
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
            req = types.SimpleNamespace(query_params={"token": schluessel},
                                        url=types.SimpleNamespace(path="/x"))
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
    check("alter Schluessel -> ebenfalls ohne Admin-Rechte", _einloesen(_alt) == ("chef", True))

    print("\n\033[1m3. Schluessel endet mit seiner Sitzung (Code-Review 2026-10-07)\033[0m")
    _ts0 = int(time.time()) - 60
    _ks, _ = dk.erzeugen("chef", sitzung=(_ts0, "a" * 32))
    check("Positivkontrolle: an eine lebende Sitzung gebundener Schluessel gilt",
          _einloesen(_ks) == ("chef", False), _einloesen(_ks))
    check("die Bindung steht IM Schluessel (6 Teile)", len(_ks.split(".")) == 6, _ks.count("."))
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
    _o, _ = dk.erzeugen("api")
    check("ohne Sitzung (API-Key): Form 0, gilt", _o.split(".")[4] == "0"
          and _einloesen(_o)[0] == "api", _o)

for _n in ("_openapi_url", "download_key_holen"):
    _k = next((k for k in baum.body if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
               and k.name == _n), None)
    _aufrufe = [c for c in ast.walk(_k) if isinstance(c, ast.Call)
                and ast.unparse(c.func) == "_dlkey.erzeugen"] if _k else []
    check(f"{_n}: jedes erzeugen() gibt die Sitzungs-Einschraenkung mit",
          bool(_aufrufe) and all(any(kw.arg == "eingeschraenkt" and "_sitzung_ohne_admin" in ast.unparse(kw.value)
                                     for kw in c.keywords) for c in _aufrufe),
          [ast.unparse(c) for c in _aufrufe])
    check(f"{_n}: jedes erzeugen() bindet an die Sitzung (_abruf_sitzung)",
          bool(_aufrufe) and all(any(kw.arg == "sitzung" and "_abruf_sitzung" in ast.unparse(kw.value)
                                     for kw in c.keywords) for c in _aufrufe),
          [ast.unparse(c) for c in _aufrufe])

print(f"\n\033[1mErgebnis: {_ok}/{_ok + _fail}\033[0m")
sys.exit(1 if _fail else 0)

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


class _C:
    SECRET_KEY = "testgeheimnis-fuer-den-waechter"

    def get_setting(self, k, d=None):
        return {"download_key_ttl_min": 15, "download_key_strict": False}.get(k, d)


_cfg.config = _C()
sys.modules["backend.config"] = _cfg
_bp = types.ModuleType("backend")
_bp.__path__ = [str(WURZEL / "backend")]
sys.modules.setdefault("backend", _bp)

from backend import download_key as dk  # noqa: E402

print("\n\033[1m1. Der Schluessel ist als Sitzungstoken wertlos\033[0m")
key, exp = dk.erzeugen("nexus\\sven.sander")
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
check("verify_token ist auffindbar (Positivkontrolle)", bool(vt))
if vt:
    ns = {"time": time, "hmac": __import__("hmac"), "hashlib": __import__("hashlib"),
          "config": _C(), "_revoked_logins": {}, "_norm_login": lambda x: (x or "").lower()}
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
check("pruefen gibt den Benutzer zurueck", dk.pruefen(key) == "nexus\\sven.sander", dk.pruefen(key))
check("ein veraenderter Benutzer faellt durch",
      dk.pruefen(key.replace(dk._b64("nexus\\sven.sander"), dk._b64("nexus\\fremd"))) is None)
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
SPEISER = re.compile(r"_dlk\s*\(|JarvisDL")


def ohne_kommentare(text):
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


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
    for fund, wert in token_stellen(ohne_kommentare(datei.read_text(encoding="utf-8"))):
        if not SPEISER.search(wert):
            treffer.append(f"{datei.name}: {fund}")
check("JEDE ?token=-Adresse wird aus dem Abruf-Schluessel gespeist",
      not treffer, " | ".join(treffer[:4]))
# Positivkontrolle: die Suche findet ueberhaupt Stellen – sonst waere die
# Zeile darueber gruen, weil das Muster nichts trifft.
gefunden = sum(len(token_stellen(ohne_kommentare(d.read_text(encoding="utf-8"))))
               for d in (WURZEL / "frontend" / "js").glob("*.js") if d.name not in AUSNAHMEN)
check("die Suche findet die Adressen ueberhaupt (Positivkontrolle)",
      gefunden >= 8, f"gefunden={gefunden}")
check("und sie wuerde den Altstand melden (Gegenprobe im Test selbst)",
      not SPEISER.search("?token=' + encodeURIComponent(tk)"))

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
check("und der ist per Vorgabe AUS (ein harter Schnitt braeche die Android-App)",
      dk.streng() is False)
check("der Endpunkt nimmt KEIN Ziel entgegen (er bindet an den Benutzer, nicht an eine Datei)",
      re.search(r'@app\.get\("/api/download-key"\)\s*\nasync def download_key_holen\('
                r'user: str = Depends\(require_auth\)\)', QUELLE) is not None)

print(f"\n\033[1mErgebnis: {_ok}/{_ok + _fail}\033[0m")
sys.exit(1 if _fail else 0)

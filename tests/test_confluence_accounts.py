#!/usr/bin/env python3
"""Waechter: persoenlicher Confluence-Zugang (backend/confluence_accounts.py).

**Vorgabe 2026-09-29:** der in der Confluence-Skill-Config hinterlegte Token ist
ab jetzt nur noch der RUECKFALL. Wer unter *Mein Confluence-Zugang*
(``/confluence-addon``) einen eigenen PAT hinterlegt, arbeitet damit – bei den
``confluence_*``-Werkzeugen im Chat.

Geprueft wird die AUFLOESUNG (welcher Token gilt fuer welchen Lauf), die
Feld-Whitelist, die Geheimhaltung des Tokens, der Verbindungstest samt seinem
404-Rueckfall und die Verdrahtung. Der Rechte-Namensraum haengt an
``tests/test_endpoint_rights.py``, die Klartext-Ausgabe an
``tests/test_secret_reveal.py``.

⚠ SANDKASTEN MIT EXIT 2. Konten- und Schluesseldatei werden umgebogen; zeigt
eine davon nicht ins Wegwerf-Verzeichnis, bricht der Lauf mit **2** ab – ein
Test, der die echte ``data/confluence_accounts.json`` ueberschreibt, nimmt einem
Benutzer im Betrieb seinen Zugang.

Lauf:  python3 tests/test_confluence_accounts.py
"""

import ast
import json
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(text, bed, extra=""):
    """``check(Beschreibung, Bedingung)`` – **in DIESER Reihenfolge.**

    Der Abbruch bei vertauschten Argumenten ist kein Luxus: eine nicht-leere
    Zeichenkette ist wahr, ein vertauschter Aufruf meldet also OK, ohne die
    Bedingung je auszuwerten (am 2026-08-28 in `test_jira_vorlagen.py` fuer
    57 Aufrufe genau so passiert)."""
    global _ok, _fail
    if not isinstance(text, str):
        print("ABBRUCH: check() vertauscht – erst die Beschreibung, dann die "
              "Bedingung (bekam %r)" % (text,))
        sys.exit(2)
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, (" – %s" % extra) if extra else ""))


def section(t):
    print("\n═══ %s" % t)


def sicher(fn, *a, **k):
    """Nie ungeprueft dereferenzieren: eine Pruefung darf FEHLSCHLAGEN, nicht
    ABBRECHEN – sonst endet der Lauf ohne Bilanz und ist von 'nicht gelaufen'
    nicht zu unterscheiden (Register)."""
    try:
        return fn(*a, **k), ""
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


# ── Stub, damit der echte config-Import die Live-settings.json nicht anfasst ──
_SKILLCFG = {"confluence": {"config": {"base_url": "https://wiki.firma.de",
                                       "api_token": "SAMMEL-TOKEN"}}}
if "backend.config" not in sys.modules:
    _cfg = types.ModuleType("backend.config")

    class _C:
        def get_skill_states(self):
            return _SKILLCFG

        def get_setting(self, k, d=None):
            return d

    _cfg.config = _C()
    sys.modules["backend.config"] = _cfg

from backend import confluence_accounts as ca  # noqa: E402

# ── Sandkasten ───────────────────────────────────────────────────────────────
_tmp = tempfile.mkdtemp(prefix="cflacc-test-")
ca.DATA_DIR = Path(_tmp)
ca.KONTEN_DATEI = Path(_tmp) / "confluence_accounts.json"
ca.SCHLUESSEL_DATEI = Path(_tmp) / ".confluencekey"
for _n in ("KONTEN_DATEI", "SCHLUESSEL_DATEI", "DATA_DIR"):
    if not str(getattr(ca, _n)).startswith(_tmp):
        print("ABBRUCH: Sandkasten greift nicht – %s = %s" % (_n, getattr(ca, _n)))
        sys.exit(2)

try:
    import cryptography  # noqa: F401
except Exception:
    print("ABBRUCH: 'cryptography' fehlt – ohne sie ist das Modul nicht pruefbar.")
    sys.exit(2)


def frisch():
    if ca.KONTEN_DATEI.exists():
        ca.KONTEN_DATEI.unlink()


# ═════════════════════════════════════════════════════════════════════════════
section("1) Ohne eigenen Token gilt der Sammelzugang")
# ═════════════════════════════════════════════════════════════════════════════
frisch()
r = ca.aufloesen("alice")
check("Quelle ist der Sammelzugang", r["quelle"] == ca.QUELLE_SAMMEL, r["quelle"])
check("und der Client traegt dessen Token",
      r["client"].token == "SAMMEL-TOKEN", r["client"].token)
check("ohne eigenen Zugang gibt es keinen Hinweis – es ist der Normalfall",
      r["hinweis"] == "", r["hinweis"])
check("hat_zugang() sagt nein", ca.hat_zugang("alice") is False)

# ═════════════════════════════════════════════════════════════════════════════
section("2) Mit eigenem Token gilt DIESER – das ist der ganze Punkt")
# ═════════════════════════════════════════════════════════════════════════════
ca.speichern("alice", {"api_token": "ALICE-PAT"})
r = ca.aufloesen("alice")
check("Quelle ist der persoenliche Zugang",
      r["quelle"] == ca.QUELLE_PERSOENLICH, r["quelle"])
check("der Client traegt ALICES Token, nicht den des Servers",
      r["client"].token == "ALICE-PAT", r["client"].token)
check("die ADRESSE kommt weiterhin vom Administrator",
      r["client"].base == "https://wiki.firma.de", r["client"].base)
check("ein anderer Benutzer bleibt beim Sammelzugang",
      ca.aufloesen("bob")["client"].token == "SAMMEL-TOKEN")

# ═════════════════════════════════════════════════════════════════════════════
section("3) Der Token verlaesst den Server NIE")
# ═════════════════════════════════════════════════════════════════════════════
info = ca.zugang_info("alice")
flach = json.dumps(info, ensure_ascii=False)
check("zugang_info nennt den Token nicht", "ALICE-PAT" not in flach, flach[:200])
check("auch nicht maskiert – es gibt nur ein Ja/Nein",
      info.get("token_gesetzt") is True and not any(
          isinstance(v, str) and "*" in v for v in info.values()))
check("die Adresse wird dagegen ANGEZEIGT (der Benutzer muss sie kennen)",
      info.get("basis_url") == "https://wiki.firma.de")
roh = ca.KONTEN_DATEI.read_text(encoding="utf-8")
check("und in der Datei liegt er verschluesselt, nicht im Klartext",
      "ALICE-PAT" not in roh, roh[:160])
# Der EINE ausdrueckliche Abrufweg (POST /api/secret/reveal, protokolliert).
w, f = ca.klartext("alice", "api_token")
check("klartext() gibt ihn auf ausdruecklichen Abruf heraus",
      w == "ALICE-PAT" and not f, "%r/%r" % (w, f))
w, f = ca.klartext("alice", "base_url")
check("… aber NUR Geheimfelder (fail-closed)",
      w == "" and "Geheimfeld" in f, "%r/%r" % (w, f))
w, f = ca.klartext("bob", "api_token")
check("… und ein leeres Feld meldet einen GRUND, nicht nur nichts",
      w == "" and bool(f), "%r/%r" % (w, f))

# ═════════════════════════════════════════════════════════════════════════════
section("4) Feld-Whitelist: die ADRESSE darf der Benutzer nicht setzen")
# ═════════════════════════════════════════════════════════════════════════════
# Ein freies Adressfeld waere eine SSRF-Flaeche ohne Gegenwert – es gibt genau
# ein Haus-Confluence. `user` fehlt ebenfalls bewusst: der PAT geht als Bearer
# und ist nicht benutzergebunden, ein Benutzerfeld waere ein Feld ohne Wirkung.
check("base_url steht NICHT in AENDERBAR", "base_url" not in ca.AENDERBAR,
      str(ca.AENDERBAR))
check("user steht NICHT in AENDERBAR", "user" not in ca.AENDERBAR,
      str(ca.AENDERBAR))
for feld in ("base_url", "user", "benutzer_norm", "letzter_erfolg"):
    e, _ = sicher(ca.speichern, "alice", {feld: "x"})
    check("Feld %r wird abgewiesen" % feld, e is None)
_, txt = sicher(ca.speichern, "alice", {"base_url": "http://boese"})
check("und die Meldung nennt den Weg (Administrator)",
      "Administrator" in txt, txt)
check("die Adresse blieb unveraendert",
      ca.aufloesen("alice")["client"].base == "https://wiki.firma.de")

# ═════════════════════════════════════════════════════════════════════════════
section("5) Leeres Token-Feld heisst UNVERAENDERT, nicht 'loeschen'")
# ═════════════════════════════════════════════════════════════════════════════
# Sonst ueberschriebe ein Klick auf den Haken "verwenden" den Token mit einem
# Leerstring – derselbe Fehler, der beim Postfach und beim Lizenz-Dienstkonto
# behoben wurde.
ca.speichern("alice", {"aktiv": True, "api_token": ""})
check("der Token steht noch",
      ca.aufloesen("alice")["client"].token == "ALICE-PAT")
ca.speichern("alice", {"api_token": "ALICE-NEU"})
check("ein gefuelltes Feld ersetzt ihn",
      ca.aufloesen("alice")["client"].token == "ALICE-NEU")

# ═════════════════════════════════════════════════════════════════════════════
section("6) Der Haken 'verwenden' schaltet auf den Sammelzugang zurueck")
# ═════════════════════════════════════════════════════════════════════════════
ca.speichern("alice", {"aktiv": False})
r = ca.aufloesen("alice")
check("inaktiv → Sammelzugang", r["quelle"] == ca.QUELLE_SAMMEL)
check("MIT Hinweis – ein stiller Wechsel waere eine Anzeige ohne Aussage",
      "inaktiv" in r["hinweis"], r["hinweis"])
check("der Token bleibt gespeichert (nur abgeschaltet)",
      ca.zugang_info("alice")["token_gesetzt"] is True)
ca.speichern("alice", {"aktiv": True})
check("wieder an → persoenlicher Zugang",
      ca.aufloesen("alice")["quelle"] == ca.QUELLE_PERSOENLICH)

# ═════════════════════════════════════════════════════════════════════════════
section("7) Der Benutzerschluessel wird normiert")
# ═════════════════════════════════════════════════════════════════════════════
# Ohne Normalisierung haette dieselbe Person je Anmeldeform einen eigenen
# Zugang und wuerde ihren eigenen nicht wiederfinden (Register).
frisch()
ca.speichern("firma\\Alice", {"api_token": "A-PAT"})
for form in ("alice", "ALICE", "firma\\alice", "alice@firma.de"):
    check("dieselbe Person unter %r findet ihren Token" % form,
          ca.aufloesen(form)["client"].token == "A-PAT")

# ═════════════════════════════════════════════════════════════════════════════
section("8) Kanal-Kennungen bekommen keinen Zugang")
# ═════════════════════════════════════════════════════════════════════════════
# wa:/tg:/api: sind Telefonnummern und Quellen, keine Personen mit
# Confluence-Konto.
for kennung in ("wa:+4915112345", "tg:99887", "api:Vision-Kamera"):
    e, _ = sicher(ca.speichern, kennung, {"api_token": "X"})
    check("%r wird abgewiesen" % kennung, e is None)
    check("%r laeuft ueber den Sammelzugang" % kennung,
          ca.aufloesen(kennung)["quelle"] == ca.QUELLE_SAMMEL)

# ═════════════════════════════════════════════════════════════════════════════
section("9) Ohne Adresse nuetzt der beste Token nichts – und das wird gesagt")
# ═════════════════════════════════════════════════════════════════════════════
frisch()
ca.speichern("alice", {"api_token": "A-PAT"})
_SKILLCFG["confluence"]["config"]["base_url"] = ""
r = ca.aufloesen("alice")
check("ohne Adresse gibt es keinen persoenlichen Zugang",
      r["quelle"] == ca.QUELLE_SAMMEL)
check("und der Hinweis nennt den Ort, an dem sie fehlt",
      "Skill" in r["hinweis"] and "Adresse" in r["hinweis"], r["hinweis"])
check("die Oberflaeche erfaehrt es ebenfalls",
      ca.zugang_info("alice")["server_konfiguriert"] is False)
_SKILLCFG["confluence"]["config"]["base_url"] = "https://wiki.firma.de"

# ═════════════════════════════════════════════════════════════════════════════
section("10) Loeschen stellt den Sammelzugang wieder her")
# ═════════════════════════════════════════════════════════════════════════════
check("loeschen() meldet Erfolg", ca.loeschen("alice") is True)
check("danach gilt wieder der Sammelzugang",
      ca.aufloesen("alice")["client"].token == "SAMMEL-TOKEN")
check("ein zweites Loeschen meldet ehrlich 'nichts da'",
      ca.loeschen("alice") is False)

# ═════════════════════════════════════════════════════════════════════════════
section("11) Der ContextVar ist die EINZIGE Quelle des Benutzers")
# ═════════════════════════════════════════════════════════════════════════════
# Kaeme er aus einem Werkzeug-Argument, koennte das Modell (und damit eine
# Prompt-Injektion) waehlen, mit wessen Token es liest – und unter wessen Namen
# es eine Seite anlegt.
frisch()
ca.speichern("alice", {"api_token": "A-PAT"})
tok = ca.current_confluence_user.set("alice")
try:
    check("aufloesen() ohne Argument nimmt den ContextVar",
          ca.client_fuer_lauf().token == "A-PAT")
finally:
    ca.current_confluence_user.reset(tok)
check("ausserhalb eines Laufs gilt der Sammelzugang",
      ca.client_fuer_lauf().token == "SAMMEL-TOKEN")

SKILL = (ROOT / "skills" / "confluence" / "main.py").read_text(encoding="utf-8")
schemata = re.findall(r'"([a-z_]*(?:benutzer|user|zugang|token|konto)[a-z_]*)"\s*:\s*\{',
                      SKILL)
check("kein confluence_*-Werkzeug hat ein Benutzer-/Token-Feld im Schema",
      not schemata, str(schemata))

# ═════════════════════════════════════════════════════════════════════════════
section("12) Der Verbindungstest prueft den PERSOENLICHEN Zugang")
# ═════════════════════════════════════════════════════════════════════════════
# Wuerde er den gerade GELTENDEN nehmen, meldete er bei kaputtem eigenem Token
# "ok" (der Sammelzugang antwortet) und der Benutzer haette keinen Weg zu seinem
# Fehler – dieselbe Falle wie beim SAP- und Jira-Verbindungstest.
_ECHTER_CLIENT = ca.ConfluenceClient


class _Stub:
    """Attrappe mit der ECHTEN Signatur und den ECHTEN Rueckgabeformen.

    ⚠ Eine Attrappe, die eine BEQUEMERE Form anbietet als das Original, prueft
    eine Kette, die es nicht gibt (Register). ``current_user`` gibt deshalb ein
    dict mit ``displayName``/``username``, wie Confluence Server/DC es liefert.

    ⚠ UND ``cfg=None`` HEISST "LIES DIE SKILL-CONFIG", nicht "leer" – genau das
    hatte die erste Fassung falsch (``cfg or {}``), womit ``sammel_client()``
    einen Client ohne Token ergab. Gefangen hat es nur die Positivkontrolle
    unten; ohne sie waere die Messung des Verbindungstests trivial gewesen.
    """
    lauf = []

    def __init__(self, cfg=None):
        cfg = cfg if cfg is not None else ca.get_confluence_config()
        self.base = (cfg.get("base_url") or "").strip().rstrip("/")
        self.token = (cfg.get("api_token") or "").strip()

    @property
    def configured(self):
        return bool(self.base and self.token)

    def current_user(self):
        _Stub.lauf.append(("current_user", self.token))
        if _Stub.cu_wirft is not None:
            raise _Stub.cu_wirft
        return {"displayName": "Alice A.", "username": "alice"}

    def spaces(self, limit=50):
        _Stub.lauf.append(("spaces", self.token))
        if _Stub.sp_wirft is not None:
            raise _Stub.sp_wirft
        return [{"key": "DOC"}]


_Stub.cu_wirft = None
_Stub.sp_wirft = None
ca.ConfluenceClient = _Stub
try:
    frisch()
    ca.speichern("alice", {"api_token": "A-PAT"})
    _Stub.lauf.clear()
    d, err = sicher(ca.testen, "alice")
    check("der Test laeuft und liefert Namen und Konto",
          d is not None and d["anzeigename"] == "Alice A." and d["konto"] == "alice",
          "%s %s" % (d, err))
    check("⚠ und er benutzt ALICES Token, nicht den des Servers",
          _Stub.lauf == [("current_user", "A-PAT")], str(_Stub.lauf))
    check("der Erfolg wird am Zugang vermerkt",
          ca.zugang_info("alice")["letzter_erfolg"] > 0)
    check("… samt Namen, damit ein fremder Token auffaellt",
          ca.zugang_info("alice")["anzeigename"] == "Alice A.")

    # ⚠ DIESER FALL IST DER EIGENTLICHE BEWEIS – und er hat gefehlt. Mit einem
    # AKTIVEN eigenen Token liefern "der persoenliche" und "der gerade geltende
    # Zugang" DENSELBEN Client: die Pruefung darueber kann die beiden gar nicht
    # unterscheiden, und die Gegenprobe "Test nimmt den geltenden Zugang" blieb
    # deshalb stumm (2026-09-29). Der Unterschied wird erst sichtbar, wenn der
    # eigene Zugang NICHT der geltende ist – genau die Lage, in der der Knopf
    # sonst "ok" meldet, weil der Sammelzugang antwortet.
    ca.speichern("alice", {"aktiv": False})
    check("Positivkontrolle: inaktiv gilt der Sammelzugang",
          ca.client_fuer_lauf("alice").token == "SAMMEL-TOKEN")
    _Stub.lauf.clear()
    d, err = sicher(ca.testen, "alice")
    check("⚠ der Test nimmt trotzdem den PERSOENLICHEN Token",
          [t for _n, t in _Stub.lauf] == ["A-PAT"], "%s %s" % (_Stub.lauf, err))
    ca.speichern("alice", {"aktiv": True})

    # 404 = diesen Pfad kennt der Server nicht (Cloud, aeltere Staende). Ein
    # funktionierender Token darf deshalb NICHT als kaputt gemeldet werden.
    _Stub.cu_wirft = ca.ConfluenceError(404, "not found")
    _Stub.lauf.clear()
    d, err = sicher(ca.testen, "alice")
    check("⚠ bei 404 gilt eine Lebendpruefung als Erfolg",
          d is not None, err)
    check("… und sie geht ueber spaces(), also wirklich ans Netz",
          ("spaces", "A-PAT") in _Stub.lauf, str(_Stub.lauf))
    check("… der Name bleibt dann LEER statt geraten",
          bool(d) and d["anzeigename"] == "" and d["konto"] == "", str(d))

    # Jeder ANDERE Fehler ist ein echter Fehlschlag – ein Rueckfall auf alles
    # wuerde einen abgelehnten Token gruenfaerben.
    for status in (401, 403):
        _Stub.cu_wirft = ca.ConfluenceError(status, "nope")
        _Stub.sp_wirft = None
        _Stub.lauf.clear()
        d, err = sicher(ca.testen, "alice")
        check("⚠ HTTP %d wird als Fehlschlag gemeldet, nicht umgangen" % status,
              d is None and "ConfluenceKontoFehler" in err, "%s %s" % (d, err))
        check("… und spaces() wird dabei NICHT als Rueckfall gerufen",
              not any(n == "spaces" for n, _t in _Stub.lauf), str(_Stub.lauf))
        check("… der Fehler steht danach am Zugang",
              bool(ca.zugang_info("alice")["letzter_fehler"]))

    # Auch der Rueckfall darf scheitern.
    _Stub.cu_wirft = ca.ConfluenceError(404, "not found")
    _Stub.sp_wirft = ca.ConfluenceError(401, "abgelehnt")
    d, err = sicher(ca.testen, "alice")
    check("⚠ scheitert auch die Lebendpruefung, ist es ein Fehlschlag",
          d is None and "ConfluenceKontoFehler" in err, "%s %s" % (d, err))
    _Stub.cu_wirft = _Stub.sp_wirft = None

    # Ohne eigenen Token gibt es nichts zu testen – und das sagt der Fehler.
    ca.loeschen("alice")
    d, err = sicher(ca.testen, "alice")
    check("ohne eigenen Token wird der Test abgewiesen",
          d is None and "kein eigener Token" in err, "%s %s" % (d, err))
    # Ein NEUER Token raeumt den alten Fehler ab – er gehoert nicht mehr dazu.
    ca.speichern("alice", {"api_token": "A-PAT"})
    ca.merke_ergebnis("alice", False, "alter Fehler")
    ca.speichern("alice", {"api_token": "A-NEU"})
    check("ein neuer Token loescht den alten Fehler am Zugang",
          ca.zugang_info("alice")["letzter_fehler"] == "",
          ca.zugang_info("alice")["letzter_fehler"])
finally:
    ca.ConfluenceClient = _ECHTER_CLIENT

# ═════════════════════════════════════════════════════════════════════════════
section("13) EINE Konstruktionsstelle – als REGEL, nicht als Liste")
# ═════════════════════════════════════════════════════════════════════════════
# ⚠ Gemessen wird die EIGENSCHAFT: jede Stelle, die einen ConfluenceClient
# BAUT, ist entweder der geteilte Client selbst, das Konten-Modul, oder sie
# steht auf der unten begruendeten Liste der Sammelzugang-Stellen. Damit faellt
# eine KUENFTIGE Konstruktionsstelle von selbst auf und verlangt eine
# Entscheidung – eine gepflegte Liste waere an dem Tag unvollstaendig, an dem
# jemand eine ergaenzt (dieselbe Lehre wie bei den vier `_client()`-Stellen des
# Jira-Zugangs, wo eine halbe Umstellung zwei verschiedene Ergebnisse lieferte).
#
# ABSICHTLICH beim Sammelzugang – jede Zeile mit eigenem Grund:
SAMMEL_OK = {
    # Fuellt die GEMEINSAME Wissensdatenbank. Mit einem persoenlichen Token
    # haenge der Inhalt des geteilten Index davon ab, wer den Lauf zuletzt
    # angestossen hat.
    "backend/confluence_abgleich.py",
    # Holt Profilbilder fuer ALLE Benutzer – eine Serveraufgabe ohne Person.
    "backend/avatar.py",
}
ERLAUBT = {"backend/confluence_client.py", "backend/confluence_accounts.py"}
bauer = []
for pfad in sorted(ROOT.glob("backend/*.py")) + sorted(ROOT.glob("skills/*/main.py")):
    rel = pfad.relative_to(ROOT).as_posix()
    baum, fehler = sicher(ast.parse, pfad.read_text(encoding="utf-8"))
    if baum is None:
        check("%s ist parsebar" % rel, False, fehler)
        continue
    for knoten in ast.walk(baum):
        if (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Name)
                and knoten.func.id == "ConfluenceClient"):
            bauer.append(rel)
bauer = sorted(set(bauer))
# Positivkontrolle: findet die Regel ueberhaupt Stellen? Eine leere Menge waere
# trivial erfuellt und der ganze Abschnitt wertlos.
check("Positivkontrolle: die Regel findet Konstruktionsstellen",
      len(bauer) >= 3, str(bauer))
check("keine unbegruendete Konstruktionsstelle",
      not (set(bauer) - ERLAUBT - SAMMEL_OK),
      str(sorted(set(bauer) - ERLAUBT - SAMMEL_OK)))
check("⚠ der SKILL baut keinen Client selbst – er fragt das Konten-Modul",
      "skills/confluence/main.py" not in bauer, str(bauer))

# ⚠ VORGABE 2026-09-29: der eigene Zugang hat IN JEDEM BEREICH Vorrang. Als
# REGEL ueber main.py: jede Funktion mit angemeldetem Benutzer (`user`-
# Parameter), die `_confluence_client` ruft, reicht ihn weiter. Einzige
# Ausnahme: der Verbindungstest der Skill-Konfiguration prueft GENAU den
# Sammelzugang. `_cfb_aktiv` hat keinen Benutzer und faellt nicht unter die Regel.
MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_mb = ast.parse(MAIN_SRC)
SAMMEL_FN = {"confluence_test"}
_mit_user, _ohne_user = [], []
for _f in ast.walk(_mb):
    if not isinstance(_f, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    if _f.name == "_confluence_client":
        continue
    _hat_user = any(a.arg == "user" for a in _f.args.args + _f.args.kwonlyargs)
    for _x in ast.walk(_f):
        if (isinstance(_x, ast.Call) and isinstance(_x.func, ast.Name)
                and _x.func.id == "_confluence_client" and _hat_user):
            _gibt = (len(_x.args) == 1 and isinstance(_x.args[0], ast.Name)
                     and _x.args[0].id == "user")
            (_mit_user if _gibt else _ohne_user).append(_f.name)
check("Positivkontrolle: Aufrufe von `_confluence_client` mit Benutzer gefunden",
      len(_mit_user) >= 5, str(_mit_user))
check("⚠ jeder Aufruf mit angemeldetem Benutzer reicht `user` weiter",
      not (set(_ohne_user) - SAMMEL_FN), str(sorted(set(_ohne_user) - SAMMEL_FN)))
_cc = next((f for f in ast.walk(_mb) if isinstance(f, ast.FunctionDef)
            and f.name == "_confluence_client"), None)
# AUSGEFUEHRT, nicht gelesen: ein Vorkommen von `client_fuer_lauf(user)` bliebe
# auch in einem toten Zweig wahr (Gegenprobe `if False:` – 0 FAIL am Text).
import backend as _bk  # noqa: E402
_rufe = []
class _FakeCfa:
    @staticmethod
    def client_fuer_lauf(u=None):
        _rufe.append(("eigen", u)); return "EIGEN"
    @staticmethod
    def sammel_client():
        _rufe.append(("sammel", None)); return "SAMMEL"
_ns_cc = {}
_alt_mod = sys.modules.get("backend.confluence_accounts")
_alt_attr = getattr(_bk, "confluence_accounts", None)
try:
    sys.modules["backend.confluence_accounts"] = _FakeCfa
    _bk.confluence_accounts = _FakeCfa
    if _cc is not None:
        exec(compile(ast.Module(body=[_cc], type_ignores=[]), "main.py", "exec"), _ns_cc)
    _f_cc = _ns_cc.get("_confluence_client")
    _mit = _f_cc("m.mustermann") if _f_cc else None
    _ohne = _f_cc() if _f_cc else None
finally:
    if _alt_mod is not None:
        sys.modules["backend.confluence_accounts"] = _alt_mod
    else:
        sys.modules.pop("backend.confluence_accounts", None)
    if _alt_attr is not None:
        _bk.confluence_accounts = _alt_attr
check("⚠ `_confluence_client(user)` liefert den Zugang des BENUTZERS",
      _mit == "EIGEN" and ("eigen", "m.mustermann") in _rufe, str(_rufe))
check("`_confluence_client()` ohne Benutzer liefert den Sammelzugang",
      _ohne == "SAMMEL", str(_rufe))
check("main.py baut keinen ConfluenceClient selbst",
      "backend/main.py" not in bauer, str(bauer))

# Und die Verdrahtung: `_client()` des Skills MUSS ueber die Aufloesung gehen,
# und `_guard()` darueber laufen (sonst haette ein Werkzeug den Sammelzugang,
# waehrend das daneben den persoenlichen nimmt).
_baum = ast.parse(SKILL)
_fn = {n.name: n for n in ast.walk(_baum)
       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
check("skills/confluence/main.py hat ein _client()", "_client" in _fn)
_cl = ast.unparse(_fn["_client"]) if "_client" in _fn else ""
check("… und es ruft confluence_accounts.client_fuer_lauf()",
      "client_fuer_lauf" in _cl, _cl[:200])
check("_guard() laeuft ueber _client() (EINE Stelle fuer alle Werkzeuge)",
      "_guard" in _fn and "_client()" in ast.unparse(_fn["_guard"]))
check("und kein Werkzeug baut daneben einen eigenen Client",
      SKILL.count("ConfluenceClient(") == 0, str(SKILL.count("ConfluenceClient(")))

AGENT = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
check("agent.py setzt den ContextVar je Werkzeug-Aufruf",
      "current_confluence_user" in AGENT)
check("und nimmt ihn im finally zurueck (sonst haengt er am naechsten Lauf)",
      "_ccv.reset(_c_token)" in AGENT)

# ═════════════════════════════════════════════════════════════════════════════
section("14) Die Dateien stehen in ALLEN vier Sperrlisten")
# ═════════════════════════════════════════════════════════════════════════════
# confluence_accounts.json + .confluencekey ergeben zusammen die Klartext-Token;
# ein PAT traegt die vollen Rechte seines Besitzers, und die Werkzeuge SCHREIBEN
# auch (Seite anlegen, kommentieren).
SBX = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
from backend import sandbox  # noqa: E402
check("data/confluence_accounts.json in _APP_DENY_REL",
      "data/confluence_accounts.json" in sandbox._APP_DENY_REL)
check("data/.confluencekey in _APP_DENY_REL",
      "data/.confluencekey" in sandbox._APP_DENY_REL)
check("data/confluence_accounts.json in PRIVATE_FILES (0640)",
      "data/confluence_accounts.json" in sandbox.PRIVATE_FILES)
check("data/.confluencekey in PRIVATE_FILES_STRENG (0600)",
      "data/.confluencekey" in sandbox.PRIVATE_FILES_STRENG)
check("beide im SHELL_SECRET_PATHS-Muster",
      "confluence_accounts" in SBX and r"\.confluencekey" in SBX)
# EIGENE Schluesseldatei: ein gemeinsamer Schluessel verbaende zwei Bereiche,
# und ein Restore eines einzelnen machte den anderen unlesbar.
check("⚠ eigene Schluesseldatei, nicht die des Jira-Moduls",
      ".confluencekey" in str(ca.SCHLUESSEL_DATEI)
      or _tmp in str(ca.SCHLUESSEL_DATEI))
QUELLE = (ROOT / "backend" / "confluence_accounts.py").read_text(encoding="utf-8")
check("… und im Quelltext steht keine fremde Schluesseldatei",
      ".jirakey" not in QUELLE and ".sapkey" not in QUELLE)

# ═════════════════════════════════════════════════════════════════════════════
section("15) Endpunkte, Route und Rechte")
# ═════════════════════════════════════════════════════════════════════════════
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
for m, pfad in (("get", "/api/confluence/account"),
                ("post", "/api/confluence/account"),
                ("delete", "/api/confluence/account"),
                ("post", "/api/confluence/account/test")):
    check("%s %s existiert" % (m.upper(), pfad),
          '@app.%s("%s")' % (m, pfad) in MAIN)
check("alle vier haengen an require_confluence_account_access",
      MAIN.count("Depends(require_confluence_account_access)") == 4,
      str(MAIN.count("Depends(require_confluence_account_access)")))
check("die Seite /confluence-addon wird ausgeliefert",
      '@app.get("/confluence-addon")' in MAIN)
check("/api/me meldet permissions.confluence",
      '"confluence": _skill_active("confluence")' in MAIN)
# ⚠ Der Endpunkt filtert NICHT vor – die Whitelist im Modul ist die einzige
# Instanz. Zwei Schichten mit unterschiedlicher Meinung verwerfen ein Feld
# still und melden trotzdem Erfolg (Register).
_p = MAIN.index('@app.post("/api/confluence/account")')
_rumpf = MAIN[_p:_p + 1800]
check("⚠ der POST reicht den Rumpf UNVERAENDERT durch",
      "speichern(user, body)" in _rumpf, _rumpf[-200:])
check("… und der Benutzer kommt aus der Anmeldung, nie aus dem Rumpf",
      'body.get("user")' not in _rumpf and 'body.get("benutzer")' not in _rumpf)
check("der Test laeuft im Thread (ConfluenceClient ist synchron)",
      "to_thread(confluence_accounts.testen, user)" in MAIN)
# Die Freigabe ist EINE Funktion – Dependency UND secret_reveal fragen dieselbe.
check("die Freigabe steht in genau EINER Funktion",
      MAIN.count("def _user_may_use_confluence_account(") == 1)
check("die Dependency benutzt sie",
      "if _user_may_use_confluence_account(user):" in MAIN)
check("und die Rechtematrix von /api/secret/reveal ebenfalls",
      '"confluence": _user_may_use_confluence_account,' in MAIN)
SR = (ROOT / "backend" / "secret_reveal.py").read_text(encoding="utf-8")
check("secret_reveal kennt den Bereich 'confluence'",
      'b == "confluence"' in SR)

# ═════════════════════════════════════════════════════════════════════════════
section("16) Oberflaeche: Kachel, Container, i18n in DE UND EN")
# ═════════════════════════════════════════════════════════════════════════════
HTML = (ROOT / "frontend" / "confluence_addon.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "confluence_addon.js").read_text(encoding="utf-8")
PORTAL = (ROOT / "frontend" / "portal.html").read_text(encoding="utf-8")
# Portal-Logik liegt seit BSI H4 (CSP ohne Inline-Skript, 2026-10-04) in js/portal_seite.js.
PORTAL_JS = (ROOT / "frontend" / "js" / "portal_seite.js").read_text(encoding="utf-8")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")

check("es gibt einen Container 'Mein Confluence-Zugang'",
      'id="ca-sect-account"' in HTML)
check("er ist OFFEN (einziger Container der Seite)",
      re.search(r'id="ca-sect-account"[^>]*\bopen\b', HTML) is not None)
check("der Plugin-Container der Jira-Seite ist NICHT mitkopiert",
      "ja-sect-plugin" not in HTML and "browser-addon" not in HTML)
check("die Seite laedt das geteilte CSS (keine zweite Fassung)",
      "css/jira_addon.css?v=" in HTML)
check("… und es gibt keine eigene confluence_addon.css",
      not (ROOT / "frontend" / "css" / "confluence_addon.css").exists())
check("das Kennwortfeld traegt das Auge (Anweisung des Betreibers)",
      'data-pw-quelle="confluence"' in HTML and 'data-pw-kennung="api_token"' in HTML)
check("die Seite bindet ihr Modul ein",
      "js/confluence_addon.js?v=" in HTML)

check("die Portal-Kachel existiert", 'id="pt-card-confluence"' in PORTAL)
check("… und fuehrt auf /confluence-addon",
      'id="pt-card-confluence" href="/confluence-addon"' in PORTAL)
check("… und wird an permissions.confluence eingeblendet",
      "d.permissions.confluence" in PORTAL_JS)
check("fail-closed: ohne Auskunft geht die Seite aufs Portal",
      "me.permissions && me.permissions.confluence" in JS
      and "replace('/portal')" in JS)
check("die Seite benutzt eigene Element-Kennungen (kein ja-*-Konflikt)",
      "ja-acc-token" not in JS and "ca-acc-token" in JS)

# Jeder im JS und im Markup benutzte caddon.*-Schluessel MUSS in BEIDEN Sprachen
# stehen – als REGEL ueber die wirklich benutzten Schluessel, nicht als Liste:
# ein fehlender Schluessel faellt sonst erst dem englischen Benutzer auf.
benutzt = set(re.findall(r"data-i18n(?:-html|-title|-placeholder|-aria)?=\"(caddon\.[a-z0-9_]+)\"", HTML))
benutzt |= set(re.findall(r"T\('(caddon\.[a-z0-9_]+)'", JS))
check("Positivkontrolle: es werden caddon.*-Schluessel benutzt",
      len(benutzt) >= 15, str(len(benutzt)))
fehlend = sorted(k for k in benutzt if I18N.count("'%s'" % k) < 2)
check("jeder benutzte caddon.*-Schluessel steht in DE UND EN",
      not fehlend, str(fehlend))
for k in ("portal.card_confluence", "portal.card_confluence_desc"):
    check("%s steht in DE und EN" % k, I18N.count("'%s'" % k) >= 2)

# Die Seite meldet ihre Aktivitaet – und die Kennung muss die sein, die
# activity.js aus dem PFAD bildet (mit Bindestrich).
check("⚠ die Aktivitaets-Kennung passt zum Pfad (Bindestrich, nicht Unterstrich)",
      '"confluence-addon": "Confluence"' in MAIN)

print("\n── Code-Review 2026-10-07: Sperre und unlesbare Datei ──")
import threading as _th  # noqa: E402
frisch()
_fehler = []


def _schreiber(name, n):
    for i in range(n):
        try:
            ca.speichern(name, {"api_token": "tok-%s-%d" % (name, i)})
            ca.merke_ergebnis(name, True, anzeigename=name)
        except Exception as e:  # noqa: BLE001
            _fehler.append(repr(e))


_fs = [_th.Thread(target=_schreiber, args=("nutzer%d" % k, 25)) for k in range(6)]
for _f in _fs:
    _f.start()
for _f in _fs:
    _f.join()
_alle = ca._laden()
check("⚠ 6 Benutzer speichern gleichzeitig: kein Fehler (keine geteilte .tmp)", not _fehler,
      _fehler[:2])
check("⚠ … und KEIN Zugang ging verloren (Lesen-Aendern-Schreiben unter Sperre)",
      sorted(_alle) == sorted("nutzer%d" % k for k in range(6)), sorted(_alle))
check("keine .tmp-Reste", not list(ca.KONTEN_DATEI.parent.glob("*.tmp")))
ca.KONTEN_DATEI.write_text('{"nutzer0": {"api_token_enc": "x"', encoding="utf-8")
_vorher = ca.KONTEN_DATEI.read_bytes()
try:
    ca.speichern("neu", {"api_token": "t"})
    _geworfen = None
except ca.ConfluenceKontoFehler as e:
    _geworfen = e
check("⚠ unlesbare Kontendatei: Speichern wird abgewiesen (statt alle anderen zu loeschen)",
      _geworfen is not None and _geworfen.kategorie == "fehler", repr(_geworfen))
check("⚠ … und die Datei bleibt unveraendert", ca.KONTEN_DATEI.read_bytes() == _vorher)
ca.merke_ergebnis("nutzer0", False, "x")
check("merke_ergebnis schreibt eine unlesbare Datei ebenfalls nicht",
      ca.KONTEN_DATEI.read_bytes() == _vorher)
frisch()

print("\n" + "═" * 70)
print("ERGEBNIS: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)

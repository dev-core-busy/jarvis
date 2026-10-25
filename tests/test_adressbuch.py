#!/usr/bin/env python3
"""Waechter: Adressbuch-Suche (Name -> E-Mail-Adresse), backend/adressbuch.py.

Gemessen wird der ECHTE Code AUSGEFUEHRT, mit Attrappen an den beiden
Aussengrenzen (Exchange und Verzeichnis). Die Attrappen bilden die echten
Signaturen und Rueckgabeformen nach – eine bequemere Attrappe wuerde eine
Kette pruefen, die es nicht gibt (Register).

Die Zusagen, die hier haengen:

1. Reihenfolge: Exchange zuerst, Verzeichnis als Rueckfall – und der Rueckfall
   greift NUR bei einem Fehlschlag, nicht bei einem leeren Ergebnis.
2. Ohne Benutzer wird GAR NICHT gesucht (fail-closed) – sonst waere das
   Dienstkonto ein Weg, das Firmen-Adressbuch ohne Identitaet zu lesen.
3. "Nichts gefunden" (Ergebnis) und "konnte nicht nachsehen" (Ausnahme) sind
   unterscheidbar – sie fuehren zu verschiedenen naechsten Schritten.
4. Eintraege ohne brauchbare Adresse fallen heraus (X500-Pfade, Benutzer ohne
   Postfach) – ein Treffer ohne Adresse ist eine Sackgasse mit dem Anschein
   eines Ergebnisses.
5. Ein ANMELDEfehler wird gezaehlt (Aussetzer-Buchhaltung), ein Netz-/Kanal-
   fehler NICHT – sonst setzt jede Netzstoerung das Postfach aus.
6. Die Suche uebergeht den Aussetzer NIEMALS (kein `trotz_aussetzer`): ein
   Tippvorschlag feuert wiederholt und ist kein Einzelklick.
7. Deckel und Mindestlaenge greifen.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

    python3 tests/test_adressbuch.py
"""
import ast
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0
_bilanz = False


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n── {t} " + "─" * max(0, 60 - len(t)))


def bilanz():
    global _bilanz
    _bilanz = True
    print("\n" + "=" * 62)
    print(f"Ergebnis: {_ok} ok, {_fail} fehlgeschlagen")
    print("=" * 62)


# ⚠ `backend.config` NUR als Stub: der echte Import schreibt die Live-
# settings.json zurueck (Register). `adressbuch` selbst importiert config
# nicht, aber `mail_client` haengt daran.
_cfg = types.ModuleType("backend.config")


class _Config:
    def get_setting(self, k, v=None):
        return v

    def get_skill_states(self):
        return {}

    def save_skill_state(self, *a, **kw):
        raise AssertionError("ein Waechter darf keinen Zustand schreiben")


_cfg.config = _Config()
sys.modules["backend.config"] = _cfg

try:
    from backend import adressbuch as A
    from backend.mail_client import MailFehler
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.adressbuch nicht importierbar: {type(e).__name__}: {e}")
    sys.exit(2)


# ── Attrappen ───────────────────────────────────────────────────────────────

class _ClientAttrappe:
    """Bildet MailClient nach – NUR die Teile, die adressbuch benutzt."""

    def __init__(self, treffer=None, fehler=None):
        self._treffer = treffer or []
        self._fehler = fehler
        self.gefragt = []
        self.geschlossen = 0

    def adressen_suchen(self, frage, limit=10):
        self.gefragt.append((frage, limit))
        if self._fehler is not None:
            raise self._fehler
        return list(self._treffer)[:limit]

    def schliessen(self):
        self.geschlossen += 1


class _Umgebung:
    """Setzt die beiden Aussengrenzen von `adressbuch` fuer EINEN Fall."""

    def __init__(self, *, ews_treffer=None, ews_fehler=None, konto_fehler=None,
                 ad_treffer=None, ad_fehler=None):
        self.client = _ClientAttrappe(ews_treffer, ews_fehler)
        self.konto_fehler = konto_fehler
        self.ad_treffer = ad_treffer or []
        self.ad_fehler = ad_fehler
        self.konto_rufe = []
        self.ad_rufe = []
        self.ergebnisse = []          # (ok, fehler, art) aus merke_ergebnis

    def __enter__(self):
        ma = types.ModuleType("backend.mail_accounts")

        def konto_fuer(user, **kw):
            # ⚠ Die Attrappe MERKT die Schlagwortargumente: die Zusage "die
            # Suche uebergeht den Aussetzer nicht" ist nur so messbar.
            self.konto_rufe.append((user, dict(kw)))
            if self.konto_fehler is not None:
                raise self.konto_fehler
            return object()

        def merke_ergebnis(user, ok, fehler="", art=""):
            self.ergebnisse.append((ok, fehler, art))

        ma.konto_fuer = konto_fuer
        ma.merke_ergebnis = merke_ergebnis

        ld = types.ModuleType("backend.ldap_directory")

        def search_users(q, bu=None, bp=None, limit=100):
            self.ad_rufe.append((q, limit))
            if self.ad_fehler is not None:
                raise self.ad_fehler
            return list(self.ad_treffer)

        ld.search_users = search_users

        mc = types.ModuleType("backend.mail_client")
        mc.MailFehler = MailFehler
        mc.MailClient = lambda konto: self.client

        self._alt = {}
        for name, mod in (("backend.mail_accounts", ma),
                          ("backend.ldap_directory", ld),
                          ("backend.mail_client", mc)):
            self._alt[name] = sys.modules.get(name)
            sys.modules[name] = mod
        A._reset_fuer_tests()
        return self

    def __exit__(self, *_):
        for name, mod in self._alt.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        A._reset_fuer_tests()
        return False


EWS_TREFFER = [{"name": "Max Mustermann", "adresse": "max.mustermann@beispiel.de",
                "art": "person"}]

# ── 0. Positivkontrolle des Messaufbaus ─────────────────────────────────────
abschnitt("0. Positivkontrolle: der Aufbau erreicht den echten Code")
with _Umgebung(ews_treffer=EWS_TREFFER) as u:
    res = A.suchen("anna.muster", "Mustermann")
pruefe(u.client.gefragt and u.client.gefragt[0][0] == "Mustermann",
       "die Exchange-Attrappe wird WIRKLICH gefragt", str(u.client.gefragt))
pruefe(res.get("quelle") == "ews" and res.get("treffer") == EWS_TREFFER,
       "und ihr Ergebnis kommt unveraendert zurueck", str(res))
if not u.client.gefragt:
    print("ABBRUCH: der Messaufbau erreicht den Produktivcode nicht – alle "
          "folgenden Pruefungen waeren trivial")
    bilanz()
    sys.exit(2)
pruefe(u.client.geschlossen == 1, "die Verbindung wird geschlossen",
       str(u.client.geschlossen))
pruefe(u.ergebnisse == [(True, "", "")],
       "ein Erfolg wird am Konto vermerkt (loest einen Aussetzer auf)",
       str(u.ergebnisse))

# ── 1. Reihenfolge und Rueckfall ────────────────────────────────────────────
abschnitt("1. Exchange zuerst, Verzeichnis als Rueckfall")
with _Umgebung(ews_treffer=EWS_TREFFER,
               ad_treffer=[{"display": "Falsch", "sam": "x",
                            "mail": "falsch@beispiel.de"}]) as u:
    res = A.suchen("anna.muster", "Mustermann")
pruefe(res["quelle"] == "ews" and not u.ad_rufe,
       "gelingt Exchange, wird das Verzeichnis NICHT gefragt", str(u.ad_rufe))

# Ein LEERES Exchange-Ergebnis ist eine Antwort – kein Grund fuer den Rueckfall.
with _Umgebung(ews_treffer=[], ad_treffer=[{"display": "Aus dem AD", "sam": "y",
                                            "mail": "ad@beispiel.de"}]) as u:
    res = A.suchen("anna.muster", "Niemand")
pruefe(res["quelle"] == "ews" and res["treffer"] == [] and not u.ad_rufe,
       "ein LEERES Ergebnis loest keinen Rueckfall aus (es ist eine Antwort)",
       str(res) + str(u.ad_rufe))

# Kanalfehler (IMAP-Postfach, EWS aus) -> Verzeichnis
with _Umgebung(ews_fehler=MailFehler("kein Adressbuch", "kanal", "imap"),
               ad_treffer=[{"display": "Max Mustermann", "sam": "mmuster",
                            "mail": "max.mustermann@beispiel.de"}]) as u:
    res = A.suchen("anna.muster", "Mustermann")
pruefe(res["quelle"] == "ad" and len(res["treffer"]) == 1
       and res["treffer"][0]["adresse"] == "max.mustermann@beispiel.de",
       "ohne Exchange liefert das Verzeichnis", str(res))
pruefe(bool(res["hinweis"]) and "Verzeichnis" in res["hinweis"],
       "und die Antwort NENNT die zweite Quelle samt Einschraenkung",
       res["hinweis"][:90])
# ⚠ HIER STAND `"Exchange" in res["hinweis"]` – und das war TRIVIAL WAHR:
# der feste Satz des Hinweises nennt "Exchange-Adressbuch" ohnehin, die
# Bedingung konnte also nie fehlschlagen. Aufgefallen ist es nur, weil die
# Gegenprobe "der Hinweis nennt den ersten Fehlschlag nicht" STUMM blieb –
# eine stumme Gegenprobe ist genauso oft eine zu breite Pruefung wie eine zu
# schwache Sabotage. Gemessen wird deshalb der GRUND des gescheiterten
# Versuchs, also ein Text, den nur dieser Weg erzeugen kann.
pruefe("kein Adressbuch" in res["hinweis"],
       "der Hinweis nennt den GRUND des ersten, gescheiterten Versuchs",
       res["hinweis"][:120])
pruefe(u.ad_rufe and u.ad_rufe[0][1] > A.VORGABE_LIMIT,
       "das Verzeichnis wird mit Reserve gefragt (Eintraege ohne Postfach "
       "fallen erst danach heraus)", str(u.ad_rufe))

# Kein Postfach hinterlegt -> ebenfalls Verzeichnis
with _Umgebung(konto_fehler=MailFehler("kein Postfach", "eingabe"),
               ad_treffer=[{"display": "Max Mustermann", "sam": "m",
                            "mail": "max.mustermann@beispiel.de"}]) as u:
    res = A.suchen("anna.muster", "Mustermann")
pruefe(res["quelle"] == "ad" and len(res["treffer"]) == 1,
       "ein Benutzer OHNE Postfach bekommt Treffer aus dem Verzeichnis", str(res))

# Beide Quellen weg -> Ausnahme, die BEIDE nennt
with _Umgebung(ews_fehler=MailFehler("EWS tot", "kanal", "ews"),
               ad_fehler=RuntimeError("NO_CREDENTIALS")) as u:
    try:
        A.suchen("anna.muster", "Mustermann")
        _geworfen = None
    except A.AdressbuchFehler as e:
        _geworfen = str(e)
    except Exception as e:  # noqa: BLE001
        _geworfen = "FALSCHE AUSNAHME: %r" % e
pruefe(_geworfen is not None and "AUSNAHME" not in _geworfen,
       "scheitern BEIDE Quellen, kommt AdressbuchFehler", str(_geworfen)[:90])
pruefe(_geworfen and "EWS tot" in _geworfen and "NO_CREDENTIALS" in _geworfen,
       "und die Meldung nennt BEIDE Versuche (nicht nur den letzten)",
       str(_geworfen)[:120])

# ── 2. Ohne Benutzer wird nicht gesucht ─────────────────────────────────────
abschnitt("2. Fail-closed: ohne Benutzer gar keine Suche")
for leer in ("", "   ", None):
    with _Umgebung(ews_treffer=EWS_TREFFER,
                   ad_treffer=[{"display": "X", "sam": "x",
                                "mail": "x@beispiel.de"}]) as u:
        try:
            A.suchen(leer, "Mustermann")
            schlecht = "kein Fehler"
        except A.AdressbuchFehler:
            schlecht = ""
        except Exception as e:  # noqa: BLE001
            schlecht = "falsche Ausnahme %r" % e
    pruefe(not schlecht, f"Benutzer {leer!r}: abgewiesen", schlecht)
    pruefe(not u.ad_rufe and not u.client.gefragt,
           f"Benutzer {leer!r}: KEINE Quelle wird gefragt "
           "(auch nicht das Dienstkonto)", str(u.ad_rufe))

# ── 3. Treffer ohne brauchbare Adresse fallen heraus ────────────────────────
abschnitt("3. Eintraege ohne Adresse sind keine Treffer")
with _Umgebung(ews_fehler=MailFehler("x", "kanal"),
               ad_treffer=[
                   {"display": "Ohne Postfach", "sam": "a", "mail": ""},
                   {"display": "X500", "sam": "b",
                    "mail": "/o=firma/cn=Recipients/cn=b"},
                   {"display": "Gut", "sam": "c", "mail": "gut@beispiel.de"},
                   {"display": "Doppelt", "sam": "d", "mail": "GUT@beispiel.de"},
               ]) as u:
    res = A.suchen("anna.muster", "Suche")
adressen = [t["adresse"] for t in res["treffer"]]
pruefe(adressen == ["gut@beispiel.de"],
       "ohne '@' kein Treffer, und gleiche Adresse nur EINMAL (ohne "
       "Ruecksicht auf Gross/Klein)", str(adressen))
pruefe(res["treffer"][0]["name"] == "Gut" and res["treffer"][0]["art"] == "person",
       "Name und Art werden gesetzt", str(res["treffer"]))

# ── 4. Anmeldefehler zaehlt, Netzfehler nicht ───────────────────────────────
abschnitt("4. Aussetzer-Buchhaltung: nur 'auth' zaehlt")
with _Umgebung(ews_fehler=MailFehler("Kennwort falsch", "auth", "ews"),
               ad_treffer=[]) as u:
    try:
        A.suchen("anna.muster", "Mustermann")
    except A.AdressbuchFehler:
        pass
pruefe(u.ergebnisse and u.ergebnisse[0][0] is False
       and u.ergebnisse[0][2] == "auth",
       "ein ANMELDEfehler wird mit art='auth' gemeldet", str(u.ergebnisse))

with _Umgebung(ews_fehler=MailFehler("Netz weg", "netz", "ews"),
               ad_treffer=[]) as u:
    A.suchen("anna.muster", "Mustermann")
pruefe(u.ergebnisse and u.ergebnisse[0][2] == "netz",
       "ein Netzfehler wird mit SEINER Kategorie gemeldet (zaehlt dort nicht "
       "gegen den Aussetzer)", str(u.ergebnisse))

# ── 5. Der Aussetzer wird NIE uebergangen ───────────────────────────────────
abschnitt("5. Kein trotz_aussetzer – ein Tippvorschlag ist kein Einzelklick")
with _Umgebung(ews_treffer=EWS_TREFFER) as u:
    A.suchen("anna.muster", "Mustermann")
pruefe(u.konto_rufe and not u.konto_rufe[0][1].get("trotz_aussetzer"),
       "konto_fuer wird OHNE trotz_aussetzer gerufen", str(u.konto_rufe))
# Dieselbe Zusage als REGEL am Syntaxbaum: ein spaeterer Aufrufer koennte sie
# an einer anderen Stelle setzen, die dieser Fall nicht durchlaeuft.
_quelle = (ROOT / "backend" / "adressbuch.py").read_text(encoding="utf-8")
_baum = ast.parse(_quelle)
_mit = [n for n in ast.walk(_baum)
        if isinstance(n, ast.keyword) and n.arg == "trotz_aussetzer"]
pruefe(not _mit, "und NIRGENDS im Modul steht trotz_aussetzer als Argument",
       str([ast.unparse(n) for n in _mit]))

# ── 6. Deckel, Mindestlaenge, Drossel ───────────────────────────────────────
abschnitt("6. Grenzen")
with _Umgebung(ews_treffer=EWS_TREFFER) as u:
    for kurz in ("", " ", "a"):
        res = A.suchen("anna.muster", kurz)
        pruefe(res["treffer"] == [] and bool(res["hinweis"]),
               f"Frage {kurz!r}: nicht gesucht, mit Begruendung", str(res))
    pruefe(not u.client.gefragt,
           "eine zu kurze Frage erreicht die Quelle gar nicht", str(u.client.gefragt))

VIELE = [{"name": "N%d" % i, "adresse": "n%d@beispiel.de" % i, "art": "person"}
         for i in range(100)]
with _Umgebung(ews_treffer=VIELE) as u:
    pruefe(u is not None, "Positivkontrolle: 100 Treffer stehen bereit")
    res = A.suchen("anna.muster", "Na")
    pruefe(len(res["treffer"]) == A.VORGABE_LIMIT,
           f"ohne Angabe gilt die Vorgabe ({A.VORGABE_LIMIT})",
           str(len(res["treffer"])))
    res = A.suchen("anna.muster", "Na", 999)
    pruefe(len(res["treffer"]) == A.MAX_LIMIT,
           f"ein zu grosses Limit wird gedeckelt ({A.MAX_LIMIT})",
           str(len(res["treffer"])))
    res = A.suchen("anna.muster", "Na", "quatsch")
    pruefe(len(res["treffer"]) == A.VORGABE_LIMIT,
           "ein unbrauchbares Limit faellt auf die Vorgabe zurueck",
           str(len(res["treffer"])))
    res = A.suchen("anna.muster", "Na", 0)
    pruefe(len(res["treffer"]) == 1, "Limit 0 wird auf 1 gehoben (kein leeres "
           "Ergebnis aus einer Zahl)", str(len(res["treffer"])))

# Drossel: der Deckel liegt bei MAX_JE_MINUTE, danach eine Ausnahme mit Grund.
with _Umgebung(ews_treffer=EWS_TREFFER) as u:
    pruefe(A.MAX_JE_MINUTE >= 10 and A.MAX_JE_MINUTE <= 120,
           f"der Minutendeckel ist plausibel ({A.MAX_JE_MINUTE})",
           str(A.MAX_JE_MINUTE))
    _durch = 0
    _gebremst = ""
    for _ in range(A.MAX_JE_MINUTE + 5):
        try:
            A.suchen("anna.muster", "Mustermann")
            _durch += 1
        except A.AdressbuchFehler as e:
            _gebremst = str(e)
            break
    pruefe(_durch == A.MAX_JE_MINUTE,
           f"genau {A.MAX_JE_MINUTE} Abfragen gehen durch", str(_durch))
    pruefe("Berechtigung" in _gebremst,
           "die Bremse sagt ausdruecklich, dass sie KEINE Rechtefrage ist",
           _gebremst[:90])
    # Ein anderer Benutzer ist davon nicht betroffen
    try:
        A.suchen("max.muster", "Mustermann")
        _fremd = True
    except A.AdressbuchFehler:
        _fremd = False
    pruefe(_fremd, "die Bremse zaehlt JE BENUTZER, nicht global")

# ── ist_aufgeloest: Herkunft eines Empfaengers (Code-Review 2026-10-25) ─────
# "Name <adresse>" ist die uebliche Form, in der ein Modell eine nachgeschlagene
# Adresse einsetzt – sie muss als aufgeloest gelten, sonst warnt die Karte im
# Regelfall (und eine Dauerwarnung wird ueberlesen).
_marke = A.aufgeloest_cv.set({"max@firma.local", "b@c.de"})
try:
    pruefe(A.ist_aufgeloest("max@firma.local") is True, "nackte Adresse: aufgeloest")
    pruefe(A.ist_aufgeloest("Max Muster <max@firma.local>") is True,
           "Form 'Name <adresse>': aufgeloest")
    pruefe(A.ist_aufgeloest('"Muster, Max" <MAX@firma.local>; b@c.de') is True,
           "Komma im Anzeigenamen + Semikolon-Trenner + Grossschreibung")
    pruefe(A.ist_aufgeloest("Max <max@firma.local>, fremd@x.de") is False,
           "eine nicht nachgeschlagene Adresse in der Zeile: NICHT aufgeloest")
    pruefe(A.ist_aufgeloest("nur ein Name") is False, "ohne Adresse: nicht aufgeloest")
finally:
    A.aufgeloest_cv.reset(_marke)
pruefe(A.ist_aufgeloest("max@firma.local") is None,
       "ohne Lauf-Klammer: UNBEKANNT (None), nicht 'nein'")

bilanz()
sys.exit(0 if _fail == 0 else 1)

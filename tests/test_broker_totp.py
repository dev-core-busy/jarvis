#!/usr/bin/env python3
"""Ein Authenticator-Eintrag fuer Anmeldung UND Root-Freigaben (2026-10-20).

WARUM ES DAS GIBT: der Betreiber will genau EINEN Eintrag in der
Authenticator-App. Moeglich sind zwei Richtungen, und nur eine davon ist
zulaessig:

  * Broker prueft gegen das Geheimnis des BACKENDS – damit kennt der
    Dienstbenutzer den Nachweis, und Befund K2 ist wieder offen (ein
    eingeschleuster Prozess rechnet sich selbst gueltige Codes).
  * Das Geheimnis liegt root-eigen im BROKER und die Anmeldung fragt ihn
    (``totp_secret == "broker"``, Op ``broker.totp_pruefen``). Das Backend
    kennt es nie. DAS ist der gebaute Weg.

Geprueft wird in drei Teilen:
  1. VERHALTEN von ``freigabe.pruefen`` – geteilter Wiederholschutz bei
     getrennten Sperren (das ist der Kern, siehe unten).
  2. REGEL ueber ``main.py``: jede Funktion, die einen 2FA-Code prueft, muss den
     Broker-Fall behandeln. Ohne diese Regel faellt der naechste neue Pruefweg
     still aus – genau so war ``/api/auth/bestaetigen`` beim Bau dieser
     Aenderung eine Stunde lang kaputt (``pruefen(user, "broker", code)`` kann
     NIE zutreffen, ohne jede Fehlermeldung).
  3. FAIL-CLOSED: ein unerreichbarer Broker heisst "keine Anmeldung".

DER KERN (Teil 1), weil er beim Lesen wie Kosmetik aussieht:
  * Wiederholschutz GEMEINSAM – sonst ist der Umbau eine VERSCHLECHTERUNG.
    Bisher ging ein gueltiger Code nur bei einer Freigabe durchs Backend
    (selten), jetzt bei jeder Anmeldung (oft); ohne gemeinsamen Schutz koennte
    ein kompromittiertes Backend den gerade eingetippten Anmeldecode fuer eine
    Root-Freigabe verwenden.
  * Sperren GETRENNT – sonst legt ein fehlschlagender Anmeldeversuch die
    Root-Freigaben fuer SPERRE_S lahm. Der Weg dorthin ist NICHT die
    Anmeldemaske (davor stehen IP-Drossel, Kontosperre und Kennwortpruefung),
    sondern der SOCKET: jeder Prozess des Dienstbenutzers kann
    ``broker.totp_pruefen`` direkt rufen, ohne Kennwort.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""

import ast
import base64
import json
import os
import pathlib
import sys
import tempfile
import time

PROJ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

ok = 0
fehler: list[str] = []


def p(name: str, bedingung: bool) -> None:
    global ok
    if bedingung:
        ok += 1
    else:
        fehler.append(name)


def abbruch(grund: str) -> None:
    print(f"ABBRUCH: {grund}", file=sys.stderr)
    print("Exit 2 – konnte nicht laufen, das ist KEIN bestandener Lauf.", file=sys.stderr)
    sys.exit(2)


# ───────────────────────── Teil 1: Verhalten ─────────────────────────
# Sandkasten: NIE gegen /etc/jarvis messen – ein Test, der den echten
# Freigabe-Schluessel ersetzt, sperrt den Betreiber aus.
sandkasten = tempfile.mkdtemp(prefix="brokertotp_")
os.environ["JARVIS_BROKER_FREIGABE_KEY"] = os.path.join(sandkasten, "k")
os.environ["JARVIS_BROKER_FREIGABE_STATE"] = os.path.join(sandkasten, "s")

try:
    from backend.broker import freigabe as f
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.broker.freigabe nicht importierbar: {e}")

# Positivkontrolle des Sandkastens: zeigt ein Pfad nach draussen, sofort raus.
for name, pfad in (("SCHLUESSEL", f.SCHLUESSEL), ("ZUSTAND", f.ZUSTAND)):
    if not str(pfad).startswith(sandkasten):
        abbruch(f"{name} zeigt aus dem Sandkasten heraus: {pfad}")

b32, uri = f.einrichten()
try:
    schl = base64.b32decode(b32 + "=" * (-len(b32) % 8))
except Exception as e:  # noqa: BLE001
    abbruch(f"einrichten() lieferte kein gueltiges Base32: {e}")
jetzt = time.time()


def code(dt: float = 0) -> str:
    return f._code(schl, int((jetzt + dt) // f.SCHRITT_S))


# Positivkontrolle: ohne sie waere jede Ablehnung unten trivial wahr
if f.pruefen(code(), jetzt, f.ZWECK_FREIGABE) != (True, "ok"):
    abbruch("ein frischer Code gilt nicht einmal – Messaufbau kaputt")
ok += 1

# 1a Wiederholschutz ueber BEIDE Zwecke hinweg
f.uebernehmen(b32, jetzt - 60)
p("Login nimmt einen frischen Code an",
  f.pruefen(code(), jetzt, f.ZWECK_LOGIN) == (True, "ok"))
p("die Freigabe lehnt den vom Login verbrauchten Code ab",
  f.pruefen(code(), jetzt, f.ZWECK_FREIGABE) == (False, "nachweis_verbraucht"))

f.uebernehmen(b32, jetzt - 60)
p("die Freigabe nimmt einen frischen Code an",
  f.pruefen(code(), jetzt, f.ZWECK_FREIGABE) == (True, "ok"))
p("der Login lehnt den von der Freigabe verbrauchten Code ab",
  f.pruefen(code(), jetzt, f.ZWECK_LOGIN) == (False, "nachweis_verbraucht"))

# 1b Sperren getrennt – in BEIDE Richtungen
f.uebernehmen(b32, jetzt - 60)
for _ in range(f.FEHL_MAX):
    f.pruefen("000000", jetzt, f.ZWECK_LOGIN)
p("nach FEHL_MAX falschen Codes ist der Login gesperrt",
  f.pruefen(code(), jetzt, f.ZWECK_LOGIN) == (False, "gesperrt"))
p("eine Login-Sperre legt die Freigaben NICHT lahm",
  f.pruefen(code(), jetzt, f.ZWECK_FREIGABE) == (True, "ok"))

f.uebernehmen(b32, jetzt - 60)
for _ in range(f.FEHL_MAX):
    f.pruefen("000000", jetzt, f.ZWECK_FREIGABE)
p("nach FEHL_MAX falschen Codes ist die Freigabe gesperrt",
  f.pruefen(code(), jetzt, f.ZWECK_FREIGABE) == (False, "gesperrt"))
p("eine Freigabe-Sperre legt den Login NICHT lahm",
  f.pruefen(code(), jetzt, f.ZWECK_LOGIN) == (True, "ok"))

# 1c uebernehmen(): der laufende Schritt gilt als verbraucht
f.uebernehmen(b32, jetzt)
p("nach uebernehmen ist der laufende Code verbraucht",
  f.pruefen(code(), jetzt, f.ZWECK_FREIGABE) == (False, "nachweis_verbraucht"))
p("der folgende Code gilt",
  f.pruefen(code(f.SCHRITT_S), jetzt + f.SCHRITT_S, f.ZWECK_FREIGABE) == (True, "ok"))

# 1d uebernehmen() nimmt keinen untauglichen Schluessel
for mist, warum in (("", "leer"), ("abc!", "kein Base32"), ("AAAA", "zu kurz")):
    try:
        f.uebernehmen(mist)
        p(f"uebernehmen lehnt ab: {warum}", False)
    except ValueError:
        p(f"uebernehmen lehnt ab: {warum}", True)

# 1e ein unbekannter Zweck darf keine Pruefung OHNE Sperre erzeugen
f.uebernehmen(b32, jetzt - 60)
p("ein unbekannter Zweck wird abgelehnt", f.pruefen(code(), jetzt, "xyz")[0] is False)

# 1f Altbestand: fehl/gesperrt_bis ohne Zweck galten fuer Freigaben
f.uebernehmen(b32, jetzt - 60)
f._schreibe_privat(f.ZUSTAND, json.dumps(
    {"letzter_schritt": 0, "fehl": 2, "gesperrt_bis": jetzt + 600}))
p("eine Altbestand-Sperre gilt fuer Freigaben weiter",
  f.pruefen(code(), jetzt, f.ZWECK_FREIGABE) == (False, "gesperrt"))

# 1g die Marke darf selbst kein Schluessel sein koennen – sonst waere der
# Verweis "broker" zugleich ein (sehr schwaches) Geheimnis.
try:
    f.uebernehmen(f.MARKE_IM_BROKER)
    p("MARKE_IM_BROKER laesst sich nicht als Schluessel uebernehmen", False)
except ValueError:
    p("MARKE_IM_BROKER laesst sich nicht als Schluessel uebernehmen", True)


# ──────────────── Teil 2: REGEL ueber die Pruefwege in main.py ────────────────
MAIN = (PROJ / "backend" / "main.py").read_text(encoding="utf-8")
try:
    BAUM = ast.parse(MAIN)
except SyntaxError as e:
    abbruch(f"backend/main.py nicht parsebar: {e}")

# Funktionen, die einen 2FA-Code gegen ein GESPEICHERTES Secret pruefen, duerfen
# den Broker-Fall nicht uebersehen. Ausnahme NUR mit Grund:
AUSNAHMEN = {
    # /totp/verify prueft ausschliesslich gegen ``totp_pending_secret`` (eine
    # laufende EINRICHTUNG). Daran steht die Marke nie: solange 2FA aktiv ist,
    # verweigert /totp/setup eine neue, und uebernehmen() raeumt pending ab.
    "totp_verify": "prueft nur das vorgemerkte Secret einer Einrichtung",
}

# Wege, die den Broker-Fall ERKENNEN muessen, ihn aber bewusst NICHT fragen.
# /totp/show gibt das Secret heraus – liegt es im Broker, gibt es nichts
# herauszugeben (409 mit dem Weg ueber die Root-Konsole). Den Broker zu fragen
# wuerde dort nur einen Code verbrauchen.
OHNE_BROKER_FRAGE = {
    "totp_show": "im Broker-Fall wird nichts herausgegeben, also kein Code verbraucht",
}


def _ruft(knoten: ast.AST, name: str) -> bool:
    """Ruft dieser Teilbaum ``name(...)`` oder ``x.name(...)`` auf? Exakt, per AST –
    ein Teilstring ist keine Identitaet (Register)."""
    for k in ast.walk(knoten):
        if not isinstance(k, ast.Call):
            continue
        fn = k.func
        if isinstance(fn, ast.Name) and fn.id == name:
            return True
        if isinstance(fn, ast.Attribute) and fn.attr == name:
            return True
    return False


def _prueft_totp_schutz(knoten: ast.AST) -> bool:
    """Ruft ``_totp_schutz.pruefen(...)`` – also die Pruefung gegen ein Secret,
    das das BACKEND kennt."""
    for k in ast.walk(knoten):
        if not isinstance(k, ast.Call):
            continue
        fn = k.func
        if (isinstance(fn, ast.Attribute) and fn.attr == "pruefen"
                and isinstance(fn.value, ast.Name) and fn.value.id == "_totp_schutz"):
            return True
    return False


pruefwege = [k for k in ast.walk(BAUM)
             if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
             and _prueft_totp_schutz(k)]

# Positivkontrolle: findet die Erkennung ueberhaupt etwas? Ohne sie waere die
# ganze Regel trivial wahr – und ein umbenanntes Modul macht sie dauerhaft blind.
if len(pruefwege) < 2:
    abbruch(f"nur {len(pruefwege)} Pruefweg(e) gefunden – die AST-Erkennung greift nicht "
            "(Modul ``_totp_schutz`` umbenannt?)")
ok += 1

for fn in pruefwege:
    if fn.name in AUSNAHMEN:
        p(f"{fn.name}: Ausnahme traegt einen Grund", bool(AUSNAHMEN[fn.name]))
        continue
    p(f"{fn.name} behandelt den Broker-Fall (_totp_im_broker)",
      _ruft(fn, "_totp_im_broker"))
    if fn.name in OHNE_BROKER_FRAGE:
        p(f"{fn.name}: fragt den Broker bewusst nicht – Grund benannt",
          bool(OHNE_BROKER_FRAGE[fn.name]))
        continue
    p(f"{fn.name} fragt den Broker (_totp_broker_pruefen)",
      _ruft(fn, "_totp_broker_pruefen"))

# Die Marke wird nirgends ABGETIPPT verglichen, sondern immer ueber
# ``freigabe.MARKE_IM_BROKER`` – ein abgetippter Vergleich wird beim naechsten
# Umbenennen still falsch.
#
# ⚠ Gemessen wird der VERGLEICH, nicht das Vorkommen: die erste Fassung zaehlte
# jedes Literal "broker" und meldete ``Path(__file__).parent / "broker"`` – also
# einen Verzeichnisnamen. Ein Muster, das auch fremde Daten trifft, ist keine
# Regel (Register).
abgetippte_vergleiche = []
for k in ast.walk(BAUM):
    if not isinstance(k, ast.Compare):
        continue
    for seite in [k.left, *k.comparators]:
        if isinstance(seite, ast.Constant) and seite.value == f.MARKE_IM_BROKER:
            abgetippte_vergleiche.append(k.lineno)
p("die Marke wird nirgends abgetippt verglichen (nur ueber freigabe.MARKE_IM_BROKER)",
  not abgetippte_vergleiche)
if abgetippte_vergleiche:
    fehler[-1] += f" – Zeilen {abgetippte_vergleiche}"


# ── Teil 2b: die Marke darf nicht als Geheimnis VERPACKT werden ──
# ⚠ Auf DEV gemessen, Stunden nach dem Einbau: ``totp_secret`` ist ein geheimer
# Feldname, also hat der Tresor den Verweis "broker" fuer einen Klartext-
# Altbestand gehalten und verpackt. Es funktionierte (beim Lesen wird entpackt),
# erzeugte aber einen 503-Ausfallpfad, sobald der Hauptschluessel fehlt - und
# genau dieses Startfenster gab es am 2026-10-05 wirklich.
# ⚠ Der Entwicklungsrechner hat KEINEN Hauptschluessel – dort gibt
# ``wert_verschluesseln`` alles unveraendert zurueck, und jede Aussage ueber das
# Verpacken waere trivial wahr (lokal gemessen: hauptfernet() is None). Deshalb
# bekommt der Test einen EIGENEN Wegwerf-Schluessel im Sandkasten; nur so misst
# er die Wirkung auf jedem Rechner und nicht nur auf dem Server.
_schluesseldatei = os.path.join(sandkasten, "geheimnis.key")
try:
    from cryptography.fernet import Fernet as _Fernet
    with open(_schluesseldatei, "wb") as _fh:
        _fh.write(_Fernet.generate_key())
except Exception as e:  # noqa: BLE001
    abbruch(f"Wegwerf-Hauptschluessel nicht erzeugbar (cryptography fehlt?): {e}")
os.environ["JARVIS_GEHEIMNIS_DATEI"] = _schluesseldatei

try:
    from backend import geheimnis_tresor as _tresor
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.geheimnis_tresor nicht importierbar: {e}")
_tresor._zuruecksetzen_fuer_test()     # der Schluessel wird je Prozess gemerkt

p("die Broker-Marke steht in der Klartext-Liste des Tresors",
  f.MARKE_IM_BROKER in getattr(_tresor, "KLARTEXT_WERTE", frozenset()))

# Ein Platzhalter fuer "irgendein Wert, der KEIN Verweis ist". Bewusst lesbar
# und mit Bindestrichen: ein zufaellig aussehender Base32-String (erst
# "ABCDEFGHIJKLMNOP234567") hat Entropie 4,46 und schlaegt in gitleaks als
# ``generic-api-key`` an – die CI war deswegen rot. Ein Eintrag in
# ``.gitleaksignore`` waere der falsche Weg: er haengt an der ZEILENNUMMER und
# meldet sich beim naechsten Einschub erneut (steht so in dessen Kopf).
# Fuer die Pruefung zaehlt nur: nicht leer, kein ``JGS1:``, nicht in
# KLARTEXT_WERTE – dann gilt der Wert als Klartext in einem geheimen Feld.
PROBE_KEIN_VERWEIS = "erfundener-testwert-kein-geheimnis"

# Positivkontrolle: verpackt der Tresor hier ueberhaupt? Ohne sie waere
# "die Marke bleibt Klartext" erfuellt, weil gar nichts verpackt wird.
_probe_geheim = _tresor.wert_verschluesseln(PROBE_KEIN_VERWEIS)
if not _probe_geheim.startswith(_tresor.PRAEFIX_WERT):
    abbruch("wert_verschluesseln verpackt nicht einmal ein echtes Secret – "
            f"Messaufbau kaputt (Hauptschluessel: {_tresor.status()})")
ok += 1
p("ein echtes Secret wird weiterhin verpackt (keine Feldausnahme)",
  _probe_geheim.startswith(_tresor.PRAEFIX_WERT))
p("die Marke bleibt Klartext",
  _tresor.wert_verschluesseln(f.MARKE_IM_BROKER) == f.MARKE_IM_BROKER)
# Und der Rueckweg: ein Klartext-Wert kommt unveraendert zurueck.
p("die Marke uebersteht einen Schreib-/Lesezyklus unveraendert",
  _tresor.wert_entschluesseln(_tresor.wert_verschluesseln(f.MARKE_IM_BROKER))
  == f.MARKE_IM_BROKER)

# Die Marke gilt nicht als "noch zu verpackender Altbestand" – sonst schreibt
# das Backend auth_state.json bei JEDEM Start neu und meldet es im Journal.
_baum_marke = {"users": {"jarvis": {"totp_secret": f.MARKE_IM_BROKER}}}
_baum_echt = {"users": {"jarvis": {"totp_secret": PROBE_KEIN_VERWEIS}}}
# Positivkontrolle zuerst: erkennt die Funktion einen ECHTEN Klartext-Rueckstand?
if not _tresor.klartext_felder(_baum_echt):
    abbruch("klartext_felder findet nicht einmal ein echtes Klartext-Secret – "
            "Messaufbau kaputt")
ok += 1
p("ein echtes Klartext-Secret gilt weiterhin als Altbestand",
  bool(_tresor.klartext_felder(_baum_echt)))
p("die Marke gilt NICHT als zu verpackender Altbestand",
  _tresor.klartext_felder(_baum_marke) == [])


# ──────────────── Teil 3: FAIL-CLOSED der Broker-Abfrage ────────────────
fn_pruefen = next((k for k in ast.walk(BAUM)
                   if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and k.name == "_totp_broker_pruefen"), None)
if fn_pruefen is None:
    abbruch("_totp_broker_pruefen fehlt in main.py")
ok += 1

quelle_fn = ast.get_source_segment(MAIN, fn_pruefen) or ""
# Jede Rueckgabe ausser dem Erfolgsfall muss False sein – ein Fehler darf nie
# "Code war in Ordnung" bedeuten.
rueckgaben = [k.value for k in ast.walk(fn_pruefen) if isinstance(k, ast.Return)]
wahr = [r for r in rueckgaben
        if isinstance(r, ast.Tuple) and r.elts
        and isinstance(r.elts[0], ast.Constant) and r.elts[0].value is True]
p("genau EIN Rueckgabepfad meldet Erfolg", len(wahr) == 1)
p("_totp_broker_pruefen faengt jede Ausnahme ab (unerreichbar ist kein 500)",
  any(isinstance(k, ast.ExceptHandler) for k in ast.walk(fn_pruefen)))
p("eine Antwort ohne 'grund' gilt als unreachable (alter Broker ohne die Op)",
  "unreachable" in quelle_fn)
p("der Erfolg haengt an 'ok is True', nicht an der Wahrheit des Feldes",
  'res.get("ok") is True' in quelle_fn)

# Der Login-Zweig muss bei "unerreichbar" mit 503 antworten und NICHT durchlassen.
fn_login = next((k for k in ast.walk(BAUM)
                 if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and k.name == "_login_ablauf"), None)
if fn_login is None:
    abbruch("_login_ablauf fehlt in main.py")
quelle_login = ast.get_source_segment(MAIN, fn_login) or ""
p("der Login antwortet bei unerreichbarem Broker mit 503",
  "503 if _brk_grund in" in quelle_login)
p("der Login setzt _mit_2fa erst NACH der Broker-Pruefung",
  quelle_login.index("_totp_broker_pruefen") < quelle_login.rindex("_mit_2fa = True"))


# ──────────────── Teil 4: der Notweg existiert ────────────────
ADMIN = (PROJ / "backend" / "broker" / "admin.py").read_text(encoding="utf-8")
try:
    baum_admin = ast.parse(ADMIN)
except SyntaxError as e:
    abbruch(f"backend/broker/admin.py nicht parsebar: {e}")

# ⚠ ZWEI VERFEHLTE FASSUNGEN, beide von der Gegenprobe entlarvt:
#   1. ``'"totp-aus"' in ADMIN`` – der Text steht auch im HILFETEXT, der Waechter
#      las also seine eigene Begruendung (Register).
#   2. Der String in einem ``ast.Compare`` – ``if befehl == "totp-aus":`` bleibt
#      im Rumpf stehen, wenn die aeussere Weiche den Befehl nicht mehr annimmt.
#      Der Zweig ist dann UNERREICHBAR, das Vorkommen aber unveraendert da.
# Gemessen wird deshalb die WIRKUNG: der Dispatch wird wirklich ausgefuehrt und
# darf den Befehl nicht als "Unbekannter Befehl" abweisen.
import contextlib
import io


def _dispatch_kennt(befehl: str) -> bool:
    """Fuehrt ``admin.main([befehl])`` ohne weitere Argumente aus und prueft, dass
    der Befehl ANGENOMMEN wird (Aufruf-Hinweis) statt als unbekannt zu gelten.

    Ohne Argument kehrt jeder dieser Befehle zurueck, BEVOR er eine Datei
    anfasst – die Messung veraendert nichts.
    """
    puffer = io.StringIO()
    echt_geteuid = os.geteuid
    os.geteuid = lambda: 0          # die Konsole verlangt root; wir messen nur den Dispatch
    try:
        with contextlib.redirect_stdout(puffer), contextlib.redirect_stderr(puffer):
            admin_modul.main([befehl])
    except SystemExit:
        pass
    finally:
        os.geteuid = echt_geteuid
    ausgabe = puffer.getvalue()
    return "Unbekannter Befehl" not in ausgabe


try:
    from backend.broker import admin as admin_modul
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.broker.admin nicht importierbar: {e}")

# Positivkontrolle BEIDER Richtungen: der Dispatch muss einen Bestandsbefehl
# kennen UND einen erfundenen ablehnen. Ohne die zweite waere jede Aussage
# unten trivial wahr (eine Messung, die immer "kennt" sagt, misst nichts).
if not _dispatch_kennt("erlauben"):
    abbruch("der Dispatch kennt nicht einmal 'erlauben' – Messaufbau kaputt")
if _dispatch_kennt("gibtesnicht-xyz"):
    abbruch("der Dispatch haelt einen erfundenen Befehl fuer bekannt – "
            "die Messung kann einen entfernten Befehl nicht sehen")
ok += 2

p("die root-Konsole kann 2FA abschalten (Notweg gegen das Aussperren)",
  _dispatch_kennt("totp-aus"))
p("die root-Konsole kann ein vorhandenes Geheimnis uebernehmen",
  _dispatch_kennt("totp-uebernehmen"))
# Zusaetzlich, und bewusst getrennt: der Notweg muss auch IM HILFETEXT stehen –
# ein Befehl, den niemand kennt, hilft im Ernstfall nicht.
p("der Notweg steht im Hilfetext", "totp-aus <konto>" in (ast.get_docstring(baum_admin) or ""))
fn_schreiben = next((k for k in ast.walk(baum_admin)
                     if isinstance(k, ast.FunctionDef) and k.name == "_auth_state_schreiben"), None)
p("_auth_state_schreiben existiert", fn_schreiben is not None)
if fn_schreiben is not None:
    q = ast.get_source_segment(ADMIN, fn_schreiben) or ""
    # Register: chmod MUSS nach chown kommen – ein chown loescht setgid.
    p("der Eigentuemer von auth_state.json bleibt erhalten (sonst kann das Backend "
      "die Datei nicht mehr schreiben)", "os.chown" in q)
    p("chmod kommt NACH chown", q.index("os.chown") < q.index("os.chmod"))


print(f"\n{ok} ok, {len(fehler)} Fehler")
for z in fehler:
    print(f"  FAIL: {z}")
sys.exit(1 if fehler else 0)

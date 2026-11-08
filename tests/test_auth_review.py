#!/usr/bin/env python3
"""Waechter: Anmelde-Befunde aus dem Code-Review vom 2026-10-18.

  [1] ``_gruppe_passt`` AUSGEFUEHRT (per AST geschnitten): genauer DN passt,
      Schreibweise egal; ein voller DN in einer ANDEREN OU passt nur noch mit
      in der Vorgabe NICHT (mit Meldung), nur mit ``JARVIS_AD_GRUPPE_STRENG=0``
      wieder (Notschalter, ebenfalls mit Meldung); ein blosser Name
      trifft wie bisher ueber den CN; beide Aufrufer benutzen DIESE Regel.
  [2] REGEL (AST): jede Anmelde-Abhaengigkeit ``require_*``, die – selbst oder
      ueber Helfer – Anmeldedaten aufloest (Token, Abruf- oder
      Delegations-Schluessel), weist gesperrte Konten ab
      (``security_guard.is_blocked``) und prueft die Anmeldeberechtigung;
      ein Delegations-Schluessel endet mit der Abmelde-Epoche (A5, 2026-11-05).
  [3] ``_user_is_admin`` und die Revalidierung kennen keinen Namens-Freibrief
      fuer ``root`` mehr (ein gleichnamiges AD-Konto war sonst Admin).
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


Q = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
B = ast.parse(Q)
FN = {n.name: n for n in B.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for n in ("_dn_norm", "_gruppe_passt", "_gruppen_passen", "_member_of_any_group",
          "_user_is_admin", "require_local_auth", "require_auth"):
    if n not in FN:
        abbruch("%s fehlt in main.py" % n)

print("\n[1] _gruppe_passt")
MELD = []
ns = {"os": os, "_CN_TREFFER_GEMELDET": set(), "print": lambda *a, **k: MELD.append(" ".join(map(str, a)))}
exec(compile(ast.fix_missing_locations(ast.Module(body=[FN["_dn_norm"], FN["_gruppe_passt"]], type_ignores=[])),
             "main", "exec"), ns)
gp = ns["_gruppe_passt"]
SOLL = "CN=Jarvis-Admins,OU=IT,DC=firma,DC=local"
check("(Positivkontrolle) genauer DN passt", gp("CN=Jarvis-Admins,OU=IT,DC=firma,DC=local", SOLL))
check("Schreibweise und Leerraum egal", gp("cn=jarvis-admins, ou=it, dc=FIRMA, dc=local", SOLL))
check("andere Gruppe passt nicht", not gp("CN=Jarvis-Nutzer,OU=IT,DC=firma,DC=local", SOLL))
check("Praefix-Falle: Jarvis-Admins2 passt nicht", not gp("CN=Jarvis-Admins2,OU=IT,DC=firma,DC=local", SOLL))
os.environ.pop("JARVIS_AD_GRUPPE_STRENG", None)
MELD.clear()
r = gp("CN=Jarvis-Admins,OU=Fremd,DC=firma,DC=local", SOLL)
check("andere OU (Vorgabe streng): zaehlt NICHT, aber MIT Meldung", r is False and any("andere OU" in m
      for m in MELD), str(MELD))
os.environ["JARVIS_AD_GRUPPE_STRENG"] = "1"
check("andere OU mit JARVIS_AD_GRUPPE_STRENG=1: zaehlt NICHT",
      gp("CN=Jarvis-Admins,OU=Fremd,DC=firma,DC=local", SOLL) is False)
os.environ["JARVIS_AD_GRUPPE_STRENG"] = "0"
_ns_neu = dict(ns, _CN_TREFFER_GEMELDET=set())
MELD.clear()
exec(compile(ast.fix_missing_locations(ast.Module(body=[FN["_dn_norm"], FN["_gruppe_passt"]], type_ignores=[])),
             "main", "exec"), _ns_neu)
check("andere OU mit Notschalter =0: zaehlt wieder, MIT Meldung",
      _ns_neu["_gruppe_passt"]("CN=Jarvis-Admins,OU=Fremd,DC=firma,DC=local", SOLL) is True and MELD, str(MELD))
check("Notschalter laesst eine FREMDE Gruppe trotzdem nicht durch",
      _ns_neu["_gruppe_passt"]("CN=Jarvis-Nutzer,OU=Fremd,DC=firma,DC=local", SOLL) is False)
os.environ.pop("JARVIS_AD_GRUPPE_STRENG", None)
check("blosser Name: trifft ueber den CN (wie bisher gewollt)",
      gp("CN=Jarvis-Admins,OU=Irgendwo,DC=firma,DC=local", "Jarvis-Admins") and gp("CN=Jarvis-Admins,OU=X,DC=firma,DC=local", "cn=jarvis-admins"))
for n in ("_gruppen_passen", "_member_of_any_group"):
    rufe = [c for c in ast.walk(FN[n]) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_gruppe_passt"]
    alt = [c for c in ast.walk(FN[n]) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "startswith"]
    check("%s benutzt _gruppe_passt (kein eigener startswith-Vergleich)" % n, rufe and not alt)

print("\n[2] Sperre an jeder Anmeldedaten-pruefenden Abhaengigkeit")
# Bis 2026-11-05 zaehlte hier nur, wer verify_token SELBST ruft. Der
# Delegations-Schluessel (require_claudesub_key) loest seine Identitaet ueber
# einen HELFER und einen ANDEREN Aufloeser auf (benutzer_zu_schluessel) – er
# fiel durch die Regel und ueberlebte Kontosperre, Entzug und Zwangsabmeldung
# (Befund A5). Jetzt: jeder Aufloeser von Anmeldedaten, auch ueber Helfer bis
# Tiefe 3. Die Sperre muss in der Abhaengigkeit selbst stehen ODER in JEDER
# Funktion, die dort Anmeldedaten aufloest.
AUFLOESER = {"verify_token", "benutzer_zu_schluessel", "_query_benutzer", "pruefen_voll"}


def _direkt(fn):
    namen = set()
    for c in ast.walk(fn):
        if isinstance(c, ast.Call):
            if isinstance(c.func, ast.Name):
                namen.add(c.func.id)
            elif isinstance(c.func, ast.Attribute):
                namen.add(c.func.attr)
    return namen


DIREKT = {n: _direkt(f) for n, f in FN.items()}


def _huelle(name, tiefe=3):
    gesehen, rand = {name}, {name}
    for _ in range(tiefe):
        rand = {c for n in rand for c in DIREKT[n]
                if c in FN and c not in gesehen and c not in AUFLOESER}
        gesehen |= rand
    return gesehen


geprueft = 0
ueber_helfer = []
for name in sorted(FN):
    if not name.startswith("require_"):
        continue
    orte = sorted(f for f in _huelle(name) if DIREKT[f] & AUFLOESER)
    if not orte:
        continue
    geprueft += 1
    if orte != [name]:
        ueber_helfer.append(name)
    for pflicht, was in (("is_blocked", "weist gesperrte Konten ab"),
                         ("_login_still_allowed", "prueft die Anmeldeberechtigung")):
        ok = pflicht in DIREKT[name] or all(pflicht in DIREKT[f] for f in orte)
        check("%s %s (Aufloesung in %s)" % (name, was, ", ".join(orte)), ok)
    # Ein Aufloeser ohne eingebauten Widerruf (verify_token prueft die Epoche
    # selbst) muss die Widerrufs-Epoche an der Fundstelle pruefen.
    for f in orte:
        if "benutzer_zu_schluessel" in DIREKT[f]:
            check("%s: Schluessel endet mit der Abmelde-Epoche (_epoche_widerrufen)" % f,
                  "_epoche_widerrufen" in DIREKT[f])
check("(Positivkontrolle) Anmeldedaten-pruefende Abhaengigkeiten gefunden (%d)" % geprueft,
      geprueft >= 4)
check("(Positivkontrolle) mindestens eine loest ueber einen Helfer auf (%s)"
      % ", ".join(ueber_helfer), bool(ueber_helfer))

print("\n[3] kein Namens-Freibrief fuer root")
for n in ("_user_is_admin",):
    konst = [c.value for c in ast.walk(FN[n]) if isinstance(c, ast.Constant) and c.value == "root"]
    check("%s kennt 'root' nicht als Admin-Namen" % n, not konst)
kandidaten = [n for n in FN.values() if any(isinstance(c, ast.Constant) and c.value == "root" for c in ast.walk(n))
              and any(isinstance(c, ast.Name) and c.id == "ALLOWED_USERS" for c in ast.walk(n))]
check("keine Funktion stellt 'root' neben ALLOWED_USERS", not kandidaten, str([k.name for k in kandidaten]))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)

#!/usr/bin/env python3
"""Waechter: Anmeldung fuer die Sitzung bei Jira und Confluence (2026-11-15).

Vorgabe des Betreibers: ist "Persoenliche Zugaenge erlauben" AUS, darf kein
persoenlicher Token auf der Platte liegen – angemeldet wird fuer die Sitzung
(bei der Anmeldung an Jarvis oder im Bereich), der Token liegt nur im
Arbeitsspeicher, und es gibt ein Abmelden nach dem SAP-Vorbild. Ohne Anmeldung
gilt der gemeinsame Zugang ("PAT, sonst gemeinsam").

Gemessen an den ECHTEN Modulen im Sandkasten (Exit 2, wenn er nicht greift):

1. SitzungsSpeicher: setzen, lesen, Ablauf, beenden, keine Token in ``info``.
2. Jira und Confluence je:
   * Anmelden wird VOR dem Merken geprueft (abgelehnter Token = nicht angemeldet),
   * im Sitzungsbetrieb gilt der Sitzungs-Token (persoenlich), sonst der
     gemeinsame Zugang MIT Hinweis,
   * nach ``sitzung_beenden`` wieder der gemeinsame Zugang,
   * bei ERLAUBTEN persoenlichen Zugaengen gibt es den Weg nicht (abgewiesen,
     und ein Rest im Speicher greift nicht),
   * nichts davon erreicht die Kontendatei,
   * Kanal-Kennungen (``wa:…``) werden nie persoenlich.
3. main.py (am Syntaxbaum): Endpunkte und Schranken, Jarvis-Abmeldung beendet
   beide Sitzungen, der Anmeldeschritt-Endpunkt haengt an ``require_auth``.

Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.
    python3 tests/test_zugang_sitzung.py
"""
import ast
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(os.environ.get("ZS_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if not isinstance(cond, bool):
        print(f"ABBRUCH: check() erwartet eine Bedingung, bekam {type(cond).__name__} "
              f"({label!r}) – vertauschte Argumente?")
        sys.exit(2)
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n═══ {t}")


if "backend.config" not in sys.modules:
    _cfg = types.ModuleType("backend.config")

    class _C:
        def get_skill_states(self):
            return {}

        def get_setting(self, k, d=None):
            return d

    _cfg.config = _C()
    sys.modules["backend.config"] = _cfg

try:
    import cryptography  # noqa: F401
    from backend import confluence_accounts as ca  # noqa: E402
    from backend import jira_accounts as ja  # noqa: E402
    from backend import sitzungs_token as st  # noqa: E402
    import backend.confluence_client as _cc  # noqa: E402
    import backend.jira_client as _jc  # noqa: E402
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Module nicht importierbar: {e}")
    sys.exit(2)

# ── Sandkasten ───────────────────────────────────────────────────────────────
_tmp = tempfile.mkdtemp(prefix="zugang-sitzung-test-")
for mod, name in ((ca, "confluence"), (ja, "jira")):
    mod.DATA_DIR = Path(_tmp)
    mod.KONTEN_DATEI = Path(_tmp) / f"{name}_accounts.json"
    mod.SCHLUESSEL_DATEI = Path(_tmp) / f".{name}key"
    for _n in ("KONTEN_DATEI", "SCHLUESSEL_DATEI", "DATA_DIR"):
        if not str(getattr(mod, _n)).startswith(_tmp):
            print(f"ABBRUCH: Sandkasten greift nicht – {name}.{_n}")
            sys.exit(2)

CFG = {
    "jira": {"base_url": "https://jira.beispiel.de", "api_token": "SAMMEL"},
    "confluence": {"base_url": "https://wiki.beispiel.de", "api_token": "SAMMEL"},
}
ja.get_jira_config = lambda: CFG["jira"]
ca.get_confluence_config = lambda: CFG["confluence"]
_jc.get_jira_config = lambda: CFG["jira"]
_cc.get_confluence_config = lambda: CFG["confluence"]

# Gegenstelle als Attrappe mit der ECHTEN Methodensignatur: "GUT" wird
# angenommen, alles andere mit dem echten Fehlertyp abgelehnt. Gezaehlt wird,
# wie oft gefragt wurde – "vor dem Merken geprueft" ist sonst nicht messbar.
AUFRUFE = {"jira": 0, "confluence": 0}


def _jira_myself(self):
    AUFRUFE["jira"] += 1
    if self.token == "GUT":
        return {"displayName": "Anna Beispiel", "name": "anna.beispiel"}
    raise _jc.JiraError(401, "Unauthorized")


def _cf_current(self):
    AUFRUFE["confluence"] += 1
    if self.token == "GUT":
        return {"displayName": "Anna Beispiel", "username": "anna.beispiel"}
    raise _cc.ConfluenceError(401, "Unauthorized")


_jc.JiraClient.myself = _jira_myself
_cc.ConfluenceClient.current_user = _cf_current

USER = "anna.beispiel"
MODUL = {"jira": ja, "confluence": ca}
FEHLER = {"jira": ja.JiraKontoFehler, "confluence": ca.ConfluenceKontoFehler}


def schalter(name, erlaubt):
    CFG[name]["persoenliche_zugaenge"] = bool(erlaubt)


def frisch():
    for m in MODUL.values():
        if m.KONTEN_DATEI.exists():
            m.KONTEN_DATEI.unlink()
        m._SITZUNG.leeren()


def wirft(fn, typ):
    try:
        fn()
    except typ as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return f"FALSCHER TYP {type(e).__name__}: {e}"
    return None


# Positivkontrolle: die Attrappe greift (sonst waeren alle Pruefungen auf
# "angemeldet" eine Aussage ueber das Netz statt ueber den Code).
try:
    _probe = _jc.JiraClient({"base_url": "https://x", "api_token": "GUT"}).myself()
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Attrappe greift nicht: {e}")
    sys.exit(2)
if _probe.get("name") != "anna.beispiel":
    print("ABBRUCH: Attrappe liefert nicht die erwartete Form")
    sys.exit(2)

# ═════════════════════════════════════════════════════════════════════════════
section("1) SitzungsSpeicher")
s = st.SitzungsSpeicher(laufzeit_s=3600)
bis = s.setzen("u", "GEHEIM", anzeigename="U", konto="u1")
check(s.token("u") == "GEHEIM", "Token lesbar nach dem Setzen")
check(abs(bis - (time.time() + 3600)) < 5, "Ablauf = jetzt + Laufzeit", str(bis))
inf = s.info("u")
check(inf["angemeldet"] is True and inf["sitzung_bis"] == bis, "info meldet angemeldet + bis")
check("GEHEIM" not in repr(inf), "info enthaelt den Token NICHT", repr(inf))
s._daten["u"]["bis"] = time.time() - 1
check(s.token("u") == "" and s.info("u")["angemeldet"] is False, "abgelaufen = nicht angemeldet")
check("u" not in s._daten, "abgelaufener Eintrag wird verworfen")
s.setzen("u", "X")
check(s.beenden("u") is True and s.token("u") == "", "beenden verwirft den Token")
check(s.beenden("u") is False, "zweites Beenden meldet nichts beendet")
check(wirft(lambda: s.setzen("u", ""), ValueError) is not None, "leerer Token wird abgewiesen")
check(st.LAUFZEIT_S == 12 * 3600, "Laufzeit wie SAP/VEMAS: 12 Stunden", str(st.LAUFZEIT_S))

# ═════════════════════════════════════════════════════════════════════════════
for name in ("jira", "confluence"):
    m, F = MODUL[name], FEHLER[name]
    section(f"2) {name}: Anmeldung fuer die Sitzung")
    frisch()
    schalter(name, False)
    check(m.sitzungs_modus() is True, "Schalter aus = Sitzungsbetrieb")

    r = m.aufloesen(USER)
    check(r["quelle"] == m.QUELLE_SAMMEL and r["client"].token == "SAMMEL",
          "ohne Anmeldung: gemeinsamer Zugang", r["quelle"])
    check(bool(r["hinweis"]), "… mit Hinweis", repr(r["hinweis"]))

    vor = AUFRUFE[name]
    grund = wirft(lambda: m.sitzung_anmelden(USER, "FALSCH"), F)
    check(grund is not None and "FALSCHER TYP" not in (grund or ""),
          "abgelehnter Token: Fehler mit Grund", str(grund))
    check(AUFRUFE[name] == vor + 1, "… die Gegenstelle WURDE gefragt")
    check(m.zugang_info(USER)["angemeldet"] is False, "… und es ist NICHT angemeldet")
    check(m.aufloesen(USER)["quelle"] == m.QUELLE_SAMMEL, "… es gilt weiter der gemeinsame Zugang")

    check(wirft(lambda: m.sitzung_anmelden(USER, "   "), F) is not None, "leerer Token: Fehler")
    info = m.sitzung_anmelden(USER, "GUT")
    check(info.get("angemeldet") is True, "gueltiger Token: angemeldet")
    check(info.get("sitzung_anzeigename") == "Anna Beispiel", "… Anzeigename aus der Gegenstelle")
    check("GUT" not in repr(info), "zugang_info enthaelt den Token NICHT")
    r = m.aufloesen(USER)
    check(r["quelle"] == m.QUELLE_PERSOENLICH and r["client"].token == "GUT",
          "angemeldet: der Sitzungs-Token gilt (persoenlich)", r["quelle"])
    check(r["hinweis"] == "", "… ohne Hinweis")
    if name == "jira":
        check(r["client"].schreiben is True, "Jira: der persoenliche Client darf schreiben")
        with_ng = ja.nur_gemeinsam.set(True)
        try:
            check(ja.aufloesen(USER)["client"].token == "SAMMEL",
                  "Jira-Erweiterung (nur_gemeinsam) bleibt beim gemeinsamen Zugang")
        finally:
            ja.nur_gemeinsam.reset(with_ng)
    check(m.aufloesen("anderer.benutzer")["quelle"] == m.QUELLE_SAMMEL,
          "ein anderer Benutzer bleibt beim gemeinsamen Zugang")
    check(not m.KONTEN_DATEI.exists() or "GUT" not in m.KONTEN_DATEI.read_text(),
          "der Token erreicht die Kontendatei NICHT")

    kanal = f"wa:{USER}"
    check(wirft(lambda: m.sitzung_anmelden(kanal, "GUT"), F) is not None,
          "Kanal-Kennung kann sich nicht anmelden")
    m._SITZUNG.setzen(m.norm_user(kanal), "GUT")
    check(m.aufloesen(kanal)["quelle"] == m.QUELLE_SAMMEL,
          "Kanal-Kennung wird nie persoenlich (auch mit Eintrag im Speicher)")

    check(m.sitzung_beenden(USER) is True, "Abmelden beendet die Sitzung")
    check(m.aufloesen(USER)["quelle"] == m.QUELLE_SAMMEL, "nach dem Abmelden: gemeinsamer Zugang")

    section(f"2b) {name}: bei ERLAUBTEN persoenlichen Zugaengen gibt es den Weg nicht")
    frisch()
    schalter(name, True)
    check(m.sitzungs_modus() is False, "Schalter an = kein Sitzungsbetrieb")
    check(wirft(lambda: m.sitzung_anmelden(USER, "GUT"), F) is not None,
          "Anmelden fuer die Sitzung wird abgewiesen")
    m._SITZUNG.setzen(m.norm_user(USER), "GUT")
    r = m.aufloesen(USER)
    check(r["quelle"] == m.QUELLE_SAMMEL and r["client"].token == "SAMMEL",
          "ein Rest im Speicher greift NICHT (nur der gespeicherte Token zaehlt)", r["quelle"])
    check(m.zugang_info(USER).get("sitzungs_modus") is False, "zugang_info meldet sitzungs_modus=False")
    frisch()

# ═════════════════════════════════════════════════════════════════════════════
section("3) main.py am Syntaxbaum")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(MAIN)


def _fn(name):
    return next((n for n in ast.walk(baum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == name), None)


def _route(fn):
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args \
                and isinstance(d.args[0], ast.Constant):
            return d.func.attr, d.args[0].value
    return None, None


def _deps(fn):
    out = []
    for dflt in fn.args.defaults + fn.args.kw_defaults:
        if isinstance(dflt, ast.Call) and getattr(dflt.func, "id", "") == "Depends" and dflt.args:
            out.append(getattr(dflt.args[0], "id", ""))
    return out


ERWARTET = {
    "jira_account_anmelden": ("post", "/api/jira/account/sitzung", "require_jira_assist_access"),
    "jira_account_abmelden": ("delete", "/api/jira/account/sitzung", "require_jira_assist_access"),
    "confluence_account_anmelden": ("post", "/api/confluence/account/sitzung",
                                    "require_confluence_account_access"),
    "confluence_account_abmelden": ("delete", "/api/confluence/account/sitzung",
                                    "require_confluence_account_access"),
    "zugaenge_anmeldung": ("get", "/api/zugaenge/anmeldung", "require_auth"),
}
for fname, (meth, pfad, dep) in ERWARTET.items():
    f = _fn(fname)
    if f is None:
        check(False, f"{fname} existiert")
        continue
    check(_route(f) == (meth, pfad), f"{fname}: {meth.upper()} {pfad}", str(_route(f)))
    check(_deps(f) == [dep], f"{fname}: Schranke {dep}", str(_deps(f)))


def _ruft(fn, attr):
    """Direkter Aufruf ``x.attr(...)`` ODER ``asyncio.to_thread(x.attr, ...)`` –
    der Anmelde-Endpunkt reicht die Funktion an den Thread weiter."""
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr == attr:
            return True
        if n.func.attr == "to_thread" and n.args and isinstance(n.args[0], ast.Attribute) \
                and n.args[0].attr == attr:
            return True
    return False


for fname, ziel in (("jira_account_anmelden", "sitzung_anmelden"),
                    ("confluence_account_anmelden", "sitzung_anmelden"),
                    ("jira_account_abmelden", "sitzung_beenden"),
                    ("confluence_account_abmelden", "sitzung_beenden")):
    f = _fn(fname)
    check(f is not None and _ruft(f, ziel), f"{fname} ruft {ziel}")

# Jarvis-Abmeldung beendet ALLE vier Sitzungen (SAP/VEMAS gab es schon).
lo = next((n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)
           and _route(n) == ("post", "/api/logout")), None)
if lo is None:
    print("ABBRUCH: /api/logout nicht gefunden")
    sys.exit(2)
importe = {a.asname or a.name for n in ast.walk(lo) if isinstance(n, ast.ImportFrom)
           for a in n.names}
beendet = {n.func.value.id for n in ast.walk(lo) if isinstance(n, ast.Call)
           and isinstance(n.func, ast.Attribute) and n.func.attr == "sitzung_beenden"
           and isinstance(n.func.value, ast.Name)}
for modul in ("jira_accounts", "confluence_accounts", "sap_accounts", "vemas_accounts"):
    alias = {a.asname for n in ast.walk(lo) if isinstance(n, ast.ImportFrom)
             for a in n.names if a.name == modul}
    check(bool(alias & beendet), f"Jarvis-Abmeldung beendet die Sitzung von {modul}",
          f"alias={alias} beendet={beendet}")

# Der Anmeldeschritt-Endpunkt gibt nie ein Geheimnis heraus: die Hilfsfunktion
# baut ihre Eintraege nur aus diesen Schluesseln.
hf = _fn("_zugang_anmeldungen")
check(hf is not None, "_zugang_anmeldungen existiert")
if hf is not None:
    schluessel = {k.value for n in ast.walk(hf) if isinstance(n, ast.Dict)
                  for k in n.keys if isinstance(k, ast.Constant)}
    check(schluessel <= {"system", "art", "feld", "benutzer", "benutzer_feld"},
          "Eintraege tragen nur Feldnamen und Benutzer", str(schluessel))
    # fail-closed je System: jede Schleife hat ihr eigenes try/except
    schleifen = [n for n in hf.body if isinstance(n, ast.For)]
    check(len(schleifen) == 2 and all(any(isinstance(x, ast.Try) for x in s.body)
                                      for s in schleifen),
          "je System eigenes try (ein Fehler laesst nur dieses System weg)")
    # Testphase: vor JEDER Systemschleife steht die Freigabe-Schranke mit
    # leerer Rueckgabe – sonst sieht jeder Benutzer den zweiten Schritt.
    erste_schleife = next((i for i, n in enumerate(hf.body) if isinstance(n, ast.For)),
                          len(hf.body))
    def _ist_schranke(n):
        if not (isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp)
                and isinstance(n.test.op, ast.Not) and isinstance(n.test.operand, ast.Call)):
            return False
        f = n.test.operand.func
        return (isinstance(f, ast.Name) and f.id == "_user_may_use_zugang_anmeldung"
                and len(n.body) == 1 and isinstance(n.body[0], ast.Return))
    check(any(_ist_schranke(n) for n in hf.body[:erste_schleife]),
          "Freigabe-Schranke steht vor den Systemen (Testphase)")

# Die Schranke selbst: leer = niemand, nur gelistete Benutzer
pf = _fn("_user_may_use_zugang_anmeldung")
check(pf is not None, "_user_may_use_zugang_anmeldung existiert")
if pf is not None:
    gelesen = {n.args[0].value for n in ast.walk(pf) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == "get_setting"
               and n.args and isinstance(n.args[0], ast.Constant)}
    check(gelesen == {"zugang_anmeldung_users"}, "liest genau zugang_anmeldung_users",
          str(gelesen))
    ns = {"config": type("C", (), {"get_setting": staticmethod(lambda k, d=None: _ZA[0])}),
          "_norm_login": lambda x: x.strip().lower().split("\\")[-1]}
    exec(compile(ast.Module(body=[pf], type_ignores=[]), "pf", "exec"), ns)
    _ZA = [""]
    check(ns[pf.name]("anna.beispiel") is False, "leere Liste = niemand")
    _ZA = ["anna.beispiel, erika.muster"]
    check(ns[pf.name]("Anna.Beispiel") is True, "gelisteter Benutzer darf")
    check(ns[pf.name]("m.mustermann") is False, "nicht gelisteter Benutzer darf nicht")
    check(ns[pf.name]("") is False, "leerer Benutzer darf nicht")

print(f"\n{'═' * 70}\nERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)

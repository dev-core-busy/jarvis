#!/usr/bin/env python3
"""Waechter: Schutz gegen Password Spraying (2026-10-15).

Spraying = ein Kennwort fuer viele Konten, verteilt ueber viele Adressen. Die
Zaehler je Konto und je IP (BSI M3) greifen dabei nicht. Gemessen wird die
WIRKUNG der vier Bausteine:

  [A] ``backend/anmelde_schutz.py`` direkt (Ablage im Wegwerf-Verzeichnis):
      IPv6 als /64, Kontoschwelle aus der Domaenen-Richtlinie (als EIGENSCHAFT:
      Jarvis sperrt vor der Domaene), Erkennung ueber alle Konten, Meldung genau
      einmal, Persistenz, Bremse und Mindestdauer per Zeitmessung.
  [B] ``main._ad_vorab_freigabe`` (per AST, Verzeichnis-Attrappe in echter Form):
      jeder Zweig – und "nein" NIE aus einem Fehler, sonst sperrte ein kaputtes
      Dienstkonto alle Gruppenmitglieder aus; Gedaechtnis fuer den Dienst-Bind.
  [C] ``main.authenticate_linux_user``: bei "nein" geht KEIN Kennwort zum DC.
  [D] ``main._login_ablauf``/``login`` am Syntaxbaum: keine eigene Antwort fuer
      "nicht freigegeben" (das Orakel), jede 401 gleich, Bremse und Mindestdauer
      verdrahtet; Vorab- und Nachpruefung rufen DIESELBE Gruppenfunktion.
  [E] ``main._anmelde_schwellen_aktualisieren``: Richtlinie -> gesetzte Schwelle.

``backend.config`` nur als Stub. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import os
import ast
import asyncio
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def check(name: str, bed: bool) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


EINST: dict = {}
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: EINST.get(k, d),
                                    save_setting=lambda k, v: EINST.__setitem__(k, v))
sys.modules["backend.config"] = _cfg

from backend import anmelde_schutz as AS  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="spruehen_"))
AS.STORE_PATH = TMP / "anmelde_schutz.json"
if not str(AS.STORE_PATH).startswith(str(TMP)):
    abbruch("Ablage nicht im Wegwerf-Verzeichnis")


def neu():
    AS._zuruecksetzen_fuer_test()
    AS.STORE_PATH.unlink(missing_ok=True)
    AS._zuruecksetzen_fuer_test()


try:
    # ── [A] Modul ────────────────────────────────────────────────────────────
    print("\n[A] anmelde_schutz")
    neu()
    k = AS.ip_schluessel
    check("IPv6: zwei Adressen desselben /64 -> derselbe Schluessel",
          k("2001:db8:1:2::1") == k("2001:db8:1:2:ffff::9"))
    check("IPv6: anderes /64 -> anderer Schluessel", k("2001:db8:1:2::1") != k("2001:db8:1:3::1"))
    check("IPv4 bleibt exakt (kein /24 – sonst traefe es das halbe Firmennetz)",
          k("192.0.2.1") != k("192.0.2.2"))
    check("IPv4-in-IPv6 zaehlt als die IPv4-Adresse", k("::ffff:192.0.2.1") == "192.0.2.1")
    check("Unbekanntes bleibt unveraendert", k("unknown") == "unknown")

    T0 = 1_800_000_000.0
    for i in range(AS.IP_MAX):
        AS.fehlversuch("2001:db8:7:7::%x" % (i + 1), "", jetzt=T0 + i)
    check("IP-Grenze greift ueber wechselnde Adressen EINES /64",
          AS.ip_wartezeit("2001:db8:7:7::abcd", jetzt=T0 + AS.IP_MAX) > 0)
    check("…ein anderes /64 bleibt frei", AS.ip_wartezeit("2001:db8:7:8::1", jetzt=T0 + AS.IP_MAX) == 0)

    # Schwelle aus der Richtlinie – als EIGENSCHAFT fuer jede Domaenen-Schwelle
    for schwelle in range(2, 11):
        km, fen, q = AS.schwellen_aus_richtlinie({"schwelle": schwelle, "fenster_s": 1800}, True)
        if not (km < schwelle and q == "domaene" and fen >= 1800):
            check("Domaene sperrt nach %d: Jarvis sperrt vorher (%d)" % (schwelle, km), False)
            break
    else:
        check("fuer jede Domaenen-Schwelle 2..10 sperrt Jarvis VORHER, Fenster >= Domaene", True)
    check("Domaene mit kurzem Fenster: Jarvis-Fenster nie unter der Vorgabe",
          AS.schwellen_aus_richtlinie({"schwelle": 3, "fenster_s": 60}, True)[1] == AS.KONTO_FENSTER_VORGABE_S)
    check("Richtlinie nicht lesbar: Rueckfallschwelle 2",
          AS.schwellen_aus_richtlinie(None, True)[:1] == (AS.KONTO_MAX_OHNE_RICHTLINIE,)
          and AS.KONTO_MAX_OHNE_RICHTLINIE < 3)
    check("ohne Domaene: Vorgabe", AS.schwellen_aus_richtlinie(None, False)[0] == AS.KONTO_MAX_VORGABE)
    check("Domaene sperrt nie (Schwelle 0): Vorgabe",
          AS.schwellen_aus_richtlinie({"schwelle": 0, "fenster_s": 0}, True)[0] == AS.KONTO_MAX_VORGABE)

    neu()
    AS.schwellen_setzen(2, 1800, "domaene")
    AS.fehlversuch("192.0.2.10", "eva", jetzt=T0)
    check("gesetzte Schwelle 2: nach 1 Fehlversuch noch frei", AS.konto_wartezeit("eva", jetzt=T0 + 1) == 0)
    check("gesetzte Schwelle 2: der 2. sperrt", AS.fehlversuch("192.0.2.11", "eva", jetzt=T0 + 2))
    check("Schwelle wirkt im Modul (KONTO_MAX liest den gesetzten Wert)", AS.KONTO_MAX == 2)
    AS.schwellen_setzen(0, 10, "x")
    check("Untergrenzen: mindestens 1 Versuch, Fenster nie unter der Vorgabe",
          AS.KONTO_MAX == 1 and AS.KONTO_FENSTER_S == AS.KONTO_FENSTER_VORGABE_S)

    # Spruehen
    neu()
    for i in range(AS.SPRUEH_KONTEN - 1):
        AS.fehlversuch("198.51.100.%d" % i, "konto%d" % i, jetzt=T0 + i)
    check("%d verschiedene Konten: noch kein Spruehangriff" % (AS.SPRUEH_KONTEN - 1),
          not AS.spruehlage(jetzt=T0 + 20)["aktiv"])
    for i in range(30):
        AS.fehlversuch("198.51.100.200", "konto0", jetzt=T0 + 20 + i)
    check("viele Fehlversuche fuer EIN Konto sind kein Spruehangriff",
          not AS.spruehlage(jetzt=T0 + 60)["aktiv"])
    AS.fehlversuch("203.0.113.9", "neuer.name", jetzt=T0 + 61)
    lage = AS.spruehlage(jetzt=T0 + 62)
    check("%d. verschiedenes Konto: Spruehangriff erkannt" % AS.SPRUEH_KONTEN,
          lage["aktiv"] and lage["konten"] >= AS.SPRUEH_KONTEN)
    m1 = AS.sprueh_neu_melden(jetzt=T0 + 62)
    m2 = AS.sprueh_neu_melden(jetzt=T0 + 63)
    check("Meldung genau EINMAL je Angriff", m1 is not None and m2 is None)
    AS._zuruecksetzen_fuer_test()                     # "Neustart": nur Speicher weg
    check("Spruehlage ueberlebt einen Neustart (Platte)", AS.spruehlage(jetzt=T0 + 64)["aktiv"]
          and AS.sprueh_neu_melden(jetzt=T0 + 64) is None)
    check("nach SPRUEH_DAUER_S ohne Nachschub vorbei",
          not AS.spruehlage(jetzt=T0 + 61 + AS.SPRUEH_DAUER_S + 1)["aktiv"])
    neu()
    for i in range(AS.SPRUEH_KONTEN):
        AS.fehlversuch("198.51.100.%d" % i, "k%d" % i, jetzt=T0 + i * (AS.SPRUEH_FENSTER_S / 2))
    check("verteilt ueber mehr als das Fenster: kein Spruehangriff",
          not AS.spruehlage(jetzt=T0 + AS.SPRUEH_KONTEN * AS.SPRUEH_FENSTER_S / 2)["aktiv"])

    # Bremse und Mindestdauer – gemessen, mit kleinen Werten
    neu()
    AS.SPRUEH_ABSTAND_S = 0.2
    AS.FEHL_MINDESTDAUER_S, AS.FEHL_STREUUNG_S = 0.3, 0.0

    async def _drei_mal():
        t = time.monotonic()
        for _ in range(3):
            await AS.bremse()
        return time.monotonic() - t

    check("ohne Spruehangriff bremst nichts", asyncio.run(_drei_mal()) < 0.1)
    for i in range(AS.SPRUEH_KONTEN):
        AS.fehlversuch("198.51.100.%d" % i, "b%d" % i)
    d = asyncio.run(_drei_mal())
    check("waehrend eines Spruehangriffs: 3 Anmeldungen brauchen >= 2 Abstaende (%.2f s)" % d,
          d >= 2 * AS.SPRUEH_ABSTAND_S - 0.02)
    check("Bremse funktioniert auch in einer NEUEN Ereignisschleife", asyncio.run(_drei_mal()) > 0)

    async def _dauer(start_offset):
        t = time.monotonic()
        await AS.angleichen(AS.uhr() - start_offset)
        return time.monotonic() - t

    check("Fehlantwort wird auf die Mindestdauer gestreckt",
          asyncio.run(_dauer(0)) >= AS.FEHL_MINDESTDAUER_S - 0.02)
    check("…eine schon langsame Antwort nicht weiter", asyncio.run(_dauer(5)) < 0.05)

    # ── Main per AST ─────────────────────────────────────────────────────────
    MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    BAUM = ast.parse(MAIN)
    FN = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    noetig = ["_ad_vorab_freigabe", "_gruppen_passen", "_ad_user_allowed",
              "authenticate_linux_user", "_login_ablauf", "login",
              "_anmelde_schwellen_aktualisieren", "_ldap_escape", "_group_cn_prefix",
              "_dn_norm", "_gruppe_passt"]
    fehlt = [n for n in noetig if n not in FN]
    if fehlt:
        abbruch("in main.py nicht gefunden: %s" % fehlt)

    def _laden(namen, ns):
        knoten = []
        for n in namen:
            f = FN[n]
            f.decorator_list = []
            knoten.append(f)
        exec(compile(ast.fix_missing_locations(ast.Module(body=knoten, type_ignores=[])),
                     "main.py<auszug>", "exec"), ns)
        return ns

    # ── [B] Vorabpruefung ───────────────────────────────────────────────────
    print("\n[B] _ad_vorab_freigabe")

    class _Eintrag(dict):
        def __contains__(self, k):
            return dict.__contains__(self, k)

    class _Wert:
        def __init__(self, v):
            self.values = v

    class _Conn:
        """ldap3-Verbindung in echter Form: search(...), entries, unbind()."""
        def __init__(self, verzeichnis, wirft=False):
            self.v, self.wirft, self.entries, self.suchen = verzeichnis, wirft, [], 0

        def search(self, search_base, search_filter, attributes, **k):
            self.suchen += 1
            if self.wirft:
                raise RuntimeError("Suche gescheitert")
            name = search_filter.split("=", 1)[1].rstrip(")")
            self.entries = ([_Eintrag(memberOf=_Wert(self.v[name]))] if name in self.v else [])
            return True

        def unbind(self):
            pass

    DIR = {"anna": ["CN=Jarvis-Nutzer,OU=G,DC=firma,DC=local"], "bert": ["CN=Andere,DC=firma,DC=local"]}
    BINDS = {"n": 0, "wirft": False, "suche_wirft": False}

    def _bind():
        BINDS["n"] += 1
        if BINDS["wirft"]:
            raise RuntimeError("BIND_FAILED")
        return _Conn(DIR, wirft=BINDS["suche_wirft"]), "DC=firma,DC=local"

    sys.modules["backend.ldap_directory"] = types.SimpleNamespace(_bind=_bind)
    import backend
    backend.ldap_directory = sys.modules["backend.ldap_directory"]

    NSB = {"config": _cfg.config, "time": time, "print": lambda *a, **k: None,
           "_norm_login": lambda n: (n or "").split("@")[0].split("\\")[-1].strip().lower(),
           "_VORAB_DIENST_PAUSE_S": 600, "_vorab_dienst_pause": {"bis": 0.0},
           "os": os, "_CN_TREFFER_GEMELDET": set()}
    # _dn_norm/_gruppe_passt: seit 2026-10-18 die EINE Gruppenregel (DN-genau)
    _laden(["_ldap_escape", "_group_cn_prefix", "_dn_norm", "_gruppe_passt", "_gruppen_passen",
            "_ad_vorab_freigabe"], NSB)
    vorab = NSB["_ad_vorab_freigabe"]
    GRUPPE = "CN=Jarvis-Nutzer,OU=G,DC=firma,DC=local"

    EINST.clear()
    check("nichts freigegeben -> nein (ohne Verzeichnis)", vorab("anna") == "nein" and BINDS["n"] == 0)
    EINST.update(ad_allowed_users="anna, bert")
    check("in der Benutzerliste -> ja (ohne Verzeichnis)", vorab("FIRMA\\Anna") == "ja" and BINDS["n"] == 0)
    check("nur Liste, Name fehlt -> nein", vorab("carl") == "nein")
    EINST.clear(); EINST.update(ad_allowed_group=GRUPPE)
    check("Gruppe ohne Dienstkonto -> unbekannt (wie bisher binden)", vorab("anna") == "unbekannt")
    EINST.update(ad_bind_user="svc")
    check("Gruppe + Dienstkonto: Mitglied -> ja", vorab("anna") == "ja")
    check("Gruppe + Dienstkonto: kein Mitglied -> nein", vorab("bert") == "nein")
    check("Gruppe + Dienstkonto: Name existiert nicht -> nein", vorab("niemand") == "nein")
    BINDS["suche_wirft"] = True
    check("Suche scheitert -> unbekannt, NIE nein", vorab("bert") == "unbekannt")
    BINDS["suche_wirft"] = False
    BINDS["wirft"] = True
    n0 = BINDS["n"]
    erst = vorab("anna")
    zweit = vorab("anna")
    check("Dienst-Bind scheitert -> unbekannt, NIE nein", erst == "unbekannt")
    check("…und wird in der Pause NICHT wiederholt (sonst sperrt ein Angriff das Dienstkonto)",
          zweit == "unbekannt" and BINDS["n"] == n0 + 1)
    NSB["_vorab_dienst_pause"]["bis"] = 0.0
    BINDS["wirft"] = False
    check("nach der Pause wird wieder gefragt", vorab("anna") == "ja")
    check("Positivkontrolle der Attrappe: LDAP-Sonderzeichen werden escaped",
          vorab("x*)(cn=*") == "nein")

    # ── [C] authenticate_linux_user ─────────────────────────────────────────
    print("\n[C] authenticate_linux_user")
    VERBINDEN = []

    class _TlsFehler(Exception):
        pass

    sys.modules["backend.ldap_tls"] = types.SimpleNamespace(
        verbinden=lambda *a, **k: VERBINDEN.append(a) or (_ for _ in ()).throw(RuntimeError("stop")),
        TlsFehler=_TlsFehler)
    backend.ldap_tls = sys.modules["backend.ldap_tls"]
    sys.modules.setdefault("ldap3", types.ModuleType("ldap3"))
    VORAB = {"w": "nein"}
    NSC = {"ALLOWED_USERS": set(), "config": _cfg.config, "time": time,
           "print": lambda *a, **k: None, "_ad_vorab_freigabe": lambda u: VORAB["w"]}
    _laden(["authenticate_linux_user"], NSC)
    auth = NSC["authenticate_linux_user"]
    EINST.clear(); EINST.update(ad_server="ldaps://dc.firma.local", ad_domain="firma.local")
    det: dict = {}
    r = auth("bert", "Sommer2026!", det)
    check("nicht freigegeben: abgelehnt, Grund 'nicht_freigegeben'",
          r is False and det.get("reason") == "nicht_freigegeben")
    check("nicht freigegeben: KEIN Kennwort zum DC (verbinden nie gerufen)", VERBINDEN == [])
    VORAB["w"] = "ja"
    auth("anna", "x", {})
    check("Positivkontrolle: freigegeben -> der Bind wird versucht", len(VERBINDEN) == 1)
    VORAB["w"] = "unbekannt"
    auth("anna", "x", {})
    check("unbekannt -> wie bisher binden", len(VERBINDEN) == 2)

    # ── [D] Login-Ablauf am Syntaxbaum ──────────────────────────────────────
    print("\n[D] Login-Ablauf")
    abl = FN["_login_ablauf"]
    texte = [c.value for c in ast.walk(abl) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    check("kein 'Keine Anmeldeberechtigung' mehr im Login (das Orakel)",
          not any("Keine Anmeldeberechtigung" in s for s in texte))
    antworten_401 = []
    for c in ast.walk(abl):
        if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "JSONResponse":
            sc = next((kw.value.value for kw in c.keywords if kw.arg == "status_code"
                       and isinstance(kw.value, ast.Constant)), None)
            if sc in (401, 403) and c.args and isinstance(c.args[0], ast.Dict):
                for k_, v_ in zip(c.args[0].keys, c.args[0].values):
                    if isinstance(k_, ast.Constant) and k_.value == "error" and isinstance(v_, ast.Constant):
                        antworten_401.append((sc, v_.value))
    check("Positivkontrolle: Fehlantworten im Login gefunden (%d)" % len(antworten_401),
          len(antworten_401) >= 2)
    check("kein 403 mehr im Login (eine eigene Antwort verriete 'Kennwort stimmt')",
          all(s != 403 for s, _ in antworten_401))
    check("kein LDAP/fremder Name UND falsches Kennwort: derselbe Text (>= 2 Stellen)",
          sum(1 for s, txt in antworten_401
              if (s, txt) == (401, "Benutzername oder Passwort falsch")) >= 2)
    lg = FN["login"]
    aufrufe = {getattr(c.func, "attr", "") for c in ast.walk(lg) if isinstance(c, ast.Call)
               and isinstance(c.func, ast.Attribute) and getattr(c.func.value, "id", "") == "_anmelde_schutz"}
    check("login() ruft bremse() und angleichen()", {"bremse", "angleichen"} <= aufrufe)
    for name in ("_ad_user_allowed", "_ad_vorab_freigabe"):
        ruft = any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_gruppen_passen"
                   for c in ast.walk(FN[name]))
        check("%s nutzt DIESELBE Gruppenfunktion (_gruppen_passen)" % name, ruft)

    # ── [E] Schwellen aus der Richtlinie ────────────────────────────────────
    print("\n[E] _anmelde_schwellen_aktualisieren")
    neu()
    RICHT = {"w": {"schwelle": 3, "fenster_s": 1800.0}}
    NSE = {"config": _cfg.config, "_anmelde_schutz": AS, "print": lambda *a, **k: None,
           "_ad_sperrrichtlinie_lesen": lambda: RICHT["w"]}
    _laden(["_anmelde_schwellen_aktualisieren"], NSE)
    akt = NSE["_anmelde_schwellen_aktualisieren"]
    akt()
    check("Domaene 3 in 30 min -> Jarvis 2 in 30 min",
          AS.KONTO_MAX == 2 and AS.KONTO_FENSTER_S == 1800 and AS.SCHWELLEN_QUELLE == "domaene")
    RICHT["w"] = None
    akt()
    check("Richtlinie nicht lesbar -> Rueckfallschwelle", AS.KONTO_MAX == AS.KONTO_MAX_OHNE_RICHTLINIE
          and AS.SCHWELLEN_QUELLE == "ohne_richtlinie")
    EINST.clear()
    akt()
    check("ohne Domaene -> Vorgabe", AS.KONTO_MAX == AS.KONTO_MAX_VORGABE)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)

#!/usr/bin/env python3
"""Live-Probe auf DEV: persoenlicher Confluence-Zugang gegen den ECHTEN Dienst.

Laeuft AUF DEM SERVER im Produktiv-venv. Gemessen wird ueber HTTPS, also den
echten Bedienweg – ein Zweitprozess, der die Dateien selbst liest, misst nicht
den Dienst, der schreibt (Register).

⚠ DER VORGEFUNDENE ZUSTAND WIRD WIEDERHERGESTELLT, nicht geraten. Die Probe
legt einen Zugang fuer einen WEGWERF-Benutzer an und entfernt ihn im ``finally``
(ueber ``atexit`` gesichert – ein Abbruch mitten drin darf keinen Eintrag
hinterlassen). Der Skill-Schalter und der Sammelzugang werden **nur gelesen**.

⚠ SIE BRAUCHT KEINEN ECHTEN PAT. Ein erfundener Token MUSS von Confluence
abgelehnt werden – genau das ist die Messung: der Aufruf geht wirklich ans Netz,
und die Ablehnung beweist, dass ALICES Token benutzt wurde und nicht der
Sammelzugang (der wuerde antworten).

Lauf auf DEV:  cd /opt/jarvis && ./venv/bin/python tests/live_confluence_zugang_dev.py
"""

import atexit
import json
import ssl
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/opt/jarvis")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

BASIS = "https://127.0.0.1"
# ⚠ EIN ERFUNDENER BENUTZER TAUGT NICHT: `require_auth` weist jeden ab, der
# nicht angemeldet sein DARF – der erste Lauf meldete 24 FAIL mit lauter
# `403 NOT_AUTHORIZED`, und keiner davon war ein Codefehler. Genommen wird der
# freigegebene Benutzer, nicht die Freigabe umgestellt (Register).
#
# `jarvis` ist das lokale Dienstkonto und damit die harmlosere Wahl gegenueber
# einem echten Menschen: die Probe legt einen Wegwerf-Token an, und ein Mensch
# koennte in demselben Moment seinen eigenen pflegen.
PROBE_USER = "jarvis"

_ok = _fail = 0


def check(text, bed, extra=""):
    global _ok, _fail
    if not isinstance(text, str):
        print("ABBRUCH: check() vertauscht"); sys.exit(2)
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, (" – %s" % extra) if extra else ""))


def section(t):
    print("\n═══ %s" % t)


_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE   # Selbstsigniert auf DEV; wir messen lokal.


def ruf(pfad, methode="GET", rumpf=None, token=None):
    """(status, dict). Wirft nie – ein Fehlschlag ist ein Messwert."""
    d = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=d, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if d:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60, context=_CTX) as a:
            roh = a.read().decode(errors="replace")
            try:
                return a.status, json.loads(roh or "{}")
            except ValueError:
                # ⚠ NICHT JEDE ANTWORT IST JSON – `/confluence-addon` liefert
                # HTML. Die erste Fassung parste bedingungslos, der Wurf landete
                # im `except` und meldete -1: ein Fehler, den es nicht gab.
                #
                # ⚠ UND DER TEXT WIRD GANZ DURCHGEREICHT, nur die ANZEIGE
                # gekuerzt: mit `roh[:200]` lag der gesuchte Container-Marker
                # ausserhalb des Ausschnitts, und die Pruefung meldete einen
                # Fehler, den es nicht gab (zweiter Messfehler derselben Art in
                # dieser Datei).
                return a.status, {"_html": roh, "_kurz": roh[:200]}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return -1, {"_fehler": str(e)}


from backend import main as M            # noqa: E402
from backend import confluence_accounts as ca  # noqa: E402

TOKEN = M.generate_token(PROBE_USER)


def abraeumen():
    """Der Wegwerf-Zugang MUSS weg – auch bei einem Abbruch."""
    try:
        if ca.hat_zugang(PROBE_USER):
            ca.loeschen(PROBE_USER)
            print("  … Wegwerf-Zugang entfernt")
    except Exception as e:  # noqa: BLE001
        print("  ⚠ Wegwerf-Zugang NICHT entfernt: %s" % e)


atexit.register(abraeumen)

# Vorzustand festhalten – gemessen, nicht angenommen.
VOR_BENUTZER = set(ca.alle_benutzer())
VOR_BASIS = ca.basis_url()
VOR_SAMMEL = ca.sammel_client().configured
print("Vorzustand: %d Zugang/Zugaenge, Adresse=%r, Sammelzugang=%s"
      % (len(VOR_BENUTZER), VOR_BASIS, VOR_SAMMEL))
if PROBE_USER in VOR_BENUTZER:
    print("ABBRUCH: der Wegwerf-Benutzer hat schon einen Zugang – Rueckstand "
          "eines frueheren Laufs. Erst pruefen, dann erneut fahren.")
    sys.exit(2)
if not VOR_BASIS or not VOR_SAMMEL:
    print("ABBRUCH: ohne konfigurierten Sammelzugang ist der Rueckfall nicht "
          "messbar – 'konnte nicht laufen' ist nicht 'bestanden'.")
    sys.exit(2)

# ═════════════════════════════════════════════════════════════════════════════
section("1) Die Seite und die Freigabe")
# ═════════════════════════════════════════════════════════════════════════════
s, d = ruf("/confluence-addon")
check("GET /confluence-addon liefert die Seite (ohne Token, leere Huelle)",
      s == 200, str(s))
check("… und es ist WIRKLICH die Seite (Container im Markup)",
      'id="ca-sect-account"' in str(d.get("_html", "")),
      str(d.get("_kurz", ""))[:120])
check("… und sie bindet ihr Modul ein (kein halber Frontend-Deploy)",
      "confluence_addon.js?v=" in str(d.get("_html", "")))
s, d = ruf("/api/me", token=TOKEN)
check("/api/me meldet permissions.confluence",
      s == 200 and (d.get("permissions") or {}).get("confluence") is True,
      "%s %s" % (s, (d.get("permissions") or {}).get("confluence")))

# ═════════════════════════════════════════════════════════════════════════════
section("2) Ohne Token kommt niemand an den Zugang")
# ═════════════════════════════════════════════════════════════════════════════
for m in ("GET", "POST", "DELETE"):
    s, _ = ruf("/api/confluence/account", m,
               {"api_token": "X"} if m == "POST" else None)
    check("%s /api/confluence/account ohne Token: 401" % m, s == 401, str(s))
s, _ = ruf("/api/confluence/account", token="Muell-Token")
check("… und mit Muell-Token ebenfalls 401", s == 401, str(s))

# ═════════════════════════════════════════════════════════════════════════════
section("3) Der Zustand kommt heraus – der Token NIE")
# ═════════════════════════════════════════════════════════════════════════════
s, d = ruf("/api/confluence/account", token=TOKEN)
acc = d.get("account") or {}
check("GET liefert den Zustand", s == 200 and d.get("ok") is True, "%s %s" % (s, d))
check("noch kein eigener Zugang", acc.get("vorhanden") is False, str(acc))
check("die Adresse wird ANGEZEIGT (der Benutzer muss sie kennen)",
      acc.get("basis_url") == VOR_BASIS, repr(acc.get("basis_url")))
check("der Sammelzugang wird als vorhanden gemeldet",
      acc.get("sammel_vorhanden") is True, str(acc.get("sammel_vorhanden")))

s, d = ruf("/api/confluence/account", "POST",
           {"api_token": "PROBE-PAT-NICHT-ECHT", "aktiv": True}, token=TOKEN)
check("POST legt den Zugang an", s == 200 and d.get("ok") is True, "%s %s" % (s, d))
acc = d.get("account") or {}
check("… und die Antwort meldet 'vorhanden'", acc.get("vorhanden") is True, str(acc))
check("⚠ der Token steht NICHT in der Antwort",
      "PROBE-PAT-NICHT-ECHT" not in json.dumps(d), json.dumps(d)[:200])
check("… auch nicht maskiert – es gibt nur ein Ja/Nein",
      acc.get("token_gesetzt") is True
      and not any(isinstance(v, str) and "*" in v for v in acc.values()))

# ═════════════════════════════════════════════════════════════════════════════
section("4) Auf der PLATTE liegt er verschluesselt – und die Rechte stimmen")
# ═════════════════════════════════════════════════════════════════════════════
datei = ca.KONTEN_DATEI
schluessel = ca.SCHLUESSEL_DATEI
check("die Kontendatei ist entstanden", datei.exists(), str(datei))
if datei.exists():
    roh = datei.read_text(encoding="utf-8")
    check("⚠ der Token liegt NICHT im Klartext darin",
          "PROBE-PAT-NICHT-ECHT" not in roh, roh[:200])
    check("Rechte 0640", oct(datei.stat().st_mode & 0o777) == "0o640",
          oct(datei.stat().st_mode & 0o777))
check("die Schluesseldatei ist entstanden", schluessel.exists(), str(schluessel))
if schluessel.exists():
    check("Rechte 0600", oct(schluessel.stat().st_mode & 0o777) == "0o600",
          oct(schluessel.stat().st_mode & 0o777))
# Der Shell-Weg: `authorize_fs` muss BEIDE verweigern – mit Positivkontrolle,
# dass es nicht einfach alles verweigert (sonst waere die Messung trivial).
from backend.sandbox import authorize_fs  # noqa: E402
# ⚠ POSITIVKONTROLLE ZUERST. `authorize_fs` sperrt den GANZEN App-Baum fuers
# Lesen ("nur in den Wissens-/Arbeitsverzeichnissen") – eine Datei aus
# /opt/jarvis taugt deshalb nicht als Gegenprobe, und ohne diese Kontrolle waere
# "verweigert" trivial wahr: es waere auch ohne jeden Sperrlisten-Eintrag so.
e, g = authorize_fs("read", str(ROOT / "data/rag/probe.txt"), PROBE_USER)
if not e:
    print("ABBRUCH: authorize_fs verweigert schon einen erlaubten Pfad (%s) – "
          "die Messung darunter waere trivial." % g[:80])
    sys.exit(2)
check("Positivkontrolle: ein Wissenspfad ist lesbar", bool(e), g[:80])
# ⚠ UND DIE ZUSAGE IST DER GRUND, NICHT DAS NEIN. Faellt der Eintrag aus der
# Sperrliste, verweigert die allgemeine Bereichsregel die Datei WEITERHIN – die
# Pruefung "wird verweigert" waere damit blind fuer genau den Fehler, den sie
# finden soll. Gemessen wird deshalb, dass die Datei als GESCHUETZT gilt.
_e_ref, g_ref = authorize_fs("read", str(ROOT / "backend/main.py"), PROBE_USER)
for p in (datei, schluessel):
    e, g = authorize_fs("read", str(p), PROBE_USER)
    check("authorize_fs verweigert %s" % p.name, not e, str(g)[:80])
    check("… und zwar als GESCHUETZTE Datei, nicht ueber die Bereichsregel",
          (not e) and g != g_ref, "%r == Bereichsregel %r" % (g[:50], g_ref[:50]))

# ═════════════════════════════════════════════════════════════════════════════
section("5) ⚠ Der Verbindungstest geht WIRKLICH ans Netz – mit ALICES Token")
# ═════════════════════════════════════════════════════════════════════════════
# Der erfundene Token MUSS abgelehnt werden. Antwortete hier der Sammelzugang,
# kaeme ein "ok" – genau die Falle, gegen die der Test gebaut ist.
s, d = ruf("/api/confluence/account/test", "POST", None, token=TOKEN)
check("der Test antwortet (der Aufruf ist wirklich rausgegangen)", s != -1, str(d))
check("⚠ ein erfundener Token wird ABGELEHNT (kein Rueckfall auf den Sammelzugang)",
      s in (400, 500) and d.get("ok") is not True, "%s %s" % (s, d))
grund = str(d.get("error") or "")
check("… und der Grund nennt Confluence", "Confluence" in grund, grund[:160])
s, d = ruf("/api/confluence/account", token=TOKEN)
check("der Fehlschlag steht danach am Zugang",
      bool((d.get("account") or {}).get("letzter_fehler")),
      str((d.get("account") or {}).get("letzter_fehler"))[:160])

# ═════════════════════════════════════════════════════════════════════════════
section("6) Die Aufloesung im echten Dienst: persoenlich statt Sammelzugang")
# ═════════════════════════════════════════════════════════════════════════════
r = ca.aufloesen(PROBE_USER)
check("Quelle ist der persoenliche Zugang",
      r["quelle"] == ca.QUELLE_PERSOENLICH, r["quelle"])
check("der Client traegt den Probe-Token",
      r["client"].token == "PROBE-PAT-NICHT-ECHT", r["client"].token[:20])
check("die Adresse kommt weiterhin vom Administrator",
      r["client"].base == VOR_BASIS, r["client"].base)
# ⚠ EIN SELBSTVERGLEICH BEWEIST NICHTS: die erste Fassung nahm hier "jarvis" –
# also PROBE_USER selbst –, und die Pruefung meldete "persoenlich". Kein
# Codefehler, ein Messfehler. `aufloesen` liest nur, es entsteht kein Eintrag.
ANDERER = ziele.wert("JARVIS_DEV_TESTUSER")
if ca.norm_user(ANDERER) == ca.norm_user(PROBE_USER):
    print("ABBRUCH: der Vergleichsbenutzer ist derselbe – Selbstvergleich.")
    sys.exit(2)
check("Positivkontrolle: der Vergleichsbenutzer hat keinen eigenen Zugang",
      not ca.hat_zugang(ANDERER))
r2 = ca.aufloesen(ANDERER)
check("⚠ ein ANDERER Benutzer bleibt unveraendert beim Sammelzugang",
      r2["quelle"] == ca.QUELLE_SAMMEL, r2["quelle"])
check("… und traegt NICHT den Probe-Token",
      r2["client"].token != "PROBE-PAT-NICHT-ECHT")

# ═════════════════════════════════════════════════════════════════════════════
section("7) Der Sammelzugang funktioniert weiter – gegen das ECHTE Confluence")
# ═════════════════════════════════════════════════════════════════════════════
# Positivkontrolle des ganzen Umbaus: ohne sie koennte der persoenliche Zweig
# richtig sein und der Rueckfall trotzdem kaputt.
from backend.confluence_client import ConfluenceError  # noqa: E402
try:
    sp = ca.sammel_client().spaces(3)
    check("der Sammelzugang liest echte Bereiche", isinstance(sp, list) and sp,
          str([x.get("key") for x in (sp or [])])[:120])
except ConfluenceError as e:
    check("der Sammelzugang liest echte Bereiche", False, "ConfluenceError %s" % e)
except Exception as e:  # noqa: BLE001
    check("der Sammelzugang liest echte Bereiche", False, str(e)[:120])
# Und WER ist der Sammelzugang? Das beantwortet die neue Client-Methode.
try:
    ich = ca.sammel_client().current_user() or {}
    check("⚠ /rest/api/user/current antwortet auf DIESEM Confluence",
          bool(ich.get("displayName") or ich.get("username")),
          json.dumps(ich)[:160])
except ConfluenceError as e:
    # Das ist der Fall, fuer den der 404-Rueckfall gebaut ist – er gehoert
    # BENANNT, nicht stillschweigend als Erfolg gezaehlt.
    check("⚠ /rest/api/user/current antwortet auf DIESEM Confluence", False,
          "HTTP %s – der 404-Rueckfall in testen() greift hier" % e.status)
except Exception as e:  # noqa: BLE001
    check("⚠ /rest/api/user/current antwortet auf DIESEM Confluence", False,
          str(e)[:120])

# ═════════════════════════════════════════════════════════════════════════════
section("8) base_url aus dem Rumpf wird abgewiesen")
# ═════════════════════════════════════════════════════════════════════════════
s, d = ruf("/api/confluence/account", "POST",
           {"base_url": "https://boese.example"}, token=TOKEN)
check("⚠ base_url im Rumpf: 400", s == 400, "%s %s" % (s, d))
check("… und die Meldung nennt den Weg", "Administrator" in str(d.get("error")),
      str(d.get("error"))[:160])
check("die Adresse blieb unveraendert", ca.basis_url() == VOR_BASIS)
s, d = ruf("/api/confluence/account", "POST",
           {"api_token": "", "aktiv": False}, token=TOKEN)
check("ein leeres Token-Feld loescht den Token NICHT",
      s == 200 and ca.aufloesen(PROBE_USER)["client"] is not None
      and ca.zugang_info(PROBE_USER)["token_gesetzt"] is True, "%s %s" % (s, d))
check("… und der Haken ist uebernommen",
      ca.zugang_info(PROBE_USER)["aktiv"] is False)

# ═════════════════════════════════════════════════════════════════════════════
section("9) Das Auge am Kennwortfeld (POST /api/secret/reveal)")
# ═════════════════════════════════════════════════════════════════════════════
s, d = ruf("/api/secret/reveal", "POST",
           {"bereich": "confluence", "kennung": "api_token"}, token=TOKEN)
check("der Bereich 'confluence' ist bekannt und gibt den Wert heraus",
      s == 200 and d.get("wert") == "PROBE-PAT-NICHT-ECHT", "%s %s" % (s, str(d)[:120]))
s, d = ruf("/api/secret/reveal", "POST",
           {"bereich": "confluence", "kennung": "base_url"}, token=TOKEN)
check("⚠ ein Nicht-Geheimfeld wird abgewiesen", s != 200 or not d.get("wert"),
      "%s %s" % (s, str(d)[:120]))
s, d = ruf("/api/secret/reveal", "POST",
           {"bereich": "confluence", "kennung": "api_token", "user": "jarvis",
            "benutzer": "jarvis"}, token=TOKEN)
check("⚠ ein Benutzername im Rumpf aendert NICHTS",
      s == 200 and d.get("wert") == "PROBE-PAT-NICHT-ECHT", "%s %s" % (s, str(d)[:120]))

# ═════════════════════════════════════════════════════════════════════════════
section("10) Loeschen – und der Ausgangszustand steht wieder")
# ═════════════════════════════════════════════════════════════════════════════
s, d = ruf("/api/confluence/account", "DELETE", token=TOKEN)
check("DELETE meldet Erfolg", s == 200 and d.get("removed") is True, "%s %s" % (s, d))
check("danach gilt wieder der Sammelzugang",
      ca.aufloesen(PROBE_USER)["quelle"] == ca.QUELLE_SAMMEL)
check("⚠ der VORGEFUNDENE Bestand ist unveraendert",
      set(ca.alle_benutzer()) == VOR_BENUTZER,
      "vorher %s / nachher %s" % (sorted(VOR_BENUTZER), ca.alle_benutzer()))
check("der Skill-Schalter wurde nicht angefasst",
      ca.sammel_client().configured is VOR_SAMMEL)

print("\n" + "═" * 70)
print("ERGEBNIS: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)

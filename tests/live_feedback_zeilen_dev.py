#!/usr/bin/env python3
"""Live auf DEV: der Bewertungsbogen ueber die ECHTEN Endpunkte.

Gemessen wird die Kette, die ein jsdom-Lauf nicht abbilden kann: HTTPS,
Rechteprueufung, Dateiablage, CSV-Export.

⚠ DER VORGEFUNDENE ZUSTAND WIRD ERFASST UND WIEDERHERGESTELLT – nicht geraten.
Auf DEV ist der Feedback-Skill AUS und es gibt keine Datendateien; wer das
hinterher blind „aufraeumt", kann einen Zustand herstellen, den der Betreiber
nie hatte (Register: `test_messung_zustand`).

Aufruf auf DEV:  ./venv/bin/python tests/live_feedback_zeilen_dev.py
"""
import json
import os
import pathlib
import ssl
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

BASIS = "https://127.0.0.1"
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

_ok = _fail = 0


def check(was, bedingung, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % was)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s%s" % (was, (" – " + detail) if detail else ""))


def ruf(pfad, method="GET", body=None, token=None, roh=False):
    """(status, daten). Wirft NICHT – ein Fehlschlag ist ein Messwert."""
    r = urllib.request.Request(BASIS + pfad, method=method)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    d = None
    if body is not None:
        d = json.dumps(body).encode("utf-8")
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, d, timeout=30, context=_ctx) as a:
            inhalt = a.read()
            if roh:
                return a.status, inhalt
            try:
                return a.status, json.loads(inhalt)
            except Exception:  # noqa: BLE001
                return a.status, None
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:  # noqa: BLE001
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m0. Vorgefundenen Zustand erfassen\033[0m")
# ═══════════════════════════════════════════════════════════════════════════
from backend import feedback as fb  # noqa: E402
from backend import main as bm  # noqa: E402

_SETTINGS = ROOT / "data" / "settings.json"


def skill_zustand():
    """Den Skill-Zustand FRISCH VON PLATTE lesen.

    ⚠ NICHT ueber eine `Config`-Instanz im Messprozess: die haelt den Stand vom
    eigenen Start und sieht nicht, was der DIENST zwischenzeitlich geschrieben
    hat. Geschaltet wird ueber den HTTP-Endpunkt, also schreibt der Dienst –
    gelesen gehoert deshalb die Datei (Register).
    """
    try:
        return (json.loads(_SETTINGS.read_text(encoding="utf-8"))
                .get("skills", {}).get("feedback"))
    except Exception:  # noqa: BLE001
        return None


_STATUS_VOR = skill_zustand()
_FORM_VOR = fb._pfad_formulare().exists()
_ABG_VOR = fb._pfad_abgaben().exists()
print("  Skill-Zustand vorher : %r" % (_STATUS_VOR,))
print("  Formulardatei vorher : %s" % ("vorhanden" if _FORM_VOR else "NICHT vorhanden"))
print("  Abgabendatei vorher  : %s" % ("vorhanden" if _ABG_VOR else "NICHT vorhanden"))

TOKEN = bm.generate_token("jarvis")
st, me = ruf("/api/me", token=TOKEN)
check("das Sitzungstoken traegt (Positivkontrolle)", st == 200 and isinstance(me, dict),
      "Status %s" % st)
if st != 200:
    print("\nABBRUCH: ohne Anmeldung ist keine Messung deutbar.")
    sys.exit(2)
check("der Benutzer ist Administrator (fuer die Admin-Endpunkte noetig)",
      bool(me.get("is_admin")))

# Der Skill muss AN sein, sonst antwortet die Benutzer-Kachel 403. Ueber den
# ECHTEN Endpunkt schalten – ein `save_skill_state()` im Messprozess erreicht
# den laufenden Dienst nicht (Register).
_SKILL_GESCHALTET = False
if not (_STATUS_VOR or {}).get("enabled"):
    st_e, _ = ruf("/api/skills/feedback/enable", "POST", {}, TOKEN)
    _SKILL_GESCHALTET = st_e == 200
    check("den Skill fuer die Messung eingeschaltet", _SKILL_GESCHALTET,
          "Status %s" % st_e)

_abgaben_ids = []
fid = ""
try:
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\033[1m1. Den Bewertungsbogen anlegen\033[0m")
    # ═══════════════════════════════════════════════════════════════════════
    TEXTE = ["Erreichbarkeit", "Reaktionszeit", "Fachliche Qualität",
             "Freundlichkeit", "Dokumentation", "Gesamteindruck"]
    st, d = ruf("/api/feedback/admin/formulare", "POST", {
        "titel": "LIVE Gesamtbewertung (Messung)",
        "beschreibung": "Bitte bewerten.",
        "spalten": [{"id": "spkrit", "name": "Kriterium", "typ": "fest"},
                    {"id": "spanm", "name": "Anmerkung", "typ": "text"},
                    {"id": "spbew", "name": "Bewertung", "typ": "sterne"}],
        "zeilen": [{"id": "z%d" % i, "werte": {"spkrit": t}}
                   for i, t in enumerate(TEXTE)],
    }, TOKEN)
    check("das Formular wird angenommen", st == 200 and (d or {}).get("ok"),
          "Status %s: %s" % (st, d))
    form = (d or {}).get("formular") or {}
    fid = form.get("id") or ""
    check("es hat 6 feste Zeilen", len(form.get("zeilen") or []) == 6)
    check("die Kennungen sind uebernommen",
          [z.get("id") for z in (form.get("zeilen") or [])]
          == ["z%d" % i for i in range(6)])

    st, d = ruf("/api/feedback/admin/formulare", "POST", {
        "titel": "LIVE ohne Zeilen (Messung)",
        # ⚠ MIT einer ausfuellbaren Spalte: nur `fest` faellt schon vorher in
        # die Sackgassen-Regel, und dann misst der Fall etwas anderes als er
        # behauptet (eigener Messfehler, 2026-09-15).
        "spalten": [{"id": "k", "name": "Kriterium", "typ": "fest"},
                    {"id": "t", "name": "Anmerkung", "typ": "text"}],
        "zeilen": [],
    }, TOKEN)
    check("⚠ `fest` ohne feste Zeilen: 400 mit Grund", st == 400
          and "Feste Zeilen" in str((d or {}).get("error") or ""),
          "Status %s: %s" % (st, d))

    # ═══════════════════════════════════════════════════════════════════════
    print("\n\033[1m2. Das Formular kommt beim Benutzer an\033[0m")
    # ═══════════════════════════════════════════════════════════════════════
    st, d = ruf("/api/feedback/formulare", token=TOKEN)
    if st == 403:
        print("  \033[33m!\033[0m der Benutzer `jarvis` hat keinen Feedback-Zugang – "
              "Abschnitt 2/3 NICHT PRUEFBAR")
        _fail += 1
    else:
        check("die Liste kommt", st == 200 and (d or {}).get("ok"), "Status %s" % st)
        meins = next((f for f in ((d or {}).get("formulare") or [])
                      if f.get("id") == fid), None)
        check("der Bogen ist dabei", meins is not None)
        check("⚠ die festen Zeilen gehen an den Client",
              len(((meins or {}).get("zeilen") or [])) == 6,
              "ohne sie zeichnet die Seite eine leere Zeile")
        check("mit ihrem Text",
              ((((meins or {}).get("zeilen") or [{}])[0]).get("werte") or {})
              .get("spkrit") == "Erreichbarkeit")

        # ═══════════════════════════════════════════════════════════════════
        print("\n\033[1m3. Abgabe – mit Faelschungsversuch\033[0m")
        # ═══════════════════════════════════════════════════════════════════
        st, d = ruf("/api/feedback/abgabe", "POST", {
            "formular_id": fid,
            "zeilen": [
                {"_zid": "z0", "spkrit": "GEFAELSCHT", "spanm": "lief gut", "spbew": 5},
                {"_zid": "z3", "spbew": 3},
                {"_zid": "fremd", "spanm": "darf nicht ankommen"},
            ],
        }, TOKEN)
        check("die Abgabe wird angenommen", st == 200 and (d or {}).get("ok"),
              "Status %s: %s" % (st, d))
        # ⚠ MERKEN, um sie hinterher zu entfernen: `formular_loeschen` laesst
        # die Abgaben bewusst liegen – sie waere sonst ein Rueckstand im ECHTEN
        # Bestand (auf DEV ist der Skill entgegen der Doku AN und es gibt
        # Datendateien).
        _abgaben_ids.append(((d or {}).get("abgabe") or {}).get("id") or "")
        zl = ((d or {}).get("abgabe") or {}).get("zeilen") or []
        check("alle 6 Zeilen sind gespeichert", len(zl) == 6)
        check("⚠ DER FESTE TEXT KOMMT AUS DER DEFINITION",
              bool(zl) and zl[0].get("spkrit") == "Erreichbarkeit",
              "gemessen: %r" % (zl[0].get("spkrit") if zl else None))
        check("die fremde Zeile ist verworfen",
              all(z.get("_zid", "").startswith("z") for z in zl))

        st, d = ruf("/api/feedback/abgabe", "POST",
                    {"formular_id": fid, "zeilen": [{"_zid": "z0"}]}, TOKEN)
        check("eine Abgabe ohne jede Eingabe: 400 mit Grund", st == 400,
              "Status %s: %s" % (st, d))

    # ═══════════════════════════════════════════════════════════════════════
    print("\n\033[1m4. Auf Platte und im CSV\033[0m")
    # ═══════════════════════════════════════════════════════════════════════
    roh = json.loads(fb._pfad_formulare().read_text(encoding="utf-8"))
    dort = next((f for f in roh.get("formulare", []) if f.get("id") == fid), {})
    check("die Definition liegt auf Platte", len(dort.get("zeilen") or []) == 6)
    check("die Datei ist 0640",
          oct(fb._pfad_formulare().stat().st_mode & 0o777) == "0o640",
          oct(fb._pfad_formulare().stat().st_mode & 0o777))

    st, inhalt = ruf("/api/feedback/admin/export?fid=" + fid, token=TOKEN, roh=True)
    if st == 200 and isinstance(inhalt, bytes):
        text = inhalt.decode("utf-8-sig")
        check("der CSV-Kopf nennt die feste Spalte", "Kriterium" in text.splitlines()[0])
        check("der feste Text steht darin", "Erreichbarkeit" in text)
        check("⚠ der gefaelschte Text steht NICHT darin", "GEFAELSCHT" not in text)
    else:
        check("der CSV-Export antwortet", False, "Status %s" % st)

    st, _ = ruf("/api/feedback/formulare")
    check("ohne Token: 401", st == 401, "Status %s" % st)

finally:
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\033[1m5. Vorgefundenen Zustand wiederherstellen\033[0m")
    # ═══════════════════════════════════════════════════════════════════════
    for aid in [x for x in _abgaben_ids if x]:
        st, _ = ruf("/api/feedback/admin/abgaben/" + aid, "DELETE", None, TOKEN)
        check("die Test-Abgabe ist entfernt", st == 200, "Status %s" % st)
    if fid:
        st, _ = ruf("/api/feedback/admin/formulare/" + fid, "DELETE", None, TOKEN)
        check("das Testformular ist entfernt", st == 200, "Status %s" % st)
    # Nur entfernen, was es VORHER nicht gab – sonst stellt die Messung einen
    # Zustand her, den der Betreiber nie hatte.
    for name, war_da, pfad in (("Formulardatei", _FORM_VOR, fb._pfad_formulare()),
                               ("Abgabendatei", _ABG_VOR, fb._pfad_abgaben())):
        if not war_da and pfad.exists():
            pfad.unlink()
            print("  entfernt (war vorher nicht da): %s" % name)
    if _SKILL_GESCHALTET:
        st, _ = ruf("/api/skills/feedback/disable", "POST", {}, TOKEN)
        check("der Skill ist wieder AUS (wie vorgefunden)", st == 200,
              "Status %s" % st)
    jetzt = skill_zustand()
    check("der Skill-Zustand entspricht dem vorgefundenen",
          bool((jetzt or {}).get("enabled")) == bool((_STATUS_VOR or {}).get("enabled")),
          "vorher %r, jetzt %r" % (_STATUS_VOR, jetzt))
    check("keine Datendatei zurueckgelassen",
          fb._pfad_formulare().exists() == _FORM_VOR
          and fb._pfad_abgaben().exists() == _ABG_VOR)

print("\n" + "=" * 70)
print("\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (_ok, _fail))
sys.exit(1 if _fail else 0)

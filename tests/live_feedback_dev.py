#!/usr/bin/env python3
"""Live-Messung des Feedback-Skills auf DEV, gegen die ECHTEN Endpunkte.

⚠ DER VORGEFUNDENE ZUSTAND WIRD GEMERKT UND EXAKT WIEDERHERGESTELLT – Skill-
Schalter und Freigabeliste gehoeren dem Betreiber. Ein geratener Leerwert ist
keine Wiederherstellung, sondern eine Aenderung (Register; test_messung_zustand
prueft das als Regel).

Das Sitzungstoken wird selbst erzeugt: /api/login laeuft gegen PAM, und das
OS-Kennwort weicht auf DEV vom .env-Eintrag ab (Register). Umgangen wird damit
nichts – jeder Endpunkt prueft danach Token UND Freigabe.
"""
import json
import sys
import subprocess
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
import ssl  # noqa: E402

ssl._create_default_https_context = ssl._create_unverified_context

from backend.config import config  # noqa: E402
from backend import main as M  # noqa: E402

BASIS = "https://127.0.0.1"
ok = fail = 0


def c(t, b, d=""):
    global ok, fail
    if b:
        ok += 1
        print("  \033[32m✓\033[0m %s" % t)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (t, (" – " + d) if d else ""))


def ruf(pfad, token=None, methode="GET", rumpf=None, roh=False):
    req = urllib.request.Request(BASIS + pfad, method=methode)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if rumpf is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(rumpf).encode()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = r.read()
            return r.status, (d if roh else json.loads(d.decode())), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode()), dict(e.headers)
        except Exception:  # noqa: BLE001
            return e.code, None, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}, {}


# ── VORGEFUNDENEN ZUSTAND MERKEN ────────────────────────────────────────────
from backend.skills.manager import SkillManager  # noqa: E402

sm = SkillManager()
_vor_states = config.get_skill_states()
VOR_SKILL = (_vor_states.get("feedback") or {}).get("enabled")
VOR_USERS = config.get_setting("ad_knowledge_editors", "")
VOR_GROUP = config.get_setting("ad_knowledge_editors_group", "")
print("vorgefunden: skill=%r users=%r group=%r" % (VOR_SKILL, VOR_USERS, VOR_GROUP))

TOKEN = M.generate_token("jarvis")
FREMD = M.generate_token("fremder.mensch")
angelegt = []



def _neustart_und_melden(sitzung, basis):
    """Den Dienst neu starten, damit sein RAM-Stand den Eintrag nicht zurueckschreibt.

    ⚠ GEMESSEN WIRD DER DIENST, NICHT DIE DATEI. `config.get_skill_states()` im
    Messprozess liest die gerade bereinigte Datei und meldet brav `None` –
    waehrend der laufende Dienst den Eintrag weiter im RAM haelt und beim
    naechsten Anlass zurueckschreibt (Register: ein Poll auf eine zweite Instanz
    derselben Datei misst nicht den Prozess, der schreibt).

    ⚠ ALS DIENSTBENUTZER SCHEITERT DER NEUSTART – das ist richtig so, und die
    Probe BEHAUPTET dann nichts, sondern sagt, was zurueckbleibt.
    """
    r = subprocess.run(["systemctl", "restart", "jarvis.service"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print("  ⚠ RUECKSTAND: der Dienst liess sich nicht neu starten (%s). "
              "Es bleibt ein Skill-Eintrag {'enabled': False} zurueck – "
              "vorgefunden war GAR KEINER. Wirkung ist dieselbe (Skill aus), "
              "der Zustand aber nicht identisch. Als root aufraeumen:\n"
              "    ./venv/bin/python -c \"from backend.config import config; "
              "config.remove_skill_state('feedback')\" "
              "&& systemctl restart jarvis.service"
              % (r.stderr or r.returncode).strip()[:80])
        return
    time.sleep(10)
    rest = None
    if sitzung is not None and basis:
        try:
            sk = sitzung.get(basis + "/api/skills", timeout=30).json()
            rest = [x for x in (sk.get("skills") or []) if x.get("name") == "feedback"]
        except Exception:                                           # noqa: BLE001
            rest = None
    print("  Dienst neu gestartet; Skill-Eintrag: %s"
          % ("weg" if config.get_skill_states().get("feedback") is None
             else "steht noch"))

def zurueck():
    """Den VORGEFUNDENEN Zustand herstellen – nicht einen geratenen."""
    for fid in angelegt:
        try:
            ruf("/api/feedback/admin/formulare/" + fid, TOKEN, "DELETE")
        except Exception:  # noqa: BLE001
            pass
    # ⚠ Die Abgaben ueberleben das Loeschen des Formulars (Zusage des Moduls) –
    # eine Messung muss sie deshalb GEZIELT entfernen.
    try:
        import pathlib as _pl
        _p = _pl.Path("/opt/jarvis/data/feedback_abgaben.jsonl")
        if _p.exists():
            _z = [z for z in _p.read_text(encoding="utf-8").splitlines() if z.strip()]
            _b = [z for z in _z if '"LIVE Testbogen"' not in z]
            if _b:
                _p.write_text("\n".join(_b) + "\n", encoding="utf-8")
            else:
                _p.unlink()
            print("Test-Abgaben entfernt: %d" % (len(_z) - len(_b)))
        _f = _pl.Path("/opt/jarvis/data/feedback_formulare.json")
        if _f.exists():
            import json as _j
            if not (_j.loads(_f.read_text(encoding="utf-8")).get("formulare") or []):
                _f.unlink()
    except Exception as _e:  # noqa: BLE001
        print("Aufraeumen unvollstaendig: %s" % _e)
    config.save_setting("ad_knowledge_editors", VOR_USERS)
    config.save_setting("ad_knowledge_editors_group", VOR_GROUP)
    if VOR_SKILL is True:
        sm.enable_skill("feedback")
    elif VOR_SKILL is False:
        sm.disable_skill("feedback")
    else:
        # ⚠ ES GAB GAR KEINEN EINTRAG – dann darf auch keiner zurueckbleiben.
        # (`remove_skill_state`, NICHT `save_skill_states` – die gibt es nicht;
        #  der erste Lauf ist genau daran abgestuerzt und liess den Zustand
        #  verstellt zurueck.)
        # Und das genuegt NICHT allein: der DIENST haelt die Skill-Zustaende im
        # RAM und schreibt sie beim naechsten Anlass zurueck – ohne Neustart
        # stand danach `{'enabled': False, …}` in der settings.json, obwohl
        # vorher gar kein Eintrag da war (gemessen 2026-09-14).
        if "feedback" in config.get_skill_states():
            config.remove_skill_state("feedback")
        _neustart_und_melden(None, None)
    print("\nFreigabe wiederhergestellt: users=%r group=%r"
          % (config.get_setting("ad_knowledge_editors", ""),
             config.get_setting("ad_knowledge_editors_group", "")))
    # ⚠ Ueber den Skill-Eintrag sagt diese Stelle bewusst NICHTS – den
    # kennt nur der DIENST; `_neustart_und_melden` berichtet ihn.


try:
    # ═══════════════════════════════════════════════════════════════════════
    print("\n1. Ohne Freigabe")
    # ═══════════════════════════════════════════════════════════════════════
    config.save_setting("ad_knowledge_editors", "")
    config.save_setting("ad_knowledge_editors_group", "")
    s, d, _ = ruf("/api/feedback/formulare", TOKEN)
    c("⚠ leere Freigabe: 403 auch fuer den lokalen Admin", s == 403, "ist %s" % s)
    s, d, _ = ruf("/api/feedback/formulare")
    c("ohne Token: 401", s == 401, "ist %s" % s)

    # Der Admin-Zweig haengt NICHT an der Bereichsfreigabe.
    s, d, _ = ruf("/api/feedback/admin/formulare", TOKEN)
    c("⚠ der Admin-Endpunkt geht trotzdem (kein Admin-Bypass noetig)",
      s == 200, "ist %s" % s)
    s, d, _ = ruf("/api/feedback/admin/formulare", FREMD)
    c("und ein Nicht-Admin kommt dort NICHT hinein", s == 403, "ist %s" % s)

    # ═══════════════════════════════════════════════════════════════════════
    print("\n2. Mit Freigabe und aktivem Skill")
    # ═══════════════════════════════════════════════════════════════════════
    config.save_setting("ad_knowledge_editors", "jarvis")
    # ⚠ UEBER DEN ECHTEN ENDPUNKT, nicht ueber den SkillManager im Messprozess:
    # der DIENST haelt seine Skill-Zustaende im eigenen Speicher – ein
    # `enable_skill()` hier draussen erreicht ihn nicht (Register: dieselbe
    # Klasse wie der Memory-Cache je Benutzer und der FAISS-Index im RAM).
    sx, sd, _ = ruf("/api/skills/feedback/enable", TOKEN, "POST", {})
    c("der Skill laesst sich ueber den Endpunkt einschalten",
      sx == 200, "%s %r" % (sx, sd))
    import time as _t
    _t.sleep(2)
    s, me, _ = ruf("/api/me", TOKEN)
    c("`permissions.feedback` ist wahr",
      s == 200 and (me.get("permissions") or {}).get("feedback") is True,
      "ist %r" % ((me or {}).get("permissions") or {}).get("feedback"))

    s, d, _ = ruf("/api/feedback/admin/formulare", TOKEN, "POST", {
        "titel": "LIVE Testbogen", "beschreibung": "nur fuer die Messung",
        "spalten": [{"name": "Modul", "typ": "text"},
                    {"name": "Note", "typ": "sterne"},
                    {"name": "Anmerkung", "typ": "text"}]})
    c("ein Formular laesst sich anlegen", s == 200 and d.get("ok"), "%s %r" % (s, d))
    F = (d or {}).get("formular") or {}
    if F.get("id"):
        angelegt.append(F["id"])
    SP = {x["name"]: x["id"] for x in F.get("spalten", [])}
    c("es hat drei Spalten", len(F.get("spalten", [])) == 3)

    s, d, _ = ruf("/api/feedback/formulare", TOKEN)
    c("der Benutzer sieht es", s == 200 and any(
        x["id"] == F.get("id") for x in (d.get("formulare") or [])))

    # ═══════════════════════════════════════════════════════════════════════
    print("\n3. Abgabe")
    # ═══════════════════════════════════════════════════════════════════════
    s, d, _ = ruf("/api/feedback/abgabe", TOKEN, "POST", {
        "formular_id": F.get("id"),
        "zeilen": [{SP.get("Modul"): "Rechnungswesen", SP.get("Note"): 4,
                    SP.get("Anmerkung"): "laeuft"},
                   {SP.get("Modul"): "=1+1", SP.get("Note"): "99",
                    "FREMD": "boese"}]})
    c("eine Abgabe wird angenommen", s == 200 and d.get("ok"), "%s %r" % (s, d))
    A = (d or {}).get("abgabe") or {}
    c("der Benutzer steht normiert darin", A.get("benutzer") == "jarvis")
    c("die Sterne sind begrenzt",
      (A.get("zeilen") or [{}, {}])[1].get(SP.get("Note")) == 5)
    c("die fremde Spalte ist verworfen",
      not any("FREMD" in z for z in (A.get("zeilen") or [])))
    c("⚠ die Spalten sind mitgespeichert", len(A.get("spalten") or []) == 3)

    s, d, _ = ruf("/api/feedback/abgabe", TOKEN, "POST", {
        "formular_id": F.get("id"), "zeilen": [],
        "user": "jemand.anders"})
    c("eine leere Abgabe wird mit 400 abgewiesen", s == 400, "ist %s" % s)

    # ⚠ Der Benutzer aus dem Rumpf darf NICHTS bewirken.
    s, d, _ = ruf("/api/feedback/abgabe", TOKEN, "POST", {
        "formular_id": F.get("id"), "user": "jemand.anders",
        "benutzer": "jemand.anders",
        "zeilen": [{SP.get("Modul"): "Probe"}]})
    c("⚠ ein `user` im Rumpf aendert nichts",
      s == 200 and ((d or {}).get("abgabe") or {}).get("benutzer") == "jarvis",
      "ist %r" % ((d or {}).get("abgabe") or {}).get("benutzer"))

    s, d, _ = ruf("/api/feedback/meine?fid=" + F.get("id", ""), TOKEN)
    c("die eigenen Abgaben kommen zurueck", s == 200 and len(d.get("abgaben") or []) == 2)
    s, d, _ = ruf("/api/feedback/admin/abgaben?fid=" + F.get("id", ""), TOKEN)
    c("und der Admin sieht sie auch", s == 200 and len(d.get("abgaben") or []) == 2)

    # ═══════════════════════════════════════════════════════════════════════
    print("\n4. CSV-Export")
    # ═══════════════════════════════════════════════════════════════════════
    s, roh, kopf = ruf("/api/feedback/admin/export?fid=" + F.get("id", ""),
                       TOKEN, roh=True)
    c("der Export antwortet mit 200", s == 200, "ist %s" % s)
    txt = roh.decode("utf-8") if isinstance(roh, bytes) else ""
    c("die Datei beginnt mit einem BOM", txt.startswith("﻿"))
    c("⚠ die Formel ist entschaerft", "'=1+1" in txt, txt[:200])
    c("Trennzeichen `;`", "Zeitpunkt;Benutzer;" in txt)
    cd = kopf.get("content-disposition") or kopf.get("Content-Disposition") or ""
    c("der Dateiname steht im Kopf", "filename" in cd.lower(), cd)
    s, d, _ = ruf("/api/feedback/admin/export", TOKEN)
    c("ohne `fid`: 400", s == 400, "ist %s" % s)
    s, d, _ = ruf("/api/feedback/admin/export?fid=" + F.get("id", ""), FREMD)
    c("und ein Nicht-Admin bekommt 403", s == 403, "ist %s" % s)

    # ═══════════════════════════════════════════════════════════════════════
    print("\n5. Loeschen und 404")
    # ═══════════════════════════════════════════════════════════════════════
    s, d, _ = ruf("/api/feedback/admin/formulare/gibtsnicht", TOKEN, "DELETE")
    c("unbekanntes Formular: 404", s == 404, "ist %s" % s)
    s, d, _ = ruf("/api/feedback/admin/abgaben/gibtsnicht", TOKEN, "DELETE")
    c("unbekannte Abgabe: 404", s == 404, "ist %s" % s)

    # ═══════════════════════════════════════════════════════════════════════
    print("\n6. Skill aus -> Kachel weg")
    # ═══════════════════════════════════════════════════════════════════════
    ruf("/api/skills/feedback/disable", TOKEN, "POST", {})
    import time as _t2
    _t2.sleep(2)
    s, me, _ = ruf("/api/me", TOKEN)
    c("⚠ ohne aktiven Skill ist `permissions.feedback` falsch",
      s == 200 and (me.get("permissions") or {}).get("feedback") is False,
      "ist %r" % ((me or {}).get("permissions") or {}).get("feedback"))
    # ⚠ `roh=True`: die Seite liefert HTML – ein JSON-Parser darauf ergibt
    # Status 0 und sieht wie ein Serverfehler aus (eigener Messfehler, 1. Lauf).
    s, _roh, _ = ruf("/feedback", TOKEN, roh=True)
    c("die Seite bleibt erreichbar (leere Huelle, JS leitet um)",
      s == 200, "ist %s" % s)

finally:
    zurueck()

print("\n" + "=" * 70)
print("\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)

#!/usr/bin/env python3
"""Live-Probe auf DEV: Ueberarbeiten-Modus und Netzfreigabe-Pfad.

Laeuft IM Produktiv-venv auf dem Server, gegen die ECHTE settings.json, den
echten Skill-Manager und – wenn Jira konfiguriert ist – gegen ein echtes Ticket
und das echte Modell. Ein Test mit Attrappen kann nicht belegen, dass die
Feldnamen zum Speicherweg der Oberflaeche passen.

Er raeumt hinter sich auf: die Skill-Konfiguration wird am Ende auf den Stand
von vorher zurueckgesetzt.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/opt/jarvis")

_ok = _fail = 0


def check(bed, text, extra=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (" – " + str(extra) if extra else ""))


from backend import jira_assist as ja           # noqa: E402
from backend.config import config               # noqa: E402

PFAD_C = r"\\hh-vm-dcapps.nexus.int\shares\Nexus_Digital_Pathology\Infrastruktur\KI-Taskforce\nexerius-jira-chrome"
PFAD_F = r"\\hh-vm-dcapps.nexus.int\shares\Nexus_Digital_Pathology\Infrastruktur\KI-Taskforce\nexerius-jira-firefox.zip"


def skill_cfg() -> dict:
    return dict((config.get_skill_states().get("jira") or {}).get("config") or {})


print("\n═══ 1) Netzfreigabe: gespeichert wie die Oberflaeche, gelesen wie der Endpunkt")
vorher = skill_cfg()
check(ja.paket_pfade() == {"chrome": "", "firefox": ""},
      "vor dem Eintrag sind beide Pfade leer (Download-Knopf)",
      str(ja.paket_pfade()))

# GENAU DER WEG DER OBERFLAECHE: nur die zwei eigenen Felder. Wenn der Merge
# nicht traegt, ist danach der Jira-Zugang weg – das ist der teure Fall.
from backend.skills.manager import SkillManager            # noqa: E402

sm = SkillManager()
sm.update_skill_config("jira", {"addon_pfad_chrome": PFAD_C,
                             "addon_pfad_firefox": PFAD_F})

nachher = skill_cfg()
p = ja.paket_pfade()
check(p["chrome"] == PFAD_C, "der Chrome-Ordner kommt zurueck", p["chrome"])
check(p["firefox"] == PFAD_F, "die Firefox-Datei ebenfalls", p["firefox"])
for feld in ("base_url", "api_token", "max_results"):
    if feld in vorher:
        check(nachher.get(feld) == vorher.get(feld),
              "der Merge laesst '%s' unangetastet" % feld,
              "vorher=%r nachher=%r" % (str(vorher.get(feld))[:12],
                                        str(nachher.get(feld))[:12]))

print("\n═══ 2) Der Endpunkt liefert die Pfade an die Anleitung")
# Nicht ueber HTTP (die Freigabeliste ist auf DEV leer, jeder bekaeme 403),
# sondern ueber genau den Ausdruck, den der Endpunkt einsetzt.
check("paket_pfade" in open("/opt/jarvis/backend/main.py", encoding="utf-8").read(),
      "main.py setzt paket_pfade in die Antwort")

print("\n═══ 3) Ueberarbeiten: leerer Entwurf kostet KEINEN Modellaufruf")
try:
    asyncio.run(ja.auswerten("ABC-1", "ueberarbeiten", "probe", "de", entwurf="  "))
    check(False, "leerer Entwurf wird abgewiesen")
except ja.AssistFehler as e:
    check("Kommentarfeld" in str(e), "leerer Entwurf wird abgewiesen", str(e)[:70])

print("\n═══ 4) Ende-zu-Ende gegen ein ECHTES Ticket und das echte Modell")
key = ""
try:
    from backend.jira_client import JiraClient             # noqa: E402
    c = JiraClient()
    if c.configured:
        tr = c.search("ORDER BY created DESC", limit=1) or {}
        issues = tr.get("issues") or []
        key = (issues[0] or {}).get("key", "") if issues else ""
except Exception as e:  # noqa: BLE001
    print("  ..   Jira nicht abfragbar: %s" % str(e)[:90])

if not key:
    print("  ..   kein Ticket ermittelbar – Abschnitt 4 uebersprungen")
else:
    entwurf = ("Hallo,\n\nwir habe das Problem angeschaut und melden uns "
               "spätestens morgen mit einer Loesung. Die Rechnug geht dann "
               "auch raus.\n\nMfg")
    try:
        r = asyncio.run(ja.auswerten(key, "ueberarbeiten", "probe", "de",
                                     entwurf=entwurf))
        # BEWUSST NUR KENNZAHLEN, KEINE INHALTE: hier laufen echte Kundendaten.
        check(r["ok"] is True, "der Lauf ist durch")
        check(r["key"] == key, "er gehoert zum abgefragten Ticket (%s)" % key)
        check(len(r["text"]) > 20, "es kam eine Fassung zurueck (%d Zeichen)"
              % len(r["text"]))
        check(ja.ABGLEICH_MARKE not in r["text"],
              "der Abgleich-Marker steht NICHT im Antworttext")
        # Die Rechtschreibfehler des Entwurfs sollen weg sein – das ist der
        # eigentliche Zweck des Knopfes.
        for fehler in ("habe das Problem", "Rechnug"):
            check(fehler not in r["text"], "korrigiert: %r ist weg" % fehler)
        print("  ..   Kommentare ausgewertet: %d | Modell: %s | Hinweis: %s"
              % (r["kommentare"], r["modell"],
                 "ja (%d Zeichen)" % len(r["hinweis"]) if r["hinweis"] else "nein"))
    except Exception as e:  # noqa: BLE001
        check(False, "Ende-zu-Ende-Lauf", str(e)[:160])

print("\n═══ 5) Aufraeumen")
try:
    sm.update_skill_config("jira", {
        "addon_pfad_chrome": vorher.get("addon_pfad_chrome", ""),
        "addon_pfad_firefox": vorher.get("addon_pfad_firefox", "")})
    check(ja.paket_pfade()["chrome"] == vorher.get("addon_pfad_chrome", ""),
          "der Ausgangszustand ist wiederhergestellt")
except Exception as e:  # noqa: BLE001
    check(False, "Aufraeumen", str(e)[:120])

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)

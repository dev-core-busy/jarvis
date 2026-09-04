#!/usr/bin/env python3
"""Waechter: sagt "Freigabe verbinden" im Fehlerfall, WAS los ist?

GEMELDET AM 2026-09-04: "Einstellungen -> Wissen -> Netzwerk-Freigaben -> Klick
auf 'verbinden' liefert keine Informationen, wenn etwas nicht klappt."

Zutreffend, und es waren ZWEI Fehler uebereinander:
  1. Die Meldung stand rund 190 Markup-Zeilen ueber der Freigabenliste
     (#kb-notification in settings.html bei 2076, die Liste bei 2270) und war
     nach 3,5 s wieder weg – ausserhalb des Sichtfensters passiert damit fuer
     den Benutzer NICHTS. (Frontend-Teil: tests/test_mount_meldung_ui.js)
  2. Der Text selbst: `mount error(13): Permission denied` ist richtig und
     trotzdem nutzlos. HIER wird geprueft, dass die Deutung dazukommt – und
     dass sie den Rohtext NIE ersetzt.

Die geprueften Funktionen werden per ``ast`` geschnitten und WIRKLICH
ausgefuehrt: eine Quelltext-Suche bliebe gruen, sobald jemand den Zweig
spaeter ueberspringt.
"""

import ast
import re
import sys
from pathlib import Path

WURZEL = Path(__file__).parent.parent
OK = FAIL = 0


def check(text, bedingung, detail=""):
    global OK, FAIL
    if not isinstance(text, str) or isinstance(bedingung, str):
        print(f"\033[31mABBRUCH: check(...) vertauscht: {text!r}\033[0m")
        sys.exit(2)
    if bedingung:
        OK += 1
        print(f"  \033[32m✓\033[0m {text}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {text}" + (f"  → {detail}" if detail else ""))


def schneide(quelle, name):
    """Genau diese Funktion aus main.py – kein Fenster, kein Textschnitt."""
    baum = ast.parse(quelle)
    for k in baum.body:
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return ast.get_source_segment(quelle, k) or ""
    return ""


HAUPT = (WURZEL / "backend" / "main.py").read_text()

print("\n\033[1m1. Die Deutung wird AUSGEFUEHRT\033[0m")

code = schneide(HAUPT, "_mount_fehler_deuten")
check("Positivkontrolle: die Funktion wurde geschnitten",
      len(code) > 300 and code.count("def _mount_fehler_deuten") == 1, f"{len(code)} Zeichen")
if not code:
    print("\033[31mABBRUCH: _mount_fehler_deuten gibt es nicht (umbenannt?)\033[0m")
    sys.exit(2)

ns = {"re": re}
exec(compile(code, "<schnitt>", "exec"), ns)
deute = ns["_mount_fehler_deuten"]

faelle = [
    # (Beschreibung, result, typ, quelle, MUSS enthalten)
    ("falsches Kennwort wird gedeutet",
     {"ok": False, "rc": 32, "stderr": "mount error(13): Permission denied"},
     "smb", "//srv/freigabe", ["Kennwort"]),
    ("unbekannter Freigabename wird gedeutet",
     {"ok": False, "rc": 32, "stderr": "mount error(2): No such file or directory"},
     "smb", "//srv/tippfehler", ["Freigabenamen"]),
    ("nicht erreichbarer Server wird gedeutet",
     {"ok": False, "rc": 32, "stderr": "mount error: could not resolve address / Host is down"},
     "smb", "//srv/x", ["nicht erreichbar"]),
    ("fehlendes Systempaket wird beim NAMEN genannt",
     {"ok": False, "rc": 32, "stderr": "mount: /mnt/kb_0: unknown filesystem type 'cifs'."},
     "smb", "//srv/x", ["cifs-utils"]),
    ("davfs2 bei WebDAV",
     {"ok": False, "rc": 32, "stderr": "unknown filesystem type 'davfs'"},
     "webdav", "https://srv/dav", ["davfs2"]),
    ("Zeitueberschreitung nennt die Erreichbarkeit",
     {"ok": False, "rc": -1, "stderr": "Command '['mount', ...]' timed out after 20 seconds"},
     "smb", "//srv/x", ["erreichbar"]),
    # ── LIVE GEMESSEN auf DEV (util-linux 2.40 / Debian 13, 2026-09-04) ──
    # Die aus der Literatur bekannten "mount error(13)"-Texte kommen dort GAR
    # NICHT vor; aktuelle mount-Fassungen melden "fsconfig() failed: <errno>".
    # Ohne diese Faelle deutet die Funktion auf einem heutigen Server nichts.
    ("ECHT: nicht erreichbarer SMB-Server (fsconfig/EINPROGRESS)",
     {"ok": False, "rc": 32, "stderr": "mount: /mnt/kb_0: fsconfig() failed: "
      "Operation now in progress.\n       dmesg(1) may have more information "
      "after failed mount system call.\n"},
     "smb", "//192.0.2.77/freigabe", ["nicht erreichbar"]),
    ("ECHT: falsche Schreibweise der SMB-Quelle (Malformed UNC)",
     {"ok": False, "rc": 32, "stderr": "mount: /mnt/kb_0: fsconfig() failed: "
      "Malformed UNC in devname\n.\n       dmesg(1) may have more information "
      "after failed mount system call.\n"},
     "smb", "kein-pfad", ["//server/freigabe"]),
    ("ECHT: dieselbe NFS-Meldung bei RICHTIGER Quelle = fehlendes Paket",
     {"ok": False, "rc": 32, "stderr": "mount: /mnt/kb_0: fsconfig() failed: "
      "NFS: mount program didn't pass remote address.\n"},
     "nfs", "192.0.2.77:/export", ["nfs-common"]),
    ("ECHT: NFS-Quelle ohne Server-Teil",
     {"ok": False, "rc": 32, "stderr": "mount: /mnt/kb_0: fsconfig() failed: "
      "NFS: mount program didn't pass remote address.\n"},
     "nfs", "export", ["server:/export"]),
    ("ECHT: die deutsche Fassung derselben Meldung wird auch erkannt",
     {"ok": False, "rc": 32, "stderr": "mount: /mnt/kb_0: fsconfig() failed: "
      "Die Operation ist jetzt in Bearbeitung."},
     "smb", "//192.0.2.77/x", ["nicht erreichbar"]),
    ("ausstehende Root-Freigabe wird benannt",
     {"ok": False, "decision": "pending", "rc": None, "stderr": ""},
     "smb", "//srv/x", ["Root-Freigaben"]),
    ("gesperrte Op wird benannt",
     {"ok": False, "decision": "denied", "rc": None, "stderr": ""},
     "smb", "//srv/x", ["gesperrt"]),
]
for name, res, typ, quelle, muss in faelle:
    try:
        t = deute(res, typ, quelle)
    except Exception as e:  # noqa: BLE001
        t = f"__FEHLER__ {type(e).__name__}: {e}"
    check(name, all(m.lower() in t.lower() for m in muss), t[:160])

# DIE REGEL: die Deutung ERGAENZT, sie ersetzt nie. Sonst ist der naechste,
# unbekannte Fall unauffindbar.
roh = "mount error(13): Permission denied"
t = deute({"ok": False, "rc": 32, "stderr": roh}, "smb", "//srv/x")
check("⚠ der Rohtext bleibt erhalten (die Deutung ergaenzt nur)", roh in t, t[:160])

# Reihenfolge: erst was zu tun ist, dann die Systemmeldung. Ein Administrator
# soll nicht erst durch "fsconfig() failed" lesen muessen.
t2 = deute({"ok": False, "rc": 32, "stderr": "mount: /mnt/x: fsconfig() failed: "
            "Malformed UNC in devname\n.\n       dmesg(1) may have more "
            "information after failed mount system call.\n"}, "smb", "srv")
check("⚠ die Deutung steht VOR der Systemmeldung",
      t2.index("//server/freigabe") < t2.index("fsconfig"), t2[:200])
check("der dmesg-Hinweis ist raus (in einer Weboberflaeche nutzlos)",
      "dmesg" not in t2, t2[:200])
check("… und die Meldung ist einzeilig (Toast-tauglich)", "\n" not in t2, repr(t2)[:160])

# Der schlimmste Fall: gar keine Ausgabe. Frueher stand dann "Mount
# fehlgeschlagen:" und dahinter nichts – genau die gemeldete Nicht-Information.
t = deute({"ok": False, "rc": 32, "stderr": "", "error": ""}, "smb", "//srv/x")
check("⚠ ohne jede Ausgabe entsteht KEINE leere Meldung",
      len(t.strip()) > 30 and "32" in t, repr(t))
check("und sie nennt den Ort der Einzelheiten (Journal)", "journalctl" in t.lower(), t[:160])

t = deute({"ok": False, "rc": None}, "smb", "//srv/x")
check("auch ohne rc und ohne Text kommt eine verwertbare Meldung",
      len(t.strip()) > 10, repr(t))


print("\n\033[1m2. Der Endpunkt benutzt die Deutung – und protokolliert sie\033[0m")

mount_code = schneide(HAUPT, "mount_share")
check("Positivkontrolle: der Endpunkt wurde geschnitten",
      len(mount_code) > 300 and "broker_client.call" in mount_code, f"{len(mount_code)} Zeichen")
check("der Fehlerzweig deutet, statt stderr roh durchzureichen",
      "_mount_fehler_deuten(" in mount_code, mount_code[:200])
check("und er schreibt den Fehler ins Journal",
      "Mount fehlgeschlagen" in mount_code and "flush=True" in mount_code)
un_code = schneide(HAUPT, "unmount_share")
check("das Trennen deutet ebenfalls", "_mount_fehler_deuten(" in un_code)

# Der NameError, der bei JEDEM erfolgreichen Mount einen Fehler meldete, den es
# nicht gab: `source` gibt es in dieser Funktion nicht.
baum = ast.parse(mount_code)
namen = {n.id for n in ast.walk(baum) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
zuweisungen = {t.id for n in ast.walk(baum) if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name)}
check("⚠ kein Zugriff auf ein nicht zugewiesenes 'source' (NameError im Erfolgsfall)",
      "source" not in (namen - zuweisungen), str(sorted(namen - zuweisungen))[:200])


print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
if FAIL:
    print(f"\033[31m{FAIL} Pruefung(en) fehlgeschlagen\033[0m")
sys.exit(1 if FAIL else 0)

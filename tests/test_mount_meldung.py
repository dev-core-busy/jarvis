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


def sicher(fn, *a, **k):
    """Nie ungeprueft aufrufen: eine Pruefung, die WIRFT, bricht den Lauf ab –
    und ein abgebrochener Waechter ist von einem bestandenen nicht zu
    unterscheiden (Register). Genau so passiert, als Abschnitt 5 dazukam."""
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return f"__FEHLER__ {type(e).__name__}: {e}"


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
    # ⚠ DER KERNEL-CODE IST DIE GENAUESTE AUSKUNFT und gewinnt gegen die
    # generischen Muster: "Operation now in progress" sagt gar nichts, waehrend
    # "-13" eindeutig das Kennwort meint. Live auf DEV gemessen (2026-09-04):
    # ohne diese Zeilen ist ein SMB-Fehler von aussen nicht deutbar – und die
    # Deutung lag prompt daneben (Ping 0,2 ms und Port 445 offen, trotzdem
    # "Server nicht erreichbar").
    ("Kernel -13 = Kennwort/Berechtigung",
     {"ok": False, "rc": 32, "stderr": "mount: /mnt/kb_0: fsconfig() failed: "
      "Operation now in progress. [Kernel: CIFS: VFS: cifs_mount failed "
      "w/return code = -13]"},
     "smb", "//srv/x", ["Kennwort"]),
    ("Kernel -2 = Freigabe gibt es nicht",
     {"ok": False, "rc": 32, "stderr": "[Kernel: cifs_mount failed w/return code = -2]"},
     "smb", "//srv/tippfehler", ["gibt es auf dem Server nicht"]),
    ("Kernel -115 = Verbindung kam nicht zustande, Rechner antwortet aber",
     {"ok": False, "rc": 32, "stderr": "mount: /mnt/kb_0: fsconfig() failed: "
      "Operation now in progress. [Kernel: CIFS: VFS: Error connecting to "
      "socket. Aborting operation. | cifs_mount failed w/return code = -115]"},
     "smb", "//191.100.147.90/knowledgebase_an_rag", ["SMB-Version"]),
    ("Kernel -95 = SMB-Version",
     {"ok": False, "rc": 32, "stderr": "[Kernel: cifs_mount failed w/return code = -95]"},
     "smb", "//srv/x", ["vers="]),
    ("⚠ der Kernel-Code STICHT das generische Muster",
     {"ok": False, "rc": 32, "stderr": "mount error: Host is down [Kernel: "
      "cifs_mount failed w/return code = -13]"},
     "smb", "//srv/x", ["Kennwort"]),
    ("ein unbekannter Kernel-Code wird beim NAMEN genannt",
     {"ok": False, "rc": 32, "stderr": "[Kernel: cifs_mount failed w/return code = -524]"},
     "smb", "//srv/x", ["-524"]),
    ("'Error connecting to socket' ohne Code nennt Port 445",
     {"ok": False, "rc": 32, "stderr": "CIFS: VFS: Error connecting to socket."},
     "smb", "//srv/x", ["445"]),
    # ⚠ GEMELDET 2026-09-04: derselbe Errno-Text, aber das Ziel ist ein PFAD –
    # dann ist nicht der Server das Hindernis, sondern ein abgestorbener Mount.
    ("ECHT: Host is down mit PFAD = toter Mount, nicht toter Server",
     {"ok": False, "rc": -1, "stderr": "Broker-Op-Fehler: [Errno 112] Host is "
      "down: '/mnt/jarvis-kb/share_1'"},
     "smb", "//191.100.147.90/knowledgebase_an_rag", ["abgestorbener", "Mount"]),
    ("… waehrend derselbe Text OHNE Pfad weiter auf den Server zeigt",
     {"ok": False, "rc": 32, "stderr": "mount error: Host is down"},
     "smb", "//srv/x", ["nicht erreichbar"]),
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
# ⚠ EINE MELDUNG DARF SICH NICHT SELBST WIDERSPRECHEN. Live gemessen stand
# "Der Server hat nicht geantwortet" neben "obwohl der Rechner antwortet".
t_k = deute({"ok": False, "rc": 32, "stderr": "mount: /mnt/x: fsconfig() failed: "
             "Operation now in progress. dmesg(1) may have more information "
             "after failed mount system call. [Kernel: CIFS: VFS: Error "
             "connecting to socket. | cifs_mount failed w/return code = -115]"},
            "smb", "//srv/x")
check("⚠ der Kernel-Code sticht das generische 'nicht erreichbar'",
      "nicht erreichbar" not in t_k and "SMB-Version" in t_k, t_k[:220])
check("… und der Kernel-Teil bleibt in der Systemmeldung erhalten",
      "-115" in t_k, t_k[:220])
check("… waehrend der dmesg-Hinweis draussen bleibt", "dmesg" not in t_k, t_k[:220])

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
# Ein Eingabefehler ist kein Serverfehler: eine unbrauchbare Quelle muss 400
# ergeben, nicht 500 – sonst steht in jedem Monitoring ein Serverfehler, wo
# jemand einen Schraegstrich vergessen hat.
check("⚠ eine unbrauchbare Quelle beim Verbinden ergibt 400, nicht 500",
      "status_code=400" in mount_code and "mount_quelle" in mount_code,
      mount_code[mount_code.find("_mount_fehler_deuten"):][:300])

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


print("\n\033[1m3. Eine falsch geschriebene Quelle wird beim EINGEBEN abgefangen\033[0m")
#
# VORGABE DES BETREIBERS (2026-09-04): "wenn im 'SMB/CIFS' Fall ein falsch
# formatierter Pfad versucht wird einzugeben, muss das abgefangen werden."
# Vorher nahm der Endpunkt JEDE nicht leere Zeichenkette an – der Fehler fiel
# erst beim Klick auf "Verbinden" auf, nach bis zu 10 s Netz-Timeout.

sys.path.insert(0, str(WURZEL))
from backend import mount_quelle as MQ   # noqa: E402

# Was ABGEWIESEN werden muss – jeweils mit einem Wort, das im Fehlertext
# stehen MUSS, damit die Meldung den naechsten Schritt nennt.
schlecht = [
    ("smb", "srv/freigabe",        "//srv/freigabe"),   # die zwei Slashes fehlen
    ("smb", "kein-pfad",           "//server/freigabe"),
    ("smb", "//srv",               "freigabe"),         # Freigabename fehlt
    ("smb", "//srv/",              "freigabe"),
    ("smb", "C:\\daten\\x",        "lokaler Pfad"),
    ("smb", "/mnt/daten",          "lokaler Pfad"),
    ("smb", "",                    "//server/freigabe"),
    ("smb", "//sr v/freigabe",     "Servername"),
    ("smb", "//srv/frei\ngabe",    "Steuerzeichen"),
    ("nfs", "export",              "server:/export"),
    ("nfs", "/export",             "lokaler Pfad"),
    ("nfs", "srv:export",          "absoluter Pfad"),
    ("webdav", "srv/dav",          "https://server/pfad"),
    ("blubb", "//srv/x",           "Freigabetyp"),
]
for typ, quelle, muss in schlecht:
    norm, fehler = MQ.pruefe(typ, quelle)
    check(f"abgewiesen: {typ} {quelle!r}",
          bool(fehler) and not norm and muss.lower() in fehler.lower(),
          f"norm={norm!r} fehler={fehler!r}")

# Was ANGENOMMEN werden muss – und worauf es normalisiert wird. Ein
# Administrator kennt //server/freigabe aus Linux, \\server\freigabe aus
# Windows und smb://server/freigabe aus dem Dateimanager. Alle drei MEINEN
# dieselbe Freigabe; das abzulehnen waere Schikane.
gut = [
    ("smb", "//srv/freigabe",             "//srv/freigabe"),
    ("smb", "\\\\srv\\freigabe",             "//srv/freigabe"),
    ("smb", "smb://srv/freigabe",         "//srv/freigabe"),
    ("smb", "cifs://srv/freigabe",        "//srv/freigabe"),
    ("smb", "  //srv/freigabe/  ",        "//srv/freigabe"),
    ("smb", "///srv/freigabe",            "//srv/freigabe"),
    ("smb", "//srv.firma.de/Abt Technik", "//srv.firma.de/Abt Technik"),
    ("smb", "//192.0.2.7/daten/unter",    "//192.0.2.7/daten/unter"),
    ("nfs", "srv:/export",                "srv:/export"),
    ("nfs", "nfs://srv/export",           "srv:/export"),
    ("webdav", "https://srv/dav/",        "https://srv/dav"),
    ("webdav", "davs://srv/dav",          "https://srv/dav"),
]
for typ, quelle, erwartet in gut:
    norm, fehler = MQ.pruefe(typ, quelle)
    check(f"angenommen: {typ} {quelle!r} -> {erwartet!r}",
          not fehler and norm == erwartet, f"norm={norm!r} fehler={fehler!r}")

# Ein Leerzeichen im Freigabenamen ist in Windows-Netzen der Normalfall – wer
# es verbietet, sperrt die Haelfte der Freigaben aus.
check("Leerzeichen im Freigabenamen bleiben erhalten",
      MQ.pruefe("smb", "//srv/Abt Technik")[0] == "//srv/Abt Technik")

print("\n\033[1m4. Die Schranke sitzt an ALLEN Eingaengen\033[0m")

for name in ("add_mount", "update_mount"):
    code_ep = schneide(HAUPT, name)
    check(f"{name}: prueft die Quelle ueber mount_quelle",
          "mount_quelle.pruefe(" in code_ep, code_ep[:160])
    # Die Pruefung muss VOR dem Speichern stehen – sonst landet die kaputte
    # Quelle im Bestand und wird erst danach beanstandet.
    i_pruef = code_ep.find("mount_quelle.pruefe(")
    i_save = code_ep.find("_save_mounts_config(")
    check(f"{name}: und zwar VOR dem Speichern",
          i_pruef >= 0 and i_save > i_pruef, f"{i_pruef} / {i_save}")

# ⚠ VON DER LIVE-PROBE GEFUNDEN (2026-09-04, DEV): das Anlegen einer Freigabe
# endete im getrennten Betrieb mit nacktem HTTP 500. Das unprivilegierte
# Backend machte mkdir auf /mnt/... (gehoert root) – und weil der Eintrag zwei
# Zeilen darueber SCHON gespeichert war, blieb eine halb angelegte Freigabe
# zurueck, deren Ordner nie in der Wissensliste landete. Im echten Bestand
# gemessen: drei Freigaben, keine einzige in `folders`.
add_code = schneide(HAUPT, "add_mount")
baum_add = ast.parse(add_code)
mkdir_geschuetzt = False
for k in ast.walk(baum_add):
    if isinstance(k, ast.Try):
        quelle_try = ast.get_source_segment(add_code, k) or ""
        if ".mkdir(" in quelle_try:
            mkdir_geschuetzt = True
check("⚠ das mkdir des Einhaengepunkts ist abgesichert (kein HTTP 500)",
      mkdir_geschuetzt or ".mkdir(" not in add_code, add_code[:120])
i_mkdir = add_code.find(".mkdir(")
i_folders = add_code.find("_kb_ordner_sicherstellen(")
check("… und die Ordner-Eintragung folgt DANACH (sie darf nicht mitausfallen)",
      i_folders > i_mkdir >= 0, f"{i_mkdir} / {i_folders}")

ops_quelle = (WURZEL / "backend" / "broker" / "ops.py").read_text()
op_code = ""
for k in ast.parse(ops_quelle).body:
    if isinstance(k, ast.FunctionDef) and k.name == "_op_mount_share":
        op_code = ast.get_source_segment(ops_quelle, k) or ""
check("Positivkontrolle: die Broker-Op wurde geschnitten", len(op_code) > 200)
check("auch der Broker prueft die Form (Tiefenverteidigung)",
      "mount_quelle" in op_code and "pruefe(" in op_code, op_code[:200])
check("… und benutzt die NORMALISIERTE Quelle fuer den mount-Aufruf",
      "source = norm" in op_code, op_code[:200])
# Der gemeldete Fall: ein abgestorbener Mount blockiert jeden neuen Versuch.
check("⚠ ein belegter Einhaengepunkt wird VOR dem mkdir geloest",
      "_mp_freimachen(" in op_code
      and op_code.find("_mp_freimachen(") < op_code.find(".mkdir("),
      op_code[:200])
mkdir_try = any(isinstance(k, ast.Try) and ".mkdir(" in (ast.get_source_segment(op_code, k) or "")
                for k in ast.walk(ast.parse(op_code)))
check("… und das mkdir selbst wirft keinen Broker-Op-Fehler mehr", mkdir_try)
check("der Hinweis auf den geloesten Mount landet im Ergebnis",
      "vorlauf" in op_code and 'erg["stderr"]' in op_code)
frei_code = ""
for k in ast.parse(ops_quelle).body:
    if isinstance(k, ast.FunctionDef) and k.name in ("_mp_freimachen", "_ist_eingehaengt"):
        frei_code += (ast.get_source_segment(ops_quelle, k) or "") + "\n"
check("Positivkontrolle: die Helfer wurden geschnitten", len(frei_code) > 300)
kern_code = ""
for k in ast.parse(ops_quelle).body:
    if isinstance(k, ast.FunctionDef) and k.name == "_kernel_grund":
        kern_code = ast.get_source_segment(ops_quelle, k) or ""
check("Positivkontrolle: _kernel_grund wurde geschnitten", len(kern_code) > 200)
check("⚠ der Broker holt den Kernel-Grund aus dmesg (nur root kann das)",
      "dmesg" in kern_code and "CIFS" in kern_code, kern_code[:160])
check("… und nur Zeilen DIESES Versuchs (der Ring reicht Tage zurueck)",
      "seit" in kern_code and "fromisoformat" in kern_code)
check("der mount-Zweig haengt den Kernel-Grund an einen Fehlschlag an",
      "_kernel_grund(" in op_code and "[Kernel:" in op_code, op_code[-400:])
check("… und NUR an einen Fehlschlag (ein Erfolg braucht keine dmesg-Zeile)",
      'if not erg.get("ok")' in op_code)

check("⚠ die Lage wird ueber /proc/mounts festgestellt, NICHT per stat",
      "/proc/mounts" in frei_code and ".is_mount()" not in frei_code, frei_code[:160])
check("… und ein toter Mount wird per lazy umount geloest",
      '"-l"' in frei_code or "'-l'" in frei_code, frei_code[:200])

# Drift-Schranke: die Beispiele stehen im Backend UND im Formular.
kjs = (WURZEL / "frontend" / "js" / "knowledge.js").read_text()
import re as _re
block = kjs[kjs.find("JarvisKnowledgeManager.MOUNT_BEISPIEL = {"):]
block = block[:block.find("};") + 2]
check("Positivkontrolle: der Beispiel-Block wurde gefunden", len(block) > 40, block[:80])
for typ, bsp in MQ.BEISPIEL.items():
    check(f"Beispiel im Formular deckt sich mit dem Backend ({typ})",
          f"'{bsp}'" in block, block)

# Der Platzhalter darf nicht per data-i18n-placeholder gesetzt werden: applyLang()
# wuerde den typabhaengigen Wert bei jedem Sprachwechsel ueberschreiben.
shtml = (WURZEL / "frontend" / "settings.html").read_text()
zeile = [z for z in shtml.splitlines() if 'id="kb-mount-source"' in z]
check("Positivkontrolle: das Quellfeld wurde gefunden", len(zeile) == 1, str(zeile))
check("⚠ der Platzhalter haengt am TYP, nicht an der Sprache",
      bool(zeile) and "data-i18n-placeholder" not in zeile[0], zeile[0] if zeile else "")


print("\n\033[1m6. Der Einhaengepunkt haengt NICHT am Listenindex\033[0m")
#
# ⚠ EIN FEHLER MIT DATENFOLGE: bis 2026-09-04 hiess der Einhaengepunkt
# share_<idx>, und remove_mount macht mounts.pop(idx). Wer eine Freigabe aus
# der MITTE loescht, verschob damit alle nachfolgenden: die Wissens-Ordnerliste
# zeigte auf den Punkt der NACHBARfreigabe, der Status meldete "nicht
# verbunden", obwohl die Freigabe noch hing, und ein Klick auf "Verbinden"
# mountete dieselbe Quelle ein zweites Mal.

_ns = {"Path": Path, "_MOUNT_BASE": Path("/mnt/jarvis-kb")}
for _fn in ("_mount_path", "_freier_mountpunkt", "_mounts_migrieren"):
    _code = schneide(HAUPT, _fn)
    if not _code:
        print(f"\033[31mABBRUCH: {_fn} gibt es nicht (umbenannt?)\033[0m")
        sys.exit(2)
    exec(compile(_code, "<schnitt>", "exec"), _ns)
mp_fn, frei_fn, migr_fn = _ns["_mount_path"], _ns["_freier_mountpunkt"], _ns["_mounts_migrieren"]

check("Positivkontrolle: die drei Helfer wurden geschnitten und laufen",
      str(sicher(mp_fn, 3)) == "/mnt/jarvis-kb/share_3", str(sicher(mp_fn, 3)))

# Der gespeicherte Pfad gewinnt gegen den Index – das IST der Fix.
m1 = {"source": "//a/b", "mountpoint": "/mnt/jarvis-kb/share_7"}
check("⚠ der gespeicherte Einhaengepunkt gewinnt gegen den Index",
      str(sicher(mp_fn, 0, m1)) == "/mnt/jarvis-kb/share_7", str(sicher(mp_fn, 0, m1)))

# Fremdeingabe: der Wert landet als Argument in einer ROOT-Operation.
for boese in ("/etc", "/mnt/jarvis-kb/../../etc", "relativ", "", "/mnt/jarvis-kb"):
    got = str(sicher(mp_fn, 5, {"mountpoint": boese}))
    check(f"abgewiesen und auf den Index zurueckgefallen: {boese!r}",
          got == "/mnt/jarvis-kb/share_5", got)

# DIE EIGENSCHAFT: Loeschen aus der Mitte verschiebt nichts.
bestand = [{"source": "//a/1", "mountpoint": "/mnt/jarvis-kb/share_0"},
           {"source": "//a/2", "mountpoint": "/mnt/jarvis-kb/share_1"},
           {"source": "//a/3", "mountpoint": "/mnt/jarvis-kb/share_2"}]
vorher = {m["source"]: str(mp_fn(i, m)) for i, m in enumerate(bestand)}
bestand.pop(0)                     # die erste Freigabe loeschen
nachher = {m["source"]: str(mp_fn(i, m)) for i, m in enumerate(bestand)}
check("⚠ nach dem Loeschen der ERSTEN Freigabe behalten die uebrigen ihren Pfad",
      all(nachher[k] == vorher[k] for k in nachher), f"{vorher} -> {nachher}")
# Gegenprobe der Messung: ohne gespeicherten Pfad WUERDE es sich verschieben.
ohne = [{"source": "//a/2"}, {"source": "//a/3"}]
check("Positivkontrolle: ohne gespeicherten Pfad verschiebt es sich sehr wohl",
      str(mp_fn(0, ohne[0])) == "/mnt/jarvis-kb/share_0", str(mp_fn(0, ohne[0])))

# Migration: der HEUTIGE Index wird festgeschrieben – nur so bleiben laufende
# Mounts und die vorhandene folders-Liste gueltig.
alt_best = [{"source": "//a/1"}, {"source": "//a/2"}]
check("Migration schreibt und meldet das", migr_fn(alt_best) is True)
check("… und zwar mit dem HEUTIGEN Index (laufende Mounts bleiben gueltig)",
      [m["mountpoint"] for m in alt_best]
      == ["/mnt/jarvis-kb/share_0", "/mnt/jarvis-kb/share_1"],
      str(alt_best))
check("… idempotent (ein zweiter Lauf schreibt nicht)", migr_fn(alt_best) is False)

# Freie Vergabe: share_<len> waere nach einem Loeschen womoeglich belegt.
belegt = [{"source": "//a/x", "mountpoint": "/mnt/jarvis-kb/share_0"},
          {"source": "//a/y", "mountpoint": "/mnt/jarvis-kb/share_2"}]
frei = str(sicher(frei_fn, belegt))
check("⚠ ein neuer Punkt kollidiert nicht mit einem vorhandenen",
      frei not in ("/mnt/jarvis-kb/share_0", "/mnt/jarvis-kb/share_2")
      and frei.startswith("/mnt/jarvis-kb/share_"), frei)
def _belegt_auf_platte():
    try:
        with open("/proc/mounts") as f:
            return {z.split(" ")[1] for z in f if len(z.split(" ")) > 1
                    and z.split(" ")[1].startswith("/mnt/jarvis-kb")}
    except OSError:
        return set()


_weg = {"/mnt/jarvis-kb/share_0", "/mnt/jarvis-kb/share_2"} | _belegt_auf_platte()
_erwartet = next(f"/mnt/jarvis-kb/share_{n}" for n in range(1000)
                 if f"/mnt/jarvis-kb/share_{n}" not in _weg)
check("… und nimmt die kleinste freie Nummer", frei == _erwartet,
      f"{frei} statt {_erwartet} (belegt: {sorted(_weg)})")

# REGEL statt Liste: jede Aufrufstelle muss den Eintrag mitgeben – damit faellt
# auch ein KUENFTIGER Aufrufer auf, ohne dass jemand eine Liste pflegt.
import re as _re2
haupt_ohne = ohne_kommentare_py(HAUPT) if False else HAUPT
roh_ohne = _re2.sub(r"#[^\n]*", "", haupt_ohne)
nackt = _re2.findall(r"_mount_path\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", roh_ohne)
check("⚠ REGEL: kein _mount_path()-Aufruf ohne den Eintrag",
      not nackt, f"ohne Eintrag aufgerufen: {nackt}")
check("Positivkontrolle: es gibt ueberhaupt Aufrufstellen",
      len(_re2.findall(r"_mount_path\(", roh_ohne)) >= 6,
      str(len(_re2.findall(r"_mount_path\(", roh_ohne))))
# Beim Bearbeiten darf der Punkt nicht neu vergeben werden (folders!).
up_code = schneide(HAUPT, "update_mount")
check("das Bearbeiten UEBERNIMMT den Einhaengepunkt",
      '"mountpoint": str(mp)' in up_code and "_freier_mountpunkt" not in up_code,
      up_code[-300:])
# Die Migration muss VERDRAHTET sein – die Funktion allein nuetzt nichts, und
# sie gehoert in _get_mounts_config (nicht in einen Startup-Hook): nur so greift
# sie auch im Autostart-Pfad und bei jeder kuenftigen Aufrufstelle.
get_code = schneide(HAUPT, "_get_mounts_config")
check("Positivkontrolle: _get_mounts_config wurde geschnitten",
      len(get_code) > 100 and "mounts" in get_code)
check("⚠ die Migration ist verdrahtet (nicht nur vorhanden)",
      "_mounts_migrieren(" in get_code, get_code[:200])
check("… und das Ergebnis wird gespeichert",
      "_save_mounts_config(" in get_code, get_code[:300])
check("… ohne dass ein Fehler dabei die Liste verschluckt",
      "except" in get_code and "return mounts" in get_code, get_code[-200:])

# ⚠ EINE GEMOUNTETE FREIGABE, DIE NICHT IN `folders` STEHT, WIRD NICHT
# INDIZIERT – sie liegt da und niemand findet ihren Inhalt. Genau so auf DEV
# vorgefunden (zwei verbundene Freigaben, keine davon in der Liste): der
# HTTP 500 beim Anlegen brach VOR der Pflege der Liste ab.
ord_code = schneide(HAUPT, "_kb_ordner_sicherstellen")
check("Positivkontrolle: _kb_ordner_sicherstellen wurde geschnitten",
      len(ord_code) > 200 and "folders" in ord_code)
check("… und vergleicht EINTRAGSWEISE, nicht als Teilstring",
      "folders.split(" in ord_code, ord_code[:200])
check("⚠ das Verbinden traegt den Ordner nach (heilt den Altbestand)",
      "_kb_ordner_sicherstellen(" in mount_code, mount_code[:200])
i_ord = mount_code.find("_kb_ordner_sicherstellen(")
i_reidx = mount_code.find("force_reindex")
check("… und zwar VOR dem Reindex (sonst laeuft der ueber die Freigabe nicht)",
      0 <= i_ord < i_reidx, f"{i_ord} / {i_reidx}")
# ⚠ Der Reindex darf die ANTWORT nicht aufhalten: seit die Freigabe in
# `folders` steht, laeuft er ueber deren ganzen Inhalt – auf DEV lief der
# Endpunkt dadurch in ein 300-s-Timeout, obwohl der Mount nach Sekunden stand.
check("⚠ der Reindex laeuft als Hintergrund-Aufgabe, nicht im Request",
      "asyncio.create_task(" in mount_code
      and mount_code.find("asyncio.create_task(") < mount_code.rfind("return JSONResponse"),
      mount_code[-400:])
check("… und die Antwort sagt, dass der Index nachzieht",
      "hinweis" in mount_code, mount_code[-200:])

add_code2 = schneide(HAUPT, "add_mount")
check("das Anlegen vergibt einen FREIEN Punkt und schreibt ihn fest",
      "_freier_mountpunkt(" in add_code2 and '"mountpoint": str(mp)' in add_code2)
check("… und benutzt fuer die Ordnerliste dieselbe Funktion (keine zweite Fassung)",
      "_kb_ordner_sicherstellen(" in add_code2
      and 'kb_cfg["folders"]' not in add_code2, add_code2[-300:])


print("\n\033[1m7. Bearbeiten zeigt den hinterlegten Benutzer\033[0m")
#
# ⚠ GEMELDET 2026-09-04: "bei Einstellungen -> Wissen -> Netzwerk-Freigaben ->
# bearbeiten wird ein hinterlegter Benutzer nicht angezeigt". Das Formular las
# `m.username` und setzte es brav – der Endpunkt gab das Feld nur NIE heraus.
# Und weil der leere Benutzername beim Speichern uebernommen wird (nur das
# leere KENNWORT bedeutet "unveraendert"), LOESCHTE jedes Bearbeiten ihn.
list_code = schneide(HAUPT, "list_mounts")
check("Positivkontrolle: list_mounts wurde geschnitten",
      len(list_code) > 300 and "result.append" in list_code)
check("⚠ der Endpunkt liefert den Benutzernamen aus",
      '"username"' in list_code, list_code[list_code.find("result.append"):][:300])
check("… und ob ein Kennwort hinterlegt ist (fuer den Sterne-Platzhalter)",
      '"has_password"' in list_code)
# Das KENNWORT selbst darf nirgends herauskommen – mehrfach dokumentierte
# Zusage des Projekts.
import re as _re3
feld_zeilen = _re3.findall(r'"(\w+)":\s*m\.get\("(\w+)"', list_code)
check("⚠ und das Kennwort selbst NICHT",
      all(q != "password" for _, q in feld_zeilen), str(feld_zeilen))

kjs2 = (WURZEL / "frontend" / "js" / "knowledge.js").read_text()
i_form = kjs2.find("kb-mount-edit-user")
check("das Formular fuellt das Benutzerfeld", i_form > 0)
zeile_user = kjs2[kjs2.rfind("\n", 0, i_form):kjs2.find("\n", i_form)]
check("⚠ und maskiert den Wert (Fremdinhalt in einem value-Attribut)",
      "_escHtml(m.username" in zeile_user, zeile_user.strip()[:160])
i_pass = kjs2.find("kb-mount-edit-pass")
zeile_pass = kjs2[kjs2.rfind("\n", 0, i_pass):kjs2.find("\n", i_pass)]
check("das Kennwortfeld sagt, ob eines hinterlegt ist (data-pw-gesetzt)",
      "data-pw-gesetzt" in zeile_pass and "has_password" in zeile_pass,
      zeile_pass.strip()[:160])


print("\n\033[1m5. Die Egress-Sperre darf keine Mounts blockieren\033[0m")
#
# ⚠ AM 2026-09-04 AUF DEV BEWIESEN: mit aktiver Internet-Sperre liess sich
# KEINE Netzwerk-Freigabe mehr einbinden. Der Kernel-CIFS-Client hat keine
# skuid, fiel deshalb durch "meta skuid != <uid> accept" und landete im
# nackten "drop". Gegenprobe: eine vorangestellte accept-Regel fuer das Ziel →
# 30 Pakete, gemountet, Inhalt sichtbar. Ein Userspace-Test auf Port 445
# gelang die ganze Zeit – genau das schickte die Suche in die falsche Richtung.
import types as _ty
if "backend.egress_guard" not in sys.modules:
    _d = _ty.ModuleType("dotenv"); _d.load_dotenv = lambda *a, **k: None
    sys.modules.setdefault("dotenv", _d)
from backend import egress_guard as EG   # noqa: E402

regeln = sicher(EG._render_nft, 996, ["191.100.2.50"])
check("Positivkontrolle: der Regelsatz wurde erzeugt",
      isinstance(regeln, str) and "chain out" in regeln, str(regeln)[:120])
zeilen = [z.strip() for z in str(regeln).splitlines() if z.strip()]
drops = [z for z in zeilen if z.startswith("drop") or " drop" in z]
check("es gibt genau eine drop-Regel", len(drops) == 1, str(drops))
check("⚠ und sie trifft NUR den Sandbox-Benutzer (kein nacktes 'drop')",
      bool(drops) and "skuid 996" in drops[0], str(drops))
# Die Sperre selbst muss bleiben: fuer den Sandbox-Benutzer aendert sich nichts.
check("die Sperre gilt weiter fuer den Sandbox-Benutzer",
      "meta skuid != 996 accept" in regeln and "meta skuid 996 drop" in regeln)
check("… und die Ausnahmen (Loopback, privat, DNS) stehen davor",
      regeln.index("127.0.0.0/8") < regeln.index("skuid 996 drop")
      and regeln.index("dport 53 accept") < regeln.index("skuid 996 drop"))
check("die Kette bleibt im Whitelist-Muster (policy accept + gezieltes drop)",
      "policy accept" in regeln)


print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
if FAIL:
    print(f"\033[31m{FAIL} Pruefung(en) fehlgeschlagen\033[0m")
sys.exit(1 if FAIL else 0)

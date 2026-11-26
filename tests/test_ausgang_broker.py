#!/usr/bin/env python3
"""Waechter: Ausgangsfilter aus der Oberflaeche (backend/broker/ausgang.py + meta.py).

Zusagen:
  [1] Lesen fuer die Anzeige: ``freigaben_lesen`` zerlegt Modus und Freigaben,
      Kommentare zaehlen nicht; ``treffer_lesen`` zaehlt Protokollzeilen je
      Wirkung/Benutzer/Protokoll/Ziel/Port, nennt den Kontonamen zur uid,
      sortiert nach Anzahl und uebergeht fremde Zeilen.
  [2] Pruefen geht durch das ECHTE ``ausgang.sh --zeigen`` an einer
      Wegwerf-Kopie: ein guter Text ist gueltig (mit Regelzahl), ein schlechter
      nennt Zeile und Grund – und die gespeicherte Konfiguration bleibt
      unberuehrt. Ueberlange Texte werden vorher abgewiesen.
  [3] Speichern: schreibt 0600 erst NACH der Pruefung, wendet an (nft -f,
      Boot-Unit). Ein ungueltiger Text schreibt nichts und ruft nft nicht.
      Scheitert das Anwenden, kommt der alte Text Byte fuer Byte zurueck (bzw.
      die Datei verschwindet, wenn es keine gab) und die Antwort sagt
      ``zurueck``.
  [4] Freigabe-Code (meta.py): speichern und entfernen nur mit gueltigem
      Code, pruefen ohne; jede Entscheidung steht im Audit.
  [5] Status: Konfiguration, Gueltigkeit, geladen/Policy, Unit und Treffer;
      "Protokoll nicht lesbar" ist etwas anderes als "keine Zeilen".
  [6] AIDE: beide Dateien stehen im Register ``eigene_dateien.PFADE`` (sonst
      ist jede Bearbeitung in der Oberflaeche ein Befund).

  [0] Positivkontrolle: das echte Skript laeuft im Sandkasten (``--zeigen``
      mit lokalen Konten liefert einen Satz). Sonst Exit 2.

``backend.config`` wird nicht importiert. Fuer die Gegenprobe:
JARVIS_AUSGANG_BROKER_PRUEFLING / JARVIS_AUSGANG_META_PRUEFLING zeigen auf Kopien
von ausgang.py bzw. meta.py.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PRUEFLING = Path(os.environ.get("JARVIS_AUSGANG_BROKER_PRUEFLING") or ROOT / "backend" / "broker" / "ausgang.py")
META = Path(os.environ.get("JARVIS_AUSGANG_META_PRUEFLING") or ROOT / "backend" / "broker" / "meta.py")
OK = FAIL = 0


def check(name: str, bed: bool, detail="") -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f" – {str(detail)[:300]}" if detail != "" else ""))


def abbruch(grund: str) -> None:
    print(f"ABBRUCH: {grund}")
    sys.exit(2)


# ── Sandkasten ────────────────────────────────────────────────────────────────
SK = Path(tempfile.mkdtemp(prefix="jv_ausgang_broker_"))
BIN = SK / "bin"
LOG = SK / "aufrufe.log"
for d in (BIN, SK / "etc", SK / "units"):
    d.mkdir(parents=True)

# nft: -c prueft (Fehler per Marke), -f laedt und merkt die Policy,
# list chain zeigt sie, delete nimmt sie weg
(BIN / "nft").write_text(f"""#!/bin/sh
printf 'nft %s\\n' "$*" >> "{LOG}"
if [ "$1" = "-c" ]; then [ -f "{SK}/nft_c_fehler" ] && exit 1; exit 0; fi
if [ "$1" = "-f" ]; then
    [ -f "{SK}/nft_f_fehler" ] && {{ echo "nft: Fehler beim Laden" >&2; exit 1; }}
    grep -o 'policy [a-z]*' "$2" | head -1 > "{SK}/geladen"; exit 0
fi
if [ "$1" = "list" ]; then
    [ -f "{SK}/geladen" ] || exit 1
    printf 'table inet jarvis_ausgang {{\\n\\tchain out {{\\n\\t\\ttype filter hook output priority filter; %s;\\n\\t}}\\n}}\\n' "$(cat "{SK}/geladen")"
    exit 0
fi
if [ "$1" = "delete" ]; then rm -f "{SK}/geladen"; exit 0; fi
exit 0
""")
(BIN / "systemctl").write_text(f"""#!/bin/sh
printf 'systemctl %s\\n' "$*" >> "{LOG}"
case "$1" in
  is-enabled) [ -f "{SK}/units/jarvis-ausgang.service" ] && {{ echo enabled; exit 0; }}; echo not-found; exit 1;;
esac
exit 0
""")
(BIN / "journalctl").write_text(f"""#!/bin/sh
printf 'journalctl %s\\n' "$*" >> "{LOG}"
[ -f "{SK}/journal_kaputt" ] && exit 3
[ -s "{SK}/journal" ] || exit 1
cat "{SK}/journal"
""")
# id -u ohne Namen = root (das Skript verlangt root fuer --anwenden),
# mit Namen das echte id (Konten werden wirklich aufgeloest)
(BIN / "id").write_text("""#!/bin/sh
if [ "$#" = 1 ] && [ "$1" = "-u" ]; then echo 0; exit 0; fi
exec /usr/bin/id "$@"
""")
for f in BIN.iterdir():
    f.chmod(0o755)

KONF = SK / "etc" / "ausgang.conf"
ABLAGE = SK / "etc" / "ausgang.nft"
os.environ.update({
    "PATH": f"{BIN}:/usr/bin:/bin",
    "JARVIS_AUSGANG_CONF": str(KONF),
    "JARVIS_AUSGANG_ABLAGE": str(ABLAGE),
    "JARVIS_UNIT_DIR": str(SK / "units"),
    "JARVIS_BROKER_FREIGABE_KEY": str(SK / "etc" / "freigabe.key"),
    "JARVIS_BROKER_FREIGABE_STATE": str(SK / "etc" / "freigabe.state"),
    "JARVIS_BROKER_POLICY": str(SK / "etc" / "policy.json"),
    "JARVIS_BROKER_AUDIT": str(SK / "audit.jsonl"),
    "JARVIS_AIDE_WURZEL": str(SK / "aide"),
})

spec = importlib.util.spec_from_file_location("backend.broker.ausgang", PRUEFLING)
ag = importlib.util.module_from_spec(spec)
sys.modules["backend.broker.ausgang"] = ag
spec.loader.exec_module(ag)
spec = importlib.util.spec_from_file_location("backend.broker.meta", META)
meta = importlib.util.module_from_spec(spec)
sys.modules["backend.broker.meta"] = meta
spec.loader.exec_module(meta)
freigabe = importlib.import_module("backend.broker.freigabe")
from backend import eigene_dateien  # noqa: E402

for name, p in (("KONF", ag.KONF), ("ABLAGE", ag.ABLAGE), ("FREIGABE", freigabe.SCHLUESSEL)):
    if not str(p).startswith(str(SK)):
        abbruch(f"{name} zeigt aus dem Sandkasten: {p}")
if not ag.SKRIPT.is_file():
    abbruch(f"ausgang.sh fehlt: {ag.SKRIPT}")


def log() -> str:
    return LOG.read_text() if LOG.exists() else ""


GUT = ("# Kopf\nMODUS=protokoll\n"
       "erlaube alle udp 53 192.0.2.53\n"
       "# Notiz\nerlaube root tcp 22,443 *\n"
       "erlaube nobody tcp - 198.51.100.0/24\n")
SCHLECHT = "MODUS=protokoll\nerlaube alle tcp 443 *\n"

print("[0] Positivkontrolle")
p0 = ag.pruefen(GUT)
if not p0.get("ok"):
    abbruch(f"das echte ausgang.sh nimmt einen guten Text nicht an: {p0}")
print("  OK   ausgang.sh --zeigen laeuft im Sandkasten")

print("[1] Lesen fuer die Anzeige")
z = ag.freigaben_lesen(GUT)
check("Modus und drei Freigaben, Kommentare zaehlen nicht",
      z["modus"] == "protokoll" and len(z["freigaben"]) == 3, z)
check("Felder einer Freigabe", z["freigaben"][1] == {"benutzer": "root", "proto": "tcp", "ports": "22,443",
                                                     "ziele": "*", "zeile": 5} if len(z["freigaben"]) > 1 else False, z)
check("ohne Datei: Vorgabe protokoll, keine Freigaben", ag.freigaben_lesen("") == {"modus": "protokoll", "freigaben": []})
jetzt = time.time()
zeilen = [
    f"{jetzt - 30:.6f} h kernel: nft-aus-frei: IN= OUT=eth0 SRC=192.0.2.10 DST=203.0.113.5 PROTO=TCP SPT=1 DPT=443 UID=0 GID=0",
    f"{jetzt - 20:.6f} h kernel: nft-aus-frei: IN= OUT=eth0 SRC=192.0.2.10 DST=203.0.113.5 PROTO=TCP SPT=2 DPT=443 UID=0 GID=0",
    f"{jetzt - 10:.6f} h kernel: nft-aus-drop: IN= OUT=eth0 SRC=192.0.2.10 DST=203.0.113.9 PROTO=UDP SPT=3 DPT=53 UID=65534 GID=65534",
    f"{jetzt - 5:.6f} h kernel: nft-aus-frei: IN= OUT=eth0 SRC=192.0.2.10 DST=224.0.0.22 PROTO=2",
    f"{jetzt:.6f} h kernel: nft-in-drop: IN=eth0 SRC=203.0.113.1 DST=192.0.2.10 PROTO=TCP DPT=22",
    "kaputt",
]
tr = ag.treffer_lesen(zeilen)
check("drei Gruppen, fremde Zeilen uebergangen", len(tr) == 3, tr)
erster = tr[0] if tr else {}
check("haeufigste zuerst, gezaehlt und mit Kontoname",
      erster.get("anzahl") == 2 and erster.get("benutzer") == "root" and erster.get("port") == "443"
      and erster.get("art") == "frei", erster)
check("zuletzt = juengste Zeile der Gruppe", abs(erster.get("zuletzt", 0) - (jetzt - 20)) < 0.01, erster)
drop = [t for t in tr if t.get("art") == "drop"]
check("verworfen getrennt gezaehlt, nobody erkannt",
      len(drop) == 1 and drop[0]["benutzer"] == "nobody" and drop[0]["proto"] == "UDP", drop)
kern = [t for t in tr if t.get("ziel") == "224.0.0.22"]
check("ohne uid: kein Kontoname", len(kern) == 1 and kern[0]["uid"] == "" and kern[0]["benutzer"] == "", kern)

print("[2] Pruefen")
check("guter Text: gueltig, drei Regeln", p0.get("regeln") == 3, p0)
p = ag.pruefen(SCHLECHT)
check("schlechter Text: ungueltig, Grund nennt die Zeile", p.get("ok") is False and "Zeile 2" in p.get("meldung", ""), p)
check("Pruefen legt keine Konfiguration an", not KONF.exists())
check("ueberlang abgewiesen", ag.pruefen("erlaube alle udp 53 192.0.2.53\n" * (ag.MAX_ZEILEN + 5)).get("ok") is False)
check("kein Text abgewiesen", ag.pruefen(None).get("ok") is False)

print("[3] Speichern")
LOG.write_text("")
r = ag.speichern(SCHLECHT)
check("ungueltig: nichts geschrieben, nft nicht gerufen", r.get("ok") is False and not KONF.exists()
      and "nft -f" not in log(), r)
LOG.write_text("")
r = ag.speichern(GUT.replace("\n", "\r\n"))
check("gueltig: ok", r.get("ok") is True, r)
check("Datei = Text (Zeilenenden normiert)", KONF.is_file() and KONF.read_text() == GUT, KONF.read_text() if KONF.exists() else "")
check("Datei 0600", KONF.is_file() and stat.S_IMODE(KONF.stat().st_mode) == 0o600)
check("angewendet: nft -f und Boot-Unit", "nft -f" in log() and (SK / "units" / "jarvis-ausgang.service").is_file(), log())
check("gespeicherter Satz liegt in der Ablage", ABLAGE.is_file())
# Vorabpruefung: ein ungueltiger Text erreicht die gespeicherte Datei NIE –
# auch nicht fuer einen Moment (das Zurueckschreiben danach waere eine
# zweite Schranke fuer dieselbe Frage; gemessen wird deshalb die Datei selbst)
vor = KONF.stat()
r = ag.speichern(SCHLECHT)
nach = KONF.stat()
check("ungueltig bei vorhandener Datei: abgewiesen VOR dem Schreiben (Datei unberuehrt, kein zurueck)",
      r.get("ok") is False and not r.get("zurueck") and (vor.st_ino, vor.st_mtime_ns) == (nach.st_ino, nach.st_mtime_ns), r)
alt = KONF.read_bytes()
(SK / "nft_f_fehler").write_text("")
r = ag.speichern(GUT.replace("MODUS=protokoll", "MODUS=sperre"))
(SK / "nft_f_fehler").unlink()
check("Anwenden scheitert: Fehler mit zurueck", r.get("ok") is False and r.get("zurueck") is True, r)
check("alter Text Byte fuer Byte zurueck", KONF.read_bytes() == alt)
KONF.unlink()
(SK / "nft_f_fehler").write_text("")
r = ag.speichern(GUT)
(SK / "nft_f_fehler").unlink()
check("ohne alte Datei: nach Fehlschlag keine Datei", r.get("ok") is False and not KONF.exists(), r)

print("[4] Freigabe-Code")
freigabe.einrichten()
schluessel = freigabe._lade()
KONF.unlink(missing_ok=True)
LOG.write_text("")
r = meta.behandeln("broker.ausgang", {"aktion": "speichern", "text": GUT, "by": "admin"})
check("speichern ohne Code: abgewiesen, nichts geschrieben",
      r.get("grund") == "nachweis_fehlt" and not KONF.exists() and "nft" not in log(), r)
r = meta.behandeln("broker.ausgang", {"aktion": "speichern", "text": GUT, "by": "admin", "nachweis": "000000"})
check("speichern mit falschem Code: abgewiesen", r.get("ok") is False and r.get("grund") and not KONF.exists(), r)
r = meta.behandeln("broker.ausgang", {"aktion": "pruefen", "text": GUT, "by": "admin"})
check("pruefen ohne Code: ok", r.get("ok") is True, r)
r = meta.behandeln("broker.ausgang", {"aktion": "entfernen", "by": "admin"})
check("entfernen ohne Code: abgewiesen", r.get("grund") == "nachweis_fehlt", r)
r = meta.behandeln("broker.ausgang", {"aktion": "irgendwas", "by": "admin"})
check("unbekannte Aktion: abgewiesen", r.get("ok") is False, r)
freigabe.ZUSTAND.unlink(missing_ok=True)
code = freigabe._code(schluessel, int(time.time() // freigabe.SCHRITT_S))
r = meta.behandeln("broker.ausgang", {"aktion": "speichern", "text": GUT, "by": "admin", "nachweis": code})
check("speichern mit Code: ok, Datei geschrieben", r.get("ok") is True and KONF.read_text() == GUT, r)
audit = (SK / "audit.jsonl").read_text() if (SK / "audit.jsonl").exists() else ""
eintraege = [json.loads(z) for z in audit.splitlines() if z.strip()]
ops = [(e.get("key"), e.get("decision")) for e in eintraege]
check("Audit: abgewiesene und ausgefuehrte Speicherung",
      ("broker.ausgang:speichern", "abgewiesen") in ops and ("broker.ausgang:speichern", "executed") in ops, ops)

print("[5] Status")
(SK / "journal").write_text("\n".join(zeilen[:3]) + "\n")
st = meta.behandeln("broker.ausgang_status", {"stunden": 24})
check("Konfiguration, gueltig, geladen accept, Unit an",
      st.get("konfiguration") is True and st.get("gueltig") is True and st.get("geladen") is True
      and st.get("policy") == "accept" and st.get("unit") == "enabled", {k: st.get(k) for k in ("konfiguration", "gueltig", "geladen", "policy", "unit", "fehler")})
check("Text und Freigaben mitgeliefert", st.get("text") == GUT and len(st.get("freigaben") or []) == 3)
check("Treffer gelesen", st.get("protokoll_lesbar") is True and len(st.get("treffer") or []) == 2, st.get("treffer"))
jz = [z for z in log().splitlines() if z.startswith("journalctl ")]
check("Protokoll ueber alle Systemstarts (_TRANSPORT=kernel, nicht -k = nur dieser Start)",
      bool(jz) and "_TRANSPORT=kernel" in jz[-1] and " -k" not in jz[-1] and " -b" not in jz[-1], jz[-1:] or jz)
(SK / "journal").write_text("")
st = ag.status()
check("keine Zeilen: lesbar, leer", st.get("protokoll_lesbar") is True and st.get("treffer") == [])
(SK / "journal_kaputt").write_text("")
st = ag.status()
(SK / "journal_kaputt").unlink()
check("Protokoll nicht lesbar: als solches gemeldet", st.get("protokoll_lesbar") is False)
KONF.write_text(SCHLECHT)
st = ag.status()
check("fehlerhafte Datei: gueltig False mit Grund", st.get("gueltig") is False and "Zeile 2" in st.get("fehler", ""), st.get("fehler"))
r = ag.entfernen()
st = ag.status(stunden="999999")
check("nach entfernen: nicht geladen, Unit fehlt, Datei bleibt",
      r.get("ok") is True and st.get("geladen") is False and st.get("unit") != "enabled" and KONF.is_file(), (r, st.get("geladen"), st.get("unit")))
check("Zeitraum gedeckelt", st.get("stunden") == ag.MAX_STUNDEN, st.get("stunden"))
KONF.unlink()
st = ag.status(stunden="kaputt")
check("ohne Datei: nicht eingerichtet, Vorgabe-Zeitraum", st.get("konfiguration") is False and st.get("gueltig") is None
      and st.get("stunden") == ag.STUNDEN_VORGABE, st)

print("[6] AIDE-Register")
check("ausgang.conf und ausgang.nft stehen in eigene_dateien.PFADE",
      {"/etc/jarvis/ausgang.conf", "/etc/jarvis/ausgang.nft"} <= set(eigene_dateien.PFADE), eigene_dateien.PFADE)

shutil.rmtree(SK, ignore_errors=True)
print(f"\nERGEBNIS: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)

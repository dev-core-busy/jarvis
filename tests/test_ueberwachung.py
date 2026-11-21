#!/usr/bin/env python3
"""Waechter fuer die Serverueberwachung (Haertung B13, backend/ueberwachung.py).

Gemessen wird die AUSWERTUNG an Eingaben in der Form, die ``sammeln`` aus dem
System liest – die sshd- und Kernel-Zeilen sind am 2026-11-20 auf ECHT und
DEV gemessene Formate (Adressen durch Dokumentationsnetze ersetzt). Dazu:
Meldelogik (nur bei Aenderung), Lesen fuer die Oberflaeche (veraltet =
Warnung), atomares Schreiben, Zertifikatsablauf ueber ein echtes openssl,
die Units im Haertungsskript und die Schranke am Endpunkt.

JARVIS_UEBERW_PRUEFLING / JARVIS_HAERTUNG_PRUEFLING / JARVIS_MAIN_PRUEFLING
lenken auf Kopien (Gegenprobe tests/gegen_ueberwachung.py).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = Path(os.environ.get("JARVIS_UEBERW_PRUEFLING", ROOT / "backend" / "ueberwachung.py"))
SKRIPT = Path(os.environ.get("JARVIS_HAERTUNG_PRUEFLING", ROOT / "deploy" / "security" / "system_haertung.sh"))
MAIN = Path(os.environ.get("JARVIS_MAIN_PRUEFLING", ROOT / "backend" / "main.py"))

OK = FAIL = 0


def pruefe(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  \033[32m✓\033[0m " + text)
    else:
        FAIL += 1
        print("  \033[31m✗\033[0m " + text)


def abbruch(text):
    print("ABBRUCH: " + text)
    print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
    sys.exit(2)


for f in (MOD, SKRIPT, MAIN):
    if not f.is_file():
        abbruch("%s fehlt" % f)

spec = importlib.util.spec_from_file_location("ueberwachung_pruefling", MOD)
ue = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(ue)
except Exception as e:      # noqa: BLE001 – ein kaputter Pruefling ist "konnte nicht laufen"
    abbruch("Modul nicht ladbar: %s" % e)
for name in ("auswerten", "ssh_fehlversuche", "nft_zeilen", "lesen", "schreiben", "konf_laden"):
    if not callable(getattr(ue, name, None)):
        abbruch("Funktion %s fehlt" % name)

KONF = dict(ue.VORGABE)
JETZT = 1_800_000_000.0


def eingabe(**kw):
    e = {"dienste": {}, "fehlgeschlagen": [], "platz": {},
         "zert_ablauf": JETZT + 400 * 86400, "zert_fehler": "",
         "ssh": [], "kern": [], "cursor": {"ssh": "c1", "kern": "k1"},
         "uid_dienst": 1001, "uid_sandbox": [996, 997]}
    e.update(kw)
    return e


def j(*msgs, t=JETZT - 60):
    return [{"zeit": t + i, "msg": m} for i, m in enumerate(msgs)]


def ids(zustand):
    return {b["id"]: b["stufe"] for b in zustand["befunde"]}


# ── 0. Positivkontrolle und Bauform ──────────────────────────────────────────
print("[0] Bauform")
baum = ast.parse(MOD.read_text(encoding="utf-8"))
importe = set()
for n in ast.walk(baum):
    if isinstance(n, ast.Import):
        importe |= {a.name.split(".")[0] for a in n.names}
    elif isinstance(n, ast.ImportFrom) and n.module:
        importe.add(n.module.split(".")[0])
fremd = importe - set(sys.stdlib_module_names) - {"__future__"}
pruefe(not fremd, "nur Standardbibliothek (laeuft als root mit System-Python aus der Broker-Kopie)%s"
       % (" – fremd: %s" % sorted(fremd) if fremd else ""))
leer, _ = ue.auswerten(eingabe(), {}, KONF, JETZT)
pruefe(leer["stufe"] == "ok" and leer["befunde"] == [],
       "Positivkontrolle: ruhiges System ergibt Stufe ok ohne Befund")

# ── 1. SSH je Verbindung ─────────────────────────────────────────────────────
print("[1] SSH-Fehlversuche je Verbindung")
f = ue.ssh_fehlversuche
pruefe(len(f(j("Failed publickey for admin from 192.0.2.7 port 50000 ssh2: RSA SHA256:x",
               "Accepted publickey for admin from 192.0.2.7 port 50000 ssh2: ED25519 SHA256:y"))) == 0,
       "Schluessel durchprobiert, dann angemeldet: KEIN Fehlversuch")
pruefe(len(f(j("Failed publickey for admin from 192.0.2.7 port 50002 ssh2: RSA SHA256:x"))) == 0,
       "nur 'Failed publickey', Abschluss steht erst im naechsten Lauf: noch KEIN Fehlversuch")
pruefe(len(f(j("Failed password for admin from 192.0.2.7 port 50003 ssh2",
               "Accepted publickey for admin from 192.0.2.7 port 50003 ssh2: ED25519 SHA256:y"))) == 0,
       "Kennwort falsch, dann mit Schluessel angemeldet (eine Verbindung): KEIN Fehlversuch")
pruefe(len(f(j("Failed publickey for admin from 192.0.2.7 port 50001 ssh2: RSA SHA256:x",
               "Failed publickey for admin from 192.0.2.7 port 50001 ssh2: RSA SHA256:z",
               "Connection closed by authenticating user admin 192.0.2.7 port 50001 [preauth]"))) == 1,
       "kein passender Schluessel, Client gibt auf: genau EIN Fehlversuch")
r = f(j("Invalid user gast from 198.51.100.4 port 4711",
        "Connection reset by invalid user gast 198.51.100.4 port 4711 [preauth]"))
pruefe(len(r) == 1 and r[0]["user"] == "gast" and r[0]["ip"] == "198.51.100.4",
       "unbekannter Benutzer (zwei Zeilen) = ein Fehlversuch, Benutzer und Adresse erkannt")
pruefe(len(f(j("Invalid user a from 198.51.100.4 port 1", "Invalid user b from 198.51.100.4 port 2"))) == 2,
       "zwei Verbindungen = zwei Fehlversuche")
pruefe(len(f(j("Connection closed by 198.51.100.9 port 22222 [preauth]",
               "Received disconnect from 198.51.100.9 port 22223:11: Bye [preauth]"))) == 0,
       "Verbindung ohne Anmeldeversuch (Portscan) zaehlt nicht")
pruefe(len(f(j("User root from 198.51.100.5 not allowed because not listed in AllowUsers"))) == 1,
       "AllowUsers-Ablehnung (Zeile ohne Port) zaehlt")
pruefe(len(f(j("error: maximum authentication attempts exceeded for root from 198.51.100.6 port 9 ssh2 [preauth]"))) == 1,
       "maximale Versuche ueberschritten zaehlt")
pruefe(len(f(j("Failed password for invalid user x from 2001:db8::5 port 7 ssh2"))) == 1,
       "IPv6-Quelle wird erkannt")

# ── 2. Firewall-Zeilen ───────────────────────────────────────────────────────
print("[2] Verworfene Pakete")
OUT = ("nft-out-drop: IN= OUT=ens192 SRC=192.0.2.10 DST=203.0.113.5 LEN=60 TOS=0x00 PREC=0x00 TTL=64 "
       "ID=1 DF PROTO=TCP SPT=40000 DPT=443 WINDOW=64240 RES=0x00 SYN URGP=0 UID=%s GID=%s")
IN = ("nft-in-drop: IN=ens192 OUT= MAC=00:00 SRC=192.0.2.99 DST=192.0.2.10 LEN=60 TOS=0x00 PREC=0x00 "
      "TTL=63 ID=2 DF PROTO=TCP SPT=5000 DPT=8443 WINDOW=1 RES=0x00 SYN URGP=0")
z = ue.nft_zeilen(j(OUT % (996, 996), IN, "anderes Kernel-Rauschen"))
pruefe(len(z) == 2 and z[0]["richtung"] == "out" and z[0]["uid"] == "996" and z[0]["dpt"] == "443"
       and z[1]["richtung"] == "in" and z[1]["src"] == "192.0.2.99",
       "nft-Zeilen zerlegt (Richtung, UID, Ziel/Quelle, Port), Rauschen ignoriert")
zerlegt = OUT % (1001, 1001)
pruefe(ue._mit_kennung(zerlegt[len("nft-out-drop: "):], "nft-out-drop") == zerlegt
       and ue._mit_kennung(zerlegt, "kernel") == zerlegt and ue._mit_kennung(zerlegt, "nft-out-drop") == zerlegt,
       "von journald zerlegte Zeile (Kennung nft-out-drop) wird wieder vollstaendig, echte bleibt gleich")
s, _ = ue.auswerten(eingabe(kern=j(OUT % (1001, 1001))), {}, KONF, JETZT)
pruefe(ids(s).get("out_dienst") == "alarm" and s["stufe"] == "alarm",
       "nft-out-drop vom Dienstbenutzer ist ein ALARM")
pruefe("203.0.113.5:443" in s["befunde"][0]["werte"].get("ziele", []), "Alarm nennt das Ziel")
s, _ = ue.auswerten(eingabe(kern=j(OUT % (996, 996))), {}, KONF, JETZT)
pruefe(ids(s) == {"out_sandbox": "info"}, "nft-out-drop der Sandbox ist nur ein Hinweis")
s, _ = ue.auswerten(eingabe(kern=j(OUT % (4242, 4242))), {}, KONF, JETZT)
pruefe(ids(s).get("out_fremd") == "warnung", "nft-out-drop einer fremden UID ist eine Warnung")
s, _ = ue.auswerten(eingabe(uid_dienst=None, kern=j(OUT % (1001, 1001))), {}, KONF, JETZT)
pruefe(ids(s).get("out_fremd") == "warnung" and "out_dienst" not in ids(s),
       "ohne bekannte Dienst-UID wird nichts als Dienst geraten (Warnung statt Alarm)")
s, _ = ue.auswerten(eingabe(kern=j(*[IN] * 3)), {}, KONF, JETZT)
pruefe(ids(s) == {"in_drop": "info"}, "einige nft-in-drop: Hinweis")
grenze = int(float(KONF["IN_WARNUNG"]))
s, _ = ue.auswerten(eingabe(kern=j(*[IN] * grenze)), {}, KONF, JETZT)
pruefe(ids(s).get("in_drop") == "warnung", "Drossel ausgeschoepft (%d in einem Lauf): Warnung" % grenze)

# ── 3. Dienste ───────────────────────────────────────────────────────────────
print("[3] Dienste")
d = {"a.service": {"enabled": "enabled", "active": "inactive"},
     "b.service": {"enabled": "enabled", "active": "activating"},
     "c.service": {"enabled": "disabled", "active": "inactive"},
     "d.service": {"enabled": "not-found", "active": "inactive"},
     "e.service": {"enabled": "enabled", "active": "failed"},
     "f.service": {"enabled": "enabled", "active": "active"},
     "g.service": {"enabled": "enabled", "active": "deactivating"}}
s, _ = ue.auswerten(eingabe(dienste=d), {}, KONF, JETZT)
pruefe(ids(s) == {"dienst:a.service": "alarm", "dienst:e.service": "alarm"},
       "aktiviert und nicht aktiv = Alarm; startend, beim Neustart (deactivating), abgeschaltet, nicht installiert = nichts (%s)" % ids(s))
s, _ = ue.auswerten(eingabe(fehlgeschlagen=["x.timer", "y.service"]), {}, KONF, JETZT)
pruefe(ids(s) == {"failed": "warnung"}, "Units im Zustand failed: Warnung")
dienste_vorgabe = set(ue.VORGABE["DIENSTE"].split())
pruefe({"jarvis.service", "jarvis-broker.service", "jarvis-firewall.service", "jarvis-egress.service",
        "auditd.service", "ssh.service"} <= dienste_vorgabe,
       "Vorgabe umfasst Dienst, Broker, Firewall, Ausgangsfilter, auditd, ssh")

# ── 4. Platz ─────────────────────────────────────────────────────────────────
print("[4] Freier Platz")
G = 100 * 10**9


def platz(frei, geraet=1):
    return {"frei": frei, "gesamt": G, "geraet": geraet}


for anteil, soll in ((3, "alarm"), (10, "warnung"), (50, None)):
    s, _ = ue.auswerten(eingabe(platz={"/": platz(anteil * 10**9)}), {}, KONF, JETZT)
    pruefe(ids(s).get("platz:/") == soll, "%d %% frei: %s" % (anteil, soll or "kein Befund"))
s, _ = ue.auswerten(eingabe(platz={"/": platz(3 * 10**9), "/var/log": platz(3 * 10**9)}), {}, KONF, JETZT)
pruefe(list(ids(s)) == ["platz:/"], "/var/log auf demselben Dateisystem wird nicht doppelt gemeldet")
s, _ = ue.auswerten(eingabe(platz={"/": platz(50 * 10**9), "/var/log": platz(3 * 10**9, geraet=2)}), {}, KONF, JETZT)
pruefe(ids(s) == {"platz:/var/log": "alarm"}, "eigenes Dateisystem fuer /var/log wird eigens geprueft")

# ── 5. Zertifikat ────────────────────────────────────────────────────────────
print("[5] Zertifikat")
for tage, soll in ((5, "alarm"), (20, "warnung"), (400, None), (-2, "alarm")):
    s, _ = ue.auswerten(eingabe(zert_ablauf=JETZT + tage * 86400), {}, KONF, JETZT)
    pruefe(ids(s).get("zert") == soll, "Ablauf in %d Tagen: %s" % (tage, soll or "kein Befund"))
s, _ = ue.auswerten(eingabe(zert_ablauf=None, zert_fehler="Datei fehlt"), {}, KONF, JETZT)
pruefe(ids(s).get("zert") == "warnung", "unlesbares Zertifikat: Warnung")
# echtes openssl: ein Zertifikat mit 10 Tagen Laufzeit
tmp = Path(tempfile.mkdtemp(prefix="ueberw_"))
try:
    crt = tmp / "s.crt"
    r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "10",
                        "-subj", "/CN=probe", "-keyout", str(tmp / "s.key"), "-out", str(crt)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  HINWEIS openssl nicht nutzbar – Zertifikatslesen nicht geprueft")
    else:
        ab, grund = ue._zert_ablauf(str(crt))
        pruefe(ab is not None and abs((ab - time.time()) / 86400 - 10) < 0.1,
               "openssl: Ablauf eines 10-Tage-Zertifikats gelesen (%s)" % (grund or "ok"))
        ab2, grund2 = ue._zert_ablauf(str(tmp / "fehlt.crt"))
        pruefe(ab2 is None and "fehlt" in grund2, "fehlende Datei: Grund statt Ablauf")

    # ── 6. Ereignisse ueber Laeufe ────────────────────────────────────────────
    print("[6] Ereignisse bleiben 24 h")
    FEHL = "Invalid user x from 198.51.100.4 port %d"
    s1, _ = ue.auswerten(eingabe(ssh=j(FEHL % 1)), {}, KONF, JETZT)
    pruefe(ids(s1).get("ssh") == "warnung", "eine Fehlanmeldung: Warnung")
    s2, _ = ue.auswerten(eingabe(ssh=[]), s1, KONF, JETZT + 23 * 3600)
    pruefe(ids(s2).get("ssh") == "warnung", "nach 23 h noch sichtbar")
    s3, _ = ue.auswerten(eingabe(ssh=[]), s2, KONF, JETZT + 25 * 3600)
    pruefe("ssh" not in ids(s3), "nach 25 h verschwunden")
    s4, _ = ue.auswerten(eingabe(ssh=j(FEHL % 1)), s1, KONF, JETZT + 300)
    pruefe(s4["befunde"][0]["werte"]["anzahl"] == 1,
           "dieselbe Verbindung im naechsten Lauf erneut gelesen: nicht doppelt gezaehlt")
    n_alarm = int(float(KONF["SSH_ALARM"]))
    s5, _ = ue.auswerten(eingabe(ssh=j(*[FEHL % (100 + i) for i in range(n_alarm)])), {}, KONF, JETZT)
    pruefe(ids(s5).get("ssh") == "alarm", "%d Fehlversuche in einem Lauf: Alarm" % n_alarm)
    pruefe(s5["cursor"] == {"ssh": "c1", "kern": "k1"}, "Journal-Cursor wird fortgeschrieben")
    # Verlauf fuer das Aufklappen am Zahnrad: je Lauf ein Eintrag, juengster zuerst
    sv = s1
    for i in range(ue.VERLAUF_MAX + 2):
        sv, _ = ue.auswerten(eingabe(ssh=j(FEHL % (500 + i), "Invalid user y from 203.0.113.%d port %d" % (i, 600 + i))),
                             sv, KONF, JETZT + 300 * (i + 1))
    wv = ([b for b in sv["befunde"] if b["id"] == "ssh"] or [{}])[0].get("werte", {})
    vl = wv.get("verlauf") or []
    pruefe(len(vl) == ue.VERLAUF_MAX and wv.get("verlauf_gesamt") == ue.VERLAUF_MAX + 3,
           "Verlauf gedeckelt auf VERLAUF_MAX, Gesamtzahl der Laeufe genannt (%d/%s)" % (len(vl), wv.get("verlauf_gesamt")))
    pruefe(bool(vl) and vl[0].get("zeit", 0) > vl[-1].get("zeit", 0) and vl[0].get("anzahl") == 2
           and "203.0.113.%d" % (ue.VERLAUF_MAX + 1) in vl[0].get("ips", []),
           "juengster Lauf zuerst, mit Anzahl und allen Quelladressen %s" % str(vl[:1]))

    # ── 7. Meldungen nur bei Aenderung ────────────────────────────────────────
    print("[7] Journal-Meldungen")
    aus = {"jarvis.service": {"enabled": "enabled", "active": "inactive"}}
    a1, m1 = ue.auswerten(eingabe(dienste=aus), {}, KONF, JETZT)
    pruefe(len(m1) == 1 and m1[0][0] == "alarm" and m1[0][1].startswith("B13 ALARM dienst:jarvis.service"),
           "neuer Alarm: genau eine Meldung 'B13 ALARM …'")
    a2, m2 = ue.auswerten(eingabe(dienste=aus), a1, KONF, JETZT + 300)
    pruefe(m2 == [], "gleicher Alarm im naechsten Lauf: keine Meldung")
    pruefe(a2["befunde"][0]["seit"] == JETZT, "'seit' bleibt der erste Zeitpunkt")
    a3, m3 = ue.auswerten(eingabe(dienste=aus), a2, KONF, JETZT + ue.ERINNERN_S + 1)
    pruefe(len(m3) == 1 and m3[0][0] == "alarm", "anhaltender Alarm: Erinnerung nach ERINNERN_S")
    a4, m4 = ue.auswerten(eingabe(), a3, KONF, JETZT + ue.ERINNERN_S + 400)
    pruefe(len(m4) == 1 and m4[0][0] == "behoben" and m4[0][1].startswith("B13 BEHOBEN dienst:jarvis.service"),
           "Alarm vorbei: eine Meldung 'B13 BEHOBEN …'")
    _, m5 = ue.auswerten(eingabe(kern=j(OUT % (996, 996))), {}, KONF, JETZT)
    pruefe(m5 == [], "ein Hinweis (Sandbox) erzeugt keine Journalzeile")

    # ── 8. Lesen fuer die Oberflaeche ─────────────────────────────────────────
    print("[8] Lesen")
    zd = tmp / "zustand.json"
    r0 = ue.lesen(zd, jetzt=JETZT)
    pruefe(r0["eingerichtet"] is False and r0["stufe"] == "ok", "ohne Datei: nicht eingerichtet, kein Alarm")
    ue.schreiben(a1, zd)
    r1 = ue.lesen(zd, jetzt=JETZT + 60)
    pruefe(r1["stufe"] == "alarm" and not r1["veraltet"] and r1["befunde"][0]["id"] == "dienst:jarvis.service",
           "frischer Zustand: Stufe und Befunde der Datei")
    pruefe("ssh_gezaehlt" not in r1 and "cursor" not in r1 and "gemeldet" not in r1["befunde"][0],
           "Oberflaeche bekommt keine Interna (Cursor, Zaehlschluessel)")
    ue.schreiben(leer, zd)
    r2 = ue.lesen(zd, jetzt=JETZT + ue.VERALTET_S + 60)
    pruefe(r2["stufe"] == "warnung" and r2["veraltet"] and r2["befunde"][0]["id"] == "veraltet",
           "stehengebliebener Waechter (Zustand aelter als VERALTET_S): Warnung, nicht 'alles gut'")
    pruefe(ue.VERALTET_S <= 3 * ue.TAKT_S + 60, "VERALTET_S liegt bei hoechstens drei Takten")
    zd.write_text("kaputt", encoding="utf-8")
    pruefe(ue.lesen(zd, jetzt=JETZT)["stufe"] == "warnung", "unlesbarer Zustand: Warnung")

    # ── 9. Schreiben ─────────────────────────────────────────────────────────
    print("[9] Schreiben")
    ue.schreiben(a1, zd)
    pruefe(json.loads(zd.read_text(encoding="utf-8"))["stufe"] == "alarm", "Zustand geschrieben")
    pruefe(not list(tmp.glob("*.tmp")), "keine Zwischendatei liegen geblieben")
    pruefe(zd.stat().st_mode & 0o007 == 0, "Datei fuer andere nicht lesbar (Sandbox-Benutzer)")

    # ── 10. Konfiguration ─────────────────────────────────────────────────────
    print("[10] Konfiguration")
    kd = tmp / "ueberwachung.conf"
    kd.write_text('PLATZ_ALARM="50"\n', encoding="utf-8")
    # 0644 ausdruecklich: mit umask 002 waere die Datei gruppenbeschreibbar und
    # fiele schon an der MODUS-Pruefung durch – die Eigentuemer-Pruefung bliebe
    # dann ungemessen (Gegenprobe "fremde Datei wird gelesen" war stumm).
    kd.chmod(0o644)
    k = ue.konf_laden(kd)
    if os.geteuid() == 0:
        print("  HINWEIS als root: die Schranke 'fremde Datei' ist so nicht messbar")
    else:
        pruefe(k["PLATZ_ALARM"] == ue.VORGABE["PLATZ_ALARM"] and k.get("_konf_fehler"),
               "nicht root-eigene Datei wird ignoriert und gemeldet")
        s, _ = ue.auswerten(eingabe(), {}, k, JETZT)
        pruefe(ids(s).get("konf") == "warnung", "ignorierte Konfiguration ist eine Warnung")
    pruefe(ue.konf_laden(tmp / "fehlt.conf") == ue.VORGABE, "ohne Datei: Vorgaben")

    # ── 11. Aufruf ────────────────────────────────────────────────────────────
    print("[11] Aufruf")
    if os.geteuid() != 0:
        r = subprocess.run([sys.executable, "-I", str(MOD), "--lauf"], capture_output=True, text=True)
        pruefe(r.returncode == 2 and "root" in r.stderr, "--lauf ohne root: Exit 2")
    r = subprocess.run([sys.executable, "-I", str(MOD), "--unsinn"], capture_output=True, text=True)
    pruefe(r.returncode == 2, "unbekannter Aufruf: Exit 2")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ── 12. Units im Haertungsskript ─────────────────────────────────────────────
print("[12] Units (system_haertung.sh)")
sk = SKRIPT.read_text(encoding="utf-8")
m = re.search(r'^UEBERW_PROG="([^"]+)"', sk, re.M)
prog = m.group(1) if m else ""
pruefe(prog.startswith("/usr/local/lib/jarvis-broker/") and prog.endswith("/ueberwachung.py"),
       "Programm aus der ROOT-EIGENEN Broker-Kopie, nicht aus /opt/jarvis (K1): %s" % prog)
svc = re.search(r'^UEBERW_SERVICE="([^"]*)"', sk, re.M)
svc = svc.group(1) if svc else ""
for zeile in ("ExecStart=/usr/bin/python3 -I $UEBERW_PROG --lauf", "Type=oneshot", "PrivateNetwork=yes",
              "ProtectSystem=strict", "NoNewPrivileges=yes", "StateDirectory=jarvis-ueberwachung"):
    pruefe(zeile in svc.splitlines(), "Service: %s" % zeile)
pruefe("/opt/jarvis" not in svc, "Service verweist nirgends auf /opt/jarvis")
tim = re.search(r"^UEBERW_TIMER='([^']*)'", sk, re.M)
tim = tim.group(1) if tim else ""
pruefe("OnUnitActiveSec=5min" in tim.splitlines() and "WantedBy=timers.target" in tim.splitlines(),
       "Timer: alle 5 Minuten, in timers.target")
pruefe(str(ue.TAKT_S // 60) + "min" in tim, "Takt im Modul (TAKT_S) passt zum Timer")
ziele = re.search(r'^ZIELE="\n(.*?)^"', sk, re.S | re.M)
ziele = ziele.group(1) if ziele else ""
pruefe("etc/systemd/system/jarvis-ueberwachung.service|0644|UEBERW_SERVICE" in ziele
       and "etc/systemd/system/jarvis-ueberwachung.timer|0644|UEBERW_TIMER" in ziele,
       "beide Units stehen in der ZIELE-Liste")
pruefe(re.search(r"systemctl enable --now jarvis-ueberwachung\.timer", sk) is not None,
       "--anwenden schaltet den Timer ein")
pruefe(re.search(r"is-active --quiet jarvis-ueberwachung\.timer", sk) is not None
       and "VERALTET" in sk, "--pruefen prueft Timer UND Alter des Zustands")
pruefe("/var/lib/jarvis-ueberwachung/zustand\\.json$ f VarFile" in sk,
       "AIDE fuehrt den Zustand als wechselnde Datei (sonst taeglicher Fund)")
pruefe(str(ue.ZUSTAND_DATEI).startswith("/var/lib/jarvis-ueberwachung/"),
       "Zustandsdatei liegt im StateDirectory der Unit")

# ── 13. Endpunkt ─────────────────────────────────────────────────────────────
print("[13] Endpunkt")
mb = ast.parse(MAIN.read_text(encoding="utf-8"))
fn = None
for n in ast.walk(mb):
    if isinstance(n, ast.AsyncFunctionDef):
        for dek in n.decorator_list:
            if isinstance(dek, ast.Call) and getattr(dek.func, "attr", "") == "get" and dek.args \
                    and isinstance(dek.args[0], ast.Constant) and dek.args[0].value == "/api/system/ueberwachung":
                fn = n
pruefe(fn is not None, "GET /api/system/ueberwachung existiert")
if fn is not None:
    deps = [d for d in fn.args.defaults if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "Depends"]
    pruefe(any(isinstance(d.args[0], ast.Name) and d.args[0].id == "require_local_auth" for d in deps if d.args),
           "nur fuer Administratoren (Depends(require_local_auth))")
    aufrufe = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
    pruefe(any(getattr(c.func, "attr", "") == "to_thread" and c.args
               and getattr(c.args[0], "attr", "") == "lesen" for c in aufrufe),
           "liest ueber asyncio.to_thread(<ueberwachung>.lesen)")

print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)

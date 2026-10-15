#!/usr/bin/env python3
"""Gegenprobe zu den MITTEL-Befunden aus dem Code-Review 2026-10-07.

Je Probe wird EINE Schranke zurueckgedreht und Exit 1 des zustaendigen
Waechters verlangt:

  * Clickjacking ueber /static/addin/..%2F           -> test_bsi_h7.py
  * gespeichertes Geheimnis an eine neue Adresse      -> test_bsi_m5.py, test_bsi_m5_ui.js
  * Hauptschluessel fehlt: Chiffrat als Signierschl.  -> test_bsi_m5.py
  * CSP-Meldepfad: Flut ohne Obergrenze               -> test_csp_h4.py
  * /api/stt und Sammel-Loeschen im Event-Loop        -> test_event_loop_review.py
  * Zip-Bombe im Destillat                            -> test_wissen_destillat.py
  * WebDAV mit jarvis/jarvis                          -> test_webdav_kennwort.py
  * abgebrochener SSH-Test laesst SSH_ROOT stehen     -> test_fernzugang.py
  * firewall.sh --test: Rueckfall nur IPv4 / ohne Timer -> test_firewall_rueckfall.py
  * verschluckte Fehler beim Entfernen/Aktualisieren  -> test_wissen_docedit_ui.js
  * cfbBearbeiten-Wettlauf                            -> test_cf_bindung_ui.js
  * Inhalte des Vorgaengers nach dem Abmelden         -> test_wissen_abmelden_ui.js
  * Confluence-Blaettern                              -> test_cf_abgleich.py

Ablauf wie gegen_review_hoch.py (gruene Basis, Sicherung im HOME, Laufmarke,
md5, ohne Bytecode, SIGTERM/SIGINT ueber ``finally``).
NICHT in einem Sammellauf ueber ``tests/*`` mitlaufen lassen – patcht den Baum.

Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
PY = Path(WURZEL / "venv" / "bin" / "python")
PY = str(PY) if PY.is_file() else sys.executable


def _py(n):
    return [PY, str(WURZEL / "tests" / n)]


def _js(n):
    return ["node", str(WURZEL / "tests" / n)]


W_H7 = _py("test_bsi_h7.py")
W_M5 = _py("test_bsi_m5.py")
W_M5UI = _js("test_bsi_m5_ui.js")
W_CSP = _py("test_csp_h4.py")
W_LOOP = _py("test_event_loop_review.py")
W_DEST = _py("test_wissen_destillat.py")
W_DAV = _py("test_webdav_kennwort.py")
W_FZ = _py("test_fernzugang.py")
W_FW = _py("test_firewall_rueckfall.py")
W_DOC = _js("test_wissen_docedit_ui.js")
W_CFB = _js("test_cf_bindung_ui.js")
W_ABM = _js("test_wissen_abmelden_ui.js")
W_CFA = _py("test_cf_abgleich.py")
WAECHTER_ALLE = [W_H7, W_M5, W_M5UI, W_CSP, W_LOOP, W_DEST, W_DAV, W_FZ, W_FW, W_DOC, W_CFB,
                 W_ABM, W_CFA]
SICHERUNG = Path.home() / ".gegen_review_mittel"
MARKE = SICHERUNG / "laeuft"

SK = "backend/sicherheits_kopf.py"
CSP = "backend/csp.py"
MAIN = "backend/main.py"
SR = "backend/secret_reveal.py"
SKEY = "backend/secret_key.py"
WDS = "backend/wissen_destillat.py"
DAV = "backend/webdav.py"
FZ = "backend/broker/fernzugang.py"
FW = "deploy/security/firewall.sh"
CC = "backend/confluence_client.py"
CFA = "backend/confluence_abgleich.py"
CF_JS = "frontend/js/confluence.js"
SKC = "frontend/js/skillcfg.js"
KBM = "frontend/js/kbmatrix.js"
WJS = "frontend/js/wissen.js"
ERFASST = [SK, CSP, MAIN, SR, SKEY, WDS, DAV, FZ, FW, CC, CFA, CF_JS, SKC, KBM, WJS]

PROBEN = [
    # ── Clickjacking ──
    ("H7: X-Frame-Options wieder am rohen Pfad", SK,
     "    pfad = _pfad_normal(pfad)\n    if not any(pfad.startswith(p) for p in ADDIN_PRAEFIXE):\n",
     "    if not any((pfad or \"\").startswith(p) for p in ADDIN_PRAEFIXE):\n", W_H7),
    ("CSP: frame-ancestors wieder am rohen Pfad", CSP,
     "    pfad = pfad_normal(pfad)\n    addin = any(pfad.startswith(p) for p in _ADDIN_PRAEFIXE)\n",
     "    addin = any((pfad or \"\").startswith(p) for p in _ADDIN_PRAEFIXE)\n", W_H7),
    ("CSP: /novnc/-Ausnahme wieder am rohen Pfad", CSP,
     "pfad_normal(pfad).startswith(p) for p in _AUSGENOMMEN",
     "(pfad or \"\").startswith(p) for p in _AUSGENOMMEN", W_H7),
    # ── Geheimnis an neue Adresse ──
    ("Skill-Config: Umleitung wird nicht abgewiesen", MAIN,
     "    umgeleitet = _sr.umgeleitete_geheimnisse(body, gespeichert)\n    if umgeleitet:\n",
     "    umgeleitet = _sr.umgeleitete_geheimnisse(body, gespeichert)\n    if False:\n", W_M5),
    ("Skill-Config: weggelassenes Geheimnis zaehlt nicht als behalten", SR,
     "and (n.get(k) == \"\" or (not pfad and k not in n))]",
     "and n.get(k) == \"\"]", W_M5),
    ("Skill-Config: ohne Paarung (fremder Zugang blockiert den Umzug)", SR,
     "                if _bindet(g, _gruppe(k), gruppen, geheimnisse):\n",
     "                if True:\n", W_M5),
    ("Profil: neue Adresse behaelt den Schluessel", MAIN,
     "        if behalten and str(prof.get(feld) or \"\"):\n            return True\n",
     "        if behalten and str(prof.get(feld) or \"\"):\n            return False\n", W_M5),
    ("Oberflaeche: confluence.js meldet Ablehnung wieder als Gespeichert", CF_JS,
     "if (!r.ok || (d && d.success === false)) throw d || {};",
     "if (false) throw d || {};", W_M5UI),
    ("Oberflaeche: skillcfg.js ohne Hinweis 'neu eingeben'", SKC,
     "                    if (d && d.code === 'geheimnis_neu_eingeben') {\n",
     "                    if (false) {\n", W_M5UI),
    # ── Hauptschluessel ──
    ("Hauptschluessel fehlt: Chiffrat wieder als Signierschluessel", SKEY,
     "                  \"(Prozess ueber systemd mit LoadCredential starten).\", flush=True)\n"
     "            return secrets.token_hex(32)\n",
     "                  \"(Prozess ueber systemd mit LoadCredential starten).\", flush=True)\n"
     "            return wert\n", W_M5),
    # ── CSP-Flut ──
    ("CSP: keine Tages-Obergrenze", CSP,
     "                if _tag_zeilen.get(tag, 0) >= TAG_MAX_ZEILEN:\n                    continue\n",
     "", W_CSP),
    ("CSP: Zaehler-Speicher unbegrenzt", CSP,
     "                    if len(_gesehen) >= GESEHEN_MAX:\n                        continue\n",
     "", W_CSP),
    ("CSP: volle Datei waechst weiter", CSP,
     "            if not neu and p.stat().st_size >= DATEI_MAX:\n",
     "            if False:\n", W_CSP),
    # ── Event-Loop ──
    ("/api/stt: Modell wieder im Event-Loop", MAIN,
     "    if await asyncio.to_thread(_get_whisper_model, source=\"voice_browser\") is None:\n",
     "    if _get_whisper_model(source=\"voice_browser\") is None:\n", W_LOOP),
    ("Sammel-Loeschen: rmtree wieder im Event-Loop", MAIN,
     "    ergebnis = await asyncio.to_thread(lambda: [(sid, cs.delete_session(user, sid)) for sid in ids])\n",
     "    ergebnis = [(sid, cs.delete_session(user, sid)) for sid in ids]\n", W_LOOP),
    # ── Zip-Bombe ──
    ("Destillat: Archiv-Pruefung vor den Lesern fehlt", WDS,
     "        if zu_gross:\n", "        if False:\n", W_DEST),
    ("Destillat: Teil-Groesse im eigenen Leser ungeprueft", WDS,
     "    if z.getinfo(name).file_size > grenze:\n", "    if False:\n", W_DEST),
    # ── WebDAV ──
    ("WebDAV: wieder mit jarvis/jarvis", DAV,
     [("    if not cfg.get(\"password\"):\n        _log.warning",
       "    if False:\n        _log.warning"),
      ("    password = cfg[\"password\"]\n", "    password = cfg.get(\"password\", \"jarvis\")\n")],
     W_DAV, 1),
    ("WebDAV: Status wieder fest 'gesetzt'", MAIN,
     "        \"password_gesetzt\": bool(cfg.get(\"password\")),\n",
     "        \"password_gesetzt\": True,\n", W_DAV),
    ("WebDAV: Einschalten ohne Kennwort erlaubt", MAIN,
     "    if webdav.get(\"enabled\") and not webdav.get(\"password\"):\n",
     "    if False:\n", W_DAV),
    ("WebDAV: Ablehnung aendert den Zustand im Speicher schon", MAIN,
     "    webdav = dict(kb_cfg.get(\"webdav\", {}))\n",
     "    webdav = kb_cfg.get(\"webdav\", {})\n", W_DAV),
    # ── SSH / Firewall ──
    ("SSH-Test: SSH_ROOT bleibt nach Abbruch stehen", FZ,
     "            if r is None or r.returncode != 0:\n", "            if False:\n", W_FZ),
    ("firewall.sh: Rueckfall wieder nur IPv4", FW,
     "'iptables-restore \"$1\"; if [ -s \"$2\" ]; then ip6tables-restore \"$2\"; fi'",
     "'iptables-restore \"$1\"'", W_FW),
    ("firewall.sh: laufender Test wird ueberschrieben", FW,
     "        if systemctl is-active --quiet fw-rollback.timer; then\n",
     "        if false; then\n", W_FW),
    ("firewall.sh: ohne Rueckfall-Timer werden Regeln gesetzt", FW,
     "        if [[ $? -ne 0 ]]; then\n            echo \"ABBRUCH: Rueckfall-Timer",
     "        if false; then\n            echo \"ABBRUCH: Rueckfall-Timer", W_FW),
    # ── verschluckte Fehler ──
    ("kbmatrix: Datei-DELETE-Ablehnung wieder verschluckt", KBM,
     "        if (!r1.ok || (d1 && d1.ok === false)) throw",
     "        if (false) throw", W_DOC),
    ("wissen.js: PATCH-Antwort wieder ungeprueft", WJS,
     "                    if (!r.ok || !d || d.ok !== true) throw new Error((d && d.error) || httpHint(r.status));\n",
     "                    if (false) throw new Error('');\n", W_DOC),
    # ── Wettlauf / Abmelden ──
    ("cfbBearbeiten: spaete Antwort wieder ungeprueft", WJS,
     "                if (lauf !== _cfbEditLauf) return;\n                if (a.ganz)",
     "                if (a.ganz)", W_CFB),
    ("Abmelden: wieder nur die Maske", WJS,
     "        if (_hattSitzung) { frischeSeite(); return; }\n        showLogin();\n",
     "        showLogin();\n", W_ABM),
    ("Neue Anmeldung: wieder in die alte Seite", WJS,
     "                    if (_hattSitzung) { frischeSeite(); return; }\n                    loadScope();\n",
     "                    loadScope();\n", W_ABM),
    # ── Confluence-Blaettern ──
    ("Blaettern: wieder an 'weniger als verlangt'", CC,
     "            return bool(links.get(\"next\"))\n",
     "            return len(results) >= page\n", W_CFA),
    ("Blaettern: weiter um len(results) (doppelte Seiten)", CC,
     "            return int(d[\"start\"]) + int(d[\"limit\"])\n",
     "            return start + len(results)\n", W_CFA),
    ("Abgleich: gekappte Liste loescht den Rest", CFA,
     "            if len(liste) >= MAX_SEITEN_JE_BEREICH:\n", "            if False:\n", W_CFA),
]
DATEIEN = sorted({p[1] for p in PROBEN})

_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(cmd):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    e = subprocess.run(cmd, cwd=WURZEL, capture_output=True, text=True, timeout=300, env=env)
    return e.returncode, e.stdout + e.stderr


def zurueck():
    for rel in DATEIEN:
        s = SICHERUNG / rel.replace("/", "__")
        if s.is_file():
            shutil.copyfile(s, WURZEL / rel)


def _signal(signum, _frame):
    raise SystemExit(128 + signum)


if set(DATEIEN) - set(ERFASST):
    print("ABBRUCH (Exit 2): Proben fassen ungesicherte Dateien an: %s"
          % sorted(set(DATEIEN) - set(ERFASST)))
    sys.exit(2)

if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

for cmd in WAECHTER_ALLE:
    rc, aus = lauf(cmd)
    if rc != 0:
        print("ABBRUCH (Exit 2): Basislauf %s nicht gruen (Exit %d)." % (Path(cmd[-1]).name, rc))
        print(aus[-1500:])
        sys.exit(2)
print("Basislauf aller Waechter gruen.\n")

SICHERUNG.mkdir(mode=0o700, exist_ok=True)
for rel in DATEIEN:
    shutil.copyfile(WURZEL / rel, SICHERUNG / rel.replace("/", "__"))
soll = {rel: md5(WURZEL / rel) for rel in DATEIEN}
MARKE.write_text("laeuft", encoding="utf-8")
signal.signal(signal.SIGTERM, _signal)
signal.signal(signal.SIGINT, _signal)
try:
    for probe in PROBEN:
        if isinstance(probe[2], list):
            name, rel, schritte, waechter, erwartet = probe
        else:
            name, rel, alt, neu, waechter = probe
            schritte, erwartet = [(alt, neu)], 1
        pfad = WURZEL / rel
        quelle = pfad.read_text(encoding="utf-8")
        treffer = [quelle.count(a) for a, _n in schritte]
        if treffer != [1] * len(schritte):
            pruefe(False, "%s -> Anker eindeutig" % name, "Treffer %s" % treffer)
            continue
        for a, n in schritte:
            quelle = quelle.replace(a, n)
        pfad.write_text(quelle, encoding="utf-8")
        rc, _aus = lauf(waechter)
        pruefe(rc == erwartet, "%s -> %s Exit %d" % (name, Path(waechter[-1]).name, erwartet),
               "Exit %d" % rc)
        zurueck()
        pruefe(md5(pfad) == soll[rel], "%s -> Datei byte-gleich zurueck" % name)
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for rel in DATEIEN:
    pruefe(md5(WURZEL / rel) == soll[rel], "%s unveraendert" % rel)
for cmd in WAECHTER_ALLE:
    rc, _ = lauf(cmd)
    pruefe(rc == 0, "Abschlusslauf %s gruen" % Path(cmd[-1]).name, "Exit %d" % rc)
shutil.rmtree(SICHERUNG, ignore_errors=True)

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)

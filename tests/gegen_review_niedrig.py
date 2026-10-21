#!/usr/bin/env python3
"""Gegenprobe zu den NIEDRIG-Befunden aus dem Code-Review 2026-10-07.

Je Probe wird EINE Schranke zurueckgedreht und Exit 1 des zustaendigen
Waechters verlangt (bei einer Kombination steht der erwartete Exit dabei):

  * Sitzung/Widerruf, /ws/users, verify-token, Sicherheitsprotokoll
                                                  -> test_review_niedrig_sitzung.py
  * Abruf-Schluessel endet mit der Sitzung        -> test_download_key.py
  * /api/stt Deckel/Gleichzeitigkeit, AD-Test      -> test_event_loop_review.py
  * Beschriftung /api/stt                          -> test_aktion_beschriftung.py
  * Broker-Policy fail-closed, davfs2-Zugang       -> test_broker_niedrig.py
  * node_aktualisieren.sh                          -> test_bsi_m6_m7.py
  * Destillat -> Confluence mit eigenem Zugang     -> test_destillat_confluence.py
  * Importzeiten im Thread, Listen-Obergrenzen     -> test_cfb_importdatum_api.py
  * Confluence-Zugaenge: Sperre, unlesbare Datei   -> test_confluence_accounts.py
  * Bild-Vorhaltefrist                             -> test_bilddaten_bergen.py
  * Oberflaeche                                    -> test_review_niedrig_ui.js,
                                                     test_cron_log_ui.js

Ablauf wie gegen_review_mittel.py (gruene Basis, Sicherung im HOME, Laufmarke,
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


W_SN = _py("test_review_niedrig_sitzung.py")
W_DL = _py("test_download_key.py")
W_LOOP = _py("test_event_loop_review.py")
W_AB = _py("test_aktion_beschriftung.py")
W_BR = _py("test_broker_niedrig.py")
W_M6 = _py("test_bsi_m6_m7.py")
W_DC = _py("test_destillat_confluence.py")
W_IZ = _py("test_cfb_importdatum_api.py")
W_CA = _py("test_confluence_accounts.py")
W_BB = _py("test_bilddaten_bergen.py")
W_UI = _js("test_review_niedrig_ui.js")
W_CL = _js("test_cron_log_ui.js")
WAECHTER_ALLE = [W_SN, W_DL, W_LOOP, W_AB, W_BR, W_M6, W_DC, W_IZ, W_CA, W_BB, W_UI, W_CL]
SICHERUNG = Path.home() / ".gegen_review_niedrig"
MARKE = SICHERUNG / "laeuft"

MAIN = "backend/main.py"
ST = "backend/sitzung_token.py"
SL = "backend/sicherheits_log.py"
POL = "backend/broker/policy.py"
META = "backend/broker/meta.py"
OPS = "backend/broker/ops.py"
NODE = "deploy/security/node_aktualisieren.sh"
CA = "backend/confluence_accounts.py"
AG = "backend/agent.py"
SAD = "frontend/js/settings_ad.js"
SEC = "frontend/js/security_incidents.js"
SYS = "frontend/js/sysload.js"
KAM = "frontend/js/settings_kamerabild.js"
API = "frontend/js/api_doku.js"
CRON = "frontend/js/cron.js"
DES = "frontend/js/wissen_destillat.js"
KNW = "frontend/js/knowledge.js"
LDD = "backend/ldap_directory.py"
WJS = "frontend/js/wissen.js"
KH = "frontend/js/konto_hinweise.js"
FB = "frontend/js/feedback.js"
CP = "frontend/js/claude_portal.js"
AM = "frontend/js/ai_mouse.js"
I18N = "frontend/js/i18n.js"
ERFASST = [MAIN, ST, SL, POL, META, OPS, NODE, CA, AG, SAD, SEC, SYS, KAM, API, CRON, DES, KNW,
           WJS, KH, FB, CP, AM, I18N, LDD]

PROBEN = [
    # ── Sitzung und Widerruf ──
    ("Sitzungsablage unlesbar: startet wieder leer", ST,
     "        _alle_vor = int(time.time())\n", "        _alle_vor = 0\n", W_SN),
    ("Sitzungsablage: Sperre 'alle vorher' wird nicht geprueft", ST,
     "        if k in _widerrufen or (_alle_vor and ts < _alle_vor):\n",
     "        if k in _widerrufen:\n", W_SN),
    ("sitzung_besteht: abgemeldete Sitzung gilt weiter", ST,
     "        return str(kennung) not in _widerrufen\n", "        return True\n", W_SN),
    ("Widerrufsdatei unlesbar: startet wieder leer", MAIN,
     "        _revoked_logins = {_WIDERRUF_ALLE: int(time.time())}\n",
     "        _revoked_logins = {}\n", W_SN),
    ("Epoche 'alle vorher' wird nicht geprueft", MAIN,
     "    return bool(alle) and int(ts) < alle\n", "    return False\n", W_SN),
    ("Widerrufsdatei wieder an Ort und Stelle geschrieben (nicht atomar)", MAIN,
     "        tmp = _REVOKED_FILE.with_name(f\"{_REVOKED_FILE.name}.{os.getpid()}.tmp\")\n",
     "        tmp = _REVOKED_FILE\n", W_SN),
    ("verify-token: wieder 30 Tage", MAIN,
     "            remaining = max(0, _sitzung.max_alter_s() - (time.time() - int(ts)))\n",
     "            remaining = max(0, 2592000 - (time.time() - int(ts)))\n", W_SN),
    ("require_admin_or_query: gesperrtes Konto kommt durch", MAIN,
     "    if security_guard.is_blocked(username):\n        raise HTTPException(status_code=403, detail=\"ACCOUNT_BLOCKED\")\n"
     "    if not _user_is_admin(username):\n",
     "    if not _user_is_admin(username):\n", W_SN),
    ("/ws/users: keine Pruefung je Nachricht", MAIN,
     "            grund = _uc_sitzung_ungueltig(token_str)\n            if grund:\n"
     "                await _uc_sitzung_beenden(ws, grund)\n                break\n", "", W_SN),
    ("/ws/users: kein Waechter fuer stille Verbindungen", MAIN,
     "        waechter = asyncio.create_task(_uc_waechter(ws, token_str))\n", "", W_SN),
    ("Sicherheitsprotokoll: wieder ohne Schluessel geschrieben", SL,
     "            if _mac_schluessel:\n                eintrag[\"mac\"] = 1\n", "", W_SN),
    ("Sicherheitsprotokoll: letzte Zeile ohne Schluessel faellt nicht auf", SL,
     "    if _mac_schluessel and letzte_ohne_mac and letzte_ohne_mac[1]:\n", "    if False:\n", W_SN),
    # ── Abruf-Schluessel ──
    ("Abruf-Schluessel: abgemeldete Sitzung wird nicht geprueft", MAIN,
     "                or not _sitzung.sitzung_besteht(sitz[1], sitz[0])):\n", "                or False):\n", W_DL),
    ("Abruf-Schluessel: Epoche wird nicht geprueft", MAIN,
     "                _epoche_widerrufen(name, sitz[0])\n", "                False\n", W_DL),
    # ── /api/stt und AD ──
    ("/api/stt: angekuendigte Laenge wird nicht vorab geprueft", MAIN,
     "    if angekuendigt > max_bytes:\n        return None\n", "", W_LOOP),
    ("/api/stt: Lesen bricht an der Grenze nicht ab", MAIN,
     "        if n > max_bytes:\n            return None\n", "", W_LOOP),
    ("/api/stt: Transkriptionen ohne Deckel", MAIN,
     "        async with _stt_sem:\n            text = await asyncio.to_thread(\n"
     "                _transcribe_audio, pfad, sprache, \"Jarvis Sprachsteuerung:\", \"voice_browser\")\n",
     "        text = await asyncio.to_thread(\n"
     "            _transcribe_audio, pfad, sprache, \"Jarvis Sprachsteuerung:\", \"voice_browser\")\n", W_LOOP),
    # Der Verbindungstest liegt seit 2026-10-21 in ldap_directory.erreichbar()
    ("AD testen: wieder im Event-Loop", MAIN,
     "        await asyncio.to_thread(ldap_directory.erreichbar, ad_server, 5)\n",
     "        ldap_directory.erreichbar(ad_server, 5)\n", W_LOOP),
    ("AD testen: Verbindung bleibt offen", LDD,
     "        conn.open()\n    finally:\n        try:\n            conn.unbind()\n"
     "        except Exception:  # noqa: BLE001\n            pass\n",
     "        conn.open()\n    finally:\n        pass\n", W_LOOP),
    ("Beschriftung: /api/stt ohne Eintrag", MAIN,
     "    (\"POST\",   r\"/api/stt\",                             \"Chat · Spracheingabe\"),\n", "", W_AB),
    # ── Broker ──
    ("Policy: kaputte Datei gilt wieder als leer", POL,
     "        except PolicyUnlesbar as e:\n            print(\"[Broker-Policy] \" + MELDUNG_UNLESBAR % e, flush=True)\n"
     "            return DENY\n",
     "        except PolicyUnlesbar:\n            data = {\"version\": 1, \"ops\": {}}\n", W_BR),
    ("Policy: Broker-Start stuerzt an kaputter Datei ab", POL,
     "            print(\"[Broker-Policy] \" + MELDUNG_UNLESBAR % e, flush=True)\n            return []\n",
     "            raise\n", W_BR),
    ("Policy: Admin-Ops werfen statt zu melden", META,
     "    except policy.PolicyUnlesbar as e:\n        return {\"ok\": False, \"error\": policy.MELDUNG_UNLESBAR % e}\n",
     "    except ZeroDivisionError:\n        return {}\n", W_BR),
    ("davfs2: Steuerzeichen nicht geprueft", OPS,
     "        if any(ord(c) < 32 or ord(c) == 127 for c in (wert or \"\")):\n", "        if False:\n", W_BR),
    ("davfs2: wieder Teilstring-Vergleich", OPS,
     "        if erstes == [mp]:\n", "        if mp in z:\n", W_BR),
    ("davfs2: Felder ungequotet", OPS,
     "    return '\"' + wert.replace(\"\\\\\", \"\\\\\\\\\").replace('\"', '\\\\\"') + '\"'\n",
     "    return wert\n", W_BR),
    # ── node_aktualisieren.sh ──
    ("Node: Schranke vor der Installation wirkungslos", NODE,
     "    [ \"${JARVIS_NODE_AUTO:-}\" = \"1\" ] || return 0\n    local f\n", "    return 0\n    local f\n", W_M6),
    ("Node: echte Installation ohne Schranke", NODE,
     "_schranke_auto \"$tmp/sim_echt\" || exit $?\n", "", W_M6),
    ("Node: npm rebuild wieder als root", NODE,
     "        if [ \"$eigner\" = \"root\" ] || [ -z \"$eigner\" ]; then\n", "        if false; then\n", W_M6),
    # ── Wissen ──
    ("Destillat -> Confluence: Zugang des Benutzers ungeprueft", MAIN,
     "    if not c.configured:\n        return JSONResponse({\"ok\": False, \"error\": \"Confluence ist nicht aktiv oder nicht konfiguriert.\"},\n"
     "                            status_code=400)\n", "", W_DC),
    ("Importzeiten wieder im Event-Loop", MAIN,
     "            zeiten = (await asyncio.to_thread(_cfa.import_zeiten))[\"seiten\"]\n",
     "            zeiten = _cfa.import_zeiten()[\"seiten\"]\n", W_IZ),
    ("Listen-Obergrenze wieder fest 500", MAIN,
     "_CF_MAX_BEREICHE = 5000\n", "_CF_MAX_BEREICHE = 500\n", W_IZ),
    ("Confluence-Zugaenge: unlesbare Datei wird ueberschrieben", CA,
     "    try:\n        alle = _laden_streng()\n    except KontenUnlesbar as e:\n        raise ConfluenceKontoFehler(\n"
     "            \"Die gespeicherten Confluence-Zugaenge sind nicht lesbar (%s) – \"\n            \"es wird nichts ueberschrieben.",
     "    try:\n        alle = _laden()\n    except KontenUnlesbar as e:\n        raise ConfluenceKontoFehler(\n"
     "            \"Die gespeicherten Confluence-Zugaenge sind nicht lesbar (%s) – \"\n            \"es wird nichts ueberschrieben.", W_CA),
    ("Confluence-Zugaenge: Altstand (keine Sperre, feste .tmp)", CA,
     [("    with _SPERRE:\n        _speichern_unter_sperre(un, felder)\n", "    _speichern_unter_sperre(un, felder)\n"),
      ("    with _SPERRE:\n        _merke_unter_sperre(un, ok, fehler, anzeigename, konto)\n",
       "    _merke_unter_sperre(un, ok, fehler, anzeigename, konto)\n"),
      ("    tmp = KONTEN_DATEI.with_name(\"%s.%d.%d.tmp\" % (KONTEN_DATEI.name, os.getpid(),\n"
       "                                                    threading.get_ident()))\n",
       "    tmp = KONTEN_DATEI.with_suffix(\".tmp\")\n")], W_CA, 1),
    ("Bild-Vorhaltefrist: Wiederverwendung frischt nicht auf", AG,
     "                        _os.utime(ziel)\n", "                        pass\n", W_BB),
    # ── Oberflaeche ──
    ("settings_ad: wieder feste Farbe statt Klasse", SAD,
     "        el.classList.add('jv-hinweis-' + art);\n", "        el.style.color = '#f59e0b';\n", W_UI),
    ("settings_ad: Freigabe-Text wieder fest", SAD,
     "        if (!users && !group) _hinweis(el, 'warn', window.t(pre + '_none'));\n",
     "        if (!users && !group) _hinweis(el, 'warn', 'Niemand ist freigeschaltet.');\n", W_UI),
    ("Sandbox-Kaestchen: Ablehnung stellt nicht zurueck", SEC,
     "                      zurueck();\n                      return;\n", "                      return;\n", W_UI),
    ("Sandbox-Kaestchen: Netzfehler stellt nicht zurueck", SEC,
     "                  zurueck();\n              });\n", "              });\n", W_UI),
    ("Sicherheits-Reiter: Statuspunkt wieder Emoji", SEC,
     "_P('err') + '<b>' + esc(T('security.sandbox_none',", "'\U0001F534 <b>' + esc(T('security.sandbox_none',", W_UI),
    ("sysload: misst auch im Hintergrund-Tab", SYS,
     "        if (document.hidden) return;\n        _timer = setTimeout(abrufen, TAKT_MS);\n",
     "        _timer = setTimeout(abrufen, TAKT_MS);\n", W_UI),
    ("Kamerabild: auch im Hintergrund-Tab", KAM,
     "        if (document.hidden) return;\n        var tab", "        var tab", W_UI),
    ("API-Doku: Zaehler auch im Hintergrund-Tab", API,
     "setInterval(function () { if (!document.hidden) refreshForeignCounts(); }, 15000);",
     "setInterval(refreshForeignCounts, 15000);", W_UI),
    ("API-Doku: Schloss wieder als Emoji", API,
     "'<span class=\"ep-lock\" title=\"' + esc(T('api.lock_ep')) + '\">' + _schloss() + '</span>'",
     "'<span class=\"ep-lock\" title=\"' + esc(T('api.lock_ep')) + '\">\U0001F512</span>'", W_UI),
    ("cron: Platzhalter wieder als zweites Argument", CRON,
     "window.t('cron.log_load_err').replace('{e}', d.fehler)", "window.t('cron.log_load_err', { e: d.fehler })", W_UI),
    ("cron: Platzhalter wieder als zweites Argument (Protokoll-Pruefstand)", CRON,
     "window.t('cron.log_load_err').replace('{e}', d.fehler)", "window.t('cron.log_load_err', { e: d.fehler })", W_CL),
    ("cron: Datum wieder fest deutsch", CRON,
     "function _cronOrt() { return window._lang === 'en' ? 'en-GB' : 'de-DE'; }",
     "function _cronOrt() { return 'de-DE'; }", W_UI),
    ("Destillat: Nicht-JSON wirft wieder", DES,
     "        return r.json().catch(function () { return null; })\n", "        return r.json()\n", W_UI),
    ("Destillat: roher Fehlertext im Status", DES,
     "                status('wi-dest-takestatus', t('wissen.dest_take_failed'), 'err');\n            })\n",
     "                status('wi-dest-takestatus', String(e && e.message || e), 'err');\n            })\n", W_UI),
    ("Destillat: Zuruecksetzen laesst Marke stehen", DES,
     "        if (p) { delete p.dataset.beruehrt; p.value", "        if (p) { p.value", W_UI),
    ("Gelerntes Wissen: Titel wieder roh", KNW,
     "title=\"${this._escHtml(f.path)}\">${this._escHtml(f.title)}</span>",
     "title=\"${f.path}\">${f.title}</span>", W_UI),
    ("wissen.js: Status wieder mit Emoji", WJS,
     "cfbStatus('✓ ' + t(edit ? 'wissen.cfb_saved' : 'wissen.cfb_added', { n: nm }));",
     "cfbStatus('\u2705 ' + t(edit ? 'wissen.cfb_saved' : 'wissen.cfb_added', { n: nm }));", W_UI),
    ("feedback.js: Rueckfall wieder wirkungslos", FB,
     "        return (window.t && window.t(key) !== key ? window.t(key) : null) || fallback;\n",
     "        return (window.t ? window.t(key, fallback) : fallback) || fallback;\n", W_UI),
    ("claude_portal.js: Rueckfall wieder wirkungslos", CP,
     "        return (window.t && window.t(key) !== key ? window.t(key) : null) || fallback;\n",
     "        return (window.t ? window.t(key, fallback) : null) || fallback;\n", W_UI),
    ("ai_mouse.js: Rueckfall wieder wirkungslos", AM,
     "        return (window.t && window.t(key) !== key ? window.t(key) : null) || fallback;\n",
     "        return (window.t ? window.t(key) : fallback) || fallback;\n", W_UI),
    ("wissen.js: Laufanzeiger wieder als Sanduhr-Zeichen", WJS,
     "'<span class=\"wi-hourglass\" aria-hidden=\"true\"></span>' + esc(m)",
     "'<span class=\"wi-hourglass\">\u23f3</span>' + esc(m)", W_UI),
    ("i18n: Fortschrittstext wieder mit Sanduhr", I18N,
     "        'wissen.cf_starting': 'Import wird gestartet…',",
     "        'wissen.cf_starting': '\u23f3 Import wird gestartet…',", W_UI),
    ("Konto-Hinweise: Merker wieder ein Stueck des Tokens", KH,
     "    function merkerWert(tok) {\n", "    function merkerWert(tok) {\n        return tok.slice(-16);\n", W_UI),
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

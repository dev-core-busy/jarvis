#!/usr/bin/env python3
"""Gegenprobe zu den Fixes aus dem Code-Review vom 2026-10-18.

Je Probe wird EINE tragende Stelle zurueckgedreht und Exit 1 des zustaendigen
Waechters verlangt (mindestens ein FAIL, kein Abbruch). Ablauf wie die
uebrigen gegen_*: gruene Basis ALLER beteiligten Waechter, Sicherung im HOME,
Laufmarke, md5-Kontrolle danach, ohne Bytecode. SIGTERM laeuft ueber
``finally``. NICHT in einem Sammellauf ueber ``tests/*`` mitlaufen lassen –
patcht den Baum.

Aufruf: ``python3 tests/gegen_review_20261018.py [Teilname]`` – mit Argument
nur die Proben, deren Name den Text enthaelt.
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
# Platzhalter: der Interpreter wird JE WAECHTER im Basislauf gewaehlt. Lokal fehlt
# dem venv numpy (test_bsi_m12 -> Exit 2), dem System-Python fastapi
# (test_agent_rechte -> Exit 2) – keiner der beiden traegt alle Waechter.
PY = "<py>"
_VENV = WURZEL / "venv" / "bin" / "python"
KANDIDATEN = ([str(_VENV)] if _VENV.is_file() else []) + [sys.executable]
GEWAEHLT = {}
SICHERUNG = Path.home() / ".gegen_review_20261018"
MARKE = SICHERUNG / "laeuft"


def py(name):
    return [PY, str(WURZEL / "tests" / name)]


def js(name):
    return ["node", str(WURZEL / "tests" / name)]


OPS = "backend/broker/ops.py"
DC = "backend/desktop_control.py"
K12 = py("test_broker_k1k2.py")
AG = "backend/agent.py"
MN = "backend/main.py"
AR = py("test_agent_rechte.py")
WBP = py("test_wa_bruecke.py")
POL = py("test_broker_policy_zaehler.py")
DAE = py("test_broker_daemon.py")
ZK = py("test_zert_kopie.py")
SOL = py("test_schreiben_ohne_link.py")
LT = py("test_lauf_tmp.py")
KERN = py("test_agent_kern.py")
SHL = py("test_shell_lesen.py")
ANT = py("test_anthropic_nachrichten.py")
KOM = py("test_kontext_kompression.py")
SKC = py("test_skill_modul_cache.py")
CHA = js("test_chatlib_attribut.js")
M12 = py("test_bsi_m12.py")
ATO = py("test_atomar.py")
AUR = py("test_auth_review.py")
WBJ = js("test_wa_bruecke_schutz.js")
IDX = "services/whatsapp-bridge/index.js"
SCH = "services/whatsapp-bridge/schutz.js"

# (Name, Datei, alt, neu, Waechter)
PROBEN = [
    # ── A2: chpasswd ──
    ("A2 Broker prueft das Kennwort nicht", OPS,
     "    fehler = kennwort_eingabe_fehler(password)\n    if fehler:\n",
     "    fehler = \"\"\n    if fehler:\n", K12),
    ("A2 Steuerzeichen-Regel fehlt", OPS,
     "    if any(ord(c) < 32 or ord(c) == 127 for c in kennwort):\n",
     "    if False:\n", K12),
    ("A2 Liste wird wieder zu Text", OPS,
     "    password = args.get(\"password\", \"\")   # KEIN str(): eine Liste ist kein Kennwort\n",
     "    password = str(args.get(\"password\", \"\"))\n", K12),
    ("A2 zweite Schranke in desktop_control fehlt", DC,
     "            or any(ord(c) < 32 or ord(c) == 127 for c in new_password)):\n",
     "            or False):\n", K12),
    # ── A3: unlock_screen ──
    ("A3 Broker nimmt jedes Ziel", OPS,
     "    if ziel not in _DESKTOP_USERS:\n        return {\"ok\": False, \"rc\": -1, \"stdout\": \"\",\n"
     "                \"stderr\": f\"Ziel '{ziel[:40]!r}' nicht erlaubt",
     "    if False:\n        return {\"ok\": False, \"rc\": -1, \"stdout\": \"\",\n"
     "                \"stderr\": f\"Ziel '{ziel[:40]!r}' nicht erlaubt", K12),
    ("A3 desktop_control prueft das Ziel nicht", DC,
     "    if not isinstance(target_user, str) or not re.fullmatch(r\"[a-z_][a-z0-9_-]{0,31}\", target_user):\n",
     "    if not isinstance(target_user, str):\n", K12),
    # ── A4: Unter-Agenten gehoeren ihrem Auftraggeber ──
    ("A4 Folgeauftrag ohne Besitzerpruefung", MN,
     "                if not agent_manager.gehoert(target, _ws_user):\n",
     "                if False:\n", AR),
    ("A4 spawn_agent fuer jeden", MN,
     "        if not _ws_systemweit(_sp_user):\n",
     "        if False:\n", AR),
    ("A4 stop_all fuer jeden", MN,
     "            if agent_manager and _ws_systemweit(_st_user):\n                agent_manager.stop_all()\n",
     "            if agent_manager:\n                agent_manager.stop_all()\n", AR),
    ("A4 Liste ungefiltert", MN,
     "        agents = (agent_manager.get_all_info(fuer=None if _ws_systemweit(_gl_user) else _gl_user)\n",
     "        agents = (agent_manager.get_all_info()\n", AR),
    ("A4 _ws_systemweit nimmt leer als Admin", MN,
     "    return bool(benutzer) and benutzer in _LOCAL_PRIVILEGED_USERS\n",
     "    return benutzer in _LOCAL_PRIVILEGED_USERS\n", AR),
    ("A4 gehoert() ohne Normalisierung", AG,
     "        return bool(besitzer) and besitzer != _ANON_ACTOR and besitzer == besitzer_norm(benutzer)\n",
     "        return bool(besitzer) and besitzer != _ANON_ACTOR and besitzer == benutzer\n", AR),
    ("A4 Liste filtert nicht nach Besitzer", AG,
     "            if fuer is None or self.gehoert(a, fuer):\n",
     "            if True:\n", AR),
    ("A4 Altweg ohne Namen wieder privilegiert", AG,
     "            agent._current_actor_privileged = (bool(agent._current_username)\n"
     "                                               and parent._actor_is_privileged())\n",
     "            agent._current_actor_privileged = parent._actor_is_privileged()\n", AR),
    ("A4 kein Deckel fuer ruhende Unter-Agenten", AG,
     "        self._ruhende_sub_agenten_kappen()\n        parent = self.main_agent\n",
     "        parent = self.main_agent\n", AR),
    # ── A5: Marker nur am erzeugenden Werkzeug ──
    ("A5 Spawn-Marker in jedem Ergebnis", AG,
     "                    if ((not self.is_sub_agent) and self._liefert_auftrag(tool_name)\n",
     "                    if ((not self.is_sub_agent)\n", AR),
    ("A5 Delegations-Marker in jedem Ergebnis", AG,
     "        if self._liefert_auftrag(tool_name) and \"_delegate\" in result_str:\n",
     "        if \"_delegate\" in result_str:\n", AR),
    ("A5 Merkmal immer wahr", AG,
     "        return bool(getattr(werkzeug, \"liefert_agenten_auftrag\", False))\n",
     "        return True\n", AR),
    # ── A6: WhatsApp-Bridge ──
    ("A6 Bridge ohne Middleware", IDX, "app.use(schutz.pruefen);\n", "\n", WBJ),
    ("A6 /send-media liest wieder jeden Pfad", IDX,
     "        const buffer = fs.readFileSync(echt);\n", "        const buffer = fs.readFileSync(media_path);\n", WBJ),
    ("A6 Webhook ohne Geheimnis", SCH,
     "'Content-Length': koerper.length,\n                            ...kopfzeilen() };",
     "'Content-Length': koerper.length };", WBJ),
    ("A6 Pfadschranke ohne Ordnervergleich", SCH,
     "        if (path.dirname(echt) !== basis) return null;\n", "\n", WBJ),
    ("A6 Kopfvergleich immer wahr", SCH,
     "        if (!kopfStimmt(req.get(KOPF))) {\n", "        if (false) {\n", WBJ),
    ("A6 Backend-Webhook ohne Geheimnis", MN,
     "    if not _wab.pruefe(request.headers.get(_wab.KOPF)):\n", "    if False:\n", WBP),
    ("A6 leere Freigabeliste wieder offen", MN,
     "    if sender_clean not in allowed_list:\n", "    if allowed_list and sender_clean not in allowed_list:\n", WBP),
    ("A6 Sprachdatei-Pfad ungeprueft", MN,
     "        if not _wab.sprachdatei_erlaubt(media_path):\n", "        if False:\n", WBP),
    ("A6 Status-Abfrage ohne Geheimnis", "backend/tools/whatsapp.py",
     "            req = urllib.request.Request(f\"{BRIDGE_URL}/status\", method=\"GET\",\n"
     "                                         headers=_wa_bruecke.kopf())\n",
     "            req = urllib.request.Request(f\"{BRIDGE_URL}/status\", method=\"GET\")\n", WBP),
    ("A6 Reflexion wieder auf totem Pfad", "backend/tools/reflection.py",
     "                    f\"{BRIDGE_URL}/send\",\n", "                    \"http://localhost:3001/api/send\",\n", WBP),
    ("A6 Sprachschranke ohne realpath", "backend/wa_bruecke.py",
     "        echt = os.path.realpath(pfad)\n", "        echt = os.path.abspath(pfad)\n", WBP),
    # ── B: Broker ──
    ("B shell_root wieder ueber gekuerzten Text", OPS,
     "        lambda a: _shell_root_key(a.get(\"command\", \"\")),\n",
     "        lambda a: \"shell_root:\" + _norm_cmd(str(a.get(\"command\", \"\"))),\n", K12),
    ("B shell_root-Anzeige ohne bezifferte Kuerzung", OPS,
     "    return (f\"Root-Shell-Befehl ({len(cmd)} Zeichen, hier nur die ersten \"\n",
     "    return (f\"Root-Shell-Befehl: \" + \"\"\n", K12),
    ("B Mountpunkt wieder nur per Praefix", OPS,
     "    if not isinstance(mp, str) or not _MOUNTPUNKT_RE.fullmatch(mp):\n",
     "    if not isinstance(mp, str) or not mp.startswith(\"/mnt/\") or \"..\" in mp:\n", K12),
    ("B Mountpunkt-Symlink nicht geprueft", OPS,
     "        if _stat.S_ISLNK(st.st_mode):\n            return f\"Einhaengepunkt abgewiesen",
     "        if False:\n            return f\"Einhaengepunkt abgewiesen", K12),
    ("B Zertifikat folgt wieder dem Link", "backend/broker/zert_kopie.py",
     "        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=efd)\n",
     "        return os.open(name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=efd)\n", ZK),
    # (Probe "Zertifikat direkt statt Temp+rename" gestrichen: O_EXCL auf die
    #  vorhandene Zieldatei wirft – sie mass einen Absturz, keine Zusage; die
    #  Eigenschaft "kein Link wird verfolgt" belegt die Probe darueber.)
    ("B settings.json wieder durch Link geschrieben", "backend/config.py",
     "        os.replace(tmp, path)\n",
     "        open(path, \"w\").write(open(tmp).read()); os.unlink(tmp)   # folgt dem Link (Altstand)\n", SOL),
    ("B Policy schreibt wieder bei jeder Op", "backend/broker/policy.py",
     "            elif time.monotonic() - _letzter_flush >= ZAEHLER_FLUSH_S:\n",
     "            elif True:\n", POL),
    ("B Policy ohne Deckel fuer offene Eintraege", "backend/broker/policy.py",
     "            if offen >= PENDING_MAX:\n", "            if False:\n", POL),
    ("B Daemon ohne Lese-Limit", "backend/broker/daemon.py",
     "    server = await asyncio.start_unix_server(_handle, path=SOCKET_PATH,\n                                             limit=MAX_REQUEST_BYTES + 1)",
     "    server = await asyncio.start_unix_server(_handle, path=SOCKET_PATH)", DAE),
    ("B Daemon: lange Ops im kurzen Pool", "backend/broker/daemon.py",
     "                loop.run_in_executor(_LANG if lang else _KURZ,\n",
     "                loop.run_in_executor(_KURZ,\n", DAE),
    ("B timeout_arg ohne Grenzen", OPS,
     "    return max(1, min(t, OP_TIMEOUT_MAX))\n", "    return t\n", DAE),
    ("B ro-Bindung fremder Anhaenge erlaubt", "backend/lauf_tmp.py",
     "            if s.startswith(anh + \"/\") and not (eigen and (s == eigen or s.startswith(eigen + \"/\"))):\n",
     "            if False:\n", LT),
    # ── B/C: Agent ──
    ("C Werkzeug-Statistik wieder am geteilten Agenten", AG,
     "    s = _lauf_stats_cv.get()\n    return s if s is not None else []\n",
     "    global _GLOBAL_STATS\n    try:\n        return _GLOBAL_STATS\n    except NameError:\n        _GLOBAL_STATS = []\n        return _GLOBAL_STATS\n", KERN),
    ("C Lern-Hinweis wieder in den Verlauf", AG,
     "                            contents=[\n                                *chat_history,\n                                types.Content(role=\"user\", parts=[types.Part.from_text(text=learning_hint)]),\n                            ],\n                            tools=self._llm_tools\n                        )\n                        # Tool-Calls",
     "                            contents=[\n                                *chat_history,\n                                types.Content(role=\"user\", parts=[types.Part.from_text(text=learning_hint)]),\n                            ],\n                            tools=self._llm_tools\n                        )\n                        chat_history.append(types.Content(role=\"user\", parts=[types.Part.from_text(text=learning_hint)]))\n                        # Tool-Calls", KERN),
    ("C Lauf-Kontext nicht geoeffnet", AG,
     "        token = _lauf_kontext_oeffnen(self, rechte)\n        try:\n            return await fn(self, *args, **kwargs)\n",
     "        token = _lauf_kontext_cv.set(_lauf_kontext_cv.get())\n        try:\n            return await fn(self, *args, **kwargs)\n", KERN),
    ("C Stopp trifft nur einen Tab", AG,
     "            for scope in list(self._stop_scopes.get(self._run_key(username), ())):\n                scope.event.set()\n",
     "            for scope in list(self._stop_scopes.get(self._run_key(username), ()))[:1]:\n                scope.event.set()\n", KERN),
    ("C Shell: Zeilen-Timeout statt Frist", "backend/tools/shell.py",
     "            fertig, _ = await asyncio.wait(aufgaben, timeout=max(0.0, rest))\n",
     "            fertig, _ = await asyncio.wait(aufgaben)\n", SHL),
    ("C Shell: kein Mengendeckel", "backend/tools/shell.py",
     "                    gesammelt[ziel] += stueck[:frei]\n", "                    gesammelt[ziel] += stueck\n", SHL),
    ("C Anthropic: IDs wieder je Schritt", "backend/llm.py",
     "                    tool_id = f\"call_{fc.name}_{step}_{_nr}\"\n", "                    tool_id = f\"call_{fc.name}_{step}\"\n", ANT),
    ("C Anthropic: Bilder der Werkzeug-Antwort verworfen", "backend/llm.py",
     "                if inline_data_blocks and tool_result_blocks:\n", "                if False:\n", ANT),
    ("C Anthropic: kein Prompt-Caching", "backend/llm.py",
     "        if anthropic_tools:\n            anthropic_tools[-1] = {**anthropic_tools[-1], \"cache_control\": _cache}\n", "", ANT),
    ("C Kompression nimmt wieder die aeltesten Zeilen", AG,
     "        return list(zeilen[:anfang]) + [f\"[… {weg} Zeilen ausgelassen …]\"] + list(zeilen[-ende:])\n",
     "        return list(zeilen[:anfang + ende])\n", KOM),
    ("C Skill-Module wieder je Agent ausgefuehrt", "backend/skills/loader.py",
     "        if not frisch and eintrag is not None and eintrag[0] == stempel:\n", "        if False:\n", SKC),
    # ── Frontend / Bridge / Docker ──
    ("F chatlib: Adresse ohne Attribut-Escape", "frontend/js/chatlib.js",
     "                return _hold(`<img src=\"${_A(safe)}\" alt=\"${_A(alt)}\"",
     "                return _hold(`<img src=\"${safe}\" alt=\"${alt}\"", CHA),
    ("F Webhook ohne Zertifikats-Pin", SCH,
     "            checkServerIdentity: (_host, zert) => (zert && zert.fingerprint256 === pin.fp)\n",
     "            checkServerIdentity: () => undefined && (pin.fp)\n", WBJ),
    ("F Docker schaltet TLS-Pruefung wieder ab", "docker/entrypoint.sh",
     "    export JARVIS_WEBHOOK=\"https://localhost/api/whatsapp/incoming\"\n",
     "    export JARVIS_WEBHOOK=\"https://localhost/api/whatsapp/incoming\"\n    export NODE_TLS_REJECT_UNAUTHORIZED=0\n", M12),
    # ── Wissen ──
    ("W Gruppen-Manifest wieder fail-open", "backend/knowledge_groups.py",
     "    data = _atomar.lesen(MANIFEST_PATH, vorgabe=_default_manifest,\n                         pruefen=lambda d: isinstance(d, dict))\n",
     "    try:\n        data = json.loads(MANIFEST_PATH.read_text(encoding=\"utf-8\"))\n    except Exception:\n        return _default_manifest()\n", ATO),
    ("W atomar ohne Sicherung", "backend/atomar.py",
     "                os.replace(pfad, _sicherung(pfad))\n", "                pass\n", ATO),
    # ── Anmeldung ──
    ("A require_local_auth ohne Sperre", MN,
     "    # allen rund 240 Admin-Routen weiter durch, waehrend require_auth es abwies.\n    if security_guard.is_blocked(username):\n",
     "    # allen rund 240 Admin-Routen weiter durch, waehrend require_auth es abwies.\n    if False:\n", AUR),
    ("A root wieder Admin per Name", MN,
     "    if u in ALLOWED_USERS:\n        return True\n    users_raw",
     "    if u in ALLOWED_USERS or u in {\"jarvis\", \"root\"}:\n        return True\n    users_raw", AUR),
    ("A Gruppe wieder nur ueber CN", MN,
     "    if m == w:\n        return True\n", "    if m.split(\",\")[0] == w.split(\",\")[0]:\n        return True\n", AUR),
    ("A Gruppe: Vorgabe wieder weich", MN,
     'os.environ.get("JARVIS_AD_GRUPPE_STRENG", "1").strip() == "0"',
     'os.environ.get("JARVIS_AD_GRUPPE_STRENG", "0").strip() != "1"', AUR),
]

_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  ok   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (("  -> " + detail) if detail else ""))


def md5(p):
    return hashlib.md5((WURZEL / p).read_bytes()).hexdigest()


def lauf(cmd):
    if cmd[0] == PY:
        cmd = [GEWAEHLT.get(cmd[-1], KANDIDATEN[0])] + cmd[1:]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run(cmd, cwd=WURZEL, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return 124, 0, "Zeitueberschreitung"
    import re as _re
    aus = _re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)   # Farbcodes weg, sonst zaehlt "✗" nicht
    fails = sum(aus.count(m) for m in ("  FAIL ", "  FAIL:", "\nFAIL ", "  ✗ ", "✗ "))
    return r.returncode, fails, aus


def zurueck():
    for d in DATEIEN:
        q = SICHERUNG / d.replace("/", "__")
        if q.exists():
            shutil.copy2(q, WURZEL / d)


filt = sys.argv[1] if len(sys.argv) > 1 else ""
AUSWAHL = [p for p in PROBEN if filt in p[0]]
if not AUSWAHL:
    print("ABBRUCH (Exit 2): keine Probe passt zu %r" % filt)
    sys.exit(2)
DATEIEN = sorted({p[1] for p in AUSWAHL})
WAECHTER = []
for p in AUSWAHL:
    if p[4] not in WAECHTER:
        WAECHTER.append(p[4])

SICHERUNG.mkdir(exist_ok=True)
if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs – wird zurueckgenommen.")
    for q in SICHERUNG.iterdir():
        if q.name != "laeuft":
            shutil.copy2(q, WURZEL / q.name.replace("__", "/"))
    MARKE.unlink()

for w in WAECHTER:
    for kand in (KANDIDATEN if w[0] == PY else [None]):
        if kand:
            GEWAEHLT[w[-1]] = kand
        rc, f, aus = lauf(w)
        if rc == 0:
            break
    if rc != 0:
        print("ABBRUCH (Exit 2): Basislauf %s nicht gruen (Exit %d)" % (Path(w[-1]).name, rc))
        print(aus[-1500:])
        sys.exit(2)
print("Basislauf gruen (%d Waechter).\n" % len(WAECHTER))

for q in SICHERUNG.iterdir():
    if q.name != "laeuft":
        q.unlink()
vorher = {}
for d in DATEIEN:
    shutil.copy2(WURZEL / d, SICHERUNG / d.replace("/", "__"))
    vorher[d] = md5(d)
MARKE.write_text("laeuft")
signal.signal(signal.SIGTERM, lambda *a: sys.exit(3))
try:
    for name, datei, alt, neu, w in AUSWAHL:
        p = WURZEL / datei
        t = p.read_text(encoding="utf-8")
        if t.count(alt) != 1:
            pruefe(False, "%s: Anker nicht eindeutig (%d)" % (name, t.count(alt)))
            continue
        p.write_text(t.replace(alt, neu, 1), encoding="utf-8")
        rc, f, aus = lauf(w)
        pruefe(rc == 1 and f >= 1, "%s -> beisst (%d FAIL, %s)" % (name, f, Path(w[-1]).name),
               "Exit %d" % rc)
        zurueck()
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for d in DATEIEN:
    pruefe(md5(d) == vorher[d], "%s byte-gleich zurueck" % d)
for w in WAECHTER:
    rc, _, _ = lauf(w)
    pruefe(rc == 0, "Abschlusslauf %s wieder gruen" % Path(w[-1]).name)
print("\n" + "=" * 60)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)

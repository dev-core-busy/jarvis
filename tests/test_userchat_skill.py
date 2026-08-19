#!/usr/bin/env python3
"""Waechter: Benutzer-Chat ist ein SKILL (2026-08-19) + Support-Agent-Kachel versteckt.

Der Bereich /userchat haengt seit dem Umbau am Skill ``userchat`` (Vorgabe AUS).
Geprueft wird, dass ALLE Zugaenge daran haengen – Seite, Endpunkte, WebSocket,
Portal-Kachel und der Ungelesen-Poll. Ein einzelnes vergessenes Tor macht den
Schalter wertlos: Tokens sind zustandslos und ueberleben das Abschalten, ein
offener Tab wuerde also einfach weiterchatten.

BEWUSST OHNE fastapi lauffaehig: ``backend.main`` zu importieren zieht den
halben Dienst hoch und schreibt beim Laden von ``backend.config`` die
LIVE-settings.json zurueck (Profil-Migration). Der Test liest deshalb Quelltext
und fuehrt nur die vier Konfigurations-Helfer isoliert mit einer Attrappe aus.

Aufruf:  python3 tests/test_userchat_skill.py
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
PORTAL = (ROOT / "frontend" / "portal.html").read_text(encoding="utf-8")
SKILL_DIR = ROOT / "skills" / "userchat"

_ok = _fail = 0


def section(t):
    print(f"\n\033[1m{t}\033[0m")


def check(name, bedingung, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        _fail += 1
        print(f"  \033[31m✗\033[0m {name}" + (f"  →  {detail}" if detail else ""))


def funktion(quelle: str, name: str) -> str:
    """Rumpf einer Funktion aus dem Quelltext – per ast, nicht per Textsuche.

    Ein Schnitt 'von Marke bis zur naechsten Marke' hat in diesem Projekt schon
    einmal 446 fremde Zeilen mitgenommen und die Pruefung trivial wahr gemacht.
    Fehlt die Funktion, gibt es "" – der Waechter FAELLT dann durch, statt mit
    einer Ausnahme abzubrechen (ein Abbruch saehe wie ein Erfolg aus).
    """
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return ""
    for knoten in ast.walk(baum):
        if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)) and knoten.name == name:
            return ast.get_source_segment(quelle, knoten) or ""
    return ""


def nur_code(quelle: str) -> str:
    """Kommentare und Docstrings entfernen.

    Ein Waechter, der seine eigene BEGRUENDUNG liest, prueft nichts – im Projekt
    inzwischen achtmal passiert. Die Pruefungen unten laufen deshalb gegen den
    reinen Code.
    """
    ohne_kommentar = re.sub(r"#.*", "", quelle)
    ohne_kommentar = re.sub(r'"""(?:.|\n)*?"""', '""', ohne_kommentar)
    return re.sub(r"'''(?:.|\n)*?'''", "''", ohne_kommentar)


# ═══════════════════════════════════════════════════════════════════════════
section("1 – Skill-Manifest")

sj = SKILL_DIR / "skill.json"
check("skills/userchat/skill.json vorhanden", sj.exists())
manifest = {}
if sj.exists():
    try:
        manifest = json.loads(sj.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        check("skill.json ist gueltiges JSON", False, str(e))
    else:
        check("skill.json ist gueltiges JSON", True)

check("Vorgabe AUS (enabled: false)", manifest.get("enabled") is False,
      repr(manifest.get("enabled")))
check("kein System-Skill (loeschbar)", manifest.get("system") is False,
      repr(manifest.get("system")))
check("module = main", manifest.get("module") == "main")
# Ein Werkzeug waere ein Versandweg im Namen des Benutzers, den ein Modell
# auswaehlen koennte – und damit auch eine Prompt-Injektion.
check("KEINE Agent-Werkzeuge im Manifest", manifest.get("tools") == [],
      repr(manifest.get("tools")))
check("Verlaufsdatei steht in data_dirs (Purge mit 'Daten entfernen')",
      "data/userchat_history.json" in (manifest.get("data_dirs") or []),
      repr(manifest.get("data_dirs")))
schema = manifest.get("config_schema") or {}
check("config_schema kennt history_max", "history_max" in schema)
check("config_schema kennt attachment_max_mb", "attachment_max_mb" in schema)

mp = SKILL_DIR / "main.py"
check("skills/userchat/main.py vorhanden", mp.exists())
mp_src = mp.read_text(encoding="utf-8") if mp.exists() else ""
check("get_tools() liefert eine leere Liste",
      "return []" in nur_code(funktion(mp_src, "get_tools")))


# ═══════════════════════════════════════════════════════════════════════════
section("2 – Backend: jedes Tor haengt am Skill")

check("_UC_SKILL ist definiert", '_UC_SKILL = "userchat"' in MAIN)

seite = nur_code(funktion(MAIN, "userchat_page"))
check("/userchat liefert 404, wenn der Skill aus ist",
      "_skill_active(_UC_SKILL)" in seite and "404" in seite, seite[:200])

dep = nur_code(funktion(MAIN, "require_userchat_access"))
check("require_userchat_access prueft den Skill-Zustand",
      "_skill_active(_UC_SKILL)" in dep, dep[:200])
check("require_userchat_access antwortet 403 mit Klartext",
      "403" in dep and "HTTPException" in dep, dep[:200])

for fn in ("get_online_users", "userchat_unread", "userchat_known_users", "userchat_search"):
    kopf = funktion(MAIN, fn).split("\n")[0:3]
    check(f"{fn} haengt an require_userchat_access",
          "require_userchat_access" in " ".join(kopf), " ".join(kopf))
    check(f"{fn} haengt NICHT mehr am blossen require_auth",
          "Depends(require_auth)" not in " ".join(kopf), " ".join(kopf))

ws = nur_code(funktion(MAIN, "userchat_ws"))
check("/ws/users prueft den Skill-Zustand", "_skill_active(_UC_SKILL)" in ws)
# Die Reihenfolge ist die eigentliche Aussage: wird der Client vorher
# registriert, laeuft eine offene Seite nach dem Abschalten weiter.
_pos_skill = ws.find("_skill_active(_UC_SKILL)")
_pos_reg = ws.find("_uc_clients[username].append")
check("/ws/users prueft VOR dem Registrieren des Clients",
      0 <= _pos_skill < _pos_reg, f"skill@{_pos_skill} reg@{_pos_reg}")

# Ein Close ohne bekannten Grund laesst den Client alle 3 s neu verbinden –
# eine stille Endlosschleife gegen einen Bereich, der aus ist. Genau dafuer gibt
# es "area_off"; ein generisches "error" faellt im Client durch alle Zweige.
check("/ws/users meldet den Grund als area_off", '"type": "area_off"' in ws)
UC_JS = (ROOT / "frontend" / "js" / "userchat.js").read_text(encoding="utf-8")
check("userchat.js kennt area_off", "case 'area_off':" in UC_JS)
_zweig = UC_JS.split("case 'area_off':", 1)[-1].split("case '", 1)[0]
check("area_off haelt den Reconnect an",
      "_sessionInvalid = true" in _zweig and "clearTimeout(reconnectTimer)" in _zweig, _zweig[:200])
check("area_off schickt aufs Portal", "'/portal'" in _zweig, _zweig[:200])
# Die Anmeldung ist gueltig – nur der Bereich ist zu. Tokens zu verwerfen waere
# eine Abmeldung ohne Grund (und in /chat waere der Benutzer dann auch draussen).
check("area_off verwirft KEINE Tokens", "localStorage.removeItem" not in _zweig, _zweig[:200])

me = nur_code(funktion(MAIN, "get_me") or funktion(MAIN, "api_me") or "")
if not me:  # Name der /api/me-Funktion nicht geraten – dann global suchen
    me = nur_code(MAIN)
check("/api/me meldet permissions.userchat",
      '"userchat": _skill_active(_UC_SKILL)' in me)


# ═══════════════════════════════════════════════════════════════════════════
section("3 – Grenzwerte kommen aus der Skill-Config, nicht aus Konstanten")

check("die feste Konstante _UC_HISTORY_MAX ist weg",
      "_UC_HISTORY_MAX" not in MAIN)
check("die fest verdrahteten 7_000_000 Bytes sind weg",
      "7_000_000" not in MAIN)

_code = nur_code(MAIN)
check("_uc_history_max() wird beim Kuerzen benutzt", "_uc_history_max()" in _code)
check("_uc_attachment_max_b64() wird beim Anhang benutzt",
      "_uc_attachment_max_b64()" in _code)

# Die vier Helfer isoliert ausfuehren – mit einer Config-Attrappe, damit der
# echte backend.config nicht geladen wird (der schreibt settings.json zurueck).
raum: dict = {}
zustand: dict = {}


class _CfgAttrappe:
    def get_skill_states(self):
        return zustand


raum["config"] = _CfgAttrappe()
raum["_UC_SKILL"] = "userchat"   # Modul-Global von main.py, hier gestellt
for name in ("_uc_skill_config", "_uc_cfg_int", "_uc_history_max", "_uc_attachment_max_b64"):
    q = funktion(MAIN, name)
    if not q:
        check(f"{name} vorhanden", False)
    else:
        exec(compile(q, "<main>", "exec"), raum)  # noqa: S102

if "_uc_history_max" in raum:
    zustand.clear()
    check("ohne Skill gilt die Vorgabe 200", raum["_uc_history_max"]() == 200)
    zustand["userchat"] = {"enabled": True, "config": {"history_max": 500}}
    check("gesetzter Wert wirkt", raum["_uc_history_max"]() == 500)
    zustand["userchat"] = {"enabled": True, "config": {"history_max": 999999}}
    check("nach oben begrenzt (5000)", raum["_uc_history_max"]() == 5000)
    zustand["userchat"] = {"enabled": True, "config": {"history_max": 1}}
    check("nach unten begrenzt (20)", raum["_uc_history_max"]() == 20)
    zustand["userchat"] = {"enabled": True, "config": {"history_max": "Unsinn"}}
    check("Muell faellt auf die Vorgabe zurueck", raum["_uc_history_max"]() == 200)

if "_uc_attachment_max_b64" in raum:
    zustand.clear()
    check("Anhang-Vorgabe entspricht ~5 MB", raum["_uc_attachment_max_b64"]() == 7_000_000)
    zustand["userchat"] = {"enabled": True, "config": {"attachment_max_mb": 100}}
    check("Anhang nach oben begrenzt (25 MB)",
          raum["_uc_attachment_max_b64"]() == 25 * 1_400_000)


# ═══════════════════════════════════════════════════════════════════════════
section("4 – Portal: Kachel und Ungelesen-Poll haengen an permissions.userchat")

check("Benutzer-Chat-Kachel startet versteckt",
      re.search(r'<a class="pt-card hidden" id="pt-card-userchat"', PORTAL) is not None)
check("Kachel wird aus permissions.userchat eingeblendet",
      "d.permissions.userchat" in PORTAL and
      "getElementById('pt-card-userchat')" in PORTAL)
check("Ungelesen-Poll laeuft nur bei aktivem Skill", "!_ucAn" in PORTAL)
check("_ucAn wird vor dem /api/me-Abruf deklariert",
      0 < PORTAL.find("var _ucAn = false;") < PORTAL.find("fetch('/api/me'"))
# Vier Leerzeichen = Rumpf der IIFE, also ein Aufruf beim Seitenaufbau. Der
# erlaubte Aufruf steht im permissions-Zweig und ist tiefer eingerueckt.
check("kein unbedingter refreshUnread() beim Seitenaufbau",
      not re.search(r"^ {4}refreshUnread\(\);\s*$", PORTAL, re.M))


# ═══════════════════════════════════════════════════════════════════════════
section("5 – Support-Agent-Kachel ist fuer ALLE versteckt (Umbau steht aus)")

check("Kachel traegt hidden",
      re.search(r'<a class="pt-card hidden" id="pt-card-agent" href="/supportagent">', PORTAL)
      is not None)
# Der Kern: es darf KEINE Bedingung geben, die sie wieder einblendet.
check("kein JS blendet pt-card-agent ein",
      "pt-card-agent" not in re.sub(r"<!--(?:.|\n)*?-->", "", PORTAL).split("<script>")[-1],
      "im Skriptteil referenziert")
check("die Seite /supportagent bleibt erreichbar",
      '@app.get("/supportagent"' in MAIN)


print(f"\n\033[1mErgebnis: {_ok}/{_ok + _fail}\033[0m")
sys.exit(0 if _fail == 0 else 1)

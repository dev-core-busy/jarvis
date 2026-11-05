#!/usr/bin/env python3
"""Waechter: Confluence ist nur lesend angebunden (2026-11-05, "wie bei SAP").

Zusagen:
* ``ConfluenceClient._request`` laesst nur GET durch; alles andere endet mit
  ``NUR_LESEN_TEXT``, OHNE dass eine Anfrage den Prozess verlaesst.
* Einzige Ausnahme: das Destillat (``create_page`` + ``upload_attachment_bytes``,
  ``ausnahme="destillat"``). Eine andere Kennung oeffnet nichts.
* Nur der Destillat-Endpunkt benutzt diese beiden Methoden – kein Werkzeug,
  kein anderer Endpunkt.
* Der Skill bietet der KI kein schreibendes Werkzeug an (Code und Manifest).
* Einstellungen → Confluence zeigt "Nur-Lesen erzwingen" angehakt und gesperrt.

Sabotierte Kopien fuer die Gegenprobe ueber CF_CLIENT, CF_SKILL, CF_SKILLJSON,
CF_SETTINGS, CF_MAIN (die Originale werden nie angefasst).
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_confluence_nur_lesen.py
"""
import ast
import importlib.util
import json
import os
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _pfad(var, rel):
    return Path(os.environ.get(var) or ROOT / rel)


CLIENT = _pfad("CF_CLIENT", "backend/confluence_client.py")
SKILL = _pfad("CF_SKILL", "skills/confluence/main.py")
SKILLJSON = _pfad("CF_SKILLJSON", "skills/confluence/skill.json")
SETTINGS = _pfad("CF_SETTINGS", "frontend/settings.html")
MAIN = _pfad("CF_MAIN", "backend/main.py")

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


# backend.config nur als Attrappe (der echte Import schreibt settings.json)
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_skill_states=lambda: {}, get_setting=lambda k, d=None: d)
sys.modules.setdefault("backend.config", _cfg)

try:
    import backend  # noqa: F401
    spec = importlib.util.spec_from_file_location("backend.confluence_client", CLIENT)
    cc = importlib.util.module_from_spec(spec)
    sys.modules["backend.confluence_client"] = cc
    spec.loader.exec_module(cc)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: confluence_client nicht ladbar: {e}")
    sys.exit(2)

# ── Netz-Attrappe: zaehlt, was den Prozess verlassen wuerde ─────────────────
GESENDET = []


class _Antwort:
    status_code = 200
    text = "{}"

    def json(self):
        return {"id": "1", "results": []}


def _request(method, url, **kw):
    GESENDET.append((method.upper(), url))
    return _Antwort()


cc.requests.request = _request
c = cc.ConfluenceClient({"base_url": "https://wiki.beispiel.de", "api_token": "t"})

# ═══════════════════════════════════════════════════════════════════════════
section("0. Positivkontrolle: GET geht durch und wird gesendet")
# ═══════════════════════════════════════════════════════════════════════════
try:
    c._request("GET", "/rest/api/space")
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: GET scheitert ({e}) – Messaufbau kaputt")
    sys.exit(2)
if GESENDET != [("GET", "https://wiki.beispiel.de/rest/api/space")]:
    print(f"ABBRUCH: die Netz-Attrappe sieht den GET nicht ({GESENDET}) – "
          "jede 'nichts gesendet'-Pruefung waere trivial wahr")
    sys.exit(2)
check(True, "GET erreicht das Netz")

# ═══════════════════════════════════════════════════════════════════════════
section("1. Alles ausser GET ist gesperrt – ohne Netzverkehr")
# ═══════════════════════════════════════════════════════════════════════════
for m in ("POST", "PUT", "DELETE", "PATCH", "post"):
    GESENDET.clear()
    try:
        c._request(m, "/rest/api/content", json={})
        check(False, f"{m} wird abgelehnt", "kein Fehler")
    except cc.ConfluenceError as e:
        check(str(e) == cc.NUR_LESEN_TEXT and not GESENDET,
              f"{m} wird abgelehnt, nichts gesendet", f"{e} / {GESENDET}")
GESENDET.clear()
try:
    c._request("POST", "/rest/api/content", ausnahme="werkzeug")
    check(False, "eine fremde Ausnahme-Kennung oeffnet nichts")
except cc.ConfluenceError:
    check(not GESENDET, "eine fremde Ausnahme-Kennung oeffnet nichts")
check(tuple(cc.SCHREIB_AUSNAHMEN) == ("destillat",), "einzige Ausnahme: destillat",
      str(cc.SCHREIB_AUSNAHMEN))

# ═══════════════════════════════════════════════════════════════════════════
section("2. Die Destillat-Ausnahme funktioniert")
# ═══════════════════════════════════════════════════════════════════════════
GESENDET.clear()
try:
    c.create_page("DOC", "Titel", "<p>x</p>")
    check(GESENDET and GESENDET[0][0] == "POST", "create_page legt an", str(GESENDET))
except cc.ConfluenceError as e:
    check(False, "create_page legt an", str(e))
GESENDET.clear()
try:
    c.upload_attachment_bytes("1", "bild.png", b"\x89PNG", "image/png")
    check(GESENDET and GESENDET[0][0] == "POST", "Destillat-Bilder werden angehaengt", str(GESENDET))
except cc.ConfluenceError as e:
    check(False, "Destillat-Bilder werden angehaengt", str(e))

# ═══════════════════════════════════════════════════════════════════════════
section("3. Wer darf die Ausnahme benutzen? (Syntaxbaum)")
# ═══════════════════════════════════════════════════════════════════════════
AUSNAHME_METHODEN = {"create_page", "upload_attachment_bytes"}
try:
    baum_client = ast.parse(CLIENT.read_text(encoding="utf-8"))
    baum_main = ast.parse(MAIN.read_text(encoding="utf-8"))
    baum_skill = ast.parse(SKILL.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Quelltext nicht lesbar: {e}")
    sys.exit(2)

# 3a: im Client tragen NUR die beiden Ausnahme-Methoden einen Nicht-GET-Aufruf
schreibend = set()
for fn in ast.walk(baum_client):
    if not isinstance(fn, ast.FunctionDef):
        continue
    for call in ast.walk(fn):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_request" and call.args
                and isinstance(call.args[0], ast.Constant)
                and str(call.args[0].value).upper() != "GET"):
            schreibend.add(fn.name)
check(schreibend == AUSNAHME_METHODEN, "nur create_page/upload_attachment_bytes schreiben im Client",
      str(sorted(schreibend)))


def _benutzer(baum, namen):
    """Funktionen, die eine der Methoden ansprechen (Aufruf ODER Uebergabe
    an to_thread – beides ist eine Benutzung)."""
    raus = set()
    for fn in ast.walk(baum):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and n.attr in namen:
                raus.add(fn.name)
    return raus


nutzer_main = _benutzer(baum_main, AUSNAHME_METHODEN)
check("wissen_destillat_confluence" in nutzer_main,
      "Positivkontrolle: der Destillat-Endpunkt wird als Nutzer erkannt", str(nutzer_main))
check(nutzer_main <= {"wissen_destillat_confluence"},
      "in main.py nutzt NUR der Destillat-Endpunkt die Ausnahme", str(sorted(nutzer_main)))
check(not _benutzer(baum_skill, AUSNAHME_METHODEN),
      "der Skill nutzt die Ausnahme nicht", str(_benutzer(baum_skill, AUSNAHME_METHODEN)))

# ═══════════════════════════════════════════════════════════════════════════
section("4. Der KI wird kein schreibendes Werkzeug angeboten")
# ═══════════════════════════════════════════════════════════════════════════
LESEND = {"confluence_test_connection", "confluence_list_spaces", "confluence_search",
          "confluence_get_page", "confluence_list_attachments", "confluence_download_attachment"}
namen = set()
for kl in ast.walk(baum_skill):
    if isinstance(kl, ast.ClassDef):
        for f in kl.body:
            if isinstance(f, ast.FunctionDef) and f.name == "name":
                for r in ast.walk(f):
                    if isinstance(r, ast.Return) and isinstance(r.value, ast.Constant):
                        namen.add(r.value.value)
check(len(namen) >= 5, "Positivkontrolle: Werkzeugnamen gefunden", str(sorted(namen)))
check(namen <= LESEND, "nur lesende Werkzeuge im Skill", str(sorted(namen - LESEND)))
try:
    manifest = json.loads(SKILLJSON.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: skill.json nicht lesbar: {e}")
    sys.exit(2)
check(set(manifest.get("tools") or []) <= LESEND, "nur lesende Werkzeuge im Manifest",
      str(sorted(set(manifest.get("tools") or []) - LESEND)))

# ═══════════════════════════════════════════════════════════════════════════
section("5. Einstellungen → Confluence: Nur-Lesen angehakt und gesperrt")
# ═══════════════════════════════════════════════════════════════════════════
html = SETTINGS.read_text(encoding="utf-8")
tag = re.search(r'<input[^>]*\bid="cf-read-only"[^>]*>', html)
check(tag is not None, "Kaestchen cf-read-only vorhanden")
if tag:
    t = tag.group(0)
    check(re.search(r"\bchecked\b", t) and re.search(r"\bdisabled\b", t),
          "angehakt UND gesperrt", t)
check('data-i18n="cf.read_only"' in html and "nicht abschaltbar" in html,
      "Beschriftung sagt 'nicht abschaltbar'")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)

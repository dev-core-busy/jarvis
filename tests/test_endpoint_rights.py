#!/usr/bin/env python3
"""Waechter fuer die Endpunkt-Rechte in backend/main.py.

WARUM ES DIESEN TEST GIBT
-------------------------
Am 2026-08-04 ergab eine vollstaendige Durchsicht aller 342 Routen, dass 61
Endpunkte an ``require_auth`` hingen, obwohl sie Administratoren-Material
liefern oder Administratoren-Aktionen ausfuehren. Die Muster, die dabei immer
wieder auftraten:

1. **Lesen war freier als Schreiben.** ``POST /api/skills/{n}/config`` war
   Admin, ``GET`` daneben nicht (behoben 2026-08-02). Dasselbe bei
   ``/api/knowledge/pending`` (PATCH/approve = Editor, GET = jeder) und bei
   der Telemetrie. Wer nur die Schreib-Endpunkte prueft, findet das nie.
2. **Die Oberflaeche war die einzige Schranke.** Desktop-Knopf und
   Update-Pille im Portal erscheinen nur fuer Admins (``if (d.is_admin)``) –
   die Endpunkte dahinter standen jedem offen. Eine clientseitige Sichtbarkeit
   ist keine Berechtigung.
3. **Fremde Zugangsdaten als Vollmacht.** ``/api/jira/*``, ``/api/confluence/*``
   und ``/api/kundenverwaltung/*`` fragen mit den SERVER-Zugangsdaten ab und
   umgehen damit die Rechte des Benutzers im Zielsystem.
4. **Verbindungstests sind SSRF-Werkzeuge.** ``/api/profiles/test``,
   ``/api/profiles/models`` und ``/api/auth/ad_test`` nehmen ein Ziel aus dem
   Request und melden, ob es erreichbar war.

Dieser Test friert das Ergebnis ein: die unten gelisteten Endpunkte MUESSEN an
der jeweils genannten Dependency haengen. Er laeuft ohne fastapi (reine
Quelltext-Analyse) und faellt auch dann, wenn jemand eine NEUE Route in einem
der geschuetzten Namensraeume anlegt und dabei ``require_auth`` verwendet.

    python3 tests/test_endpoint_rights.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")

_ok = 0
_fail: list[str] = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        _fail.append(name + (f" – {detail}" if detail else ""))
        print(f"  \033[31m✗\033[0m {name}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n\033[1m{t}\033[0m")


# ─── Routen samt Signatur einsammeln ─────────────────────────────────────────

def routes() -> list[tuple[str, str, str, set[str]]]:
    out = []
    pat = re.compile(r'@app\.(get|post|put|delete|patch|websocket)\("([^"]+)"[^)]*\)\s*\n'
                     r'(?:@[^\n]+\n)*async def (\w+)\(')
    for m in pat.finditer(SRC):
        method, route, fn = m.group(1), m.group(2), m.group(3)
        i = SRC.index(f"async def {fn}(", m.start())
        j = i + len(f"async def {fn}")
        depth = 0
        while j < len(SRC):
            if SRC[j] == "(":
                depth += 1
            elif SRC[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        sig = SRC[i:j + 1]
        out.append((method, route, fn, set(re.findall(r"Depends\((\w+)\)", sig))))
    return out


ROUTES = routes()
BY_KEY = {(m, r): (fn, d) for m, r, fn, d in ROUTES}

section("Grundlage")
check("Routen gefunden (>300)", len(ROUTES) > 300, str(len(ROUTES)))
check("require_admin_or_knowledge_editor ist definiert",
      "async def require_admin_or_knowledge_editor" in SRC)

# ─── Muss-Admin-Liste ────────────────────────────────────────────────────────
# Begruendung je Gruppe im Kommentar; jede Zeile ist ein belegter Befund.

ADMIN: dict[str, list[tuple[str, str]]] = {
    # Schreiben hier wirkt in JEDEM spaeteren System-Prompt – auch dem eines
    # Admins. Genau deshalb steht 'reflection' in _BLOCKED_TOOLS_FOR_LDAP;
    # der HTTP-Weg daneben war offen.
    "Instruktionen (System-Prompt aller Laeufe)": [
        ("get", "/api/instructions"), ("get", "/api/instructions/{name}"),
        ("post", "/api/instructions/{name}"), ("delete", "/api/instructions/{name}"),
    ],
    # QR = Kopplung eines fremden Telefons an die Bridge; Logs = Nachrichtentexte.
    "WhatsApp (Kopplung, Steuerung, Nachrichteninhalte)": [
        ("get", "/api/whatsapp/qr"), ("post", "/api/whatsapp/logout"),
        ("post", "/api/whatsapp/reconnect"), ("get", "/api/whatsapp/logs"),
        ("delete", "/api/whatsapp/logs"), ("get", "/api/whatsapp/bridge-logs"),
        ("delete", "/api/whatsapp/bridge-logs"), ("get", "/api/whatsapp/status"),
    ],
    # Erkennungs-Ereignisse sind biometrische Daten; cleanup() loescht die
    # gesamte Gesichts-Datenbank.
    "Vision (biometrische Daten, Kamera, Loeschen)": [
        ("get", "/api/vision/status"), ("post", "/api/vision/control"),
        ("get", "/api/vision/cameras"), ("get", "/api/vision/profiles"),
        ("post", "/api/vision/profiles"), ("post", "/api/vision/profiles/rename"),
        ("delete", "/api/vision/profile/{name}"),
        ("post", "/api/vision/training/start"), ("post", "/api/vision/training/stop"),
        ("get", "/api/vision/training/status"), ("get", "/api/vision/events"),
        ("post", "/api/vision/cleanup"),
    ],
    # revoke entzieht dem ganzen System den Google-Zugriff; gog-setup schreibt
    # OAuth-Zugangsdaten.
    "Google (Zugangsdaten, Widerruf)": [
        ("get", "/api/google/status"), ("post", "/api/google/device-start"),
        ("get", "/api/google/device-status"), ("post", "/api/google/revoke"),
        ("get", "/api/google/gog-status"), ("post", "/api/google/gog-setup"),
        ("post", "/api/google/gog-auth-url"), ("post", "/api/google/gog-auth-exchange"),
        ("delete", "/api/google/gog-account"),
    ],
    # Abfrage mit den SERVER-Zugangsdaten: umgeht die Rechte des Benutzers im
    # Zielsystem vollstaendig.
    "Fremdsysteme mit Server-Zugangsdaten": [
        ("get", "/api/confluence/test"), ("get", "/api/confluence/spaces"),
        ("get", "/api/confluence/pages"), ("get", "/api/confluence/search"),
        ("get", "/api/confluence/page"),
        ("get", "/api/jira/test"), ("get", "/api/jira/search"), ("get", "/api/jira/issue"),
        ("get", "/api/kundenverwaltung/test"),
        ("get", "/api/kundenverwaltung/tickets-by-buzzwords"),
    ],
    # Ziel kommt aus dem Request, Antwort verraet Erreichbarkeit = Portscanner
    # aus dem Inneren des Netzes heraus.
    "Verbindungstests (SSRF-Werkzeug)": [
        ("post", "/api/profiles/test"), ("post", "/api/profiles/models"),
        ("get", "/api/profiles/{profile_id}/test"), ("post", "/api/auth/ad_test"),
    ],
    # Sicherheitskonfiguration bzw. Aktionen, die in der Oberflaeche ohnehin
    # nur Admins angeboten werden (is_admin-Gate im Portal ist KEINE Rechte-
    # pruefung).
    "Sicherheits-/Systemkonfiguration": [
        ("get", "/api/auth/ad_status"), ("get", "/api/settings/ssl"),
        ("get", "/api/update/status"), ("get", "/api/update/settings"),
        ("post", "/api/vnc/unlock"), ("get", "/api/mcp/servers"),
        ("get", "/api/openclaw/search"), ("get", "/api/openclaw/workflow-task"),
    ],
    # Telemetrie: Prompts, Tool-Argumente und Fehler ALLER Benutzer.
    "Telemetrie / Diagnose": [
        ("get", "/api/telemetry/stats"), ("get", "/api/telemetry/spans"),
        ("get", "/api/telemetry/errors"), ("delete", "/api/telemetry"),
        ("delete", "/api/telemetry/tool_stats"), ("delete", "/api/telemetry/llm_stats"),
        ("delete", "/api/telemetry/errors"), ("delete", "/api/telemetry/spans"),
        ("get", "/api/conv_log"), ("get", "/api/conv_log/ips"),
        ("get", "/api/conv_log/users"), ("get", "/api/conv_log/{conv_id}"),
        ("delete", "/api/conv_log"),
        ("get", "/api/audit_log"), ("delete", "/api/audit_log"),
        ("get", "/api/logs/retention"), ("post", "/api/logs/retention/run"),
        # Global wirkende Kontext-Einstellung.
        # `/api/context/compress` stand hier bis 2026-08-05 – der Endpunkt ist
        # ENTFERNT (er wirkte auf den zuletzt geladenen, ggf. fremden Verlauf),
        # ebenso `/api/context/truncate`. Ihre Abwesenheit prueft GONE unten.
        ("post", "/api/context/threshold"),
    ],
}

# Lesen muss so streng sein wie Schreiben: die Schreib-Geschwister dieser drei
# haengen seit jeher an require_knowledge_editor.
EDITOR: list[tuple[str, str]] = [
    ("get", "/api/knowledge/learned"),
    ("get", "/api/knowledge/pending"),
    ("get", "/api/knowledge/pending/{doc_id}"),
]

for title, items in ADMIN.items():
    section(f"Muss Administrator sein – {title}")
    for method, route in items:
        got = BY_KEY.get((method, route))
        if not got:
            check(f"{method.upper()} {route}", False, "Route nicht gefunden")
            continue
        fn, deps = got
        check(f"{method.upper():6} {route}", "require_local_auth" in deps,
              f"{fn}: {sorted(deps) or 'KEINE'}")

section("Muss Administrator ODER Wissens-Editor sein")
for method, route in EDITOR:
    got = BY_KEY.get((method, route))
    if not got:
        check(f"{method.upper()} {route}", False, "Route nicht gefunden")
        continue
    fn, deps = got
    check(f"{method.upper():6} {route}",
          "require_admin_or_knowledge_editor" in deps, f"{fn}: {sorted(deps) or 'KEINE'}")

# ─── Namensraum-Waechter: neue Routen duerfen nicht zurueckfallen ────────────
# Der eigentliche Nutzen des Tests. Wer morgen GET /api/whatsapp/foo mit
# require_auth ergaenzt, faellt hier auf – ohne dass jemand die Liste oben
# pflegen muss.

section("Namensraum-Waechter (auch fuer kuenftige Routen)")
GUARDED_PREFIXES = [
    "/api/telemetry", "/api/conv_log", "/api/audit_log", "/api/logs/",
    "/api/instructions", "/api/whatsapp/", "/api/vision/", "/api/google/",
    "/api/confluence/", "/api/jira/", "/api/kundenverwaltung/", "/api/mcp/",
    "/api/openclaw/", "/api/broker/",
]
# Ausnahmen mit Begruendung – jede einzeln belegt, keine Sammelfreigabe.
EXEMPT = {
    # Server-zu-Server-Kamerarelais mit eigenem stream_key (Pruefung im Rumpf).
    ("get", "/api/vision/stream"), ("get", "/api/vision/download/stream-tools"),
    # Nur von localhost (Bridge) erreichbar, eigene Pruefung im Rumpf.
    ("post", "/api/whatsapp/incoming"),
    # Externe Automatisierung: Token ODER Agent-API-Key (require_auth_or_agent).
    ("get", "/api/jira/phonenumber"), ("get", "/api/jira/crm-number"),
    ("get", "/api/jira/passende-tickets"),
    # Jira-Assistent der Browser-Erweiterung: bewusst UNTERHALB von Admin, aber
    # mit eigener Freigabeliste (`require_jira_assist_access` – Benutzerliste
    # ODER Gruppe, leer = niemand, KEIN Admin-Bypass). Damit auf derselben Ebene
    # wie require_sap_access/require_email_access/require_tracks_access, die
    # ebenfalls auf Fachsysteme mit Server-Zugangsdaten zugreifen.
    # EINZELN eingetragen und nicht als Dependency freigegeben: eine dritte
    # Route unter /api/jira/ mit dieser Schranke soll hier wieder auffallen.
    ("get", "/api/jira/assist/health"), ("post", "/api/jira/assist"),
    # Auslieferung der Browser-Erweiterung als ZIP. Dieselbe Freigabe wie oben.
    # Der Inhalt ist NICHT vertraulich (er liegt als Quelltext im Repo) – die
    # Schranke haengt daran, dass niemand ein Werkzeug angeboten bekommt, das
    # er anschliessend nicht benutzen darf.
    ("get", "/api/jira/assist/paket"),
    # Prompt-Vorlagen: `require_jira_vorlagen_access` = dieselbe Freigabe ODER
    # Administrator. Der Admin-Zweig ist noetig, weil die GEMEINSAMEN Vorlagen
    # im Einstellungs-Reiter gepflegt werden und `_user_may_use_jira_assist`
    # bewusst keinen Admin-Bypass kennt – ohne ihn saehe ein Administrator ohne
    # eigene Jira-Freigabe seinen eigenen Reiter leer (gleiche Stelle und
    # gleiche Begruendung wie GET /api/sap/analyses/catalog).
    # Die zusaetzliche Schranke "gemeinsame Vorlagen nur fuer Admins" sitzt im
    # MODUL (jira_vorlagen.speichern), damit sie nicht am Endpunkt vergessen
    # werden kann.
    ("get", "/api/jira/assist/vorlagen"), ("post", "/api/jira/assist/vorlagen"),
    ("delete", "/api/jira/assist/vorlagen/{vid}"),
    # Die persoenliche Standard-Vorlage (2026-08-28): dieselbe Dependency und
    # dieselbe Begruendung wie die drei Routen darueber. Gespeichert wird eine
    # Zuordnung Benutzer → Vorlagen-Kennung, sonst nichts.
    ("post", "/api/jira/assist/vorlagen/standard"),
    # ── Mein Jira-Zugang (2026-08-28) ──
    # `require_jira_assist_access`, also die Freigabe des Bereichs: wer
    # /jira-addon betreten darf, darf dort seinen EIGENEN Token hinterlegen.
    #
    # WARUM DAS HIER RICHTIG IST, obwohl es nach "Zugangsdaten" klingt: der
    # Token ERWEITERT keine Rechte, er ERSETZT die des Sammelzugangs durch die
    # eigenen – in aller Regel engeren. Diese Routen sind der Weg, das Muster
    # "fremde Zugangsdaten als Vollmacht" (Endpunkt-Durchsicht 2026-08-04)
    # loszuwerden, nicht ein neuer Fall davon. Herausgegeben wird NIE ein
    # Token, auch nicht maskiert (`jira_accounts.zugang_info`).
    # Gleiche Einstufung wie /api/sap/account – dort ebenfalls die
    # Bereichs-Freigabe und nicht Admin.
    ("get", "/api/jira/account"), ("post", "/api/jira/account"),
    ("delete", "/api/jira/account"), ("post", "/api/jira/account/test"),
}
# Vision-Medien (Kamerabild, Gesichts-Ausschnitte, Trainings-Vorschau,
# Begruessungs-Audio) brauchen ``?token=``, weil <img>/<audio> keine Header
# setzen. Sie sind aber biometrische Daten – deshalb ``require_admin_or_query``
# (Admin UND Query-Token), nicht ``require_auth_or_query``. Genau diese fuenf
# hat der Namensraum-Waechter beim ersten Lauf gefunden.
QUERY_ADMIN_OK = {"require_admin_or_query"}
offenders = []
for method, route, fn, deps in ROUTES:
    if not any(route.startswith(p) for p in GUARDED_PREFIXES):
        continue
    if (method, route) in EXEMPT:
        continue
    if deps & ({"require_local_auth", "require_admin_or_knowledge_editor"} | QUERY_ADMIN_OK):
        continue
    offenders.append(f"{method.upper()} {route} ({fn}: {sorted(deps) or 'KEINE'})")
check("kein Endpunkt in geschuetzten Namensraeumen unterhalb von Admin",
      not offenders, "; ".join(offenders))

section("Regel: Lesen darf nicht freier sein als Schreiben")
# Fuer jede Route mit Schreibmethode: gibt es ein GET auf denselben Pfad mit
# SCHWAECHERER Dependency? Das war das Muster hinter zwei Vorfaellen.
RANK = {"require_local_auth": 3, "require_admin_or_knowledge_editor": 2,
        "require_knowledge_editor": 2, "require_sap_access": 2,
        "require_email_access": 2, "require_tracks_access": 2,
        "require_jira_assist_access": 2,
        # Freigabe ODER Admin – also mindestens so eng wie die Freigabe selbst.
        "require_jira_vorlagen_access": 2,
        # Bereichs-Schranke ohne eigene Freigabeliste: prueft NUR, ob der Skill
        # "userchat" an ist. Damit auf der Ebene von require_auth, nicht darueber.
        "require_userchat_access": 1,
        "require_auth_pwchange": 1, "require_auth": 1, "require_auth_or_query": 1,
        "require_admin_or_query": 3, "require_auth_or_agent": 1}


def rank(deps):
    return max([RANK.get(d, 0) for d in deps] or [0])


# Bekannte, bewusste Ausnahmen: gleicher Pfad, absichtlich unterschiedliche
# Ebene, weil Lesen den eigenen Datenbestand betrifft.
ASYM_OK = {
    # Lesen betrifft den EIGENEN Bestand, Schreiben ist enger gefasst.
    "/api/support/history", "/api/support/instructions",
    "/api/chat/shared-history", "/api/chat/preprompt",
    "/api/knowledge/files", "/api/knowledge/groups",
    "/api/knowledge/assignments", "/api/wissen/subfolders",
    "/api/context/threshold",
    # Logo/Video muessen VOR der Anmeldung sichtbar sein (Loginseite) – Schreiben
    # ist Admin. Die Asymmetrie ist hier der Zweck, nicht der Fehler.
    "/api/branding/logo", "/api/branding/portal-video",
    # Lesen liefert Schluessel MASKIERT (_mask_key, unten eigens geprueft),
    # Schreiben ist Admin.
    "/api/settings", "/api/profiles",
}
asym = []
writes = {}
for method, route, fn, deps in ROUTES:
    if method in ("post", "put", "patch", "delete"):
        writes.setdefault(route, []).append((method, fn, deps))
for method, route, fn, deps in ROUTES:
    if method != "get" or route not in writes or route in ASYM_OK:
        continue
    for wm, wfn, wdeps in writes[route]:
        if rank(deps) < rank(wdeps):
            asym.append(f"GET {route} ({rank(deps)}) < {wm.upper()} ({rank(wdeps)})")
check("kein GET schwaecher geschuetzt als das Schreiben auf demselben Pfad",
      not asym, "; ".join(sorted(set(asym))))

section("Absichtlich NICHT Admin (Gegenprobe – muss so bleiben)")
# Wuerden diese versehentlich auf Admin gehoben, waere die Anwendung fuer
# normale Benutzer kaputt. Der Test haelt beide Richtungen fest.
MUST_STAY_USER = [
    ("get", "/api/me"), ("get", "/api/cpu"), ("get", "/api/skills"),
    ("get", "/api/chat/sessions"), ("post", "/api/chat/sessions"),
    ("get", "/api/context/stats"), ("post", "/api/context/clear"),
    ("get", "/api/wissen/scope"), ("get", "/api/wissen/files"),
    ("get", "/api/wissen/pending"), ("get", "/api/support/history"),
    ("post", "/api/support/instructions"), ("get", "/api/users/online"),
    ("get", "/api/llm/active-status"), ("post", "/api/llm/profiles/{profile_id}/activate"),
    ("get", "/api/info_files"), ("post", "/api/logout"),
    ("get", "/api/settings"), ("get", "/api/profiles"),
]
for method, route in MUST_STAY_USER:
    got = BY_KEY.get((method, route))
    if not got:
        check(f"{method.upper()} {route} vorhanden", False, "Route nicht gefunden")
        continue
    fn, deps = got
    check(f"{method.upper():6} {route} bleibt fuer angemeldete Benutzer",
          "require_local_auth" not in deps, f"{fn}: {sorted(deps)}")

section("Entfernte Kontext-Endpunkte duerfen nicht zurueckkommen (2026-08-05)")
# /compress erzwang die Komprimierung von `_current_chat_history` – dem ZULETZT
# GELADENEN Verlauf des GETEILTEN Hauptagenten, bei parallelen Nutzern also dem
# eines Fremden. /truncate kuerzte nur den sitzungslosen Eimer und hatte in
# keinem Client einen Aufrufer (das Editieren laeuft ueber die WS-Nachricht
# `truncate_user_msg_index`). Beide sind entfernt; wer sie wieder einfuehrt,
# braucht einen ausdruecklich uebergebenen Zielverlauf.
for _m, _r in (("post", "/api/context/compress"), ("post", "/api/context/truncate")):
    check(f"{_m.upper()} {_r} ist entfernt", BY_KEY.get((_m, _r)) is None,
          "Route wieder vorhanden")
check("agent.force_compress() ist mit dem Endpunkt entfernt",
      "async def force_compress" not in
      (ROOT / "backend" / "agent.py").read_text(encoding="utf-8"))
check("der WS-Pfad zum Kuerzen bleibt (Nachricht editieren)",
      "_truncate_history_to_user_index(_hist, _keep)" in SRC)
check("kein Frontend ruft die entfernten Endpunkte",
      not any("context/compress" in p.read_text(encoding="utf-8")
              or "context/truncate" in p.read_text(encoding="utf-8")
              for p in (ROOT / "frontend").rglob("*.js")))

section("Wissensgruppen: Editoren-Felder nur fuer Verwalter der Gruppe")
# GET /api/knowledge/groups muss fuer JEDEN angemeldeten Benutzer erreichbar
# bleiben (Filter-Pulldown in /chat und /support), lieferte aber auch
# editors_users/editors_group mit – AD-Kontonamen aus der Rechtekonfiguration.
check("Endpunkt fuehrt die Liste durch _kb_strip_editor_fields",
      "_kb_strip_editor_fields(user, data)" in SRC)
check("Helfer ist definiert", "def _kb_strip_editor_fields(" in SRC)
_i = SRC.index("def _kb_strip_editor_fields(")
_body = SRC[_i:_i + 2200]
check("entfernt beide Felder", '_KB_EDITOR_FIELDS = ("editors_users", "editors_group")' in SRC)
check("entscheidet PRO Gruppe (nicht pauschal)", "_is_kb_group_editor(user, g)" in _body)
check("Admin und globaler Editor sehen die Felder",
      "_may_edit_knowledge(user) or _is_admin_user(user)" in _body)
check("fail-closed: bei Fehler werden die Felder entfernt",
      "except Exception" in _body and _body.rindex("_KB_EDITOR_FIELDS") > _body.index("except Exception"))
check("Gruppenliste bleibt fuer normale Benutzer erreichbar",
      "require_local_auth" not in (BY_KEY.get(("get", "/api/knowledge/groups")) or ("", set()))[1])

section("Instruktionen sind nicht mehr git-verfolgt")
_gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
check("data/instructions/ steht in .gitignore", "data/instructions/" in _gi)
check("Vorgaben liegen versioniert unter data/instructions_default/",
      (ROOT / "data" / "instructions_default").is_dir())
_ag = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
check("load_instructions() saet die Vorgaben", "_seed_instructions()" in _ag)
check("Saat nur bei KEINER vorhandenen .md",
      'if any(INSTRUCTIONS_DIR.glob("*.md")):' in _ag)

section("Maskierung: /api/settings und /api/profiles geben keine Schluessel heraus")
for fn in ("get_settings", "get_profiles"):
    i = SRC.index(f"async def {fn}(")
    body = SRC[i:i + 1600]
    check(f"{fn} maskiert api_key", '"api_key": _mask_key(' in body)
    check(f"{fn} maskiert session_key", '"session_key": _mask_key(' in body)
check("get_settings maskiert den Agent-API-Key",
      '"agent_api_key": _mask_key(' in SRC[SRC.index("async def get_settings("):][:1600])

print(f"\n\033[1mErgebnis: {_ok}/{_ok + len(_fail)}\033[0m")
if _fail:
    print("\033[31mFehlgeschlagen:\033[0m")
    for f in _fail:
        print("  -", f)
sys.exit(1 if _fail else 0)

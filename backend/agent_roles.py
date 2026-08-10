"""Spezialisierte Rollen-Agenten – Registry (data/agent_roles.json).

WAS DAS IST
-----------
Ein Administrator legt benannte Rollen an ("image_builder", "analyst", …). Jede
Rolle traegt einen eigenen System-Prompt, einen eigenen Werkzeug-Zuschnitt,
optional ein eigenes LLM-Profil und eine eigene Denktiefe. Der Hauptagent
bekommt dadurch das Werkzeug ``delegate(role, task)``: er gibt eine Teilaufgabe
an eine Rolle, wartet auf deren Ergebnis (SEQUENZIELL) und arbeitet damit weiter.

WARUM EINE EIGENE DATEI UND NICHT settings.json
-----------------------------------------------
Eine Rollen-Definition ist dasselbe Persistenz-Substrat wie ein Cron-Auftrag
oder ``data/instructions/*.md``: der hier gespeicherte Prompt wirkt in KUENFTIGEN
Laeufen, auch in denen eines Admins. Deshalb liegt sie neben
``data/scheduled_jobs.json`` – mit denselben Schranken (0640, in
``sandbox.PRIVATE_FILES``, ``_APP_DENY_REL`` und ``SHELL_SECRET_PATHS``), damit
ein ``cat`` in der Sandbox sie nicht lesen und kein Lauf sie beschreiben kann.

WARUM DIESES MODUL NUR STDLIB IMPORTIERT
----------------------------------------
``backend.config`` migriert beim Import Profile und schreibt die Live-
``settings.json`` zurueck (siehe tests/test_license.py, tests/test_shell_redirects.py).
Ein Test dieser Registry darf das nicht ausloesen. Die Denktiefen-Stufen stehen
deshalb hier nochmal als Tupel – Abgleich mit ``llm.REASONING_LEVELS`` haelt ein
Test fest, statt sich auf den Import zu verlassen.

DIE SICHERHEITSFORMEL STEHT IN effektive_werkzeuge()
----------------------------------------------------
    Rollen-Whitelist  ∩  (Werkzeuge des Aufrufers − Sperrliste)  −  delegate
Eine Rolle kann damit nur WEGNEHMEN, niemals hinzufuegen. Ohne diese Richtung
waere "Rolle X darf Werkzeug Y" der bequemste Weg um
``_BLOCKED_TOOLS_FOR_LDAP`` und die Sandbox-Gates herum – und damit eine
dauerhafte Rechteerhoehung fuer jeden, der delegieren darf.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROLES_FILE = PROJECT_ROOT / "data" / "agent_roles.json"

# Deckel. Die Rollenliste steht in der Beschreibung von `delegate` und damit in
# JEDEM Prompt jedes Laufs – eine unbegrenzte Liste kostet bei jeder Anfrage
# Kontext, auch wenn nie delegiert wird.
MAX_ROLLEN = 24
MAX_NAME_LEN = 60
MAX_DESC_LEN = 400
MAX_PROMPT_LEN = 6000
MAX_STEPS_CAP = 50

# Kennung = der Wert, den das Modell in `delegate(role=…)` schreibt. Bewusst eng
# gefasst (klein, ASCII): sie steht in einer Werkzeug-Beschreibung, in
# Journal-Zeilen und im Agent-Label. Ein Leerzeichen oder Umlaut darin macht
# jeden dieser Wege unnoetig fehleranfaellig.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")

# Dieselben fuenf Stufen wie llm.REASONING_LEVELS, plus "" = keine Vorgabe
# (dann entscheiden Profil und globale Einstellung).
EFFORT_STUFEN = ("", "off", "low", "medium", "high", "max")

# Das Delegations-Werkzeug selbst ist fuer eine Rolle NIE verfuegbar: sonst
# koennte Rolle A Rolle B rufen, die wieder A ruft. Der Deckel pro Lauf in
# agent.py ist die zweite Schranke, diese hier die erste.
DELEGATE_TOOL = "delegate"

# Nur diese Felder darf `aendern()` anfassen. Ohne Whitelist waere ein
# ``PUT /api/agent_roles/<id>`` mit beliebigen Schluesseln moeglich – dieselbe
# Luecke, die scheduler.update_job() bis 2026-07-28 hatte (dort konnte ein
# Domain-Nutzer sich `owner_privileged: true` setzen).
UPDATABLE_FIELDS = ("name", "description", "prompt", "tools", "profile_id",
                    "reasoning_effort", "max_steps", "enabled")

_lock = threading.RLock()


# ─── Vorgabe-Rollen ──────────────────────────────────────────────────────────
# Bewusst OHNE profile_id: eine fest verdrahtete Profil-UUID zeigt auf einem
# fremden System ins Nichts. Der Administrator weist das Profil zu (bei
# image_builder ist das der eigentliche Zweck – siehe Hinweis im Prompt).

VORGABE_ROLLEN: list[dict] = [
    {
        "id": "image_builder",
        "name": "Bild-Erzeuger",
        "description": (
            "Erzeugt oder sucht Bilder. Nutze diese Rolle fuer JEDEN Bildauftrag "
            "(Illustration, Symbolbild, Logo-Entwurf, Bildsuche) – sie kann ein "
            "eigenes Bildmodell verwenden, das im Chat-Profil nicht verfuegbar ist."
        ),
        "prompt": (
            "Du bist ein spezialisierter Bild-Agent. Du erzeugst genau EIN Bild "
            "zur beschriebenen Aufgabe (generate_image) oder suchst ein passendes "
            "(search_image), wenn ausdruecklich ein echtes Foto verlangt ist.\n"
            "- Formuliere den Bild-Prompt selbst aus und mache ihn konkret "
            "(Motiv, Bildaufbau, Stil, Farbstimmung).\n"
            "- Frage NICHT nach – arbeite mit dem, was in der Aufgabe steht.\n"
            "- Melde am Ende in einem Satz, was du erzeugt hast.\n"
            "HINWEIS FUER DEN ADMINISTRATOR: Diese Rolle braucht ein LLM-Profil "
            "mit einem Bildmodell. Ohne zugewiesenes Profil laeuft sie mit dem "
            "Profil des Aufrufers – bei einem Textmodell scheitert die "
            "Bilderzeugung dann genauso wie im Chat."
        ),
        "tools": ["generate_image", "search_image"],
        "profile_id": "",
        "reasoning_effort": "low",
        "max_steps": 6,
        "enabled": True,
    },
    {
        "id": "analyst",
        "name": "Analyst",
        "description": (
            "Wertet Daten und Dokumente aus: Tabellen, Wissensdatenbank, "
            "Kennzahlen, Diagramme. Nutze diese Rolle fuer Auswertungen, "
            "Vergleiche und Zahlen-Analysen, die mehr als einen Blick brauchen."
        ),
        "prompt": (
            "Du bist ein spezialisierter Analyse-Agent. Du arbeitest ausschliesslich "
            "LESEND.\n"
            "- Belege jede Aussage mit der Quelle (Dateiname, Dokumenttitel, "
            "Wissenseintrag).\n"
            "- Rechne selbst nach, statt Zahlen aus einem Text zu uebernehmen; "
            "nutze fuer Tabellen create_chart mit source= (dann laufen die Zahlen "
            "nicht durch das Modell).\n"
            "- Sage ausdruecklich, was du NICHT belegen kannst – eine erfundene "
            "Zahl ist schlimmer als eine Luecke.\n"
            "- Ergebnis: kurzes Fazit, dann die Belege."
        ),
        "tools": ["knowledge_search", "filesystem", "office_read", "create_chart"],
        "profile_id": "",
        "reasoning_effort": "high",
        "max_steps": 20,
        "enabled": True,
    },
    {
        "id": "writer",
        "name": "Autor",
        "description": (
            "Erstellt fertige Dokumente: Word, Excel, PowerPoint, PDF. Nutze "
            "diese Rolle, wenn eine Datei als Ergebnis herauskommen soll – sie "
            "kennt die Hausvorlagen."
        ),
        "prompt": (
            "Du bist ein spezialisierter Dokument-Agent. Du erzeugst die "
            "verlangte Datei mit den office_*-Werkzeugen.\n"
            "- Nutze IMMER die Hausvorlage; setze KEINE Schriftgroessen und "
            "Farben von Hand (office_template_info zeigt die Layouts).\n"
            "- Gliedere selbst sinnvoll: Titel, Abschnitte, Aufzaehlungen mit "
            "Unterebenen ('> ' fuer eine Ebene tiefer).\n"
            "- Keine Platzhalter im Ergebnis: kein 'TODO', kein '$(date)', kein "
            "'hier Text einfuegen'.\n"
            "- Melde am Ende den Dateinamen und was darin steht."
        ),
        "tools": ["office_create_word", "office_create_excel",
                  "office_create_powerpoint", "office_to_pdf",
                  "office_template_info", "office_read", "filesystem"],
        "profile_id": "",
        "reasoning_effort": "",
        "max_steps": 15,
        "enabled": True,
    },
]


# ─── Datei ───────────────────────────────────────────────────────────────────

def _leer() -> dict:
    return {"version": 1, "roles": []}


def _load() -> dict:
    with _lock:
        try:
            if not ROLES_FILE.exists():
                return _leer()
            data = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("roles"), list):
                print("[Rollen] agent_roles.json unbrauchbar – wird als leer behandelt", flush=True)
                return _leer()
            # Beschaedigte Einzeleintraege ueberspringen, nicht die ganze Datei
            # verwerfen: eine halb geschriebene Rolle darf nicht alle anderen
            # unsichtbar machen (gleiche Regel wie beim conv_log-Index).
            sauber = []
            for r in data["roles"]:
                if isinstance(r, dict) and ID_RE.match(str(r.get("id", ""))):
                    sauber.append(_normalisieren(r))
                else:
                    print(f"[Rollen] Eintrag ohne gueltige Kennung uebersprungen: {r!r:.80}", flush=True)
            data["roles"] = sauber
            return data
        except Exception as e:  # noqa: BLE001
            print(f"[Rollen] agent_roles.json nicht lesbar ({e}) – wird als leer behandelt", flush=True)
            return _leer()


def _save(data: dict) -> None:
    """Schreibt atomar (os.replace) und erhaelt Eigentuemer/Modus.

    Eigentuemer erhalten ist kein Detail: schreibt einmal root (Migration,
    Test aus einer Root-Shell), gehoert die Datei danach root und der
    unprivilegierte Dienst kann sie nicht mehr aendern – dieselbe Falle wie am
    2026-07-31 bei /opt/jarvis und am 2026-08-10 bei standard.pptx.
    """
    with _lock:
        ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
        alt_stat = None
        try:
            alt_stat = ROLES_FILE.stat()
        except OSError:
            pass
        tmp = ROLES_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            if alt_stat is not None:
                os.chmod(tmp, alt_stat.st_mode & 0o7777)
                if hasattr(os, "chown") and os.geteuid() == 0:
                    os.chown(tmp, alt_stat.st_uid, alt_stat.st_gid)
            else:
                os.chmod(tmp, 0o640)
        except OSError as e:
            print(f"[Rollen] Rechte/Eigentuemer nicht uebernommen: {e}", flush=True)
        os.replace(tmp, ROLES_FILE)


# ─── Validierung ─────────────────────────────────────────────────────────────

def _text(v: Any, grenze: int) -> str:
    s = "" if v is None else str(v)
    return s.strip()[:grenze]


def _valid_effort(v: Any) -> str:
    s = _text(v, 12).lower()
    return s if s in EFFORT_STUFEN else ""


def _valid_steps(v: Any) -> int:
    """0 = Vorgabe des Systems (config.MAX_AGENT_STEPS)."""
    try:
        n = int(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    return min(n, MAX_STEPS_CAP)


def _valid_tools(v: Any) -> list[str]:
    """Werkzeug-Whitelist. Nimmt Liste ODER kommagetrennten Text (die
    Oberflaeche schickt eine Liste, die API-Nutzung oft Text)."""
    if isinstance(v, str):
        roh = [t for t in re.split(r"[,\s]+", v) if t]
    elif isinstance(v, (list, tuple)):
        roh = [str(t).strip() for t in v]
    else:
        return []
    out: list[str] = []
    for t in roh:
        t = t.strip()
        # Kein delegate: keine Rolle darf delegieren (Rekursionsschutz, erste
        # von zwei Schranken – die zweite ist der Deckel pro Lauf).
        if not t or t == DELEGATE_TOOL or t in out:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", t):
            continue
        out.append(t)
    return out


def _normalisieren(r: dict) -> dict:
    """Bringt einen Eintrag in die kanonische Form. Unbekannte Schluessel
    fallen dabei weg – die Datei bleibt so das, was dieses Modul versteht."""
    return {
        "id": _text(r.get("id"), 40).lower(),
        "name": _text(r.get("name"), MAX_NAME_LEN) or _text(r.get("id"), MAX_NAME_LEN),
        "description": _text(r.get("description"), MAX_DESC_LEN),
        "prompt": _text(r.get("prompt"), MAX_PROMPT_LEN),
        "tools": _valid_tools(r.get("tools")),
        "profile_id": _text(r.get("profile_id"), 64),
        "reasoning_effort": _valid_effort(r.get("reasoning_effort")),
        "max_steps": _valid_steps(r.get("max_steps")),
        "enabled": bool(r.get("enabled", True)),
    }


def _pruefen(r: dict, vorhandene_ids: set[str]) -> None:
    """Wirft ValueError mit Klartext. Die Meldung geht 1:1 an den Administrator."""
    if not ID_RE.match(r["id"]):
        raise ValueError(
            "Kennung ungueltig: erlaubt sind 2–40 Zeichen aus a-z, 0-9, '_' und '-', "
            "beginnend mit einem Buchstaben oder einer Ziffer (z.B. 'image_builder')."
        )
    if r["id"] in vorhandene_ids:
        raise ValueError(f"Die Kennung '{r['id']}' ist bereits vergeben.")
    if not r["name"]:
        raise ValueError("Ein Anzeigename ist erforderlich.")
    if not r["description"]:
        # Die Beschreibung ist KEIN Schmuck: sie steht in der Werkzeug-
        # Beschreibung von `delegate` und ist die einzige Grundlage, auf der das
        # Modell entscheidet, ob es diese Rolle einsetzt. Ohne sie ist die Rolle
        # zwar anlegbar, aber praktisch unerreichbar.
        raise ValueError(
            "Eine Beschreibung ist erforderlich – daran erkennt der Orchestrator, "
            "wofuer diese Rolle zustaendig ist."
        )
    if not r["prompt"]:
        raise ValueError("Ein Rollen-Prompt ist erforderlich.")


# ─── Lesen ───────────────────────────────────────────────────────────────────

def alle(nur_aktive: bool = False) -> list[dict]:
    rollen = _load()["roles"]
    if nur_aktive:
        rollen = [r for r in rollen if r.get("enabled")]
    return rollen


def holen(rid: str) -> dict | None:
    rid = _text(rid, 40).lower()
    for r in _load()["roles"]:
        if r["id"] == rid:
            return r
    return None


def namen(nur_aktive: bool = True) -> list[str]:
    return [r["id"] for r in alle(nur_aktive=nur_aktive)]


# ─── Schreiben ───────────────────────────────────────────────────────────────

def anlegen(data: dict) -> dict:
    with _lock:
        d = _load()
        if len(d["roles"]) >= MAX_ROLLEN:
            raise ValueError(
                f"Es sind hoechstens {MAX_ROLLEN} Rollen moeglich – die Rollenliste "
                "steht in jedem Prompt und kostet dort Kontext."
            )
        r = _normalisieren(data)
        _pruefen(r, {x["id"] for x in d["roles"]})
        d["roles"].append(r)
        _save(d)
        return r


def aendern(rid: str, data: dict) -> dict:
    with _lock:
        d = _load()
        rid = _text(rid, 40).lower()
        for i, r in enumerate(d["roles"]):
            if r["id"] != rid:
                continue
            # Nur die Whitelist – die Kennung bleibt fest (sie steht in
            # Journal-Zeilen und moeglicherweise in gespeicherten Auftraegen).
            neu = dict(r)
            for f in UPDATABLE_FIELDS:
                if f in data:
                    neu[f] = data[f]
            neu["id"] = r["id"]
            neu = _normalisieren(neu)
            _pruefen(neu, {x["id"] for x in d["roles"] if x["id"] != rid})
            d["roles"][i] = neu
            _save(d)
            return neu
        raise ValueError(f"Rolle '{rid}' nicht gefunden.")


def loeschen(rid: str) -> bool:
    with _lock:
        d = _load()
        rid = _text(rid, 40).lower()
        vorher = len(d["roles"])
        d["roles"] = [r for r in d["roles"] if r["id"] != rid]
        if len(d["roles"]) == vorher:
            return False
        _save(d)
        return True


def _bildprofil_finden() -> str:
    """Id eines Profils, das Bilder erzeugen kann – oder "".

    WARUM AUTOMATISCH: die Rolle `image_builder` ist ohne Bildmodell wertlos (sie
    erbt dann das Textprofil des Aufrufers und sagt nur ab). Eine fest verdrahtete
    UUID im Code waere falsch, ein LEERES Feld ist es aber genauso – dann muss ein
    Administrator es wissen und nachtragen, und bis dahin scheitert jeder
    Bildauftrag mit einer korrekten, aber nutzlosen Meldung (auf DEV genau so
    passiert). Deshalb wird zur LAUFZEIT ein passendes Profil gesucht:
    Provider `google` kann Bilder (Imagen/Gemini-Image), ausserdem alles, dessen
    Modellname auf ein Bildmodell hindeutet.
    """
    try:
        from backend.config import config
        for p in config.profiles:
            m = (p.get("model") or "").lower()
            if "imagen" in m or "-image" in m or "dall-e" in m or "flux" in m:
                return p.get("id") or ""
        for p in config.profiles:
            if (p.get("provider") or "").lower() == "google":
                return p.get("id") or ""
    except Exception as e:  # noqa: BLE001
        print(f"[Rollen] Bildprofil nicht ermittelbar: {e}", flush=True)
    return ""


def saeen() -> int:
    """Legt die Vorgabe-Rollen an – NUR wenn die Datei noch gar nicht existiert.

    Nicht pro fehlender Rolle: eine bewusst geloeschte Rolle darf nicht bei
    jedem Start zurueckkommen (dieselbe Regel wie bei
    ``agent.py::_seed_instructions``, wo genau das eine Entscheidung des
    Administrators in einen wiederkehrenden Fehler verwandelt haette).
    """
    with _lock:
        if ROLES_FILE.exists():
            return 0
        d = _leer()
        bild = _bildprofil_finden()
        for v in VORGABE_ROLLEN:
            r = _normalisieren(v)
            # image_builder bekommt gleich ein bildfaehiges Profil, sonst ist die
            # Rolle beim ersten Bildauftrag wirkungslos.
            if r["id"] == "image_builder" and not r["profile_id"] and bild:
                r["profile_id"] = bild
                print(f"[Rollen] image_builder: Bildprofil {bild} zugewiesen", flush=True)
            d["roles"].append(r)
        _save(d)
        print(f"[Rollen] {len(d['roles'])} Vorgabe-Rollen angelegt ({ROLES_FILE})", flush=True)
        return len(d["roles"])


# ─── Fuer den Dispatch ───────────────────────────────────────────────────────

def effektive_werkzeuge(rolle: dict, verfuegbar: set[str],
                        gesperrt: set[str] | None = None) -> tuple[set[str], list[str]]:
    """Die Sicherheitsformel.

        Rollen-Whitelist  ∩  (verfuegbar − gesperrt)  −  delegate

    Rueckgabe: ``(erlaubt, fehlend)``. ``fehlend`` sind Werkzeuge aus der
    Whitelist, die es hier nicht gibt (Skill nicht aktiv) oder die dem Aufrufer
    verwehrt sind – der Aufrufer soll das im Klartext erfahren, statt eine Rolle
    zu bekommen, die stillschweigend ohne ihr Handwerkszeug arbeitet.

    Eine Rolle kann NUR wegnehmen. Wer diese Richtung umdreht, macht die
    Rollen-Whitelist zur Umgehung von ``_BLOCKED_TOOLS_FOR_LDAP`` und damit zu
    einer dauerhaften Rechteerhoehung fuer jeden, der delegieren darf.
    """
    gesperrt = set(gesperrt or ())
    erlaubt_pool = set(verfuegbar) - gesperrt - {DELEGATE_TOOL}
    wunsch = [t for t in (rolle.get("tools") or []) if t != DELEGATE_TOOL]
    erlaubt = {t for t in wunsch if t in erlaubt_pool}
    fehlend = [t for t in wunsch if t not in erlaubt_pool]
    return erlaubt, fehlend


def werkzeug_beschreibung(rollen: list[dict] | None = None) -> str:
    """Der Text, der in der Beschreibung von ``delegate`` steht.

    Hier – und nicht im System-Prompt – entscheidet sich, ob das Modell eine
    Rolle findet: die Werkzeug-Beschreibung ist der Ort, an den es schaut. Der
    System-Prompt hat gut 33.000 Zeichen, eine Zeile darin ist der schwaechste
    Hebel (gemessene Erfahrung mit WA_TASK_PROMPT).
    """
    rollen = alle(nur_aktive=True) if rollen is None else rollen
    if not rollen:
        return ""
    zeilen = [f"- {r['id']} ({r['name']}): {r['description']}" for r in rollen]
    return "\n".join(zeilen)

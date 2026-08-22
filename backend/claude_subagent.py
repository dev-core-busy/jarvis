"""Claude Subagent – Codearbeiten, die Claude Code an Jarvis abgibt.

WAS DAS IST
-----------
Claude Code (kostet Anthropic-Tokens) beschreibt eine eng umrissene Codeaufgabe;
Jarvis (kostenlose Tokens) fuehrt sie aus. Zurueck kommt ein PATCH, kein Text –
Claude prueft ihn und wendet ihn lokal an.

DIE MESSUNG, DIE DEN ZUSCHNITT BESTIMMT (Machbarkeitsprobe 2026-08-21, DEV,
Qwen3.6-35B, unprivilegierter Lauf im /tmp-Klon):

  * "Aendere X, Riegel muss gruen werden"        -> 2/2 Erfolg, ~10 s, 6 Schritte,
    minimaler Diff (1 Datei, 2 Zeilen), Ursachenanalyse fachlich richtig.
  * "Suche alle Vorkommen von Y"                 -> Liste richtig (24/24),
    ABGELEITETE ZAHL FALSCH (13 statt 11 Dateien).
  * "Aendere X, miss, mache rueckgaengig"        -> GESCHEITERT. 17 Schritte an
    sed-Escaping verbrannt, Antwort endete in einem rohen Tool-Call-Fragment.

Daraus die drei Regeln, die dieses Modul erzwingt:

1. KEIN ZAHLENWERT AUS DER MODELLANTWORT GEHT IN EINE BEWERTUNG EIN.
   Diff, Dateiliste und Riegel-Ergebnis rechnet DIESES MODUL – deterministisch,
   nach dem Lauf. Dieselbe Regel wie in ``skills/office/tabellen.py``: die Daten
   gehen nie durch das Sprachmodell. Das ist keine Stilfrage – in drei von drei
   Probelaeufen war die abgeleitete Zahl falsch, waehrend die zugrunde liegenden
   Daten (grep-Ausgabe, Testlauf) jedes Mal stimmten.

2. EINE DELEGATION = EIN ZIELZUSTAND. Auftraege mit Zustandswechsel ("aendere,
   miss, baue zurueck") ueberfordern das Modell nachweislich. Den Rueckbau macht
   dieses Modul mit ``git checkout``, nicht der Agent.

3. DER LAUF IST IMMER UNPRIVILEGIERT und arbeitet in einem WEGWERF-KLON unter
   /tmp. ``privileged`` ist hart ``False`` und KEIN Feld eines Auftrags – wer das
   aendert, macht aus dem Modul einen Weg zu beliebiger Codeausfuehrung auf dem
   Server. Weil /tmp laut ``sandbox.py`` Lese- UND Schreibwurzel fuer
   Domain-Benutzer ist, braucht der Lauf dafuer keinerlei Sonderrechte: er kommt
   an /opt/jarvis, an settings.json und an .env schlicht nicht heran.

RECHTE
------
Der Schluessel bindet den Lauf an einen BENUTZER. Die Freigabe pruefen die
Endpunkte in ``main.py`` (``_user_may_use_claudesub``) – bewusst dort und nicht
hier: Gruppen-Mitgliedschaften sind Sache der Anmeldeschicht. Dieses Modul
beantwortet nur "zu welchem Benutzer gehoert dieser Schluessel".

DER SCHLUESSEL WIRD NUR EINMAL ANGEZEIGT und danach als SHA-256 gespeichert.
Abweichung vom Standort-Sync (der sein Token dauerhaft zeigt), bewusst: hier
laege sonst eine Klartext-Vollmacht auf Platte, und wiederholtes Anzeigen bringt
nichts, was "neu erzeugen" nicht auch loest. Naeher an ``.mailkey``/``.sapkey``.
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "claude_subagent.json"

# Arbeitsbereiche: /tmp ist tmpfs und laut sandbox.py Lese- UND Schreibwurzel
# fuer unprivilegierte Laeufe. Genau deshalb kann der Lauf unprivilegiert sein.
ARBEIT_ROOT = Path("/tmp/claude_subagent")

# Schluessel-Praefix: <MARKE>-CSA-1.<kennung>.<geheimnis>
# Der Benutzer sieht den Schluessel und kopiert ihn – er traegt deshalb den
# ASSISTENTEN-NAMEN aus dem Branding, nicht "Jarvis" (Vorgabe des Nutzers).
# Dieselbe Quelle wie ``mail_accounts.kategorie_name``, aber OHNE Rueckfall auf
# den Firmennamen: das Feld heisst "Name des Assistenten".
SCHLUESSEL_KERN = "CSA-1."


def marken_slug() -> str:
    """Assistenten-Name als ASCII-Grosswort fuer den Schluessel-Praefix."""
    try:
        from backend.config import config  # noqa: PLC0415
        st = config.get_skill_states().get("branding", {}) or {}
        if st.get("enabled"):
            wert = ((st.get("config", {}) or {}).get("assistant_name") or "").strip()
            if wert:
                s = (wert.lower().replace("ä", "ae").replace("ö", "oe")
                     .replace("ü", "ue").replace("ß", "ss"))
                s = re.sub(r"[^a-z0-9]+", " ", s).strip().split(" ")[0]
                if s:
                    return s.upper()[:16]
    except Exception:  # noqa: BLE001
        pass
    return "JARVIS"


def marken_anzeige() -> str:
    """Assistenten-Name unveraendert (fuer Fliesstext), sonst "Jarvis"."""
    try:
        from backend.config import config  # noqa: PLC0415
        st = config.get_skill_states().get("branding", {}) or {}
        if st.get("enabled"):
            wert = ((st.get("config", {}) or {}).get("assistant_name") or "").strip()
            if wert:
                return wert[:64]
    except Exception:  # noqa: BLE001
        pass
    return "Jarvis"


def schluessel_prefix() -> str:
    return marken_slug() + "-" + SCHLUESSEL_KERN


# ─── Einstellbares ───────────────────────────────────────────────────────────
# Bis 2026-08-22 standen hier Modulkonstanten, waehrend das Manifest drei
# Schalter versprach: der Reiter zeigte sie, gespeichert wurden sie auch, und
# gelesen hat sie NIEMAND. Dieselbe Fehlerklasse wie ``prompt_tool_calling``
# (jahrelang wirkungslos, weil es in der Whitelist fehlte) – eine Zusage, die
# der Code nicht haelt.

SKILL_NAME = "claude_subagent"


def skill_config() -> dict:
    """Konfiguration des Skills (Administrator-Teil).

    Lazy und fehlertolerant: der Skill kann fehlen oder aus sein – dann gibt es
    ein leeres dict und es gelten die Vorgaben dieses Moduls.
    """
    try:
        from backend.config import config  # noqa: PLC0415
        st = config.get_skill_states().get(SKILL_NAME, {}) or {}
        return st.get("config", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def _cfg_int(schluessel: str, vorgabe: int, unten: int, oben: int) -> int:
    """Zahl aus der Skill-Config, hart begrenzt.

    Die Begrenzung ist kein Zierrat: die Werte kommen aus einem Formular und
    koennen auch von Hand in die settings.json geschrieben werden.
    """
    try:
        n = int(str(skill_config().get(schluessel, "")).strip() or vorgabe)
    except Exception:  # noqa: BLE001
        return vorgabe
    return max(unten, min(n, oben))


def gleichzeitig() -> int:
    """Parallele Laeufe (Vorgabe 2).

    Bewusst eine FUNKTION und keine Modulkonstante – der Wert ist im
    Admin-Reiter aenderbar und muss ohne Dienstneustart greifen (gleiche
    Begruendung wie ``documents.retention_days()``).
    """
    return _cfg_int("gleichzeitig", GLEICHZEITIG_VORGABE, 1, 4)


def laufzeit_s() -> int:
    return _cfg_int("laufzeit_s", LAUFZEIT_S_VORGABE, 60, 1800)


def arbeit_ttl_min() -> int:
    return _cfg_int("arbeit_ttl_min", ARBEIT_TTL_MIN_VORGABE, 5, 1440)


def profil_id() -> str:
    """LLM-Profil fuer Delegations-Laeufe – leer = das global aktive.

    Warum das ueberhaupt waehlbar ist: ein Delegations-Lauf ist kein Chat. Er
    laeuft minutenlang, ruft Werkzeuge auf und wird am Ende MASCHINELL geprueft.
    Dafuer kann ein anderes Modell richtig sein als fuer die Unterhaltung – und
    ohne dieses Feld erbt der Lauf zwangslaeufig das Chat-Profil.
    """
    return str(skill_config().get("profile_id") or "").strip()[:64]


def reasoning_effort() -> str:
    """Denktiefe der Delegations-Laeufe – leer = Profil bzw. globale Vorgabe.

    Ungueltige Werte werden zu "" (= keine Vorgabe) und NICHT durchgereicht: ein
    Tippfehler in der settings.json darf nicht jede Anfrage mit einem
    Provider-400 toeten (dieselbe Regel wie ``llm.normalize_effort``).
    """
    s = str(skill_config().get("reasoning_effort") or "").strip().lower()
    return s if s in EFFORT_STUFEN else ""


def profil_id_aufgeloest() -> str:
    """Die KENNUNG des gewaehlten Profils – "" wenn keines gewaehlt/gefunden.

    Noetig, weil ``profil_id()`` auch einen NAMEN liefern darf: an
    ``agent._role_profile_id`` gehoert die Kennung, ein Name liefe dort ins
    Leere. Nichts gewaehlt oder Eintrag verwaist -> "" (= Profil des Aufrufers),
    genau das Verhalten, das der Rollen-Weg fuer verwaiste Profile vorsieht.
    """
    if not profil_id():
        return ""
    return wirksames_profil().get("id", "")


def wirksames_profil() -> dict:
    """Welches LLM-Profil ein Delegations-Lauf WIRKLICH benutzt – zur Anzeige.

    Beantwortet die Frage, die man sonst nur durch Nachdenken ueber zwei
    Einstellungen beantworten kann: das Feld hier, sonst das global aktive.
    Zurueck kommt zusaetzlich die aufgeloeste ``temperature`` – siehe
    ``temperatur_hinweis``.
    """
    ergebnis = {"id": "", "name": "", "temperature": "", "gewaehlt": False,
                "gefunden": False}
    gewuenscht = profil_id()
    try:
        from backend.config import config  # noqa: PLC0415
        # ``profiles`` ist eine Liste, ``active_profile`` eine PROPERTY (kein
        # Aufruf). Ein Tippfehler waere hier besonders teuer: das breite
        # ``except`` unten wuerde ihn verschlucken und der Hinweis erschiene
        # einfach nie – ein Test prueft deshalb den Erfolgsfall.
        ziel = None
        if gewuenscht:
            ergebnis["gewaehlt"] = True
            # ID ODER NAME. Der Reiter rendert hier ein Textfeld (generisches
            # Skill-Formular), und eine UUID abzutippen ist eine Zumutung – der
            # Profilname steht in derselben Oberflaeche direkt daneben.
            # Kennung zuerst: sie ist unveraenderlich, der Name nicht.
            for p in (config.profiles or []):
                if str(p.get("id")) == gewuenscht:
                    ziel = p
                    break
            if ziel is None:
                for p in (config.profiles or []):
                    if str(p.get("name") or "").strip() == gewuenscht:
                        ziel = p
                        break
        else:
            ziel = config.active_profile
        if ziel:
            ergebnis.update({
                "id": str(ziel.get("id") or ""),
                "name": str(ziel.get("name") or ""),
                "temperature": str(ziel.get("temperature", "")),
                "gefunden": True,
            })
    except Exception:  # noqa: BLE001
        pass
    return ergebnis


def temperatur_hinweis() -> str:
    """Klartext, wenn das wirksame Profil auf "auto" steht – sonst "".

    WAS HIER BEWUSST NICHT BEHAUPTET WIRD: dass "auto" die Delegation kaputt
    macht. Am 2026-08-22 auf DEV gegen das aktive Profil gemessen (Qwen3.6-35B
    auf vLLM 0.27.1, je 12 Laeufe): ohne das Feld kamen 12 verschiedene
    Antworten, mit ``0.2`` nur 2 – die wirksame Vorgabe des Servers ist also
    hoch. Die WERKZEUG-Aufrufe waren in BEIDEN Faellen 12/12 exakt richtig.
    Der Hinweis nennt deshalb die Folge (nicht reproduzierbar), nicht ein
    Versagen, das nicht gemessen wurde.

    Ein geloeschtes Profil meldet sich ebenfalls – sonst liefe die Delegation
    still mit einem anderen Modell als im Reiter eingetragen.
    """
    p = wirksames_profil()
    if p["gewaehlt"] and not p["gefunden"]:
        return ("Das eingetragene LLM-Profil gibt es nicht mehr. Die Laeufe "
                "benutzen das global aktive Profil – bitte im Reiter "
                "'Claude Subagent' neu waehlen.")
    if not p["gefunden"]:
        return ""
    if (p["temperature"] or "").strip().lower() not in ("", "auto"):
        return ""
    return (f"Profil '{p['name']}' steht auf temperature 'auto'. Damit wird "
            f"das Feld nicht gesendet und es gilt die Vorgabe des Anbieters – "
            f"die ist von hier aus nicht bekannt und je nach Server "
            f"unterschiedlich. Folge: zwei gleiche Auftraege koennen "
            f"unterschiedlich ausgehen. Fuer die Delegation ist das vertretbar, "
            f"weil das Ergebnis ohnehin maschinell geprueft wird; scheitert ein "
            f"Auftrag aber sprunghaft, ist eine feste Zahl im Profil (z.B. 0.2) "
            f"das Erste, was man versucht.")

# ─── Grenzen ─────────────────────────────────────────────────────────────────
# Notbremsen, KEINE Aufbewahrungs-Schranken (siehe die Lehre zu Stueckzahlen im
# Projekt). Wird gekuerzt, steht die Zahl im Ergebnis – ein stiller Schnitt
# liesse Claude den Patch fuer vollstaendig halten.
MAX_DIFF_BYTES = 200_000              # Patch-Groesse
MAX_SPEC_ZEICHEN = 12_000             # Auftragstext
MAX_DATEIEN = 40                      # erlaubte Zieldateien je Auftrag
MAX_JOBS = 200                        # Ringpuffer der Auftragsliste

# Vorgaben der einstellbaren Werte. Gelesen wird ueber die FUNKTIONEN unten,
# nicht ueber diese Namen – siehe die Begruendung an ``_cfg_int``.
GLEICHZEITIG_VORGABE = 2              # parallele Laeufe
LAUFZEIT_S_VORGABE = 600              # Wanduhr je Auftrag
ARBEIT_TTL_MIN_VORGABE = 60           # Arbeitsbereiche danach abraeumen

# Dieselben fuenf Stufen wie ``llm.REASONING_LEVELS``, plus "" = keine Vorgabe
# (dann gilt Profil bzw. globale Einstellung).
EFFORT_STUFEN = ("", "off", "low", "medium", "high", "max")

# Werkzeug-Zuschnitt des Laufs. HARTE Schranke: sie sitzt in
# ``agent.py::_execute_tool`` VOR der Ausfuehrung, nicht nur in der Werkzeugliste,
# die das Modell sieht. ``None`` hiesse "keine Beschraenkung", die LEERE Menge
# "keine Werkzeuge" – nie auf Falsyness pruefen.
WERKZEUGE = {"filesystem", "shell_execute"}

_lock = threading.RLock()
_state: dict | None = None
_jobs_lock = threading.Lock()
_laufend: set = set()


# ─── Zustand ─────────────────────────────────────────────────────────────────

def _leer() -> dict:
    return {"schluessel": [], "jobs": []}


def _laden() -> dict:
    global _state
    with _lock:
        if _state is not None:
            return _state
        try:
            _state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if not isinstance(_state, dict):
                raise ValueError("kein Objekt")
            _state.setdefault("schluessel", [])
            _state.setdefault("jobs", [])
        except Exception:  # noqa: BLE001
            # Beschaedigte Datei darf den Dienst nicht kippen; sie wird beim
            # naechsten Schreiben ersetzt.
            _state = _leer()
        return _state


def _speichern() -> None:
    """Atomar schreiben, Eigentuemer und 0640 erhalten.

    Eigentuemer: der Root-Broker kann diese Datei anfassen – gehoerte sie danach
    root, koennte das unprivilegierte Backend seine eigenen Schluessel nicht mehr
    speichern (dieselbe Falle wie bei settings.json).
    """
    with _lock:
        daten = _state if _state is not None else _leer()
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        st = None
        try:
            if STATE_PATH.exists():
                st = STATE_PATH.stat()
        except Exception:  # noqa: BLE001
            st = None
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
        try:
            os.chmod(STATE_PATH, 0o640)
        except Exception:  # noqa: BLE001
            pass
        try:
            if os.geteuid() == 0:
                if st is not None and (st.st_uid != 0 or st.st_gid != 0):
                    # Vorhandene Datei: Eigentuemer beibehalten.
                    os.chown(STATE_PATH, st.st_uid, st.st_gid)
                elif st is None:
                    # NEUE Datei, als root angelegt. Ohne diesen Zweig bleibt sie
                    # root:root 0640 – der Dienst laeuft unprivilegiert und kann
                    # sie dann NICHT LESEN. Der Fehler sieht danach wie ein
                    # falscher Schluessel aus (HTTP 401), und niemand bringt das
                    # mit der Eigentuemerschaft in Verbindung. Genau so beim
                    # ersten Live-Test am 2026-08-21 passiert.
                    d = STATE_PATH.parent.stat()
                    if d.st_uid != 0 or d.st_gid != 0:
                        os.chown(STATE_PATH, d.st_uid, d.st_gid)
        except Exception:  # noqa: BLE001
            pass


def _reset_fuer_tests() -> None:
    global _state
    with _lock:
        _state = None


# ─── Schluessel ──────────────────────────────────────────────────────────────

def _norm_user(user: str) -> str:
    """Benutzername auf die Vergleichsform bringen.

    Dieselbe Klasse von Problem wie bei ``security_guard`` (2026-08-10): derselbe
    Mensch meldet sich mal als ``nexus\\x``, mal als ``x`` an. Ohne Normierung
    haette er je Tippform einen eigenen Schluessel-Satz.
    """
    u = (user or "").strip().lower()
    if "\\" in u:
        u = u.split("\\", 1)[1]
    if "@" in u:
        u = u.split("@", 1)[0]
    return u


def _hash(geheimnis: str) -> str:
    return hashlib.sha256(geheimnis.encode("utf-8")).hexdigest()


def schluessel_erzeugen(user: str) -> dict:
    """Erzeugt einen neuen Schluessel fuer diesen Benutzer.

    Ein Benutzer hat hoechstens EINEN Schluessel – ein zweiter Aufruf ersetzt den
    alten (und macht ihn damit sofort unbrauchbar). Das ist der Widerrufsweg:
    wer sein Geheimnis verloren oder verstreut hat, drueckt "neu erzeugen".

    Rueckgabe enthaelt ``schluessel`` im KLARTEXT – das ist die EINZIGE Stelle,
    an der er existiert. Gespeichert wird nur der Hash.
    """
    u = _norm_user(user)
    if not u:
        raise ValueError("Kein Benutzer angegeben")
    kennung = uuid.uuid4().hex[:12]
    geheimnis = secrets.token_urlsafe(32)
    voll = schluessel_prefix() + kennung + "." + geheimnis
    with _lock:
        daten = _laden()
        daten["schluessel"] = [k for k in daten["schluessel"]
                               if _norm_user(k.get("user", "")) != u]
        daten["schluessel"].append({
            "kennung": kennung,
            "user": u,
            "hash": _hash(geheimnis),
            "algo": "sha256",
            "letzte4": geheimnis[-4:],
            "erstellt": int(time.time()),
            "zuletzt": 0,
        })
        _speichern()
    return {"schluessel": voll, "kennung": kennung, "letzte4": geheimnis[-4:]}


def schluessel_info(user: str) -> dict | None:
    """Was die Oberflaeche zeigen darf – NIE das Geheimnis."""
    u = _norm_user(user)
    with _lock:
        for k in _laden()["schluessel"]:
            if _norm_user(k.get("user", "")) == u:
                return {"kennung": k.get("kennung"), "letzte4": k.get("letzte4"),
                        "erstellt": k.get("erstellt"), "zuletzt": k.get("zuletzt")}
    return None


def schluessel_loeschen(user: str) -> bool:
    u = _norm_user(user)
    with _lock:
        daten = _laden()
        vorher = len(daten["schluessel"])
        daten["schluessel"] = [k for k in daten["schluessel"]
                               if _norm_user(k.get("user", "")) != u]
        if len(daten["schluessel"]) == vorher:
            return False
        _speichern()
        return True


def benutzer_zu_schluessel(token: str) -> str | None:
    """Wem gehoert dieser Schluessel? ``None`` = unbekannt/ungueltig.

    Die Kennung steckt im Schluessel, damit ohne Durchprobieren nachgesehen
    werden kann – sie ist kein Geheimnis, das Geheimnis ist der dritte Teil.
    Verglichen wird ueber ``hmac.compare_digest``: ein zeichenweiser Vergleich
    verraet ueber die Laufzeit, wie viele Zeichen stimmen.
    """
    tok = (token or "").strip()
    # NICHT auf den AKTUELLEN Praefix pruefen: er traegt den Assistenten-Namen,
    # und der kann sich aendern – ein ausgegebener Schluessel wuerde sonst
    # ungueltig, sobald jemand das Branding umbenennt. Massgeblich ist der
    # unveraenderliche Kern "CSA-1."; das Geheimnis ist ohnehin der dritte Teil.
    schnitt = tok.find(SCHLUESSEL_KERN)
    if schnitt < 0:
        return None
    teile = tok[schnitt + len(SCHLUESSEL_KERN):].split(".", 1)
    if len(teile) != 2 or not teile[0] or not teile[1]:
        return None
    kennung, geheimnis = teile
    with _lock:
        for k in _laden()["schluessel"]:
            if k.get("kennung") != kennung:
                continue
            if hmac.compare_digest(str(k.get("hash", "")), _hash(geheimnis)):
                k["zuletzt"] = int(time.time())
                _speichern()
                return str(k.get("user", "")) or None
            return None
    return None


# ─── Auftragspruefung ────────────────────────────────────────────────────────

_RE_BASIS = re.compile(r"^[0-9a-f]{7,40}$")
# Zieldateien: relativer Pfad im Repo, keine Traversal, keine absoluten Pfade.
_RE_DATEI = re.compile(r"^[A-Za-z0-9_./-]{1,200}$")
# Der Riegel ist KEIN Freitext-Shellbefehl, sondern eine Testdatei des Repos.
# Alles andere waere ueber die API beliebige Codeausfuehrung fuer jeden mit
# Schluessel – die Freigabeliste soll Rechenzeit schuetzen, nicht die Shell.
_RE_RIEGEL = re.compile(r"^tests/[A-Za-z0-9_.-]+\.(py|js)$")


class AuftragsFehler(ValueError):
    """Auftrag ist nicht ausfuehrbar – Meldung geht im Klartext an den Aufrufer."""


def _rel_pfad(wert) -> str:
    """Relativer Repo-Pfad in Vergleichsform.

    ⚠ ``str.lstrip("./")`` ist ein ZEICHEN-Strip, kein Praefix-Strip: aus
    ``../../etc/passwd`` wird damit ``etc/passwd`` und JEDE Traversal-Pruefung
    danach laeuft ins Leere. Genau dieser Fehler steckte in der ersten Fassung
    dieses Moduls – gefunden hat ihn der Test, nicht das Lesen.

    Dieselbe Funktion muss die Pruefung UND der Vergleich in
    ``unerlaubte_dateien`` benutzen: zwei Normierungen mit unterschiedlicher
    Meinung sind das Muster, das in diesem Projekt schon mehrfach Stunden
    gekostet hat.
    """
    p = str(wert or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def auftrag_pruefen(spec: str, basis: str, dateien: list, riegel: str) -> dict:
    """Validiert einen Delegations-Auftrag. Wirft ``AuftragsFehler`` mit Grund.

    Fail-closed: was hier nicht ausdruecklich erlaubt ist, laeuft nicht.
    """
    s = (spec or "").strip()
    if not s:
        raise AuftragsFehler("Kein Auftragstext ('spec') angegeben.")
    if len(s) > MAX_SPEC_ZEICHEN:
        raise AuftragsFehler(
            f"Auftragstext ist {len(s)} Zeichen lang, erlaubt sind {MAX_SPEC_ZEICHEN}.")

    b = (basis or "").strip().lower()
    if not _RE_BASIS.match(b):
        raise AuftragsFehler(
            "'basis' muss ein Commit-Hash sein (7-40 Hexziffern). "
            "Delegiere nur von einem Stand, der auf origin/master liegt.")

    if not isinstance(dateien, list) or not dateien:
        raise AuftragsFehler(
            "'dateien' fehlt: gib die Dateien an, die der Lauf aendern darf. "
            "Ohne diese Liste gibt es keine Schranke gegen Kollateralschaden.")
    if len(dateien) > MAX_DATEIEN:
        raise AuftragsFehler(f"Zu viele Zieldateien ({len(dateien)}), erlaubt sind {MAX_DATEIEN}.")
    sauber = []
    for d in dateien:
        p = _rel_pfad(d)
        # Reihenfolge: erst die STRUKTUR (absolut? Traversal?), dann das Muster.
        # ".." als eigenes Pfadsegment pruefen, nicht als Teilstring – sonst
        # faellt eine legitime Datei "backend/..dotfile" durch.
        if (not p or p.startswith("/") or ".." in p.split("/")
                or not _RE_DATEI.match(p)):
            raise AuftragsFehler(f"Unzulaessiger Dateipfad: {d!r}")
        sauber.append(p)

    r = (riegel or "").strip()
    if not r:
        raise AuftragsFehler(
            "'riegel' fehlt: nenne die Testdatei, die das Ergebnis beweist "
            "(z.B. tests/test_branding_aliase.py). Ohne mechanischen Riegel "
            "wird nicht delegiert – die Modellantwort allein ist kein Nachweis.")
    if not _RE_RIEGEL.match(r):
        raise AuftragsFehler(
            f"'riegel' muss eine Testdatei des Repos sein (tests/*.py oder tests/*.js), "
            f"nicht {r!r}. Ein freier Shellbefehl ist hier bewusst nicht moeglich.")

    return {"spec": s, "basis": b, "dateien": sauber, "riegel": r}


# ─── Arbeitsbereich ──────────────────────────────────────────────────────────

def _repo_url() -> str:
    """Herkunft des Klons. Bewusst origin/master und NICHT /opt/jarvis:
    dessen git-HEAD ist alt (dort wird nicht committet) und die Arbeitskopie
    driftet per scp – ein Klon von dort passt zu keinem lokalen Stand."""
    try:
        out = subprocess.run(["git", "-C", str(PROJECT_ROOT), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
        url = (out.stdout or "").strip()
        if url:
            # SSH-Form fuer den Server auf token-loses HTTPS drehen: der Dienst
            # hat keinen Deploy-Key, das Repo ist oeffentlich.
            m = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", url)
            if m:
                return f"https://{m.group(1)}/{m.group(2)}.git"
            return url
    except Exception:  # noqa: BLE001
        pass
    return "https://github.com/dev-core-busy/jarvis.git"


def _lauf(cmd: list, cwd: Path, timeout: int = 120) -> tuple[int, str]:
    """Unterprozess mit Deckel; Rueckgabe (exitcode, stdout+stderr)."""
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                                "GIT_TERMINAL_PROMPT": "0"})
        return p.returncode, ((p.stdout or "") + (p.stderr or ""))
    except subprocess.TimeoutExpired:
        return 124, f"Zeitlimit von {timeout}s ueberschritten: {' '.join(cmd[:3])}"
    except Exception as e:  # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


def arbeitsbereich_anlegen(job_id: str, basis: str) -> tuple[Path, str | None]:
    """Legt den Wegwerf-Klon an. Rueckgabe (pfad, fehler)."""
    ziel = ARBEIT_ROOT / job_id
    try:
        shutil.rmtree(ziel, ignore_errors=True)
        ziel.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return ziel, f"Arbeitsbereich nicht anlegbar: {e}"

    work = ziel / "work"
    rc, aus = _lauf(["git", "clone", "--depth", "1", _repo_url(), str(work)],
                    cwd=ziel, timeout=300)
    if rc != 0:
        return work, f"Klon gescheitert: {aus[-500:]}"

    rc, kopf = _lauf(["git", "rev-parse", "HEAD"], cwd=work, timeout=30)
    kopf = (kopf or "").strip()
    if rc != 0 or not kopf:
        return work, "HEAD des Klons nicht lesbar."
    if not kopf.startswith(basis) and not basis.startswith(kopf[:len(basis)]):
        # NICHT stillschweigend weiterarbeiten: ein Patch gegen einen anderen
        # Stand laesst sich spaeter nicht sauber anwenden, und der Grund waere
        # dann nicht mehr erkennbar.
        return work, (f"Basis stimmt nicht: angefordert {basis}, origin/master steht auf "
                      f"{kopf[:12]}. Committe und pushe zuerst, oder delegiere nicht.")

    # Damit sowohl das filesystem-Werkzeug (laeuft als Dienstbenutzer) als auch
    # shell_execute (laeuft als jarvis_sandbox) arbeiten koennen. In der Probe
    # war GENAU DAS die Stelle, an der sich das Modell selbst blockierte: der
    # Klon gehoerte root, git verweigerte mit safe.directory.
    try:
        for p in ziel.rglob("*"):
            if p.is_dir():
                os.chmod(p, 0o777)
                continue
            # ⚠ DAS AUSFUEHRBIT MUSS ERHALTEN BLEIBEN. Ein pauschales 0666
            # nimmt git-getrackten Skripten (100755) das x-Bit – der naechste
            # `git diff` meldet dann Modus-Aenderungen an Dateien, die der
            # Auftrag nie angefasst hat, und der Riegel verwirft zu Recht.
            # Beim ersten Live-Lauf am 2026-08-21 waren das run.sh,
            # start_jarvis.sh und start_jarvis_root.sh. (Dieselbe Datei, die
            # dem Projekt schon einmal einen 203/EXEC beschert hat.)
            m = p.stat().st_mode
            os.chmod(p, 0o777 if (m & 0o111) else 0o666)
        os.chmod(ziel, 0o777)
    except Exception:  # noqa: BLE001
        pass
    return work, None


def diff_ermitteln(work: Path) -> tuple[str, list, bool]:
    """Patch, Dateiliste und Kuerzungs-Flag – DETERMINISTISCH, ohne Modell."""
    rc, roh = _lauf(["git", "diff"], cwd=work, timeout=60)
    if rc != 0:
        return "", [], False
    rc2, namen = _lauf(["git", "diff", "--name-only"], cwd=work, timeout=60)
    dateien = [z.strip() for z in (namen or "").splitlines() if z.strip()] if rc2 == 0 else []
    gekuerzt = False
    if len(roh.encode("utf-8")) > MAX_DIFF_BYTES:
        roh = roh[:MAX_DIFF_BYTES]
        gekuerzt = True
    return roh, dateien, gekuerzt


def riegel_laufen(work: Path, riegel: str) -> tuple[bool, str]:
    """Fuehrt die benannte Testdatei aus. Rueckgabe (bestanden, Ausgabe)."""
    pfad = work / riegel
    if not pfad.is_file():
        return False, f"Riegel {riegel} existiert im Arbeitsbereich nicht."
    cmd = ["python3", riegel] if riegel.endswith(".py") else ["node", riegel]
    rc, aus = _lauf(cmd, cwd=work, timeout=300)
    return rc == 0, aus[-8000:]


def unerlaubte_dateien(geaendert: list, erlaubt: list) -> list:
    """Welche Dateien wurden angefasst, die der Auftrag nicht nennt?"""
    ok = {_rel_pfad(d) for d in erlaubt}
    return [d for d in geaendert if _rel_pfad(d) not in ok]


def lauf_hinweis(antwort: str) -> str:
    """Diagnose-Zusatz, wenn der LAUF selbst gescheitert ist (kein Urteil).

    ``agent.py`` meldet Ausnahmen als ``f"Fehler: {str(e)}"`` – und bei
    httpx-Fehlern wie ``ConnectTimeout`` ist ``str(e)`` LEER. Beim Aufrufer
    steht dann nur ``"Fehler:"`` ohne jede Aussage, waehrend der Riegel voellig
    korrekt "leerer Patch" meldet. Am 2026-08-21 hat genau diese Kombination
    eine halbe Stunde Fehlersuche gekostet: das dem BENUTZER zugewiesene
    LLM-Profil zeigte auf einen abgeschalteten Host, und das Ergebnis sah aus
    wie ein Fehler dieses Moduls.

    Bewusst GETRENNT von ``bewerten()``: die Annahme-Entscheidung darf nichts
    aus der Modellantwort lesen. Das hier ist reine Diagnose fuer den Menschen
    bzw. fuer Claude – sie kippt kein Urteil, sie erklaert es.
    """
    t = (antwort or "").strip()
    if not t:
        return "Der Lauf hat keine Antwort geliefert."
    if t.rstrip(":").strip().lower() in ("fehler", "error"):
        return ("Der Agentenlauf ist mit einer Ausnahme OHNE Meldung abgebrochen. "
                "Typischer Grund: das dem Benutzer zugewiesene LLM-Profil ist "
                "nicht erreichbar (Einstellungen -> LLM-Profile). Die Ausnahme "
                "steht im Journal des Dienstes und in der Telemetrie.")
    return ""


def bewerten(diff: str, geaendert: list, erlaubt: list, riegel_ok: bool,
             riegel: str, gekuerzt: bool) -> tuple[bool, list]:
    """Der Riegel. ALLES-ODER-NICHTS – jede Einzelpruefung reicht zum Verwerfen.

    Bewusst eine reine Funktion ohne Seiteneffekte: sie ist die
    sicherheitsrelevanteste Stelle des Moduls und muss ohne Agentenlauf pruefbar
    sein. Keine ihrer Eingaben stammt aus der Modellantwort.
    """
    gruende = []
    if not (diff or "").strip():
        gruende.append("Der Lauf hat nichts geaendert (leerer Patch).")
    fremd = unerlaubte_dateien(geaendert, erlaubt)
    if fremd:
        gruende.append("Nicht freigegebene Dateien angefasst: " + ", ".join(fremd))
    if not riegel_ok:
        gruende.append(f"Riegel {riegel} ist rot.")
    if gekuerzt:
        gruende.append(f"Patch ueberschreitet {MAX_DIFF_BYTES} Bytes und wurde gekuerzt.")
    return (not gruende), gruende


def aufraeumen(job_id: str) -> None:
    shutil.rmtree(ARBEIT_ROOT / job_id, ignore_errors=True)


def alte_arbeitsbereiche_abraeumen() -> int:
    """Reste abgebrochener Laeufe entfernen. Frist statt 'sofort loeschen':
    ein gerade fertiger Auftrag soll noch abrufbar sein."""
    if not ARBEIT_ROOT.is_dir():
        return 0
    grenze = time.time() - arbeit_ttl_min() * 60
    weg = 0
    for p in ARBEIT_ROOT.iterdir():
        try:
            if p.is_dir() and p.stat().st_mtime < grenze:
                shutil.rmtree(p, ignore_errors=True)
                weg += 1
        except Exception:  # noqa: BLE001
            pass
    return weg


# ─── Auftragsverwaltung ──────────────────────────────────────────────────────

def job_anlegen(user: str, geprueft: dict) -> dict:
    with _lock:
        daten = _laden()
        job = {
            "id": uuid.uuid4().hex[:12],
            "user": _norm_user(user),
            "status": "wartet",
            "spec": geprueft["spec"],
            "basis": geprueft["basis"],
            "dateien": geprueft["dateien"],
            "riegel": geprueft["riegel"],
            "erstellt": int(time.time()),
            "gestartet": 0,
            "fertig": 0,
            "ergebnis": None,
            "fehler": "",
        }
        daten["jobs"].append(job)
        if len(daten["jobs"]) > MAX_JOBS:
            daten["jobs"] = daten["jobs"][-MAX_JOBS:]
        _speichern()
        return dict(job)


def job_holen(job_id: str, user: str) -> dict | None:
    """Nur eigene Auftraege. Fremde antworten 404 statt 403 – ob ein Auftrag
    existiert, ist selbst eine Information (Muster wie bei cron/Regeln)."""
    u = _norm_user(user)
    with _lock:
        for j in _laden()["jobs"]:
            if j.get("id") == job_id and _norm_user(j.get("user", "")) == u:
                return dict(j)
    return None


def jobs_liste(user: str, limit: int = 20) -> list:
    u = _norm_user(user)
    with _lock:
        eigene = [j for j in _laden()["jobs"] if _norm_user(j.get("user", "")) == u]
    return [{k: v for k, v in j.items() if k != "ergebnis"} for j in eigene[-limit:]][::-1]


def _job_setzen(job_id: str, **felder) -> None:
    with _lock:
        for j in _laden()["jobs"]:
            if j.get("id") == job_id:
                j.update(felder)
                _speichern()
                return


def freie_plaetze() -> int:
    with _jobs_lock:
        return max(0, gleichzeitig() - len(_laufend))


# ─── Der Lauf ────────────────────────────────────────────────────────────────

_VORSPANN = """Du bist ein Coding-Agent. Dein Arbeitsbereich ist der Ordner
{work}
Das ist ein vollstaendiger Klon des Projekts. Arbeite AUSSCHLIESSLICH dort.
Fasse /opt/jarvis nicht an.

REGELN
- Aendere NUR diese Dateien: {dateien}
- Halte den Eingriff minimal. Keine Umformatierungen, keine Aufraeumarbeiten,
  keine zusaetzlichen Dateien.
- Dein Ergebnis wird MASCHINELL geprueft: {riegel} muss danach fehlerfrei
  durchlaufen. Fuehre den Riegel selbst aus:
      cd {work} && {riegel_cmd}
  Laeuft er rot, lies ihn und behebe die Ursache. Rate nicht.
- Zaehle nichts und rechne nichts aus. Zahlen in deiner Antwort werden nicht
  ausgewertet - der Patch und der Riegel zaehlen.

=== AUFGABE ===
{spec}

Arbeite vollstaendig autonom, ohne Rueckfragen."""


def auftragstext(work: Path, geprueft: dict) -> str:
    riegel = geprueft["riegel"]
    cmd = f"python3 {riegel}" if riegel.endswith(".py") else f"node {riegel}"
    return _VORSPANN.format(
        work=str(work), dateien=", ".join(geprueft["dateien"]),
        riegel=riegel, riegel_cmd=cmd, spec=geprueft["spec"])


async def job_ausfuehren(job_id: str) -> None:
    """Fuehrt einen Auftrag aus. Ergebnis wird DETERMINISTISCH ermittelt.

    Der Agent bekommt eine EIGENE Instanz (nicht den geteilten Hauptagenten):
    ein Lauf dauert Minuten und wuerde sonst den Chat aller anderen blockieren.
    """
    with _jobs_lock:
        _laufend.add(job_id)
    work = None
    try:
        job = None
        with _lock:
            for j in _laden()["jobs"]:
                if j.get("id") == job_id:
                    job = dict(j)
                    break
        if not job:
            return

        _job_setzen(job_id, status="laeuft", gestartet=int(time.time()))
        work, fehler = arbeitsbereich_anlegen(job_id, job["basis"])
        if fehler:
            _job_setzen(job_id, status="fehler", fehler=fehler, fertig=int(time.time()))
            return

        from backend.agent import JarvisAgent
        agent = JarvisAgent()
        # HARTE Schranke: sitzt in _execute_tool vor der Ausfuehrung.
        agent._role_tools = set(WERKZEUGE)
        # Profil und Denktiefe ueber DIESELBEN Attribute wie die Rollen-Agenten
        # (agent_roles) und Short Tracks. Eigene waeren eine zweite Mechanik
        # fuer dieselbe Frage, und der Rollen-Weg behandelt ein geloeschtes
        # Profil bereits richtig (Lauf laeuft mit dem Profil des Aufrufers
        # weiter, Journal-Zeile statt Abbruch).
        agent._role_profile_id = profil_id_aufgeloest()
        auftrag = auftragstext(work, job)
        grenze_s = laufzeit_s()

        antwort = ""
        try:
            antwort = await asyncio.wait_for(
                agent.run_task_headless(
                    auftrag,
                    # "" heisst hier NICHT "aus", sondern "keine Vorgabe" – dann
                    # gilt Profil bzw. globale Einstellung. Deshalb None.
                    reasoning_effort=reasoning_effort() or None,
                    # privileged ist HART False und kein Feld des Auftrags.
                    # internet aus: die Aufgabe braucht kein Netz, und ein
                    # unprivilegierter Lauf mit Fremdtext soll keines haben.
                    actor={"user": job["user"], "privileged": False,
                           "internet": False, "sap": False},
                ),
                timeout=grenze_s,
            )
        except asyncio.TimeoutError:
            antwort = f"(Zeitlimit von {grenze_s}s ueberschritten)"
        except Exception as e:  # noqa: BLE001
            antwort = f"(Ausnahme im Lauf) {type(e).__name__}: {e}"

        # ── Ab hier rechnet NUR noch dieses Modul ──────────────────────────
        diff, geaendert, gekuerzt = diff_ermitteln(work)
        riegel_ok, riegel_aus = riegel_laufen(work, job["riegel"])
        angenommen, gruende = bewerten(diff, geaendert, job["dateien"],
                                       riegel_ok, job["riegel"], gekuerzt)
        # Diagnose ANHAENGEN, nicht das Urteil aendern: "leerer Patch" ist
        # richtig, sagt aber nicht, WARUM nichts entstanden ist.
        if not angenommen:
            hinweis = lauf_hinweis(antwort)
            if hinweis:
                gruende.append(hinweis)

        _job_setzen(
            job_id,
            status="fertig",
            fertig=int(time.time()),
            ergebnis={
                "angenommen": angenommen,
                "gruende": gruende,
                "diff": diff,
                "diff_gekuerzt": gekuerzt,
                "dateien": geaendert,
                "riegel": job["riegel"],
                "riegel_ok": riegel_ok,
                "riegel_ausgabe": riegel_aus,
                "antwort": (antwort or "")[:4000],
            },
        )
    except Exception as e:  # noqa: BLE001
        _job_setzen(job_id, status="fehler", fehler=f"{type(e).__name__}: {e}",
                    fertig=int(time.time()))
    finally:
        with _jobs_lock:
            _laufend.discard(job_id)
        if work is not None:
            # Arbeitsbereich bleibt bis zur Frist stehen: ein fertiger Auftrag
            # soll nachvollziehbar sein. Aufraeumen macht die TTL.
            pass

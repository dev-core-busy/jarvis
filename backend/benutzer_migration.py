"""Doppelte Benutzer-Ablagen zusammenfuehren (Vorfall 2026-09-07).

Bis zum Fix bildete JEDE der fuenf benutzerbezogenen Ablagen ihren Pfadteil mit
einem EIGENEN Sanitizer auf dem ROHEN Anmeldenamen. Derselbe Mensch bekam damit
je Tippform zwei Ablagen – gemeldet als ``memory_nexus_karsten_moeller.json``
neben ``memory_karsten_moeller.json``, auf DEV nachgemessen ausserdem
``chats/nexusandreas.bender`` (8 Sitzungen) neben ``chats/andreas.bender`` (1).

⚠ DIE RICHTUNG DER ZUORDNUNG IST DER GANZE ENTWURF: aus dem Dateinamen
``nexusandreas.bender`` laesst sich der Rohname NICHT rekonstruieren (der alte
Sanitizer hat den Backslash geloescht, und aus ``memory_andreas_bender`` ist
nicht ersichtlich, ob der Mensch ``andreas.bender`` oder ``andreas_bender``
heisst). Deshalb wird VORWAERTS gerechnet: fuer jeden BEKANNTEN Benutzernamen
werden die plausiblen Rohformen durch die historischen Sanitizer geschickt, und
nur ein so entstandener Treffer gilt als zuordenbar. **Was nicht zuordenbar
ist, wird GEMELDET und nicht angefasst** – ein geratener Zusammenschluss
vermischt die Daten zweier Menschen, und das ist nicht rueckholbar.

Der Trockenlauf ist die Vorgabe. Geschrieben wird nur mit ``anwenden(...)``,
und dann mit Sicherung.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from backend.benutzer import _KANAL_PRAEFIXE, norm_user, pfad_teil

PROJECT_ROOT = Path(__file__).parent.parent
DATA = PROJECT_ROOT / "data"


# ── Die historischen Sanitizer ──────────────────────────────────────────────
# Bewusst hier DUPLIZIERT und nicht importiert: sie sind Vergangenheit. Wuerden
# sie aus dem Produktivcode gelesen, ginge die Zuordnung genau in dem Moment
# verloren, in dem der Produktivcode korrigiert wird – also jetzt.

def _alt_memory(u: str) -> str | None:
    if not u or u in ("jarvis", ""):
        return None                      # Legacy-Datei memory.json, kein Fall
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", u)


def _alt_chats(u: str) -> str:
    out = "".join(c for c in (u or "").strip() if c.isalnum() or c in "._-@")
    return out or "anonymous"


def _alt_chat_history(u: str) -> str:
    x = (u or "anonymous").strip().lower()
    return "".join(c for c in x if c.isalnum() or c in "._-@") or "anonymous"


def _alt_sap(u: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", (u or "unbekannt").strip().lower()) or "unbekannt"


def _alt_support(u: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "_"
                   for c in (u or "anon")).strip("_") or "anon"


@dataclass
class Ablage:
    name: str
    verzeichnis: Path
    muster: str                  # "{}" fuer Ordner, "memory_{}.json" usw.
    art: str                     # ordner | json_dict | json_liste | text
    alt_sanitizer: object
    fallback: str = "anonymous"

    def pfad(self, teil: str) -> Path:
        return self.verzeichnis / self.muster.format(teil)

    def eintraege(self) -> list[str]:
        """Vorhandene Pfadteile dieser Ablage (ohne Muster-Rahmen)."""
        if not self.verzeichnis.is_dir():
            return []
        pre, _, suf = self.muster.partition("{}")
        raus = []
        for p in sorted(self.verzeichnis.iterdir()):
            if self.art == "ordner" and not p.is_dir():
                continue
            if self.art != "ordner" and not p.is_file():
                continue
            n = p.name
            if not n.startswith(pre) or not n.endswith(suf):
                continue
            # Sicherungen und Nebendateien nie als Eintrag zaehlen.
            if any(n.endswith(x) for x in (".bak", ".tmp", ".migrated")):
                continue
            teil = n[len(pre):len(n) - len(suf)] if suf else n[len(pre):]
            if teil:
                raus.append(teil)
        return raus


def ablagen() -> list[Ablage]:
    return [
        Ablage("memory", DATA, "memory_{}.json", "json_dict", _alt_memory),
        Ablage("chats", DATA / "chats", "{}", "ordner", _alt_chats),
        Ablage("chat_history", DATA / "chat_history", "{}.json", "json_liste", _alt_chat_history),
        Ablage("sap_instructions", DATA / "sap_instructions", "{}.md", "text", _alt_sap, "unbekannt"),
        Ablage("support_instructions", DATA / "support_instructions", "{}.md", "text", _alt_support, "anon"),
        # ⚠ Diese sechste Ablage hat der WAECHTER gefunden, nicht die Durchsicht
        # von Hand – genau deshalb prueft er die Regel und keine Liste.
        Ablage("vemas_instructions", DATA / "vemas_instructions", "{}.md", "text", _alt_sap, "unbekannt"),
    ]


# ── Bekannte Benutzernamen und Domaenen ─────────────────────────────────────

def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def domaenen_praefixe() -> list[str]:
    """Domaenen-Kurznamen, die als ``DOM\\user`` vor einem Namen stehen koennen.

    Zwei Quellen, und die zweite ist die verlaesslichere: die Konfiguration
    (``ad_domain``) sagt, welche Domaene eingestellt IST – die roh gespeicherten
    Namen in ``security_state.json``/``issues.json`` beweisen, welches Praefix
    wirklich benutzt WURDE (dort steht ``nexus\\andreas.bender`` woertlich).
    """
    raus: set[str] = set()
    s = _json(DATA / "settings.json") or {}
    dom = str(s.get("ad_domain") or "").strip()
    if dom:
        raus.add(dom.split(".")[0].lower())
        raus.add(dom.lower())
    for datei, holen in ((DATA / "security_state.json", lambda d: list((d.get("violations") or {}))),
                         (DATA / "issues.json", lambda d: [i.get("author", "") for i in (d if isinstance(d, list) else d.get("issues", []))])):
        d = _json(datei)
        if not d:
            continue
        try:
            for name in holen(d):
                if isinstance(name, str) and "\\" in name:
                    raus.add(name.split("\\")[0].strip().lower())
        except Exception:
            continue
    return sorted(x for x in raus if x)


def bekannte_benutzer() -> list[str]:
    """Normalisierte Benutzernamen aus allen Quellen, die welche kennen.

    ``user_sessions.json`` und ``ad_cache.json`` tragen sie bereits
    normalisiert (also mit Punkt: ``andreas.bender``) – genau die Form, die als
    Migrationsziel gebraucht wird und die aus einem alten Dateinamen nicht
    rekonstruierbar waere.
    """
    raus: set[str] = set()
    for datei, feld in ((DATA / "user_sessions.json", "users"),
                        (DATA / "ad_cache.json", "users")):
        d = _json(datei)
        if isinstance(d, dict):
            quelle = d.get(feld) if isinstance(d.get(feld), dict) else d
            for k in (quelle or {}):
                if isinstance(k, str) and k.strip():
                    raus.add(norm_user(k))
    # Die Ablagen selbst: ein bereits richtig benannter Eintrag ist ein Beleg
    # fuer den Namen (chats/andreas.bender beweist "andreas.bender").
    #
    # ⚠ ABER NUR, WENN ER NICHT MIT EINEM DOMAENEN-PRAEFIX BEGINNT. Genau hier
    # lag der Denkfehler der ersten Fassung, und der Waechter hat ihn gefangen:
    # ``pfad_teil("nexusandreas.bender")`` gibt den Namen UNVERAENDERT zurueck
    # (kein Backslash, kein @ mehr drin), der kaputte Eintrag sah damit wie ein
    # kanonischer aus, galt als "bekannter Benutzer" – und wurde von der
    # Zuordnung als bereits richtig uebersprungen. Die Migration fand NICHTS.
    praefixe = domaenen_praefixe()
    for a in ablagen():
        for e in a.eintraege():
            if pfad_teil(e, a.fallback) != e:
                continue
            if any(e.lower().startswith(p) and len(e) > len(p) for p in praefixe):
                continue
            # Kanal-Ablagen sind keine BENUTZER. Sie werden zugeordnet (ueber
            # `kanal_kandidaten`), gehoeren aber nicht in eine Liste, die
            # "bekannte Benutzer" heisst - eine Anzeige darf nicht behaupten,
            # `api_claude-subagent-probe` sei ein Mensch.
            if any(e.lower().startswith(pre[:-1]) for pre in _KANAL_PRAEFIXE):
                continue
            raus.add(e)
    d = _json(DATA / "issues.json")
    posten = d if isinstance(d, list) else (d or {}).get("issues", [])
    for i in posten if isinstance(posten, list) else []:
        if isinstance(i, dict) and isinstance(i.get("author"), str):
            raus.add(norm_user(i["author"]))
    return sorted(x for x in raus if x and x != "jarvis")


# Der Sentinel aus agent.py: unprivilegierte Laeufe OHNE Namen. Kein Mensch,
# aber eine echte Ablage - und ``pfad_teil`` streift die Unterstriche ab, also
# aendert sich der Dateiname und die alte Datei wuerde nie mehr gelesen.
_ANON_ACTOR = "__unprivilegiert__"


def kanal_kandidaten(eintraege: list[str], alt_sanitizer) -> list[str]:
    """Rohformen fuer Kanal-Ablagen (``api:``/``wa:``/``tg:``) rekonstruieren.

    ⚠ DAS IST KEIN RATEN, sondern VORWAERTS-VERIFIKATION: aus dem Eintrag
    ``api_Audit-Test`` wird die Rohform ``api:Audit-Test`` GEBILDET, und sie
    gilt nur dann, wenn der alte Sanitizer aus ihr genau diesen Eintrag
    erzeugt. Ohne diesen Schritt bleiben die Kanal-Ablagen als
    "nicht zuordenbar" liegen – und weil der korrigierte Code sie unter einem
    anderen Namen sucht (``api_audit-test`` statt ``api_Audit-Test``), waere
    ihr Inhalt still verloren. Auf DEV waren das vier Dateien.

    Der Trenner ist offen: der alte memory-Sanitizer machte aus dem Doppelpunkt
    ein ``_``, der von chats/chat_history loeschte ihn ganz.
    """
    raus: set[str] = set()
    for e in eintraege:
        for pre in _KANAL_PRAEFIXE:          # "wa:", "tg:", "api:"
            kurz = pre[:-1]                  # "wa", "tg", "api"
            for trenner in ("_", ""):
                anfang = kurz + trenner
                if not e.lower().startswith(anfang.lower()) or len(e) <= len(anfang):
                    continue
                roh = pre + e[len(anfang):]
                if str(alt_sanitizer(roh)).lower() == e.lower():
                    raus.add(roh)
    return sorted(raus)


def rohformen(name: str, praefixe: list[str]) -> list[str]:
    """Plausible Rohformen eines Anmeldenamens.

    Gross-/Kleinschreibung gehoert dazu: der alte memory-Sanitizer war
    case-sensitiv, ``NEXUS\\Andreas.Bender`` ergab ``NEXUS_Andreas_Bender``.
    """
    raus = {name, name.upper(), name.title()}
    for p in praefixe:
        for pp in (p, p.upper(), p.title()):
            for n in (name, name.upper(), name.title()):
                raus.add(f"{pp}\\{n}")
        raus.add(f"{name}@{p}")
    return sorted(raus)


# ── Befund ──────────────────────────────────────────────────────────────────

# ── Doppelte Schluessel in gemeinsamen Dateien ──────────────────────────────
# Nicht jede Ablage ist eine Datei je Benutzer: ``issues_admin_seen.json`` hat
# EINEN Schluessel je Benutzer, und auf DEV lagen dort beide Formen desselben
# Menschen ('nexus\andreas.bender' und 'andreas.bender'). Der korrigierte Code
# schreibt nur noch normalisiert – der alte Schluessel bliebe als Karteileiche
# liegen.
#
# ⚠ ``security_state.json`` steht hier BEWUSST NICHT drin. Dort liegen Sperren
# und Verstoss-Zaehler, und die Entscheidung von 2026-08-10 lautet ausdruecklich:
# der Altbestand wird beim LESEN mitgefunden und NICHT migriert – eine Sperre
# umzuschreiben ist eine Sicherheitsentscheidung und gehoert nicht in ein
# Aufraeumskript.
SCHLUESSEL_DATEIEN = [
    ("issues_admin_seen.json", None),   # None = die Datei selbst ist das dict
]


def _schluessel_vorgaenge() -> list[tuple[str, str, str]]:
    """(Datei, alter Schluessel, kanonischer Schluessel) fuer doppelte Eintraege."""
    raus = []
    for name, feld in SCHLUESSEL_DATEIEN:
        d = _json(DATA / name)
        if not isinstance(d, dict):
            continue
        ziel_dict = d.get(feld) if feld else d
        if not isinstance(ziel_dict, dict):
            continue
        for k in list(ziel_dict):
            if not isinstance(k, str):
                continue
            kanon = norm_user(k)
            if kanon != k:
                raus.append((name, k, kanon))
    return raus


def schluessel_aufraeumen(trocken: bool = True) -> list[str]:
    """Doppelte Benutzer-Schluessel zusammenfuehren.

    ⚠ BEI KONFLIKT GEWINNT DER KLEINERE (aeltere) Marker. Der Wert ist ein
    "bis hierhin gesehen"-Zeitstempel: mit dem groesseren verpasst der
    Administrator Meldungen, mit dem kleineren sieht er hoechstens eine
    doppelt. Die Halbfehlerstellungen sind nicht gleich schwer.
    """
    meldungen = []
    # ⚠ NACH DATEI GRUPPIERT, und das FELD wird beachtet. Beides hat eine
    # Gegenprobe gefunden (2026-09-07): die erste Fassung lud die Datei je
    # Vorgang NEU und arbeitete immer am Top-Level-dict. Bei zwei doppelten
    # Schluesseln in derselben Datei fand der zweite Durchgang seinen Eintrag
    # nicht mehr, und bei einer Datei MIT Feld (``security_state.json`` ->
    # "blocked") griff sie auf die falsche Ebene und warf einen KeyError.
    nach_datei: dict[str, list[tuple[str, str]]] = {}
    for name, alt_k, kanon in _schluessel_vorgaenge():
        nach_datei.setdefault(name, []).append((alt_k, kanon))
    felder = dict(SCHLUESSEL_DATEIEN)
    for name, paare in nach_datei.items():
        d = _json(DATA / name)
        if not isinstance(d, dict):
            continue
        feld = felder.get(name)
        ziel_dict = d.get(feld) if feld else d
        if not isinstance(ziel_dict, dict):
            continue
        geaendert = False
        for alt_k, kanon in paare:
            if alt_k not in ziel_dict:
                continue                      # schon in diesem Lauf erledigt
            if kanon in ziel_dict and ziel_dict[kanon] != ziel_dict[alt_k]:
                behalten = min(str(ziel_dict[kanon]), str(ziel_dict[alt_k]))
                meldungen.append(f"{name}: '{alt_k}' + '{kanon}' -> '{kanon}' "
                                 f"(aelterer Marker {behalten!r} bleibt)")
                if not trocken:
                    ziel_dict[kanon] = behalten
            else:
                meldungen.append(f"{name}: '{alt_k}' -> '{kanon}'")
                if not trocken:
                    ziel_dict.setdefault(kanon, ziel_dict[alt_k])
            if not trocken:
                ziel_dict.pop(alt_k, None)
                geaendert = True
        if geaendert and not trocken:
            (DATA / name).write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    return meldungen


@dataclass
class Vorgang:
    ablage: str
    quelle: Path
    ziel: Path
    benutzer: str
    art: str                     # umbenennen | zusammenfuehren
    hinweise: list[str] = field(default_factory=list)


@dataclass
class Befund:
    vorgaenge: list[Vorgang] = field(default_factory=list)
    unzuordenbar: list[tuple[str, str]] = field(default_factory=list)
    benutzer: list[str] = field(default_factory=list)
    praefixe: list[str] = field(default_factory=list)
    schluessel: list[str] = field(default_factory=list)


def finde() -> Befund:
    b = Befund(benutzer=bekannte_benutzer(), praefixe=domaenen_praefixe(),
               schluessel=schluessel_aufraeumen(trocken=True))
    for a in ablagen():
        vorhanden = a.eintraege()
        if not vorhanden:
            continue
        # Vorwaerts: welcher alte Pfadteil gehoert zu welchem Benutzer?
        # Neben den bekannten MENSCHEN auch die Kanal-Ablagen und den
        # Sentinel - sie sind keine Benutzer, aber echte Ablagen.
        kandidaten = list(b.benutzer) + kanal_kandidaten(vorhanden, a.alt_sanitizer) \
            + [_ANON_ACTOR]
        zuordnung: dict[str, str] = {}
        for u in kandidaten:
            ziel = pfad_teil(u, a.fallback)
            for roh in rohformen(u, b.praefixe):
                alt = a.alt_sanitizer(roh)
                if alt is None:
                    continue
                for e in vorhanden:
                    # Ein Eintrag ist nur dann Altbestand, wenn er von seinem
                    # eigenen Ziel ABWEICHT. Der frueher hier stehende
                    # Zusatztest ("und ist selbst nicht kanonisch") war die
                    # zweite Haelfte des Denkfehlers aus bekannte_benutzer und
                    # ist ersatzlos weg: ``e != ziel`` sagt schon alles.
                    if e.lower() == str(alt).lower() and e != ziel:
                        zuordnung[e] = ziel
        for e in vorhanden:
            ziel = zuordnung.get(e)
            if ziel is None:
                if pfad_teil(e, a.fallback) != e:
                    b.unzuordenbar.append((a.name, e))
                continue
            qp, zp = a.pfad(e), a.pfad(ziel)
            if qp == zp:
                continue
            b.vorgaenge.append(Vorgang(
                a.name, qp, zp,
                next((u for u in kandidaten if pfad_teil(u, a.fallback) == ziel), ziel),
                "zusammenfuehren" if zp.exists() else "umbenennen"))
    return b


# ── Anwenden ────────────────────────────────────────────────────────────────

def _sichere(pfade: list[Path], marke: str) -> Path | None:
    """Sicherung ALLER betroffenen Pfade als tar, VOR der ersten Aenderung.

    Die Anzahl gesicherter Posten wird zurueckgemeldet – eine Sicherung, deren
    Erfolg niemand prueft, ist keine (Register, 2026-08-25).
    """
    import tarfile
    da = [p for p in pfade if p.exists()]
    if not da:
        return None
    ziel = DATA / "backups" / f"benutzer-zusammenfuehrung-{marke}.tgz"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ziel, "w:gz") as t:
        for p in da:
            t.add(p, arcname=str(p.relative_to(PROJECT_ROOT)))
    with tarfile.open(ziel) as t:
        if not t.getnames():
            raise RuntimeError("Sicherung ist leer")
    return ziel


def _merge_json_dict(q: Path, z: Path, hinweise: list[str]) -> None:
    """memory: Schluessel zusammenfuehren, bei Konflikt gewinnt der NEUERE.

    Die Eintraege tragen ``updated`` – damit ist die Entscheidung gemessen und
    nicht geraten. Fehlt der Zeitstempel auf beiden Seiten, gewinnt das ZIEL
    (der Eintrag unter dem kanonischen Namen ist der, mit dem weitergearbeitet
    wurde).
    """
    a = _json(q) or {}
    b = _json(z) or {}
    if not isinstance(a, dict) or not isinstance(b, dict):
        raise RuntimeError(f"unerwartete Struktur in {q.name}/{z.name}")
    for k, v in a.items():
        if k not in b:
            b[k] = v
            continue
        ta = (v or {}).get("updated", "") if isinstance(v, dict) else ""
        tb = (b[k] or {}).get("updated", "") if isinstance(b[k], dict) else ""
        if ta > tb:
            b[k] = v
            hinweise.append(f"Schluessel '{k}': Fassung aus {q.name} ist neuer")
        elif ta != tb:
            hinweise.append(f"Schluessel '{k}': Fassung im Ziel bleibt (neuer)")
        else:
            hinweise.append(f"Schluessel '{k}': gleich alt, Ziel bleibt")
    z.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
    q.unlink()


def _merge_json_liste(q: Path, z: Path, hinweise: list[str]) -> None:
    """chat_history: anhaengen und nach ``ts`` sortieren.

    Ohne Sortierung stuende der aeltere Verlauf hinter dem neueren – der Chat
    laese sich dann nicht mehr als Gespraech lesen.
    """
    a = _json(q) or []
    b = _json(z) or []
    if not isinstance(a, list) or not isinstance(b, list):
        raise RuntimeError(f"unerwartete Struktur in {q.name}/{z.name}")
    zus = b + a
    def _ts(x):
        return (x or {}).get("ts", 0) if isinstance(x, dict) else 0
    if all(isinstance(x, dict) and "ts" in x for x in zus):
        zus.sort(key=_ts)
    else:
        hinweise.append("nicht alle Eintraege haben 'ts' – Reihenfolge Ziel+Quelle")
    hinweise.append(f"{len(a)} + {len(b)} = {len(zus)} Nachrichten")
    z.write_text(json.dumps(zus, ensure_ascii=False), encoding="utf-8")
    q.unlink()


def _merge_ordner(q: Path, z: Path, hinweise: list[str]) -> None:
    """chats: Sitzungen verschieben. Kollisionen bleiben STEHEN.

    Sitzungs-Kennungen sind 12 Hex-Zeichen, eine Kollision ist praktisch
    ausgeschlossen – aber sie waere ein Datenverlust, deshalb wird sie gemeldet
    statt geloest. Dateien auf Benutzerebene (``preprompt.txt``, ``.welcome_v1``)
    gehen mit; ist die Datei im Ziel schon da, bleibt die des Ziels.
    """
    z.mkdir(parents=True, exist_ok=True)
    rest = []
    for p in sorted(q.iterdir()):
        ziel = z / p.name
        if ziel.exists():
            if p.is_dir():
                rest.append(p.name)
                hinweise.append(f"Sitzung '{p.name}' gibt es im Ziel schon – Quelle bleibt stehen")
            else:
                hinweise.append(f"'{p.name}' im Ziel behalten, Fassung der Quelle verworfen")
                p.unlink()
            continue
        shutil.move(str(p), str(ziel))
    if rest:
        hinweise.append(f"{q.name} NICHT entfernt ({len(rest)} Kollision(en))")
        return
    try:
        q.rmdir()
    except OSError:
        hinweise.append(f"{q.name} nicht leer – bleibt stehen")


def _merge_text(q: Path, z: Path, hinweise: list[str]) -> None:
    """Anweisungsdateien: der NEUERE Text gewinnt, der andere wird gesichert.

    ⚠ AUSDRUECKLICH NICHT ANEINANDERGEHAENGT. Diese Dateien sind
    Prompt-Substrat; zwei verkettete Anweisungen koennen sich widersprechen,
    und dann entscheidet die Reihenfolge ueber das Verhalten des Agenten –
    genau der Vorfall vom 2026-08-17.
    """
    qm, zm = q.stat().st_mtime, z.stat().st_mtime
    if qm > zm:
        alt = z.with_suffix(z.suffix + ".vor-zusammenfuehrung")
        shutil.move(str(z), str(alt))
        shutil.move(str(q), str(z))
        hinweise.append(f"Quelle war neuer – bisheriger Zieltext liegt in {alt.name}")
    else:
        alt = q.with_suffix(q.suffix + ".vor-zusammenfuehrung")
        shutil.move(str(q), str(alt))
        hinweise.append(f"Ziel war neuer – Quelltext liegt in {alt.name}")


_MERGE = {"json_dict": _merge_json_dict, "json_liste": _merge_json_liste,
          "ordner": _merge_ordner, "text": _merge_text}


def anwenden(befund: Befund | None = None, trocken: bool = True) -> dict:
    """Fuehrt die Vorgaenge aus. ``trocken=True`` ist die Vorgabe.

    Idempotent: ein zweiter Lauf findet nichts mehr.
    """
    b = befund or finde()
    ergebnis: dict = {"trocken": trocken, "vorgaenge": [], "fehler": [],
                      "unzuordenbar": b.unzuordenbar, "sicherung": None}
    ergebnis["schluessel"] = b.schluessel
    if not b.vorgaenge and not b.schluessel:
        return ergebnis
    if b.schluessel and not trocken:
        schluessel_aufraeumen(trocken=False)
    if not b.vorgaenge:
        return ergebnis
    if not trocken:
        marke = time.strftime("%Y%m%d-%H%M%S")
        betroffen = [v.quelle for v in b.vorgaenge] + [v.ziel for v in b.vorgaenge]
        ergebnis["sicherung"] = str(_sichere(betroffen, marke) or "")
    arten = {a.name: a.art for a in ablagen()}
    for v in b.vorgaenge:
        eintrag = {"ablage": v.ablage, "benutzer": v.benutzer, "art": v.art,
                   "quelle": v.quelle.name, "ziel": v.ziel.name, "hinweise": v.hinweise}
        if trocken:
            ergebnis["vorgaenge"].append(eintrag)
            continue
        try:
            if not v.quelle.exists():
                v.hinweise.append("Quelle nicht mehr vorhanden – uebersprungen")
            elif v.art == "umbenennen":
                v.ziel.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(v.quelle), str(v.ziel))
            else:
                _MERGE[arten[v.ablage]](v.quelle, v.ziel, v.hinweise)
        except Exception as e:  # noqa: BLE001
            ergebnis["fehler"].append(f"{v.ablage}/{v.quelle.name}: {e}")
        ergebnis["vorgaenge"].append(eintrag)
    return ergebnis

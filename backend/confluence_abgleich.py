"""Confluence-Abgleich: die gespeicherten Einbindungen ins Wissen holen.

WAS ES IST (Vorgabe 2026-09-27): die unter ``/wissen`` gespeicherten Eintraege
der *Dynamischen Confluence-Einbindung* (``backend/confluence_bindung.py``)
werden vom vorhandenen 5-Minuten-Auftrag *Wissensabgleich* auf Aenderungen
geprueft und in die Wissensdatenbank uebernommen. Der Auftrag ruft ``lauf()``
VOR dem Index-Abgleich (``rag_autoindex.lauf``) – die hier geschriebenen
Dateien kommen damit im SELBEN Takt in den Index, ueber den EINEN vorhandenen
Indizierweg. Einen zweiten gibt es ausdruecklich nicht.

ENTSCHEIDUNGEN DES BETREIBERS (2026-09-27), hier als Code:

* **Direkt, Seitentext 1:1** – kein Entwurf, keine KI, keine Freigabe. Jede
  Seite wird eine Markdown-Datei im Wissensordner ihrer Wissensgruppe(n)
  (``<ordner>/confluence/<BEREICH>/<seite>_<titel>.md``) und bekommt die
  Gruppen des Eintrags als Zuordnung. Der Auftrag bleibt damit, was er ist:
  deterministisch und ohne LLM (siehe ``scheduler._execute``).
* **Geloeschte oder abgewaehlte Seiten verschwinden wieder** aus dem Wissen –
  Datei weg, Zuordnung weg; das Aufraeumen des Index erledigt der
  Index-Abgleich danach (verwaiste Eintraege).
* **Ein komplett markierter Zweig nimmt neue Unterseiten mit** (``ganz`` /
  ``zweige`` in der Auswahl), ein teilweise markierter nur die gespeicherten
  Seiten.

⚠ AENDERUNG = VERSIONSNUMMER. Die Seitenliste eines Bereichs kommt mit
``expand=version`` – eine Rundreise je 50 Seiten statt einer je Seite. Den
Inhalt holt der Lauf NUR fuer neue und geaenderte Seiten. Im Regelfall (nichts
geaendert) kostet ein Takt damit eine Handvoll Listenabrufe und schreibt nichts.

⚠ EIN FEHLGESCHLAGENER ABRUF LOESCHT NICHTS. Kann die Seitenliste eines
Bereichs nicht geholt werden (Netz, Rechte, Wartung), bleiben ALLE bisher
geholten Seiten dieses Bereichs liegen. „Nicht erreichbar" ist keine Aussage
ueber den Bestand – dieselbe Regel wie beim getrennten Netzlaufwerk im
Index-Abgleich (``streng=True``). Ohne sie loeschte eine Confluence-Wartung
am Abend das ganze Wissen, und der naechste Takt holte es wieder.

⚠ SKILL AUS = PAUSE, NICHT LOESCHEN. Ist der Confluence-Skill aus oder nicht
konfiguriert, laeuft gar nichts – auch kein Aufraeumen. Wer den Skill kurz
abschaltet, soll danach nicht vor einer leeren Wissensdatenbank stehen.

⚠ DECKEL JE TAKT (``MAX_ABRUFE_JE_LAUF``). Der erste Abgleich eines grossen
Bereichs holt hunderte Seiten; ohne Deckel liefe ein Takt minutenlang und der
naechste startete mitten hinein. Was offen bleibt, holt der naechste Takt –
die Oberflaeche nennt die Zahl.

⚠ TAG-FILTER (Vorgabe 2026-09-27): traegt ein Eintrag Tags, zaehlen von den
markierten Seiten nur die, die mindestens einen davon tragen (``tags_filtern``);
ohne Tags alle. Die Labels kommen mit DERSELBEN Seitenliste
(``expand=metadata.labels``), kein Abruf je Seite – und nur, wenn ueberhaupt ein
Eintrag Tags hat, sonst bleibt der Listenabruf wie er war. Ein neu gesetzter
oder entfernter Tag aendert die VERSION der Seite nicht; das ist kein Problem,
weil die Menge der gewollten Seiten in jedem Takt neu gebildet wird: eine
Seite, die ihren Tag verliert, faellt aus ``gewollt`` und wird aufgeraeumt.
⚠ LABELS UNBEKANNT ≠ KEINE LABELS. Liefert die Liste fuer eine Seite keine
Label-Angabe (``labels is None``), gilt der Bereich fuer diesen Eintrag als
nicht erreichbar – sonst raeumte eine Antwort ohne ``metadata`` still alle
getaggten Seiten aus dem Wissen.

Stand in ``data/confluence_abgleich.json`` (0640, in den Sperrlisten wie die
Einbindung selbst): je Seite Version, Datei und Gruppen, je Eintrag das
Ergebnis des letzten Laufs fuer die Anzeige.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

# Deckel je Takt fuer INHALTS-Abrufe (Listenabrufe sind nicht gedeckelt – ohne
# sie waere keine Aenderung erkennbar).
MAX_ABRUFE_JE_LAUF = 150
# Seiten je Bereich. Deckungsgleich mit der Baumansicht waere 500; der Abgleich
# darf mehr, weil ein komplett markierter Bereich sonst still Seiten verlöre.
MAX_SEITEN_JE_BEREICH = 3000
# Textlaenge je Seite. „1:1" heisst: nicht auf die 8000 Zeichen des Extraktors
# kuerzen – der Deckel schuetzt nur vor einer entgleisten Riesenseite.
TEXT_MAX = 400_000

_SPERRE = threading.Lock()        # EIN Lauf zugleich
_STAND_SPERRE = threading.Lock()


def _pfad() -> Path:
    """Ablage des Stands. Funktion statt Konstante – ein Test biegt sie um."""
    return Path(__file__).resolve().parent.parent / "data" / "confluence_abgleich.json"


def _stand_laden() -> dict:
    p = _pfad()
    if not p.is_file():
        return {"version": 1, "seiten": {}, "eintraege": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        # ⚠ NICHT STILL – und NICHT als leeren Stand weiterarbeiten: ein leerer
        # Stand hiesse „nichts ist geholt", und der Lauf schriebe alles neu,
        # ohne die alten Dateien je wieder zu finden. Der Aufrufer bricht ab.
        raise RuntimeError(f"Stand {p} nicht lesbar ({type(e).__name__}: {e})") from e
    if not isinstance(d, dict):
        raise RuntimeError(f"Stand {p} hat eine unerwartete Form")
    d.setdefault("seiten", {})
    d.setdefault("eintraege", {})
    return d


def _stand_speichern(d: dict) -> None:
    p = _pfad()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o640)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, p)


def eintrag_staende() -> dict:
    """Ergebnis des letzten Laufs je Eintrag (fuer die Liste unter /wissen).

    Fail-open in die harmlose Richtung: ohne lesbaren Stand steht in der Liste
    eben kein Abgleichsergebnis – die Einbindung selbst bleibt bedienbar."""
    try:
        with _STAND_SPERRE:
            return dict(_stand_laden().get("eintraege") or {})
    except Exception as e:  # noqa: BLE001
        print(f"[CF-Abgleich] {e}", flush=True)
        return {}


def import_zeiten() -> dict:
    """Wann jede Seite zuletzt ins Wissen importiert wurde – fuer den Baum.

    Rueckgabe ``{"seiten": {pid: iso}, "bereiche": {key: iso}}``; je Bereich
    steht der JUENGSTE Import einer seiner Seiten. Es zaehlen nur Seiten, die
    der Stand fuehrt – also die, die gerade im Wissen liegen; eine abgewaehlte
    Seite ist dort bereits entfernt.

    ⚠ ALTBESTAND OHNE ``zeit`` (Stand vor 2026-09-28): dann gilt die
    Aenderungszeit der Datei – sie wurde genau beim Import geschrieben. Fehlt
    auch die Datei, steht KEIN Datum da (nicht raten).

    Fail-open in die harmlose Richtung wie ``eintrag_staende``: ohne lesbaren
    Stand stehen eben keine Daten im Baum.
    """
    aus: dict = {"seiten": {}, "bereiche": {}}
    try:
        with _STAND_SPERRE:
            seiten = dict(_stand_laden().get("seiten") or {})
    except Exception as e:  # noqa: BLE001
        print(f"[CF-Abgleich] {e}", flush=True)
        return aus
    for pid, s in seiten.items():
        if not isinstance(s, dict):
            continue
        zeit = str(s.get("zeit") or "")
        if not zeit and s.get("datei"):
            try:
                zeit = datetime.fromtimestamp(_abs(s["datei"]).stat().st_mtime) \
                    .isoformat(timespec="seconds")
            except Exception:  # noqa: BLE001 – Datei weg: kein Datum
                zeit = ""
        if not zeit:
            continue
        aus["seiten"][str(pid)] = zeit
        key = str(s.get("space") or "")
        # ISO-Zeiten gleicher Form sind als Text chronologisch sortierbar.
        if key and zeit > aus["bereiche"].get(key, ""):
            aus["bereiche"][key] = zeit
    return aus


# ── Aufloesung: welche Seiten gehoeren zu einer Auswahl? ────────────────────

def _nachfahren(kinder: dict, wurzel: str) -> set:
    """Alle Seiten unter ``wurzel`` (ohne sie selbst), zyklenfest."""
    aus, stapel = set(), [wurzel]
    while stapel:
        cur = stapel.pop()
        for k in kinder.get(cur, ()):
            if k not in aus and k != wurzel:
                aus.add(k)
                stapel.append(k)
    return aus


def seiten_der_auswahl(sel: dict, liste: list, startseite: str = "") -> set:
    """Kennungen der Seiten, die eine Bereichs-Auswahl HEUTE abdeckt.

    ``liste`` ist die aktuelle Seitenliste des Bereichs (mit ``parent``).
    ⚠ ES ZAEHLT NUR, WAS IN DIESER LISTE STEHT: eine Kennung aus der Auswahl,
    die es im Bereich nicht (mehr) gibt, faellt heraus – geloescht oder
    verschoben, und eine untergeschobene fremde Kennung kommt so nie an.
    """
    ids = {str(p.get("id")) for p in liste if p.get("id") is not None}
    if sel.get("ganz") is True:
        return set(ids)
    kinder: dict = {}
    for p in liste:
        par = str(p.get("parent") or "")
        if par:
            kinder.setdefault(par, []).append(str(p.get("id")))
    aus = {s for s in (sel.get("seiten") or []) if s in ids}
    for z in sel.get("zweige") or []:
        if z in ids:
            aus.add(z)
            aus |= _nachfahren(kinder, z)
    if sel.get("start") is True and startseite and startseite in ids:
        aus.add(startseite)
    return aus


def tags_filtern(ids: set, liste: list, tags) -> set | None:
    """Von ``ids`` nur die Seiten, die mindestens einen der ``tags`` tragen.

    Leere ``tags`` = kein Filter (``ids`` unveraendert). ``None`` als Rueckgabe
    heisst: fuer mindestens eine betroffene Seite sind die Labels UNBEKANNT –
    der Aufrufer behandelt das wie einen gescheiterten Abruf und loescht
    nichts. Verglichen wird klein geschrieben (Confluence speichert Labels
    klein, die Ablage ebenfalls).
    """
    gesucht = {str(t).lower() for t in (tags or []) if t}
    if not gesucht:
        return set(ids)
    nach_id = {str(p.get("id")): p for p in liste}
    aus = set()
    for pid in ids:
        lab = (nach_id.get(pid) or {}).get("labels")
        if lab is None:
            return None
        if gesucht & {str(x).lower() for x in lab}:
            aus.add(pid)
    return aus


# ── Dateien ─────────────────────────────────────────────────────────────────

def _sicher(s: str, n: int) -> str:
    s = re.sub(r"[^\w\-äöüÄÖÜß]+", "_", str(s or "")).strip("_")
    return s[:n] or "x"


def _zielpfad(gruppen: list, space: str, pid: str, titel: str) -> Path:
    from backend.web_extractor import _target_dir_for_groups
    basis = _target_dir_for_groups(gruppen)
    return basis / "confluence" / _sicher(space, 60) / f"{pid}_{_sicher(titel, 60)}.md"


def _abs(datei: str) -> Path:
    from backend.tools.knowledge import PROJECT_ROOT
    p = Path(datei)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _rel(p: Path) -> str:
    from backend.tools.knowledge import PROJECT_ROOT
    try:
        return str(p.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(p)


def _datei_weg(datei: str) -> None:
    if not datei:
        return
    p = _abs(datei)
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    try:
        from backend import knowledge_groups as kg
        kg.set_assignment(datei, [])
    except Exception:  # noqa: BLE001
        pass
    # Leer gewordene Bereichs-Ordner mit abraeumen (nur den direkten).
    try:
        if p.parent.name and not any(p.parent.iterdir()):
            p.parent.rmdir()
    except Exception:  # noqa: BLE001
        pass


def _inhalt(titel: str, space_name: str, space: str, link: str, version: int,
            text: str) -> str:
    kopf = [f"# {titel}", "",
            f"> Quelle: Confluence · {space_name} ({space})" + (f" · {link}" if link else ""),
            f"> Stand: Version {version}, abgeglichen "
            f"{datetime.now().strftime('%d.%m.%Y %H:%M')}", ""]
    return "\n".join(kopf) + (text or "").strip() + "\n"


# ── Der Lauf ────────────────────────────────────────────────────────────────

def _aktiv() -> tuple[bool, str]:
    """(laeuft?, Grund) – Skill installiert+aktiv UND konfiguriert, wie der
    Container unter /wissen (``_cfb_aktiv``). EINE Regel, nicht nachgebaut."""
    try:
        from backend.main import _cfb_aktiv
        skill, conf = _cfb_aktiv()
    except Exception as e:  # noqa: BLE001
        return False, f"Zustand nicht ermittelbar ({e})"
    if not skill:
        return False, "Confluence-Skill ist nicht aktiv"
    if not conf:
        return False, "Confluence ist nicht konfiguriert"
    return True, ""


def lauf(client=None, aktiv=None) -> dict:
    """Ein Abgleich-Durchgang. Wirft NIE – Rueckgabe immer mit ``grund``.

    ``client``/``aktiv`` sind nur fuer Tests (Attrappe statt Netz). Rueckgabe:
    ``{"aktiv", "grund", "neu", "geaendert", "entfernt", "offen", "fehler"}``.
    """
    leer = {"aktiv": False, "neu": 0, "geaendert": 0, "entfernt": 0, "offen": 0,
            "fehler": 0}
    try:
        from backend import rag_autoindex
        if rag_autoindex.abgeschaltet():
            return {**leer, "grund": "Wissensabgleich ist abgeschaltet"}
    except Exception:  # noqa: BLE001
        pass
    ok, grund = aktiv if aktiv is not None else _aktiv()
    if not ok:
        return {**leer, "grund": grund}
    if not _SPERRE.acquire(blocking=False):
        return {**leer, "aktiv": True, "grund": "Confluence-Abgleich laeuft bereits"}
    try:
        return _lauf(client)
    except Exception as e:  # noqa: BLE001
        print(f"[CF-Abgleich] Lauf gescheitert: {type(e).__name__}: {e}", flush=True)
        return {**leer, "aktiv": True, "fehler": 1,
                "grund": f"fehlgeschlagen: {e}"[:300]}
    finally:
        _SPERRE.release()


def _lauf(client) -> dict:
    import backend.confluence_bindung as cfb
    from backend.confluence_client import html_to_text

    if client is None:
        from backend.confluence_client import ConfluenceClient
        client = ConfluenceClient()
    # ⚠ Wirft ``BestandUnlesbar``, wenn die Ablage da, aber nicht lesbar ist –
    # und MUSS es: als leere Liste gelesen raeumte der Abschnitt "Nicht mehr
    # gewollt" unten jede importierte Seite ab. ``lauf`` faengt den Fehler, der
    # Bestand bleibt unberuehrt.
    eintraege = cfb.liste()
    with _STAND_SPERRE:
        stand = _stand_laden()
    seiten_alt: dict = stand["seiten"]

    listen: dict = {}          # key -> Seitenliste | None (Abruf gescheitert)
    startseiten: dict = {}
    gescheitert: set = set()   # Bereiche, deren Bestand NICHT angefasst wird
    gewollt: dict = {}         # pid -> {space, name, titel, version, link, gruppen}
    je_eintrag: dict = {}
    # Labels nur holen, wenn ein Eintrag sie braucht – ohne Tags bleibt der
    # Listenabruf byte-gleich zum Stand vor dem Tag-Filter.
    mit_labels = any(e.get("tags") for e in eintraege)

    for e in eintraege:
        bid = e.get("id") or ""
        info = {"zeit": datetime.now().isoformat(timespec="seconds"),
                "seiten": 0, "offen": 0, "fehler": ""}
        je_eintrag[bid] = info
        gruppen = [g for g in (e.get("gruppen") or []) if g]
        if not gruppen:
            # Altbestand ohne Zuordnung: nicht raten, sondern benennen.
            info["fehler"] = "keiner Wissensgruppe zugeordnet"
            for sel in e.get("auswahl") or []:
                gescheitert.add(sel.get("key") or "")
            continue
        if e.get("tags_ungueltig"):
            # Kaputte Tag-Angabe (von Hand geschriebene Ablage): NICHT als
            # "kein Filter" lesen – das holte den ganzen Bereich ins Wissen.
            info["fehler"] = "Tags ungueltig"
            for sel in e.get("auswahl") or []:
                gescheitert.add(sel.get("key") or "")
            continue
        tags = e.get("tags") or []
        for sel in e.get("auswahl") or []:
            key = sel.get("key") or ""
            if not key:
                continue
            if key not in listen:
                try:
                    if mit_labels:
                        listen[key] = client.pages_in_space(
                            key, MAX_SEITEN_JE_BEREICH, with_parent=True,
                            with_version=True, with_labels=True)
                    else:
                        listen[key] = client.pages_in_space(key, MAX_SEITEN_JE_BEREICH,
                                                            with_parent=True, with_version=True)
                except Exception as ex:  # noqa: BLE001 – ConfluenceError wie Netzfehler
                    listen[key] = None
                    print(f"[CF-Abgleich] Seitenliste {key} nicht abrufbar: {ex}", flush=True)
            liste = listen[key]
            if liste is None:
                gescheitert.add(key)
                info["fehler"] = f"Bereich {key} nicht erreichbar"
                continue
            # ⚠ Eine LEERE Liste bei vorhandenem Bestand zaehlt wie ein Fehlschlag
            # (Code-Review 2026-10-07). Confluence antwortet auf einen Bereich,
            # den der Zugang nicht (mehr) lesen darf, mit 200 und leerer Liste –
            # ohne diese Schranke galten dann ALLE importierten Seiten als "nicht
            # mehr gewollt" und wurden geloescht ("ein fehlgeschlagener Abruf
            # loescht nichts – Netz, RECHTE, Wartung"). Ein wirklich geleerter
            # Bereich raeumt sich damit nicht selbst ab; dafuer gibt es "Einbindung
            # entfernen".
            if not liste and any((a.get("space") or "") == key for a in seiten_alt.values()):
                gescheitert.add(key)
                info["fehler"] = f"Bereich {key} liefert keine Seiten (Rechte?) – Bestand bleibt"
                print(f"[CF-Abgleich] Bereich {key}: leere Seitenliste bei vorhandenem "
                      "Bestand – nichts geloescht", flush=True)
                continue
            # An der Obergrenze ist die Liste nicht vollstaendig: was dahinter
            # liegt, ist nicht "nicht mehr gewollt", sondern nicht gelesen.
            # Uebernommen wird weiter, geloescht in diesem Bereich nichts.
            if len(liste) >= MAX_SEITEN_JE_BEREICH:
                gescheitert.add(key)
                info["fehler"] = (f"Bereich {key} hat mehr als {MAX_SEITEN_JE_BEREICH} Seiten – "
                                  "nicht vollständig gelesen, nichts gelöscht")
            st = ""
            if sel.get("start") is True and sel.get("ganz") is not True:
                if key not in startseiten:
                    try:
                        startseiten[key] = client.space_homepage(key)
                    except Exception as ex:  # noqa: BLE001
                        startseiten[key] = ""
                        info["fehler"] = f"Startseite von {key} nicht abrufbar"
                        gescheitert.add(key)
                        print(f"[CF-Abgleich] Startseite {key}: {ex}", flush=True)
                st = startseiten[key]
            nach_id = {str(p.get("id")): p for p in liste}
            ids = tags_filtern(seiten_der_auswahl(sel, liste, st), liste, tags)
            if ids is None:
                gescheitert.add(key)
                info["fehler"] = f"Tags von {key} nicht lesbar"
                continue
            info["seiten"] += len(ids)
            for pid in ids:
                p = nach_id.get(pid) or {}
                g = gewollt.setdefault(pid, {
                    "space": key, "name": sel.get("name") or key,
                    "titel": p.get("title") or pid,
                    "version": int(p.get("version") or 0),
                    "link": p.get("link") or "", "gruppen": [], "eintraege": []})
                for gid in gruppen:           # mehrere Eintraege: Gruppen vereinigen
                    if gid not in g["gruppen"]:
                        g["gruppen"].append(gid)
                g["eintraege"].append(bid)

    neu = geaendert = entfernt = offen = fehler = 0
    abrufe = 0
    seiten_neu: dict = {}

    for pid, g in gewollt.items():
        alt = seiten_alt.get(pid) or {}
        datei_alt = alt.get("datei") or ""
        aktuell = (alt and int(alt.get("v") or -1) == g["version"]
                   and sorted(alt.get("gruppen") or []) == sorted(g["gruppen"])
                   and datei_alt and _abs(datei_alt).is_file())
        if aktuell:
            seiten_neu[pid] = alt
            continue
        if abrufe >= MAX_ABRUFE_JE_LAUF:
            offen += 1
            if alt:
                seiten_neu[pid] = alt      # alter Stand bleibt, bis er dran ist
            for bid in g["eintraege"]:
                je_eintrag[bid]["offen"] += 1
            continue
        abrufe += 1
        try:
            full = client.get_page(pid, None, None)
            raw = (((full.get("body") or {}).get("storage") or {}).get("value")) or ""
            text = html_to_text(raw, TEXT_MAX)
            titel = full.get("title") or g["titel"]
            ver = int(((full.get("version") or {}).get("number")) or g["version"])
            ziel = _zielpfad(g["gruppen"], g["space"], pid, titel)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_text(_inhalt(titel, g["name"], g["space"], g["link"], ver, text),
                            encoding="utf-8")
            rel = _rel(ziel)
            if datei_alt and datei_alt != rel:
                _datei_weg(datei_alt)      # umbenannt oder andere Gruppe
            try:
                from backend import knowledge_groups as kg
                kg.set_assignment(rel, g["gruppen"])
            except Exception as ex:  # noqa: BLE001
                print(f"[CF-Abgleich] Zuordnung {rel}: {ex}", flush=True)
            # ``zeit`` = letzter WIRKLICHER Import (Inhalt geholt und
            # geschrieben). Ein Takt ohne Aenderung laesst sie stehen – der
            # Baum unter /wissen zeigt sie als "(Datum)" an der Zeile.
            seiten_neu[pid] = {"v": ver, "datei": rel, "space": g["space"],
                               "titel": titel, "gruppen": list(g["gruppen"]),
                               "zeit": datetime.now().isoformat(timespec="seconds")}
            if alt:
                geaendert += 1
            else:
                neu += 1
        except Exception as ex:  # noqa: BLE001
            fehler += 1
            if alt:
                seiten_neu[pid] = alt
            for bid in g["eintraege"]:
                je_eintrag[bid]["fehler"] = f"Seite {pid} nicht abrufbar"
            print(f"[CF-Abgleich] Seite {pid} nicht abrufbar: {ex}", flush=True)

    # Nicht mehr gewollt: aufraeumen – ausser der Bereich war nicht erreichbar.
    for pid, alt in seiten_alt.items():
        if pid in gewollt:
            continue
        if (alt.get("space") or "") in gescheitert:
            seiten_neu[pid] = alt
            continue
        _datei_weg(alt.get("datei") or "")
        entfernt += 1

    stand["seiten"] = seiten_neu
    stand["eintraege"] = je_eintrag
    stand["letzter_lauf"] = datetime.now().isoformat(timespec="seconds")
    with _STAND_SPERRE:
        _stand_speichern(stand)

    teile = []
    if neu:
        teile.append(f"{neu} neu")
    if geaendert:
        teile.append(f"{geaendert} geaendert")
    if entfernt:
        teile.append(f"{entfernt} entfernt")
    if offen:
        teile.append(f"{offen} im naechsten Lauf")
    if fehler or gescheitert:
        teile.append(f"{fehler + len(gescheitert - {''})} Fehler")
    grund = ", ".join(teile) if teile else (
        "nichts geaendert" if eintraege else "keine Einbindung")
    return {"aktiv": True, "grund": grund, "neu": neu, "geaendert": geaendert,
            "entfernt": entfernt, "offen": offen, "fehler": fehler + len(gescheitert - {""})}

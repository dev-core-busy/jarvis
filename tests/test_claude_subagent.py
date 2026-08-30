#!/usr/bin/env python3
"""Tests fuer den Skill "Claude Subagent" – Codearbeiten von Claude an Jarvis.

WAS DIESER TEST FESTHAELT, in der Reihenfolge der Wichtigkeit:

1. **Der Lauf ist IMMER unprivilegiert.** ``privileged`` steht hart auf ``False``
   und ist KEIN Feld eines Auftrags. Waere das anders, waere ein Delegations-
   Schluessel der bequemste Weg zu beliebiger Codeausfuehrung auf dem Server.
2. **Der Riegel ist eine TESTDATEI des Repos, kein Shellbefehl.** Ein freier
   Befehl waere ueber die API dasselbe wie eine Root-Shell fuer jeden mit
   Schluessel. Fail-closed: was nicht auf ``tests/*.py|js`` passt, laeuft nicht.
3. **Kein Zahlenwert aus der Modellantwort geht in die Bewertung ein.**
   ``bewerten()`` bekommt ausschliesslich Werte, die das Modul selbst ermittelt
   hat (git diff, Exitcode des Riegels). Begruendung ist gemessen, nicht
   vermutet: in der Machbarkeitsprobe vom 2026-08-21 war die vom Modell
   ABGELEITETE Zahl in drei von drei Laeufen falsch, waehrend die zugrunde
   liegenden Daten jedes Mal stimmten.
4. **Der Schluessel liegt im KLARTEXT auf Platte** (seit 2026-08-23, Vorgabe des
   Nutzers: er wird dauerhaft angezeigt) und ist ueber ``schluessel_info``
   wieder abrufbar – aber NUR fuer den Eigentuemer, und die Datei ist deshalb
   0600. Ein zweiter ``schluessel_erzeugen`` entwertet den alten – das ist
   der Widerrufsweg.
5. **Die Zustandsdatei ist gegen die Sandbox gesperrt** (``_APP_DENY_REL``,
   ``PRIVATE_FILES``, ``SHELL_SECRET_PATHS``): wer sie beschreiben kann, laesst
   kuenftige Laeufe unter fremder Kennung starten.

Laeuft ohne fastapi und ohne Netzzugriff. Ein Sandkasten-Waechter bricht mit
Exit 2 ab, wenn ein Modulpfad noch auf ``data/`` des Repos zeigt – sonst
schriebe der Testlauf in den echten Zustand (am 2026-08-18 in einem anderen
Test genau so passiert).

Exit 2 = konnte nicht laufen, 1 = Pruefung fehlgeschlagen, 0 = bestanden.

    python3 tests/test_claude_subagent.py
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


def nur_code(text: str) -> str:
    """Python-Quelltext ohne Docstrings und Kommentare.

    NOETIG, NICHT KOSMETIK: eine Pruefung wie "``privileged`` steht hart auf
    False" findet ihren Treffer sonst im DOCSTRING, der genau diese Zusage
    erklaert – und bleibt gruen, wenn der Code das Gegenteil tut. Das ist im
    Projekt mehrfach passiert.
    """
    ohne_doc = re.sub(r'"""(?:.|\n)*?"""', "", text)
    return "\n".join(z for z in ohne_doc.splitlines()
                     if not z.lstrip().startswith("#"))


from backend import claude_subagent as cs          # noqa: E402

# ── Sandkasten: Zustand in ein Wegwerf-Verzeichnis umbiegen ────────────────
TMP = Path(tempfile.mkdtemp(prefix="claude_subagent_"))
(TMP / "data").mkdir(parents=True)
cs.STATE_PATH = TMP / "data" / "claude_subagent.json"
cs.ARBEIT_ROOT = TMP / "arbeit"
cs._reset_fuer_tests()

# ── Waechter: zeigt noch irgendein Pfad ins Repo? ──────────────────────────
for _name in ("STATE_PATH", "ARBEIT_ROOT"):
    _p = getattr(cs, _name)
    if str(ROOT) in str(_p):
        print(f"ABBRUCH: {_name} zeigt ins Repo ({_p}) – der Test wuerde den "
              f"echten Zustand ueberschreiben.")
        sys.exit(2)

QUELLE = (ROOT / "backend" / "claude_subagent.py").read_text(encoding="utf-8")
CODE = nur_code(QUELLE)


# ══════════════════════════════════════════════════════════════════════════
section("1. Schluessel – Erzeugung, Pruefung, Widerruf")

_e = cs.schluessel_erzeugen("nexus\\andreas.bender")
_schluessel = _e["schluessel"]
check(_schluessel.startswith(cs.schluessel_prefix()), "Schluessel traegt das Marken-Praefix")
check(len(_schluessel) > 50, "Schluessel ist lang genug", f"{len(_schluessel)}")
check(cs.benutzer_zu_schluessel(_schluessel) == "andreas.bender",
      "Schluessel loest auf den normierten Benutzer auf",
      repr(cs.benutzer_zu_schluessel(_schluessel)))

# Normierung: dieselbe Person, andere Tippform -> derselbe Schluessel-Satz
check(cs.schluessel_info("ANDREAS.BENDER@nexus.int") is not None,
      "Normierung: UPN-Form findet denselben Eintrag")
check(cs.schluessel_info("nexus\\Andreas.Bender") is not None,
      "Normierung: Domaenen-Praefix findet denselben Eintrag")

# Der Schluessel liegt im Klartext und ist wieder abrufbar (Vorgabe 2026-08-23)
_roh = cs.STATE_PATH.read_text(encoding="utf-8")
_geheimnis = _schluessel.split(".", 2)[-1]
check(_geheimnis in _roh, "Geheimnis steht im Klartext auf Platte (dauerhafte Anzeige)")
check('"hash"' in _roh, "Der Hash bleibt daneben stehen (Vergleichsweg)")
check(cs.schluessel_info("andreas.bender").get("schluessel") == _schluessel,
      "schluessel_info gibt genau den ausgegebenen Text zurueck")
check(cs.schluessel_info("andreas.bender").get("alt") is False,
      "Neue Eintraege sind nicht 'alt'")
check(cs.schluessel_info("andreas.bender").get("letzte4") == _geheimnis[-4:],
      "Die letzten 4 Zeichen stehen weiterhin bereit")
# DIE Gegenprobe zur Klartext-Speicherung: 0600, nicht 0640. Ohne sie waere
# der Schluessel fuer jeden Prozess in der Gruppe `jarvis` lesbar.
_modus = cs.STATE_PATH.stat().st_mode & 0o777
check(_modus == 0o600, "Zustandsdatei ist 0600", oct(_modus))
import backend.sandbox as _sb  # noqa: E402
check("data/claude_subagent.json" in _sb.PRIVATE_FILES_STRENG,
      "... und steht in PRIVATE_FILES_STRENG (0600 beim Start)")
check("data/claude_subagent.json" not in _sb.PRIVATE_FILES,
      "... und NICHT mehr in der 0640-Liste (zwei Meinungen waeren ein Bug)")
check("data/claude_subagent.json" in _sb._APP_DENY_REL,
      "... bleibt fuer Werkzeuge gesperrt")

# ALTBESTAND aus der Hash-Zeit: gilt weiter, laesst sich aber nicht anzeigen.
# Geraten wird nichts – `alt: True` ist ausdruecklich etwas anderes als
# "kein Schluessel".
_alt_geheim = "AltbestandGeheimnis123"
with cs._lock:
    cs._laden()["schluessel"].append({
        "kennung": "altbestand01", "user": "alt.bestand",
        "hash": cs._hash(_alt_geheim), "algo": "sha256",
        "letzte4": _alt_geheim[-4:], "erstellt": 1, "zuletzt": 0})
    cs._speichern()
check(cs.benutzer_zu_schluessel(cs.schluessel_prefix() + "altbestand01." + _alt_geheim)
      == "alt.bestand", "Altbestand ohne Klartext gilt weiter")
_ai = cs.schluessel_info("alt.bestand")
check(_ai.get("schluessel") is None, "Altbestand liefert keinen Klartext")
check(_ai.get("alt") is True, "... und ist als 'alt' gekennzeichnet")
check(cs.schluessel_loeschen("alt.bestand") is True, "Altbestand ist loeschbar")

# Falsche/kaputte Schluessel
check(cs.benutzer_zu_schluessel(cs.schluessel_prefix() + "abc.falsch") is None,
      "Falsches Geheimnis -> None")
check(cs.benutzer_zu_schluessel("voellig-anderes-format") is None,
      "Fremdes Format -> None")
check(cs.benutzer_zu_schluessel(cs.schluessel_prefix() + "nurkennung") is None,
      "Fehlender dritter Teil -> None")
check(cs.benutzer_zu_schluessel("") is None, "Leerer Schluessel -> None")

# Ein Benutzer, EIN Schluessel: neu erzeugen entwertet den alten
_e2 = cs.schluessel_erzeugen("andreas.bender")
check(cs.benutzer_zu_schluessel(_schluessel) is None,
      "Neu erzeugen entwertet den alten Schluessel (Widerrufsweg)")
check(cs.benutzer_zu_schluessel(_e2["schluessel"]) == "andreas.bender",
      "Der neue Schluessel gilt")
check(len([k for k in cs._laden()["schluessel"]
           if k["user"] == "andreas.bender"]) == 1,
      "Es bleibt genau EIN Eintrag je Benutzer")

# Fremder Benutzer bekommt einen eigenen
_e3 = cs.schluessel_erzeugen("sven.sander")
check(cs.benutzer_zu_schluessel(_e3["schluessel"]) == "sven.sander",
      "Zweiter Benutzer, eigener Schluessel")
check(cs.benutzer_zu_schluessel(_e2["schluessel"]) == "andreas.bender",
      "... ohne den ersten zu stoeren")

check(cs.schluessel_loeschen("sven.sander") is True, "Loeschen meldet Erfolg")
check(cs.benutzer_zu_schluessel(_e3["schluessel"]) is None,
      "Geloeschter Schluessel gilt nicht mehr")
check(cs.schluessel_loeschen("gibtsnicht") is False,
      "Loeschen eines unbekannten Benutzers meldet False")

check("compare_digest" in CODE, "Vergleich laeuft zeitkonstant (compare_digest)")


# ══════════════════════════════════════════════════════════════════════════
section("2. Auftragspruefung – fail-closed")

_gut = dict(spec="Aendere X", basis="bcf1ba3", dateien=["frontend/css/chat.css"],
            riegel="tests/test_branding_aliase.py")


def _wirft(grund_teil, **abweichung):
    args = dict(_gut)
    args.update(abweichung)
    try:
        cs.auftrag_pruefen(**args)
        return False, "keine Ausnahme"
    except cs.AuftragsFehler as e:
        return (grund_teil.lower() in str(e).lower()), str(e)


_p = cs.auftrag_pruefen(**_gut)
check(_p["basis"] == "bcf1ba3" and _p["dateien"] == ["frontend/css/chat.css"],
      "Gueltiger Auftrag wird angenommen")

check(_wirft("auftragstext", spec="  ")[0], "Leerer Auftragstext -> Fehler")
check(_wirft("zeichen", spec="x" * (cs.MAX_SPEC_ZEICHEN + 1))[0],
      "Zu langer Auftragstext -> Fehler")
check(_wirft("commit", basis="master")[0], "Basis 'master' statt Hash -> Fehler")
check(_wirft("commit", basis="")[0], "Leere Basis -> Fehler")
check(_wirft("commit", basis="zzzz999")[0], "Nicht-Hex-Basis -> Fehler")
check(_wirft("dateien", dateien=[])[0], "Leere Dateiliste -> Fehler")
check(_wirft("dateien", dateien="alles")[0], "Dateiliste kein Array -> Fehler")
check(_wirft("zu viele", dateien=[f"a{i}.py" for i in range(cs.MAX_DATEIEN + 1)])[0],
      "Zu viele Zieldateien -> Fehler")
check(_wirft("unzulaessig", dateien=["../../etc/passwd"])[0],
      "Traversal im Dateipfad -> Fehler")
check(_wirft("unzulaessig", dateien=["/etc/shadow"])[0],
      "Absoluter Pfad -> Fehler")

# DIE WICHTIGSTE PRUEFUNG DIESES ABSCHNITTS: der Riegel ist kein Shellbefehl.
check(_wirft("riegel", riegel="")[0], "Fehlender Riegel -> Fehler")
for _boese in ("rm -rf /", "python3 -c 'import os'", "tests/../../etc/passwd",
               "bash tests/x.py", "tests/test_x.py; rm -rf /", "make test",
               "tests/test_x.sh", "/opt/jarvis/tests/test_x.py"):
    _t, _m = _wirft("riegel", riegel=_boese)
    check(_t, f"Riegel {_boese!r} wird abgelehnt", _m)
check(cs.auftrag_pruefen(**{**_gut, "riegel": "tests/test_icon_semantik.js"})["riegel"]
      == "tests/test_icon_semantik.js", "tests/*.js wird als Riegel akzeptiert")

check("_RE_RIEGEL" in CODE and "tests/" in QUELLE,
      "Riegel-Muster ist im Code verankert")


# ══════════════════════════════════════════════════════════════════════════
section("3. Der Riegel bewertet – alles-oder-nichts")

_dateien = ["frontend/css/chat.css"]

_a, _g = cs.bewerten("diff --git a/x b/x\n+zeile", _dateien, _dateien, True,
                     "tests/t.py", False)
check(_a is True and _g == [], "Alles gut -> angenommen")

_a, _g = cs.bewerten("", [], _dateien, True, "tests/t.py", False)
check(_a is False and any("leerer Patch" in x for x in _g),
      "Leerer Patch -> verworfen", str(_g))

_a, _g = cs.bewerten("d", ["backend/main.py"], _dateien, True, "tests/t.py", False)
check(_a is False and any("Nicht freigegebene" in x for x in _g),
      "Fremde Datei angefasst -> verworfen", str(_g))

_a, _g = cs.bewerten("d", _dateien, _dateien, False, "tests/t.py", False)
check(_a is False and any("rot" in x for x in _g),
      "Riegel rot -> verworfen", str(_g))

_a, _g = cs.bewerten("d", _dateien, _dateien, True, "tests/t.py", True)
check(_a is False and any("gekuerzt" in x for x in _g),
      "Gekuerzter Patch -> verworfen (kein stiller Schnitt)", str(_g))

_a, _g = cs.bewerten("", ["backend/main.py"], _dateien, False, "tests/t.py", True)
check(_a is False and len(_g) == 4, "Mehrere Maengel werden alle genannt", str(_g))

check(cs.unerlaubte_dateien(["./frontend/css/chat.css"], _dateien) == [],
      "Fuehrendes ./ wird beim Vergleich normalisiert")

# Der Riegel darf nichts aus der Modellantwort lesen.
_sig = re.search(r"def bewerten\(([^)]*)\)", CODE, re.S)
check(_sig is not None and "antwort" not in (_sig.group(1) if _sig else ""),
      "bewerten() nimmt die Modellantwort NICHT entgegen")

# Diagnose ist GETRENNT vom Urteil – sie erklaert, sie entscheidet nicht.
check(cs.lauf_hinweis("") == "Der Lauf hat keine Antwort geliefert.",
      "Leere Antwort wird benannt")
check("Profil" in cs.lauf_hinweis("Fehler:"),
      "Nackte Fehlermeldung 'Fehler:' verweist auf das LLM-Profil",
      cs.lauf_hinweis("Fehler:"))
check("Profil" in cs.lauf_hinweis("  ERROR  "),
      "... auch in anderer Schreibweise")
check(cs.lauf_hinweis("Ich habe die Variable ergaenzt.") == "",
      "Eine echte Antwort erzeugt KEINEN Hinweis")
_bw = CODE[CODE.find("def bewerten"):CODE.find("def aufraeumen")]
check("lauf_hinweis" not in _bw, "bewerten() ruft die Diagnose nicht auf")

# Das Ausfuehrbit git-getrackter Skripte muss den Klon ueberleben – sonst
# meldet `git diff` Modus-Aenderungen an Dateien, die niemand angefasst hat.
_ab = CODE[CODE.find("def arbeitsbereich_anlegen"):CODE.find("def diff_ermitteln")]
check("0o111" in _ab, "Ausfuehrbit wird beim Rechte-Setzen erhalten")
check(re.search(r"os\.chmod\(p,\s*0o777 if p\.is_dir\(\) else 0o666\)", _ab) is None,
      "Kein pauschales 0666 mehr (das nahm Skripten das x-Bit)")


# ══════════════════════════════════════════════════════════════════════════
section("4. Der Lauf ist unprivilegiert und eng zugeschnitten")

check(re.search(r'"privileged"\s*:\s*False', CODE) is not None,
      "actor setzt privileged hart auf False")
check(re.search(r'"privileged"\s*:\s*True', CODE) is None,
      "Nirgends wird privileged=True gesetzt")
check("privileged" not in str(cs.auftrag_pruefen(**_gut)),
      "privileged ist kein Feld eines geprueften Auftrags")
check(re.search(r'job\.get\(\s*["\']privileged', CODE) is None,
      "Der Lauf liest privileged nicht aus dem Auftrag")

check(isinstance(cs.WERKZEUGE, set) and cs.WERKZEUGE,
      "WERKZEUGE ist eine nicht-leere Whitelist")
check(cs.WERKZEUGE == {"filesystem", "shell_execute"},
      "Zuschnitt: nur filesystem + shell_execute", str(cs.WERKZEUGE))
check("_role_tools" in CODE, "Zuschnitt landet auf _role_tools (harte Schranke)")
check(re.search(r"_role_tools\s*=\s*None", CODE) is None,
      "_role_tools wird nie auf None gesetzt (None = keine Beschraenkung)")
check(re.search(r'"internet"\s*:\s*False', CODE) is not None,
      "Der Lauf bekommt keinen Internet-Zugriff")

check("/tmp" in QUELLE and "ARBEIT_ROOT" in CODE,
      "Arbeitsbereich liegt unter /tmp (dort darf ein unprivilegierter Lauf schreiben)")
check(re.search(r"/opt/jarvis", CODE) is None,
      "Kein hart verdrahteter Pfad nach /opt/jarvis im Code")


# ══════════════════════════════════════════════════════════════════════════
section("5. Auftraege sind an ihren Besitzer gebunden")

_j = cs.job_anlegen("andreas.bender", _p)
check(_j["user"] == "andreas.bender" and _j["status"] == "wartet",
      "Auftrag traegt Besitzer und Status")
check(cs.job_holen(_j["id"], "andreas.bender") is not None,
      "Eigener Auftrag ist abrufbar")
check(cs.job_holen(_j["id"], "sven.sander") is None,
      "Fremder Auftrag ist NICHT abrufbar (404 statt 403)")
check(cs.job_holen("gibtsnicht", "andreas.bender") is None,
      "Unbekannter Auftrag -> None")
check(cs.job_holen(_j["id"], "NEXUS\\Andreas.Bender") is not None,
      "Normierung gilt auch beim Abruf")

cs.job_anlegen("sven.sander", _p)
_liste = cs.jobs_liste("andreas.bender")
check(all(x["user"] == "andreas.bender" for x in _liste),
      "Die Liste zeigt nur eigene Auftraege")
check(all("ergebnis" not in x for x in _liste),
      "Die Liste traegt kein Ergebnis (Patch wird einzeln geholt)")


# ══════════════════════════════════════════════════════════════════════════
section("6. Zustandsdatei und Sandbox-Sperren")

import os  # noqa: E402
check(oct(os.stat(cs.STATE_PATH).st_mode)[-3:] == "600",
      "Zustandsdatei ist 0600 (Klartext-Schluessel)",
      oct(os.stat(cs.STATE_PATH).st_mode)[-3:])

# NEUE Datei als root: sie muss dem Eigentuemer des data-Verzeichnisses
# gehoeren, nicht root. Sonst kann der unprivilegierte Dienst sie nicht LESEN,
# und der Fehler sieht wie ein falscher Schluessel aus (HTTP 401) – genau so
# beim ersten Live-Test am 2026-08-21 passiert.
_sp = nur_code(QUELLE)
_sp_block = _sp[_sp.find("def _speichern"):_sp.find("def _reset_fuer_tests")]
check("st is None" in _sp_block and "STATE_PATH.parent.stat()" in _sp_block,
      "Neue Datei als root erbt den Eigentuemer des data-Verzeichnisses")
check(_sp_block.count("os.chown") == 2,
      "Beide Faelle (vorhanden / neu) werden bedient",
      f"{_sp_block.count('os.chown')}x chown")

# Geprueft werden die LISTEN des Moduls, nicht Textausschnitte der Datei: die
# erste Fassung schnitt "_APP_DENY_REL bis zum Wort PRIVATE_FILES" – und schlug
# fehl, sobald ein KOMMENTAR in diesem Block das Wort nennt. Ein Waechter, der
# seine eigene Begruendung liest, prueft nichts (im Projekt der zehnte Fall).
check("data/claude_subagent.json" in _sb._APP_DENY_REL, "... in _APP_DENY_REL")
check("data/claude_subagent.json" in _sb.PRIVATE_FILES_STRENG,
      "... in PRIVATE_FILES_STRENG (0600)")
check(_sb.PRIVATE_FILE_MODE_STRENG == 0o600, "... und die Stufe ist wirklich 0600")
check(bool(_sb.SHELL_SECRET_PATHS.search("cat data/claude_subagent.json")),
      "... in SHELL_SECRET_PATHS")

# Beschaedigte Datei darf den Dienst nicht kippen
cs.STATE_PATH.write_text("{kaputt", encoding="utf-8")
cs._reset_fuer_tests()
check(cs._laden() == {"schluessel": [], "jobs": []},
      "Beschaedigte Zustandsdatei -> leerer Zustand statt Absturz")


# ══════════════════════════════════════════════════════════════════════════
section("7. Herkunft des Klons")

check("depth" in CODE and "clone" in CODE, "Es wird flach geklont")
_url = cs._repo_url()
check(_url.startswith("https://"), "Klon-URL ist token-loses HTTPS", _url)
check("git@" not in _url, "SSH-Form wird auf HTTPS gedreht", _url)
check("Basis stimmt nicht" in QUELLE,
      "Abweichende Basis wird gemeldet, nicht stillschweigend uebergangen")


# ══════════════════════════════════════════════════════════════════════════
section("8. Laeuft gegen JEDE Installation – und sagt, wie")

_CLIENT = (ROOT / "deploy" / "claude_subagent" / "delegiere.py").read_text(encoding="utf-8")
_SKILLMD_P = ROOT / ".claude" / "skills" / "code-delegate" / "SKILL.md"
_SKILLMD = _SKILLMD_P.read_text(encoding="utf-8") if _SKILLMD_P.is_file() else ""
_MANIFEST = json.loads((ROOT / "skills" / "claude_subagent" / "skill.json")
                       .read_text(encoding="utf-8"))
_I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
_SEITE = (ROOT / "frontend" / "claude.html").read_text(encoding="utf-8")

# KEIN fest verdrahteter Host. Eine Vorgabe waere die Adresse genau einer
# Installation – bei der naechsten falsch, und der Fehler saehe wie ein
# Schluesselproblem aus (fremder Server -> 401).
check(re.search(r"\d{1,3}(\.\d{1,3}){3}", nur_code(_CLIENT)) is None,
      "Client enthaelt keine hart verdrahtete IP")
check("VORGABE_URL" not in _CLIENT, "Keine Vorgabe-URL mehr im Client")
# Der Client kann die Marke NICHT kennen (sie liegt auf dem Server), sucht die
# markenspezifischen Namen also nach dem MUSTER `<MARKE>_CSA_<X>` bzw.
# `~/.<marke>-csa-<x>`. Nur so kann in der Anleitung der Assistenten-Name stehen.
check('_CSA_" + end' in _CLIENT and '".*-csa-"' in _CLIENT,
      "Client sucht Kennungen nach dem Muster, nicht nach festem Namen")
check("_aus_umgebung_oder_datei" in _CLIENT
      and _CLIENT.count("_aus_umgebung_oder_datei") >= 3,
      "Schluessel UND Adresse gehen ueber denselben Weg")
check("SUBAGENT_KEY" not in _CLIENT and ".subagent-key" not in _CLIENT,
      "Keine neutralisierten Kennungen mehr im Client")

# ── Mehrere Zugaenge sind ein FEHLER, keine Auswahl (2026-08-30) ───────────
# GEMESSEN, nicht vermutet: bis dahin gewann der alphabetisch erste nicht leere
# Treffer. Wer neben `.jarvis-csa-key` einen `.nexerius-csa-key` hinterlegte,
# arbeitete weiter gegen die ALTE Installation – der neue Schluessel lag daneben
# und tat NICHTS, ohne eine einzige Meldung. Und weil Schluessel und Adresse
# getrennt ermittelt werden, waere auch die halbe Wahl moeglich (Schluessel des
# einen Servers an den anderen -> 401, sieht wie ein kaputter Schluessel aus).
#
# Geprueft wird die WIRKUNG: das Modul wird mit einem Wegwerf-HOME wirklich
# ausgefuehrt. Eine Quelltext-Suche nach "len(treffer) > 1" bliebe gruen, wenn
# jemand den Zweig spaeter ueberspringt.
_spec = importlib.util.spec_from_file_location(
    "_delegiere_probe", ROOT / "deploy" / "claude_subagent" / "delegiere.py")
_dlg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dlg)


def _mit_home(dateien: dict, umgebung: dict | None = None):
    """(schluessel, url, fehlercode) fuer ein Wegwerf-HOME. `fehler()` beendet
    den Prozess – deshalb SystemExit fangen, sonst braeche der ganze Testlauf
    ab und saehe wie ein bestandener aus (Register)."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, inhalt in dateien.items():
            (Path(tmp) / name).write_text(inhalt, encoding="utf-8")
        alt_home = os.environ.get("HOME")
        alt_env = {k: v for k, v in os.environ.items() if "_CSA_" in k.upper()}
        for k in alt_env:
            del os.environ[k]
        os.environ["HOME"] = tmp
        os.environ.update(umgebung or {})
        try:
            return _dlg.schluessel(), _dlg.basis_url(), 0
        except SystemExit as e:
            return None, None, e.code
        finally:
            for k in list(os.environ):
                if "_CSA_" in k.upper():
                    del os.environ[k]
            os.environ.update(alt_env)
            if alt_home is not None:
                os.environ["HOME"] = alt_home


_EIN = {".alpha-csa-key": "ALPHA-CSA-1.aaa.geheim",
        ".alpha-csa-url": "https://alpha.example"}
_ZWEI = dict(_EIN, **{".beta-csa-key": "BETA-CSA-1.bbb.geheim",
                      ".beta-csa-url": "https://beta.example"})

_k, _u, _rc = _mit_home(_EIN)
check(_k == "ALPHA-CSA-1.aaa.geheim" and _u == "https://alpha.example",
      "EIN hinterlegter Zugang wird gefunden (Gegenprobe)", f"{_k} / {_u}")

_k, _u, _rc = _mit_home(_ZWEI)
check(_rc == 2 and _k is None,
      "ZWEI hinterlegte Zugaenge brechen ab, statt still einen zu waehlen",
      f"rc={_rc}, gewaehlt={_k}")

_k, _u, _rc = _mit_home(_ZWEI, {"BETA_CSA_KEY": "BETA-CSA-1.bbb.geheim",
                                "BETA_CSA_URL": "https://beta.example"})
check(_rc == 0 and _u == "https://beta.example",
      "die Umgebungsvariable loest die Zwickmuehle auf", f"rc={_rc}, {_u}")

_k, _u, _rc = _mit_home(_EIN, {"X_CSA_KEY": "a", "Y_CSA_KEY": "b"})
check(_rc == 2, "auch zwei Umgebungsvariablen brechen ab", f"rc={_rc}")

# Ein Name, der nicht auf `-csa-<endung>` endet, wird nicht mehr gefunden - das
# ist der in der Meldung genannte Rueckweg, und er muss auch stimmen.
_k, _u, _rc = _mit_home({".alpha-csa-key": "ALPHA-CSA-1.aaa.geheim",
                         ".alpha-csa-url": "https://alpha.example",
                         ".beta-csa-key.inaktiv": "BETA-CSA-1.bbb.geheim",
                         ".beta-csa-url.inaktiv": "https://beta.example"})
check(_rc == 0 and _u == "https://alpha.example",
      "ein umbenannter Zugang stoert nicht mehr (der genannte Rueckweg wirkt)",
      f"rc={_rc}, {_u}")

# Die Meldung muss BEIDE Wege nennen - eine Absage ohne Ausweg ist nur Laerm.
_fn = nur_code(_CLIENT)
check("Mehrere Zugaenge" in _fn and "_CSA_" in _fn and "Benenne die nicht" in _fn,
      "die Absage nennt Umbenennen UND Umgebungsvariable als Ausweg")

# Die frueher behauptete DEV-Beschraenkung war FALSCH: der Arbeitsbereich wird
# frisch von origin/master geklont, ein sparse-checkout des Servers wirkt nur
# auf DESSEN Arbeitskopie. Sie darf nicht zurueckkommen.
for _name, _text in (("Client", _CLIENT), ("SKILL.md", _SKILLMD),
                     ("Manifest", json.dumps(_MANIFEST, ensure_ascii=False)),
                     ("Seite", _SEITE)):
    _t = _text.lower()
    check(not ("nur auf dev" in _t or "nur fuer dev" in _t or "nur für dev" in _t),
          f"{_name} behauptet keine DEV-Beschraenkung")

# Anleitung und Token-Rechnung muessen VORHANDEN und ZWEISPRACHIG sein.
for _k in ("csub.guide_head", "csub.guide_body"):
    check(_I18N.count("'" + _k + "':") == 2, f"{_k} in DE und EN vorhanden",
          f"{_I18N.count(chr(39) + _k + chr(39) + ':')}x")
check('data-i18n-html="csub.guide_body"' in _SEITE,
      "Anleitung haengt an data-i18n-html (nicht data-i18n)")
check('data-i18n="csub.guide_body"' not in _SEITE,
      "... denn data-i18n wuerde die Auszeichnung beim Sprachwechsel loeschen")

# Die Token-Aussage ist der Grund, warum es das Feature gibt – sie muss an
# BEIDEN Stellen stehen, an denen jemand nachsieht.
check("token_ersparnis" in _MANIFEST.get("help", {}),
      "Manifest nennt die Token-Ersparnis")
_te = _MANIFEST.get("help", {}).get("token_ersparnis", "")
check("800" in _te and ("4000" in _te or "4.000" in _te),
      "... mit den gemessenen Zahlen", _te[:60])
check("lohnt nicht" in _te or "lohnt sich" in _te,
      "... und mit der Einsatzregel (wann es sich NICHT lohnt)")
_gb = _I18N[_I18N.find("'csub.guide_body'"):]
_gb = _gb[:_gb.find("\n        'csub.jobs_head'")]
check("800" in _gb and "Faktor" in _gb, "Anleitung nennt Ersparnis und Faktor")
check("{marke_slug}-csa-url" in _gb and "{marke_slug}-csa-key" in _gb,
      "Anleitung nennt beide Zugangsangaben MIT Marken-Platzhalter")

section("9. SKILL.md ist HERUNTERLADBAR, kein Verweis")

# "Lege die Datei selbst an" ist keine Anleitung – und `.claude/` ist
# gitignored, die Vorlage existiert auf einer Installation gar nicht. Sie muss
# also im Repo liegen UND ueber einen Endpunkt fertig ausgeliefert werden.
_TPL = ROOT / "deploy" / "claude_subagent" / "SKILL.md"
check(_TPL.is_file(), "Vorlage liegt versioniert im Repo (deploy/claude_subagent/SKILL.md)")
_tpl = _TPL.read_text(encoding="utf-8") if _TPL.is_file() else ""
check("{MARKE}_CSA_KEY" in _tpl and "{marke_slug}-csa-key" in _tpl,
      "Vorlage traegt die Marken-Platzhalter")
check("code-delegate" in _tpl, "Vorlage nennt den Skill-Ordner")

_MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
check('"/claude/skill.md"' in _MAIN, "Endpunkt /claude/skill.md vorhanden")
# Die AUSLIEFERUNG steckt seit 2026-08-23 in `_claudesub_beiblatt` (zwei
# Downloads, eine Ersetzung). Geprueft wird deshalb die Kette Endpunkt →
# Helfer, nicht der Rumpf des Endpunkts: sonst schlaegt der Test bei jedem
# Herausziehen einer Funktion an, ohne dass etwas kaputt ist.
_ep = _MAIN[_MAIN.find('@app.get("/claude/skill.md")'):]
_ep = _ep[:_ep.find("@app.get(\"/claude/claude-md-diaet.md\")")]
_helper = _MAIN[_MAIN.find("def _claudesub_beiblatt("):]
_helper = _helper[:_helper.find('@app.get("/claude/skill.md")')]
check("_claudesub_beiblatt(request" in _ep,
      "... liefert ueber den gemeinsamen Helfer aus")
_ep = _ep + _helper          # ab hier gilt: Endpunkt PLUS sein Helfer
check("attachment" in _ep and "SKILL.md" in _ep,
      "... liefert als Download (Content-Disposition attachment)")
check("marken_slug" in _ep and "marken_anzeige" in _ep,
      "... setzt beide Marken-Formen ein")
check("PlainTextResponse" not in _ep,
      "... benutzt keine nicht importierte Response-Klasse")

# JEDER Grossbuchstaben-Bezeichner im Endpunkt muss in main.py auch existieren.
# Ein Quelltext-Test, der den Endpunkt nur LIEST, faengt genau das nicht: die
# erste Fassung benutzte `PROJECT_ROOT`, das es in main.py gar nicht gibt –
# NameError beim ersten Abruf, gefunden erst live (HTTP 500).
import re as _re2
# Kommentare UND Zeichenketten entfernen: sonst treffen deutsche Woerter
# ("DIESER", "NICHT") und Platzhalter ("{MARKE}") die Suche. Vierter Fall
# dieser Art im Projekt – ein Waechter, der seine eigene Begruendung liest.
_ep_code = _re2.sub(r'"""(?:.|\n)*?"""', "", _ep)
_ep_code = "\n".join(z.split("#")[0] for z in _ep_code.splitlines())
_ep_code = _re2.sub(r'"[^"]*"|\'[^\']*\'', '""', _ep_code)
_bez = set(_re2.findall(r"\b([A-Z][A-Z0-9_]{3,})\b", _ep_code))
_fehlend = [b for b in sorted(_bez)
            if not _re2.search(r"(?m)^\s*" + b + r"\s*[:=]|^from .* import .*\b" + b + r"\b|"
                               r"^import .*\b" + b + r"\b", _MAIN)]
check(not _fehlend, "Alle Konstanten des Endpunkts sind in main.py definiert",
      ", ".join(_fehlend))

# Die Ersetzung wirklich AUSFUEHREN, nicht nur den Code lesen.
_marke = "NEXI"
_fertig = (_tpl.replace("{MARKE}", _marke)
               .replace("{marke_slug}", _marke.lower())
               .replace("{marke}", "Nexi"))
check("{MARKE}" not in _fertig and "{marke_slug}" not in _fertig
      and "{marke}" not in _fertig,
      "Nach der Ersetzung bleibt KEIN Platzhalter stehen")
check("NEXI_CSA_KEY" in _fertig and "~/.nexi-csa-key" in _fertig,
      "Die fertige Datei nennt die Kennungen dieser Installation")

# Die ADRESSE gehoert genauso hinein. Ein Beispiel wie
# "https://dein-server.firma.de" ist Arbeit, die der Benutzer heraussuchen
# muss – der Server kennt seine Adresse (vom Nutzer gemeldet).
check("{adresse}" in _tpl, "Vorlage hat einen Adress-Platzhalter")
_mit = _fertig.replace("{adresse}", "https://jarvis.firma.test")
check("https://jarvis.firma.test" in _mit and "{adresse}" not in _mit,
      "Adresse wird eingesetzt")
check("dein-server" not in _tpl and "your-server" not in _tpl
      and "firma.de" not in _tpl,
      "Keine erfundene Beispiel-Adresse mehr in der Vorlage")
check("csa-url" in _tpl and "printf" in _tpl,
      "Vorlage enthaelt den fertigen Befehl zum Ablegen")

check("basis_url" in _helper, "Auslieferung leitet die Adresse aus der Anfrage ab")
check("request: Request" in _helper.split("\n")[0],
      "... und nimmt dafuer das Request-Objekt")

# Anleitung im Bereich: derselbe Platzhalter, gefuellt von branding.js.
_BR = (ROOT / "frontend" / "js" / "branding.js").read_text(encoding="utf-8")
check("{adresse}" in _BR and "location.origin" in _BR,
      "branding.js fuellt {adresse} mit der echten Adresse")
check("dein-server" not in _I18N and "firma.de" not in _I18N.split("csub.guide_body")[1][:4000],
      "Keine erfundene Beispiel-Adresse mehr in der Anleitung")

# Und die Anleitung darf NICHT mehr auffordern, sie selbst anzulegen.
_I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
check("/claude/skill.md" in _I18N, "Anleitung verlinkt den Download")
check("Vorlage im Repo unter" not in _I18N,
      "Anleitung fordert NICHT mehr zum Selbstanlegen auf")


# ════════════════════════════════════════════════════════════════════════════
section("Einstellbare Werte – Profil, Denktiefe, Grenzen")
# ════════════════════════════════════════════════════════════════════════════
# VORBEFUND, der diesen Abschnitt ausgeloest hat: das Manifest versprach drei
# Schalter (gleichzeitig / laufzeit_s / arbeit_ttl_min), der Reiter zeigte sie,
# gespeichert wurden sie – und GELESEN hat sie niemand. Die Werte standen als
# Modulkonstanten im Code. Dieselbe Fehlerklasse wie `prompt_tool_calling`.
# Deshalb prueft dieser Abschnitt die WIRKUNG, nicht die Anwesenheit der Felder.

_CS_SRC = nur_code((ROOT / "backend" / "claude_subagent.py").read_text(encoding="utf-8"))

# Die Konstanten duerfen NICHT zurueckkommen – sonst waere die Einstellung
# wieder wirkungslos, ohne dass irgendetwas rot wird.
for _tot in ("MAX_GLEICHZEITIG", "MAX_LAUFZEIT_S", "ARBEIT_TTL_MIN "):
    check(_tot not in _CS_SRC,
          f"Keine Modulkonstante {_tot.strip()} mehr (waere wieder unlesbar)")
for _fn in ("gleichzeitig", "laufzeit_s", "arbeit_ttl_min", "profil_id",
            "reasoning_effort", "wirksames_profil", "temperatur_hinweis"):
    check(callable(getattr(cs, _fn, None)), f"cs.{_fn}() existiert")

# Manifest und Code muessen dieselben Felder kennen. Ein Feld im Formular, das
# der Code nicht liest, ist genau der Vorbefund von oben.
_MAN = json.loads((ROOT / "skills" / "claude_subagent" / "skill.json")
                  .read_text(encoding="utf-8"))
_SCHEMA = _MAN.get("config_schema", {})
for _feld in ("gleichzeitig", "laufzeit_s", "arbeit_ttl_min", "profile_id",
              "reasoning_effort"):
    check(_feld in _SCHEMA, f"Manifest kennt '{_feld}'")
    check(f'"{_feld}"' in _CS_SRC, f"... und der Code LIEST '{_feld}'")
_EFF = _SCHEMA.get("reasoning_effort", {})
check(isinstance(_EFF.get("enum"), list),
      "Denktiefe-Feld nutzt 'enum' (skillcfg.js liest NICHT 'options')")
check("options" not in _EFF, "... und kein totes 'options' daneben")
check(set(_EFF.get("enum") or []) == set(cs.EFFORT_STUFEN),
      "Manifest-Stufen und cs.EFFORT_STUFEN sind dieselben")
_SKC = (ROOT / "frontend" / "js" / "skillcfg.js").read_text(encoding="utf-8")
check("f.enum" in _SKC and "f.options" not in _SKC,
      "Gegenprobe am Renderer: er liest wirklich 'enum'")

# Wirkung: Config setzen -> Funktion liefert den Wert, ausserhalb der Grenzen
# wird gekappt, Muell faellt auf die Vorgabe zurueck.
_echte_cfg = cs.skill_config
def _cfg(d):
    cs.skill_config = lambda: d
try:
    _cfg({})
    check(cs.gleichzeitig() == 2 and cs.laufzeit_s() == 600
          and cs.arbeit_ttl_min() == 60, "Leere Config -> Vorgaben")
    _cfg({"gleichzeitig": 4, "laufzeit_s": 120, "arbeit_ttl_min": 15})
    check(cs.gleichzeitig() == 4 and cs.laufzeit_s() == 120
          and cs.arbeit_ttl_min() == 15, "Gesetzte Werte wirken WIRKLICH")
    _cfg({"gleichzeitig": 500, "laufzeit_s": 99999, "arbeit_ttl_min": 0})
    check(cs.gleichzeitig() == 4, "gleichzeitig wird nach oben gekappt (500 -> 4)")
    check(cs.laufzeit_s() == 1800, "laufzeit_s wird gekappt")
    check(cs.arbeit_ttl_min() == 5, "arbeit_ttl_min wird nach unten gekappt")
    _cfg({"gleichzeitig": "zwei"})
    check(cs.gleichzeitig() == 2, "Muell -> Vorgabe statt Absturz")

    # Denktiefe: nur die fuenf Stufen, alles andere ist "keine Vorgabe".
    _cfg({"reasoning_effort": "low"})
    check(cs.reasoning_effort() == "low", "Gueltige Denktiefe wird uebernommen")
    _cfg({"reasoning_effort": "  HIGH "})
    check(cs.reasoning_effort() == "high", "... normalisiert (Rand, Grossschreibung)")
    _cfg({"reasoning_effort": "sehr_viel"})
    check(cs.reasoning_effort() == "",
          "Unbekannte Stufe -> leer (kein Provider-400 aus einem Tippfehler)")
    _cfg({"profile_id": "  abc-123  "})
    check(cs.profil_id() == "abc-123", "Profil-Kennung wird getrimmt")
    _cfg({"profile_id": "x" * 500})
    check(len(cs.profil_id()) == 64, "Profil-Kennung ist gedeckelt")
finally:
    cs.skill_config = _echte_cfg

# Verdrahtung im Lauf: dieselben Attribute wie bei den Rollen-Agenten.
_lauf = _CS_SRC[_CS_SRC.find("async def job_ausfuehren"):]
check("_role_profile_id = profil_id_aufgeloest()" in _lauf,
      "Der Lauf setzt _role_profile_id auf die AUFGELOESTE Kennung "
      "(ein Name liefe dort ins Leere)")
check("reasoning_effort=" in _lauf,
      "Der Lauf reicht die Denktiefe an run_task_headless durch")
check("reasoning_effort() or None" in _lauf,
      "Leere Denktiefe wird zu None (= keine Vorgabe), nicht zu ''")
check("timeout=grenze_s" in _lauf,
      "Das Zeitlimit kommt aus der Config, nicht aus einer Konstante")

# ── Der Hinweis zur temperature ────────────────────────────────────────────
# GEMESSEN am 2026-08-22 auf DEV gegen das aktive Profil (Qwen3.6-35B auf
# vLLM 0.27.1, je 12 Laeufe): ohne das Feld 12 verschiedene Antworten, mit 0.2
# nur 2 – die wirksame Vorgabe des Servers ist also hoch. Die WERKZEUG-Aufrufe
# waren in BEIDEN Faellen 12/12 exakt richtig. Der Hinweis darf deshalb kein
# Versagen behaupten, das nicht gemessen wurde.
class _FakeCfg:
    def __init__(self, profile, aktiv):
        self.profiles = profile
        self._aktiv = aktiv
    @property
    def active_profile(self):
        return self._aktiv

import types  # noqa: E402
def _mit_profilen(profile, aktiv):
    """Schiebt ein Attrappen-config-Modul unter backend.config."""
    m = types.ModuleType("backend.config")
    m.config = _FakeCfg(profile, aktiv)
    sys.modules["backend.config"] = m

_echt_cfgmod = sys.modules.get("backend.config")
try:
    _p_auto = {"id": "p1", "name": "Qwen lokal", "temperature": "auto"}
    _p_fest = {"id": "p2", "name": "Qwen fest", "temperature": "0.2"}

    cs.skill_config = lambda: {}
    _mit_profilen([_p_auto, _p_fest], _p_auto)
    _w = cs.wirksames_profil()
    # DIESE Pruefung ist der Grund fuer den ganzen Block: wirksames_profil()
    # hat ein breites except. Ein Tippfehler an den config-Zugriffen (etwa
    # get_profiles() statt .profiles, oder active_profile als Methode) wuerde
    # verschluckt – der Hinweis erschiene dann einfach NIE.
    check(_w["gefunden"] and _w["name"] == "Qwen lokal",
          "wirksames_profil() findet das global aktive Profil WIRKLICH")
    check(not _w["gewaehlt"], "... und meldet es als nicht festgelegt")
    check("auto" in cs.temperatur_hinweis(),
          "Hinweis erscheint, wenn das wirksame Profil auf auto steht")
    check("0.2" in cs.temperatur_hinweis(),
          "... und nennt den konkreten Ausweg")
    _h = cs.temperatur_hinweis().lower()
    check("werkzeug" not in _h and "tool" not in _h,
          "Der Hinweis behauptet KEIN Werkzeug-Versagen (nicht gemessen)")

    _mit_profilen([_p_auto, _p_fest], _p_fest)
    check(cs.temperatur_hinweis() == "",
          "Feste Zahl im Profil -> kein Hinweis")

    cs.skill_config = lambda: {"profile_id": "p2"}
    _mit_profilen([_p_auto, _p_fest], _p_auto)
    _w = cs.wirksames_profil()
    check(_w["name"] == "Qwen fest" and _w["gewaehlt"],
          "Das Feld im Reiter schlaegt das global aktive Profil")

    check(cs.profil_id_aufgeloest() == "p2",
          "profil_id_aufgeloest() liefert die KENNUNG (nicht den Rohwert)")

    # NAME statt Kennung: der Reiter rendert hier ein Textfeld, und eine UUID
    # abzutippen ist eine Zumutung.
    cs.skill_config = lambda: {"profile_id": "Qwen fest"}
    check(cs.wirksames_profil()["id"] == "p2",
          "Profil laesst sich ueber den NAMEN waehlen")
    check(cs.profil_id_aufgeloest() == "p2",
          "... und daraus wird die Kennung fuer _role_profile_id")

    cs.skill_config = lambda: {"profile_id": "gibtsnicht"}
    check("gibt es nicht mehr" in cs.temperatur_hinweis(),
          "Verwaistes Profil wird gemeldet (Lauf laeuft sonst still anders)")
    check(cs.profil_id_aufgeloest() == "",
          "Verwaistes Profil -> leer (Lauf faellt aufs aktive zurueck)")

    cs.skill_config = lambda: {}
    check(cs.profil_id_aufgeloest() == "",
          "Ohne Wahl wird KEIN Profil gepinnt")

    cs.skill_config = lambda: {}
    _mit_profilen([], None)
    check(cs.temperatur_hinweis() == "",
          "Ohne Profil wird nichts behauptet")
finally:
    cs.skill_config = _echte_cfg
    if _echt_cfgmod is not None:
        sys.modules["backend.config"] = _echt_cfgmod
    else:
        sys.modules.pop("backend.config", None)

# Endpunkt und Oberflaeche
_ep = _MAIN[_MAIN.find('@app.get("/api/claude/status")'):]
_ep = _ep[:_ep.find("@app.post")]
for _f in ("wirksames_profil", "temperatur_hinweis", "reasoning_effort"):
    check(_f in _ep, f"/api/claude/status liefert {_f}")
check("_cs.gleichzeitig()" in _ep and "_cs.laufzeit_s()" in _ep,
      "... und meldet die WIRKSAMEN Grenzen, nicht die Vorgaben")

_PORTAL = (ROOT / "frontend" / "js" / "claude_portal.js").read_text(encoding="utf-8")
check("zeichneModell" in _PORTAL, "Oberflaeche zeichnet den Modell-Kasten")
check(_PORTAL.count("zeichneModell();") == 1,
      "... und ruft ihn genau einmal auf")
check("modell_hinweis" in _PORTAL, "... inklusive Hinweis")
check("if (!m || !m.name) { box.hidden = true; return; }" in _PORTAL,
      "Ohne Datenstand wird nichts behauptet")
_HTML = (ROOT / "frontend" / "claude.html").read_text(encoding="utf-8")
check('id="cs-modell"' in _HTML, "Markup fuer den Modell-Kasten vorhanden")
check(".cs-modell {" in _HTML and "var(--bg-primary)" in _HTML,
      "Kasten hat eine DECKENDE Flaeche")
for _k in ("csub.model_line", "csub.model_fixed", "csub.model_global",
           "csub.model_effort"):
    check(_I18N.count(f"'{_k}'") == 2, f"{_k} in DE und EN")


section("Beiblatt: CLAUDE.md-Diaet erreicht den Anwender")

# WARUM EINE EIGENE DATEI: die SKILL.md entscheidet, WANN eine Aufgabe abgegeben
# wird. Ein zweites Thema in ihrem Rumpf verwaessert genau diesen Zuschnitt (auf
# Anweisung des Nutzers am 2026-08-23 so gebaut, nachdem der Abschnitt zuerst
# mitten in der Skill-Datei stand).
_DIAET = ROOT / "deploy" / "claude_subagent" / "claude-md-diaet.md"
check(_DIAET.is_file(), "Beiblatt liegt versioniert im Repo")
_diaet = _DIAET.read_text(encoding="utf-8") if _DIAET.is_file() else ""

# ... und der Rumpf der SKILL.md bleibt frei davon: nur ein Zeiger.
check(_tpl.count("claude-md-diaet") == 1,
      "SKILL.md verweist auf das Beiblatt - genau einmal",
      f"gefunden: {_tpl.count('claude-md-diaet')}")
check("Phase 0" not in _tpl and "Behalte-Test" not in _tpl,
      "... und traegt den Auftrag NICHT selbst")

# Der Anwender bekommt nur, was ein Endpunkt ausliefert.
check('"/claude/claude-md-diaet.md"' in _MAIN, "Endpunkt vorhanden")
_epd = _MAIN[_MAIN.find('@app.get("/claude/claude-md-diaet.md")'):]
_epd = _epd[:_epd.find('@app.get("/api/claude/status")')]
check("_claudesub_beiblatt(request" in _epd,
      "... nutzt denselben Helfer wie /claude/skill.md (keine zweite Ersetzung)")
_hlp = _MAIN[_MAIN.find("def _claudesub_beiblatt("):]
_hlp = _hlp[:_hlp.find('@app.get("/claude/skill.md")')]
check("attachment" in _hlp and "marken_slug" in _hlp and "marken_anzeige" in _hlp,
      "... Helfer liefert als Download und setzt beide Marken-Formen")
check("{name}" in _hlp or 'filename="{name}"' in _hlp,
      "... Dateiname kommt aus dem Parameter, nicht fest verdrahtet")

# Ohne Link in der Anleitung findet den Download niemand.
check(_I18N.count("/claude/claude-md-diaet.md") == 2,
      "Anleitung verlinkt das Beiblatt in DE UND EN",
      f"gefunden: {_I18N.count('/claude/claude-md-diaet.md')}")

# Inhaltliche Zusagen des Beiblatts.
check("{marke}" in _diaet, "Beiblatt ist markenneutral (Platzhalter statt Name)")
check("NICHT delegieren" in _diaet,
      "... sagt ausdruecklich, dass es NICHT delegiert wird")
check("Phase 0" in _diaet and "Phase 1" in _diaet and "Phase 2" in _diaet,
      "... arbeitet in drei Phasen (kein Ein-Schuss-Umschreiben)")
check("<BUDGET>" in _diaet and "<X>" in _diaet,
      "... nennt die anzupassenden Platzhalter")
check("settings*.json" in _diaet and "nicht** im Modellkontext" in _diaet,
      "... berichtigt den Scope (settings.json kostet keine Token)")
for _wort in ("Niemals streichen", "Behalte-Test", "git diff"):
    check(_wort in _diaet, f"... enthaelt '{_wort}'")
# Keine Zahlen aus UNSEREM Repo in einer Datei, die an fremde Projekte geht -
# sie waeren dort schlicht falsch.
check("605." not in _diaet and "65.986" not in _diaet,
      "... nennt keine Messwerte dieses Repos als die des Anwenders")


print("\n" + "=" * 62)
print(f"  {_ok} OK, {_fail} FAIL")
print("=" * 62)
sys.exit(1 if _fail else 0)

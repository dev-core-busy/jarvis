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
4. **Der Schluessel liegt nur als Hash auf Platte** und wird genau einmal
   ausgegeben. Ein zweiter ``schluessel_erzeugen`` entwertet den alten – das ist
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
import json
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
check(_schluessel.startswith(cs.SCHLUESSEL_PREFIX), "Schluessel traegt das Praefix")
check(len(_schluessel) > 50, "Schluessel ist lang genug", f"{len(_schluessel)}")
check(cs.benutzer_zu_schluessel(_schluessel) == "andreas.bender",
      "Schluessel loest auf den normierten Benutzer auf",
      repr(cs.benutzer_zu_schluessel(_schluessel)))

# Normierung: dieselbe Person, andere Tippform -> derselbe Schluessel-Satz
check(cs.schluessel_info("ANDREAS.BENDER@nexus.int") is not None,
      "Normierung: UPN-Form findet denselben Eintrag")
check(cs.schluessel_info("nexus\\Andreas.Bender") is not None,
      "Normierung: Domaenen-Praefix findet denselben Eintrag")

# Das Geheimnis darf NICHT auf Platte liegen
_roh = cs.STATE_PATH.read_text(encoding="utf-8")
_geheimnis = _schluessel.split(".", 2)[-1]
check(_geheimnis not in _roh, "Geheimnis steht NICHT im Klartext auf Platte")
check('"hash"' in _roh, "Stattdessen liegt ein Hash in der Datei")
check(cs.schluessel_info("andreas.bender").get("letzte4") == _geheimnis[-4:],
      "Nur die letzten 4 Zeichen sind wieder abrufbar")
check("schluessel" not in json.dumps(cs.schluessel_info("andreas.bender")),
      "schluessel_info gibt das Geheimnis nicht heraus")

# Falsche/kaputte Schluessel
check(cs.benutzer_zu_schluessel(cs.SCHLUESSEL_PREFIX + "abc.falsch") is None,
      "Falsches Geheimnis -> None")
check(cs.benutzer_zu_schluessel("voellig-anderes-format") is None,
      "Fremdes Format -> None")
check(cs.benutzer_zu_schluessel(cs.SCHLUESSEL_PREFIX + "nurkennung") is None,
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
check(oct(os.stat(cs.STATE_PATH).st_mode)[-3:] == "640",
      "Zustandsdatei ist 0640", oct(os.stat(cs.STATE_PATH).st_mode)[-3:])

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

_sbx = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
check("data/claude_subagent.json" in _sbx, "Datei steht in sandbox.py")
_deny = _sbx[_sbx.find("_APP_DENY_REL"):_sbx.find("PRIVATE_FILES")]
check("data/claude_subagent.json" in _deny, "... in _APP_DENY_REL")
_priv = _sbx[_sbx.find("PRIVATE_FILES = ("):_sbx.find("PRIVATE_FILE_MODE")]
check("data/claude_subagent.json" in _priv, "... in PRIVATE_FILES")
_shell = _sbx[_sbx.find("SHELL_SECRET_PATHS"):]
check("claude_subagent" in _shell[:2000], "... in SHELL_SECRET_PATHS")

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
check("SUBAGENT_URL" in _CLIENT and ".subagent-url" in _CLIENT,
      "Adresse kommt aus Umgebung ODER Datei")
check("SUBAGENT_KEY" in _CLIENT and ".subagent-key" in _CLIENT,
      "Schluessel kommt aus Umgebung ODER Datei")

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
check(".subagent-url" in _gb and ".subagent-key" in _gb,
      "Anleitung nennt beide Zugangsangaben")

print("\n" + "=" * 62)
print(f"  {_ok} OK, {_fail} FAIL")
print("=" * 62)
sys.exit(1 if _fail else 0)

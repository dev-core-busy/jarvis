#!/usr/bin/env python3
"""Outlook-Add-in Bereitstellung: Netzwerkordner statt Download.

**Was hier geprueft wird, und warum als EIGENSCHAFT und nicht als Vorkommen:**

* ``addin.ordner_pfad()`` laeuft WIRKLICH gegen eine gestellte Skill-Config –
  eine Quelltext-Suche saehe nicht, dass ein Zeilenumbruch die einzeilige
  Anzeige zerlegt oder ein Fehler beim Lesen zu einem 500er fuehrt.
* Der Statusweg (``_addin_ordner_pfad_safe``) wird per ``ast`` geschnitten und
  AUSGEFUEHRT – die Zusage lautet "ein Fehler beim Nebenfeld kippt die
  Hauptauskunft nicht", und das kann nur ein Lauf belegen.
* Der Endpunkt liefert das Feld ueberhaupt (Drift-Schranke: der Client liest
  ``addin_ordner``, das Backend muss genau diesen Namen senden).
* Der Feldname steht an DREI Orten (Backend, ``skill.json``, ``email.js``) –
  laufen sie auseinander, speichert der Admin in ein Feld, das niemand liest,
  **ohne Fehlermeldung**.

Laeuft OHNE fastapi. ``backend.config`` wird ausdruecklich NICHT echt geladen –
der echte Import migriert Profile und schreibt die Live-``settings.json``
zurueck. Der Test bricht mit **Exit 2** ab, wenn es doch geladen ist: "konnte
nicht laufen" muss von "bestanden" unterscheidbar bleiben.

    python3 tests/test_addin_ordner.py
"""

from __future__ import annotations

import ast
import io
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Sandkasten: config stubben, BEVOR etwas importiert wird ───────────────
if "backend.config" in sys.modules and not isinstance(
        sys.modules["backend.config"], types.ModuleType):
    print("ABBRUCH: backend.config ist bereits echt geladen.")
    sys.exit(2)

_cfg = types.ModuleType("backend.config")


class _C:
    def __init__(self):
        self.skill_states = {}

    def get_setting(self, k, d=None):
        return d

    def get_skill_states(self):
        return self.skill_states


_cfg.config = _C()
sys.modules["backend.config"] = _cfg

res = []


def check(name, cond, detail=""):
    """ACHTUNG: Reihenfolge ist (Beschreibung, Bedingung).

    In ``test_jira_vorlagen.py`` waren alle 57 Aufrufe vertauscht – eine
    nicht-leere Zeichenkette ist wahr, der Lauf meldete "57 OK, 0 FAIL", **ohne
    eine einzige Bedingung ausgewertet zu haben**. Deshalb der Abbruch hier.
    """
    if isinstance(name, bool) or isinstance(cond, str):
        print("ABBRUCH: check(name, cond) vertauscht aufgerufen.")
        sys.exit(2)
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def sicher(fn, *a, **k):
    """Nie ungeprueft dereferenzieren: ein Wurf in einer Pruefung bricht den
    Lauf ab, und ein abgebrochener Lauf ist von "nicht gelaufen" nicht zu
    unterscheiden (Register)."""
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return "WURF: %r" % (e,)


def ohne_kommentare(quelle: str) -> str:
    """Kommentare UND Docstrings entfernen.

    Ein Waechter, der seine eigene Begruendung liest, prueft nichts – im
    Projekt dreizehnmal bezahlt. Die Begruendungen dieses Projekts stehen in
    DOCSTRINGS, ``tokenize`` entfernt nur ``#``-Kommentare.
    """
    import tokenize
    aus = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.line.strip().startswith(
                    ('"""', "'''", 'r"""', "r'''")):
                continue
            aus.append(tok.string if tok.type != tokenize.NL else "\n")
    except Exception:  # noqa: BLE001
        return quelle
    return "\n".join(aus)


print("\n\033[1m1. addin.ordner_pfad() – ausgefuehrt\033[0m")

from backend import addin  # noqa: E402

MAIL = types.ModuleType("backend.mail_accounts")
_mail_cfg = {}
_mail_wirft = False


def _skill_config():
    if _mail_wirft:
        raise RuntimeError("Konfiguration nicht lesbar")
    return dict(_mail_cfg)


MAIL.skill_config = _skill_config
sys.modules["backend.mail_accounts"] = MAIL


def pfad_mit(wert):
    global _mail_cfg
    _mail_cfg = {} if wert is None else {"addin_ordner_pfad": wert}
    return sicher(addin.ordner_pfad)


check("kein Feld -> leer (die Kachel bietet den Download an)",
      pfad_mit(None) == "", pfad_mit(None))
check("leerer Wert -> leer", pfad_mit("") == "", pfad_mit(""))
check("UNC-Pfad kommt unveraendert zurueck",
      pfad_mit(r"\\srv\freigabe\addins") == r"\\srv\freigabe\addins",
      pfad_mit(r"\\srv\freigabe\addins"))
check("Laufwerksbuchstabe bleibt gueltig (keine Formpruefung)",
      pfad_mit(r"X:\office\addins") == r"X:\office\addins")
check("SharePoint-Adresse bleibt gueltig",
      pfad_mit("https://firma.sharepoint.com/addins")
      == "https://firma.sharepoint.com/addins")
check("Leerzeichen im Freigabenamen bleiben (Windows-Normalfall)",
      pfad_mit(r"\\srv\Meine Freigabe\add ins") == r"\\srv\Meine Freigabe\add ins")
check("aussen getrimmt", pfad_mit("   \\\\srv\\f   ") == r"\\srv\f",
      pfad_mit("   \\\\srv\\f   "))
# Ein Zeilenumbruch zerlegte die einzeilige Anzeige - und in einem
# Kopiervorgang haette er dort nichts zu suchen.
check("Zeilenumbruch wird entfernt",
      "\n" not in pfad_mit("\\\\srv\\a\nzweite Zeile")
      and "\r" not in pfad_mit("\\\\srv\\a\r\nb"),
      repr(pfad_mit("\\\\srv\\a\nzweite Zeile")))
check("Steuerzeichen werden entfernt",
      "\x07" not in pfad_mit("\\\\srv\\a\x07b"), repr(pfad_mit("\\\\srv\\a\x07b")))
check("Deckel greift (%d Zeichen)" % addin.ORDNER_PFAD_MAX,
      len(pfad_mit("\\\\srv\\" + "x" * 4000)) == addin.ORDNER_PFAD_MAX,
      len(pfad_mit("\\\\srv\\" + "x" * 4000)))
# FAIL-OPEN in die harmlose Richtung: eine unlesbare Konfiguration darf keinen
# Pfad behaupten - ein falsch behaupteter schickt den Benutzer in einen leeren
# Ordner, ein fehlender kostet nur einen Download.
_mail_wirft = True
check("unlesbare Konfiguration -> leer, kein Wurf", pfad_mit("\\\\srv\\f") == "",
      pfad_mit("\\\\srv\\f"))
_mail_wirft = False
check("ordner_pfad ist eine FUNKTION, kein Modulwert (ohne Dienstneustart)",
      callable(getattr(addin, "ordner_pfad", None)))


print("\n\033[1m2. Der Statusweg kippt die Hauptauskunft nicht\033[0m")

MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_baum = ast.parse(MAIN)
_safe = None
for k in ast.walk(_baum):
    if isinstance(k, ast.FunctionDef) and k.name == "_addin_ordner_pfad_safe":
        _safe = k
        break
if _safe is None:
    print("ABBRUCH: _addin_ordner_pfad_safe nicht gefunden.")
    sys.exit(2)

# WIRKLICH ausfuehren: die Zusage ist "jeder Fehler ergibt leer, nichts wirft".
_ns = {}
exec(compile(ast.Module(body=[_safe], type_ignores=[]), "<safe>", "exec"), _ns)
_pfad_safe = _ns["_addin_ordner_pfad_safe"]

_mail_cfg = {"addin_ordner_pfad": r"\\srv\ok"}
check("liefert den Pfad durch", sicher(_pfad_safe) == r"\\srv\ok", sicher(_pfad_safe))
_mail_wirft = True
check("wirft NICHT, wenn die Quelle wirft", sicher(_pfad_safe) == "", sicher(_pfad_safe))
_mail_wirft = False

# Ein eigener try-Block, getrennt von der uebrigen Statusauskunft: beim
# Zahnrad-Badge verschluckte ein GEMEINSAMES except einen NameError im
# Listenaufbau und der Zaehler fiel still auf 0.
check("hat einen eigenen try/except",
      any(isinstance(n, ast.Try) for n in ast.walk(_safe)))
_safe_src = ohne_kommentare(ast.get_source_segment(MAIN, _safe) or "")
check("meldet den Grund, statt still zu schweigen",
      "print" in _safe_src, _safe_src[:120])


print("\n\033[1m3. Der Endpunkt liefert das Feld (Drift-Schranke)\033[0m")

_status = None
for k in ast.walk(_baum):
    if isinstance(k, ast.AsyncFunctionDef) and k.name == "email_status":
        _status = k
        break
check("email_status gefunden", _status is not None)
_st_src = ohne_kommentare(ast.get_source_segment(MAIN, _status) or "") if _status else ""
# Der Client liest genau diesen Namen. Ein anderer hier heisst: die Kachel
# bietet auf ewig den Download an, ohne dass etwas auffaellt.
check("sendet den Schluessel 'addin_ordner'", '"addin_ordner"' in _st_src, _st_src[:200])
check("benutzt den geschuetzten Helfer, nicht addin.ordner_pfad direkt",
      "_addin_ordner_pfad_safe" in _st_src and "addin.ordner_pfad" not in _st_src)
# Der Endpunkt liegt schon hinter der Freigabe - ein UNC-Pfad nennt Servernamen
# und Freigabe des Hauses und gehoert nicht an einen offenen Endpunkt.
check("email_status haengt an require_email_access",
      "require_email_access" in _st_src, _st_src[:200])
# Kein zusaetzlicher Endpunkt fuer ein Feld: die Oberflaeche ruft
# /api/email/status ohnehin.
check("es gibt keinen eigenen Endpunkt fuer den Pfad",
      "/api/email/addin" not in MAIN)


print("\n\033[1m4. Der Feldname steht an drei Orten – und sie stimmen ueberein\033[0m")

FELD = "addin_ordner_pfad"
SKILL = json.loads((ROOT / "skills" / "email" / "skill.json").read_text(encoding="utf-8"))
ADMIN_JS = (ROOT / "frontend" / "js" / "email.js").read_text(encoding="utf-8")
ADDIN_PY = (ROOT / "backend" / "addin.py").read_text(encoding="utf-8")

check("skill.json kennt das Feld", FELD in SKILL.get("config_schema", {}),
      sorted(SKILL.get("config_schema", {})))
check("skill.json: Vorgabe ist LEER (nichts aendert sich beim Ausrollen)",
      SKILL["config_schema"].get(FELD, {}).get("default") == ""
      if FELD in SKILL.get("config_schema", {}) else False)
check("addin.py liest genau dieses Feld", ('"%s"' % FELD) in ADDIN_PY)
check("email.js liest und schreibt genau dieses Feld",
      ADMIN_JS.count(FELD) >= 2, ADMIN_JS.count(FELD))
# Der Reiter darf beim Speichern des Pfads NICHT den ganzen Formularstand
# senden: `update_skill_config` merged, ein leeres Kennwortfeld waere sonst ein
# geloeschter Zugang (Register: "Zwei Knoepfe im selben Reiter").
_m = re.search(r"function speichereAddinPfad\([\s\S]*?\n    \}", ADMIN_JS)
check("speichereAddinPfad gefunden", _m is not None)
_sp = _m.group(0) if _m else ""
check("sendet NUR das eigene Feld (eigene Teilmenge)",
      _sp.count(FELD) >= 1 and "ews_url" not in _sp and "imap_host" not in _sp,
      _sp[:200])
# Und umgekehrt: der Verbindungs-Knopf darf den Pfad nicht mitsenden.
_m2 = re.search(r"function speichereVerbindung\([\s\S]*?\n    \}", ADMIN_JS)
check("speichereVerbindung sendet den Pfad NICHT",
      _m2 is not None and FELD not in _m2.group(0))


print("\n\033[1m5. Der Pfad wird NIE als Ziel benutzt\033[0m")

# ⚠ DIE ZENTRALE ZUSAGE. Der Pfad ist eine ANGABE fuer Menschen. Es gibt keine
# Browser-API, die in einen als TEXT genannten Ordner schreibt, und der Server
# bindet dafuer keine Freigabe ein. Wer das aendert, macht aus einem
# Anzeigefeld ein Schreibziel - und aus dem Feld die Luecke, die diese Grenze
# verhindert.
# ⚠ GESCHNITTEN PER AST, nicht per Regex. Die erste Fassung suchte
# `def ordner_pfad(...)` in der KOMMENTARFREIEN Fassung – dort steht nach
# `tokenize` jedes Token auf eigener Zeile, das Muster traf NIE, und der Test
# fiel auf die GANZE Datei zurueck: er meldete `subprocess` als Verstoss, das
# in einer voellig anderen Funktion (`zert_namen`) steht. Register: ein Schnitt,
# der nichts trifft, prueft fremden Code.
_ordner_knoten = None
for _k in ast.walk(ast.parse(ADDIN_PY)):
    if isinstance(_k, ast.FunctionDef) and _k.name == "ordner_pfad":
        _ordner_knoten = _k
        break
check("ordner_pfad im Syntaxbaum gefunden", _ordner_knoten is not None)
_of = ohne_kommentare(ast.get_source_segment(ADDIN_PY, _ordner_knoten) or "") \
    if _ordner_knoten else ""
# POSITIVKONTROLLE DES SCHNITTS: er muss die Funktion enthalten und NICHT die
# Nachbarfunktion, in der `subprocess` legitim steht.
check("Schnitt trifft ordner_pfad und nur sie",
      "addin_ordner_pfad" in _of and "isprintable" in _of
      and "def zert_namen" not in _of and "def dateiname" not in _of,
      _of[:120])
for verb in ("open(", "mkdir", "write_text", "shutil", "subprocess", "Path("):
    check("ordner_pfad benutzt kein %s" % verb, verb not in _of, _of[:200])

# Im Client: der eingetragene Pfad darf nirgends an eine Schreib-API gehen.
_js_ohne = re.sub(r"/\*[\s\S]*?\*/", "", ADMIN_JS)
_js_ohne = re.sub(r"(?m)^\s*//.*$", "", _js_ohne)
check("showDirectoryPicker bekommt KEINEN Pfad als Argument",
      not re.search(r"showDirectoryPicker\(\s*\{[^}]*(feldPfad|_pfadGespeichert)", _js_ohne))
check("showSaveFilePicker wird nicht mit einem Pfad gefuettert",
      not re.search(r"suggestedName\s*:\s*[^,}]*(feldPfad|_pfadGespeichert)", _js_ohne))


print("\n\033[1m6. Der Ordner-Weg: nur wo er wirklich geht\033[0m")

_m = re.search(r"function ordnerKnopf\([\s\S]*?\n    \}", _js_ohne)
check("ordnerKnopf gefunden", _m is not None)
_ok = _m.group(0) if _m else ""
# Ein Knopf, der in Firefox nichts tut, ist schlimmer als keiner; und einer
# ohne Zielpfad hat kein Ziel.
check("Knopf braucht Browser-Faehigkeit UND Pfad",
      "kannSchreiben()" in _ok and "feldPfad()" in _ok, _ok[:200])
# Eine Datei, die auf jedem Arbeitsplatz ins Leere zeigt, darf auch der
# Ordner-Weg nicht in die Freigabe legen.
check("bei kaputter Adresse bleibt der Knopf aus", "_adresseKaputt" in _ok)
# ⚠ Im Excel-Reiter sass diese Funktion HINTER dem fruehen Ausstieg fuer
# "kein Pfad": der Zweig war unerreichbar, und beim LEEREN des Feldes blieb der
# Knopf stehen. Deshalb: sie haengt am `input` des Feldes.
check("Knopf folgt dem FELDINHALT sofort (input-Zuhoerer)",
      re.search(r"em-addin-pfad'\)[\s\S]{0,200}addEventListener\('input',\s*ordnerKnopf",
                _js_ohne) is not None)
# `showDirectoryPicker` verlangt eine frische Benutzergeste - nach dem ersten
# `await` ist sie verbraucht (im Projekt bei `sidePanel.open` drei Runden lang
# bezahlt). Der Ordner MUSS also vor dem Netz-Abruf besorgt werden.
_m = re.search(r"function schreibeInOrdner\([\s\S]*?\n    \}", _js_ohne)
check("schreibeInOrdner gefunden", _m is not None)
_si = _m.group(0) if _m else ""
_i_ordner = _si.find("ordnerBesorgen()")
_i_fetch = _si.find("fetch(")
check("Ordner wird VOR dem Manifest-Abruf besorgt (Benutzergeste!)",
      0 <= _i_ordner < _i_fetch, "ordner=%d fetch=%d" % (_i_ordner, _i_fetch))
# Ein abgebrochener Dialog ist keine Stoerung - der Benutzer hat sich
# entschieden.
check("abgebrochener Dialog wird nicht als Fehler gemeldet",
      "AbortError" in _si, _si[:200])
# Der Dateiname folgt dem Branding und wird aus dem Antwortkopf gelesen -
# nachgebaut liefe er dem Branding hinterher (beim Jira-Paket gemeldet).
check("Dateiname kommt aus Content-Disposition, nicht nachgebaut",
      "dateinameAus(" in _si and "'jarvis" not in _si.lower(), _si[:200])


print("\n\033[1m7. dateinameAus – beide Kopf-Formen\033[0m")

# Bei einem Namen MIT Leerzeichen sendet Starlette die RFC-5987-Form
# `filename*=utf-8''…` – eine Pruefung nur auf `filename=` meldete dort einen
# Fehler, den es nicht gibt (im Projekt bezahlt).
_m = re.search(r"function dateinameAus\([\s\S]*?\n    \}", _js_ohne)
check("dateinameAus gefunden", _m is not None)
_dn = _m.group(0) if _m else ""
check("kennt die RFC-5987-Form (filename*=utf-8'')", "filename\\*" in _dn or "filename*" in _dn)
check("kennt die einfache Form (filename=\"…\")", 'filename\\s*=' in _dn or 'filename=' in _dn)
check("faellt auf LEER zurueck, nicht auf 'jarvis'",
      "jarvis" not in _dn.lower(), _dn[:160])


print("\n\033[1m8. Markup: der Container ist verdrahtet\033[0m")

SET = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")

check("Container em-sect-addin im Markup", 'id="em-sect-addin"' in SET)
# Ohne Eintrag in _initEmailCollapse traegt das Markup zwar die Klassen, aber
# NICHTS bindet den Klick - der Container liesse sich nicht zuklappen.
_m = re.search(r"function _initEmailCollapse\(\)[\s\S]*?\n        \}", APP)
check("_initEmailCollapse gefunden", _m is not None)
_ic = _m.group(0) if _m else ""
check("em-sect-addin ist in _initEmailCollapse registriert",
      "em-sect-addin-hdr" in _ic, _ic)
# REGEL statt Liste: JEDE .kb-section des E-Mail-Reiters muss gebunden sein -
# damit faellt auch ein kuenftiger Container auf, ohne dass jemand pflegt.
_m = re.search(r'id="settings-tab-email"[\s\S]*?\n                <!-- ═══ Tab:', SET)
check("E-Mail-Reiter geschnitten", _m is not None)
_reiter = _m.group(0) if _m else ""
_sects = re.findall(r'class="kb-section" id="(em-sect-[a-z]+)"', _reiter)
check("Reiter hat mehrere Container (Schnitt plausibel)", len(_sects) >= 5, _sects)
_fehlt = [x for x in _sects if (x + "-hdr") not in _ic]
check("JEDE .kb-section des Reiters ist gebunden", not _fehlt, _fehlt)

# Der Download ist ein reines <a href>: so entscheidet der Browser ueber das
# Ziel, und die Datei darf auch auf den Desktop. Jeder abgefangene Klick nimmt
# dem Administrator diese Wahl (Umbau 2026-08-24 im Excel-Reiter).
check("Download-Knopf ist ein <a href> auf das Manifest",
      re.search(r'<a[^>]*id="em-addin-download"[^>]*href="/addin/manifest\.xml"', SET)
      is not None)
check("Ordner-Knopf startet versteckt (erscheint nur in Chrome/Edge mit Pfad)",
      re.search(r'id="em-addin-upload"[^>]*display:none', SET) is not None)


print("\n\033[1m9. i18n: jeder benutzte Schluessel existiert in DE und EN\033[0m")

I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")


def i18n_haelften():
    """DE- und EN-Block getrennt – geschnitten an der STRUKTUR (``de: {`` /
    ``en: {``), nicht an einem beliebigen Schluessel.

    ⚠ DIE ERSTE FASSUNG SCHNITT AN ``'mail.addin_head':`` – und meldete fuenf
    FAIL, die es nicht gab: die ``mailadm.*``-Keys stehen im Block WEIT DAVOR
    (Zeile 476 bzw. 3769), landeten damit in der falschen Haelfte und galten als
    fehlend. Genau der Register-Fallstrick "Schnittgrenze ist eine Textmarke in
    einem fremden Abschnitt" (``test_email_ui.js`` schnitt so drei Reiter statt
    einem).
    """
    i = I18N.find("\n    de: {")
    j = I18N.find("\n    en: {")
    if i < 0 or j < 0 or j <= i:
        return None, None
    return I18N[i:j], I18N[j:]


_de, _en = i18n_haelften()
check("DE- und EN-Block gefunden", _de is not None and _en is not None)
# POSITIVKONTROLLE DES SCHNITTS: ohne sie bliebe eine zu weite oder zu enge
# Grenze unbemerkt, solange die Schluessel zufaellig auf beiden Seiten stehen.
check("Schnitt trennt wirklich (DE-Text nur links, EN-Text nur rechts)",
      "'Outlook-Add-in Bereitstellung'" in (_de or "")
      and "'Outlook-Add-in Bereitstellung'" not in (_en or "")
      and "'Outlook add-in deployment'" in (_en or "")
      and "'Outlook add-in deployment'" not in (_de or ""),
      "Schnitt greift in den falschen Block")
_benutzt = set(re.findall(r"T\('((?:mail|mailadm)\.addin[A-Za-z0-9_.]*)'", ADMIN_JS))
_benutzt |= set(re.findall(r"T\('(mail\.addin[A-Za-z0-9_.]*)'",
                           (ROOT / "frontend" / "js" / "email_portal.js").read_text(encoding="utf-8")))
_benutzt |= set(re.findall(r'data-i18n(?:-html)?="((?:mail|mailadm)\.addin[A-Za-z0-9_.]*)"',
                           SET + (ROOT / "frontend" / "email.html").read_text(encoding="utf-8")))
check("es werden ueberhaupt Schluessel benutzt (Positivkontrolle)",
      len(_benutzt) >= 15, len(_benutzt))
_fehlt_de = sorted(k for k in _benutzt if ("'%s':" % k) not in (_de or ""))
_fehlt_en = sorted(k for k in _benutzt if ("'%s':" % k) not in (_en or ""))
check("alle benutzten Schluessel im DE-Block", not _fehlt_de, _fehlt_de)
check("alle benutzten Schluessel im EN-Block", not _fehlt_en, _fehlt_en)
# Platzhalter muessen in BEIDEN Sprachen vorkommen - `window.t()` ersetzt sie
# nicht, das tut der Aufrufer; fehlt {n} im Text, steht dort nichts.
for k, ph in (("mailadm.addin_up_named", "{n}"), ("mailadm.addin_file", "{n}"),
              ("mailadm.addin_written", "{n}")):
    for lbl, blk in (("DE", _de or ""), ("EN", _en or "")):
        _m = re.search(r"'%s':\s*'([^']*)'" % re.escape(k), blk)
        check("%s traegt %s im %s-Text" % (k, ph, lbl), _m is not None and ph in _m.group(1),
              _m.group(1)[:80] if _m else "fehlt")


print("\n\033[1m10. Die Benutzer-Kachel schaltet um, statt zu ergaenzen\033[0m")

MAIL_HTML = (ROOT / "frontend" / "email.html").read_text(encoding="utf-8")
PORTAL = (ROOT / "frontend" / "js" / "email_portal.js").read_text(encoding="utf-8")

check("Download-Zeile hat eine Kennung zum Verstecken", 'id="em-addin-dlrow"' in MAIL_HTML)
check("Pfad-Zeile existiert und startet versteckt",
      re.search(r'id="em-addin-pfadrow"[^>]*hidden', MAIL_HTML) is not None)
# ⚠ `.em-row { display: flex }` UEBERSTIMMT das `hidden`-Attribut. Ohne diese
# Regel bleibt die Pfad-Zeile IMMER sichtbar - steht woertlich im Register
# (`.sp-row[hidden]` in /sap).
check(".em-row[hidden] setzt display:none (sonst wirkt hidden nicht)",
      re.search(r"\.em-row\[hidden\][^{]*\{[^}]*display:\s*none", MAIL_HTML) is not None,
      "Regel fehlt")
check(".em-block[hidden] ebenso",
      re.search(r"\.em-block\[hidden\]|\.em-row\[hidden\],\s*\.em-steps\[hidden\],\s*\.em-block\[hidden\]",
                MAIL_HTML) is not None)
_pj = re.sub(r"/\*[\s\S]*?\*/", "", PORTAL)
_pj = re.sub(r"(?m)^\s*//.*$", "", _pj)
_m = re.search(r"function zeigeAddinPfad\([\s\S]*?\n    \}", _pj)
check("zeigeAddinPfad gefunden", _m is not None)
_za = _m.group(0) if _m else ""
check("liest 'addin_ordner' aus dem Status", "addin_ordner" in _za, _za[:160])
check("ERSETZT den Download, statt ihn zu ergaenzen",
      "em-addin-dlrow" in _za and "em-addin-pfadrow" in _za)
check("schaltet auch die Anleitung um",
      "em-addin-steps-dl" in _za and "em-addin-steps-pfad" in _za)
# textContent, NICHT innerHTML: der Pfad ist Freitext aus dem Reiter.
check("Pfad wird per textContent gesetzt (kein innerHTML)",
      "textContent" in _za and "innerHTML" not in _za, _za[:200])
check("wird beim Statusladen gerufen", "zeigeAddinPfad(" in _pj.split("function zeigeAddinPfad")[0])
# Zwei getrennte Listen und nicht eine, in der JS ein <li> austauscht -
# `applyLang()` setzt `data-i18n-html` bei jedem Sprachwechsel neu und wuerde
# die Aenderung wortlos zurueckdrehen (Lehre aus /excel).
check("beide Anleitungs-Fassungen sind eigene Listen mit data-i18n-html",
      re.search(r'id="em-addin-steps-dl"[^>]*data-i18n-html="mail\.addin_steps_dl"',
                MAIL_HTML) is not None
      and re.search(r'id="em-addin-steps-pfad"[^>]*data-i18n-html="mail\.addin_steps_pfad"',
                    MAIL_HTML) is not None)
# Kopieren MELDET Erfolg UND Fehlschlag - in der Zwischenablage sieht man
# nichts, und `navigator.clipboard` fehlt in unsicheren Kontexten ganz.
_m = re.search(r"function kopiereAddinPfad\([\s\S]*?\n    \}", _pj)
check("kopiereAddinPfad gefunden", _m is not None)
_kp = _m.group(0) if _m else ""
check("Kopieren meldet auch den Fehlschlag mit Ausweg",
      "copyfail" in _kp and "clipboard" in _kp, _kp[:200])
# Der zweite Anleitung-Knopf liegt in der Pfad-Zeile: schaltet nur der erste
# um, ist die Anleitung im Pfad-Fall unerreichbar.
check("beide Anleitung-Knoepfe schalten um",
      "em-addin-help2" in _pj and "em-addin-help'" in _pj, "help2 fehlt")


ok = sum(1 for x in res if x)
print(f"\n\033[1mErgebnis: {ok}/{len(res)}\033[0m")
sys.exit(0 if ok == len(res) else 1)

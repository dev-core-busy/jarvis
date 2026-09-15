#!/usr/bin/env python3
"""Waechter fuer den Vorfall vom 2026-09-15 (ECHT, /chat andreas.bender).

DREI EIGENSCHAFTEN, jede aus einem eigenen Befund:

1. **Ein Bild-Anhang wird zur DATEI.** Bis zu diesem Tag ging ein Bild
   ausschliesslich als base64 ins Modell; PDF und Office legten daneben eine
   Arbeitskopie an, der Bild-Zweig nicht. Damit gab es keinen Pfad – und
   `bild_text_ersetzen` verlangt einen. Der System-Prompt sagte dem Modell
   trotzdem "Den Pfad des Bildes nimmst du aus dem Anhang-Hinweis": es suchte,
   fand nichts und enumerierte /tmp.

2. **Die Verwaltungswurzel ist nicht auflistbar.** `filesystem list
   /tmp/jarvis-anhaenge` nannte jedem Domain-Benutzer die Kennungen aller
   anderen – und die Kennung ist `sha256(name)[:8]`, also rueckrechenbar.

3. **Leere Kennungs-Verzeichnisse verschwinden.** `cleanup` entfernte nur die
   DATEIEN; die Verzeichnisse blieben fuer immer und bildeten ein wachsendes
   Anwesenheitsprotokoll.

Gemessen wird AUSGEFUEHRT, wo es geht (2 und 3 sind reine Funktionen), und per
AST, wo der Code in einem 200-Zeilen-WebSocket-Handler steckt (1). Fuer (1)
laeuft `_anhang_ablegen` zusaetzlich WIRKLICH – eine Quelltext-Pruefung kann
"entsteht eine Datei?" nicht beantworten.

SANDKASTEN: `attachments` und `lauf_tmp` schreiben sonst in die echten
Verzeichnisse des laufenden Servers. Ohne umgebogene Wurzeln bricht der Lauf
mit Exit 2 ab – "konnte nicht laufen" darf nie wie "bestanden" aussehen.
"""
import ast
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0
_BILANZ = False


def check(beschreibung: str, bedingung) -> None:
    """ACHTUNG: (Beschreibung, Bedingung) – nicht andersherum.

    Eine nicht-leere Zeichenkette ist wahr; vertauschte Argumente ergaeben
    lauter gruene Pruefungen, ohne dass je eine Bedingung ausgewertet wurde
    (im Projekt 2026-08-28 mit 57 Aufrufen bezahlt).
    """
    global OK, FAIL
    if not isinstance(beschreibung, str):
        print("ABBRUCH: check(Beschreibung, Bedingung) – Argumente vertauscht")
        sys.exit(2)
    if bedingung:
        OK += 1
        print(f"  OK   {beschreibung}")
    else:
        FAIL += 1
        print(f"  FAIL {beschreibung}")


def sicher(fn, *a, **kw):
    """Ruft fn und macht einen Wurf zu einem Messwert statt zu einem Abbruch."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return ("__WURF__", repr(e))


def _bilanz() -> None:
    if not _BILANZ:
        print("\nABGEBROCHEN – keine Bilanz (Ausnahme vor dem Ende)")
        sys.exit(1)


import atexit
atexit.register(_bilanz)


# ── Hilfsmittel ────────────────────────────────────────────────────────────
# Ein WIRKLICH dekodierbares PNG (1x1, schwarz). Ein erfundener Byte-Klumpen
# belegt nichts: der Zweig prueft den Inhalt nicht, aber ein Test mit Material,
# das ein echter Konsument nicht oeffnet, ist im Projekt schon zweimal
# schiefgegangen (xlsx-Patch, OneNote).
PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def quelltext(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def ohne_kommentare(code: str) -> str:
    """Entfernt #-Kommentare UND DOCSTRINGS, laesst alles andere zeichengenau.

    ⚠ DOCSTRINGS MUESSEN MIT – das hat dieser Waechter im ersten Lauf selbst
    bezahlt: die Pruefung "benutzt rmdir, NICHT rmtree" schlug fehl, weil die
    BEGRUENDUNG der Funktion das Wort `rmtree` dreimal nennt ("rmdir statt
    rmtree", "ein rmtree haette hier ..."). Der Code selbst enthaelt keines.

    `tokenize` kennt nur `COMMENT`; die Begruendungen dieses Projekts stehen
    aber ueberwiegend in Docstrings, und ein Filter, der nur `#` entfernt,
    laesst den Waechter seine eigene Erklaerung lesen. Siebzehnter Fall dieser
    Klasse im Projekt.

    Ersetzt werden die BEREICHE durch Leerzeichen – nicht die Tokens neu
    zusammengesetzt: letzteres zerlegt jeden mehrzeiligen Ausdruck (ebenfalls
    im Register).
    """
    import io
    import tokenize
    aus = list(code)
    zeilen = code.splitlines(keepends=True)

    def _versatz(zeile: int, spalte: int) -> int:
        return sum(len(z) for z in zeilen[: zeile - 1]) + spalte

    def _leeren(von: int, bis: int) -> None:
        for i in range(max(0, von), min(bis, len(aus))):
            if aus[i] != "\n":          # Zeilenstruktur erhalten
                aus[i] = " "

    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type == tokenize.COMMENT:
                _leeren(_versatz(*tok.start), _versatz(*tok.end))
    except Exception:  # noqa: BLE001
        return code

    # Docstrings ueber den AST: erste Anweisung in Modul/Klasse/Funktion, wenn
    # sie eine blosse Zeichenkette ist.
    try:
        baum = ast.parse(code)
        for knoten in ast.walk(baum):
            if not isinstance(knoten, (ast.Module, ast.ClassDef,
                                       ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            rumpf = getattr(knoten, "body", None) or []
            if not rumpf:
                continue
            erste = rumpf[0]
            if (isinstance(erste, ast.Expr)
                    and isinstance(erste.value, ast.Constant)
                    and isinstance(erste.value.value, str)):
                _leeren(_versatz(erste.lineno, erste.col_offset),
                        _versatz(erste.end_lineno, erste.end_col_offset))
    except Exception:  # noqa: BLE001
        pass
    return "".join(aus)


print("=" * 72)
print("1. BILD-ANHANG WIRD ZUR DATEI")
print("=" * 72)

MAIN = quelltext(ROOT / "backend" / "main.py")
MAIN_OK = ohne_kommentare(MAIN)

# Positivkontrolle des Kommentar-Filters: sonst ist jede Aussage darunter
# wertlos (der Filter koennte still nichts getan haben).
check("Kommentar-Filter greift (#-Begruendung entfernt)",
      "EIN BILD WURDE BIS" in MAIN and "EIN BILD WURDE BIS" not in MAIN_OK)
check("Kommentar-Filter laesst Code stehen",
      "_ALLOWED_IMG_MIME" in MAIN_OK)
# Positivkontrolle des DOCSTRING-Filters an einer Datei, deren Begruendung
# nachweislich in Docstrings steht – genau daran ist dieser Waechter im ersten
# Lauf gescheitert.
_ATT_ROH = quelltext(ROOT / "backend" / "attachments.py")
_ATT_OK = ohne_kommentare(_ATT_ROH)
check("Docstring-Filter greift (Begruendung im Docstring entfernt)",
      "rmdir`` statt" in _ATT_ROH and "rmdir`` statt" not in _ATT_OK)
check("Docstring-Filter laesst Code stehen",
      "def _leere_kennungen_entfernen" in _ATT_OK and ".rmdir()" in _ATT_OK)


def bild_zweig(code: str) -> str:
    """Schneidet den Bild-Zweig des WS-Anhang-Handlers heraus.

    Anker ist die Bedingung selbst, Ende der naechste `elif` derselben Kette –
    ein Fenster fester Groesse griffe in den Audio-Zweig und waere damit
    trivial wahr (im Projekt mehrfach bezahlt).
    """
    start = code.find("if _mime in _ALLOWED_IMG_MIME:")
    if start < 0:
        return ""
    ende = code.find("elif _mime in _ALLOWED_AUD_MIME", start)
    return code[start:ende] if ende > start else code[start:]


ZW = bild_zweig(MAIN_OK)
check("Bild-Zweig gefunden (Positivkontrolle des Schnitts)", len(ZW) > 100)
check("Schnitt endet VOR dem Audio-Zweig", "_ALLOWED_AUD_MIME" not in ZW)
check("Bild-Zweig reicht das Bild weiterhin inline ans Modell",
      "image_attachments.append" in ZW)
# Die WIRKUNG misst Abschnitt 1b (ausgefuehrt). Hier nur die Verdrahtung:
# ruft der Zweig die Funktion, und landet ihr Ergebnis im Prompt?
check("Bild-Zweig ruft _bild_als_datei", "_bild_als_datei(" in ZW)
check("... und stellt dessen Hinweis dem Auftrag voran",
      "_text_prepend.append" in ZW)

# DIE DRIFT-SCHRANKE, die genau diesen Vorfall gefangen haette:
# der System-Prompt verweist die Bildbearbeitung auf den Anhang-Hinweis. Wer
# den Satz stehen laesst und den Hinweis nicht erzeugt, baut den Vorfall nach.
AGENT = ohne_kommentare(quelltext(ROOT / "backend" / "agent.py"))
_prompt_will_pfad = ("bild_text_ersetzen" in AGENT
                     and "Anhang-Hinweis" in AGENT)
check("Prompt verweist die Bildbearbeitung auf den Anhang-Hinweis "
      "(Voraussetzung der naechsten Pruefung)", _prompt_will_pfad)
check("... und der Bild-Zweig LOEST diese Zusage ein",
      (not _prompt_will_pfad) or ("_bild_als_datei(" in ZW))

# Das inline-Bild geht VOR der Ablage raus – die Reihenfolge ist die Zusage
# "ansehen haengt nicht an der Platte".
check("inline-Bild steht VOR der Ablage",
      ZW.find("image_attachments.append") < ZW.find("_bild_als_datei("))


print()
print("=" * 72)
print("1b. DIE KETTE WIRD AUSGEFUEHRT – entsteht Datei UND Hinweis?")
print("=" * 72)

# ⚠ WARUM AUSGEFUEHRT UND NICHT AM QUELLTEXT: die erste Fassung dieses
# Waechters prueste "_anhang_ablegen(" im Zweig – also ein VORKOMMEN. Die
# Gegenprobe `(None, None) or _anhang_ablegen(...)` laesst den Text stehen und
# ruft nichts; sie blieb gruen. Deshalb steckt der Zweig jetzt in
# `_bild_als_datei`, und hier laeuft die ECHTE Kette.
_baum = ast.parse(MAIN)
_teile = {}
for k in ast.walk(_baum):
    if isinstance(k, ast.FunctionDef) and k.name in (
            "_bild_als_datei", "_anhang_ablegen", "_anhang_merken"):
        _teile[k.name] = ast.get_source_segment(MAIN, k) or ""
check("alle drei Funktionen per AST geschnitten (Positivkontrolle)",
      len(_teile) == 3 and all(len(v) > 100 for v in _teile.values()))
_quelle_kette = "\n\n".join(_teile.get(n, "") for n in
                            ("_anhang_ablegen", "_anhang_merken", "_bild_als_datei"))

sandkasten = Path(tempfile.mkdtemp(prefix="bildanhang_"))
try:
    # ⚠ DEN ORT BESTIMMT DIE FUNKTION, NICHT DER TEST: `_anhang_ablegen` baut
    # `Path(__file__).parent.parent / "data" / "documents"`. Ein selbst
    # gewaehltes `sandkasten/documents` waere ein anderer Ort – die Pruefung
    # "dauerhafte Ablage entstanden" schlug damit fehl, obwohl der Code stimmt.
    _docs = sandkasten / "data" / "documents"
    _anh = sandkasten / "jarvis-anhaenge"
    _anh.mkdir()

    class _DocAttrappe:
        registriert = []

        @staticmethod
        def register_upload(name, benutzer):
            _DocAttrappe.registriert.append((name, benutzer))

    class _LaufAttrappe:
        ANH_ROOT = _anh

        @staticmethod
        def anhang_ziel(benutzer, sicherer_name):
            import uuid as _u
            verz = _anh / "aa11bb22"
            verz.mkdir(parents=True, exist_ok=True)
            return verz / ("anhang_%s_%s" % (_u.uuid4().hex[:12], sicherer_name))

    class _PfadAttrappe(type(Path())):
        pass

    ns = {
        "Path": Path, "os": os, "print": lambda *a, **k: None,
        "_documents": _DocAttrappe,
        "_SESSION_ANHAENGE": {}, "_SESSION_ANHAENGE_MAX": 6,
        "_SESSION_ANHAENGE_SITZUNGEN": 200,
    }
    # `Path(__file__).parent.parent / "data" / "documents"` muss in den
    # Sandkasten zeigen – sonst schreibt der Test in den echten Bestand.
    ns["__file__"] = str(sandkasten / "backend" / "main.py")
    (sandkasten / "backend").mkdir()
    (sandkasten / "data").mkdir()
    import sys as _sys
    _sys.modules["backend.lauf_tmp"] = _LaufAttrappe
    exec(compile(_quelle_kette, "<kette>", "exec"), ns)

    import base64 as _b64t
    B64 = _b64t.b64encode(PNG_1x1).decode()
    hinweis = sicher(ns["_bild_als_datei"], B64, "sample.gif", "andreas.bender",
                     "sid-1", {"bild_text_ersetzen", "filesystem"})
    check("Lauf ohne Wurf", isinstance(hinweis, str))
    hinweis = hinweis if isinstance(hinweis, str) else ""

    _kopien = list((_anh / "aa11bb22").glob("anhang_*")) if (_anh / "aa11bb22").is_dir() else []
    check("DER FIX: eine ARBEITSKOPIE ist entstanden", len(_kopien) == 1)
    check("dauerhafte Ablage ist entstanden", len(list(_docs.glob("*"))) == 1)
    if _kopien:
        check("Arbeitskopie traegt das Muster anhang_<12 Hex>_<name>",
              _kopien[0].name.startswith("anhang_") and "_sample.gif" in _kopien[0].name)
        check("Arbeitskopie ist BYTE-GLEICH zum Bild",
              _kopien[0].read_bytes() == PNG_1x1)
        check("Arbeitskopie ist nicht ausfuehrbar",
              not (os.stat(_kopien[0]).st_mode & 0o111))
        check("HINWEIS nennt genau diesen Pfad", _kopien[0].as_posix() in hinweis)
    check("Eigentuemer wurde vermerkt", len(_DocAttrappe.registriert) == 1)
    check("Anhang wurde fuer Folgefragen gemerkt (_anhang_merken gelaufen)",
          bool(ns["_SESSION_ANHAENGE"].get("sid-1")))
    check("Hinweis nennt bild_text_ersetzen (Werkzeug vorhanden)",
          "bild_text_ersetzen" in hinweis)
    check("Hinweis sagt, dass der Pfad zum ANSEHEN nicht noetig ist",
          "ANSEHEN" in hinweis)

    # Gegenrichtung: Werkzeug NICHT im Kasten -> nicht nennen (ein Hinweis auf
    # ein fehlendes Werkzeug endet in "Tool nicht gefunden").
    h2 = sicher(ns["_bild_als_datei"], B64, "zweit.png", "andreas.bender",
                "sid-2", {"filesystem"})
    check("ohne das Werkzeug wird es NICHT genannt",
          isinstance(h2, str) and "bild_text_ersetzen" not in h2)
    h3 = sicher(ns["_bild_als_datei"], B64, "dritt.png", "andreas.bender", "sid-3", None)
    check("bei UNBEKANNTEM Werkzeugkasten wird keines genannt",
          isinstance(h3, str) and "bild_text_ersetzen" not in h3)

    # FAIL-OPEN, zweimal: kaputtes base64 und eine scheiternde Ablage duerfen
    # weder werfen noch einen Pfad behaupten.
    h4 = sicher(ns["_bild_als_datei"], "!!!kein base64!!!", "x.png",
                "andreas.bender", "sid-4", None)
    check("kaputtes base64: kein Wurf, kein Hinweis", h4 == "")

    def _kaputt(*a, **k):
        raise OSError("Platte voll")
    _echt_ablegen = ns["_anhang_ablegen"]
    ns["_anhang_ablegen"] = _kaputt
    h5 = sicher(ns["_bild_als_datei"], B64, "y.png", "andreas.bender", "sid-5", None)
    ns["_anhang_ablegen"] = _echt_ablegen
    check("scheiternde Ablage: kein Wurf, kein Hinweis (fail-open)", h5 == "")
finally:
    _sys.modules.pop("backend.lauf_tmp", None)
    shutil.rmtree(sandkasten, ignore_errors=True)


print()
print("=" * 72)
print("2. VERWALTUNGSWURZEL IST NICHT AUFLISTBAR (ausgefuehrt)")
print("=" * 72)

from backend import lauf_tmp as LT  # noqa: E402
from backend import sandbox as SBX  # noqa: E402

# SANDKASTEN-WAECHTER: die Wurzeln muessen umgebogen sein, sonst legt der Lauf
# Verzeichnisse im echten /tmp an.
sk2 = Path(tempfile.mkdtemp(prefix="bildanhang2_"))
_alt_anh, _alt_arb = LT.ANH_ROOT, LT.ARBEIT_ROOT
try:
    LT.ANH_ROOT = sk2 / "jarvis-anhaenge"
    LT.ARBEIT_ROOT = sk2 / "jarvis-arbeit"
    LT.ANH_ROOT.mkdir(parents=True)
    LT.ARBEIT_ROOT.mkdir(parents=True)
    if not str(LT.ANH_ROOT).startswith(str(sk2)):
        print("ABBRUCH: Sandkasten nicht wirksam")
        sys.exit(2)

    ich = "andreas.bender"
    fremd = "jonas.reichelt"
    k_ich = LT.benutzer_kennung(ich)
    k_fremd = LT.benutzer_kennung(fremd)
    (LT.ANH_ROOT / k_ich).mkdir()
    (LT.ANH_ROOT / k_fremd).mkdir()
    mein_anhang = LT.ANH_ROOT / k_ich / "anhang_aabbccddeeff_sample.gif"
    mein_anhang.write_bytes(PNG_1x1)
    fremder_anhang = LT.ANH_ROOT / k_fremd / "anhang_112233445566_geheim.xlsx"
    fremder_anhang.write_bytes(b"x")

    check("ist_verwaltungswurzel: ANH_ROOT ja", LT.ist_verwaltungswurzel(LT.ANH_ROOT) is True)
    check("ist_verwaltungswurzel: ARBEIT_ROOT ja", LT.ist_verwaltungswurzel(LT.ARBEIT_ROOT) is True)
    check("ist_verwaltungswurzel: Kennungs-Verzeichnis NEIN",
          LT.ist_verwaltungswurzel(LT.ANH_ROOT / k_ich) is False)
    check("ist_verwaltungswurzel: eigener Anhang NEIN",
          LT.ist_verwaltungswurzel(mein_anhang) is False)
    check("ist_verwaltungswurzel: /tmp selbst NEIN (sonst waere /tmp gesperrt)",
          LT.ist_verwaltungswurzel(Path("/tmp")) is False)

    # Jetzt die Entscheidung, um die es geht – ueber authorize_fs, also den Weg,
    # den der Dispatch wirklich nimmt.
    ok_wurzel, grund_wurzel = SBX.authorize_fs("list", str(LT.ANH_ROOT), username=ich)
    check("DER VORFALL: list /tmp/jarvis-anhaenge wird abgewiesen", ok_wurzel is False)
    check("... mit eigener Begruendung (nicht 'gehoert einem anderen')",
          "Verwaltungsverzeichnis" in (grund_wurzel or ""))
    check("... und die Meldung nennt den WEG (Anhang-Hinweis)",
          "Anhang-Hinweis" in (grund_wurzel or ""))

    ok_arb, _ = SBX.authorize_fs("list", str(LT.ARBEIT_ROOT), username=ich)
    check("list auf ARBEIT_ROOT wird ebenso abgewiesen", ok_arb is False)

    # POSITIVKONTROLLE: ohne sie waere die Sperre trivial erfuellbar (alles
    # abzuweisen ist "sicher" und wertlos).
    ok_eigen, grund_eigen = SBX.authorize_fs("read", str(mein_anhang), username=ich)
    check("POSITIVKONTROLLE: der EIGENE Anhang bleibt lesbar", ok_eigen is True)
    ok_eigenverz, _ = SBX.authorize_fs("list", str(LT.ANH_ROOT / k_ich), username=ich)
    check("POSITIVKONTROLLE: das EIGENE Kennungs-Verzeichnis bleibt auflistbar",
          ok_eigenverz is True)

    ok_fremd, grund_fremd = SBX.authorize_fs("read", str(fremder_anhang), username=ich)
    check("fremder Anhang bleibt gesperrt", ok_fremd is False)
    check("... und zwar mit der EIGENTUEMER-Begruendung (nicht der neuen)",
          "anderen Benutzer" in (grund_fremd or ""))
    ok_fremdverz, _ = SBX.authorize_fs("list", str(LT.ANH_ROOT / k_fremd), username=ich)
    check("fremdes Kennungs-Verzeichnis bleibt gesperrt", ok_fremdverz is False)

    # Schreiben in die Wurzel ebenfalls zu (eine Fassung fuer beide Richtungen).
    ok_w, _ = SBX.authorize_fs("write", str(LT.ANH_ROOT / "eigene.txt"), username=ich)
    check("Schreiben DIREKT in die Wurzel ist zu", ok_w is False)
finally:
    LT.ANH_ROOT, LT.ARBEIT_ROOT = _alt_anh, _alt_arb
    shutil.rmtree(sk2, ignore_errors=True)


print()
print("=" * 72)
print("3. LEERE KENNUNGS-VERZEICHNISSE VERSCHWINDEN (ausgefuehrt)")
print("=" * 72)

from backend import attachments as ATT  # noqa: E402

sk3 = Path(tempfile.mkdtemp(prefix="bildanhang3_"))
_alt_anh2 = LT.ANH_ROOT
try:
    LT.ANH_ROOT = sk3 / "jarvis-anhaenge"
    LT.ANH_ROOT.mkdir(parents=True)
    if not str(LT.ANH_ROOT).startswith(str(sk3)):
        print("ABBRUCH: Sandkasten 3 nicht wirksam")
        sys.exit(2)

    jetzt = time.time()
    alt = jetzt - 3600          # eine Stunde
    grenze = jetzt - 1800       # halbe Stunde

    leer_alt = LT.ANH_ROOT / "aaaaaaaa"
    leer_frisch = LT.ANH_ROOT / "bbbbbbbb"
    voll_alt = LT.ANH_ROOT / "cccccccc"
    for d in (leer_alt, leer_frisch, voll_alt):
        d.mkdir()
    (voll_alt / "anhang_aabbccddeeff_wichtig.xlsx").write_bytes(b"daten")
    os.utime(leer_alt, (alt, alt))
    os.utime(voll_alt, (alt, alt))
    # leer_frisch behaelt die aktuelle mtime

    weg = sicher(ATT._leere_kennungen_entfernen, grenze, os.getuid())
    check("Aufraeumen lief ohne Wurf", isinstance(weg, list))
    weg = weg if isinstance(weg, list) else []

    check("DER BEFUND: leeres ALTES Verzeichnis ist weg", not leer_alt.exists())
    check("... und wird gemeldet", "aaaaaaaa" in weg)
    check("leeres FRISCHES Verzeichnis bleibt (Frist wirkt)", leer_frisch.is_dir())
    check("VOLLES altes Verzeichnis bleibt (rmdir statt rmtree)", voll_alt.is_dir())
    # NIE UNGEPRUEFT DEREFERENZIEREN: mit `rmtree` statt `rmdir` ist die Datei
    # weg, `read_bytes()` wirft, und die Gegenprobe endete OHNE BILANZZEILE –
    # von "nicht gelaufen" nicht zu unterscheiden (im ersten Lauf passiert).
    check("... und seine Datei ist unangetastet",
          sicher(lambda: (voll_alt / "anhang_aabbccddeeff_wichtig.xlsx").read_bytes()) == b"daten")

    # Die wichtigste Schranke: /tmp selbst darf NIE Gegenstand sein.
    quelle = quelltext(ROOT / "backend" / "attachments.py")
    quelle_ok = ohne_kommentare(quelle)
    _fn_start = quelle_ok.find("def _leere_kennungen_entfernen")
    _fn = quelle_ok[_fn_start:] if _fn_start >= 0 else ""
    check("Aufraeumen ist auf ANH_ROOT beschraenkt (nicht _arbeitswurzeln)",
          bool(_fn) and "ANH_ROOT" in _fn and "_arbeitswurzeln" not in _fn)
    check("Aufraeumen benutzt rmdir, NICHT rmtree",
          bool(_fn) and ".rmdir()" in _fn and "rmtree" not in _fn)
    check("Aufraeumen prueft den Eigentuemer", bool(_fn) and "st_uid" in _fn)
    check("Aufraeumen folgt keinem Symlink (lstat + S_ISDIR)",
          bool(_fn) and "lstat()" in _fn and "S_ISDIR" in _fn)

    # Symlink-Gegenprobe, ausgefuehrt: ein Symlink auf ein fremdes Verzeichnis
    # darf nicht verfolgt werden.
    ziel = sk3 / "fremdes_ziel"
    ziel.mkdir()
    link = LT.ANH_ROOT / "dddddddd"
    os.symlink(ziel, link)
    os.utime(link, (alt, alt), follow_symlinks=False)
    sicher(ATT._leere_kennungen_entfernen, grenze, os.getuid())
    check("Symlink wird nicht entfernt und nicht verfolgt",
          link.is_symlink() and ziel.is_dir())

    # Verdrahtung: nuetzt nichts, wenn cleanup() es nicht ruft.
    _cl_start = quelle_ok.find("def cleanup(")
    _cl_ende = quelle_ok.find("def _leere_kennungen_entfernen")
    _cl = quelle_ok[_cl_start:_cl_ende] if 0 <= _cl_start < _cl_ende else ""
    check("cleanup() RUFT das Aufraeumen (die Funktion allein nuetzt nichts)",
          "_leere_kennungen_entfernen(" in _cl)
finally:
    LT.ANH_ROOT = _alt_anh2
    shutil.rmtree(sk3, ignore_errors=True)


print()
print("=" * 72)
print(f"Ergebnis: {OK} OK, {FAIL} FAIL")
print("=" * 72)
_BILANZ = True
sys.exit(1 if FAIL else 0)

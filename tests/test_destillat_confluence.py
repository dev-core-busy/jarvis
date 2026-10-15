#!/usr/bin/env python3
"""Waechter: Destillat als NEUE Confluence-Seite speichern (Vorgabe 2026-09-29).

Geprueft wird die EIGENSCHAFT, nicht die Schreibweise:

* **Der Konverter laeuft WIRKLICH.** Ob aus `## Titel` ein `<h2>` wird, ob der
  Rumpf ueberhaupt wohlgeformtes XML ist (sonst lehnt Confluence ihn ab) und ob
  ein `[BILD-N]` nach dem Wegfallen eines Bildes noch auf das RICHTIGE zeigt,
  kann eine Quelltext-Pruefung nicht beantworten.
* **Die Endpunkt-Zusagen stehen als REGELN ueber den AST** – damit faellt auch
  eine kuenftige Stelle auf, ohne dass jemand eine Liste pflegt.

⚠ KEIN SANDKASTEN NOETIG: gemessen werden reine Funktionen und Quelltext. Dass
das Modul ueberhaupt nichts Dauerhaftes schreibt, ist die Zusage von
`test_wissen_destillat.py` Abschnitt 1 und wird dort gehalten.
"""
from __future__ import annotations

import ast
import base64
import importlib.util
import io
import sys
import tokenize
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(desc, cond, info=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  \033[32m✓\033[0m {desc}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {desc}" + (f" – {info}" if info else ""))


def section(t):
    print(f"\n\033[1m{t}\033[0m")


def sicher(fn, *a, **k):
    """Aufruf, der nicht wirft. Ein Wurf ist ein FAIL, KEIN Abbruch – sonst
    endet der Lauf ohne Bilanzzeile und ist von 'nicht gelaufen' nicht zu
    unterscheiden (Register)."""
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return e


spec = importlib.util.spec_from_file_location(
    "wd_cf_test", ROOT / "backend" / "wissen_destillat.py")
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)

# ⚠ NAMENS-GUARD GANZ OBEN. Gegen einen aelteren Stand braeche der Lauf sonst
# mit AttributeError ab – ohne Bilanzzeile, also ununterscheidbar von "nicht
# gelaufen" (Register, mehrfach bezahlt).
_NOETIG = ["storage_aus_markdown", "bilder_als_dateien", "TITEL_MAX",
           "titel_aus_markdown", "MAX_BILDER", "MAX_BILD_BYTES",
           "MAX_BILDER_GESAMT"]
_fehlt = [n for n in _NOETIG if not hasattr(wd, n)]
if _fehlt:
    print(f"  \033[31m✗\033[0m Modul unvollstaendig: {', '.join(_fehlt)} – Abbruch")
    sys.exit(2)

MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "wissen_destillat.js").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "wissen.html").read_text(encoding="utf-8")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
CLIENT = (ROOT / "backend" / "confluence_client.py").read_text(encoding="utf-8")


def ohne_worte(quelle: str) -> str:
    """Kommentare UND Docstrings entfernen, Ergebnis bleibt parsebar.

    ⚠ `tokenize` allein genuegt NICHT – die Begruendungen dieses Projekts
    stehen ueberwiegend in DOCSTRINGS, und ein Waechter, der die liest, prueft
    seine eigene Erklaerung (neunzehn belegte Faelle im Register). Umgekehrt
    kennt nur `tokenize` die Kommentare: ein `re.sub(r"#.*$")` frisst das `##`
    innerhalb einer Zeichenkette und macht die Datei unparsebar.
    """
    puffer = quelle.splitlines(keepends=True)
    for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
        if tok.type == tokenize.COMMENT:
            (zl, zs), (el, es) = tok.start, tok.end
            if zl == el:
                z = puffer[zl - 1]
                puffer[zl - 1] = z[:zs] + " " * (es - zs) + z[es:]
    zwischen = "".join(puffer)
    weg = []
    for k in ast.walk(ast.parse(zwischen)):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                          ast.Module)):
            leib = getattr(k, "body", [])
            if (leib and isinstance(leib[0], ast.Expr)
                    and isinstance(leib[0].value, ast.Constant)
                    and isinstance(leib[0].value.value, str)):
                ersatz = "''" if len(leib) == 1 else ""
                weg.append((leib[0].lineno, leib[0].end_lineno, ersatz,
                            leib[0].col_offset))
    aus = zwischen.splitlines()
    for a, b, ersatz, spalte in weg:
        for i in range(a - 1, b):
            aus[i] = (" " * spalte + ersatz) if (i == a - 1 and ersatz) else ""
    return "\n".join(aus)


def ohne_js_kommentare(quelle: str) -> str:
    """`//`- und `/* */`-Kommentare aus JavaScript entfernen.

    ⚠ BEIM BAU BEZAHLT: die Pruefung "die Hierarchie kommt von
    `WissenPortal.cfBaum`" blieb gruen, waehrend die Gegenprobe den Aufruf
    ersetzt hatte – der Name stand noch im KOMMENTAR darueber, und der
    Waechter las damit seine eigene Begruendung (Register, neunzehnter Fall).

    ⚠ REGEX-LITERALE BRAUCHEN SEHR WOHL EINE SONDERBEHANDLUNG – die erste
    Fassung dieses Filters behauptete das Gegenteil und war dadurch blind:
    `.replace(/[&<>"]/g, …)` in `md()` enthaelt ein Anfuehrungszeichen, ein
    reiner Zeichenketten-Scanner haelt den Rest der Datei fuer einen String und
    entfernt danach gar keinen Kommentar mehr. Die Positivkontrolle hat es
    gemeldet, nicht das Lesen.

    Ob ein `/` ein Regex beginnt oder eine Division ist, entscheidet das letzte
    bedeutsame Zeichen davor: nach `)`, `]`, einer Ziffer oder einem Bezeichner
    wird geteilt (`b / 1024`), sonst beginnt ein Literal.
    """
    # Nach diesen Zeichen (oder am Anfang) kann ein Regex-Literal stehen.
    VOR_REGEX = "(,=:[!&|?{};+-*%~^<>"
    aus = []
    i, n = 0, len(quelle)
    vorher = ""
    while i < n:
        z = quelle[i]
        if z in "'\"`":
            j = i + 1
            while j < n:
                if quelle[j] == "\\":
                    j += 2
                    continue
                if quelle[j] == z:
                    break
                j += 1
            aus.append(quelle[i:j + 1])
            vorher = z
            i = j + 1
            continue
        if z == "/" and i + 1 < n and quelle[i + 1] == "/":
            while i < n and quelle[i] != "\n":
                i += 1
            continue
        if z == "/" and i + 1 < n and quelle[i + 1] == "*":
            e = quelle.find("*/", i + 2)
            i = (e + 2) if e >= 0 else n
            continue
        if z == "/" and (vorher == "" or vorher in VOR_REGEX):
            j, klasse = i + 1, False
            while j < n:
                c = quelle[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    klasse = True
                elif c == "]":
                    klasse = False
                elif c == "\n":
                    break
                elif c == "/" and not klasse:
                    break
                j += 1
            aus.append(quelle[i:j + 1])
            vorher = "/"
            i = j + 1
            continue
        aus.append(z)
        if not z.isspace():
            vorher = z
        i += 1
    return "".join(aus)


JS_OK = ohne_js_kommentare(JS)
MAIN_OK = ohne_worte(MAIN)
# POSITIVKONTROLLEN des Filters – ohne sie waere jede Pruefung darauf wertlos.
check("Filter entfernt Kommentare",
      "DER SEITENINHALT GEHT ALS HTML RAUS" in MAIN
      and "DER SEITENINHALT GEHT ALS HTML RAUS" not in MAIN_OK)
check("Filter laesst Code stehen und parsebar",
      "async def wissen_destillat_confluence(" in MAIN_OK
      and not isinstance(sicher(ast.parse, MAIN_OK), Exception))
# Dasselbe fuer das JS – ohne diese beiden Kontrollen waere jede Pruefung auf
# `JS_OK` wertlos (ein Filter, der nichts entfernt, laesst den Waechter seine
# eigene Begruendung lesen; einer, der zu viel entfernt, prueft eine Datei,
# die es so nicht gibt).
check("JS-Filter entfernt Kommentare",
      "derselben Regel wie im Baum" in JS and "derselben Regel wie im Baum" not in JS_OK)
check("JS-Filter laesst Code stehen",
      "function cfZeigen(" in JS_OK and "var bauen =" in JS_OK)
# ⚠ DIESE DREI HABEN DEN FILTERFEHLER GEFUNDEN: ein Regex mit `"` darin, ein
# Regex mit Backticks, und eine echte Division. Ohne sie waere er weiter blind.
check("JS-Filter ueberlebt ein Regex mit Anfuehrungszeichen",
      'replace(/[&<>"]/g' in JS_OK)
check("JS-Filter ueberlebt ein Regex mit Backticks",
      "[^`\\n]+" in JS_OK)
check("JS-Filter haelt eine Division nicht fuer ein Regex",
      "(b / 1024 / 1024).toFixed(1)" in JS_OK)
check("JS-Filter laesst den Modulabschluss stehen",
      "window.WissenDestillat = {" in JS_OK)


def knoten(quelle: str, name: str):
    """AST-Knoten EINER Funktion – exakt ueber den Namen, nicht per Textmarke.

    Ein Teilstring ist keine Identitaet (Register): `"x" in quelle` bleibt wahr,
    wenn die Funktion in `_alt_x` umbenannt wurde.
    """
    for k in ast.walk(ast.parse(quelle)):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return k
    return None


def aufrufe(k) -> dict:
    """``{Aufrufname: erste Zeilennummer}`` innerhalb eines Knotens.

    Gezaehlt wird ein echter ``ast.Call`` – ein VORKOMMEN des Namens (Import,
    Kommentar, Zeichenkette) ist keine Aussage darueber, dass wirklich
    aufgerufen wird.
    """
    raus: dict = {}
    for x in ast.walk(k):
        if not isinstance(x, ast.Call):
            continue
        f = x.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name and name not in raus:
            raus[name] = x.lineno
        # `asyncio.to_thread(c.create_page, ...)` – der eigentliche Aufruf steht
        # als ARGUMENT da und waere sonst unsichtbar.
        for arg in x.args:
            if isinstance(arg, ast.Attribute) and arg.attr not in raus:
                raus[arg.attr] = x.lineno
    return raus


XMLNS = ('<root xmlns:ac="http://x/ac" xmlns:ri="http://x/ri">', "</root>")


def wohlgeformt(rumpf: str):
    """Ist der Storage-Rumpf gueltiges XML? Genau das entscheidet, ob
    Confluence ihn annimmt – ein `<br>` statt `<br/>` fliegt dort raus."""
    return sicher(ET.fromstring, XMLNS[0] + rumpf + XMLNS[1])


def png(fuell: bytes = b"A") -> bytes:
    return bytes.fromhex("89504e470d0a1a0a") + fuell


def jpg(fuell: bytes = b"B") -> bytes:
    return b"\xff\xd8\xff" + fuell


def uri(daten: bytes, behauptet: str = "image/png") -> str:
    return f"data:{behauptet};base64," + base64.b64encode(daten).decode()


# ════════════════════════════════════════════════════════════════════════════
section("1. Der Seiteninhalt ist HTML – das ist die Vorgabe")

_md = ("# Haupttitel\n\n"
       "Ein **fetter** Satz mit *kursiv* und `code`.\n\n"
       "## Abschnitt\n\n"
       "- eins\n- zwei\n\n"
       "1. erstens\n2. zweitens\n\n"
       "Siehe [Handbuch](https://example.org/h).\n\n"
       "---\n\n"
       "```python\nx = 1\n```\n")
_out = sicher(wd.storage_aus_markdown, _md, [])
check("Konverter wirft nicht", not isinstance(_out, Exception), str(_out)[:120])
_out = _out if isinstance(_out, str) else ""

for _tag in ("<h1>", "<h2>", "<strong>", "<em>", "<code>", "<ul>", "<li>",
             "<ol>", "<p>", "<hr />", "<pre>", "<a href="):
    check(f"HTML erzeugt: {_tag}", _tag in _out)

# ⚠ DIE GEGENRICHTUNG IST DIE EIGENTLICHE ZUSAGE: bliebe die Markdown-Auszeichnung
# stehen, stuende sie auf der Confluence-Seite sichtbar im Text.
check("keine Markdown-Ueberschrift mehr im Rumpf", "# Haupttitel" not in _out)
check("keine Markdown-Fettschrift mehr im Rumpf", "**fetter**" not in _out)
check("keine Markdown-Liste mehr im Rumpf", "\n- eins" not in _out)
check("keine Markdown-Linkklammern mehr im Rumpf", "](https://" not in _out)

check("Rumpf ist wohlgeformtes XML (sonst nimmt Confluence ihn nicht)",
      not isinstance(wohlgeformt(_out), Exception), str(wohlgeformt(_out))[:120])
check("Umbruch als XHTML `<br />`, nicht `<br>`",
      "<br>" not in sicher(wd.storage_aus_markdown, "a\nb", []))


# ════════════════════════════════════════════════════════════════════════════
section("2. Der Text ist FREMDTEXT – er kann kein Markup erzeugen")
# Das Destillat kommt von einem Modell, das hochgeladene Fremddokumente
# verarbeitet hat. Was daraus nach Confluence geht, ist Text – nie Markup.

_boese = ('<script>alt()</script> & <img src=x onerror="a">\n\n'
          '<ac:structured-macro ac:name="html" />')
_b = sicher(wd.storage_aus_markdown, _boese, [])
_b = _b if isinstance(_b, str) else ""
check("`<script>` wird maskiert", "<script>" not in _b and "&lt;script&gt;" in _b)
check("`&` wird zu `&amp;`", "&amp;" in _b)
check("untergeschobenes Makro wird maskiert",
      "<ac:structured-macro" not in _b and "&lt;ac:structured-macro" in _b)
check("maskierter Fremdtext bleibt wohlgeformtes XML",
      not isinstance(wohlgeformt(_b), Exception))

# ⚠ STEUERZEICHEN: XML kennt sie nicht, Confluence lehnt den GANZEN Rumpf ab.
_st = sicher(wd.storage_aus_markdown, "vor\x00\x08nach", [])
_st = _st if isinstance(_st, str) else ""
check("Steuerzeichen werden entfernt", "\x00" not in _st and "\x08" not in _st)
check("Text um das Steuerzeichen bleibt erhalten", "vor" in _st and "nach" in _st)
check("Rumpf mit Steuerzeichen bleibt wohlgeformt",
      not isinstance(wohlgeformt(_st), Exception))

# `javascript:` darf nie ein Link werden – er liefe im Origin der Seite.
_js = sicher(wd.storage_aus_markdown, "[klick](javascript:alert(1))", [])
check("`javascript:`-Link wird NICHT verlinkt",
      isinstance(_js, str) and "<a href" not in _js)


# ════════════════════════════════════════════════════════════════════════════
section("3. Blockelemente verschlucken den folgenden Text nicht")
# ⚠ DER FALL OHNE LEERZEILE ist der, den ein Modell erzeugt – und er war beim
# Bau kaputt: der Absatz hinter der Ueberschrift landete roh im selben Stueck.

_eng = sicher(wd.storage_aus_markdown,
              "# Titel\nText direkt darunter.\n## Zwei\n- a\n- b\nNach der Liste.", [])
_eng = _eng if isinstance(_eng, str) else ""
check("Absatz direkt unter einer Ueberschrift wird ein <p>",
      "<p>Text direkt darunter.</p>" in _eng, _eng[:160])
check("Absatz direkt unter einer Liste wird ein <p>",
      "<p>Nach der Liste.</p>" in _eng, _eng[:200])
check("die Ueberschrift bleibt dabei eine Ueberschrift", "<h1>Titel</h1>" in _eng)


# ════════════════════════════════════════════════════════════════════════════
section("4. Bilder werden Anhaenge – und die Marker zeigen auf das richtige")

_b1, _b3 = uri(png(b"eins")), uri(jpg(b"drei"), "image/jpeg")
_liste = sicher(wd.bilder_als_dateien, [_b1, "kaputt", _b3])
check("bilder_als_dateien wirft nicht", not isinstance(_liste, Exception),
      str(_liste)[:120])
_liste = _liste if isinstance(_liste, list) else []

# ⚠ DIE INDEXGLEICHHEIT IST DER KERN. Wer die verworfenen Bilder weglaesst,
# verschiebt jeden Marker dahinter um eins – auf der Seite steht dann das
# falsche Bild, und zwar ohne jede Fehlermeldung.
check("Rueckgabe ist indexgleich zur Eingabe", len(_liste) == 3, str(len(_liste)))
check("das verworfene Bild ist None, nicht weggelassen",
      len(_liste) == 3 and _liste[1] is None)
check("das dritte Bild behaelt seine Nummer",
      len(_liste) == 3 and _liste[2] and _liste[2][0] == "bild-3.jpg",
      str(_liste[2] if len(_liste) == 3 else "?"))

_namen = [x[0] if x else "" for x in _liste]
_mb = sicher(wd.storage_aus_markdown, "A [BILD-1] B [BILD-2] C [BILD-3]", _namen)
_mb = _mb if isinstance(_mb, str) else ""
check("[BILD-1] wird ein Anhang-Verweis",
      '<ri:attachment ri:filename="bild-1.png" />' in _mb, _mb[:200])
check("[BILD-3] zeigt auf bild-3.jpg, NICHT auf bild-1",
      '<ri:attachment ri:filename="bild-3.jpg" />' in _mb, _mb[:200])
check("[BILD-2] (verworfen) wird zum HINWEIS, nicht zu einem toten Verweis",
      "Bild 2" in _mb and 'ri:filename="bild-2' not in _mb, _mb[:200])
check("Bildrumpf bleibt wohlgeformtes XML",
      not isinstance(wohlgeformt(_mb), Exception))

# Ein Marker ohne jedes Bild darf keinen Verweis erzeugen.
_ohne = sicher(wd.storage_aus_markdown, "[BILD-1]", [])
check("Marker ohne Anhang ergibt keinen ri:attachment",
      isinstance(_ohne, str) and "ri:attachment" not in _ohne and "Bild 1" in _ohne)

# ⚠ DER ANGEGEBENE MIME-TYP WIRD NICHT GEGLAUBT: die Liste ist Fremdeingabe.
_luege = sicher(wd.bilder_als_dateien, [uri(png(), "image/gif")])
check("die MAGISCHEN BYTES entscheiden, nicht die Behauptung",
      isinstance(_luege, list) and _luege and _luege[0]
      and _luege[0][0].endswith(".png") and _luege[0][2] == "image/png",
      str(_luege)[:120])

_fremd = sicher(wd.bilder_als_dateien, [uri(b"MZ\x90\x00nicht-bild")])
check("eine Nicht-Bild-Datei wird verworfen",
      isinstance(_fremd, list) and _fremd == [None], str(_fremd)[:120])
_typen = sicher(wd.bilder_als_dateien, [42, None, {"a": 1}])
check("Nicht-Zeichenketten werfen nicht und werden verworfen",
      isinstance(_typen, list) and _typen == [None, None, None], str(_typen)[:120])

# Deckel – jeder verhindert etwas anderes.
_viele = sicher(wd.bilder_als_dateien, [uri(png(bytes(10))) for _ in range(wd.MAX_BILDER + 5)])
check("Deckel: hoechstens MAX_BILDER Anhaenge",
      isinstance(_viele, list)
      and len([x for x in _viele if x]) <= wd.MAX_BILDER,
      str(len([x for x in _viele if x]) if isinstance(_viele, list) else "?"))
check("Deckel: die Liste bleibt trotzdem indexgleich",
      isinstance(_viele, list) and len(_viele) == wd.MAX_BILDER + 5)
_gross = sicher(wd.bilder_als_dateien, [uri(png(b"x" * (wd.MAX_BILD_BYTES + 10)))])
check("Deckel: ein zu grosses Einzelbild faellt heraus",
      isinstance(_gross, list) and _gross == [None])


# ════════════════════════════════════════════════════════════════════════════
section("5. Der Endpunkt – Regeln ueber den AST")

_ep = knoten(MAIN_OK, "wissen_destillat_confluence")
if _ep is None:
    print("  \033[31m✗\033[0m Endpunkt wissen_destillat_confluence fehlt – Abbruch")
    sys.exit(2)
_ruf = aufrufe(_ep)

check("Rechte: `_destillat_erlaubt` wird gerufen", "_destillat_erlaubt" in _ruf)
# Code-Review 2026-10-07: NICHT `_cfb_aktiv` – das misst den SAMMELzugang
# (fuer die Einbindung richtig, die der Cron mit ihm abgleicht). Geschrieben
# wird mit dem Zugang des Benutzers; ohne Sammel-Token war das sonst gesperrt.
check("Confluence-Zustand: Skill (`_skill_active`) wird gerufen", "_skill_active" in _ruf)
check("⚠ nicht `_cfb_aktiv` (das verlangte den Sammelzugang)", "_cfb_aktiv" not in _ruf)
_konf = [x for x in ast.walk(_ep) if isinstance(x, ast.Attribute) and x.attr == "configured"
         and isinstance(x.value, ast.Name) and x.value.id == "c"]
check("⚠ konfiguriert heisst: der aufgeloeste Zugang DES Benutzers (`c.configured`)",
      bool(_konf) and _konf[0].lineno > min((x.lineno for x in ast.walk(_ep)
                                              if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                                              and x.func.attr == "aufloesen"), default=10 ** 9),
      [x.lineno for x in _konf])
check("Sichtbarkeit: `_wissen_visible_spaces` wird gerufen",
      "_wissen_visible_spaces" in _ruf)
# REIHENFOLGE IST DIE SICHERHEIT: dahinter waere jede Pruefung wirkungslos.
check("⚠ Rechte VOR dem Lesen des Rumpfes",
      _ruf.get("_destillat_erlaubt", 10 ** 9) < _ruf.get("json", 10 ** 9),
      f"erlaubt={_ruf.get('_destillat_erlaubt')} json={_ruf.get('json')}")
check("⚠ Bereichs-Sichtbarkeit VOR dem Anlegen",
      _ruf.get("_wissen_visible_spaces", 10 ** 9) < _ruf.get("create_page", 10 ** 9),
      f"sichtbar={_ruf.get('_wissen_visible_spaces')} anlegen={_ruf.get('create_page')}")
check("⚠ Elternseite wird gegen die Seiten DIESES Bereichs geprueft",
      "pages_in_space" in _ruf
      and _ruf["pages_in_space"] < _ruf.get("create_page", 10 ** 9))

# ⚠ EIGENER TOKEN VOR SAMMELZUGANG: auf ECHT darf der Sammel-Token in 25 von
# 26 Bereichen nur lesen (gemessen 2026-09-29) – mit ihm scheitert das Anlegen.
_cfa_ruf = [x for x in ast.walk(_ep) if isinstance(x, ast.Call)
            and isinstance(x.func, ast.Attribute) and x.func.attr == "aufloesen"]
check("⚠ Zugang ueber `confluence_accounts.aufloesen` (eigener Token vor Sammelzugang)",
      bool(_cfa_ruf))
check("⚠ `aufloesen` bekommt den ANGEMELDETEN Benutzer",
      any(len(x.args) == 1 and isinstance(x.args[0], ast.Name) and x.args[0].id == "user"
          for x in _cfa_ruf))
check("⚠ nicht der Sammelzugang (`_confluence_client()` ohne Benutzer)",
      "_confluence_client" not in _ruf)
check("⚠ der Zugang steht VOR der Sichtbarkeitspruefung",
      _ruf.get("aufloesen", 10 ** 9) < _ruf.get("_wissen_visible_spaces", 0))
# Schreibrecht VOR dem Anlegen – sonst liest der Benutzer nur "Could not create
# content with type page" (so am 2026-09-29 auf ECHT gemeldet).
check("⚠ Schreibrecht (`space_permissions`) wird VOR `create_page` geprueft",
      _ruf.get("space_permissions", 10 ** 9) < _ruf.get("create_page", 0))
check("Klartext bei fehlendem Schreibrecht (`_cf_kein_schreibrecht`)",
      "_cf_kein_schreibrecht" in _ruf)

check("es wird ANGELEGT (`create_page`)", "create_page" in _ruf)
# ⚠ NIE UEBERSCHREIBEN: ein stilles `update_page` waere der kuerzeste Weg,
# eine fremde Seite zu ersetzen – und das hat niemand bestellt.
check("⚠ es wird NIE ueberschrieben (kein `update_page`)", "update_page" not in _ruf)
check("kein Loeschen im Endpunkt", "delete_page" not in _ruf)

check("der Rumpf entsteht aus `storage_aus_markdown` (HTML, nicht Markdown)",
      "storage_aus_markdown" in _ruf)
check("nicht versehentlich der Wissensdatenbank-Weg (`markdown_fuer_wissen`)",
      "markdown_fuer_wissen" not in _ruf)
check("Bilder laufen ueber `bilder_als_dateien`", "bilder_als_dateien" in _ruf)
check("Anhaenge gehen ueber `upload_attachment_bytes` (nichts auf Platte)",
      "upload_attachment_bytes" in _ruf)

# ⚠ ABGEWIESEN, NICHT GEKUERZT: ein gekuerzter Titel ist ein ANDERER Titel –
# die Seite hiesse dann anders, als der Benutzer gelesen hat.
_ep_q = ast.get_source_segment(MAIN_OK, _ep) or ""
check("Titel wird gegen TITEL_MAX geprueft", "TITEL_MAX" in _ep_q)
check("⚠ Titel wird ABGEWIESEN, nicht gekuerzt",
      "titel[:" not in _ep_q.replace(" ", ""), _ep_q[:0])

# Der Benutzer kommt aus der ANMELDUNG, nie aus dem Rumpf.
check("`user` kommt aus Depends(require_auth)",
      any(isinstance(a, ast.arg) and a.arg == "user" for a in _ep.args.args))
check("kein `user`/`created_by` aus dem Rumpf",
      'body.get("user")' not in _ep_q and 'body.get("created_by")' not in _ep_q)

check("Client kann Anhaenge aus dem Speicher laden",
      "def upload_attachment_bytes(" in CLIENT)


# ════════════════════════════════════════════════════════════════════════════
section("6. Oberflaeche")

check("Knopf im Ergebnisbereich vorhanden", 'id="wi-dest-cf"' in HTML)
check("Zielkasten vorhanden", 'id="wi-dest-cfbox"' in HTML)
for _id in ("wi-dest-cfspace", "wi-dest-cfparent", "wi-dest-cftitel",
            "wi-dest-cfgo", "wi-dest-cfcancel", "wi-dest-cfstatus"):
    check(f"Bedienelement {_id}", f'id="{_id}"' in HTML)

# ⚠ `.sec-btn` SETZT `display` UND SCHLAEGT DAS `hidden`-ATTRIBUT (Register, am
# Protokoll-Knopf derselben Seite bezahlt). Ohne die Regel stuende der Knopf
# auch dann da, wenn Confluence gar nicht aktiv ist.
check("⚠ CSS-Regel gegen das ueberschlagene hidden-Attribut",
      ".wi-dest-actions .sec-btn[hidden]" in HTML)

# ⚠ EINE QUELLE FUER DIE BEREICHSLISTE: der Container holt sie NICHT selbst.
check("⚠ kein eigener Abruf der Bereichsliste im Destillat-Modul",
      "/api/wissen/confluence/spaces" not in JS_OK)
check("Zustand kommt von wissen.js (`confluence` wird exportiert)",
      "confluence: confluence" in JS_OK)
check("wissen.js meldet den Zustand (cfDestMelden)",
      "cfDestMelden" in (ROOT / "frontend" / "js" / "wissen.js").read_text(encoding="utf-8"))
check("Seitenhierarchie ueber `WissenPortal.cfBaum` (keine zweite Fassung)",
      "WissenPortal.cfBaum" in JS_OK)
check("der Endpunkt wird wirklich gerufen",
      "'/api/wissen/destillat/confluence'" in JS_OK)

# i18n in BEIDEN Sprachen – eine gepflegte Liste waere unvollstaendig, sobald
# jemand einen Schluessel ergaenzt: gemessen wird, was der CODE benutzt.
_keys = set(__import__("re").findall(r"'(wissen\.dest_cf[a-z_]*)'", JS_OK))
_keys |= set(__import__("re").findall(r'data-i18n="(wissen\.dest_cf[a-z_]*)"', HTML))
check("mindestens acht dest_cf-Schluessel im Einsatz", len(_keys) >= 8, str(sorted(_keys)))
_de = I18N.split("en:")[0] if "en:" in I18N else I18N
for _k in sorted(_keys):
    check(f"i18n DE+EN: {_k}", I18N.count(f"'{_k}':") >= 2,
          f"{I18N.count(chr(39) + _k + chr(39) + ':')}x")


print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
sys.exit(1 if FAIL else 0)

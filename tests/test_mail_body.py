#!/usr/bin/env python3
"""Rumpf einer Antwort-Mail: Text/HTML, Signatur, HTML-Entschaerfung (2026-08-26).

DER GEMELDETE ZUSTAND: "in dem Outlook-Add-In werden aktuell Entwuerfe im Text
Format erstellt". Ursache war kein Schalter, der falsch stand, sondern dass es
keinen gab: ``mail_client.antworten`` gab den Text als ``str`` weiter, und
exchangelib legt einen ``str`` als ``BodyType=Text`` ab.

WAS DIESER TEST FESTHAELT – drei Zusagen:
  1. **Rich-Text gibt es nicht, und die Funktion sagt das.** EWS kennt in
     ``BodyType`` nur ``Best``/``HTML``/``Text``; ``norm_format`` darf
     "richtext" NICHT stillschweigend als HTML durchgehen lassen.
  2. **Die Entschaerfung ist eine ERLAUBNISLISTE.** Ein Signatur-HTML geht in
     eine echte E-Mail hinaus. Geprueft wird nicht "sind die bekannten boesen
     Tags weg", sondern "kommt nur durch, was vorgesehen ist" - auch etwas, das
     es heute noch nicht gibt.
  3. **Die Signatur geht nie durch ein Modell.** Dieser Test kann das nicht
     beweisen (er kennt kein Modell) - er haelt aber fest, dass
     ``signatur_anhaengen`` eine reine Funktion ohne Aufrufe nach draussen ist,
     und dass sie in beiden Formaten dasselbe anhaengt.

Laeuft OHNE fastapi, exchangelib und Netz - ``mail_body`` importiert nichts aus
dem Projekt (genau dafuer ist es ein eigenes Modul).

Exit 2 = konnte nicht laufen, 1 = Pruefung fehlgeschlagen, 0 = bestanden.

    python3 tests/test_mail_body.py
"""
import re
import sys
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


try:
    from backend import mail_body as mb
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.mail_body nicht importierbar: {e}")
    sys.exit(2)

for _n in ("norm_format", "text_zu_html", "html_zu_text", "html_entschaerfen",
           "signatur_anhaengen", "FORMAT_TEXT", "FORMAT_HTML"):
    if not hasattr(mb, _n):
        print(f"ABBRUCH: mail_body.{_n} fehlt")
        sys.exit(2)


# ═══════════════════════════════════════════════════════════════════════════
section("1. Formate: Rich-Text wird NICHT geraten")
# ═══════════════════════════════════════════════════════════════════════════
check(mb.norm_format("html") == "html", "'html' wird erkannt")
check(mb.norm_format("HTML") == "html", "Gross-/Kleinschreibung egal")
check(mb.norm_format(" text ") == "text", "Leerzeichen werden getrimmt")
# DER KERN: fuer Rich-Text gibt es keinen Weg. Wuerde hier "html" oder "text"
# herauskommen, behauptete die Oberflaeche etwas, das nicht passiert.
for w in ("richtext", "rich-text", "rtf", "RTF", "rich_text"):
    check(mb.norm_format(w) == "", "'%s' ist KEIN gueltiges Format" % w)
check(mb.norm_format(None) == "" and mb.norm_format("") == "" and mb.norm_format("xy") == "",
      "Unbekanntes wird zu '' (= Vorgabe des Postfachs), nicht geraten")
check(mb.FORMATE == ("text", "html") or set(mb.FORMATE) == {"text", "html"},
      "es gibt GENAU zwei Formate", str(mb.FORMATE))
# Die Begruendung muss im Modul stehen - sonst baut sie beim naechsten Anlauf
# wieder jemand nach. Geprueft wird auf die Sache, nicht auf einen Wortlaut.
_src = (ROOT / "backend" / "mail_body.py").read_text(encoding="utf-8")
check("TNEF" in _src and "BodyType" in _src,
      "das Modul begruendet, warum Rich-Text fehlt (TNEF/BodyType)")


# ═══════════════════════════════════════════════════════════════════════════
section("2. Text → HTML: maskiert, Absaetze erhalten, KEIN Markdown")
# ═══════════════════════════════════════════════════════════════════════════
h = mb.text_zu_html("Hallo Welt")
check(h == "<p>Hallo Welt</p>", "ein Absatz", h)
h = mb.text_zu_html("A\n\nB")
check(h.count("<p>") == 2 and "<br>" not in h, "Leerzeile = zwei Absaetze", h)
h = mb.text_zu_html("A\nB")
check(h.count("<p>") == 1 and h.count("<br>") == 1, "einfacher Umbruch = <br>", h)
h = mb.text_zu_html('<b>fett</b> & "Zitat"')
check("&lt;b&gt;" in h and "&amp;" in h and "<b>" not in h,
      "Text wird MASKIERT – ein <b> im Text bleibt Text", h)
# Kein Markdown: der Text ist von einem Menschen freigegeben worden. Wer daraus
# **fett** macht, aendert einen freigegebenen Text nachtraeglich.
h = mb.text_zu_html("Preis **wichtig** und 3*4 und _x_")
check("<strong>" not in h and "<em>" not in h and "**wichtig**" in h,
      "KEINE Markdown-Wiedergabe (Sternchen bleiben Sternchen)", h)
h = mb.text_zu_html("  eingerueckt")
check("&nbsp;" in h, "fuehrende Leerzeichen bleiben sichtbar", h)
h = mb.text_zu_html("Satz  mit  Luecken")
check("&nbsp;" not in h, "Leerzeichen MITTEN im Satz werden nicht geschuetzt", h)
check(mb.text_zu_html("") == "" and mb.text_zu_html("   \n  ") == "",
      "leerer Text ergibt leeres HTML")
h = mb.text_zu_html("A\r\nB")
check(h.count("<br>") == 1, "CRLF wird wie LF behandelt", h)


# ═══════════════════════════════════════════════════════════════════════════
section("3. HTML entschaerfen: Erlaubnisliste, nicht Sperrliste")
# ═══════════════════════════════════════════════════════════════════════════
# Was DURCH muss - eine echte Signatur besteht daraus.
e = mb.html_entschaerfen('<p>Mit freundlichen Gr&uuml;&szlig;en<br><b>Max</b></p>')
check("<p>" in e and "<br>" in e and "<b>Max</b>" in e, "Auszeichnung bleibt", e)
e = mb.html_entschaerfen('<a href="https://firma.de">Web</a>')
check('href="https://firma.de"' in e and ">Web<" in e, "https-Link bleibt", e)
e = mb.html_entschaerfen('<a href="mailto:a@b.de">Mail</a>')
check("mailto:a@b.de" in e, "mailto-Link bleibt", e)
e = mb.html_entschaerfen('<img src="https://firma.de/logo.png" alt="Logo" width="120">')
check("logo.png" in e and 'alt="Logo"' in e and 'width="120"' in e, "Logo bleibt", e)
e = mb.html_entschaerfen('<img src="data:image/png;base64,iVBOR">')
check("data:image/png;base64" in e,
      "eingebettetes Logo bleibt (ohne data: gibt es kein Logo ohne fremden Host)", e)
e = mb.html_entschaerfen('<table><tr><td style="padding:2px">A</td></tr></table>')
check("<table>" in e and "<td" in e and "padding" in e, "einfache Tabelle bleibt", e)

# Was NICHT durch darf.
e = mb.html_entschaerfen('<p>ok</p><script>alert(1)</script>')
check("script" not in e.lower() and "alert" not in e,
      "script wird MIT INHALT verworfen", e)
e = mb.html_entschaerfen('<style>p{x:y}</style><p>ok</p>')
check("style>" not in e.lower() and "x:y" not in e, "style-Element ebenso", e)
e = mb.html_entschaerfen('<p onclick="boese()">ok</p>')
check("onclick" not in e.lower() and ">ok<" in e,
      "on*-Attribut faellt weg, der TEXT bleibt", e)
e = mb.html_entschaerfen('<img src="x" onerror="boese()">')
check("onerror" not in e.lower(), "onerror ebenso", e)
e = mb.html_entschaerfen('<a href="javascript:boese()">klick</a>')
check("javascript" not in e.lower() and "klick" in e,
      "javascript:-Ziel faellt weg, die Beschriftung bleibt", e)
e = mb.html_entschaerfen('<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>')
check("data:text/html" not in e.lower(), "data:text/html als href faellt weg", e)
e = mb.html_entschaerfen('<iframe src="https://boese.de"></iframe>Rest')
check("iframe" not in e.lower() and "Rest" in e, "iframe faellt weg", e)
e = mb.html_entschaerfen('<svg><script>boese()</script>Text</svg>Danach')
check("svg" not in e.lower() and "boese" not in e and "Danach" in e,
      "svg wird mit Inhalt verworfen (es kann Skripte tragen)", e)
e = mb.html_entschaerfen('<p style="background:url(javascript:boese())">x</p>')
check("javascript" not in e.lower(), "javascript in einem style-Attribut", e)
e = mb.html_entschaerfen('<p style="width:expression(boese())">x</p>')
check("expression" not in e.lower(), "CSS-expression()", e)
e = mb.html_entschaerfen('<p style="color:red">x</p>')
check("color:red" in e, "harmloses style bleibt", e)
e = mb.html_entschaerfen('<form><input name="pw"></form>Rest')
check("<form" not in e.lower() and "<input" not in e.lower() and "Rest" in e,
      "Formularfelder faellen weg – und der Text DAHINTER bleibt", e)
# ⚠ DIESE VIER PRUEFUNGEN HABEN EINEN ECHTEN FEHLER GEFUNDEN (2026-08-26):
# void-Elemente (`<meta>`, `<input>`, `<link>`, `<embed>`) bekommen NIE ein
# Ende-Tag. Standen sie in der Liste "mit Inhalt verwerfen", kehrte der
# Tiefenzaehler nie auf 0 zurueck und ALLES DAHINTER verschwand. Ein aus
# Outlook kopiertes Signatur-HTML beginnt typischerweise mit `<meta>` – die
# Anschrift waere also restlos weg gewesen, ohne jede Meldung.
e = mb.html_entschaerfen('<meta charset="utf-8"><p>Max Mustermann<br>Nexus AG</p>')
check("Max Mustermann" in e and "Nexus AG" in e,
      "ein fuehrendes <meta> frisst NICHT den Rest (Outlook-Signatur!)", e)
e = mb.html_entschaerfen('<link rel="stylesheet" href="x"><p>Anschrift</p>')
check("Anschrift" in e and "<link" not in e.lower(), "dasselbe fuer <link>", e)
e = mb.html_entschaerfen('<embed src="x"><p>Anschrift</p>')
check("Anschrift" in e and "embed" not in e.lower(), "dasselbe fuer <embed>", e)
e = mb.html_entschaerfen('<script/>Danach')
check("Danach" in e, "ein selbstschliessendes <script/> ebenso", e)
e = mb.html_entschaerfen('<!--[if mso]><b>x</b><![endif]-->Text')
check("if mso" not in e and "Text" in e, "Kommentare faellen weg", e)
# EIN UNBEKANNTES Tag: der Inhalt ist meist die Anschrift, das Tag Zierrat.
e = mb.html_entschaerfen('<marquee>Nexus AG</marquee>')
check("marquee" not in e.lower() and "Nexus AG" in e,
      "unbekanntes Tag faellt weg, sein INHALT bleibt", e)
# Kaputtes HTML darf keinen offenen Stapel hinterlassen.
e = mb.html_entschaerfen('<b>fett<i>beides')
check(e.count("</b>") == 1 and e.count("</i>") == 1,
      "nicht geschlossene Tags werden geschlossen", e)
e = mb.html_entschaerfen('<b><i>x</b></i>')
check(e.count("<b") == 1 and "</b>" in e, "falsch verschachteltes HTML kippt nicht", e)
e = mb.html_entschaerfen('<img src="javascript:1">')
check("<img" not in e, "ein Bild ohne brauchbares src wird ganz verworfen", e)
e = mb.html_entschaerfen('<a href="https://a.de" target="_blank">x</a>')
check("noopener" in e, "target=_blank bekommt rel=noopener", e)
check(mb.html_entschaerfen("") == "" and mb.html_entschaerfen("   ") == "",
      "leeres Fragment bleibt leer")
# Ein `<script` ohne Ende-Tag ist der Klassiker, an dem Regex-Loesungen scheitern.
e = mb.html_entschaerfen('<p>a</p><script>boese()')
check("boese" not in e, "nicht geschlossenes <script> ebenso", e)
# Nach der Entschaerfung darf NICHTS mehr uebrig sein, was ein Tag oeffnet und
# nicht auf der Liste steht. Das ist die Pruefung der REGEL statt einer Liste.
_bunt = ('<p>ok</p><script>x</script><foo bar=1>t</foo><svg/><object></object>'
         '<embed><link rel=x><meta><base href=x><applet></applet><noscript>n</noscript>')
e = mb.html_entschaerfen(_bunt)
_tags = set(t.lower() for t in re.findall(r"<\s*([a-zA-Z0-9]+)", e))
check(_tags <= set(mb._ERLAUBT), "nach der Entschaerfung nur erlaubte Tags", str(_tags))


# ═══════════════════════════════════════════════════════════════════════════
section("4. Signatur anhaengen")
# ═══════════════════════════════════════════════════════════════════════════
SIG = {"name": "Standard", "text": "Max Mustermann\nNexus AG", "html": ""}

t, h = mb.signatur_anhaengen("Danke!", SIG, "text")
check("Danke!" in t and "Max Mustermann" in t, "Text: Signatur haengt hinten", t)
check(h == "", "Text: kein HTML-Teil", h)
check("-- " in t, "Text: RFC-Trenner '-- ' steht davor", t)
check(t.index("Danke!") < t.index("Max Mustermann"),
      "Text: die Signatur steht NACH der Antwort")

t, h = mb.signatur_anhaengen("Danke!", SIG, "html")
check("<p>Danke!</p>" in h, "HTML: die Antwort wird umgesetzt", h)
check("Max Mustermann" in h and "<br>" in h,
      "HTML: die Textsignatur wird ebenfalls umgesetzt", h)
check("Max Mustermann" in t, "HTML: der Textteil traegt sie auch (multipart)", t)

SIG_HTML = {"name": "Mit Logo", "text": "Max Mustermann",
            "html": '<p><b>Max Mustermann</b><br><a href="https://n.de">n.de</a></p>'}
t, h = mb.signatur_anhaengen("Hallo", SIG_HTML, "html")
check("<b>Max Mustermann</b>" in h and "https://n.de" in h,
      "HTML: die HTML-Fassung gewinnt, wenn eine da ist", h)
check("Max Mustermann" in t, "HTML: der Textteil nimmt die TEXT-Fassung", t)

# Nur HTML hinterlegt, aber Text gesendet: die Signatur darf nicht verschwinden.
NUR_HTML = {"name": "x", "text": "", "html": "<p>Max<br>Nexus AG</p>"}
t, h = mb.signatur_anhaengen("Hallo", NUR_HTML, "text")
check("Max" in t and "Nexus AG" in t and "<p>" not in t,
      "Text-Antwort mit HTML-Signatur: sie wird umgesetzt, nicht weggelassen", t)

# Ein boeses HTML in der Signatur wird auch hier entschaerft - die Pruefung
# sitzt beim BAUEN des Rumpfes, nicht beim Speichern: sonst ginge ein
# Altbestand ungeprueft hinaus.
BOESE = {"name": "x", "text": "Max", "html": '<p>Max<script>boese()</script></p>'}
t, h = mb.signatur_anhaengen("Hallo", BOESE, "html")
check("boese" not in h and "script" not in h.lower(),
      "die Signatur-HTML wird beim Bauen entschaerft", h)

# Keine Signatur
t, h = mb.signatur_anhaengen("Hallo", None, "text")
check(t == "Hallo" and h == "", "ohne Signatur bleibt der Text unveraendert", t)
t, h = mb.signatur_anhaengen("Hallo", {"text": "", "html": ""}, "html")
check("<p>Hallo</p>" in h and "--" not in h,
      "leere Signatur: kein Trenner ohne Inhalt", h)

# Die Funktion ist REIN: kein Netz, keine Datei, kein Modell. Geprueft am
# Quelltext der Funktion selbst (nicht am Modul - dort steht die Begruendung).
_fn = _src.split("def signatur_anhaengen", 1)[1].split("\ndef ", 1)[0]
_fn_code = "\n".join(z for z in _fn.split("\n")
                     if not z.strip().startswith("#") and '"""' not in z)
for _boese in ("requests", "open(", "run_task", "provider", "llm"):
    check(_boese not in _fn_code,
          "signatur_anhaengen ruft nichts nach draussen: kein '%s'" % _boese)


# ═══════════════════════════════════════════════════════════════════════════
section("5. HTML → Text (Rueckfall im multipart)")
# ═══════════════════════════════════════════════════════════════════════════
t = mb.html_zu_text("<p>A</p><p>B</p>")
check("A" in t and "B" in t and "<" not in t, "Tags weg, Text da", t)
t = mb.html_zu_text("Zeile<br>Zwei")
check("\n" in t, "<br> wird ein Umbruch", repr(t))
t = mb.html_zu_text("<ul><li>Eins</li><li>Zwei</li></ul>")
check("- Eins" in t and "- Zwei" in t, "Listenpunkte werden lesbar", t)
t = mb.html_zu_text("Gr&uuml;&szlig;e")
check("Grüße" in t, "Entities werden aufgeloest", t)
t = mb.html_zu_text("<script>boese()</script>Text")
check("boese" not in t, "Skript-Inhalt kommt nicht in die Textfassung", t)


print(f"\n{'='*62}\n  {_ok} OK, {_fail} FAIL\n{'='*62}")
sys.exit(1 if _fail else 0)

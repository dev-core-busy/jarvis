"""Rumpf einer Antwort-Mail: Text, HTML und das Anhaengen der Signatur.

WARUM ES DIESES MODUL GIBT
--------------------------
Bis 2026-08-26 entstand jede Antwort aus dem Outlook-Add-in als **reiner
Text** – ``mail_client.antworten`` gab den Vorschlagstext unveraendert als
``body`` weiter, und Exchange legt einen ``str`` als ``BodyType=Text`` ab.
Gemeldet wurde genau das: "in dem Outlook-Add-In werden aktuell Entwuerfe im
Text Format erstellt."

Hier liegen die drei Dinge, die dafuer gebraucht werden, und zwar **ohne**
``exchangelib``, ``imaplib`` oder ``fastapi``: das Modul ist damit ohne
Postfach und ohne installierte Fremdmodule pruefbar (``tests/test_mail_body.py``).

⚠ RICH-TEXT (RTF) GIBT ES HIER NICHT, UND ZWAR NICHT AUS BEQUEMLICHKEIT.
Auf DEV an ``exchangelib`` 5.6.0 gemessen: ``BodyField.from_xml`` kennt genau
zwei Typen, ``{Body.body_type: Body, HTMLBody.body_type: HTMLBody}`` – also
``Text`` und ``HTML``. Auch das EWS-Schema selbst kennt in ``BodyType`` nur
``Best`` (nur lesend), ``HTML`` und ``Text``; einen RTF-Rumpf kann man ueber
EWS **nicht setzen**. Was Outlook "Rich-Text" nennt, ist ausserdem gar kein
RTF-Body, sondern **TNEF** (``winmail.dat``) – ein eigenes Containerformat,
das ueber IMAP/SMTP selbst zu erzeugen waere. Deshalb bietet die Oberflaeche
Rich-Text sichtbar, aber **abgeschaltet** an und nennt den Grund: die Frage
"warum fehlt das?" soll beantwortet sein, bevor sie entsteht.
"""

from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

# ── Formate ──────────────────────────────────────────────────────────────────
FORMAT_TEXT = "text"
FORMAT_HTML = "html"
FORMATE = (FORMAT_TEXT, FORMAT_HTML)


def norm_format(wert) -> str:
    """Ein Format aus Fremdeingabe – oder ``""`` fuer "nichts gewaehlt".

    **Unbekanntes wird NICHT geraten.** Ein Tippfehler im API-Aufruf soll auf
    die Vorgabe des Postfachs fallen (das ist eine Entscheidung, die jemand
    getroffen hat) und nicht auf einen Wert, den sich diese Funktion aussucht.
    ``"richtext"``/``"rtf"`` gelten ausdruecklich als unbekannt – siehe der
    Block im Modul-Docstring.
    """
    w = str(wert or "").strip().lower()
    return w if w in FORMATE else ""


# ── Text → HTML ──────────────────────────────────────────────────────────────
# Bewusst KEINE Markdown-Wiedergabe. Der Text im Fenster ist der Text, den ein
# Mensch gelesen und ggf. geaendert hat; wer daraus **fett** macht, aendert
# einen freigegebenen Text nachtraeglich. Ein Sternchen in "3*4" waere sonst
# Auszeichnung. Uebersetzt werden nur die Dinge, die in reinem Text KEINE
# Bedeutung haben und in HTML verlorengingen: Absaetze und Zeilenumbrueche.

def text_zu_html(text: str) -> str:
    """Reinen Text in sicheres HTML umsetzen (maskiert, Absaetze erhalten).

    Leerzeile = Absatz (``<p>``), einfacher Umbruch = ``<br>``. Fuehrende
    Leerzeichen werden zu geschuetzten, damit eine eingerueckte Aufzaehlung
    nicht zusammenfaellt – HTML frisst Folgeleerzeichen sonst weg.
    """
    roh = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not roh.strip():
        return ""
    absaetze = re.split(r"\n[ \t]*\n", roh)
    aus = []
    for a in absaetze:
        zeilen = []
        for z in a.split("\n"):
            m = _html.escape(z, quote=False)
            # Nur FUEHRENDE Leerzeichen schuetzen: mitten im Satz ist eine
            # Folge von Leerzeichen Tippfehler, am Zeilenanfang Absicht.
            fuehrend = len(z) - len(z.lstrip(" \t"))
            if fuehrend:
                m = "&nbsp;" * fuehrend + m.lstrip(" \t").replace("\t", "&nbsp;" * 4)
            zeilen.append(m)
        inhalt = "<br>".join(zeilen).strip()
        if inhalt:
            aus.append("<p>" + inhalt + "</p>")
    return "\n".join(aus)


def html_zu_text(html_text: str) -> str:
    """Grobe Textfassung eines HTML-Schnipsels – fuer den Alternativteil.

    Genau so grob wie noetig: eine Mail wird als ``multipart/alternative``
    verschickt, der Textteil ist der Rueckfall fuer Programme ohne HTML. Er
    muss lesbar sein, nicht schoen.
    """
    s = str(html_text or "")
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|tr|li|h[1-6])\s*>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ── HTML entschaerfen ────────────────────────────────────────────────────────
# WARUM MIT EINEM PARSER UND NICHT MIT REGEX: eine Signatur ist Text, den der
# Postfach-Inhaber selbst hinterlegt – aber sie geht in eine E-Mail hinaus, und
# HTML aus einem Freitextfeld ungeprueft zu verschicken ist genau die Klasse
# Fehler, die man einmal macht. Ein `re.sub("<script.*?>")` uebersieht
# `<img onerror=...>`, `<svg><script>`, `javascript:`-Ziele und ein nicht
# geschlossenes `<script`. Deshalb wird das Fragment ZERLEGT und aus einer
# ERLAUBNISLISTE neu aufgebaut: was nicht ausdruecklich vorgesehen ist, kommt
# nicht durch - auch nicht etwas, das es heute noch nicht gibt.

# Erlaubt ist, was eine Signatur braucht: Text, Auszeichnung, Links, Logo,
# einfache Tabellen (die klassische Signatur-Anordnung).
_ERLAUBT = {
    "p", "br", "div", "span", "b", "strong", "i", "em", "u", "s", "small",
    "a", "img", "hr", "ul", "ol", "li", "table", "thead", "tbody", "tr",
    "td", "th", "h1", "h2", "h3", "h4", "font", "sub", "sup", "blockquote",
}
# DREI Klassen, und die Unterscheidung ist keine Feinheit – die erste Fassung
# hatte sie nicht und verlor damit Inhalt (vom Test gefunden):
#
#   _TOETEN     – Tag UND Inhalt weg. Nur Traeger von Code oder Metadaten;
#                 alle haben ein Ende-Tag.
#   _LEER_WEG   – Tag weg, KEINE Inhaltsbuchhaltung. Das sind void-Elemente:
#                 sie bekommen NIE ein Ende-Tag. Stehen sie in _TOETEN, kehrt
#                 der Tiefenzaehler nie auf 0 zurueck und ALLES DAHINTER
#                 verschwindet. Genau das passierte mit `<meta>`/`<input>` –
#                 und ein aus Outlook kopiertes Signatur-HTML beginnt
#                 typischerweise mit `<meta>`, die Anschrift waere also
#                 vollstaendig weg gewesen.
#   sonst       – Tag weg, INHALT BLEIBT. Ein unbekanntes Tag ist meist
#                 Zierrat, sein Inhalt aber die Anschrift.
_TOETEN = {"script", "style", "iframe", "object", "svg", "math",
           "template", "noscript", "frameset", "applet", "head", "title"}
_LEER_WEG = {"input", "link", "meta", "base", "embed", "frame", "source",
             "track", "param", "area", "col", "wbr"}
_LEER = {"br", "img", "hr"}     # erlaubt, aber ohne Ende-Tag

_ATTR_ERLAUBT = {
    "a": {"href", "title", "target", "rel", "style"},
    "img": {"src", "alt", "width", "height", "style", "border"},
    "td": {"style", "align", "valign", "width", "colspan", "rowspan"},
    "th": {"style", "align", "valign", "width", "colspan", "rowspan"},
    "table": {"style", "align", "width", "border", "cellpadding", "cellspacing"},
    "tr": {"style", "align", "valign"},
    "font": {"color", "size", "face"},
}
_ATTR_ALLGEMEIN = {"style", "align", "dir", "title"}

# Ziele, die ein Link tragen darf. `javascript:` und `vbscript:` sind der
# klassische Weg; `data:` in einem href ebenso (data:text/html).
_HREF_OK = re.compile(r"^(?:https?:|mailto:|tel:|#|/|\./|\.\./)", re.I)
# Ein Bild darf zusaetzlich eingebettet sein: ohne `data:image` gibt es kein
# Logo ohne fremden Host, und externe Bilder blockt Outlook oft von selbst.
_SRC_OK = re.compile(r"^(?:https?:|cid:|data:image/(?:png|jpe?g|gif|webp);base64,)", re.I)
# In einem style-Attribut gefaehrlich: alles, was Code nachladen oder
# ausfuehren kann.
_STYLE_BOESE = re.compile(r"(?i)(expression\s*\(|javascript:|vbscript:|@import|behavior\s*:|url\s*\(\s*['\"]?\s*(?:javascript|data:text))")


class _Entschaerfer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.aus: list[str] = []
        self.stapel: list[str] = []
        self.tot = 0            # Verschachtelungstiefe innerhalb eines _TOETEN

    # -- Attribute ------------------------------------------------------
    def _attrs(self, tag: str, attrs) -> str | None:
        """Gefilterte Attribute – oder ``None``, wenn das Tag ganz wegfaellt.

        ``None`` gibt es nur fuer ``<img>`` ohne brauchbares ``src``: ein Bild
        ohne Quelle ist nichts, es hinterliesse aber in Outlook einen Platzhalter
        mit rotem Kreuz und saehe nach einem Fehler in der Signatur aus.
        """
        erlaubt = _ATTR_ERLAUBT.get(tag, set()) | _ATTR_ALLGEMEIN
        teile, hat_src = [], False
        for name, wert in attrs:
            n = (name or "").lower()
            # `on*` faellt schon ueber die Erlaubnisliste heraus; die
            # ausdrueckliche Zeile steht hier, damit sie auch dann greift, wenn
            # jemand die Liste erweitert.
            if n.startswith("on") or n not in erlaubt:
                continue
            w = "" if wert is None else str(wert)
            if n == "href" and not _HREF_OK.match(w.strip()):
                continue
            if n == "src":
                if not _SRC_OK.match(w.strip()):
                    continue
                hat_src = True
            if n == "style" and _STYLE_BOESE.search(w):
                continue
            teile.append(' %s="%s"' % (n, _html.escape(w, quote=True)))
        if tag == "a" and any(t.startswith(' target=') for t in teile) \
                and not any(t.startswith(' rel=') for t in teile):
            teile.append(' rel="noopener noreferrer"')
        if tag == "img" and not hat_src:
            return None
        return "".join(teile)

    # -- Ereignisse -----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        t = (tag or "").lower()
        if t in _TOETEN:
            self.tot += 1
            return
        if t in _LEER_WEG:
            return          # void-Element: Tag weg, Zaehler NICHT anfassen
        if self.tot or t not in _ERLAUBT:
            return          # Tag weg, Inhalt bleibt
        a = self._attrs(t, attrs)
        if a is None:
            return
        self.aus.append("<" + t + a + ">")
        if t not in _LEER:
            self.stapel.append(t)

    def handle_startendtag(self, tag, attrs):
        t = (tag or "").lower()
        # `<script/>` und `<svg/>` schliessen sich selbst – hier darf der
        # Zaehler NICHT steigen, sonst frisst er den Rest des Fragments.
        if t in _TOETEN or t in _LEER_WEG or self.tot or t not in _ERLAUBT:
            return
        a = self._attrs(t, attrs)
        if a is None:
            return
        self.aus.append("<" + t + a + ">")
        if t not in _LEER:
            self.aus.append("</" + t + ">")

    def handle_endtag(self, tag):
        t = (tag or "").lower()
        if t in _TOETEN:
            self.tot = max(0, self.tot - 1)
            return
        if t in _LEER_WEG:
            return          # ein `</input>` gibt es nicht, aber es kommt vor
        if self.tot or t not in _ERLAUBT or t in _LEER:
            return
        if t in self.stapel:
            # Bis zu diesem Tag schliessen: falsch verschachteltes HTML soll
            # keinen offenen Stapel hinterlassen.
            while self.stapel:
                offen = self.stapel.pop()
                self.aus.append("</" + offen + ">")
                if offen == t:
                    break

    def handle_data(self, data):
        if self.tot:
            return
        self.aus.append(_html.escape(data or "", quote=False))

    def handle_comment(self, data):
        return          # Kommentare fallen weg (bedingte Outlook-Kommentare!)

    def handle_decl(self, decl):
        return

    def unknown_decl(self, data):
        return

    def handle_pi(self, data):
        return

    def ergebnis(self) -> str:
        while self.stapel:
            self.aus.append("</" + self.stapel.pop() + ">")
        return "".join(self.aus)


def html_entschaerfen(fragment: str) -> str:
    """HTML aus einem Freitextfeld auf eine Erlaubnisliste zurechtschneiden.

    Rueckgabe ist ein **Fragment** (kein vollstaendiges Dokument): es wird in
    den Rumpf einer Mail gesetzt. FAIL-CLOSED – kippt der Parser, kommt
    nichts durch. Ein halb entschaerftes Fragment waere schlimmer als keines.
    """
    if not (fragment or "").strip():
        return ""
    try:
        p = _Entschaerfer()
        p.feed(str(fragment))
        p.close()
        return p.ergebnis().strip()
    except Exception as e:  # noqa: BLE001
        print("[Mail] HTML-Entschaerfung fehlgeschlagen, Fragment verworfen: %s" % e,
              flush=True)
        return ""


# ── Signatur anhaengen ───────────────────────────────────────────────────────
# ⚠ DIES IST DER KERN DER ZUSAGE: die Signatur wird DETERMINISTISCH hinter den
# freigegebenen Text gesetzt – sie geht NIE durch ein Sprachmodell. Eine
# Signatur enthaelt Pflichtangaben (Rechtsform, Registergericht,
# Geschaeftsfuehrung); ein Modell, das sie "mitschreibt", formuliert sie um,
# und niemand liest gegen. Aus demselben Grund steht sie nicht im Textfeld der
# Vorschau: was dort steht, kann bearbeitet werden.
_TRENNER_TEXT = "-- "           # RFC 3676 Abschnitt 4.3
_TRENNER_HTML = '<p>--&nbsp;</p>'


def signatur_anhaengen(text: str, sig: dict | None, fmt: str) -> tuple[str, str]:
    """Rumpf bauen. Rueckgabe ``(text, html)``; ``html`` ist ``""`` bei Text.

    ``sig`` ist ein Signatur-Eintrag (``{"text","html",...}``) oder ``None``.
    Fehlt bei einer HTML-Antwort die HTML-Fassung, wird die TEXT-Fassung
    umgesetzt – eine Signatur, die je nach Format verschwindet, waere die
    schlechtere Ueberraschung.
    """
    grund = (text or "").rstrip()
    s_text = str((sig or {}).get("text") or "").strip()
    s_html = str((sig or {}).get("html") or "").strip()
    if fmt == FORMAT_HTML:
        html_teile = [text_zu_html(grund)]
        text_teile = [grund]
        if s_html:
            sicher = html_entschaerfen(s_html)
            if sicher:
                html_teile.append(_TRENNER_HTML)
                html_teile.append(sicher)
                # Der Textteil des multipart bekommt die Textfassung, sonst
                # (falls keine hinterlegt ist) eine aus dem HTML abgeleitete.
                text_teile.append("\n" + _TRENNER_TEXT + "\n" + (s_text or html_zu_text(sicher)))
        elif s_text:
            html_teile.append(_TRENNER_HTML)
            html_teile.append(text_zu_html(s_text))
            text_teile.append("\n" + _TRENNER_TEXT + "\n" + s_text)
        return ("\n".join(text_teile), "\n".join([h for h in html_teile if h]))
    # Reiner Text
    if s_text:
        return (grund + "\n\n" + _TRENNER_TEXT + "\n" + s_text, "")
    if s_html:
        # Nur eine HTML-Fassung hinterlegt, gesendet wird Text: daraus eine
        # Textfassung machen, statt die Signatur weglassen.
        abgeleitet = html_zu_text(html_entschaerfen(s_html))
        if abgeleitet:
            return (grund + "\n\n" + _TRENNER_TEXT + "\n" + abgeleitet, "")
    return (grund, "")

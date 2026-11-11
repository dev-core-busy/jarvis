"""Schema-Graph: Stream-Parser fuer SQL-DDL, dazu YAML-Objektexporte.

YAML (seit 2026-11-07, Abschnitt "YAML" unten) liest PyYAML – das einzige
Fremdpaket, und nur fuer .yaml/.yml; der SQL-Weg bleibt ohne.

Ziel: ein Schema-Bestand von vielen tausend Dateien und zweistelligen
Gigabyte. Bei dieser Groesse ist "Datei lesen, an ';' teilen" keine Option –
eine einzelne Datei kann mehrere GB tragen, und der weit ueberwiegende Teil
davon sind erfahrungsgemaess DATEN (INSERT, COPY ... FROM stdin), nicht
Struktur. Der Parser arbeitet deshalb in zwei Stufen:

1. ``anweisungen(datei)`` – ein Zustandsautomat ueber Bloecke (``BLOCK``
   Bytes). Er kennt Zeichenketten ('..', "..", `..`, [..], $tag$..$tag$),
   Kommentare (--, /* */) und Trenner (``;`` sowie ``GO`` auf eigener Zeile
   fuer T-SQL). Eine Anweisung, deren Kopf KEINE Struktur traegt, wird nicht
   gepuffert, sondern nur bis zu ihrem Ende ueberlesen – sonst laege ein
   INSERT ueber 2 GB komplett im Speicher. Nach ``COPY ... FROM stdin`` folgt
   ein Datenblock bis ``\\.``; der wird zeilenweise verworfen (dort stehen
   Apostrophe und Semikola ohne SQL-Bedeutung).
2. ``zerlege(anweisung)`` – macht aus EINER Struktur-Anweisung Fakten:
   Tabellen/Sichten mit Spalten, Primaerschluessel, Fremdschluessel (inline,
   als Tabellen-Constraint und per ALTER TABLE), Kommentare (COMMENT ON,
   MySQL-``COMMENT '..'``, T-SQL ``sp_addextendedproperty``) und die von einer
   Sicht benutzten Tabellen.

Dieses Modul importiert NICHTS aus ``backend`` – es laeuft in eigenen
Prozessen (spawn), und ein Import von ``backend.config`` dort wuerde die
Live-``settings.json`` anfassen.

Unbekanntes wird uebersprungen und GEZAEHLT, nicht geraten: eine Datei ohne
erkennbare Struktur liefert ``tabellen == []`` und eine Statistik, die das
sagt.
"""
from __future__ import annotations

import codecs
import re

# Fassung dessen, was der Parser aus einer Datei herausholt. HOCHZAEHLEN, wenn
# sich das aendert (neues Format, neue Fakten): die Erfassung ist inkrementell
# und liest sonst nur neue und geaenderte Dateien – gemessen auf DEV
# 2026-11-07: 8431 YAML-Dateien, mit dem Parser OHNE YAML erfasst, waeren nach
# dem Einbau des YAML-Wegs nie wieder gelesen worden (Graph blieb leer).
# 1 = SQL-DDL, 2 = dazu YAML-Objektexporte, 3 = dazu Begleitdokumente,
# 4 = dazu Herkunft der Sichtspalten (Join-Pruefung ueber Sichten),
# 5 = dazu Texterkennung in Bildern der Begleitdokumente,
# 6 = dazu UTF-16-Dateien (Skriptexport des SQL Server Management Studio).
FASSUNG = 6

BLOCK = 4 * 1024 * 1024
# Obergrenze fuer EINE Struktur-Anweisung. Ein CREATE TABLE ueber 64 MB gibt
# es praktisch nicht; wird sie erreicht, ist der Trenner verloren gegangen
# (z. B. ein nicht geschlossener Kommentar) und der Rest der Datei waere eine
# einzige Anweisung. Dann verwerfen und zaehlen statt den Speicher zu fuellen.
MAX_ANWEISUNG = 64 * 1024 * 1024

# Koepfe, die Struktur tragen. Alles andere wird nur ueberlesen.
_STRUKTUR_KOPF = re.compile(
    r"\s*(?:CREATE\b|ALTER\s+TABLE\b|COMMENT\s+ON\b|"
    r"(?:EXEC(?:UTE)?\s+)?(?:\w+\.)*sp_addextendedproperty\b)",
    re.I)
# Koepfe, die sicher KEINE Struktur tragen – ab hier wird nicht mehr gepuffert.
_DATEN_KOPF = re.compile(
    r"\s*(?:INSERT|COPY|UPDATE|DELETE|MERGE|REPLACE|SET|SELECT|GRANT|REVOKE|"
    r"USE|BEGIN|COMMIT|END|DECLARE|PRINT|IF|LOCK|UNLOCK|ANALYZE|VACUUM|"
    r"TRUNCATE|DROP|CALL|VALUES)\b",
    re.I)
_COPY_STDIN = re.compile(r"\s*COPY\b[^;]*\bFROM\s+stdin\b", re.I | re.S)

# Lexer fuer den Trenner-Automaten. Reihenfolge ist Bedeutung: zuerst die
# vollstaendigen Konstrukte, dann die UNVOLLSTAENDIGEN am Fensterende (die
# halten den Rest fuer den naechsten Block zurueck), dann die Trenner.
# Zeichenketten in der "unrolled loop"-Form ('[^']*(?:''[^']*)*'), weil die
# naive Alternation je Zeichen bei Datenzeilen ueber Megabytes messbar
# langsamer ist. Dollar-Quoting nur, wenn das ``$`` kein Teil eines Namens ist
# – sonst oeffnete ein Name mit ZWEI ``$`` (Oracle erlaubt ``PAY$RATE$HIST``)
# bei ``$RATE$`` eine "Zeichenkette" bis Dateiende. Ein einzelnes ``$`` wie in
# ``V$SESSION`` ist ohne zweites ``$`` ohnehin harmlos (gemessen).
_LEX = re.compile(
    r"""
      (?P<kom>--[^\n]*\n|/\*.*?\*/)
    | (?P<str>'[^']*(?:''[^']*)*'|"[^"]*(?:""[^"]*)*"|`[^`]*`
        |(?<![\w$])\$\$.*?\$\$|(?<![\w$])\$(?P<tag>[A-Za-z_]\w*)\$.*?\$(?P=tag)\$)
    | (?P<offen>--[^\n]*\Z|/\*.*\Z|'[^']*(?:''[^']*)*\Z|"[^"]*(?:""[^"]*)*\Z|`[^`]*\Z
        |(?<![\w$])\$(?:[A-Za-z_]\w*)?\$.*\Z|(?<![\w$])\$[A-Za-z_]\w*\Z)
    | (?P<semi>;)
    | (?P<go>^[ \t]*GO[ \t]*(?:\r?\n|\Z))
    """,
    re.X | re.S | re.M | re.I)
# Schnellweg fuer den Ueberlese-Modus: verschluckt in EINEM Aufruf alles, was
# sicher keinen Trenner enthaelt – Klartext, VOLLSTAENDIGE Zeichenketten und
# Kommentare. Er haelt an allem anderen an (``;``, ``$``, eine moegliche
# GO-Zeile, ein unvollstaendiges Konstrukt am Fensterende), und dort uebernimmt
# der Lexer. Ohne ihn kostete jede Zeichenkette einer INSERT-Zeile eine
# Python-Iteration (Profil: 1,2 Mio. Aufrufe auf 40 MB). Possessiv (``*+``),
# damit ein Abbruch nicht zurueckverfolgt (Python >= 3.11).
_UEBERLESEN = re.compile(
    r"""(?:[^'"`;\-/$\n]++|\n(?![ \t]*GO\b)|'[^']*+(?:''[^']*+)*+'|"[^"]*+(?:""[^"]*+)*+"
       |`[^`]*+`|--[^\n]*+\n(?![ \t]*GO\b)|/\*.*?\*/|-(?!-)|/(?!\*))*+""",
    re.X | re.S | re.I)
_COPY_ENDE = re.compile(r"(?m)^\\\.[ \t]*\r?(?:\n|\Z)")
# Eine vollstaendige GO-Zeile AB der Suchposition (der Aufrufer prueft, dass
# davor ein Zeilenumbruch steht).
_GO_ZEILE = re.compile(r"[ \t]*GO[ \t]*\r?\n", re.I)


# So viele Bytes vom Dateianfang entscheiden ueber die Kodierung.
_KODIERUNG_PROBE = 4096


def kodierung(pfad) -> str:
    """Kodierung einer Textdatei: ``utf-16`` / ``utf-8-sig`` nach der Marke am
    Dateianfang, ``utf-16-le`` / ``utf-16-be`` ohne Marke am Muster der
    Nullbytes, sonst ``utf-8``.

    ⚠ WARUM (ECHT 2026-11-11): das SQL Server Management Studio speichert
    seinen Skriptexport als UTF-16. Fest als UTF-8 gelesen stand zwischen allen
    Buchstaben ein Nullzeichen – kein ``CREATE`` und keine ``GO``-Zeile wurde
    erkannt, die Datei galt mit 1796 Anweisungen und 0 Strukturen als "ok".
    """
    try:
        with open(pfad, "rb") as f:
            kopf = f.read(_KODIERUNG_PROBE)
    except OSError:
        return "utf-8"
    if kopf.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if kopf.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    # Ohne Marke: in UTF-16 ist bei lateinischem Text jedes ZWEITE Byte null,
    # und zwar immer an derselben Stelle des Paars. In UTF-8 kommt ein Nullbyte
    # in einer Textdatei gar nicht vor.
    paare = len(kopf) // 2
    if paare >= 8:
        gerade = kopf[0:2 * paare:2].count(0)
        ungerade = kopf[1:2 * paare:2].count(0)
        if ungerade * 2 >= paare and gerade * 20 <= paare:
            return "utf-16-le"
        if gerade * 2 >= paare and ungerade * 20 <= paare:
            return "utf-16-be"
    return "utf-8"


class Statistik(dict):
    """Zaehler eines Laufs ueber eine Datei (dict, damit es pickelbar bleibt)."""

    def __init__(self):
        super().__init__(bytes=0, anweisungen=0, struktur=0, uebersprungen=0,
                         copy_bloecke=0, zu_lang=0, unverstanden=0)


class _Laufend:
    """Die gerade gelesene Anweisung.

    ``modus``: None = Kopf noch unbekannt, "s" = Struktur (wird gepuffert),
    "x" = ueberlesen (wird NICHT gepuffert). ``kopf`` haelt unabhaengig davon
    die ersten Zeichen fest – daran wird ``COPY … FROM stdin`` erkannt, auch
    wenn die Anweisung selbst verworfen wird.
    """
    KOPF = 400
    # Laengster Struktur-Kopf ist "EXECUTE <schema>.sp_addextendedproperty".
    UNBEKANNT_AB = 80

    def __init__(self):
        self.teile: list[str] = []
        self.laenge = 0
        self.modus = None
        self.kopf = ""
        self.zu_lang = False

    def dazu(self, teil: str, kommentar: bool = False) -> None:
        if not teil:
            return
        if len(self.kopf) < self.KOPF:
            # Ein VOLLSTAENDIGER Kommentar zaehlt im Kopf als ein Leerzeichen:
            # sonst fuellte ein langer Vorspann (Lizenztext, Kopf eines
            # Exports) den Kopf allein, die Anweisung dahinter kam nie in
            # Sicht und galt als "unbekannt" – ihr CREATE ging verloren.
            # Fuehrender Leerraum zaehlt gar nicht (viele kurze Kommentare
            # hintereinander fuellten ihn sonst genauso).
            stueck = " " if kommentar else teil
            if not self.kopf:
                stueck = stueck.lstrip()
            self.kopf += stueck[:self.KOPF - len(self.kopf)]
        if self.modus == "x":
            return
        self.teile.append(teil)
        self.laenge += len(teil)
        if self.modus is None:
            self._kopf_entscheiden()
        if self.modus == "s" and self.laenge > MAX_ANWEISUNG:
            self.zu_lang = True
            self.modus, self.teile, self.laenge = "x", [], 0

    def _kopf_entscheiden(self) -> None:
        k = _ohne_kommentare(self.kopf).lstrip()
        if not k:
            return
        if _STRUKTUR_KOPF.match(k):
            self.modus = "s"
        elif _DATEN_KOPF.match(k) or len(k) >= self.UNBEKANNT_AB:
            # Datenanweisung – oder ein unbekannter Kopf, der lang genug ist,
            # dass kein Struktur-Kopf mehr daraus werden kann. NICHT schon nach
            # dem ersten Wort entscheiden: an einer Blockgrenze steht sonst
            # "ALTER " ohne "TABLE" da, und die Anweisung waere verloren
            # (gemessen mit 7-Byte-Bloecken).
            self.modus, self.teile, self.laenge = "x", [], 0

    def text(self) -> str:
        return "".join(self.teile)

    def ist_copy_stdin(self) -> bool:
        return bool(_COPY_STDIN.match(_ohne_kommentare(self.kopf)))


def anweisungen(pfad, stat: Statistik | None = None, block: int = BLOCK):
    """Liefert die STRUKTUR-Anweisungen einer Datei als Text (ohne Trenner).

    Kommentare bleiben im Text stehen (``zerlege`` entfernt sie selbst); fuer
    die Trennung werden sie aber erkannt (ein ``;`` im Kommentar trennt nicht).
    """
    stat = stat if stat is not None else Statistik()
    dec = codecs.getincrementaldecoder(kodierung(pfad))(errors="replace")
    puf = ""
    anw = _Laufend()
    im_copy = False

    def abschliessen(a: _Laufend):
        stat["anweisungen"] += 1
        if a.zu_lang:
            stat["zu_lang"] += 1
            return None
        if a.modus == "s":
            stat["struktur"] += 1
            return a.text()
        if a.modus == "x":
            stat["uebersprungen"] += 1
        elif a.kopf.strip():
            stat["unverstanden"] += 1
        else:
            # Nur Leerraum/Kommentar: keine Anweisung (Kommentare stehen im
            # Kopf nur als Leerzeichen, siehe ``_Laufend.dazu``).
            stat["anweisungen"] -= 1
        return None

    # ``start``: ab hier ist ``puf`` noch nicht verarbeitet. Das Zeichen davor
    # bleibt als KONTEXT im Puffer: ``^`` (GO-Zeile) und der Lookbehind des
    # Dollar-Quotings schauen ein Zeichen zurueck, und ohne Kontext gaelte
    # jeder Pufferanfang als Zeilenanfang.
    start = 0
    with open(pfad, "rb") as f:
        ende = False
        while not ende:
            roh = f.read(block)
            ende = not roh
            stat["bytes"] += len(roh)
            puf += dec.decode(roh, final=ende)
            # Fenster, das in diesem Durchgang sicher verarbeitet werden kann:
            # bis zum letzten Zeilenende; ohne Zeilenende (eine Datenzeile ueber
            # GB hat keins) bis kurz vor das Pufferende, aber NIE hinter einem
            # Zeichen, das ein Zwei-Zeichen-Konstrukt beginnt – "-" | "-" an der
            # Grenze machte aus einem Kommentar Code und aus dessen ";" einen
            # Trenner (gemessen mit 1-, 2- und 5-Byte-Bloecken).
            if ende:
                grenze = len(puf)
            else:
                nl = puf.rfind("\n", start)
                if nl >= 0:
                    grenze = nl + 1
                else:
                    grenze = max(start, len(puf) - 8)
                    while grenze > start and puf[grenze - 1] in "-/*$":
                        grenze -= 1
            pos = start
            while pos < grenze:
                if im_copy:
                    m = _COPY_ENDE.search(puf, pos, grenze)
                    if not m:
                        pos = grenze
                        break
                    pos = m.end()
                    im_copy = False
                    continue
                if anw.modus == "x":
                    # ⚠ Der Schnellweg erkennt eine GO-Zeile nur am
                    # Zeilenumbruch DAVOR. Steht er schon hinter dem Umbruch
                    # (Fensteranfang: der Umbruch war das Ende des vorigen
                    # Fensters; oder direkt hinter einem Zeilenkommentar),
                    # verschluckte er "GO" als Klartext – und die folgende
                    # Anweisung (im Skriptexport: das CREATE hinter
                    # "SET QUOTED_IDENTIFIER ON / GO") ging in der ueberlesenen
                    # auf. Dann entscheidet der Lexer.
                    if not (pos > 0 and puf[pos - 1] == "\n" and _GO_ZEILE.match(puf, pos, grenze)):
                        sm = _UEBERLESEN.match(puf, pos, grenze)
                        if sm.end() > pos:
                            # Ueber ``dazu`` und nicht an ihm vorbei: die Zusage
                            # "im Modus x wird nicht gepuffert" steht dann an EINER
                            # Stelle (zwei Schranken fuer dieselbe Frage machten
                            # jede Gegenprobe darauf stumm – gemessen).
                            anw.dazu(puf[pos:sm.end()])
                            pos = sm.end()
                            if pos >= grenze:
                                break
                m = _LEX.search(puf, pos, grenze)
                if m is None:
                    anw.dazu(puf[pos:grenze])
                    pos = grenze
                    break
                art = m.lastgroup
                if art == "offen" and not ende:
                    anw.dazu(puf[pos:m.start()])
                    pos = m.start()
                    break
                if art in ("kom", "str", "offen"):
                    anw.dazu(puf[pos:m.start()])
                    anw.dazu(puf[m.start():m.end()], kommentar=art == "kom")
                    pos = m.end()
                    continue
                # Trenner (; oder GO)
                anw.dazu(puf[pos:m.start()])
                text = abschliessen(anw)
                if text is not None:
                    yield text
                if anw.modus == "x" and anw.ist_copy_stdin():
                    im_copy = True
                    stat["copy_bloecke"] += 1
                anw = _Laufend()
                pos = m.end()
            if pos > 0:
                puf = puf[pos - 1:]
                start = 1
            else:
                start = 0
            if len(puf) > 2 * MAX_ANWEISUNG:
                # Ein offenes Konstrukt ueber 128 MB: der Trenner ist verloren,
                # der Rest der Datei ist nicht sicher zu lesen.
                raise ValueError("nicht geschlossene Zeichenkette/Kommentar ueber "
                                 f"{2 * MAX_ANWEISUNG // (1024 * 1024)} MB")
        if len(puf) > start:
            anw.dazu(puf[start:])
        text = abschliessen(anw)
        if text is not None:
            yield text


# ─── Stufe 2: eine Struktur-Anweisung zerlegen ──────────────────────────────

_STR_ODER_KOM = re.compile(
    r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]\n]*\])|--[^\n]*|/\*.*?\*/", re.S)


def _ohne_kommentare(text: str) -> str:
    """Entfernt Kommentare, laesst Zeichenketten und Bezeichner stehen."""
    return _STR_ODER_KOM.sub(lambda m: m.group(1) if m.group(1) else " ", text)


# Bezeichner: "x", `x`, [x] oder blank; mehrteilig mit Punkt.
_ID1 = r'(?:"(?:[^"]|"")+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_À-￿#@$][\w$#@À-￿]*)'
_ID = rf"{_ID1}(?:\s*\.\s*{_ID1}){{0,3}}"
_ID_RE = re.compile(_ID)


def bezeichner(roh: str) -> str:
    """Der Bezeichner AM ANFANG von ``roh`` ohne Anfuehrungszeichen, Punktteile
    mit '.' verbunden. Was dahinter steht (``ASC``, ein Typ), gehoert nicht dazu.
    """
    m = _ID_RE.match((roh or "").strip())
    if not m:
        return ""
    teile = re.findall(_ID1, m.group(0))
    out = []
    for t in teile:
        if t[0] == '"' and t[-1] == '"':
            t = t[1:-1].replace('""', '"')
        elif t[0] in "`[" and t[-1] in "`]":
            t = t[1:-1]
        out.append(t)
    return ".".join(out)


def _zeichenkette(roh: str) -> str:
    """'abc''d' -> abc'd ; N'..' und E'..' werden ebenfalls verstanden."""
    s = (roh or "").strip()
    if s[:1] in "NnEe" and s[1:2] == "'":
        s = s[1:]
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


def _klammer_ende(text: str, start: int) -> int:
    """Index der zur Klammer an ``start`` passenden schliessenden Klammer (-1)."""
    tiefe = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            j = text.find(c, i + 1)
            while j != -1 and j + 1 < n and text[j + 1] == c and c != "`":
                j = text.find(c, j + 2)
            if j == -1:
                return -1
            i = j + 1
            continue
        if c == "[":
            j = text.find("]", i + 1)
            # Nur ein Bezeichner in eckigen Klammern (T-SQL) – ein Array-Typ
            # wie int[] hat keinen Inhalt; beides ist mit find abgedeckt.
            i = (j + 1) if j != -1 else i + 1
            continue
        if c == "(":
            tiefe += 1
        elif c == ")":
            tiefe -= 1
            if tiefe == 0:
                return i
        i += 1
    return -1


def _teile_oben(text: str) -> list[str]:
    """Teilt an Kommata der obersten Klammerebene (Zeichenketten beachtet)."""
    teile, tiefe, start, i, n = [], 0, 0, 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            j = text.find(c, i + 1)
            while j != -1 and j + 1 < n and text[j + 1] == c and c != "`":
                j = text.find(c, j + 2)
            i = (j + 1) if j != -1 else n
            continue
        if c == "[":
            j = text.find("]", i + 1)
            i = (j + 1) if j != -1 else i + 1
            continue
        if c == "(":
            tiefe += 1
        elif c == ")":
            tiefe -= 1
        elif c == "," and tiefe == 0:
            teile.append(text[start:i])
            start = i + 1
        i += 1
    teile.append(text[start:])
    return [t.strip() for t in teile if t.strip()]


def _spaltenliste(roh: str) -> list[str]:
    return [bezeichner(t) for t in _teile_oben(roh) if bezeichner(t)]


_CREATE_TABLE = re.compile(
    rf"CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:GLOBAL|LOCAL|PRIVATE)\s+)?"
    rf"(?:(?:TEMPORARY|TEMP|UNLOGGED|VOLATILE|MULTISET|SET|COLUMN|ROW|EXTERNAL|TRANSIENT|"
    rf"VIRTUAL|FOREIGN|SHARDED|DUPLICATED|IMMUTABLE|BLOCKCHAIN)\s+)*"
    rf"TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_ID})", re.I)
_CREATE_VIEW = re.compile(
    rf"CREATE\s+(?:OR\s+(?:REPLACE|ALTER)\s+)?(?:(?:FORCE|NOFORCE|EDITIONABLE|NONEDITIONABLE|"
    rf"SECURE|RECURSIVE|TEMP|TEMPORARY|MATERIALIZED|ALGORITHM\s*=\s*\w+|"
    rf"DEFINER\s*=\s*\S+|SQL\s+SECURITY\s+\w+)\s+)*"
    rf"VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_ID})", re.I)
_ALTER_TABLE = re.compile(
    rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?P<name>{_ID})", re.I)
_COMMENT_ON = re.compile(
    rf"COMMENT\s+ON\s+(?P<art>TABLE|COLUMN|VIEW|MATERIALIZED\s+VIEW)\s+(?P<ziel>{_ID})"
    rf"\s+IS\s+(?P<text>[NnEe]?'(?:[^']|'')*'|NULL)", re.I | re.S)
_EXT_PROP = re.compile(r"sp_addextendedproperty\b(?P<args>.*)", re.I | re.S)

_FK_RE = re.compile(
    rf"FOREIGN\s+KEY\s*\((?P<von>[^)]*)\)\s*REFERENCES\s+(?P<ziel>{_ID})\s*(?:\((?P<nach>[^)]*)\))?",
    re.I)
_PK_RE = re.compile(r"PRIMARY\s+KEY\s*(?:CLUSTERED\s+|NONCLUSTERED\s+)?\((?P<sp>[^)]*)\)", re.I)
_INLINE_REF = re.compile(rf"\bREFERENCES\s+(?P<ziel>{_ID})\s*(?:\((?P<nach>[^)]*)\))?", re.I)
_INLINE_KOM = re.compile(r"\bCOMMENT\s+(?:=\s*)?(?P<t>[NnEe]?'(?:[^']|'')*')", re.I)
_TAB_KOM = re.compile(r"\bCOMMENT\s*=?\s*(?P<t>[NnEe]?'(?:[^']|'')*')", re.I)
_CONSTRAINT_KOPF = re.compile(
    r"(?:CONSTRAINT\s+\S+\s+)?(?:PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|EXCLUDE|"
    r"INDEX|KEY|FULLTEXT|SPATIAL|PERIOD\s+FOR|LIKE|CONSTRAINT)\b", re.I)
# Woerter, an denen die Typangabe einer Spalte endet.
_TYP_ENDE = re.compile(
    r"\b(?:NOT\s+NULL|NULL|DEFAULT|PRIMARY|REFERENCES|UNIQUE|CHECK|CONSTRAINT|COLLATE|"
    r"GENERATED|IDENTITY|AUTO_INCREMENT|AUTOINCREMENT|COMMENT|ENCODE|SPARSE|ROWGUIDCOL|"
    r"CHARACTER\s+SET|ON\s+UPDATE|AS\s*\(|ENABLE|DISABLE)\b", re.I)
_VON_JOIN = re.compile(rf"\b(?:FROM|JOIN)\s+(?P<t>{_ID})", re.I)


def zerlege(text: str) -> dict | None:
    """Fakten aus EINER Struktur-Anweisung.

    Rueckgabe (eine der Formen) oder ``None`` fuer Unbekanntes::

        {"art": "tabelle"|"sicht", "name", "spalten": [...], "pk": [...],
         "fks": [{"von": [...], "ziel", "nach": [...]}], "kommentar", "nutzt": [...]}
        {"art": "alter", "name", "fks": [...], "pk": [...]}
        {"art": "kommentar", "ziel_art": "tabelle"|"spalte", "ziel", "text"}
    """
    t = _ohne_kommentare(text).strip()
    if not t:
        return None
    m = _CREATE_TABLE.match(t)
    if m:
        return _tabelle(t, m)
    m = _CREATE_VIEW.match(t)
    if m:
        rest = t[m.end():]
        nutzt = sorted({bezeichner(x.group("t")) for x in _VON_JOIN.finditer(rest)} - {""})
        km = re.match(r"\s*\((?P<sp>[^)]*)\)\s*AS\b", rest, re.I)
        herkunft = sicht_herkunft(rest[km.end():] if km else rest)
        nutzt = sorted(set(nutzt) | set(herkunft.pop("tabellen")))
        if km:
            # Ausdrueckliche Liste: die Namen gelten POSITIONSWEISE – die
            # Herkunft der Auswahl steht unter anderen Namen, und ein ``*``
            # bildet ``(a, b)`` auf die ersten Spalten ab, nicht auf gleiche
            # Namen. Beides waere eine falsche Zuordnung, also keine.
            namen = _spaltenliste(km.group("sp"))
            herkunft = {"spalten": {}, "stern": []}   # (die FROM-Liste ist oben schon uebernommen)
        else:
            namen = sicht_spalten(rest)
        spalten = [{"name": s, "typ": "", "pk": False, "null": True, "kommentar": ""} for s in namen]
        return {"art": "sicht", "name": bezeichner(m.group("name")), "spalten": spalten,
                "pk": [], "fks": [], "kommentar": "", "nutzt": nutzt, "herkunft": herkunft}
    m = _ALTER_TABLE.match(t)
    if m:
        rest = t[m.end():]
        fks = [{"von": _spaltenliste(f.group("von")), "ziel": bezeichner(f.group("ziel")),
                "nach": _spaltenliste(f.group("nach") or "")} for f in _FK_RE.finditer(rest)]
        pk = []
        pm = _PK_RE.search(rest)
        if pm:
            pk = _spaltenliste(pm.group("sp"))
        if not fks and not pk:
            return None
        return {"art": "alter", "name": bezeichner(m.group("name")), "fks": fks, "pk": pk}
    m = _COMMENT_ON.match(t)
    if m:
        if m.group("text").upper() == "NULL":
            return None
        art = "spalte" if m.group("art").upper() == "COLUMN" else "tabelle"
        return {"art": "kommentar", "ziel_art": art, "ziel": bezeichner(m.group("ziel")),
                "text": _zeichenkette(m.group("text"))}
    m = _EXT_PROP.search(t)
    if m:
        return _ext_prop(m.group("args"))
    return None


def _tabelle(t: str, m) -> dict | None:
    name = bezeichner(m.group("name"))
    rest = t[m.end():]
    erg = {"art": "tabelle", "name": name, "spalten": [], "pk": [], "fks": [],
           "kommentar": "", "nutzt": []}
    auf = rest.find("(")
    vorspann = rest[:auf] if auf != -1 else rest
    # CREATE TABLE x AS SELECT … / PARTITION OF … / LIKE … ohne Spaltenblock
    if auf == -1 or re.search(r"\b(?:AS|PARTITION\s+OF|OF|CLONE|COPY)\b", vorspann, re.I):
        erg["nutzt"] = sorted({bezeichner(x.group("t")) for x in _VON_JOIN.finditer(rest)} - {""})
        po = re.search(rf"PARTITION\s+OF\s+(?P<t>{_ID})", rest, re.I)
        if po:
            erg["nutzt"].append(bezeichner(po.group("t")))
        return erg
    zu = _klammer_ende(rest, auf)
    if zu == -1:
        return erg
    koerper = rest[auf + 1:zu]
    nachspann = rest[zu + 1:]
    km = _TAB_KOM.search(nachspann)
    if km:
        erg["kommentar"] = _zeichenkette(km.group("t"))
    for teil in _teile_oben(koerper):
        if _CONSTRAINT_KOPF.match(teil):
            pm = _PK_RE.search(teil)
            if pm:
                erg["pk"] = _spaltenliste(pm.group("sp"))
            for f in _FK_RE.finditer(teil):
                erg["fks"].append({"von": _spaltenliste(f.group("von")),
                                   "ziel": bezeichner(f.group("ziel")),
                                   "nach": _spaltenliste(f.group("nach") or "")})
            continue
        m1 = re.match(_ID1, teil)
        sname = bezeichner(m1.group(0)) if m1 else ""
        if not sname:
            continue
        hinten = teil[m1.end():]
        te = _TYP_ENDE.search(hinten)
        typ = (hinten[:te.start()] if te else hinten).strip()
        typ = re.sub(r"\s+", " ", typ.replace("[", "").replace("]", ""))[:80]
        spalte = {"name": sname, "typ": typ,
                  "pk": bool(re.search(r"\bPRIMARY\s+KEY\b", hinten, re.I)),
                  "null": not re.search(r"\bNOT\s+NULL\b", hinten, re.I),
                  "kommentar": ""}
        ik = _INLINE_KOM.search(hinten)
        if ik:
            spalte["kommentar"] = _zeichenkette(ik.group("t"))
        ir = _INLINE_REF.search(hinten)
        if ir:
            erg["fks"].append({"von": [sname], "ziel": bezeichner(ir.group("ziel")),
                               "nach": _spaltenliste(ir.group("nach") or "")})
        erg["spalten"].append(spalte)
    if not erg["pk"]:
        erg["pk"] = [s["name"] for s in erg["spalten"] if s["pk"]]
    return erg


def _ext_prop(args: str) -> dict | None:
    """T-SQL ``sp_addextendedproperty 'MS_Description', 'Text', 'SCHEMA', 'dbo',
    'TABLE', 'x' [, 'COLUMN', 'y']`` – auch mit ``@name = N'..'``-Form."""
    werte = [_zeichenkette(w) for w in re.findall(r"[NnEe]?'(?:[^']|'')*'", args)]
    if len(werte) < 2 or werte[0].lower() not in ("ms_description", "description"):
        return None
    text = werte[1]
    paare = {}
    rest = werte[2:]
    for i in range(0, len(rest) - 1, 2):
        paare[rest[i].upper()] = rest[i + 1]
    schema = paare.get("SCHEMA", "")
    tab = paare.get("TABLE") or paare.get("VIEW")
    if not tab:
        return None
    ziel = f"{schema}.{tab}" if schema else tab
    if paare.get("COLUMN"):
        return {"art": "kommentar", "ziel_art": "spalte",
                "ziel": f"{ziel}.{paare['COLUMN']}", "text": text}
    return {"art": "kommentar", "ziel_art": "tabelle", "ziel": ziel, "text": text}


# ─── YAML (ein Objekt je Datei, Export aus dem Datenbank-Katalog) ───────────
#
# Gemessen am echten Bestand auf DEV (2026-11-07, 8429 Dateien, 47 MB, alle mit
# dem C-Lader in 2,9 s lesbar): je Datei EIN Objekt mit ``name``,
# ``object_type`` (TABLE, VIEW, SEQUENCE, PACKAGE, FUNCTION, PROCEDURE),
# ``schema``; Tabellen mit ``columns`` (name, type, length, precision, scale,
# char_length, nullable, comment), ``comment``, ``constraints``
# (PRIMARY_KEY/UNIQUE mit columns), ``foreign_keys`` (columns,
# referenced_table, referenced_columns – OHNE Schema: dasselbe Schema),
# ``indexes``; Sichten nur mit ``definition`` (SQL) und ``comment``. Daneben
# Verzeichnisdateien (``*_SCHEMA_INDEX.yaml``: ``index_version``, ``tables``
# als Liste mit ``file``) – die werden erkannt und uebersprungen.
#
# Gelesen wird nur ueber den SAFE-Lader (keine Python-Objekte). Aliase sind
# abgeschaltet, sobald die Datei nach Ankern aussieht: ein Alias-Baum ("billion
# laughs") ist mit dem Safe-Lader ebenso ein Speicherproblem.

YAML_ENDUNGEN = (".yaml", ".yml")
YAML_MAX = 64 * 1024 * 1024
_YAML_ANKER = re.compile(r"(?m)(?:^|[\s:,\[{-])&[A-Za-z0-9_-]+")
_OBJEKT_TABELLE = {"TABLE"}
_OBJEKT_SICHT = {"VIEW", "MATERIALIZED_VIEW", "MATERIALIZED VIEW"}
# Woerter, die am Ende eines Auswahl-Ausdrucks stehen, ohne ein Alias zu sein.
_KEIN_ALIAS = {"END", "NULL", "AND", "OR", "NOT", "THEN", "ELSE", "IS", "IN", "DISTINCT", "ALL",
               "UNIQUE", "TRUE", "FALSE", "SYSDATE", "SYSTIMESTAMP", "ROWNUM", "LEVEL", "USER"}


def _yaml_laden(text: str):
    """Alle Dokumente einer YAML-Datei (Safe-Lader, ohne Aliase bei Ankern)."""
    import yaml  # noqa: PLC0415 – nur fuer YAML-Dateien noetig
    if _YAML_ANKER.search(text):
        class _OhneAlias(yaml.SafeLoader):
            def compose_node(self, parent, index):
                if self.check_event(yaml.AliasEvent):
                    raise yaml.YAMLError("YAML-Aliase (*name) werden nicht verarbeitet")
                return super().compose_node(parent, index)
        lader = _OhneAlias
    else:
        lader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return list(yaml.load_all(text, Loader=lader))


def _yaml_typ(c: dict) -> str:
    """``VARCHAR2`` + length 30 -> ``VARCHAR2(30)``; NUMBER mit precision/scale."""
    typ = str(c.get("type") or c.get("data_type") or "").strip()
    if not typ or "(" in typ:
        return typ[:80]
    gross = typ.upper()
    p, sk = c.get("precision"), c.get("scale")
    if gross in ("NUMBER", "NUMERIC", "DECIMAL", "FLOAT") and isinstance(p, int) and p > 0:
        return f"{typ}({p},{sk})" if isinstance(sk, int) and sk > 0 else f"{typ}({p})"
    if gross in ("VARCHAR2", "NVARCHAR2", "VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "RAW"):
        n = c.get("char_length") or c.get("length")
        if isinstance(n, int) and n > 0:
            return f"{typ}({n})"
    return typ[:80]


def _liste(x) -> list:
    return [str(v) for v in x if isinstance(v, (str, int))] if isinstance(x, list) else []


def _ebene0(text: str):
    """Positionen der Woerter SELECT/FROM auf oberster Klammerebene (Zeichenketten
    und Bezeichner in Anfuehrungszeichen uebersprungen)."""
    tiefe, i, n = 0, 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            j = text.find(c, i + 1)
            while j != -1 and j + 1 < n and text[j + 1] == c:
                j = text.find(c, j + 2)
            i = (j + 1) if j != -1 else n
            continue
        if c == "(":
            tiefe += 1
        elif c == ")":
            tiefe -= 1
        elif tiefe == 0 and (c in "sSfF") and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_$#")):
            for wort in ("SELECT", "FROM"):
                ende = i + len(wort)
                if text[i:ende].upper() == wort and (ende >= n or not (text[ende].isalnum() or text[ende] in "_$#")):
                    yield wort, i
        i += 1


def _alias(ausdruck: str) -> str | None:
    t = ausdruck.strip()
    m = re.search(rf"\bAS\s+({_ID1})\s*$", t, re.I)
    if m:
        return bezeichner(m.group(1)) or None
    if re.fullmatch(_ID, t):
        return bezeichner(t).rsplit(".", 1)[-1] or None
    m = re.search(rf"[\w)\]\"'`]\s+({_ID1})\s*$", t)
    if m:
        kand = bezeichner(m.group(1))
        if kand and kand.upper() not in _KEIN_ALIAS:
            return kand
    return None


def _erste_auswahl(definition: str) -> tuple[str, str, str] | None:
    """(Text, SELECT-Liste, Rest ab FROM) der ERSTEN Auswahl auf oberster Ebene.

    Eine Sicht in Klammern (``(SELECT …)``) wird bis zu dreimal ausgepackt.
    ``None``, wenn es keine Auswahl gibt.
    """
    t = _ohne_kommentare(definition or "").strip()
    for _ in range(3):
        sel = fro = None
        for wort, pos in _ebene0(t):
            if wort == "SELECT" and sel is None:
                sel = pos
            elif wort == "FROM" and sel is not None:
                fro = pos
                break
        if sel is not None:
            break
        if t.startswith("("):
            zu = _klammer_ende(t, 0)
            t = t[1:zu].strip() if zu != -1 else ""
            continue
        return None
    if sel is None:
        return None
    liste = t[sel + 6:fro if fro is not None else len(t)]
    liste = re.sub(r"^\s*(?:DISTINCT|UNIQUE|ALL)\b", " ", liste, flags=re.I)
    return t, liste, (t[fro:] if fro is not None else "")


def _klammern_leeren(text: str) -> str:
    """Inhalt jeder Klammer (samt Zeichenketten darin) durch Leerzeichen ersetzen,
    die Klammern selbst bleiben stehen – Unterabfragen sind damit unsichtbar."""
    out, tiefe = [], 0
    for c in text:
        if c == "(":
            tiefe += 1
            out.append(c if tiefe == 1 else " ")
        elif c == ")":
            out.append(c if tiefe == 1 else " ")
            tiefe = max(0, tiefe - 1)
        else:
            out.append(" " if tiefe else c)
    return "".join(out)


# Wo die FROM-Liste endet (oberste Ebene, Klammerinhalte sind vorher geleert)
_VON_ENDE = re.compile(
    r"\b(?:WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|CONNECT\s+BY|START\s+WITH|WITH\s+(?:CHECK|READ)|"
    r"FETCH|LIMIT|OFFSET|WINDOW|QUALIFY|MODEL|FOR\s+UPDATE)\b", re.I)
# Mengenoperatoren: die Herkunft gilt dann nur fuer EINEN Zweig – also keine
_MENGE = re.compile(r"\b(?:UNION|INTERSECT|MINUS|EXCEPT)\b", re.I)
_JOIN_TRENNER = re.compile(r",|\bJOIN\b", re.I)
_VOR_TABELLE = re.compile(r"^\s*(?:FROM|LATERAL|ONLY)\b", re.I)
_NACH_TABELLE = re.compile(r"\b(?:ON|USING|INNER|LEFT|RIGHT|FULL|CROSS|NATURAL|OUTER|PARTITION|"
                           r"SAMPLE|TABLESAMPLE|WITH|AS\s+OF|VERSIONS)\b", re.I)


def sicht_herkunft(definition: str) -> dict:
    """Woher die Spalten einer Sicht stammen – fuer die Join-Pruefung.

    Rueckgabe ``{"spalten": {name_klein: [tabelle, spalte]}, "stern": [tabelle, …],
    "tabellen": [tabelle, …]}`` – ``tabellen`` ist die FROM-Liste der Auswahl
    (auch durch Komma getrennt; ``_VON_JOIN`` sieht nur die erste davon).
    Aufgenommen wird NUR, was eindeutig ist: ein blosser Spaltenverweis
    (``a.X``, ``a.X AS Y``, ``X`` bei genau einer Tabelle) auf eine Tabelle der
    FROM-Liste. Ausdruecke (``NVL(a.x, 0) x``), Unterabfragen, CTEs und
    Mengenoperatoren (UNION …) liefern nichts – eine falsch zugeordnete Herkunft
    wuerde einen erfundenen Join als belegt durchwinken, und das ist teurer als
    ein ehrliches "ungeprueft". ``*`` bzw. ``t.*`` steht unter ``stern``:
    jede Spalte gleichen Namens kommt aus dieser Tabelle.
    """
    leer = {"spalten": {}, "stern": [], "tabellen": []}
    roh = _ohne_kommentare(definition or "").strip()
    a = _erste_auswahl(roh)
    if a is None:
        return leer
    t, liste, von = a
    # WITH vor der Auswahl: FROM-Namen koennen CTEs sein, keine Tabellen
    if re.match(r"[\s(]*WITH\b", roh, re.I):
        return leer
    flach = _klammern_leeren(von)
    if _MENGE.search(flach):
        return leer
    e = _VON_ENDE.search(flach)
    flach = flach[:e.start()] if e else flach
    # alias/name (klein) -> Tabelle
    quellen: dict[str, str] = {}
    tabellen: list[str] = []
    for stueck in _JOIN_TRENNER.split(flach):
        stueck = _VOR_TABELLE.sub(" ", stueck)
        n = _NACH_TABELLE.search(stueck)
        stueck = (stueck[:n.start()] if n else stueck).strip()
        if not stueck:
            continue
        if stueck.startswith("("):
            tabellen.append("")   # Unterabfrage: zaehlt, ist aber keine Tabelle
            continue
        m = re.fullmatch(rf"({_ID})(?:\s+(?:AS\s+)?({_ID1}))?", stueck, re.I)
        if not m:
            tabellen.append("")
            continue
        tab = bezeichner(m.group(1))
        tabellen.append(tab)
        quellen.setdefault(tab.lower(), tab)
        quellen.setdefault(tab.rsplit(".", 1)[-1].lower(), tab)
        if m.group(2):
            al = bezeichner(m.group(2)).lower()
            if al.upper() not in _KEIN_ALIAS:
                quellen[al] = tab
    if not tabellen:
        return leer
    einzige = tabellen[0] if len(tabellen) == 1 and tabellen[0] else None
    erg = {"spalten": {}, "stern": [], "tabellen": [x for x in tabellen if x]}
    for teil in _teile_oben(liste):
        teil = teil.strip()
        sm = re.fullmatch(rf"(?:({_ID})\s*\.\s*)?\*", teil)
        if sm:
            if sm.group(1):
                q = quellen.get(bezeichner(sm.group(1)).lower())
                if q:
                    erg["stern"].append(q)
            elif einzige:
                erg["stern"].append(einzige)
            continue
        name = _alias(teil)
        if not name:
            continue
        ausdruck = re.sub(rf"\s+(?:AS\s+)?{_ID1}\s*$", "", teil, flags=re.I) \
            if not re.fullmatch(_ID, teil) else teil
        if not re.fullmatch(_ID, ausdruck.strip()):
            continue
        teile = bezeichner(ausdruck).split(".")
        if len(teile) == 1:
            if einzige:
                erg["spalten"][name.lower()] = [einzige, teile[0]]
            continue
        q = quellen.get(".".join(teile[:-1]).lower())
        if q:
            erg["spalten"][name.lower()] = [q, teile[-1]]
    return erg


def sicht_spalten(definition: str) -> list[str]:
    """Spaltennamen einer Sicht aus ihrer SELECT-Liste – NUR wenn sie vollstaendig
    bestimmbar sind (``*`` oder ein Ausdruck ohne Alias -> ``[]``).

    Eine halbe Liste waere schlimmer als keine: die Pruefung des erzeugten SQL
    ueberspringt Sichten ohne Spaltenliste, wiese aber mit einer unvollstaendigen
    gueltige Spalten als unbekannt ab. Massgeblich ist die ERSTE Auswahl
    (bei UNION bestimmt sie die Namen; bei WITH die nach den CTEs).
    """
    a = _erste_auswahl(definition)
    if a is None:
        return []
    namen = []
    for teil in _teile_oben(a[1]):
        # ``*`` und ``t.*`` haben keinen Alias -> die Liste ist nicht bestimmbar
        # (eine eigene Abfrage dafuer war messbar wirkungslos, Gegenprobe).
        name = _alias(teil)
        if not name:
            return []
        namen.append(name)
    return namen if len(set(n.lower() for n in namen)) == len(namen) else []


def yaml_objekt(d, stat: Statistik) -> list[dict]:
    """EIN YAML-Objekt -> Fakten in derselben Form wie ``zerlege``."""
    if not isinstance(d, dict):
        stat["unverstanden"] += 1
        return []
    if "index_version" in d or ("object_type" not in d and isinstance(d.get("tables"), list)):
        stat["verzeichnis"] = stat.get("verzeichnis", 0) + 1
        return []
    typ = str(d.get("object_type") or "").strip().upper()
    name = str(d.get("name") or "").strip()
    schema = str(d.get("schema") or d.get("owner") or "").strip()
    if not name or not typ:
        stat["unverstanden"] += 1
        return []
    voll = f"{schema}.{name}" if schema else name
    kommentar = str(d.get("comment") or "").strip()
    if typ in _OBJEKT_TABELLE:
        pk = []
        for c in d.get("constraints") or []:
            if isinstance(c, dict) and str(c.get("type") or "").upper().replace(" ", "_") in ("PRIMARY_KEY", "P"):
                pk = _liste(c.get("columns"))
        pk_l = {x.lower() for x in pk}
        spalten = []
        for c in d.get("columns") or []:
            if not isinstance(c, dict) or not str(c.get("name") or "").strip():
                continue
            sn = str(c["name"]).strip()
            spalten.append({"name": sn, "typ": _yaml_typ(c), "pk": sn.lower() in pk_l,
                            "null": c.get("nullable") is not False,
                            "kommentar": str(c.get("comment") or "").strip()})
        fks = []
        for f in d.get("foreign_keys") or []:
            if not isinstance(f, dict) or not f.get("referenced_table"):
                continue
            zs = str(f.get("referenced_schema") or f.get("referenced_owner") or schema or "").strip()
            zt = str(f["referenced_table"]).strip()
            fks.append({"von": _liste(f.get("columns")), "ziel": f"{zs}.{zt}" if zs else zt,
                        "nach": _liste(f.get("referenced_columns"))})
        stat["struktur"] += 1
        return [{"art": "tabelle", "name": voll, "spalten": spalten, "pk": pk, "fks": fks,
                 "kommentar": kommentar, "nutzt": []}]
    if typ in _OBJEKT_SICHT:
        definition = str(d.get("definition") or d.get("text") or "")
        rumpf = _ohne_kommentare(definition)
        nutzt = sorted({bezeichner(x.group("t")) for x in _VON_JOIN.finditer(rumpf)} - {"", voll})
        if isinstance(d.get("columns"), list) and d["columns"]:
            namen = [str(c.get("name")) for c in d["columns"] if isinstance(c, dict) and c.get("name")]
        else:
            namen = sicht_spalten(definition)
        herkunft = sicht_herkunft(definition)
        nutzt = sorted((set(nutzt) | set(herkunft.pop("tabellen"))) - {voll})
        stat["struktur"] += 1
        return [{"art": "sicht", "name": voll, "kommentar": kommentar, "nutzt": nutzt, "pk": [], "fks": [],
                 "spalten": [{"name": n, "typ": "", "pk": False, "null": True, "kommentar": ""} for n in namen],
                 "herkunft": herkunft}]
    # SEQUENCE, PACKAGE, FUNCTION, PROCEDURE, TRIGGER …: fuer Joins ohne Belang
    stat["objekt_uebersprungen"] = stat.get("objekt_uebersprungen", 0) + 1
    return []


def yaml_zerlegen(pfad: str, stat: Statistik) -> list[dict]:
    import os  # noqa: PLC0415
    groesse = os.path.getsize(pfad)
    stat["bytes"] = groesse
    if groesse > YAML_MAX:
        raise ValueError(f"YAML-Datei groesser als {YAML_MAX // 1024 // 1024} MB – nicht gelesen")
    with open(pfad, encoding=kodierung(pfad), errors="replace") as f:
        text = f.read()
    fakten = []
    for dok in _yaml_laden(text):
        stat["anweisungen"] += 1
        for obj in (dok if isinstance(dok, list) else [dok]):
            fakten.extend(yaml_objekt(obj, stat))
    return fakten


# ─── Begleitdokumente (Konventionen, SQL-Beispiele, Best Practices) ─────────
#
# Anlass (2026-11-07): zum YAML-Bestand gehoeren Dokumente des Hauses (Schema-
# Konventionen, SQL-Beispiele, Best Practices). Ohne sie verwechselte das
# Modell Fachbegriffe ("Verfahren" -> Gerichtsverfahren statt der Verfahren des Hauses)
# und erfand Joins. Sie werden in Abschnitte zerlegt und je Frage passend als
# HAUSWISSEN mitgegeben.
#
# BILDER (seit Fassung 5): ein Dokument "Datenbankmodel Diagramme" bestand im
# echten Bestand NUR aus vier Diagrammen unter Ueberschriften und fiel als
# "kein lesbarer Text" heraus. Auf DEV gemessen (2026-11-08): tesseract liest
# daraus die Tabellennamen MIT ihrer deutschen Bezeichnung (Kuerzel einer
# Rezepttabelle -> "Rezepte zur Abrechnung"), 1-2 s je Bild. Die Linien des
# Diagramms (Beziehungen) liest es nicht – der Text kommt deshalb als
# "[Bild, Texterkennung]" gekennzeichnet ins Hauswissen, nicht als Beleg.

DOK_ENDUNGEN = (".md", ".docx", ".pdf")
DOK_MAX = 64 * 1024 * 1024
DOK_TEIL = 1500
DOK_MAX_TEILE = 2000

# Grenzen der Texterkennung – die Bilder stammen aus hochgeladenen Dateien:
# ein Bild mit gefaelschter Groesse im Kopf entpackt sonst auf Gigabytes, und
# ein Dokument voller Bilder haelt die Erfassung beliebig lange auf.
OCR_BILD_BYTES = 20 * 1024 * 1024
OCR_BILD_PIXEL = 40_000_000
OCR_MIN_SEITE = 40             # kleiner: Symbol oder Zierrat, kein Text
OCR_MAX_BILDER = 100           # je Dokument
OCR_ZEIT_DOKUMENT = 300.0      # Sekunden je Dokument insgesamt
OCR_ZEIT_BILD = 60.0
OCR_SPRACHEN = ("deu", "eng")
OCR_KENNUNG = "[Bild, Texterkennung]"
OCR_FORMATE = ("PNG", "JPEG", "GIF", "BMP", "TIFF")
_RASTER = ("image/png", "image/jpeg", "image/jpg", "image/gif", "image/bmp", "image/tiff", "image/x-png")
_ocr_sprache_cache: list = []


def _ocr_sprache() -> str | None:
    """'deu+eng' (was davon installiert ist) oder None ohne tesseract.
    Einmal je Arbeitsprozess gefragt."""
    if _ocr_sprache_cache:
        return _ocr_sprache_cache[0]
    import subprocess  # noqa: PLC0415
    try:
        r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=20,
                           env={"PATH": "/usr/bin:/bin:/usr/local/bin"})
        da = {z.strip() for z in (r.stdout or "").splitlines()[1:]}
        sprachen = [x for x in OCR_SPRACHEN if x in da]
        wert = "+".join(sprachen) if r.returncode == 0 and sprachen else None
    except (OSError, subprocess.SubprocessError):
        wert = None
    _ocr_sprache_cache.append(wert)
    return wert


def _zaehle(stat, schluessel: str) -> None:
    if stat is not None:
        stat[schluessel] = stat.get(schluessel, 0) + 1


def _bild_lesen(blob: bytes, stat, ende: float) -> str:
    """Text aus EINEM Rasterbild (leer, wenn nichts Lesbares darin steht).

    Ohne temporaere Datei: das Bild geht als PNG ueber stdin an tesseract.
    IMMER neu kodiert, nie das Original durchgereicht: tesseract liest eine
    Eingabe, die kein Bild ist, als LISTE VON DATEIPFADEN (lokal gemessen:
    ``echo test | tesseract stdin stdout`` sucht die Datei "test") – ein
    praepariertes "Bild" im Dokument koennte so Serverdateien ins Hauswissen
    holen. Was PIL nicht als Bild oeffnet, erreicht tesseract nicht.
    Transparenz wird auf WEISS gelegt – ein RGBA-Diagramm mit durchsichtigem
    Hintergrund waere nach einem blossen convert("RGB") schwarze Schrift auf
    schwarzem Grund."""
    import io  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import time  # noqa: PLC0415
    if len(blob) > OCR_BILD_BYTES:
        _zaehle(stat, "bilder_zu_gross")
        return ""
    rest = ende - time.monotonic()
    if rest <= 1:
        _zaehle(stat, "bilder_ohne_zeit")
        return ""
    sprache = _ocr_sprache()
    if sprache is None:
        _zaehle(stat, "bilder_ohne_ocr")
        return ""
    from PIL import Image  # noqa: PLC0415
    try:
        # NUR Rasterformate: PIL oeffnet sonst auch EPS – und uebergibt das
        # beim Laden an Ghostscript, einen Interpreter fuer fremden Code.
        im = Image.open(io.BytesIO(blob), formats=OCR_FORMATE)
        b, h = im.size                     # nur der Kopf ist gelesen
        if b * h > OCR_BILD_PIXEL:
            _zaehle(stat, "bilder_zu_gross")
            return ""
        if min(b, h) < OCR_MIN_SEITE:
            _zaehle(stat, "bilder_klein")
            return ""
        im.load()
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            grund = Image.new("RGB", rgba.size, (255, 255, 255))
            grund.paste(rgba, mask=rgba.getchannel("A"))
            im = grund
        else:
            im = im.convert("RGB")
        puffer = io.BytesIO()
        im.save(puffer, "PNG")
    except Exception:  # noqa: BLE001 – ein kaputtes Bild kippt nicht das Dokument
        _zaehle(stat, "bilder_unlesbar")
        return ""
    try:
        r = subprocess.run(["tesseract", "stdin", "stdout", "-l", sprache], input=puffer.getvalue(),
                           capture_output=True, timeout=min(OCR_ZEIT_BILD, rest),
                           # Ein Kern je Bild: tesseract belegt sonst alle Kerne,
                           # und die Erfassung laeuft ohnehin mit mehreren Prozessen.
                           env={"OMP_THREAD_LIMIT": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"})
    except subprocess.TimeoutExpired:
        _zaehle(stat, "bilder_ohne_zeit")
        return ""
    except OSError:
        _zaehle(stat, "bilder_ohne_ocr")
        return ""
    if r.returncode != 0:
        _zaehle(stat, "bilder_unlesbar")
        return ""
    zeilen = []
    for z in r.stdout.decode("utf-8", errors="replace").splitlines():
        z = " ".join(z.split())
        # Rauschen ("~~ —", einzelne Striche aus Diagrammlinien) faellt weg
        if sum(ch.isalnum() for ch in z) >= 2:
            zeilen.append(z)
    if not zeilen:
        _zaehle(stat, "bilder_ohne_text")
        return ""
    _zaehle(stat, "bilder_gelesen")
    return "\n".join(zeilen)


class _Bilder:
    """Texterkennung ueber die Bilder EINES Dokuments: Obergrenzen fuer
    Anzahl und Zeit, jedes Bild nur einmal (ein Logo auf jeder Seite)."""

    def __init__(self, stat):
        import time  # noqa: PLC0415
        self.stat = stat
        self.ende = time.monotonic() + OCR_ZEIT_DOKUMENT
        self.gesehen: set = set()
        self.anzahl = 0

    def lesen(self, blob: bytes) -> str:
        import hashlib  # noqa: PLC0415
        kennung = hashlib.sha256(blob).digest()
        if kennung in self.gesehen:
            return ""
        self.gesehen.add(kennung)
        _zaehle(self.stat, "bilder")
        if self.anzahl >= OCR_MAX_BILDER:
            _zaehle(self.stat, "bilder_ueber_grenze")
            return ""
        self.anzahl += 1
        t = _bild_lesen(blob, self.stat, self.ende)
        return f"{OCR_KENNUNG} {t}" if t else ""


_NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_V = "{urn:schemas-microsoft-com:vml}"


def _docx_bilder(el, teil) -> list[bytes]:
    """Rasterbilder, die das Element (Absatz oder Tabelle) einbettet – in
    Lesereihenfolge. Vektorformate (EMF/WMF/SVG) liest tesseract nicht."""
    out = []
    for knoten in el.iter(f"{_NS_A}blip", f"{_NS_V}imagedata"):
        rid = knoten.get(f"{_NS_R}embed") or knoten.get(f"{_NS_R}id")
        ziel = teil.related_parts.get(rid) if rid else None
        if ziel is None or (getattr(ziel, "content_type", "") or "").lower() not in _RASTER:
            continue
        out.append(ziel.blob)
    return out


def _dok_absaetze(pfad: str, stat=None) -> list[tuple[str, str]]:
    """(art, text) in Lesereihenfolge; art 'kopf' fuer Ueberschriften.

    Bilder (DOCX) und Seiten ohne Text (PDF, z. B. gescannt) gehen durch die
    Texterkennung; ``stat`` zaehlt, was dabei gelesen und was ausgelassen wurde."""
    endung = pfad.lower().rsplit(".", 1)[-1]
    out: list[tuple[str, str]] = []
    if endung == "md":
        # Zeilenweise: eine Ueberschrift steht meist DIREKT vor ihrem Text, ohne
        # Leerzeile (eine Absatz-Zerlegung erkannte sie dann nicht – Waechter).
        # In einem Codeblock ist "# x" ein Kommentar, keine Ueberschrift.
        with open(pfad, encoding=kodierung(pfad), errors="replace") as f:
            zeilen = f.read().splitlines()
        absatz: list[str] = []
        im_code = False

        def absatz_zu():
            if absatz:
                out.append(("text", "\n".join(absatz).strip()))
                absatz.clear()
        for z in zeilen:
            if z.lstrip().startswith("`" * 3) or z.lstrip().startswith("~" * 3):
                im_code = not im_code
                absatz.append(z)
                continue
            if not im_code and re.match(r"#{1,6}\s", z):
                absatz_zu()
                out.append(("kopf", z.lstrip("#").strip()))
            elif not im_code and not z.strip():
                absatz_zu()
            else:
                absatz.append(z)
        absatz_zu()
        return [(a, t) for a, t in out if t]
    if endung == "docx":
        import docx  # noqa: PLC0415 – nur fuer Begleitdokumente noetig
        from docx.table import Table  # noqa: PLC0415
        from docx.text.paragraph import Paragraph  # noqa: PLC0415
        d = docx.Document(pfad)
        bilder = _Bilder(stat)
        for el in d.element.body.iterchildren():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                par = Paragraph(el, d)
                t = par.text.strip()
                if t:
                    stil = (par.style.name if par.style is not None else "") or ""
                    out.append(("kopf" if re.match(r"(?:Heading|Überschrift|Title|Titel)\b", stil, re.I) else "text", t))
            elif tag == "tbl":
                for zeile in Table(el, d).rows:
                    zellen = []
                    for c in zeile.cells:
                        ct = " ".join(c.text.split())
                        if ct and (not zellen or zellen[-1] != ct):   # verbundene Zellen nur einmal
                            zellen.append(ct)
                    if zellen:
                        out.append(("text", " | ".join(zellen)))
            else:
                continue
            # Bilder NACH dem Text ihres Absatzes, also unter derselben Ueberschrift
            for blob in _docx_bilder(el, d.part):
                bt = bilder.lesen(blob)
                if bt:
                    out.append(("text", bt))
        return out
    if endung == "pdf":
        import pdfplumber  # noqa: PLC0415
        bilder = _Bilder(stat)
        with pdfplumber.open(pfad) as pdf:
            for seite in pdf.pages:
                t = seite.extract_text() or ""
                if not t.strip() and seite.images:
                    # Seite ohne Textebene, aber mit Bild: gescannt -> als Bild lesen
                    t = _pdf_seite_lesen(seite, bilder)
                for block in re.split(r"\n\s*\n", t):
                    if block.strip():
                        out.append(("text", block.strip()))
        return out
    return out


def _pdf_seite_lesen(seite, bilder: _Bilder) -> str:
    """Eine PDF-Seite ohne Textebene als Bild (200 dpi) durch die Texterkennung."""
    import io  # noqa: PLC0415
    try:
        bild = seite.to_image(resolution=200).original
        puffer = io.BytesIO()
        bild.save(puffer, "PNG")
    except Exception:  # noqa: BLE001 – Seite nicht darstellbar: auslassen, gezaehlt
        _zaehle(bilder.stat, "bilder_unlesbar")
        return ""
    return bilder.lesen(puffer.getvalue())


def dokument_teile(absaetze: list[tuple[str, str]]) -> list[str]:
    """Absaetze -> Abschnitte bis ``DOK_TEIL`` Zeichen, an Absatzgrenzen, mit
    der letzten Ueberschrift als Kopf (ein Auszug ohne seine Ueberschrift
    verliert, WORUEBER er spricht)."""
    teile, akt, kopf = [], [], ""

    def schliessen():
        if akt:
            teile.append(((f"[{kopf}] " if kopf else "") + "\n".join(akt)).strip())
            akt.clear()
    laenge = 0
    for art, t in absaetze:
        if art == "kopf":
            schliessen()
            laenge = 0
            kopf = t[:120]
            continue
        while len(t) > DOK_TEIL:
            schliessen()
            laenge = 0
            schnitt = t.rfind(" ", 0, DOK_TEIL)
            schnitt = schnitt if schnitt > DOK_TEIL // 2 else DOK_TEIL
            akt.append(t[:schnitt])
            schliessen()
            t = t[schnitt:].lstrip()
        if laenge + len(t) > DOK_TEIL:
            schliessen()
            laenge = 0
        akt.append(t)
        laenge += len(t) + 1
        if len(teile) >= DOK_MAX_TEILE:
            break
    schliessen()
    return teile[:DOK_MAX_TEILE]


def dokument_zerlegen(pfad: str, stat: Statistik) -> list[dict]:
    import os  # noqa: PLC0415
    groesse = os.path.getsize(pfad)
    stat["bytes"] = groesse
    if groesse > DOK_MAX:
        raise ValueError(f"Dokument groesser als {DOK_MAX // 1024 // 1024} MB – nicht gelesen")
    teile = dokument_teile(_dok_absaetze(pfad, stat))
    if not teile:
        if stat.get("bilder_ohne_ocr"):
            raise ValueError("enthält nur Bilder, und die Texterkennung (tesseract mit deu/eng) "
                             "fehlt auf dem Server – 'apt install tesseract-ocr tesseract-ocr-deu'")
        if stat.get("bilder"):
            gruende = [f"{stat[k]} {w}" for k, w in (
                ("bilder_ohne_text", "ohne lesbaren Text"), ("bilder_klein", "zu klein"),
                ("bilder_zu_gross", "zu groß"), ("bilder_unlesbar", "nicht lesbar"),
                ("bilder_ohne_zeit", "nach Ablauf der Zeitgrenze"),
                ("bilder_ueber_grenze", "über der Höchstzahl")) if stat.get(k)]
            raise ValueError(f"enthält nur Bilder ({stat['bilder']}), die Texterkennung fand keinen Text: "
                             + ", ".join(gruende))
        raise ValueError("kein lesbarer Text (gescanntes PDF oder nur Bilder?)")
    stat["dokument_teile"] = len(teile)
    titel = os.path.basename(pfad).rsplit(".", 1)[0]
    return [{"art": "dokument", "titel": titel, "teile": teile}]


def datei_zerlegen(pfad: str) -> dict:
    """Arbeitsfunktion fuer den Prozess-Pool: eine Datei -> Fakten + Statistik.

    Faengt jeden Fehler selbst (ein Wurf im Pool beendet sonst den ganzen
    Lauf); der Fehler steht dann im Ergebnis. ``.yaml``/``.yml`` gehen ueber den
    YAML-Weg, alles andere ueber den SQL-Parser.
    """
    stat = Statistik()
    fakten = []
    if str(pfad).lower().endswith(DOK_ENDUNGEN):
        try:
            fakten = dokument_zerlegen(pfad, stat)
            return {"pfad": pfad, "ok": True, "fakten": fakten, "stat": dict(stat), "fehler": ""}
        except ImportError as e:
            return {"pfad": pfad, "ok": False, "fakten": [], "stat": dict(stat),
                    "fehler": f"Lesebibliothek fehlt ({e.name}) – Dokument nicht lesbar"}
        except Exception as e:  # noqa: BLE001
            return {"pfad": pfad, "ok": False, "fakten": [], "stat": dict(stat),
                    "fehler": f"{type(e).__name__}: {e}"[:500]}
    if str(pfad).lower().endswith(YAML_ENDUNGEN):
        try:
            fakten = yaml_zerlegen(pfad, stat)
            return {"pfad": pfad, "ok": True, "fakten": fakten, "stat": dict(stat), "fehler": ""}
        except ImportError:
            return {"pfad": pfad, "ok": False, "fakten": [], "stat": dict(stat),
                    "fehler": "PyYAML fehlt (pip install PyYAML) – YAML-Dateien sind nicht lesbar"}
        except Exception as e:  # noqa: BLE001
            return {"pfad": pfad, "ok": False, "fakten": [], "stat": dict(stat),
                    "fehler": f"{type(e).__name__}: {e}"[:500]}
    try:
        for anw in anweisungen(pfad, stat):
            try:
                f = zerlege(anw)
            except Exception:  # noqa: BLE001 – eine kaputte Anweisung kippt nicht die Datei
                f = None
            if f is None:
                stat["unverstanden"] += 1
            else:
                fakten.append(f)
        return {"pfad": pfad, "ok": True, "fakten": fakten, "stat": dict(stat), "fehler": ""}
    except Exception as e:  # noqa: BLE001
        return {"pfad": pfad, "ok": False, "fakten": fakten, "stat": dict(stat),
                "fehler": f"{type(e).__name__}: {e}"[:500]}


def _arbeiter() -> int:
    """Arbeitsprozess fuer den Indexlauf: je Zeile auf stdin ein Pfad, je Zeile
    auf stdout das Ergebnis als JSON.

    Bewusst ein eigener Prozess ueber ``python -m`` statt ``multiprocessing``:
    dessen ``spawn`` laedt das Hauptmodul des Elternprozesses erneut – im
    Dienst ``run_jarvis.py``, und das importiert ``backend.config``.
    """
    import json
    import sys
    for zeile in sys.stdin:
        pfad = zeile.rstrip("\n")
        if not pfad:
            continue
        erg = datei_zerlegen(pfad)
        sys.stdout.write(json.dumps(erg, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(_arbeiter())

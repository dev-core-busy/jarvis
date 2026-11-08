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
# 1 = SQL-DDL, 2 = dazu YAML-Objektexporte, 3 = dazu Begleitdokumente.
FASSUNG = 3

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
       |`[^`]*+`|--[^\n]*+\n|/\*.*?\*/|-(?!-)|/(?!\*))*+""",
    re.X | re.S | re.I)
_COPY_ENDE = re.compile(r"(?m)^\\\.[ \t]*\r?(?:\n|\Z)")


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

    def dazu(self, teil: str) -> None:
        if not teil:
            return
        if len(self.kopf) < self.KOPF:
            self.kopf += teil[:self.KOPF - len(self.kopf)]
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
    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
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
            stat["anweisungen"] -= 1   # nur Leerraum/Kommentar: keine Anweisung
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
                    anw.dazu(puf[pos:m.end()])
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
        spalten = []
        km = re.match(r"\s*\((?P<sp>[^)]*)\)\s*AS\b", rest, re.I)
        if km:
            spalten = [{"name": s, "typ": "", "pk": False, "null": True, "kommentar": ""}
                       for s in _spaltenliste(km.group("sp"))]
        return {"art": "sicht", "name": bezeichner(m.group("name")), "spalten": spalten,
                "pk": [], "fks": [], "kommentar": "", "nutzt": nutzt}
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


def sicht_spalten(definition: str) -> list[str]:
    """Spaltennamen einer Sicht aus ihrer SELECT-Liste – NUR wenn sie vollstaendig
    bestimmbar sind (``*`` oder ein Ausdruck ohne Alias -> ``[]``).

    Eine halbe Liste waere schlimmer als keine: die Pruefung des erzeugten SQL
    ueberspringt Sichten ohne Spaltenliste, wiese aber mit einer unvollstaendigen
    gueltige Spalten als unbekannt ab. Massgeblich ist die ERSTE Auswahl
    (bei UNION bestimmt sie die Namen; bei WITH die nach den CTEs).
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
        return []
    if sel is None:
        return []
    liste = t[sel + 6:fro if fro is not None else len(t)]
    liste = re.sub(r"^\s*(?:DISTINCT|UNIQUE|ALL)\b", " ", liste, flags=re.I)
    namen = []
    for teil in _teile_oben(liste):
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
        stat["struktur"] += 1
        return [{"art": "sicht", "name": voll, "kommentar": kommentar, "nutzt": nutzt, "pk": [], "fks": [],
                 "spalten": [{"name": n, "typ": "", "pk": False, "null": True, "kommentar": ""} for n in namen]}]
    # SEQUENCE, PACKAGE, FUNCTION, PROCEDURE, TRIGGER …: fuer Joins ohne Belang
    stat["objekt_uebersprungen"] = stat.get("objekt_uebersprungen", 0) + 1
    return []


def yaml_zerlegen(pfad: str, stat: Statistik) -> list[dict]:
    import os  # noqa: PLC0415
    groesse = os.path.getsize(pfad)
    stat["bytes"] = groesse
    if groesse > YAML_MAX:
        raise ValueError(f"YAML-Datei groesser als {YAML_MAX // 1024 // 1024} MB – nicht gelesen")
    with open(pfad, encoding="utf-8", errors="replace") as f:
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
# HAUSWISSEN mitgegeben. Bilder bleiben aussen vor (nur Text).

DOK_ENDUNGEN = (".md", ".docx", ".pdf")
DOK_MAX = 64 * 1024 * 1024
DOK_TEIL = 1500
DOK_MAX_TEILE = 2000


def _dok_absaetze(pfad: str) -> list[tuple[str, str]]:
    """(art, text) in Lesereihenfolge; art 'kopf' fuer Ueberschriften."""
    endung = pfad.lower().rsplit(".", 1)[-1]
    out: list[tuple[str, str]] = []
    if endung == "md":
        # Zeilenweise: eine Ueberschrift steht meist DIREKT vor ihrem Text, ohne
        # Leerzeile (eine Absatz-Zerlegung erkannte sie dann nicht – Waechter).
        # In einem Codeblock ist "# x" ein Kommentar, keine Ueberschrift.
        with open(pfad, encoding="utf-8", errors="replace") as f:
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
        for el in d.element.body.iterchildren():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                par = Paragraph(el, d)
                t = par.text.strip()
                if not t:
                    continue
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
        return out
    if endung == "pdf":
        import pdfplumber  # noqa: PLC0415
        with pdfplumber.open(pfad) as pdf:
            for seite in pdf.pages:
                t = seite.extract_text() or ""
                for block in re.split(r"\n\s*\n", t):
                    if block.strip():
                        out.append(("text", block.strip()))
        return out
    return out


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
    teile = dokument_teile(_dok_absaetze(pfad))
    if not teile:
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

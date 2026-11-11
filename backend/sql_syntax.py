"""Syntaxpruefung fuer SQL des SQL-Assistenten (/sql).

Zwei Schichten, weil keine allein traegt:

1. **sqlglot** parst je Dialekt. Der Parser ist bewusst NACHSICHTIG – er
   schreibt Eingaben um, statt sie abzuweisen (gemessen mit 30.25.0):
   ``SELECT a, FROM t`` wird zu ``SELECT a FROM t``, ``ORDER BY a WHERE b=1``
   wird umsortiert, ``JOIN u ON`` ohne Bedingung wird zum Kreuzprodukt.
2. **Eigene Strukturregeln** ueber die Token des sqlglot-Tokenizers (der
   kennt Zeichenketten, Kommentare und Bezeichner in Anfuehrungszeichen):
   genau diese drei Faelle plus leere WHERE/GROUP BY/ORDER BY-Listen. Sie
   gelten dialektunabhaengig.

DIALEKTE OHNE EIGENEN PARSER (HANA, DB2) werden als Standard-SQL geparst.
Ein Parserfehler ist dort nur ein HINWEIS (``hinweise``), kein Fehler – er
kann eine Besonderheit des Dialekts sein, und ein ``nicht bestanden`` aus
einem fremden Parser waere eine Aussage, die nicht gemessen ist. Die
Strukturregeln bleiben auch dort Fehler.

FEHLT sqlglot, meldet ``pruefen`` ``verfuegbar: False`` – die Oberflaeche
sagt dann „Syntaxpruefung nicht verfuegbar“ statt gruen zu zeigen
(„unbekannt“ ist eine eigene Stufe, Register). Die Strukturregeln laufen
ohne Tokenizer nicht und entfallen dann ebenfalls.
"""
from __future__ import annotations

# Dialekt des Assistenten -> sqlglot-Dialekt. "" = Standard-SQL des Parsers.
# HANA und DB2 hat sqlglot nicht (Liste der Dialekte 30.25.0 nachgesehen).
DIALEKT_PARSER = {
    "allgemein": "", "postgresql": "postgres", "mysql": "mysql", "mariadb": "mysql",
    "oracle": "oracle", "mssql": "tsql", "sqlite": "sqlite", "snowflake": "snowflake",
    "bigquery": "bigquery", "teradata": "teradata", "db2": "", "hana": "",
}
# Dialekte, deren Parserfehler nur Hinweise sind (siehe Modulkopf)
OHNE_EIGENEN_PARSER = {"db2", "hana"}

MAX_SQL = 20000

# Klauseln einer Abfrage-Ebene in der Reihenfolge, die SQL verlangt
_REIHENFOLGE = {"FROM": 1, "WHERE": 2, "GROUP": 3, "HAVING": 4, "ORDER": 5}
_KLAUSEL_NAME = {"FROM": "FROM", "WHERE": "WHERE", "GROUP": "GROUP BY", "HAVING": "HAVING",
                 "ORDER": "ORDER BY"}
# Woerter, nach denen ein Ausdruck folgen MUSS
_BRAUCHT_AUSDRUCK = {"WHERE": "WHERE", "HAVING": "HAVING", "ON": "ON", "AND": "AND", "OR": "OR"}
# Woerter, die eine neue Klausel beginnen (dann fehlt davor etwas)
_KLAUSELANFANG = {"FROM", "WHERE", "GROUP_BY", "HAVING", "ORDER_BY", "UNION", "EXCEPT",
                  "INTERSECT", "LIMIT", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS",
                  "OUTER", "SEMICOLON", "R_PAREN"}
# Satzmengen-Operatoren beginnen eine neue SELECT-Ebene
_MENGEN = {"UNION", "EXCEPT", "INTERSECT"}

# sqlglot meldet englisch; die Seite und die Reparaturrunde des Modells lesen
# deutsch. Unbekanntes bleibt woertlich stehen (zitierte Fehlermeldung).
_UEBERSETZT = (
    ("Expecting )", "Schließende Klammer fehlt"),
    ("Expecting (", "Öffnende Klammer fehlt"),
    ("Invalid expression / Unexpected token", "Unerwartetes Wort an dieser Stelle"),
    ("Required keyword:", "Ausdruck unvollständig"),
    ("Expected table name", "Tabellenname fehlt"),
)


def verfuegbar() -> bool:
    try:
        import sqlglot  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def _deutsch(beschreibung: str) -> str:
    b = (beschreibung or "").strip()
    for en, de in _UEBERSETZT:
        if b.startswith(en):
            return de
    return b or "Syntaxfehler"


def _befund(text: str, zeile=None, spalte=None, stelle: str = "") -> dict:
    return {"text": text, "zeile": zeile if isinstance(zeile, int) else None,
            "spalte": spalte if isinstance(spalte, int) else None, "stelle": (stelle or "")[:80]}


def befund_text(b: dict) -> str:
    """Eine Zeile fuer die Befundliste bzw. den Reparaturauftrag an das Modell."""
    ort = ""
    if b.get("zeile"):
        ort = f"Zeile {b['zeile']}" + (f", Spalte {b['spalte']}" if b.get("spalte") else "") + ": "
    stelle = f" (bei „{b['stelle']}“)" if b.get("stelle") else ""
    return f"Syntax – {ort}{b.get('text') or 'Syntaxfehler'}{stelle}."


def _tokens(sql: str, parser: str):
    from sqlglot.dialects.dialect import Dialect  # noqa: PLC0415
    return Dialect.get_or_raise(parser or None).tokenize(sql)


def struktur(tokens) -> list[dict]:
    """Dialektunabhaengige Regeln ueber die Token (siehe Modulkopf).

    Ebenen ueber Klammern: eine Unterabfrage und ``OVER (… ORDER BY …)``
    haben ihre eigene Reihenfolge und stoeren die der aeusseren Abfrage nicht.
    """
    befunde: list[dict] = []
    typen = [t.token_type.name for t in tokens]
    # Je Klammerebene: hoechste bisher gesehene Klausel
    stapel: list[int] = [0]
    for i, t in enumerate(tokens):
        typ = typen[i]
        nxt = typen[i + 1] if i + 1 < len(typen) else ""
        if typ == "L_PAREN":
            stapel.append(0)
            continue
        if typ == "R_PAREN":
            if len(stapel) > 1:
                stapel.pop()
            continue
        if typ in ("SELECT",) or typ in _MENGEN:
            stapel[-1] = 0
            continue
        # Ueberzaehliges Komma: vor FROM/WHERE/GROUP BY/…, vor ')' oder am Ende
        if typ == "COMMA" and (nxt in _KLAUSELANFANG or nxt == ""):
            folgt = tokens[i + 1].text if i + 1 < len(tokens) else ""
            befunde.append(_befund("Überzähliges Komma" + (f" vor {folgt.upper()}" if folgt else " am Ende"),
                                   t.line, t.col, folgt))
            continue
        wort = {"GROUP_BY": "GROUP", "ORDER_BY": "ORDER"}.get(typ, typ)
        if wort in _REIHENFOLGE:
            rang = _REIHENFOLGE[wort]
            if rang < stapel[-1]:
                vorher = next(k for k, v in _REIHENFOLGE.items() if v == stapel[-1])
                befunde.append(_befund(f"{_KLAUSEL_NAME[wort]} steht nach {_KLAUSEL_NAME[vorher]} – "
                                       "die Reihenfolge ist FROM, WHERE, GROUP BY, HAVING, ORDER BY",
                                       t.line, t.col, t.text))
            else:
                stapel[-1] = rang
            # Leere Liste nach GROUP BY / ORDER BY
            if wort in ("GROUP", "ORDER") and (nxt in _KLAUSELANFANG or nxt == ""):
                befunde.append(_befund(f"Nach {_KLAUSEL_NAME[wort]} fehlt die Liste", t.line, t.col, t.text))
        if typ in _BRAUCHT_AUSDRUCK and (nxt in _KLAUSELANFANG or nxt == ""):
            befunde.append(_befund(f"Nach {_BRAUCHT_AUSDRUCK[typ]} fehlt die Bedingung", t.line, t.col, t.text))
        if typ == "USING" and nxt != "L_PAREN":
            befunde.append(_befund("Nach USING fehlt die Spaltenliste in Klammern", t.line, t.col, t.text))
    return befunde


def pruefen(sql: str, dialekt: str = "allgemein") -> dict:
    """Syntax eines SQL-Textes. Rueckgabe:

    ``verfuegbar`` – False, wenn sqlglot fehlt (dann ``ok`` None)
    ``ok``         – True/False (Hinweise zaehlen nicht dagegen)
    ``fehler``     – Befunde ({text, zeile, spalte, stelle}), die das SQL kippen
    ``hinweise``   – Parser-Befunde bei Dialekten ohne eigenen Parser
    ``parser``     – womit geparst wurde ("" = Standard-SQL)
    ``ersatz``     – True, wenn der Dialekt keinen eigenen Parser hat
    """
    dialekt = (dialekt or "allgemein").strip().lower()
    parser = DIALEKT_PARSER.get(dialekt, "")
    ersatz = dialekt in OHNE_EIGENEN_PARSER or dialekt not in DIALEKT_PARSER
    erg = {"verfuegbar": verfuegbar(), "ok": None, "fehler": [], "hinweise": [],
           "parser": parser, "ersatz": ersatz, "dialekt": dialekt}
    if not erg["verfuegbar"]:
        return erg
    from sqlglot import parse  # noqa: PLC0415
    from sqlglot.errors import ErrorLevel, ParseError, TokenError  # noqa: PLC0415
    text = sql or ""
    if not text.strip():
        erg["fehler"].append(_befund("Kein SQL angegeben"))
        erg["ok"] = False
        return erg
    if len(text) > MAX_SQL:
        erg["fehler"].append(_befund(f"Das SQL ist länger als {MAX_SQL} Zeichen"))
        erg["ok"] = False
        return erg
    parserbefunde: list[dict] = []
    try:
        toks = _tokens(text, parser)
    except TokenError as e:
        # Unterbrochene Zeichenkette / Bezeichner: ohne Token keine weitere Pruefung
        parserbefunde.append(_befund("Zeichenkette oder Bezeichner in Anführungszeichen ist nicht geschlossen"
                                     if "tokeniz" in str(e).lower() else _deutsch(str(e))))
        toks = None
    if toks is not None:
        try:
            parse(text, read=parser or None, error_level=ErrorLevel.RAISE)
        except ParseError as e:
            for f in (e.errors or [])[:3]:
                parserbefunde.append(_befund(_deutsch(f.get("description") or ""), f.get("line"), f.get("col"),
                                             f.get("highlight") or ""))
            if not e.errors:
                parserbefunde.append(_befund(_deutsch(str(e).splitlines()[0] if str(e) else "")))
        except TokenError:
            parserbefunde.append(_befund("Zeichenkette oder Bezeichner in Anführungszeichen ist nicht geschlossen"))
        except Exception as e:  # noqa: BLE001 – ein Parserabsturz ist kein Befund ueber das SQL
            erg["hinweise"].append(_befund(f"Der Parser konnte das SQL nicht lesen ({type(e).__name__})"))
        erg["fehler"].extend(struktur(toks))
    # Dieselbe Stelle nicht zweimal melden (``a=1 AND`` findet die Strukturregel
    # UND der Parser) – die Strukturregel sagt es genauer.
    belegt = {(b["zeile"], b["spalte"]) for b in erg["fehler"] if b["zeile"]}
    parserbefunde = [b for b in parserbefunde if not b["zeile"] or (b["zeile"], b["spalte"]) not in belegt]
    (erg["hinweise"] if ersatz else erg["fehler"]).extend(parserbefunde)
    erg["ok"] = not erg["fehler"]
    return erg

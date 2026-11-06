"""Sabotage-Anker am Syntaxbaum statt am Text – fuer die ``gegen_*``-Harnesse.

WARUM (2026-11-06): vier Gegenproben bissen nicht mehr, weil ihr Anker eine
WOERTLICHE Zeile war, die der Produktcode laengst anders schreibt. Typisch:
die kind-Whitelist in ``scheduler.add_job`` bekam mit jeder neuen Auftragsart
einen Eintrag dazu (``("agent", "reminder", "wissensabgleich")`` ->
``(..., "cve_pruefung", "loesungsarchiv")``), und jede Probe, die die ganze
Zeile als Anker trug, meldete danach "SABOTAGE TRIFFT NICHT". Die Zusage
selbst ("``wissensabgleich`` steht in der Whitelist") hatte sich nie
geaendert – nur ihre Nachbarschaft.

Diese Helfer suchen deshalb das LITERAL (Tupel/Menge/Liste) ueber den
Syntaxbaum: das eine, das den gemeinten Eintrag traegt, an der gemeinten
Stelle (Funktion bzw. Zuweisungsziel). Sie liefern ``(alt, neu)`` als
Quelltext-Ausschnitt, damit der Harness seine gewohnte Trefferkontrolle
(``text.count(alt) == 1``) behaelt. Ein weiterer Eintrag in der Liste
bricht den Anker nicht mehr; ein ENTFERNTER Eintrag schon – und das ist
gewollt, denn dann existiert die Zusage nicht mehr und gehoert gemeldet,
nicht still angepasst.

Findet ein Helfer nicht GENAU ein passendes Literal, wirft er
``AssertionError`` mit Grund – das ist dieselbe Sprache wie die
Trefferkontrolle der Harnesse ("Anker 0x gefunden").

    sys.path.insert(0, str(ROOT / "tests" / "lib"))
    from sabotage_anker import eintrag_entfernen, eintrag_ergaenzen
"""
import ast

_LITERALE = (ast.Tuple, ast.Set, ast.List)


def _konstanten(knoten):
    return [e.value for e in knoten.elts if isinstance(e, ast.Constant)]


def _bereich(baum, funktion):
    """Der Teilbaum, in dem gesucht wird: die (eindeutige) Funktion oder alles."""
    if funktion is None:
        return baum
    treffer = [n for n in ast.walk(baum)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == funktion]
    assert len(treffer) == 1, f"Funktion {funktion!r} {len(treffer)}x statt 1x gefunden"
    return treffer[0]


def _literal_an_ziel(baum, ziel):
    """Das Literal, das dem Namen ``ziel`` zugewiesen wird (Modul- oder Klassenebene)."""
    gefunden = []
    for n in ast.walk(baum):
        if isinstance(n, ast.Assign):
            namen = [t.id for t in n.targets if isinstance(t, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            namen = [n.target.id]
        else:
            continue
        wert = n.value
        # frozenset({...}) / tuple([...]): das Literal im einzigen Argument
        if (isinstance(wert, ast.Call) and isinstance(wert.func, ast.Name)
                and wert.func.id in ("frozenset", "set", "tuple", "list")
                and len(wert.args) == 1 and not wert.keywords):
            wert = wert.args[0]
        if ziel in namen and isinstance(wert, _LITERALE):
            gefunden.append(wert)
    assert len(gefunden) == 1, f"Literal-Zuweisung an {ziel!r} {len(gefunden)}x statt 1x gefunden"
    return gefunden[0]


def _ausschnitt(quelle, knoten):
    seg = ast.get_source_segment(quelle, knoten)
    assert seg, "Quelltext-Ausschnitt nicht bestimmbar"
    return seg


def _neu_schreiben(knoten, elemente):
    """Dasselbe Literal (gleiche Art) mit anderen Elementen, als Quelltext."""
    if isinstance(knoten, ast.Set) and not elemente:
        return "set()"
    kopie = type(knoten)(elts=elemente, **({"ctx": knoten.ctx} if hasattr(knoten, "ctx") else {}))
    return ast.unparse(kopie)


def eintrag_entfernen(quelle, eintrag, *, funktion=None, ziel=None):
    """``(alt, neu)``: das eine Literal, das ``eintrag`` traegt, ohne ihn.

    ``funktion``: nur Literale in dieser Funktion zaehlen (z. B. ``add_job``).
    ``ziel``: nur das Literal, das diesem Namen zugewiesen wird.
    """
    baum = ast.parse(quelle)
    if ziel is not None:
        knoten = _literal_an_ziel(_bereich(baum, funktion), ziel)
        assert eintrag in _konstanten(knoten), f"{eintrag!r} steht nicht in {ziel!r}"
    else:
        kandidaten = [n for n in ast.walk(_bereich(baum, funktion))
                      if isinstance(n, _LITERALE) and eintrag in _konstanten(n)]
        assert len(kandidaten) == 1, (
            f"Literal mit {eintrag!r} {len(kandidaten)}x statt 1x gefunden"
            + (f" (in {funktion}())" if funktion else ""))
        knoten = kandidaten[0]
    rest = [e for e in knoten.elts
            if not (isinstance(e, ast.Constant) and e.value == eintrag)]
    return _ausschnitt(quelle, knoten), _neu_schreiben(knoten, rest)


def in_funktion(quelle, funktion, alt, neu):
    """``(alt, neu)``: Text-Ersatz, aber nur im Rumpf der EINEN Funktion.

    Fuer Zeilen, die woertlich in mehreren Funktionen stehen (dieselbe
    Gruppenermittlung in zwei Endpunkten) oder als eingerueckte Nachbarzeile
    (``"    if x:\\n"`` steckt auch in ``"        if x:\\n"``): der Anker wird
    auf die gemeinte Funktion begrenzt und muss DORT genau einmal stehen.
    Geliefert wird der ganze Funktions-Ausschnitt vorher/nachher.
    """
    knoten = _bereich(ast.parse(quelle), funktion)
    seg = _ausschnitt(quelle, knoten)
    n = seg.count(alt)
    assert n == 1, f"Anker in {funktion}() {n}x statt 1x: {alt[:60]!r}"
    return seg, seg.replace(alt, neu, 1)


def if_entfernen(quelle, funktion, enthaelt):
    """``(alt, "")``: das EINE ``if`` in ``funktion``, dessen Text ``enthaelt``
    traegt, samt Rumpf als ganze Zeilen – unabhaengig von Einrueckung und
    Variablennamen der Bedingung.

    ``enthaelt`` wird gegen ``ast.unparse`` verglichen, also in dessen
    Schreibweise (EINFACHE Anfuehrungszeichen, Register: "``ast.unparse``
    normiert auf einfache Anfuehrungszeichen"), z. B. ``"eintrag['mac'] = 1"``.
    Bei verschachtelten ``if`` zaehlt das innerste.
    """
    knoten = _bereich(ast.parse(quelle), funktion)
    treffer = [n for n in ast.walk(knoten)
               if isinstance(n, ast.If) and enthaelt in ast.unparse(n)]
    innerste = [n for n in treffer
                if not any(m is not n and m in ast.walk(n) for m in treffer)]
    assert len(innerste) == 1, (
        f"if mit {enthaelt!r} in {funktion}() {len(innerste)}x statt 1x gefunden")
    n = innerste[0]
    zeilen = quelle.splitlines(keepends=True)
    return "".join(zeilen[n.lineno - 1:n.end_lineno]), ""


def eintrag_ergaenzen(quelle, ziel, eintrag, *, funktion=None):
    """``(alt, neu)``: das Literal, das ``ziel`` zugewiesen wird, plus ``eintrag``.

    Steht ``eintrag`` schon darin, ist die Sabotage gegenstandslos – und die
    Zusage ("``eintrag`` gehoert NICHT dazu") existiert nicht mehr: Abbruch.
    """
    knoten = _literal_an_ziel(_bereich(ast.parse(quelle), funktion), ziel)
    assert eintrag not in _konstanten(knoten), f"{eintrag!r} steht schon in {ziel!r}"
    return (_ausschnitt(quelle, knoten),
            _neu_schreiben(knoten, [*knoten.elts, ast.Constant(eintrag)]))

"""Schema-Graph: strukturierte Antworten fuer Chat-Werkzeuge UND die Seite /sql.

Suche, Tabellendetail, Join-Pfad und Status gibt es zweimal in der
Oberflaeche – als Werkzeug im Chat (Text) und als Endpunkt fuer ``/sql``
(JSON). Beide formatieren nur noch, was hier entsteht; zwei Fassungen der
Abfragen liefen beim naechsten Feinschliff auseinander, und dann saehe ein
Benutzer im Chat andere Tabellen als auf der Seite – oder, schlimmer, eine
Fassung vergaesse den Sichtbarkeitsfilter.

Jede Funktion nimmt ``erlaubt`` (sichtbare Schema-Quellen, siehe
``schema_graph_rag``). Was nicht sichtbar ist, gibt es hier nicht: keine
Treffer, keine Kanten, keine Zaehler.
"""
from __future__ import annotations

import json

from backend import schema_graph_rag as rag
from backend import schema_graph_store as store

MAX_SPALTEN_ANZEIGE = 400
MAX_KANTEN_ANZEIGE = 60


def suche_info(con, begriffe: list[str], n: int, erlaubt) -> list[dict]:
    out = []
    for oid, _p in rag.suche(con, begriffe, limit=n, erlaubt=erlaubt):
        t = rag.tabelle_laden(con, oid, erlaubt)
        if t:
            out.append({"name": t["name"], "art": t["art"], "spalten_n": len(t["spalten"]),
                        "bereich": t["bereich"], "kommentar": t["kommentar"][:300]})
    return out


def _kante(art, vs, ns) -> dict:
    a, b = json.loads(vs or "[]"), json.loads(ns or "[]")
    return {"art": art, "paare": [[x, y] for x, y in zip(a, b)]}


def tabelle_info(con, name: str, erlaubt) -> dict:
    """{"tabelle": {...}} oder {"fehler", "vorschlaege"}."""
    o = rag.finde_objekt(con, name, erlaubt)
    letzter = name.lower().rsplit(".", 1)[-1]
    filt, werte = rag._filter(erlaubt)
    if o is None:
        vorschlaege = [r[0] for r in con.execute(
            f"SELECT o.schluessel FROM objekt o WHERE o.name_l LIKE ?{filt} LIMIT 10",
            ["%" + letzter + "%"] + werte)]
        return {"fehler": "nicht_gefunden", "vorschlaege": vorschlaege}
    if o[0] == "mehrdeutig":
        treffer = [r[0] for r in con.execute(
            f"SELECT o.schluessel FROM objekt o WHERE o.name_l=?{filt} LIMIT 20", [letzter] + werte)]
        return {"fehler": "mehrdeutig", "vorschlaege": treffer}
    t = rag.tabelle_laden(con, o[0], erlaubt)
    if t is None:
        return {"fehler": "nicht_gefunden", "vorschlaege": []}
    raus = [{"ziel": z, **_kante(art, vs, ns)} for art, z, vs, ns in con.execute(
        "SELECT k.art, o.schluessel, k.von_spalten, k.nach_spalten FROM kante k "
        f"JOIN objekt o ON o.id=k.nach WHERE k.von=?{filt}", [t["id"]] + werte)]
    rein = [{"quelle": z, **_kante(art, vs, ns)} for art, z, vs, ns in con.execute(
        "SELECT k.art, o.schluessel, k.von_spalten, k.nach_spalten FROM kante k "
        f"JOIN objekt o ON o.id=k.von WHERE k.nach=?{filt}", [t["id"]] + werte)]
    return {"tabelle": {
        "name": t["name"], "art": t["art"], "kommentar": t["kommentar"], "bereich": t["bereich"],
        "spalten_gesamt": len(t["spalten"]),
        "spalten": [{"name": s["name"], "typ": s["typ"] or "", "pk": bool(s["pk"]),
                     "nullable": bool(s["nullable"]), "kommentar": s["kommentar"] or ""}
                    for s in t["spalten"][:MAX_SPALTEN_ANZEIGE]],
        "raus_gesamt": len(raus), "raus": raus[:MAX_KANTEN_ANZEIGE],
        "rein_gesamt": len(rein), "rein": rein[:MAX_KANTEN_ANZEIGE]}}


def verbindung_info(con, von: str, nach: str, erlaubt, max_tiefe: int = 6) -> dict:
    a, b = rag.finde_objekt(con, von, erlaubt), rag.finde_objekt(con, nach, erlaubt)
    for roh, o in ((von, a), (nach, b)):
        if o is None:
            return {"fehler": "nicht_gefunden", "name": roh}
        if o[0] == "mehrdeutig":
            return {"fehler": "mehrdeutig", "name": roh}
    pfad = rag.pfad_zu_menge(con, a[0], {b[0]}, max_tiefe=max_tiefe, erlaubt=erlaubt)
    if pfad is None:
        return {"fehler": "kein_pfad", "von": a[1], "nach": b[1], "max_tiefe": max_tiefe}
    namen = {r[0]: r[1] for r in con.execute(
        f"SELECT id, schluessel FROM objekt WHERE id IN ({','.join('?' * len(pfad))})", pfad)}
    schritte = []
    for x, y in zip(pfad, pfad[1:]):
        k = [e for e in rag.kanten_zwischen(con, [x, y]) if {e["von"], e["nach"]} == {x, y}]
        if not k:
            schritte.append({"von": namen[x], "nach": namen[y], "bedingung": "", "art": "sicht"})
            continue
        e = k[0]
        bed = " AND ".join(f"{namen[e['von']]}.{p} = {namen[e['nach']]}.{q}"
                           for p, q in zip(e["von_spalten"], e["nach_spalten"]))
        schritte.append({"von": namen[x], "nach": namen[y], "bedingung": bed, "art": e["art"]})
    return {"von": a[1], "nach": b[1], "schritte": schritte}


def graph_info(erlaubt, schemata_cfg: list[dict]) -> dict:
    """Stand des Graphen, je Schema gezaehlt. ``erlaubt`` (Menge oder None =
    alle) beschraenkt die Liste – ein nicht gewaehltes Schema erscheint dann
    weder mit Namen noch mit Zahlen. Ein Schema ohne erfasste Objekte steht mit
    Nullen da (frisch angelegt oder noch nicht erfasst)."""
    con = store.graph_lesen()
    if con is None:
        return {"vorhanden": False, "stand": None,
                "schemata": [{"id": q["id"], "name": q["name"], "tabellen": 0, "sichten": 0, "spalten": 0,
                              "dokumente": 0}
                             for q in schemata_cfg or [] if erlaubt is None or q["id"] in erlaubt]}
    try:
        meta = {k: v for k, v in con.execute("SELECT k, v FROM meta")}
    finally:
        con.close()
    try:
        je = json.loads(meta.get("je_quelle") or "{}")
    except ValueError:
        je = {}
    out = []
    for q in schemata_cfg or []:
        if erlaubt is not None and q["id"] not in erlaubt:
            continue
        z = je.get(q["id"]) or {}
        out.append({"id": q["id"], "name": q["name"], "tabellen": int(z.get("tabelle", 0)),
                    "sichten": int(z.get("sicht", 0)), "spalten": int(z.get("spalten", 0)),
                    "dokumente": int(z.get("dokumente", 0))})
    return {"vorhanden": True, "stand": meta.get("stand"), "schemata": out}

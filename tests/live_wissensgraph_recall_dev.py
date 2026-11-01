#!/usr/bin/env python3
"""Recall-Messung (DEV): Suche mit und ohne Graph-Kanal, drei Fragensaetze.

Plan Phase 3: "Einschalten erst nach Messung – Satz von Prueffragen mit
bekannten Zieldokumenten, Recall@k mit und ohne Graph, je 3 Wiederholungen."

* Fragen: das eingestellte Modell formuliert je Dokument EINE Frage aus einem
  zufaelligen Abschnitt, ohne Titel/Dateinamen zu nennen. Drei Saetze mit
  verschiedenem Zufallskeim = drei Wiederholungen (die Suche selbst ist
  deterministisch – ein Satz laeuft zur Kontrolle zweimal).
* Gemessen: Recall@1/3/5/8 (Zieldokument unter den ersten k DOKUMENTEN der
  Treffer), MRR, Dauer je Suche, und wie oft der Graph-Kanal ueberhaupt etwas
  beitraegt.
* Nur lesend gegen Index und Graph; die Fragen liegen im Ablageordner der
  Messung (Echtinhalte, nicht im Repo).

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_wissensgraph_recall_dev.py [ablage] [je_satz]
"""
import asyncio
import json
import os
import random
import statistics
import sys
import time

sys.path.insert(0, "/opt/jarvis")

from backend import wissensgraph as wg                          # noqa: E402
from backend import wissensgraph_extraktion as wgx              # noqa: E402
from backend.tools import knowledge as kn                       # noqa: E402

ABLAGE = sys.argv[1] if len(sys.argv) > 1 else "/opt/jarvis/data/graph_probe"
JE_SATZ = int(sys.argv[2]) if len(sys.argv) > 2 else 30
# 11/22/33 waren die Saetze, an denen das fragebezogene Modell eingestellt
# wurde; 44/55/66 sind die Pruefsaetze, die es vorher nicht gesehen hat.
SAETZE = (11, 22, 33, 44, 55, 66)
KS = (1, 3, 5, 8)
MAX_TREFFER = 8

AUFTRAG = """AUFGABE: Formuliere EINE Frage, die ein Mitarbeiter stellen wuerde und die der
Text zwischen den Markern beantwortet. Nenne dabei weder einen Dokumenttitel noch einen
Dateinamen und zitiere keinen ganzen Satz. Gib NUR die Frage aus, eine Zeile.

=== TEXT-BEGINN {m} ===
{text}
=== TEXT-ENDE {m} ===
"""


async def fragen_erzeugen(seed: int, docs: list[str], vs) -> list[dict]:
    datei = os.path.join(ABLAGE, f"recall_fragen_{seed}.json")
    if os.path.exists(datei):
        return json.load(open(datei, encoding="utf-8"))
    st = wgx.einstellungen(frisch=True)
    provider, modell, _ = wgx.provider_holen(st)
    rnd = random.Random(seed)
    auswahl = rnd.sample(docs, min(JE_SATZ, len(docs)))
    raus = []
    from backend import fremdtext
    for m in auswahl:
        chunks, _mt = vs.chunks_fuer(wg.absolut(m))
        if not chunks:
            continue
        text = chunks[rnd.randrange(len(chunks))]
        auftrag = AUFTRAG.format(m=f"{seed:x}{rnd.randrange(1 << 20):x}",
                                 text=fremdtext.entschaerfen(wgx.kopf_entfernen(text), wgx._struktur()))
        roh, _u = await wgx.modell_aufruf(provider, modell, auftrag)
        frage = " ".join((roh or "").strip().splitlines()[:1]).strip().strip('"')
        if 10 <= len(frage) <= 300:
            raus.append({"frage": frage, "ziel": m})
    json.dump(raus, open(datei, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return raus


AUFTRAG_PAAR = """AUFGABE: Zwei Texte zwischen den Markern behandeln beide "{begriff}".
Formuliere EINE Frage, die ein Mitarbeiter stellen wuerde und fuer deren Antwort man
BEIDE Texte braucht. Nenne weder Dokumenttitel noch Dateinamen. Gib NUR die Frage aus.

=== TEXT-A-BEGINN {m} ===
{a}
=== TEXT-A-ENDE {m} ===

=== TEXT-B-BEGINN {m} ===
{b}
=== TEXT-B-ENDE {m} ===
"""


def _abschnitt(chunks, begriff, rnd):
    passend = [c for c in chunks if begriff.lower() in c.lower()]
    return (passend or chunks)[rnd.randrange(len(passend or chunks))]


async def paare_erzeugen(seed: int, docs: list[str], vs) -> list[dict]:
    """Je Paar: zwei Dokumente, die einen SELTENEN Begriff teilen (2–4 Dokumente,
    kein Hub), und eine Frage, die beide braucht. ``b`` ist das zweite Dokument."""
    datei = os.path.join(ABLAGE, f"recall_paare_{seed}.json")
    if os.path.exists(datei):
        return json.load(open(datei, encoding="utf-8"))
    st = wgx.einstellungen(frisch=True)
    provider, modell, _ = wgx.provider_holen(st)
    rnd = random.Random(seed * 7)
    erlaubt = set(docs)
    selten = [k for k in wg.graph()["knoten"]
              if k["typ"] != wg.TYP_QUELLE and 2 <= len(set(k["sources"]) & erlaubt) <= 4]
    rnd.shuffle(selten)
    from backend import fremdtext
    raus, benutzt = [], set()
    for k in selten:
        if len(raus) >= max(10, JE_SATZ // 2):
            break
        a, b = rnd.sample(sorted(set(k["sources"]) & erlaubt), 2)
        if (a, b) in benutzt:
            continue
        benutzt.add((a, b))
        ca, _ = vs.chunks_fuer(wg.absolut(a))
        cb, _ = vs.chunks_fuer(wg.absolut(b))
        if not ca or not cb:
            continue
        sx = wgx._struktur()
        auftrag = AUFTRAG_PAAR.format(begriff=fremdtext.entschaerfen(k["name"], sx), m=f"{seed:x}{rnd.randrange(1 << 20):x}",
                                      a=fremdtext.entschaerfen(wgx.kopf_entfernen(_abschnitt(ca, k["name"], rnd)), sx),
                                      b=fremdtext.entschaerfen(wgx.kopf_entfernen(_abschnitt(cb, k["name"], rnd)), sx))
        roh, _u = await wgx.modell_aufruf(provider, modell, auftrag)
        frage = " ".join((roh or "").strip().splitlines()[:1]).strip().strip('"')
        if 10 <= len(frage) <= 300:
            raus.append({"frage": frage, "a": a, "b": b, "begriff": k["name"]})
    json.dump(raus, open(datei, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return raus


def dokumente(treffer) -> list[str]:
    reihe = []
    for _s, fp, _t in treffer:
        m = wg.manifest_form(fp)
        if m not in reihe:
            reihe.append(m)
    return reihe


def messen(fragen, vs, mit_graph: bool) -> dict:
    def rangliste(start, erl, frage):
        return [(wg.absolut(m), s) for m, s, _ in wg.relevanz(frage, start, erl)]
    treffer_k = {k: 0 for k in KS}
    rr, zeiten, beitrag = [], [], 0
    for f in fragen:
        t0 = time.monotonic()
        erg, _a = vs.search_hybrid_ex(f["frage"], MAX_TREFFER,
                                      graph_rangliste=rangliste if mit_graph else None)
        zeiten.append(time.monotonic() - t0)
        docs = dokumente(erg)
        pos = docs.index(f["ziel"]) + 1 if f["ziel"] in docs else None
        for k in KS:
            if pos is not None and pos <= k:
                treffer_k[k] += 1
        rr.append(1.0 / pos if pos else 0.0)
        if mit_graph:
            start = [fp for _s, fp, _t in erg][:5]
            if wg.relevanz(f["frage"], start):
                beitrag += 1
    n = max(1, len(fragen))
    return {"n": len(fragen), **{f"recall@{k}": round(treffer_k[k] / n, 3) for k in KS},
            "mrr": round(sum(rr) / n, 3), "ms_median": round(1000 * statistics.median(zeiten), 1),
            "graph_traegt_bei": beitrag}


async def main() -> int:
    vs = kn._get_vector_store()
    if vs is None or not vs.chunk_count():
        print("ABBRUCH – kein Wissensindex")
        return 2
    st = wgx.einstellungen(frisch=True)
    quellen = [q["pfad"] for q in wg.quellen_alle() if wgx.im_umfang(q["pfad"], st["gruppen"])]
    indexiert = {wg.manifest_form(p) for p in vs.get_indexed_files()}
    docs = sorted(set(quellen) & indexiert)
    print(f"Positivkontrolle: {len(docs)} Dokumente mit Graph UND Index, Graph {wg.kennzahlen()}")
    if len(docs) < 20:
        print("ABBRUCH – zu wenige Dokumente fuer eine Messung")
        return 2
    ergebnisse = []
    for seed in SAETZE:
        fragen = await fragen_erzeugen(seed, docs, vs)
        ohne = messen(fragen, vs, False)
        mit = messen(fragen, vs, True)
        ergebnisse.append({"satz": seed, "ohne": ohne, "mit": mit})
        print(f"Satz {seed}: ohne {ohne}")
        print(f"         mit  {mit}")
    kontrolle = messen(await fragen_erzeugen(SAETZE[0], docs, vs), vs, True)
    # Verglichen werden die TREFFER-Kennzahlen – die Dauer schwankt natuerlich
    # (erste Fassung verglich sie mit und meldete "abweichend", Sonde falsch).
    def ohne_zeit(d):
        return {k: v for k, v in d.items() if k != "ms_median"}
    gleich = ohne_zeit(kontrolle) == ohne_zeit(ergebnisse[0]["mit"])
    print(f"Determinismus (Satz {SAETZE[0]} zweimal mit Graph): {'gleich' if gleich else 'ABWEICHEND'}")
    print("\nMittel ueber die Saetze (ohne → mit):")
    for schl in [f"recall@{k}" for k in KS] + ["mrr", "ms_median"]:
        o = [e["ohne"][schl] for e in ergebnisse]
        m = [e["mit"][schl] for e in ergebnisse]
        print(f"  {schl:10} {statistics.mean(o):.3f} → {statistics.mean(m):.3f}   "
              f"(je Satz: {o} → {m})")
    # ── Zusammenhangsfragen: zwei Dokumente teilen einen seltenen Begriff ──
    paar_erg = []
    for seed in SAETZE:
        paare = await paare_erzeugen(seed, docs, vs)
        zeile = {"satz": seed, "n": len(paare)}
        for name, mit_graph in (("ohne", False), ("mit", True)):
            beide = {k: 0 for k in KS}
            partner = {k: 0 for k in KS}
            for f in paare:
                erg, _a = vs.search_hybrid_ex(f["frage"], MAX_TREFFER,
                                              graph_rangliste=(lambda st, e, fr: [(wg.absolut(m), sc) for m, sc, _ in wg.relevanz(fr, st, e)]) if mit_graph else None)
                d = dokumente(erg)
                for k in KS:
                    oben = set(d[:k])
                    beide[k] += int(f["a"] in oben and f["b"] in oben)
                    partner[k] += int(bool(oben & {f["a"], f["b"]}))
            n = max(1, len(paare))
            zeile[name] = {**{f"beide@{k}": round(beide[k] / n, 3) for k in KS},
                           **{f"eins@{k}": round(partner[k] / n, 3) for k in KS}}
        paar_erg.append(zeile)
        print(f"Paare {seed} (n={zeile['n']}): ohne {zeile['ohne']}")
        print(f"                mit  {zeile['mit']}")
    print("\nZusammenhangsfragen, Mittel (ohne → mit):")
    for schl in [f"beide@{k}" for k in KS] + [f"eins@{k}" for k in KS]:
        o = [z["ohne"][schl] for z in paar_erg]
        m = [z["mit"][schl] for z in paar_erg]
        print(f"  {schl:10} {statistics.mean(o):.3f} → {statistics.mean(m):.3f}   (je Satz: {o} → {m})")
    json.dump({"einzel": ergebnisse, "paare": paar_erg},
              open(os.path.join(ABLAGE, "recall_ergebnis.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0 if gleich else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

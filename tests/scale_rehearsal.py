#!/usr/bin/env python3
"""Maßstabsprobe des Wissens-Index – VOR dem Rollout auf das Echt-System.

Warum das noetig ist: Die Fixes aus dem Code-Review vom 2026-07-30 sind gegen
12 Chunks und synthetische Messungen verifiziert. Genau diese Luecke hat A-1
jahrelang verdeckt ("auf DEV liegen 11 Chunks – der Lauf ist dort in
Sekundenbruchteilen fertig"). Dieses Skript stellt Produktionsgroesse her und
prueft die Fixes dort, wo sie wirken sollen.

ISOLATION – das Skript fasst NICHTS Echtes an:
  * eigener Wissensordner unter /tmp, eigener Vektorspeicher unter /tmp
  * Lauf-Protokoll und TF-IDF-Cache auf temporaere Pfade umgebogen
  * knowledge_groups.prune / auto_assign_system_files sind STILLGELEGT –
    ohne das wuerde der Lauf die Gruppen-Zuordnungen der echten Dateien
    loeschen (prune entfernt alles, was nicht in der uebergebenen Liste steht)

Lauf auf DEV:
    cd /opt/jarvis && env HOME=/home/jarvis venv/bin/python tests/scale_rehearsal.py
"""

import gc
import os
import random
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.tools.knowledge as K          # noqa: E402
import backend.tools.vector_store as VS      # noqa: E402
import backend.knowledge_groups as KG        # noqa: E402

# ── Umfang (an der Produktion orientiert: 893 Dateien, ~10-16k Chunks) ──
N_DATEIEN = int(os.environ.get("N_DATEIEN", "900"))
SEED = 20260731

_wortschatz = """
konfiguration schnittstelle datenuebernahme mandant benutzerkonto protokoll
installation aktualisierung sicherung wiederherstellung netzlaufwerk freigabe
zertifikat verschluesselung anmeldung abmeldung berechtigung gruppe rolle
fehlermeldung ursache abhilfe voraussetzung einschraenkung hinweis warnung
labordaten befund auftrag patient praxis arztbrief formular etikett drucker
schnittstellenparameter zeitstempel dateiname verzeichnis pfad endung format
server dienst neustart zeitueberschreitung verbindung antwortzeit auslastung
""".split()

_bezeichner = ["@STR_UCASE", "@STR_LCASE", "LDT30", "GDT21", "ERR_4711",
               "ERR_0815", "CFG_TIMEOUT", "MAX_RETRY", "SRV_PORT_8443"]


def _absatz(rng, n):
    woerter = []
    while len(woerter) < n:
        satz = rng.sample(_wortschatz, rng.randint(6, 14))
        if rng.random() < 0.06:
            satz.insert(rng.randint(0, len(satz)), rng.choice(_bezeichner))
        woerter.extend(satz)
        woerter[-1] += "."
    return " ".join(woerter[:n])


def erzeuge_bestand(ordner: Path, n: int) -> dict:
    rng = random.Random(SEED)
    ordner.mkdir(parents=True, exist_ok=True)
    woerter_gesamt = 0
    for i in range(n):
        unter = ordner / f"bereich_{i % 12:02d}"
        unter.mkdir(exist_ok=True)
        # Groessenmischung wie in echten Bestaenden: viele mittlere Dokumente,
        # einige sehr grosse Handbuecher.
        w = rng.choice([250, 400, 800, 1200, 1800, 2500, 4000, 6000])
        text = f"# Dokument {i}\n\n" + "\n\n".join(_absatz(rng, 200) for _ in range(max(1, w // 200)))
        (unter / f"dok_{i:04d}.md").write_text(text, encoding="utf-8")
        woerter_gesamt += w
    return {"dateien": n, "woerter": woerter_gesamt}


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def kopfzeile(t):
    print("\n" + "─" * 66)
    print(t)
    print("─" * 66, flush=True)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_scale_"))
    wissen = tmp / "wissen"
    vstore = tmp / "vector_store"
    ergebnis = []

    # ── Isolation ────────────────────────────────────────────────────────
    vs = VS.VectorStore(vstore)
    K._get_vector_store = lambda: vs
    K._get_folders = lambda: [wissen]
    K.LAST_INDEX_RUN_PATH = tmp / "last_index.json"
    K.INDEX_CACHE_PATH = tmp / "knowledge_index.json"
    gruppen_aufrufe = []
    KG.prune = lambda *a, **kw: gruppen_aufrufe.append("prune") or 0
    KG.auto_assign_system_files = lambda *a, **kw: gruppen_aufrufe.append("assign") or 0

    print("=" * 66)
    print("MASSSTABSPROBE Wissens-Index")
    print("=" * 66)
    print(f"Arbeitsordner: {tmp}")
    print(f"Modell:        {VS.MODEL_NAME}")

    kopfzeile(f"1. Bestand erzeugen ({N_DATEIEN} Dateien)")
    t0 = time.time()
    info = erzeuge_bestand(wissen, N_DATEIEN)
    mb = sum(f.stat().st_size for f in wissen.rglob("*.md")) / 1024 / 1024
    print(f"   {info['dateien']} Dateien, {info['woerter']:,} Woerter, {mb:.1f} MB "
          f"in {time.time()-t0:.1f}s")

    # ── 2. Voll-Reindex ──────────────────────────────────────────────────
    kopfzeile("2. Voll-Reindex (der Lauf, der historisch OOM-gekillt wurde)")
    rss_vorher = rss_mb()
    t0 = time.time()
    res = K.force_reindex()
    dauer = time.time() - t0
    rss_nachher = rss_mb()
    chunks = vs.chunk_count()
    print(f"   Dauer:        {dauer:.1f}s  ({chunks/max(dauer,0.001):.0f} Chunks/s)")
    print(f"   Ergebnis:     {res['indexed_files']} Dateien, {chunks:,} Chunks, "
          f"{res.get('failed_files', 0)} fehlgeschlagen")
    print(f"   Speicher:     {rss_vorher:.0f} MB -> {rss_nachher:.0f} MB "
          f"(Zuwachs {rss_nachher-rss_vorher:.0f} MB)")
    idx_mb = (vstore / "faiss_index.bin").stat().st_size / 1024 / 1024
    meta_mb = (vstore / "faiss_meta.json").stat().st_size / 1024 / 1024
    print(f"   Auf Platte:   Index {idx_mb:.1f} MB + Meta {meta_mb:.1f} MB")
    ergebnis.append(("Voll-Reindex ohne Fehler", res.get("failed_files", 0) == 0))
    ergebnis.append(("alle Dateien indiziert", res["indexed_files"] == N_DATEIEN))
    ergebnis.append(("Speicherzuwachs unter 2 GB", (rss_nachher - rss_vorher) < 2048))

    # ── 3. Suche: kalt und warm ──────────────────────────────────────────
    kopfzeile("3. Suchlatenz (kalt = inkl. BM25-Aufbau)")
    t0 = time.time()
    treffer = vs.search_hybrid("wie konfiguriere ich die schnittstelle fuer mandanten", 8,
                               weight_fn=K._learned_weight)
    kalt = (time.time() - t0) * 1000
    warm = []
    for q in ("ERR_4711 ursache abhilfe", "netzlaufwerk freigabe zertifikat",
              "wie starte ich den dienst neu", "@STR_UCASE grossschreibung",
              "labordaten uebernahme aus dem formular"):
        t0 = time.time()
        vs.search_hybrid(q, 8, weight_fn=K._learned_weight)
        warm.append((time.time() - t0) * 1000)
    print(f"   kalt:         {kalt:.0f} ms  ({len(treffer)} Treffer)")
    print(f"   warm:         {min(warm):.0f}–{max(warm):.0f} ms "
          f"(Median {sorted(warm)[len(warm)//2]:.0f} ms)")
    ergebnis.append(("warme Suche unter 250 ms", max(warm) < 250))

    # ── 4. Gelernte Notiz: BM25 inkrementell? ────────────────────────────
    kopfzeile("4. Gelernte Notiz anhaengen (B-2: BM25 darf NICHT neu bauen)")
    gen_vor, lexgen_vor = vs._gen, vs._lex_gen
    notiz = wissen / "bereich_00" / "gelernt_probe.md"
    notiz.write_text("# Gelernt: Portfrage\n\nDer Dienst laeuft auf SRV_PORT_8443.\n",
                     encoding="utf-8")
    t0 = time.time()
    vs.add_chunks(str(notiz), K._chunk_text(notiz.read_text(encoding="utf-8")),
                  notiz.stat().st_mtime)
    anhaengen = (time.time() - t0) * 1000
    inkrementell = (vs._lex_gen == vs._gen)
    t0 = time.time()
    vs.search_hybrid("SRV_PORT_8443", 8, weight_fn=K._learned_weight)
    danach = (time.time() - t0) * 1000
    print(f"   Anhaengen:    {anhaengen:.0f} ms (inkl. Einbettung + Speichern)")
    print(f"   BM25 danach:  {'inkrementell nachgetragen' if inkrementell else 'VOLLAUFBAU NOETIG'}")
    print(f"   Suche danach: {danach:.0f} ms")
    ergebnis.append(("BM25 wurde inkrementell nachgetragen", inkrementell))
    ergebnis.append(("Suche nach dem Lernen ohne Vollaufbau-Strafe", danach < 250))
    _ = (gen_vor, lexgen_vor)

    # ── 5. A-2: nicht erreichbarer Ordner ────────────────────────────────
    kopfzeile("5. A-2 im Ernstfall: Ordner nicht erreichbar")
    chunks_vor = vs.chunk_count()
    echt_exists = K._safe_exists
    echt_delay = K.RETRY_DELAY_SEC
    K.RETRY_DELAY_SEC = 0          # sonst 2x15s Wartezeit im Neuversuch
    K._safe_exists = lambda p, timeout=2.0: False          # "Mount tot"
    K.invalidate_files_cache()
    K._rebuild_vector_index([wissen], K._get_max_bytes(), force=False)   # Suchpfad
    nach_suche = vs.chunk_count()
    # Voll-Lauf bei totem Laufwerk MUSS abbrechen statt zu leeren.
    fehler = None
    try:
        K.force_reindex()
    except Exception as e:  # noqa: BLE001
        fehler = str(e)
    nach_reindex = vs.chunk_count()
    K._safe_exists = echt_exists
    K.RETRY_DELAY_SEC = echt_delay
    K.invalidate_files_cache()
    print(f"   vorher:              {chunks_vor:,} Chunks")
    print(f"   nach Suche:          {nach_suche:,} Chunks")
    print(f"   nach Voll-Reindex:   {nach_reindex:,} Chunks")
    print(f"   Abbruchmeldung:      {(fehler or '(keine)')[:70]}")
    ergebnis.append(("Suche laesst den Index unangetastet", nach_suche == chunks_vor))
    ergebnis.append(("Voll-Reindex bricht ab statt zu leeren", fehler is not None))
    ergebnis.append(("Index nach dem Abbruch unveraendert", nach_reindex == chunks_vor))

    # ── 6. B-4: Sammel-Entfernung ────────────────────────────────────────
    kopfzeile("6. B-4: 50 Dateien loeschen – ein Neuaufbau statt 50")
    rebuilds = {"n": 0}
    echt_rebuild = VS.VectorStore._rebuild

    def gezaehlt(self, meta, vektoren):
        rebuilds["n"] += 1
        return echt_rebuild(self, meta, vektoren)

    VS.VectorStore._rebuild = gezaehlt
    weg = sorted(wissen.rglob("dok_*.md"))[:50]
    for f in weg:
        f.unlink()
    K.invalidate_files_cache()
    t0 = time.time()
    res_del = K.force_reindex()
    dauer_del = time.time() - t0
    VS.VectorStore._rebuild = echt_rebuild
    print(f"   Index-Neuaufbauten:  {rebuilds['n']} (alter Stand: 50)")
    print(f"   Dauer:               {dauer_del:.1f}s")
    print(f"   Dateien danach:      {res_del['indexed_files']} (erwartet {N_DATEIEN-50+1})")
    ergebnis.append(("hoechstens 2 Index-Neuaufbauten", rebuilds["n"] <= 2))
    ergebnis.append(("Dateizahl stimmt", res_del["indexed_files"] == N_DATEIEN - 50 + 1))

    # ── 7. Inkrementeller Lauf ohne Aenderungen ──────────────────────────
    kopfzeile("7. Reindex ohne Aenderungen (mtime-Vergleich)")
    t0 = time.time()
    K.force_reindex(incremental=True)
    leerlauf = time.time() - t0
    print(f"   Dauer:        {leerlauf:.1f}s (nichts neu einzubetten)")
    ergebnis.append(("Leerlauf-Reindex unter 60 s", leerlauf < 60))

    # ── Bilanz ───────────────────────────────────────────────────────────
    kopfzeile("Bilanz")
    ok = 0
    for name, gut in ergebnis:
        print(("   ✅ " if gut else "   ❌ ") + name)
        ok += 1 if gut else 0
    print(f"\n   {ok}/{len(ergebnis)} Prüfungen bestanden")
    print(f"   Gruppen-Funktionen stillgelegt, Aufrufe abgefangen: {len(gruppen_aufrufe)}")

    shutil.rmtree(tmp, ignore_errors=True)
    gc.collect()
    print(f"   Arbeitsordner entfernt: {tmp}")
    return 0 if ok == len(ergebnis) else 1


if __name__ == "__main__":
    sys.exit(main())

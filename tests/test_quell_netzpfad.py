#!/usr/bin/env python3
"""Waechter: die Quellangabe im Chat nennt den NETZWERKPFAD, nicht share_N.

WAS GEMELDET WURDE (Betreiber, 2026-09-08)
------------------------------------------
Eine /chat-Antwort gab als Quelle aus: "Quelle: SAP-MARIS-Anleitung
(.one-Datei), Ordner share_0/0039_Maris/Anleitungen SAP.one". ``share_0`` ist
der EINHAENGEPUNKT auf dem Server – eine Nummer, die der Benutzer nicht kennt
und die er nirgends oeffnen kann. Auf DEV gemessen sah das Modell woertlich
``/mnt/jarvis-kb/share_2/0039_Maris/Informationen.one``; gemeint ist
``\\\\191.100.147.90\\OneNote_text_Jasmin\\0039_Maris\\Informationen.one``.

WAS DIESER WAECHTER PRUEFT – die EIGENSCHAFT, nicht den Wortlaut
----------------------------------------------------------------
1. ``mount_quelle.netzpfad`` bildet den Einhaengepunkt auf die Freigabe ab –
   inklusive der Praefix-Falle (``share_20`` ist nicht ``share_2``), der
   Windows-Schreibweise im Altbestand und fail-open bei Unbekanntem.
2. ``KnowledgeTool.execute`` wird WIRKLICH AUSGEFUEHRT: der Netzwerkpfad steht
   in der Trefferzeile, der Serverpfad bleibt daneben erreichbar (die
   ``xlsx_*``/``pdf_*``-Werkzeuge brauchen ihn – ohne ihn waere die Anzeige
   schoen und die Weiterverarbeitung tot).
3. ``_clean_doc_refs`` LOESCHT den Netzwerkpfad NICHT. Das ist der Punkt, an
   dem die Zusage sonst still gebrochen waere: die Regel "nackte lokale
   Dokumentpfade entfernen" hat aus "Quelle: srv:/export/Handbuch.pdf" ein
   "Quelle: srv:" gemacht – und aus dem ALTEN Serverpfad
   "/mnt/jarvis-kb/share_0/…/Handbuch.pdf" gar nichts.
4. Der Avatar benutzt DIESELBE Funktion – zwei Fassungen liefen beim naechsten
   Feinschliff auseinander.

Aufruf: python3 tests/test_quell_netzpfad.py
"""

import ast
import asyncio
import os
import re
import sys
import tempfile
import types
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

OK = FAIL = 0


def check(bedingung, text):
    global OK, FAIL
    if isinstance(bedingung, str):          # vertauschte Argumente
        print("ABBRUCH: check(text, bedingung) – Argumente vertauscht")
        sys.exit(2)
    if bedingung:
        OK += 1
        print(f"  \033[32mOK\033[0m   {text}")
    else:
        FAIL += 1
        print(f"  \033[31mFAIL\033[0m {text}")


def sicher(fn, text):
    """Ein Wurf ist ein FAIL, kein Abbruch – sonst fehlt die Bilanzzeile."""
    try:
        check(fn(), text)
    except Exception as e:                  # noqa: BLE001
        check(False, f"{text} [wirft: {type(e).__name__}: {e}]")


def ohne_kommentare(quelltext: str) -> str:
    """Kommentare entfernen – der Waechter darf nicht seine eigene Begruendung
    lesen (im Projekt der dreizehnte Fall dieser Klasse; hier nannte der
    Kommentar am 404-Zweig woertlich "nicht 400"). Schlaegt das Entfernen
    fehl, kommt der Originaltext zurueck – deshalb steht in Abschnitt 6 eine
    Positivkontrolle."""
    import io
    import tokenize
    try:
        aus = list(quelltext)
        zeilen = quelltext.split("\n")
        anfang = []
        pos = 0
        for z in zeilen:
            anfang.append(pos)
            pos += len(z) + 1
        for tk in tokenize.generate_tokens(io.StringIO(quelltext).readline):
            if tk.type != tokenize.COMMENT:
                continue
            start = anfang[tk.start[0] - 1] + tk.start[1]
            for i in range(start, min(start + len(tk.string), len(aus))):
                aus[i] = " "
        return "".join(aus)
    except Exception:      # noqa: BLE001
        return quelltext


def kopf(t):
    print(f"\n\033[1m{t}\033[0m")


# ── backend.config als Stub: der echte Import migriert Profile und schreibt
#    die LIVE-settings.json zurueck (Register).
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_skill_states=lambda: {})
sys.modules["backend.config"] = _cfg

from backend import mount_quelle as mq           # noqa: E402
import backend.tools.knowledge as kn            # noqa: E402

AGENT_QUELLE = (WURZEL / "backend" / "agent.py").read_text()


# ═════════════════════════════════════════════════════════════════════════════
# 1) mount_quelle.netzpfad
# ═════════════════════════════════════════════════════════════════════════════
# Die Eintraege sind der ECHTE Bestand von DEV (rein lesend abgefragt) – share_0
# traegt seine Quelle bis heute in Windows-Schreibweise, genau daran scheitert
# ein nachgebautes Mapping.
MOUNTS = [
    {"type": "smb", "source": "\\\\191.100.147.90\\Dokumentationen",
     "mountpoint": "/mnt/jarvis-kb/share_0"},
    {"type": "smb", "source": "//191.100.147.90/knowledgebase_an_rag",
     "mountpoint": "/mnt/jarvis-kb/share_1"},
    {"type": "smb", "source": "//191.100.147.90/OneNote_text_Jasmin",
     "mountpoint": "/mnt/jarvis-kb/share_2"},
    {"type": "nfs", "source": "srv:/export", "mountpoint": "/mnt/jarvis-kb/share_3"},
    {"type": "webdav", "source": "https://srv/dav", "mountpoint": "/mnt/jarvis-kb/share_4"},
]


def teil1():
    kopf("1) netzpfad: Einhaengepunkt -> Freigabe")

    n = mq.netzpfad(MOUNTS, "/mnt/jarvis-kb/share_2/0039_Maris/Informationen.one")
    check(n == r"\\191.100.147.90\OneNote_text_Jasmin\0039_Maris\Informationen.one",
          f"der gemeldete Fall wird zum UNC-Pfad ({n!r})")

    check(mq.netzpfad(MOUNTS, "/mnt/jarvis-kb/share_0/0039_Maris/x.pdf")
          == r"\\191.100.147.90\Dokumentationen\0039_Maris\x.pdf",
          "Altbestand in Windows-Schreibweise wird ebenso aufgeloest")

    check("/" not in mq.netzpfad(MOUNTS, "/mnt/jarvis-kb/share_2/a/b.one"),
          "der SMB-Pfad traegt KEINEN Schraegstrich (nur so ueberlebt er die Anzeige)")

    check(mq.netzpfad(MOUNTS, "/mnt/jarvis-kb/share_2/Datei mit Leerzeichen.one")
          == r"\\191.100.147.90\OneNote_text_Jasmin\Datei mit Leerzeichen.one",
          "Leerzeichen im Dateinamen bleiben (in Windows-Netzen der Normalfall)")

    # DIE PRAEFIX-FALLE. "share_2" steckt in "share_20" – ein Teilstring-Vergleich
    # ordnet die Datei der falschen Freigabe zu und nennt eine Quelle, die es
    # nicht gibt. Dieselbe Falle wie bei _kb_ordner_sicherstellen.
    check(mq.netzpfad(MOUNTS, "/mnt/jarvis-kb/share_20/x.one") == "",
          "share_20 gehoert NICHT zu share_2 (eintragsweiser Vergleich)")

    # Tiefster Einhaengepunkt gewinnt – der ist der spezifischere.
    tief = MOUNTS + [{"type": "smb", "source": "//srv/unter",
                      "mountpoint": "/mnt/jarvis-kb/share_2/0039_Maris"}]
    check(mq.netzpfad(tief, "/mnt/jarvis-kb/share_2/0039_Maris/x.one")
          == r"\\srv\unter\x.one",
          "bei zwei passenden Einhaengepunkten gewinnt der laengste")

    check(mq.netzpfad(MOUNTS, "mnt/jarvis-kb/share_2/a/b.one").startswith("\\\\"),
          "auch die Form ohne fuehrenden Schraegstrich wird erkannt")

    check(mq.netzpfad(MOUNTS, "/mnt/jarvis-kb/share_3/a/b.pdf") == "srv:/export/a/b.pdf",
          "NFS behaelt seine eigene Schreibweise")
    check(mq.netzpfad(MOUNTS, "/mnt/jarvis-kb/share_4/a/b.pdf")
          == "https://srv/dav/a/b.pdf",
          "WebDAV ergibt eine Adresse, die der Benutzer wirklich anklicken kann")

    # FAIL-OPEN in die harmlose Richtung: ein geratener Netzwerkpfad sieht
    # anklickbar aus und fuehrt ins Nichts – schlimmer als der Serverpfad.
    check(mq.netzpfad(MOUNTS, "data/knowledge/learned/x.md") == "",
          "eine Datei ausserhalb jeder Freigabe hat keinen Netzwerkpfad")
    check(mq.netzpfad([{"type": "smb", "source": "kaputt",
                        "mountpoint": "/mnt/jarvis-kb/share_9"}],
                      "/mnt/jarvis-kb/share_9/x.one") == "",
          "eine unbrauchbare Quelle ergibt nichts (fail-open)")
    for boese in (None, "abc", [None, 42, {}], [{"mountpoint": ""}]):
        sicher(lambda b=boese: mq.netzpfad(b, "/mnt/jarvis-kb/share_2/x.one") == "",
               f"unbrauchbare Freigabenliste {boese!r} wirft nicht")
    check(mq.netzpfad(MOUNTS, "") == "" and mq.netzpfad(MOUNTS, None) == "",
          "leerer Pfad ergibt nichts")

    # Der Einhaengepunkt selbst (ohne Unterpfad) ist die Freigabe.
    check(mq.netzpfad(MOUNTS, "/mnt/jarvis-kb/share_2")
          == r"\\191.100.147.90\OneNote_text_Jasmin",
          "der Einhaengepunkt selbst ergibt die Freigabe")

    # REGEL: die Normalisierung wird BENUTZT, nicht nachgebaut. Ohne pruefe()
    # versteht netzpfad die Windows-Schreibweise des Altbestands nicht.
    q = (WURZEL / "backend" / "mount_quelle.py").read_text()
    rumpf = ast.get_source_segment(
        q, next(k for k in ast.parse(q).body
                if isinstance(k, ast.FunctionDef) and k.name == "netzpfad"))
    check("pruefe(" in rumpf,
          "netzpfad ruft pruefe() – die Schreibweisen-Regel gibt es nur einmal")


# ═════════════════════════════════════════════════════════════════════════════
# 2) KnowledgeTool.execute – AUSGEFUEHRT
# ═════════════════════════════════════════════════════════════════════════════

class _VS:
    def chunk_count(self):
        return 42

    def file_count(self):
        return 3

    def get_indexed_files(self):
        return {}


def _lauf(treffer, mounts):
    """Der ECHTE execute()-Lauf gegen einen gestellten Index."""
    sandkasten = tempfile.mkdtemp(prefix="qnp-")
    alt = {n: getattr(kn, n) for n in
           ("PROJECT_ROOT", "_get_folders", "_get_max_bytes", "_get_vector_store",
            "_rebuild_vector_index", "_vector_search", "_get_skill_config")}
    try:
        # SANDKASTEN-WAECHTER: execute() macht mkdir auf PROJECT_ROOT/data/knowledge.
        # Ohne Umbiegung schreibt der Test in den echten Bestand.
        kn.PROJECT_ROOT = Path(sandkasten)
        if not str(kn.PROJECT_ROOT).startswith(tempfile.gettempdir()):
            print("ABBRUCH: Sandkasten nicht wirksam")
            sys.exit(2)
        kn._get_folders = lambda: [Path(sandkasten) / "data" / "knowledge"]
        kn._get_max_bytes = lambda: 1 << 20
        kn._get_vector_store = lambda: _VS()
        kn._rebuild_vector_index = lambda *a, **kw: True
        kn._vector_search = lambda *a, **kw: list(treffer)
        kn._get_skill_config = lambda: {"mounts": mounts}
        return asyncio.run(kn.KnowledgeTool().execute(query="maris", max_results=5))
    finally:
        for n, v in alt.items():
            setattr(kn, n, v)


def teil2():
    kopf("2) KnowledgeTool.execute: Netzwerkpfad in der Trefferzeile")

    server = "/mnt/jarvis-kb/share_2/0039_Maris/Informationen.one"
    unc = r"\\191.100.147.90\OneNote_text_Jasmin\0039_Maris\Informationen.one"
    aus = _lauf([(0.91, server, "Inhalt des Abschnitts.")], MOUNTS)

    zeilen = [z for z in aus.splitlines() if z.startswith("--- [")]
    check(len(zeilen) == 1 and unc in zeilen[0],
          f"die Trefferzeile nennt den Netzwerkpfad ({zeilen[:1]})")
    check(zeilen and server not in zeilen[0],
          "der Einhaengepunkt steht NICHT in der Trefferzeile")
    # Der Serverpfad muss erreichbar BLEIBEN: xlsx_inspect, xlsx_read_range und
    # pdf_formular_extrakt arbeiten mit ihm. Nur der UNC-Pfad waere eine schoene
    # Anzeige mit toter Weiterverarbeitung.
    check(server in aus,
          "der Serverpfad steht weiter im Ergebnis (Werkzeuge brauchen ihn)")
    check(re.search(r"Serverpfad[^\n]*Werkzeuge", aus) is not None,
          "und er ist als Werkzeug-Pfad gekennzeichnet")
    check("QUELLENANGABE" in aus,
          "der Auftrag an das Modell steht im Ergebnis")
    sicher(lambda: 0 <= aus.find("QUELLENANGABE") < aus.find("--- ["),
           "und zwar VOR den Treffern")

    # Ohne Freigabe darf sich NICHTS aendern – sonst kostet das Feature Token
    # und Verwirrung bei jedem Treffer aus data/knowledge.
    rein = "data/knowledge/learned/2026-09/conv_x.md"
    aus2 = _lauf([(0.91, rein, "Inhalt des Abschnitts.")], MOUNTS)
    check(f"--- [1] {rein} (Relevanz: 0.91) ---" in aus2,
          "ein Treffer ohne Freigabe sieht aus wie bisher")
    check("QUELLENANGABE" not in aus2 and "Serverpfad" not in aus2,
          "und traegt keinen einzigen Zusatz")

    # Gemischt: der Hinweis steht, aber nur die Freigabe-Treffer werden ergaenzt.
    aus3 = _lauf([(0.9, server, "A"), (0.8, rein, "B")], MOUNTS)
    check("QUELLENANGABE" in aus3 and unc in aus3
          and f"--- [2] {rein} " in aus3,
          "gemischte Trefferliste: nur der Freigabe-Treffer wird ergaenzt")

    # Ein kaputter Eintrag darf die Suche nicht kosten.
    sicher(lambda: "--- [1] " in _lauf([(0.9, server, "A")], "kaputt"),
           "kaputte Freigabenliste: die Suche liefert trotzdem Treffer")


# ═════════════════════════════════════════════════════════════════════════════
# 3) _clean_doc_refs loescht die Quellangabe nicht
# ═════════════════════════════════════════════════════════════════════════════

def _clean():
    """Das ECHTE _clean_doc_refs, per ast geschnitten und ausgefuehrt."""
    baum = ast.parse(AGENT_QUELLE)
    umg = {"re": re}
    for k in baum.body:
        if isinstance(k, ast.Assign) and len(k.targets) == 1:
            ziel = getattr(k.targets[0], "id", "")
            if ziel.startswith("_") and ziel.upper() == ziel:
                try:
                    exec(ast.get_source_segment(AGENT_QUELLE, k), umg)
                except Exception:      # braucht einen fremden Import
                    pass
    kls = next(k for k in baum.body
               if isinstance(k, ast.ClassDef) and k.name == "JarvisAgent")
    teile = []
    for k in kls.body:
        if isinstance(k, ast.FunctionDef) and k.name in ("_clean_doc_refs", "_liefer_ext_re"):
            teile.append(ast.get_source_segment(AGENT_QUELLE, k))
        if isinstance(k, ast.Assign) and getattr(k.targets[0], "id", "") == "_LIEFER_EXT":
            teile.insert(0, ast.get_source_segment(AGENT_QUELLE, k))
    code = "class A:\n" + "\n".join(
        "\n".join("    " + z for z in t.splitlines()) for t in teile)
    exec(code, umg)
    return umg["A"]()._clean_doc_refs


def teil3():
    kopf("3) _clean_doc_refs: die Quellangabe ueberlebt")
    clean = _clean()

    # Positivkontrolle des Messaufbaus: ohne sie beweist ein "bleibt stehen"
    # nichts – eine Funktion, die nichts tut, waere ebenfalls gruen.
    check("/tmp/bericht.xlsx" not in clean("Ergebnis unter /tmp/bericht.xlsx"),
          "POSITIVKONTROLLE: ein lokaler Ergebnispfad wird weiter entfernt")
    check("data/documents/ab12__x.docx" not in
          clean("Datei data/documents/ab12__x.docx"),
          "POSITIVKONTROLLE: auch data/documents/…")

    # LEERZEICHEN - der gemeldete Fall (2026-09-08). Ein Ausdruck, der am
    # Leerraum endet, maskiert nur den ANFANG des Pfades - und dann greift eine
    # Regel in den Rest. Gemessen war das NICHT die Pfad-Regel, sondern die
    # Aufraeumregel `\b(unter|in|...|datei)\s*([.,;:])`: eine Datei, die
    # wirklich "Datei.pdf" heisst, trifft sie.
    #   \\srv\share\Mein Ordner\Datei.pdf -> \\srv\share\Mein Ordner\.pdf
    #   srv:/export/Mein Ordner/Datei.pdf -> srv:/export/Mein
    for n in (r"\\srv\share\Mein Ordner\Datei.pdf",
              r"\\srv\Meine Freigabe\Preise 2026.xlsx",
              "srv:/export/Mein Ordner/Datei.pdf",
              "https://srv/dav/Mein Ordner/Datei.pdf"):
        check(n in clean(f"Das steht dort. Quelle: {n}"),
              f"mit Leerzeichen vollstaendig: {n}")
    zwei = clean(r"Quelle: \\srv\s\Erste Datei.one und \\srv\s\Zweite Datei.pdf")
    check(r"\\srv\s\Erste Datei.one" in zwei and r"\\srv\s\Zweite Datei.pdf" in zwei,
          f"zwei Pfade mit Leerzeichen in EINER Zeile bleiben ganz ({zwei!r})")

    for n in (r"\\191.100.147.90\OneNote_text_Jasmin\0039_Maris\Anleitungen SAP.one",
              r"\\191.100.147.90\Dokumentationen\0039_Maris\Handbuch.pdf",
              r"\\srv\share\Preise.xlsx",
              "srv:/export/0039_Maris/Handbuch.pdf",
              "https://srv/dav/0039_Maris/Handbuch.pdf"):
        t = f"Das steht in der Anleitung. Quelle: {n}"
        check(n in clean(t), f"bleibt vollstaendig stehen: {n}")

    # Ein Windows-Laufwerk ist KEINE Netzwerkquelle – die nfs-Form darf es nicht
    # mitnehmen, sonst wird aus der Ausnahme ein Loch in der Bereinigung.
    check("C:/temp/x.pdf" not in clean("Liegt unter C:/temp/x.pdf"),
          "ein Laufwerksbuchstabe zaehlt nicht als Netzwerkquelle")

    # BESTANDSBEFUND, unveraendert: ein markdown-VERLINKTES externes Bild
    # verschwindet weiterhin (die Markdown-Regel laeuft vor der Maskierung).
    check("https://example.com/b.png" not in clean("![e](https://example.com/b.png)"),
          "BEFUND unveraendert: markdown-verlinkte Bild-URL bleibt entfernt")

    check("\x00" not in clean(r"Quelle: \\srv\share\x.one und https://srv/y.pdf"),
          "die interne Maskierung ist vollstaendig zurueckgebaut")


# ═════════════════════════════════════════════════════════════════════════════
# 4) Der Avatar benutzt DIESELBE Funktion
# ═════════════════════════════════════════════════════════════════════════════

def teil4():
    kopf("4) Avatar: keine zweite Fassung")
    q = (WURZEL / "backend" / "avatar.py").read_text()
    # Kommentare weg – sonst liest der Waechter seine eigene Begruendung.
    ohne = re.sub(r"#[^\n]*", "", q)
    check("quell_anzeige(" in ohne,
          "avatar.py ruft quell_anzeige – statt die Zuordnung nachzubauen")
    check("mountpoint" not in ohne and "jarvis-kb" not in ohne,
          "und kennt weder Einhaengepunkte noch die Mount-Basis")

    kq = (WURZEL / "backend" / "tools" / "knowledge.py").read_text()
    rumpf = ast.get_source_segment(
        kq, next(k for k in ast.parse(kq).body
                 if isinstance(k, ast.FunctionDef) and k.name == "quell_anzeige"))
    check("mount_quelle" in rumpf and "netzpfad" in rumpf,
          "quell_anzeige geht ueber mount_quelle.netzpfad")
    check("import" in rumpf and "backend.main" not in rumpf,
          "und NICHT ueber backend.main (das waere ein Zirkelimport)")


# ═════════════════════════════════════════════════════════════════════════════
# 5) mount_quelle.serverpfad – die Rueckrichtung (fail-CLOSED)
# ═════════════════════════════════════════════════════════════════════════════

def teil5():
    kopf("5) serverpfad: Netzwerkpfad -> Serverpfad")

    # RUNDLAUF: was netzpfad ausgibt, muss serverpfad verlustfrei zurueckrechnen –
    # sonst zeigt der Link im Chat auf eine andere Datei als die zitierte.
    for p in ("/mnt/jarvis-kb/share_2/0039_Maris/Anleitungen SAP.one",
              "/mnt/jarvis-kb/share_0/x.pdf",
              "/mnt/jarvis-kb/share_3/a/b.pdf",
              "/mnt/jarvis-kb/share_4/a/b.pdf",
              "/mnt/jarvis-kb/share_2"):
        check(mq.serverpfad(MOUNTS, mq.netzpfad(MOUNTS, p)) == p,
              f"Rundlauf verlustfrei: {p}")

    # Windows-Freigaben sind case-insensitiv – der Benutzer tippt sie mal so, mal
    # so. Der UNTERPFAD behaelt seine Schreibweise (Linux ist case-sensitiv).
    check(mq.serverpfad(MOUNTS, r"\\191.100.147.90\onenote_TEXT_jasmin\0039_Maris\X.one")
          == "/mnt/jarvis-kb/share_2/0039_Maris/X.one",
          "Freigabe case-insensitiv, Unterpfad unveraendert")
    check(mq.serverpfad(MOUNTS, "//191.100.147.90/OneNote_text_Jasmin/a/b.one")
          == "/mnt/jarvis-kb/share_2/a/b.one",
          "auch die Slash-Form wird angenommen")

    # FAIL-CLOSED. Diese Funktion entscheidet, WELCHE DATEI ausgeliefert wird –
    # was sich keiner konfigurierten Freigabe zuordnen laesst, ergibt "".
    for boese, was in (
            (r"\\fremd\share\x.one", "fremder Server"),
            (r"\\191.100.147.90\OneNote_text_Jasmin2\x.one", "Praefix-Falle beim Freigabenamen"),
            (r"\\191.100.147.90\OneNote_text_Jasmin\..\..\etc\passwd", "Traversal"),
            ("/etc/passwd", "lokaler Pfad"),
            ("../../etc/passwd", "relativer Traversal"),
            ("", "leer"), (None, "None")):
        sicher(lambda b=boese: mq.serverpfad(MOUNTS, b) == "", f"abgewiesen: {was}")
    check(mq.serverpfad(MOUNTS, "\\\\191.100.147.90\\OneNote_text_Jasmin\\x\x00y") == "",
          "abgewiesen: echtes NUL-Byte")
    for schrott in (None, "abc", [None, 42], [{"mountpoint": "/mnt/x"}]):
        sicher(lambda b=schrott: mq.serverpfad(b, r"\\srv\s\x.one") == "",
               f"unbrauchbare Freigabenliste {schrott!r} wirft nicht")


# ═════════════════════════════════════════════════════════════════════════════
# 6) Der Endpunkt: Rechte + er baut die Schranke NICHT nach
# ═════════════════════════════════════════════════════════════════════════════

def teil6():
    kopf("6) /api/knowledge/netzquelle")
    q = (WURZEL / "backend" / "main.py").read_text()
    fn = next((k for k in ast.parse(q).body
               if isinstance(k, ast.AsyncFunctionDef)
               and k.name == "read_knowledge_netzquelle"), None)
    if fn is None:
        check(False, "der Endpunkt read_knowledge_netzquelle existiert")
        return
    check(True, "der Endpunkt read_knowledge_netzquelle existiert")
    rumpf = ast.get_source_segment(q, fn)
    # Docstring UND Kommentare weg – sonst liest der Waechter seine eigene
    # Begruendung: der Kommentar am 404-Zweig nennt woertlich "nicht 400"
    # (im ersten Lauf genau so passiert).
    ohne = ohne_kommentare(rumpf.replace(ast.get_docstring(fn) or "\x00", ""))

    dek = " ".join(ast.get_source_segment(q, d) for d in fn.decorator_list)
    # ast.get_source_segment() eines Dekorators liefert den Ausdruck OHNE '@'.
    check('app.get("/api/knowledge/netzquelle")' in dek, "als GET registriert")
    check("require_auth_or_query" in rumpf,
          "Auth wie bei file_raw (Token auch als ?token=, ein <a> setzt keinen Header)")

    # DIE SICHERHEITSSCHRANKE WIRD BENUTZT, NICHT NACHGEBAUT: die Pruefung
    # "liegt die Datei in einem Wissensordner" steht in read_knowledge_file_raw.
    # Eine zweite Fassung liefe beim naechsten Feinschliff auseinander – und
    # dann liefert ein Weg aus, was der andere sperrt.
    check("read_knowledge_file_raw(" in ohne,
          "delegiert an read_knowledge_file_raw")
    check("_get_folders" not in ohne and "LEARNED_DIR" not in ohne
          and "FileResponse" not in ohne,
          "und baut dessen Zugehoerigkeits-Pruefung NICHT nach")
    check("serverpfad(" in ohne, "loest ueber mount_quelle.serverpfad auf")
    check("nicht 400" not in ohne,
          "POSITIVKONTROLLE: die Kommentare sind wirklich entfernt")
    check("404" in ohne and "400" not in ohne,
          "unbekannter Netzwerkpfad -> 404 (ob es die Freigabe gibt, ist selbst "
          "eine Information)")


def namens_guard():
    """Fehlt ein neues Symbol, ist das ein FAIL MIT Bilanz – kein Abbruch.

    Gegen den kompletten Altstand gefahren brach der Lauf sonst mit einem
    nackten AttributeError ab: kein FAIL, keine Bilanzzeile, also von "nicht
    gelaufen" nicht zu unterscheiden (Register).
    """
    kopf("0) Sind die neuen Symbole ueberhaupt da?")
    fehlt = []
    if not hasattr(mq, "netzpfad"):
        fehlt.append("mount_quelle.netzpfad")
    if not hasattr(kn, "quell_anzeige"):
        fehlt.append("tools.knowledge.quell_anzeige")
    if not hasattr(mq, "serverpfad"):
        fehlt.append("mount_quelle.serverpfad")
    if "_NETZQUELLE_RE" not in AGENT_QUELLE:
        fehlt.append("agent._NETZQUELLE_RE")
    check(not fehlt, "alle neuen Symbole vorhanden"
          + (f" – FEHLT: {', '.join(fehlt)}" if fehlt else ""))
    return not fehlt


if __name__ == "__main__":
    if namens_guard():
        for t in (teil1, teil2, teil3, teil4, teil5, teil6):
            # Ein Wurf IM Abschnitt ist ein FAIL, kein Abbruch – sonst endet der
            # Lauf ohne Bilanzzeile und ist von "nicht gelaufen" nicht zu
            # unterscheiden (beim Bau dieses Waechters zweimal passiert).
            try:
                t()
            except Exception as e:      # noqa: BLE001
                check(False, f"Abschnitt {t.__name__} bricht ab: "
                             f"{type(e).__name__}: {e}")
    print("\n" + "=" * 62)
    print(f"\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
    sys.exit(1 if FAIL else 0)

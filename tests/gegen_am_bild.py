#!/usr/bin/env python3
"""Gegenproben zu 1.0.8: erzeugtes Bild in der AI-Maus (2026-09-15).

Jede Probe dreht GENAU EINE Zusage zurueck. Eine Gegenprobe, die nicht beisst,
ist ein Testmangel - kein Beweis.

⚠ DER HARNESS SICHERT JEDE DATEI, DIE ANGEFASST WIRD - auch `Vorgaben.cs`, die
der WAECHTER selbst beschreibt (er ruft `paket_bauen`), und die TESTDATEI, weil
eine Probe sie sabotiert. Am 2026-09-11 hat genau diese Auslassung eine
Sabotage stehen lassen, und der naechste Lauf meldete einen FAIL, den es im
Code nicht gab. Die Liste wird als REGEL geprueft, nicht gepflegt.
"""
import atexit
import hashlib
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path("/home/bender/ai/projekte/jarvis")
ABL = pathlib.Path.home() / ".gegen-am-bild"
MARKE = ABL / "LAUF"

AM = "backend/ai_mouse.py"
JC = "ai-mouse/src/AiMouse/Vision/JarvisClient.cs"
RW = "ai-mouse/src/AiMouse/Ui/ResultWindow.cs"
TR = "ai-mouse/src/AiMouse/TrayApplicationContext.cs"
TX = "ai-mouse/src/AiMouse/Localization/Texte.cs"
AMJS = "frontend/js/ai_mouse.js"

DATEIEN = [AM, JC, RW, TR, TX, AMJS,
           "ai-mouse/src/AiMouse/AiMouse.csproj",
           "ai-mouse/src/AiMouse/Configuration/Vorgaben.cs",
           "backend/main.py", "frontend/js/i18n.js",
           "tests/test_ai_mouse.py"]


def sichern():
    ABL.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck(still=False):
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)
    if not still:
        for rel in DATEIEN:
            a = hashlib.md5((ABL / rel.replace("/", "__")).read_bytes()).hexdigest()
            b = hashlib.md5((ROOT / rel).read_bytes()).hexdigest()
            if a != b:
                print("  ⚠ NICHT wiederhergestellt: " + rel)


def ende():
    zurueck(still=True)
    if MARKE.exists():
        MARKE.unlink()


def lies(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def ersetze(rel, alt, neu, anzahl=1):
    s = lies(rel)
    assert s.count(alt) >= anzahl, "Anker fehlt in %s: %r" % (rel, alt[:70])
    (ROOT / rel).write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


def waechter():
    """(fails, bilanz_da) - gemessen wird die BILANZZEILE, nicht nur der Code.

    Ein Lauf, der ohne Bilanz abbricht, ist von 'nicht gelaufen' nicht zu
    unterscheiden.
    """
    p = subprocess.run([sys.executable, "tests/test_ai_mouse.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"^(\d+) OK, (\d+) FAIL$", p.stdout, re.M)
    return (int(m.group(2)), True) if m else (-1, False)


PROBEN = []


def probe(name):
    def deko(fn):
        PROBEN.append((name, fn))
        return fn
    return deko


# ── a) Der Kern: das Werkzeug und die Arbeitskopie ────────────────────────
@probe("DER GEMELDETE FALL: das Bildwerkzeug ist wieder in keinem Lauf")
def _():
    ersetze(AM, "    if mit_bild and bild_werkzeug_da():\n        raus.add(BILD_WERKZEUG)\n", "")


@probe("das Bildwerkzeug wird angeboten, OHNE dass es ladbar ist")
def _():
    ersetze(AM, "    if mit_bild and bild_werkzeug_da():", "    if mit_bild:")


@probe("keine Arbeitskopie - das Werkzeug ist damit unerreichbar")
def _():
    ersetze(AM,
            "    bild_pfad = (ausschnitt_ablegen(daten, mime, user)\n"
            "                 if BILD_WERKZEUG in werkzeuge else \"\")",
            '    bild_pfad = ""')


@probe("Werkzeug bleibt im Satz, obwohl die Ablage scheiterte")
def _():
    ersetze(AM,
            "    if BILD_WERKZEUG in werkzeuge and not bild_pfad:\n"
            "        werkzeuge = {w for w in werkzeuge if w != BILD_WERKZEUG}\n", "")


@probe("die Arbeitskopie geht DAUERHAFT nach data/documents")
def _():
    ersetze(AM, "        ziel = _lauf_tmp.anhang_ziel(user, \"ausschnitt.%s\" % endung)",
            "        ziel = _projekt_wurzel() / \"data/documents\" / \"ausschnitt.png\"")


@probe("die Arbeitskopie wird ausfuehrbar abgelegt")
def _():
    ersetze(AM, "        os.chmod(ziel, 0o644)", "        os.chmod(ziel, 0o755)")


@probe("Ablage wirft statt \"\" zu liefern (fail-open aufgehoben)")
def _():
    ersetze(AM, '        print("[ai-mouse] Arbeitskopie fehlgeschlagen: %s" % e, flush=True)\n'
                '        return ""',
            '        raise')


# ── b) Der Prompt ─────────────────────────────────────────────────────────
@probe("der Prompt nennt den Pfad nicht (Modell sucht die Datei)")
def _():
    ersetze(AM, '            "Der gezeigte Ausschnitt liegt zusätzlich als Datei unter: %s"\n'
                "            % bild_pfad,", '            "",')


@probe("der Prompt nennt das Werkzeug auch OHNE Arbeitskopie")
def _():
    ersetze(AM, "    if bild_pfad:\n        zeilen += [", "    if True:\n        zeilen += [")


@probe("die Ergebnis-Marke haengt wieder nur an `bereiche`")
def _():
    ersetze(AM, "    if mit_werkzeugen:\n        zeilen += [\n            \"\",\n"
                '            "Leite deine endgültige Antwort mit genau dieser Zeile ein:",',
            "    if bereiche:\n        zeilen += [\n            \"\",\n"
            '            "Leite deine endgültige Antwort mit genau dieser Zeile ein:",')


# ── c) Die Bergung ────────────────────────────────────────────────────────
@probe("die Adresse kommt aus dem TEXT statt aus der Bilderliste")
def _():
    s = lies(AM)
    alt = """    for eintrag in reversed(bilder or []):
        kandidat = str((eintrag or {}).get("url") or "")
        if _BILD_URL_RE.fullmatch(kandidat):"""
    assert alt in s, "Anker fehlt"
    neu = """    _m = _BILD_URL_RE.search(roh)
    if _m:
        url = _m.group(0)
    for eintrag in []:
        kandidat = ""
        if False:"""
    (ROOT / AM).write_text(s.replace(alt, neu, 1), encoding="utf-8")


@probe("die Markdown-Referenz bleibt im Anzeigetext stehen")
def _():
    ersetze(AM, "    sauber = _BILD_MD_RE.sub(\"\", roh)\n"
                "    sauber = _BILD_URL_RE.sub(\"\", sauber)", "    sauber = roh")


@probe("erfundene Adresse: der Text behauptet weiter ein Bild")
def _():
    ersetze(AM, "    if hatte_referenz and not url:", "    if False:")


@probe("bild_aus_lauf wird gar nicht gerufen")
def _():
    ersetze(AM, "    ergebnis, bild_url = bild_aus_lauf(roh or \"\", bilder)",
            "    ergebnis, bild_url = (roh or \"\"), \"\"")


@probe("das Feld `bild` faellt aus der Antwort")
def _():
    ersetze(AM, '        "bild": bild_url,', "")


@probe("_agent_lauf liefert die Bilder nicht mit")
def _():
    ersetze(AM, '    bilder = list(getattr(agent, "last_task_images", None) or [])',
            "    bilder = []")


# ── d) Der Client ─────────────────────────────────────────────────────────
@probe("die Adresspruefung faellt weg (jede Adresse wird abgerufen)")
def _():
    ersetze(JC, "        return new MausAntwort(text, BildAdressePruefen(bild));",
            "        return new MausAntwort(text, bild);")


@probe("BildHolenAsync prueft die Adresse nicht mehr")
def _():
    ersetze(JC, "        string adresse = BildAdressePruefen(relativeAdresse);",
            "        string adresse = relativeAdresse;")


@probe("ein Fehlschlag beim Bildabruf wirft (kostet die Textantwort)")
def _():
    ersetze(JC, "        catch (Exception e) when (e is not OperationCanceledException)\n"
                "        {\n            return null;\n        }",
            "        catch (Exception e) when (false)\n        {\n            return null;\n        }")


@probe("nur-Bild-Antwort gilt wieder als Fehlschlag")
def _():
    ersetze(JC, "            if (text.Length == 0 && bild.Length == 0)",
            "            if (text.Length == 0)")


# ── e) Das Fenster ────────────────────────────────────────────────────────
@probe("der Bildbereich ist per Vorgabe AUFGEKLAPPT (auch ohne Bild)")
def _():
    ersetze(RW, "            Panel2Collapsed = true,", "            Panel2Collapsed = false,")


@probe("unbrauchbare Bilddaten klappen den Bereich trotzdem auf")
def _():
    ersetze(RW, "        catch (Exception)\n        {\n"
                "            // Keine Bilddaten (Fehlerseite, abgeschnittener Download). Der\n"
                "            // Text steht bereits – mehr ist hier nicht zu retten.\n"
                "            return;\n        }",
            "        catch (Exception)\n        {\n            neu = new Bitmap(1, 1);\n        }")


@probe("der Teiler-Abstand wird nicht geklemmt (wirft bei kleinem Fenster)")
def _():
    ersetze(RW, "        _teiler.SplitterDistance = Math.Min(wunsch, hoechstens);",
            "        _teiler.SplitterDistance = wunsch;")


@probe("das erzeugte Bild wird beim Schliessen nicht freigegeben")
def _():
    ersetze(RW, "        _bildAnzeige.Image = null;\n        _ergebnisBild?.Dispose();\n"
                "        _ergebnisBild = null;\n", "")


@probe("die Anzeige wird NACH dem Freigeben geloest")
def _():
    ersetze(RW, "        _bildAnzeige.Image = null;\n        _ergebnisBild?.Dispose();",
            "        _ergebnisBild?.Dispose();\n        _bildAnzeige.Image = null;")


@probe("der Knopf sagt nicht, welches Bild er kopiert")
def _():
    ersetze(RW, "        _bildButton.Text = _ergebnisBild is not null\n"
                "            ? Texte.ErgebnisBildKopierenKnopf : Texte.BildKopierenKnopf;",
            "        _bildButton.Text = Texte.BildKopierenKnopf;")


@probe("er kopiert den Ausschnitt statt des Ergebnisses")
def _():
    ersetze(RW, "        Bitmap? quelle = _ergebnisBild ?? _bild;", "        Bitmap? quelle = _bild;")


# ── f) Der Ablauf ─────────────────────────────────────────────────────────
@probe("das Bild wird gar nicht nachgeholt")
def _():
    ersetze(TR, "            await ErgebnisBildZeigenAsync(window, ergebnis.BildUrl, cts.Token)\n"
                "                .ConfigureAwait(true);\n", "")


@probe("der Text wartet auf das Bild (Fenster bleibt leer)")
def _():
    s = lies(TR)
    alt = """            if (!window.IsDisposed)
            {
                window.ShowAnswer(answer, _settings.CopyResultToClipboard);
            }

            await ErgebnisBildZeigenAsync(window, ergebnis.BildUrl, cts.Token)
                .ConfigureAwait(true);"""
    assert alt in s, "Anker fehlt"
    neu = """            await ErgebnisBildZeigenAsync(window, ergebnis.BildUrl, cts.Token)
                .ConfigureAwait(true);

            if (!window.IsDisposed)
            {
                window.ShowAnswer(answer, _settings.CopyResultToClipboard);
            }"""
    (ROOT / TR).write_text(s.replace(alt, neu, 1), encoding="utf-8")


@probe("ein gescheiterter Bildabruf bleibt still")
def _():
    ersetze(TR, "            window.KopfHinweis(Texte.BildNichtGeholt, fehler: true);\n"
                "            return;", "            return;")


@probe("waehrend des Holens steht kein Hinweis im Kopf")
def _():
    ersetze(TR, "        window.KopfHinweis(Texte.BildWirdGeholt, fehler: false);\n", "")


@probe("der Wiederholungs-Zweig zeigt kein Bild")
def _():
    ersetze(TR, "                        await ErgebnisBildZeigenAsync(window, zweit.BildUrl, cts.Token)\n"
                "                            .ConfigureAwait(true);\n", "")


# ── g) Texte und Version ──────────────────────────────────────────────────
@probe("die neuen Texte gibt es nur auf Deutsch")
def _():
    ersetze(TX, '    public static string BildWirdGeholt => T("Bild wird geladen…", "Loading image…");',
            '    public static string BildWirdGeholt => "Bild wird geladen…";')


@probe("Version nicht hochgezaehlt")
def _():
    ersetze("ai-mouse/src/AiMouse/AiMouse.csproj", "<Version>1.0.8</Version>",
            "<Version>1.0.7</Version>")


# ── h) Der Waechter selbst ────────────────────────────────────────────────
@probe("der Waechter liest wieder seine eigene Begruendung mit")
def _():
    ersetze("tests/test_ai_mouse.py", "_abl_src = _ohne_worte(_fn_abl, _src32) if _fn_abl else \"\"",
            "_abl_src = ast.get_source_segment(_src32, _fn_abl) if _fn_abl else \"\"")


# ── i) Das Bau-Fenster in der Kachel ──────────────────────────────────────
@probe("DER GEMELDETE FALL: die Kachel zeigt nur die alte Nummer")
def _():
    s = lies(AMJS)
    i = s.index("var q = (_health.quelltext_version")
    j = s.index("        }\n    }", i)
    (ROOT / AMJS).write_text(s[:i] + s[j:], encoding="utf-8")


@probe("sie holt wieder bau_noetig (7,5 ms im heissen Pfad)")
def _():
    ersetze(AMJS, "var q = (_health.quelltext_version || '').trim();",
            "var q = (_health.bau_noetig ? 'x' : '') || '';")


@probe("sie behauptet etwas, obwohl eine Angabe fehlt")
def _():
    ersetze(AMJS, "if (v && q && q !== v) {", "if (q !== v) {")


@probe("laufender und anstehender Bau sind nicht unterscheidbar")
def _():
    ersetze(AMJS, "vs.textContent += ' · ' + (_health.paket_baut\n"
                  "                    ? t('aimouse.baut_jetzt', '{v} wird gerade gebaut…')\n"
                  "                        .replace('{v}', q)\n"
                  "                    : t('aimouse.baut_gleich', '{v} wird in Kürze gebaut')\n"
                  "                        .replace('{v}', q));",
            "vs.textContent += ' · ' + t('aimouse.baut_gleich', '{v}').replace('{v}', q);")


@probe("health liefert quelltext_version nicht mehr (Anzeige tot)")
def _():
    ersetze("backend/main.py",
            '        "quelltext_version": ai_mouse.quelltext_version(),', "")


@probe("⚠ klient_version liest wieder die csproj (Update-Schleife von 1.0.7)")
def _():
    s = lies(AM)
    alt = "    return exe_version()"
    assert alt in s, "Anker fehlt"
    (ROOT / AM).write_text(s.replace(alt, "    return quelltext_version()", 1),
                           encoding="utf-8")


@probe("die neuen Texte gibt es nur auf Deutsch (Bau-Hinweis)")
def _():
    ersetze("frontend/js/i18n.js", "        'aimouse.baut_jetzt':    '{v} is being built…',\n", "")


@probe("der Waechter liest wieder seinen eigenen Kommentar mit")
def _():
    ersetze("tests/test_ai_mouse.py",
            '_dk24_code = "\\n".join(z for z in _dk24.splitlines()\n'
            '                       if not z.strip().startswith("//"))',
            "_dk24_code = _dk24")


@probe("KOMPLETTER ALTSTAND (backend/ai_mouse.py)")
def _():
    # ⚠ NICHT `HEAD`: sobald die Aenderung committet ist, IST HEAD der neue
    # Stand – und die Probe sabotiert nichts mehr (genau so passiert, sie war
    # stumm). Gesucht wird der Commit, der `BILD_WERKZEUG` eingefuehrt hat;
    # sein Vorgaenger ist der Altstand. Ein fester Hash waere eine Zeitbombe
    # (Historie-Rewrites gab es in diesem Projekt zweimal).
    einf = subprocess.run(["git", "log", "-S", "BILD_WERKZEUG", "--format=%H",
                           "--", AM], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.split()
    assert einf, "Einfuehrungs-Commit nicht gefunden"
    alt = subprocess.run(["git", "show", einf[-1] + "~1:" + AM], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    assert "BILD_WERKZEUG" not in alt, "der geholte Stand ist nicht der Altstand"
    (ROOT / AM).write_text(alt, encoding="utf-8")


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs - nehme ihn zurueck.")
        zurueck(still=True)

    # REGEL: was eine Probe anfasst, muss gesichert sein.
    quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
    genannt = {d for d in re.findall(r'"([\w/.-]+\.(?:cs|csproj|py))"', quelle)
               if (ROOT / d).exists()}
    fehlend = genannt - set(DATEIEN)
    if fehlend:
        print("⚠ NICHT GESICHERT: " + ", ".join(sorted(fehlend)))
        sys.exit(2)

    sichern()
    atexit.register(ende)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))

    basis, da = waechter()
    if not da or basis != 0:
        print("⚠ BASIS NICHT GRUEN (%s FAIL) - ohne gruene Basis ist keine "
              "Gegenprobe deutbar." % basis)
        sys.exit(2)
    print("Basis gruen (%d Proben)\n" % len(PROBEN))

    stumm = []
    for name, fn in PROBEN:
        zurueck(still=True)
        try:
            fn()
        except AssertionError as e:
            print("  ⚠ SABOTAGE VERFEHLT: %s - %s" % (name, e))
            stumm.append(name + " (verfehlt)")
            continue
        fails, bilanz = waechter()
        if not bilanz:
            print("  ABBRUCH ohne Bilanz: %s" % name)
            stumm.append(name + " (ohne Bilanz)")
        elif fails > 0:
            print("  beisst (%2d FAIL)  %s" % (fails, name))
        else:
            print("  ⚠ STUMM          %s" % name)
            stumm.append(name)

    zurueck()
    print("\n%d von %d Proben beissen." % (len(PROBEN) - len(stumm), len(PROBEN)))
    if stumm:
        print("STUMM: " + "; ".join(stumm))
    sys.exit(1 if stumm else 0)


main()

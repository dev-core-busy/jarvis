#!/usr/bin/env python3
"""Gegenproben zu tests/test_ai_mouse_signatur.py.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter das
meldet. Eine Probe, die NICHT beisst, ist ein Testmangel – kein Beweis.

⚠ DREI SCHRANKEN, jede hier schon einmal bezahlt (Register):
  1. Die Sicherungsliste wird als REGEL geprueft: was eine Probe anfasst, muss
     gesichert sein, sonst Exit 2. Eine gepflegte Liste vergisst genau die
     neue Datei – und der naechste Lauf meldet dann einen Fehler, den es im
     Code nicht gibt.
  2. LAUFMARKE: nach einem `kill -9` bleibt sie liegen, und der naechste Start
     nimmt den Rueckstand zurueck. Beim geordneten Ende wird sie abgeraeumt –
     sonst stellt ein spaeterer Lauf einen VERALTETEN Stand her und macht
     fertige Arbeit zunichte.
  3. Ohne gruenen BASISLAUF ist keine Gegenprobe deutbar.

Gemessen wird am EXIT-CODE und an der BILANZZEILE, nie am Zaehlen von
FAIL-Zeilen: ein Lauf, der ohne Bilanz abbricht, ist von einem bestandenen
nicht zu unterscheiden.
"""
from __future__ import annotations

import atexit
import re
import signal
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-aimouse-sig"
MARKE = ABLAGE / "laeuft"
# ⚠ BEIDE WAECHTER. Die Sichtbarkeits-Zusage („der Admin behaelt den
# Download-Knopf") laesst sich im Quelltext nicht messen – sie haengt am
# ausgefuehrten Renderer. Ein Harness, der nur den Python-Waechter faehrt,
# meldet die zugehoerige Probe als STUMM und sieht damit wie ein zahnloser
# Waechter aus, obwohl die Pruefung existiert.
WAECHTER = [
    [sys.executable, str(WURZEL / "tests" / "test_ai_mouse_signatur.py")],
    ["node", str(WURZEL / "tests" / "test_ai_mouse_freigabe_ui.js")],
    # ⚠ AUCH DIESE BEIDEN – sonst sind ELF Gegenproben STUMM, und zwar nicht,
    #   weil die Waechter zahnlos waeren, sondern weil der Harness sie gar
    #   nicht faehrt (am 2026-09-22 genau so gemessen). Abschnitt 34 von
    #   test_ai_mouse.py haelt die Netzfreigabe-Regel, test_endpoint_rights
    #   den Admin-Zweig am Paket-Endpunkt.
    #   Merkregel: eine stumme Gegenprobe ist zuerst ein Verdacht gegen den
    #   Harness, dann gegen den Waechter.
    [sys.executable, str(WURZEL / "tests" / "test_ai_mouse.py")],
    [sys.executable, str(WURZEL / "tests" / "test_endpoint_rights.py")],
]

DATEIEN = [
    "backend/ai_mouse_signatur.py",
    "backend/ai_mouse.py",
    "backend/main.py",
    "backend/sandbox.py",
    "deploy/ai_mouse_build.sh",
    "frontend/js/ai_mouse.js",
    "frontend/js/ai_mouse_admin.js",
    "frontend/js/app.js",
    "frontend/js/i18n.js",
    "frontend/ai_mouse.html",
    "frontend/settings.html",
    "tests/test_ai_mouse_signatur.py",
    "tests/test_ai_mouse_freigabe_ui.js",
    # ⚠ AUCH DIE TESTDATEI, DIE EINE PROBE SABOTIERT – am 2026-09-21 zweimal
    #   bezahlt: die letzte Sabotage blieb stehen, und der naechste Lauf meldete
    #   einen FAIL, den es im Code nicht gibt.
    "tests/test_ai_mouse.py",
    # Der Windows-Client (Vorgabe 2026-09-22).
    "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
    "ai-mouse/src/AiMouse/TrayApplicationContext.cs",
    "ai-mouse/src/AiMouse/Localization/Texte.cs",
    "ai-mouse/src/AiMouse/AiMouse.csproj",
]


def sichern() -> None:
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        q = WURZEL / rel
        if q.is_file():
            ziel = ABLAGE / rel.replace("/", "__")
            ziel.write_bytes(q.read_bytes())


def zurueck() -> None:
    for rel in DATEIEN:
        s = ABLAGE / rel.replace("/", "__")
        if s.is_file():
            (WURZEL / rel).write_bytes(s.read_bytes())


def ersetze(rel: str, alt: str, neu: str, anzahl: int = 1) -> None:
    """Eine Ersetzung MIT Trefferkontrolle – ohne sie sieht eine Probe, die
    ihr Ziel verfehlt, wie ein zahnloser Waechter aus (Register)."""
    p = WURZEL / rel
    s = p.read_text(encoding="utf-8")
    n = s.count(alt)
    if n < anzahl:
        raise AssertionError("SABOTAGE TRIFFT NICHT (%dx) in %s: %r"
                             % (n, rel, alt[:70]))
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


def lauf() -> tuple[int, int, bool]:
    """(exit, fails, bilanz_da) – ueber ALLE Waechter summiert.

    `bilanz_da` ist nur dann wahr, wenn JEDER Lauf seine Bilanzzeile
    geschrieben hat: ein Abbruch ohne Bilanz ist von einem bestandenen Lauf
    nicht zu unterscheiden.
    """
    code = 0
    fails = 0
    alle_bilanz = True
    for befehl in WAECHTER:
        try:
            r = subprocess.run(befehl, capture_output=True, text=True,
                               timeout=300, cwd=str(WURZEL))
        except Exception:  # noqa: BLE001
            return (9, -1, False)
        aus = r.stdout + r.stderr
        # ⚠ ZWEI BILANZFORMATE im Projekt – wer nur eines kennt, haelt einen
        #   voellig gruenen Waechter fuer abgebrochen und bricht den ganzen
        #   Lauf mit "Basislauf nicht gruen" ab (am 2026-09-22 gemessen).
        m = re.search(r"(\d+) OK, (\d+) FAIL", aus)
        m2 = re.search(r"Ergebnis: (\d+)/(\d+)", aus)
        if m:
            fails += int(m.group(2))
        elif m2:
            fails += int(m2.group(2)) - int(m2.group(1))
        else:
            alle_bilanz = False
        code = code or r.returncode
    return (code, fails, alle_bilanz)


# ── Regel: jede angefasste Datei muss gesichert sein ────────────────────────
PROBEN: list[tuple[str, str, str, str]] = [
    # (Name, Datei, alt, neu)
    ("Zertifikat wird VOR der Pruefung gespeichert",
     "backend/ai_mouse_signatur.py",
     "    # ⚠ ERST PRUEFEN, DANN SCHREIBEN – siehe `_pkcs12_lesen`.\n    meta = _pkcs12_lesen(daten, kennwort)",
     "    meta = {}"),
    ("Kennwort im Klartext abgelegt",
     "backend/ai_mouse_signatur.py",
     'd["pw_enc"] = _verschluesseln(kennwort)',
     'd["pw_enc"] = kennwort'),
    ("PFX mit 0644 statt 0600",
     "backend/ai_mouse_signatur.py",
     "PFX_MODUS = 0o600",
     "PFX_MODUS = 0o644"),
    ("Schluesseldatei mit 0644",
     "backend/ai_mouse_signatur.py",
     "SCHLUESSEL_MODUS = 0o600",
     "SCHLUESSEL_MODUS = 0o644"),
    ("ist_signiert prueft nur die Existenz",
     "backend/ai_mouse_signatur.py",
     "            return bool(versatz and groesse)",
     "            return True"),
    ("Ablauf wird NACH dem Werkzeug geprueft (alte Reihenfolge)",
     "backend/ai_mouse_signatur.py",
     '    if ablauf and ablauf < time.time():\n        return (False, "Das hinterlegte Zertifikat ist am %s abgelaufen."\n                % (d.get("gueltig_bis") or "?"))\n\n    if not werkzeug_da():',
     '    if not werkzeug_da():'),
    ("Kennwort als Argument statt -readpass",
     "backend/ai_mouse_signatur.py",
     '"-readpass", str(pw_datei),',
     '"-pass", kennwort or "",'),
    ("TSA-Pruefung weg (alles wird angenommen)",
     "backend/ai_mouse_signatur.py",
     "    if not _TSA_RE.match(wert) or len(wert) > 300:",
     "    if False:"),
    ("Zustand gibt das Kennwort heraus",
     "backend/ai_mouse_signatur.py",
     '        "werkzeug_hinweis": werkzeug_hinweis(),',
     '        "werkzeug_hinweis": werkzeug_hinweis(),\n        "pw_enc": d.get("pw_enc", ""),'),
    ("Sperrliste: PFX aus _APP_DENY_REL",
     "backend/sandbox.py",
     '    "data/ai_mouse_signatur.json", "data/.aimousesignkey",\n    "data/.aimouse_sign.pfx",',
     '    "data/ai_mouse_signatur.json", "data/.aimousesignkey",'),
    ("Sperrliste: PRIVATE_FILES_STRENG ohne die PFX",
     "backend/sandbox.py",
     '                        "data/.aimouse_sign.pfx", "data/.aimousesignkey")',
     '                        "data/.aimousesignkey")'),
    ("Sperrliste: SHELL_SECRET_PATHS ohne die Muster",
     "backend/sandbox.py",
     "    r'ai_mouse_signatur\\.json\\b|\\.aimousesignkey\\b|\\.aimouse_sign\\.pfx\\b|'\n",
     ""),
    ("Endpunkt haengt an require_auth statt require_local_auth",
     "backend/main.py",
     'async def ai_mouse_signatur_status(user: str = Depends(require_local_auth)):',
     'async def ai_mouse_signatur_status(user: str = Depends(require_auth)):'),
    ("Lese-Endpunkt gibt die PFX heraus",
     "backend/main.py",
     '    return JSONResponse({"ok": True, **ai_mouse_signatur.zustand()})\n\n\n@app.post("/api/ai-mouse/admin/signatur")',
     '    _ = ai_mouse_signatur.PFX_DATEI.read_bytes()\n'
     '    return JSONResponse({"ok": True, **ai_mouse_signatur.zustand()})\n\n\n@app.post("/api/ai-mouse/admin/signatur")'),
    ("health liefert den Freigabe-Pfad nicht",
     "backend/main.py",
     '        "freigabe_pfad": ai_mouse.freigabe_pfad(),\n        # Der SIGNATURZUSTAND',
     '        # Der SIGNATURZUSTAND'),
    ("health liefert den Signaturzustand nicht",
     "backend/main.py",
     '        "signatur": ai_mouse_signatur.zustand_kurz(),',
     ''),
    ("Bauskript signiert gar nicht",
     "deploy/ai_mouse_build.sh",
     "    from backend import ai_mouse_signatur as s",
     "    from backend import ai_mouse as s"),
    ("freigabe_pfad ohne Deckel",
     "backend/ai_mouse.py",
     '    return wert.replace("\\r", " ").replace("\\n", " ")[:MAX_PFAD]',
     '    return wert'),
    ("freigabe_pfad laesst Zeilenumbrueche stehen",
     "backend/ai_mouse.py",
     '    return wert.replace("\\r", " ").replace("\\n", " ")[:MAX_PFAD]',
     '    return wert[:MAX_PFAD]'),
    ("Pfad geht per innerHTML hinaus",
     "frontend/js/ai_mouse.js",
     "wert.textContent = pfad;",
     "wert.innerHTML = pfad;"),
    # ⚠ DIE PROBE „Admin verliert den Download-Knopf" IST ERSATZLOS WEG.
    #   Sie stammte aus der Zeit, als der Admin den Knopf in der BENUTZER-Kachel
    #   behielt; seit dem Umbau (2026-09-22) gibt es diese Zeile nicht mehr, die
    #   Sabotage traf ins Leere. Die heutige Zusage – der Download ist in der
    #   Kachel fuer JEDEN weg – misst die Probe direkt darunter.
    ("Kennwortfeld wird nach dem Speichern nicht geleert",
     "frontend/js/ai_mouse_admin.js",
     "if (pw) { pw.value = ''; }",
     "if (pw) { /* bleibt stehen */ }"),
    ("Reiter laedt den Signaturzustand nicht",
     "frontend/js/ai_mouse_admin.js",
     "            this.signaturLaden();",
     ""),
    ("Klapp-Bindung fuer die Signatur-Sektion fehlt",
     "frontend/js/app.js",
     "                { hdr: 'am-sect-sign-hdr', body: 'am-sect-sign-body', tog: 'am-sect-sign-tog' },\n",
     ""),
    ("i18n: ein Schluessel nur auf Deutsch",
     "frontend/js/i18n.js",
     "        'amsign.st_signed':      'The application on file is signed.',\n",
     ""),

    # ── Eigentuemer-Erhalt (gemessener Vorfall 2026-09-22) ─────────────────
    # Der Bauskript-Weg laeuft als root; ohne diese Zeilen gehoert die Ablage
    # danach root, und der Dienst kann sie nicht mehr lesen. Die Signatur ist
    # ab dem ersten Bau still tot.
    ("Konfig laesst den Eigentuemer bei root",
     "backend/ai_mouse_signatur.py",
     "    os.chmod(KONFIG_DATEI, KONFIG_MODUS)\n    _eigentuemer_erhalten(KONFIG_DATEI)",
     "    os.chmod(KONFIG_DATEI, KONFIG_MODUS)"),
    ("PFX laesst den Eigentuemer bei root",
     "backend/ai_mouse_signatur.py",
     "        os.chmod(PFX_DATEI, PFX_MODUS)\n        _eigentuemer_erhalten(PFX_DATEI)",
     "        os.chmod(PFX_DATEI, PFX_MODUS)"),
    ("Schluesseldatei laesst den Eigentuemer bei root",
     "backend/ai_mouse_signatur.py",
     "        os.chmod(SCHLUESSEL_DATEI, SCHLUESSEL_MODUS)\n"
     "        _eigentuemer_erhalten(SCHLUESSEL_DATEI)",
     "        os.chmod(SCHLUESSEL_DATEI, SCHLUESSEL_MODUS)"),
    ("der Helfer faellt nicht auf das Verzeichnis zurueck",
     "backend/ai_mouse_signatur.py",
     "            dst = _DATA.stat()",
     "            return"),
    ("der Helfer wirkt auch als Nicht-root",
     "backend/ai_mouse_signatur.py",
     "        if os.geteuid() != 0:",
     "        if False:"),
    # ── Download im Admin-Reiter (Vorgabe 2026-09-22) ──────────────────────
    ("der Download bleibt fuer den Admin in der BENUTZER-Kachel",
     "frontend/js/ai_mouse.js",
     "        if (dlBox) { dlBox.classList.add('hidden'); }",
     "        if (dlBox) { dlBox.classList.toggle('hidden', !_istAdmin); }"),
    ("der Download-Knopf fehlt im Admin-Reiter",
     "frontend/settings.html",
     'id="amshare-dl"', 'id="amshare-dl-weg"'),
    ("er ist wieder ein <a href> mit Token in der Adresse",
     "frontend/settings.html",
     '<button class="btn-secondary" id="amshare-dl" type="button"',
     '<a class="btn-secondary" id="amshare-dl" href="/api/ai-mouse/paket"'),
    ("der Knopf ist nicht verdrahtet",
     "frontend/js/ai_mouse_admin.js",
     "            if (shDl) { shDl.addEventListener('click', this.holePaket.bind(this)); }",
     "            if (shDl) { /* nichts */ }"),
    ("er laedt ohne Authorization-Kopf",
     "frontend/js/ai_mouse_admin.js",
     "            fetch('/api/ai-mouse/paket', { headers: authHeaders() })",
     "            fetch('/api/ai-mouse/paket')"),
    ("der Paket-Endpunkt hat keinen Admin-Zweig",
     "backend/main.py",
     "    if _user_may_use_aimouse(user) or _is_admin_user(user):\n        return user\n    raise HTTPException(status_code=403,\n        detail=\"Kein Zugriff auf AI Mouse – nicht in der Benutzerliste/-Gruppe \"\n               \"freigeschaltet (Einstellungen → Sicherheit → Berechtigungen → \"\n               \"AI Mouse; ggf. neu einloggen für Gruppen-Aktualisierung)\")\n\n\n@app.get(\"/api/ai-mouse/paket\")",
     "    if _user_may_use_aimouse(user):\n        return user\n    raise HTTPException(status_code=403,\n        detail=\"Kein Zugriff auf AI Mouse – nicht in der Benutzerliste/-Gruppe \"\n               \"freigeschaltet (Einstellungen → Sicherheit → Berechtigungen → \"\n               \"AI Mouse; ggf. neu einloggen für Gruppen-Aktualisierung)\")\n\n\n@app.get(\"/api/ai-mouse/paket\")"),
    ("der tote i18n-Schluessel kehrt zurueck",
     "frontend/js/i18n.js",
     "        'aimouse.share_lab':     'Im Netz bereitgestellt',",
     "        'aimouse.share_admin':   'alter Satz',\n        'aimouse.share_lab':     'Im Netz bereitgestellt',"),

    # ── Kein Selbst-Update von einer Netzfreigabe (2026-09-22) ─────────────
    ("der Riegel gegen die Netzfreigabe fehlt",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "            if (VonNetzfreigabe())",
     "            if (false)"),
    ("der Riegel steht VOR der Versionspruefung",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "            if (!IstNeuer(serverVersion, Eigene))",
     "            if (VonNetzfreigabe()) { NetzVersion = \"x\"; return \"n\"; }\n            if (!IstNeuer(serverVersion, Eigene))"),
    ("die vorliegende Version wird nicht gemerkt",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "                NetzVersion = (serverVersion ?? string.Empty).Trim();",
     "                // nichts merken"),
    ("das Tray-Menue sagt nichts (stilles Abschalten)",
     "ai-mouse/src/AiMouse/TrayApplicationContext.cs",
     "        if (Update.Aktualisierung.NetzVersion.Length > 0)",
     "        if (false)"),
    ("der Hinweis ist anklickbar (es gaebe nichts zu wiederholen)",
     "ai-mouse/src/AiMouse/TrayApplicationContext.cs",
     "                Enabled = false,\n            });\n        }\n\n        _promptMenu.Items.Add(new ToolStripSeparator());\n\n        var copyItem",
     "            });\n        }\n\n        _promptMenu.Items.Add(new ToolStripSeparator());\n\n        var copyItem"),
    ("die Klasse kennt wieder die Lokalisierung",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "                NetzVersion = (serverVersion ?? string.Empty).Trim();",
     "                NetzVersion = Texte.Marke;"),
    ("der Text nennt nur EINE Version",
     "ai-mouse/src/AiMouse/Localization/Texte.cs",
     '"⚠ Version {0} liegt vor (hier läuft {1}). Diese Anwendung startet von "',
     '"⚠ Version {0} liegt vor. Diese Anwendung startet von "'),
    ("der Text sagt nicht, wer ausrollt",
     "ai-mouse/src/AiMouse/Localization/Texte.cs",
     '"Administration rollt den neuen Stand aus.",',
     '"aktualisiert sich nicht selbst.",'),
    ("die Version ist nicht hochgezaehlt",
     "ai-mouse/src/AiMouse/AiMouse.csproj",
     "<Version>1.0.10</Version>", "<Version>1.0.9</Version>"),
]

_dateien = {p[1] for p in PROBEN}
_fehlt = _dateien - set(DATEIEN)
if _fehlt:
    print("HARNESS-FEHLER: diese Dateien werden angefasst, aber NICHT "
          "gesichert: %s" % sorted(_fehlt))
    sys.exit(2)


def main() -> int:
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs – stelle wieder her.")
        zurueck()
        MARKE.unlink()

    sichern()
    MARKE.parent.mkdir(parents=True, exist_ok=True)
    MARKE.write_text("laeuft", encoding="utf-8")
    atexit.register(lambda: (zurueck(), MARKE.unlink(missing_ok=True)))
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_a: sys.exit(3))

    print("── Basislauf (muss gruen sein, sonst ist nichts deutbar) ──")
    code, fails, bilanz = lauf()
    if code != 0 or fails != 0 or not bilanz:
        print("ABBRUCH: Basislauf nicht gruen (exit=%s, FAIL=%s, Bilanz=%s)"
              % (code, fails, bilanz))
        return 2
    print("   Basis gruen.\n")

    beissen = 0
    for name, rel, alt, neu in PROBEN:
        zurueck()
        try:
            ersetze(rel, alt, neu)
        except AssertionError as e:
            print("  ⚠ %-58s %s" % (name, e))
            continue
        code, fails, bilanz = lauf()
        if not bilanz:
            print("  ⚠ %-58s KEINE BILANZ (Abbruch statt FAIL!)" % name)
            continue
        if fails > 0:
            beissen += 1
            print("  beisst  %-56s %d FAIL" % (name, fails))
        else:
            print("  STUMM   %-56s 0 FAIL  ← Testmangel!" % name)

    zurueck()
    print("\n%d von %d Gegenproben beissen." % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())

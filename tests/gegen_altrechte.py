"""Gegenprobe zu test_altrechte_ui (Container "alte Benutzerberechtigungen", 2026-10-21).

Dreht je EINE Zusage in einer Plattenkopie zurueck und erwartet FAILs MIT
Bilanzzeile; stellt danach byte-gleich wieder her (md5).

Gemessen werden PRODUKT-Zusagen, nicht der Waechter selbst:
  1. Der Container fehlt (Einzellisten liegen wieder frei herum).
  2. "connection" ist mit hineingerutscht (DC-Daten nur nach Aufklappen).
  3. Der zweite Speichern-Knopf fehlt wieder.
  4. Der Status laeuft wieder ueber EINE Id (nur eine Zeile meldet).
  5. "Verbindung testen" ist mit hineingerutscht.
  6. Der EN-Schluessel fehlt.

Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""
import hashlib, os, re, subprocess, sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
HTML = W / "frontend/settings.html"
AD = W / "frontend/js/settings_ad.js"
I18N = W / "frontend/js/i18n.js"
TEST = "test_altrechte_ui.js"
# ⚠ DIE TESTDATEI SELBST GEHOERT IN DIE SICHERUNGSLISTE, auch wenn keine Probe
# sie anfasst – zweimal darauf hereingefallen (Register).
DATEIEN = [HTML, AD, I18N, W / "tests" / TEST]
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
vorher = {p: md5(p) for p in DATEIEN}
sich = {p: p.read_bytes() for p in DATEIEN}
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def lauf(test=TEST):
    r = subprocess.run(["node", str(W / "tests" / test)],
                       capture_output=True, text=True, env=env, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


E = " " * 32      # Einrueckung der Bloecke in settings.html (Kinder: E + 4)
# Die drei Zeilen, die den Container aufmachen (Oeffnung, Kopfzeile, Koerper).
AUF = (f'{E}<details class="sec-sub" data-sub="altrechte">\n'
       f'{E}    <summary style="font-weight:400;">'
       '<span data-i18n="security.sub_altrechte">alte Benutzerberechtigungen'
       '</span><span class="sec-sub-hint" data-i18n="security.sub_altrechte_hint">'
       '– Einzellisten je Bereich, von Hand gepflegt</span></summary>\n'
       f'{E}    <div class="sec-sub-body">\n')
# Der zweite Speichern-Knopf im Container "Verbindung".
KNOPF2 = (f'{E}    <button class="kb-btn-action" data-klick="ad-speichern" '
          'data-i18n="common.save">Speichern</button>\n')
TESTKNOPF = (f'{E}    <button class="kb-btn-secondary" data-klick="ad-testen" '
             'data-i18n="profile.test">Verbindung testen</button>\n')
TESTERG = (f'{E}<div id="ad-test-result" '
           'style="font-size:0.82rem;min-height:18px;margin-top:4px;"></div>\n')
# Der ganze Zertifikats-Baustein (Hinweistext, Uebergangswarnung, Container,
# in dem sapcert.js Knopf und Verankert-Zeile erzeugt).
CERT = (f'{E}<p class="kb-hint" style="margin:10px 0 4px;" '
        'data-i18n="security.ad_tls_hint">Anmeldungen über das Firmenverzeichnis laufen nur '
        'verschlüsselt und mit geprüftem Zertifikat des Domain-Controllers. Stammt es von '
        'einer internen Zertifizierungsstelle, hier prüfen und verankern.</p>\n'
        f'{E}<p id="ad-tls-uebergang" hidden '
        'style="margin:6px 0;font-size:0.82rem;color:var(--warning);"></p>\n'
        f'{E}<div class="sapcert" id="ad-cert"></div>\n')
SPEICHERN1 = (f'{E}    <button class="kb-btn-action" id="ad-save-btn" '
              'data-klick="ad-speichern" data-i18n="common.save">Speichern</button>\n')

# ⚠ EINE SABOTAGE MUSS DIE ZUSAGE VERLETZEN, NICHT DEN WAECHTER ABSTUERZEN
# LASSEN. "Container umbenennen" liess `querySelector` null liefern und den
# Lauf auf Exit 2 enden – Exit 2 heisst "konnte nicht laufen" und ist von einem
# Befund nicht zu unterscheiden. Deshalb werden die Bloecke wirklich VERSCHOBEN
# bzw. die Klammer wirklich geoeffnet und geschlossen; dafuer darf eine Probe
# mehrere Ersetzungen tragen.
# (Name, [(Datei, Anker, Ersatz), …])
PROBEN = [
    # Das <details> wird zu einem <div>: es gibt den Container nicht mehr, die
    # Einzellisten liegen wieder frei herum.
    ("Container fehlt", [
        (HTML, '<details class="sec-sub" data-sub="altrechte">', '<div class="sec-sub">'),
        (HTML, f'<span id="ad-save-status" class="ad-save-status" style="font-size:0.82rem;">'
               f'</span>\n{E}</div>\n\n{E}    </div>\n{E}</details>',
               f'<span id="ad-save-status" class="ad-save-status" style="font-size:0.82rem;">'
               f'</span>\n{E}</div>\n\n{E}    </div>\n{E}</div>'),
    ]),
    # Die Klammer geht eine Ebene hoeher auf: "Verbindung (Domain-Controller)"
    # liegt dann mit im zugeklappten Container.
    ("connection liegt mit darin", [
        (HTML, AUF, ''),
        (HTML, f'{E}<details class="sec-sub" data-sub="connection">',
               AUF + f'{E}<details class="sec-sub" data-sub="connection">'),
    ]),
    # Der zweite Knopf fehlt wieder: die DC-Daten sind nur nach Aufklappen
    # speicherbar.
    ("zweiter Speichern-Knopf fehlt", [(HTML, KNOPF2, '')]),
    # Der Status laeuft wieder ueber EINE Id: wer den Verbindungs-Knopf klickt,
    # sieht keine Meldung.
    ("Status wieder ueber eine Id", [
        (AD, "const sts = document.querySelectorAll('.ad-save-status');",
             "const sts = [document.getElementById('ad-save-status')];"),
    ]),
    # "Verbindung testen" rutscht aus dem Verbindungs-Container heraus in den
    # zugeklappten – der Knopf steht dann nicht mehr bei den Feldern, die er
    # prueft.
    ("Verbindung testen liegt in altrechte", [
        (HTML, TESTKNOPF, ''),
        (HTML, SPEICHERN1, SPEICHERN1 + TESTKNOPF),
    ]),
    # Die Ergebniszeile bleibt zurueck, waehrend der Knopf umzieht – ein
    # Ergebnis ausserhalb des Sichtfensters ist fuer den Benutzer "nichts
    # passiert".
    ("Ergebniszeile steht nicht beim Knopf", [
        (HTML, TESTERG, ''),
        (HTML, f'{E}<script src="/static/js/settings_unterklappen.js?v=1"></script>\n',
               f'{E}<script src="/static/js/settings_unterklappen.js?v=1"></script>\n' + TESTERG),
    ]),
    # Der Zertifikats-Baustein steht wieder ausserhalb beider Container –
    # dort, wo er bis 2026-10-21 lag.
    ("Zertifikat steht ausserhalb des Verbindungs-Containers", [
        (HTML, CERT, ''),
        (HTML, f'{E}<script src="/static/js/settings_unterklappen.js?v=1"></script>\n',
               f'{E}<script src="/static/js/settings_unterklappen.js?v=1"></script>\n' + CERT),
    ]),
    # Der Baustein rutscht in den zugeklappten Altweg-Container.
    ("Zertifikat liegt in altrechte", [
        (HTML, CERT, ''),
        (HTML, SPEICHERN1, SPEICHERN1 + CERT),
    ]),
    # Die Kopfzeile des Altwegs ist wieder fett wie jede andere.
    ("Kopfzeile wieder fett", [
        (HTML, f'{E}    <summary style="font-weight:400;">'
               '<span data-i18n="security.sub_altrechte">',
               f'{E}    <summary><span data-i18n="security.sub_altrechte">'),
    ]),
    # Der Regelweg ist wieder normal gewichtet und tritt damit nicht hervor.
    ("Regelweg wieder normal", [
        (HTML, 'id="rmx-open" style="font-weight:600;" data-i18n="rmx.open_btn"',
               'id="rmx-open" data-i18n="rmx.open_btn"'),
    ]),
    # Der EN-Schluessel fehlt.
    ("EN-Schluessel fehlt", [
        (I18N, "        'security.sub_altrechte':       'legacy user permissions',\n", ""),
    ]),
]

rc_ende = 1
try:
    rc, f = lauf()
    if rc != 0 or f != 0:
        print(f"ABBRUCH: Basis {TEST} nicht gruen (rc={rc}, FAIL={f})")
        sys.exit(2)
    print("Basis gruen.")
    gut = 0
    for name, patches in PROBEN:
        # Alle Anker der Probe muessen GENAU EINMAL treffen – sonst ist nicht
        # die Zusage schwach, sondern die Probe verfehlt.
        neu, verfehlt = {}, []
        for datei, anker, ersatz in patches:
            txt = neu.get(datei, sich[datei].decode())
            if txt.count(anker) != 1:
                verfehlt.append(f"{datei.name}: {txt.count(anker)}x")
                continue
            neu[datei] = txt.replace(anker, ersatz, 1)
        if verfehlt:
            print(f"  VERFEHLT {name}: Anker {', '.join(verfehlt)}")
            continue
        for datei, txt in neu.items():
            datei.write_text(txt, encoding="utf-8")
        try:
            rc, f = lauf()
        finally:
            for datei in neu:
                datei.write_bytes(sich[datei])
        # ⚠ EIN ABSTURZ IST KEIN BISS: Exit 2 heisst "konnte nicht laufen",
        # und eine Probe ohne Bilanzzeile ist von "nicht gelaufen" nicht zu
        # unterscheiden. Verlangt wird Exit 1 MIT gezaehlten FAILs.
        biss = rc == 1 and (f or 0) > 0
        gut += biss
        print(f"  {'OK     ' if biss else 'ZAHNLOS'} {name}: rc={rc} FAIL={f}")
    print(f"{gut} von {len(PROBEN)} beissen.")
    rc_ende = 0 if gut == len(PROBEN) else 1
finally:
    for p in DATEIEN:
        p.write_bytes(sich[p])
    print("byte-gleich:", all(md5(p) == vorher[p] for p in DATEIEN))
sys.exit(rc_ende)

#!/usr/bin/env python3
"""Gegenprobe zu tests/test_cve_pruefung.py: beisst der Waechter?

Jede Probe dreht EINE Zusage der CVE-Pruefung zurueck, laesst den Waechter
laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach
Byte-Gleichheit aller Dateien per md5, ohne Bytecode, mit Laufmarke (ein
abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

⚠ NIE in einem Sammellauf mitlaufen lassen – die Proben patchen Dateien.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_cve_pruefung.laufmarke"

CP = "backend/cve_pruefung.py"
MA = "backend/main.py"
CA = "backend/cve_apt.py"
SC = "backend/scheduler.py"
DA = "backend/broker/daemon.py"
OP = "backend/broker/ops.py"
SP = "frontend/js/syspackages.js"

PROBEN = [
    ("/api/me ohne cve_badge", MA, '        "cve_badge": cve_badge,\n', ''),
    ("Fremdquelle (NodeSource) gilt als Debian", CP,
     '        return not passt(eigene)', '        return False'),
    ("Zuordnung ueber das Binaerpaket statt die Quelle", CP,
     'gruppen.setdefault(p["quelle"], []).append(p)', 'gruppen.setdefault(p["paket"], []).append(p)'),
    ("Kernel ohne Sonderfall (laufender Kernel egal)", CP,
     'ist_kernel = quelle == "linux" and bool(kernel)', 'ist_kernel = False'),
    # KEINE Probe "fixed_version 0": dafuer gibt es keinen eigenen Zweig – der
    # Versionsvergleich verwirft es (jede Version >= 0). Die Probe blieb stumm,
    # weil die Zusage nicht separat existiert; der Waechter prueft die WIRKUNG.
    ("Vergleich behoben/installiert umgedreht", CP,
     'alt = [p for p in bins if cve_apt.vergleiche(p["quell_version"], fv) < 0]',
     'alt = [p for p in bins if cve_apt.vergleiche(p["quell_version"], fv) >= 0]'),
    ("nicht Eingestuftes faellt unter jede Schwelle", CP,
     '    if einstufung not in RANG:\n        return True', '    if einstufung not in RANG:\n        return False'),
    ("regulaere Quelle ohne Schalter", CP,
     'if b.get("aus_sicherheitsquelle") or einst["regulaere_quelle"]:', 'if True:'),
    ("Python im Lock-Modus gilt als behebbar", CP,
     '(("lock" if lock else "behebbar") if f.get("behoben_in") else "offen")',
     '("behebbar" if f.get("behoben_in") else "offen")'),
    ("OSV-Doppeleintraege derselben CVE nicht gebuendelt", CP,
     '        if k in je:\n            _vereinen(je[k], f, "behoben_in")',
     '        if False:\n            _vereinen(je[k], f, "behoben_in")'),
    ("Buendelung nimmt die niedrigere Behebung", CP,
     'if b and (not a or cve_apt.vergleiche(b, a) > 0):', 'if b and not a:'),
    ("Buendelung vergisst die Bewertung", CP,
     'je[k]["ausgenommen"] = bool(je[k].get("ausgenommen") or f.get("ausgenommen"))',
     'pass'),
    ("Einzel-Update nimmt auch Nicht-Behebbares", CP,
     '            and b["klasse"] == "behebbar" for n in b.get("beheben_mit") or []})',
     '            for n in b.get("beheben_mit") or []})'),
    ("Kurzbericht verschweigt die regulaere Quelle", CP,
     '        if pl.get("nur_regulaere_quelle"):', '        if False:'),
    ("gespeichertes Ergebnis nicht an den laufenden Kernel angeglichen", CP,
     '        erg = kernel_nachfuehren(_lesen(ERGEBNIS, None), laufender_kernel())',
     '        erg = _lesen(ERGEBNIS, None)'),
    ("gespeichertes Ergebnis nicht an die installierten Python-Pakete angeglichen", CP,
     'wert=python_nachfuehren(erg, python_installiert()))', 'wert=erg)'),
    ("Stempel der site-packages fehlt im Cache-Schluessel", CP,
     'm = (st.st_mtime_ns, st.st_size, st.st_ino, _site_stempel())',
     'm = (st.st_mtime_ns, st.st_size, st.st_ino)'),
    ("Python-Angleichung ohne Behebungsnachweis (jede neue Fassung gilt als sauber)", CP,
     'if v and v != b.get("version") and _py_behoben(v, b.get("fix") or ""):',
     'if v and v != b.get("version"):'),
    ("Python-Fassungen als Text verglichen", CP,
     'return Version(installiert) >= Version(fix)', 'return installiert >= fix'),
    ("Python-Angleichung trifft auch Debian-Pakete gleichen Namens", CP,
     '        if b.get("bereich") == "python":\n            v = inst.get(',
     '        if True:\n            v = inst.get('),
    ("Python-Angleichung rechnet die Zaehler nicht neu", CP,
     'return dict(erg, befunde=rest, zaehler=zaehler,',
     'return dict(erg, befunde=rest, zaehler=erg.get("zaehler"),'),
    ("Stand fehlt im Pruefergebnis", CP,
     '"stand": python_stand(inst)}, "befunde": befunde}', '}, "befunde": befunde}'),
    ("Stand haengt an der Reihenfolge", CP,
     'for n, v in sorted(inst.items()))', 'for n, v in inst.items())'),
    ("nach_paketwechsel ohne Stand-Vergleich", CP,
     '.get("stand") == jetzt:\n        return False', '.get("stand") == "nie":\n        return False'),
    ("nach_paketwechsel prueft auch ohne fruehere Pruefung", CP,
     '    if not erg or _status["laeuft"]:\n        return False\n    from backend import abhaengigkeiten',
     '    if _status["laeuft"]:\n        return False\n    from backend import abhaengigkeiten'),
    ("nach_paketwechsel startet neben einem laufenden Lauf", CP,
     '    if not erg or _status["laeuft"]:\n        return False\n    from backend import abhaengigkeiten',
     '    if not erg:\n        return False\n    from backend import abhaengigkeiten'),
    ("nach_paketwechsel behebt statt nur zu pruefen", CP,
     'lauf(beheben=False, ausloeser="paketwechsel")', 'lauf(beheben=True, ausloeser="paketwechsel")'),
    ("Start-Hook prueft nach dem Paketwechsel nicht neu", MA,
     'if await asyncio.to_thread(_cve.nach_paketwechsel):', 'if False:'),
    ("Angleichung verwirft auch Kernel-Befunde, die der Kernel NICHT behebt", CP,
     '                       and cve_apt.vergleiche(kernel, b["fix"]) >= 0)]',
     '                       )]'),
    ("Badge zaehlt Quittiertes mit", CP,
     'if b["klasse"] == "ausgenommen" or b["id"] in q:', 'if b["klasse"] == "ausgenommen":'),
    ("Lock-Fall quittierbar", CP,
     'QUITTIERBAR = ("offen", "nicht_im_index", "zurueckgehalten")',
     'QUITTIERBAR = ("offen", "nicht_im_index", "zurueckgehalten", "lock")'),
    ("behebbar quittierbar", CP,
     'erlaubt = {b["id"] for b in erg.get("befunde") or [] if b.get("quittierbar")}',
     'erlaubt = {b["id"] for b in erg.get("befunde") or []}'),
    ("beheben auch bei Wahrheitswert statt True", CP,
     'return {"beheben": d.get("beheben") is True, "schwelle": sw}',
     'return {"beheben": bool(d.get("beheben")), "schwelle": sw}'),
    ("Tilde sortiert hinter statt vor", CA,
     '    if c == "~":\n        return -1', '    if c == "~":\n        return 1'),
    ("hold wird angefasst", CA, 'if st == "hi":', 'if False:'),
    ("Sicherheitsquelle nicht erzwungen", CA,
     'if nur_sicherheit and not info.get("sicherheit"):', 'if False:'),
    ("geplante Entfernung wird ignoriert", CA,
     'if sim.returncode != 0 or re.search(r"^Remv ", sim.stdout or "", re.M):',
     'if sim.returncode != 0:'),
    ("--no-remove fehlt", CA,
     '"--only-upgrade", "--no-remove",', '"--only-upgrade",'),
    ("Auftragsart fehlt in der Whitelist", SC,
     '"cve_pruefung") else "agent",', ') else "agent",'),
    ("Optionen auch fuer fremde Auftragsart", SC,
     'if job.get("kind") != "cve_pruefung":', 'if False:'),
    ("Op nicht als lange Op", DA, '"cve_beheben"})', '})'),
    ("nur_sicherheit nicht fail-closed", OP,
     'nur_sicherheit=args.get("nur_sicherheit") is not False,',
     'nur_sicherheit=bool(args.get("nur_sicherheit")),'),
    # Offene Eintraege (7zip, 2026-10-29): Auskunft ueber Behebung anderswo,
    # Zwischenrelease und Art der Nicht-Meldung – Backend und Anzeige.
    ("offener Eintrag ohne Zwischenrelease-Markierung", CP,
     '                b["zwischenrelease"] = bool(r.get("next_point_update"))\n'
     '                b["anderswo"]',
     '                b["anderswo"]'),
    ("anderswo zaehlt fixed_version 0 als Behebung", CP,
     '                            and str(o.get("fixed_version") or "0") != "0"}',
     '                            }'),
    ("anderswo zaehlt offene Releases mit", CP,
     'if n != rel and o.get("status") == "resolved"', 'if n != rel'),
    ("anderswo niedrigste Version zuerst", CP,
     'for v in sorted(je, key=_vschluessel, reverse=True)]',
     'for v in sorted(je, key=_vschluessel)]'),
    ("nodsa: Art ersetzt wieder die Begruendung", CP,
     '"nodsa": str(r.get("nodsa") or ""),',
     '"nodsa": str(r.get("nodsa_reason") or r.get("nodsa") or ""),'),
    ("Anzeige verschweigt das Zwischenrelease", SP,
     'if (b.zwischenrelease) zusatz.push(', 'if (false) zusatz.push('),
    ("Anzeige verschweigt die Behebung anderswo", SP,
     '            if (aw) zusatz.push(aw);\n', ''),
    ("Anzeige: ignored als ohne Sicherheitsmeldung", SP,
     "if (grund === 'ignored') art =", "if (false) art ="),
    ("Anzeige: Altbestand nicht erkannt", SP,
     "if (!grund && (text === 'ignored' || text === 'postponed')) { grund = text; text = ''; }", ''),
    # Fehlende WhatsApp-Bridge ist kein Bereich (2026-10-29).
    ("fehlende Bridge wieder als 'nicht geprueft'", CP,
     '        if teil["info"].get("entfaellt"):\n            continue\n', ''),
    # Vollstaendige Fremdpaket-Liste (2026-10-29: chrome/sentinelagent fehlten).
    ("Fremdliste nur ueber Pakete mit Befund", CP,
     'namen = sorted(n for n in nach_name if not _KERNEL_VERSIONIERT.match(n))',
     'namen = sorted({n for b in befunde for n in b["pakete"] if n in nach_name})'),
    ("versionierte Kernelpakete gelten als fremd", CP,
     'namen = sorted(n for n in nach_name if not _KERNEL_VERSIONIERT.match(n))',
     'namen = sorted(nach_name)'),
    ("Paket ohne apt-Auskunft gilt als fremd", CP,
     '        if info and fremde_herkunft(info, rel):', '        if fremde_herkunft(info or {}, rel):'),
    # Node.js-Laufzeit (2026-10-29: NodeSource-nodejs war ungeprueft).
    ("pruefen() ohne Node-Bereich", CP,
     '("npm", npm_pruefen()),\n                       ("node", node)):', '("npm", npm_pruefen())):'),
    ("geprueftes nodejs bleibt in der Fremdliste", CP,
     '        deb_info["fremd"] = [n for n in deb_info["fremd"] if n != np_]\n', ''),
    ("nodejs verlaesst die Fremdliste auch ungeprueft", CP,
     'if node["info"].get("geprueft") and np_ and', 'if np_ and'),
    ("semver: erste zutreffende Alternative entscheidet", CP,
     '        treffer = treffer or all(werte)\n', '        if all(werte):\n            return True\n'),
    ("semver: Caret ignoriert die Hauptversion", CP,
     '            return v[0] == p[0]\n        if p[1] or k == 2:', '            return True\n        if p[1] or k == 2:'),
    ("nicht deutbarer Eintrag still uebergangen", CP,
     '            undeutbar.append(kennung)\n', ''),
    ("Behebung aus anderer Hauptversion gilt als fix", CP,
     'gleich = [g for g in grenzen if g[0] == v[0] and g > v]', 'gleich = [g for g in grenzen if g > v]'),
    ("Ende der Unterstuetzung ohne Befund", CP, '    elif ende < heute:', '    elif False:'),
    ("Node: Kandidat nicht gegen die Behebung geprueft", CP,
     'ok = kand is not None and kand >= _node_v(b["fix"])', 'ok = True'),
    ("Node: hold wird uebergangen", CP,
     '            elif inst["status"] == "hi":', '            elif False:'),
    ("Node aus Debian doppelt geprueft", CP, '        if inst["debian"]:\n', '        if False:\n'),
    ("Node: ohne apt-Auskunft gilt als Debian", CP,
     '"debian": (not fremde_herkunft(info, rel)) if info else None}',
     '"debian": (not fremde_herkunft(info, rel)) if info else True}'),
    ("Node wird automatisch gehoben", CP,
     '            node_von_hand += 1\n', '            pakete.update(b.get("beheben_mit") or [])\n'),
    ("Einzel-Update kennt Node nicht", CP,
     'if b["bereich"] in ("debian", "node") and b["quelle"] == quelle',
     'if b["bereich"] == "debian" and b["quelle"] == quelle'),
    ("Node: behebbar quittierbar", CP,
     'or (b["bereich"] == "node" and not b.get("beheben_mit")))', 'or b["bereich"] == "node")'),
    ("Node-Quelle ohne gespeicherten Stand", CP,
     '    if isinstance(alt, dict) and alt:\n        return alt,', '    if False:\n        return alt,'),
    ("Kurzbericht verschweigt Node von Hand", CP, '        if pl.get("node_von_hand"):', '        if False:'),
    ("Anzeige: Node-Befund verlinkt den Debian-Tracker", SP,
     "        if (b.bereich === 'node') {\n            if (!/^https", "        if (false) {\n            if (!/^https"),
    ("Anzeige: Node nicht in der Paketzeile", SP,
     "return b.bereich === 'debian' || (b.bereich === 'node' && (b.pakete || []).length > 0);",
     "return b.bereich === 'debian';"),
    ("Anzeige: Fremdquelle ungenannt", SP,
     "if (b.klasse === 'behebbar' && b.aus_fremdquelle) {", "if (false) {"),
    ("Anzeige: Einzelknopf ohne Zielpaket", SP,
     "&& (b.beheben_mit || []).length) quellen[b.quelle] = true;", ") quellen[b.quelle] = true;"),
    ("Anzeige: Behebung in anderen Hauptversionen ungenannt", SP,
     "            if (b.fix_andere) {", "            if (false) {"),
    # Filter "Nur noch nicht gesehene" (2026-10-29).
    ("Filter: ungesehen wird ignoriert", SP,
     "        if (_nurUngesehen && !(info && quittierbareIds(info.befunde).length)) return false;\n", ''),
    ("Filter: Befunde ohne Paket ungefiltert", SP,
     "        if (!_nurUngesehen) return befunde;\n", "        return befunde;\n"),
    ("Filter: Paketliste ruft den Filter nicht", SP,
     "        alle = alle.filter(function (p) { return paketGezeigt(jePaket[p.package]); });\n", ''),
    ("Filter: Haekchen fehlt", SP,
     """filter += '<label class="jv-pkg-cve-filter"><input type="checkbox" id="jv-pkg-nurungesehen"'""",
     """filter += '<label class="jv-pkg-cve-filter"><input type="checkbox" id="jv-pkg-x"'"""),
]

DATEIEN = [CP, CA, SC, DA, OP, MA, SP, "tests/test_cve_pruefung.py"]

WAECHTER = [
    (["python3", "tests/test_cve_pruefung.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
    (["node", "tests/test_cve_anzeige_ui.js"], r"^(\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout, re.M)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {(r.stdout + r.stderr).strip()[-200:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    """Rueckstand eines abgeschossenen Laufs zuruecknehmen (Laufmarke)."""
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-58s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())

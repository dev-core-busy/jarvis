#!/usr/bin/env python3
"""Gegenprobe zu den H10-Waechtern: beissen sie?

Waechter: tests/test_bsi_h10.py (Grenzen, Namespace, Broker-Op, Werkzeug),
tests/test_bsi_h10_dispatch.py (echte Laeufe durch agent.py) und
tests/test_bsi_h10_ui.js (Panel). Jede Probe dreht EINEN Teil des H10-Fixes
zurueck (Python-Ersetzung ganzer Zeilen), laesst ALLE drei Waechter laufen und
erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach
Byte-Gleichheit aller Dateien per md5. Ohne Bytecode
(PYTHONDONTWRITEBYTECODE=1 – Register: gleich grosse Sabotage in derselben
Sekunde laedt sonst die .pyc der Probe). Laufmarke: ein abgeschossener Lauf
wird beim naechsten Start zurueckgenommen.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

    venv/bin/python tests/gegen_bsi_h10.py
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
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() \
    else sys.executable
MARKE = ROOT / "tests" / ".gegen_bsi_h10.laufmarke"

SG = "backend/sandbox_grenzen.py"
LT = "backend/lauf_tmp.py"
OP = "backend/broker/ops.py"
SH = "backend/tools/shell.py"
AG = "backend/agent.py"
JS = "frontend/js/security_incidents.js"
HT = "frontend/settings.html"

PROBEN = [
    # ── sandbox_grenzen ──
    ("Grenze 0/-1 hebt auf (kein Klemmen)", SG,
     "        aus[k] = max(lo, min(hi, v))\n", "        aus[k] = v\n"),
    ("bool zaehlt als Zahl", SG,
     "        if isinstance(v, bool):\n            v = None\n", "        if False:\n            v = None\n"),
    ("Praefix klemmt nicht", SG,
     "    g = grenzen_pruefen(grenzen)\n", "    g = dict(STANDARD, **(grenzen or {}))\n"),
    ("Swap als Ausweg", SG, "        \"-p\", \"MemorySwapMax=0\",\n", ""),
    ("Laufzeitgrenze ohne Puffer und Deckel", SG,
     "    laufzeit = max(30, min(LAUFZEIT_MAX_S, t + LAUFZEIT_PUFFER_S))\n",
     "    laufzeit = max(30, t)\n"),
    ("leere Einstellung schaltet die Sandbox ab (Befund H10)", SG,
     "    kandidaten += [gesetzt, SBX_USER]\n", "    kandidaten += [gesetzt]\n"),
    ("ohne Internet kein netzgesperrter Standardbenutzer", SG,
     "        kandidaten += [gesetzt_ni, NOINET_USER]\n", "        kandidaten += [gesetzt_ni]\n"),
    ("jeder vorhandene Benutzer gilt als Sandbox", SG,
     "    return bool(name) and name.startswith(SANDBOX_PREFIX) and uid not in (None, 0)\n",
     "    return bool(name) and uid is not None\n"),
    ("Loopback-Sperre ohne uid-Bindung", SG,
     "        f\"        oif \\\"lo\\\" meta skuid {{ {ids} }} reject\\n\"\n",
     "        f\"        oif \\\"lo\\\" reject\\n\"\n"),
    ("bereit() ohne systemd-run-Pruefung", SG,
     "    if not os.path.exists(SYSTEMD_RUN):\n", "    if False:\n"),
    ("bereit() ohne bwrap-Pruefung", SG,
     "        if not _lt.bwrap_verfuegbar(sandbox_user):\n", "        if False:\n"),
    ("bereit() ohne Loopback-Sperre", SG,
     "    ok, grund = lo_sperre_sicherstellen()\n", "    ok, grund = True, \"\"\n"),
    ("Admin-Schalter: Muell gilt als Entscheidung", SG,
     "    return v if isinstance(v, bool) else VORGABE_ADMINS\n",
     "    return bool(v) if v is not None else VORGABE_ADMINS\n"),
    ("Admin-Schalter: Vorgabe wieder AUS", SG,
     "VORGABE_ADMINS = True\n", "VORGABE_ADMINS = False\n"),
    ("Bestand bekommt die neue Vorgabe", SG,
     "        wert = False if bestand else VORGABE_ADMINS\n",
     "        wert = VORGABE_ADMINS\n"),
    ("Festschreiben ueberschreibt gesetzten Wert", SG,
     "        if config.get_setting(EINSTELLUNG_ADMINS, None) is not None:\n            return None\n",
     "        pass\n"),
    # ── lauf_tmp ──
    ("pflicht faellt still zurueck (fail-open)", LT,
     "            raise IsolationFehlt(\"bubblewrap nicht verfuegbar\")\n",
     "            return innen + \"/bin/bash -c %s\" % shlex.quote(command)\n"),
    ("--unshare-net fehlt", LT, "        teile += [\"--unshare-net\"]\n", "        pass\n"),
    ("verbergen wirkungslos", LT, "        teile += [\"--tmpfs\", str(v)]\n", "        pass\n"),
    ("fehlendes Verbergen-Verzeichnis wird hingenommen", LT,
     "            raise IsolationFehlt(f\"zu verbergendes Verzeichnis fehlt: {v}\")\n",
     "            pass\n"),
    ("Grenzen-Praefix ignoriert", LT,
     "    vorn = \"\".join(shlex.quote(str(t)) + \" \" for t in (praefix or ()))\n",
     "    vorn = \"\"\n"),
    # ── Broker-Op ──
    ("Broker prueft bereit() nicht", OP,
     "    ok, grund = _sg.bereit(user)\n", "    ok, grund = True, \"\"\n"),
    ("netzgesperrter Benutzer nicht immer ohne Netz", OP,
     "    ohne_netz = bool(args.get(\"ohne_netz\")) or user == _sg.NOINET_USER\n",
     "    ohne_netz = bool(args.get(\"ohne_netz\"))\n"),
    ("fehlendes Arbeitsverzeichnis -> gemeinsames /tmp", OP,
     "                return _abgelehnt(\"privates Arbeitsverzeichnis nicht bereitstellbar\")\n",
     "                pass\n"),
    ("ohne Kennung laeuft im echten /tmp", OP,
     "            return _abgelehnt(\"kein privates Arbeitsverzeichnis angefordert\")\n",
     "            pass\n"),
    ("ohne_lauf nimmt jeden wahren Wert", OP,
     "        elif args.get(\"ohne_lauf\") is True:\n", "        elif args.get(\"ohne_lauf\"):\n"),
    ("Admin sieht private Bereiche der Domain-Benutzer", OP,
     "                verbergen.append(str(w))\n", "                pass\n"),
    ("Op wieder unter altem Namen (alter Broker fuehrt aus)", OP,
     "    \"sandbox_lauf\": (\n", "    \"sandbox_exec\": (\n"),
    ("Ausnahme -> Rueckfall auf nacktes runuser", OP,
     "        return _abgelehnt(f\"Isolation nicht anwendbar: {e}\")\n",
     "        wrapped = \"runuser -u %s -- /bin/bash -c %s\" % (shlex.quote(user), shlex.quote(command))\n"),
    ("Grenz-Treffer nicht gemeldet", OP,
     "        res[\"grenze_getroffen\"] = _sg.grenze_vermutlich_getroffen(res.get(\"rc\"))\n",
     "        res[\"grenze_getroffen\"] = False\n"),
    # ── ShellTool ──
    ("Werkzeug laeuft ohne privates /tmp", SH,
     "            if not _lauf and not _ohne_lauf:\n", "            if False:\n"),
    ("alter Broker wird nicht erkannt", SH,
     "        if op == \"sandbox_lauf\" and decision == \"unknown-op\":\n", "        if False:\n"),
    ("Abweisung des Brokers wird verschluckt", SH,
     "        if op == \"sandbox_lauf\" and res.get(\"abgelehnt\"):\n", "        if False:\n"),
    ("Werkzeug ruft die alte Op", SH,
     "                        \"sandbox_lauf\",\n", "                        \"sandbox_exec\",\n"),
    ("ohne_netz geht nicht an den Broker", SH,
     "                         \"ohne_netz\": _ohne_netz, \"grenzen\": _grenzen,\n",
     "                         \"grenzen\": _grenzen,\n"),
    ("kein Grenz-Hinweis", SH,
     "        if res.get(\"grenze_getroffen\"):\n", "        if False:\n"),
    # ── Dispatch ──
    ("Domain-Benutzer ohne Sandbox-Pflicht", AG,
     "                    _sbx_pflicht = True\n", "                    _sbx_pflicht = False\n"),
    ("Lauf-Isolation nicht verlangt (fail-open)", AG,
     "                elif not _privileged and _lauf_tmp.aktueller_lauf() is None:\n",
     "                elif False:\n"),
    ("Grund wird nicht ausgewertet (leerer Benutzer laeuft)", AG,
     "                if _sbx_grund:\n", "                if False:\n"),
    ("ohne Internet trotzdem mit Netz", AG,
     "                    exec_args['_ohne_netz'] = not _sbx_inet\n",
     "                    exec_args['_ohne_netz'] = False\n"),
    ("Admin-Schalter wirkungslos", AG,
     "                elif _sbx_grenzen.auch_admins():\n", "                elif False:\n"),
    ("Root-Befehle der Admins in die Sandbox", AG,
     "                    _sbx_pflicht = not _sh_needs_root(args.get(\"command\", \"\") or \"\")\n",
     "                    _sbx_pflicht = True\n"),
    ("Admin-Lauf ohne ohne_lauf (wuerde abgewiesen)", AG,
     "                    exec_args['_ohne_lauf'] = bool(_privileged)\n",
     "                    exec_args['_ohne_lauf'] = False\n"),
    ("Root-Broker-Weg parallel zur Sandbox", AG,
     "                    and not exec_args.get('_sandbox_user')):\n", "                    ):\n"),
    ("Desktop/Browser fuer Domain-Benutzer offen", AG,
     "    \"desktop_control\", \"browser_control\", \"browser_cdp\",\n", ""),
    # ── Oberflaeche ──
    ("Deaktivieren-Knopf wieder da", HT,
     "                                    <button type=\"button\" id=\"sec-sandbox-verify\" data-i18n=\"security.sandbox_verify\" class=\"sec-btn\">Isolation testen</button>\n",
     "                                    <button type=\"button\" id=\"sec-sandbox-verify\" data-i18n=\"security.sandbox_verify\" class=\"sec-btn\">Isolation testen</button>\n"
     "                                    <button type=\"button\" id=\"sec-sandbox-teardown\" class=\"sec-btn danger\">Deaktivieren</button>\n"),
    ("Schalter sendet Text statt bool", JS,
     "                Mgr.saveSandboxCfg({ auch_admins: !!sbAdm.checked });\n",
     "                Mgr.saveSandboxCfg({ auch_admins: String(sbAdm.checked) });\n"),
    ("Felder zeigen die Eingabe statt des Serverwerts", JS,
     "                  Mgr.renderSandboxCfg({ auch_admins: x.d.auch_admins, grenzen: x.d.grenzen });\n", ""),
    ("Erfolgs-Zeitgeber loescht spaeteren Fehler", JS,
     "                      setTimeout(function () { if (st.textContent === gut) st.textContent = ''; }, 2500);\n",
     "                      setTimeout(function () { st.textContent = ''; }, 2500);\n"),
    ("unbekannte Loopback-Sperre als 'nein'", JS,
     "                + row(h.lo_sperre === true ? true : (h.lo_sperre === false ? false : null),\n",
     "                + row(h.lo_sperre === true,\n"),
    ("{marke} nicht eingesetzt", JS,
     "        return v.split('{marke}').join(marke);\n", "        return v;\n"),
]

DATEIEN = [SG, LT, OP, SH, AG, JS, HT,
           "tests/test_bsi_h10.py", "tests/test_bsi_h10_dispatch.py", "tests/test_bsi_h10_ui.js"]

WAECHTER = [
    (["python3", "tests/test_bsi_h10.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
    ([PY, "tests/test_bsi_h10_dispatch.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
    (["node", "tests/test_bsi_h10_ui.js"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
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
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {r.stdout.strip()[-160:]}"
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

#!/usr/bin/env python3
"""Regressionstests fuer die Shell-Redirect-Policy von Domain-Benutzern.

Warum diese Datei existiert: Der Parser-Fix vom 2026-07-30 hatte 37 Pruefungen –
die lagen aber in einem Wegwerf-Skript und sind mit der Sitzung verschwunden. Am
2026-08-05 fiel deshalb unbemerkt ``2>/dev/null`` durch: ein reines
``grep … 2>/dev/null`` galt als "Schreibziel ausserhalb /tmp", und drei solche
Befehle in drei Sekunden sperrten auf ECHT ein Benutzerkonto
(``policy:shell-write``). Die Fallliste gehoert also ins Repo.

Laeuft ohne fastapi/google-genai: die drei Funktionen werden per Quelltext aus
backend/agent.py extrahiert (``import backend.agent`` zieht den ganzen
Abhaengigkeitsbaum). security_guard wird normal importiert, aber auf ein
Wegwerf-Verzeichnis umgebogen.

    python3 tests/test_shell_redirects.py
"""
import os
import re
import sys
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fail = 0
_ok = 0


def check(cond, label):
    global _fail, _ok
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


# ── Funktionen aus agent.py isoliert laden ──────────────────────────────────
_src = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
_ns = {"re": re}
for _name in ("_SHELL_DEV_SINKS", "_SHELL_WRITE_ATTACK_TARGET"):
    m = re.search(r'\n(' + _name + r'\s*=\s*(?:frozenset\(|re\.compile\().*?\n\))', _src, re.S)
    assert m, f"{_name} nicht in agent.py gefunden"
    exec(m.group(1), _ns)
for _name in ("_strip_heredocs", "_shell_redirect_writes", "_shell_write_targets",
              "_ldap_redirects_safe", "_shell_write_is_attack"):
    m = re.search(r'\ndef ' + _name + r'\(.*?(?=\ndef |\n[A-Z_]{3,}\s*=|\n# ──|\Z)', _src, re.S)
    assert m, f"{_name} nicht in agent.py gefunden"
    exec(m.group(0), _ns)

safe = lambda c: _ns["_ldap_redirects_safe"](_ns["_strip_heredocs"](c))          # noqa: E731
attack = lambda c: _ns["_shell_write_is_attack"](_ns["_strip_heredocs"](c))      # noqa: E731

# ── 1. Muss ERLAUBT sein ────────────────────────────────────────────────────
print("\n1. erlaubte Befehle")
ERLAUBT = [
    # der gemeldete Vorfall vom 2026-08-05 (ECHT), woertlich
    'grep -i "PLZ\\|PLZ_" /tmp/KIS_Export/Export/KB/DB_Objekte/KIS_TABLE_P_PVPAT_PATIENT.yaml '
    '2>/dev/null || echo "Suche in anderen Patient-Dateien..."',
    'grep -i "ADRESSE\\|ADR_" /tmp/x.yaml 2>/dev/null || echo "Nicht gefunden in Patient-Tabelle"',
    'grep -i "P_PVPAT_PATIENT\\|PATNR\\|PAT_ID" /tmp/a.yaml 2>/dev/null || '
    'grep -i "PATNR\\|PAT_ID" /tmp/b.yaml',
    # Geraete-Senken in allen Schreibweisen
    'ls -l 2>/dev/null',
    'find /tmp -name "*.yaml" 2>/dev/null | head',
    'cat /tmp/a.txt > /dev/null',
    'python3 /tmp/s.py &>/dev/null',
    'python3 /tmp/s.py >/dev/null 2>&1',
    'echo hallo > /dev/stdout',
    'echo fehler > /dev/stderr',
    'python3 /tmp/s.py >> /dev/null',
    # gemischt: erlaubtes Datei-Ziel + Senke
    'python3 /tmp/s.py > /tmp/out.txt 2>/dev/null',
    'python3 /tmp/s.py 2>/tmp/err.txt',
    # kein Datei-Ziel (Regression 2026-07-30)
    'ls -l 2>&1',
    'curl -sv http://localhost/x -o /tmp/test.csv 2>&1 | tail',
    'cat /tmp/a.txt 2>&1 | head',
    # '>' innerhalb von Anfuehrungszeichen ist kein Redirect
    'grep "a > b" /tmp/x.txt',
    "awk '$1 > 5' /tmp/x.txt",
    # erlaubtes Schreiben in den Arbeitsbereich
    'echo "print(1)" > /tmp/skript.py',
    'cat /tmp/a > "/tmp/mit leerzeichen.txt"',
    # Heredoc-Koerper darf nicht als Redirect gelesen werden
    'cat << \'EOF\' > /tmp/s.py\nif a > b:\n    pass\nEOF',
]
for cmd in ERLAUBT:
    check(safe(cmd), f"erlaubt: {cmd[:72]!r}")

# ── 2. Muss GESPERRT bleiben ────────────────────────────────────────────────
print("\n2. gesperrte Befehle")
GESPERRT = [
    'echo x > /etc/passwd',
    'echo x >> /root/.ssh/authorized_keys',
    'echo x > /opt/jarvis/data/settings.json',
    'cat /tmp/a > ../etc/x',
    'echo x > /tmp/../etc/x',
    'echo x &>/etc/shadow',                      # &> wurde vom alten Regex uebersehen
    'echo x 2>/var/log/jarvis.log',
    'echo x > relativ.txt',
    'echo x > ~/notiz.txt',
    'echo x >',                                  # Ziel unbekannt -> fail-closed
    'echo x > "offen',                           # kaputtes Anfuehrungszeichen
    'echo x > /dev/sda',                         # KEINE Senke: Plattenschreibzugriff
    'echo x > /dev/mem',
    'echo x > /tmp/ok.txt > /etc/passwd',        # ein schlechtes Ziel genuegt
]
for cmd in GESPERRT:
    check(not safe(cmd), f"gesperrt: {cmd[:72]!r}")

# ── 3. Parser-Details ───────────────────────────────────────────────────────
print("\n3. Parser (Ziele nach Senken-Filter)")
CASES = [
    ('grep x /tmp/a 2>/dev/null', [], 0),
    ('ls 2>&1', [], 0),
    ('python3 s.py > /tmp/o.txt 2>/dev/null', ["/tmp/o.txt"], 0),
    ('echo x &>/etc/shadow', ["/etc/shadow"], 0),
    ('echo x >', [], 1),
    ('grep "a > b" /tmp/x', [], 0),
]
for cmd, exp_t, exp_u in CASES:
    t, u = _ns["_shell_write_targets"](cmd)
    check(t == exp_t and u == exp_u, f"{cmd!r} -> {t}, unparsed={u} (erwartet {exp_t}, {exp_u})")

# Der Roh-Parser MUSS /dev/null weiter melden – gefiltert wird in der Policy,
# damit die Zerlegung wahrheitsgetreu bleibt.
_raw, _ = _ns["_shell_redirect_writes"]('grep x /tmp/a 2>/dev/null')
check(_raw == ["/dev/null"], "Roh-Parser meldet /dev/null unveraendert")

# ── 4. Angriffsindiz vs. Sandbox-Grenze ─────────────────────────────────────
print("\n4. Eskalation nur bei System-/Secret-Zielen")
for cmd in ['echo x > /etc/passwd', 'echo x >> /root/.ssh/authorized_keys',
            'echo x > /opt/jarvis/data/settings.json', 'echo x 2>/var/log/x.log',
            'echo x > /dev/sda', 'echo x > /home/bender/.ssh/id_rsa']:
    check(attack(cmd), f"Angriff: {cmd[:60]!r}")
for cmd in ['echo x > relativ.txt', 'echo x > ~/notiz.txt', 'echo x > /mnt/share/x.txt',
            'echo x >', 'echo x > "offen', 'grep x /tmp/a 2>/dev/null']:
    check(not attack(cmd), f"keine Eskalation: {cmd[:60]!r}")

# ── 5. security_guard: weiche Ablehnung sperrt nicht ────────────────────────
print("\n5. security_guard (weiche Ablehnung)")
_tmp = tempfile.mkdtemp(prefix="jarvis_sgtest_")

# backend.config wird durch einen Stub ersetzt, NICHT echt importiert. Zwei Gruende:
# (a) der echte Import braucht python-dotenv und den halben Abhaengigkeitsbaum – der
# Test soll ueberall laufen; (b) `config._load_v2()` schreibt bei Migrationen die
# ECHTE data/settings.json zurueck. Ein Test darf die Live-Konfiguration nicht anfassen.
import types as _types                                                # noqa: E402
_cfgmod = _types.ModuleType("backend.config")


class _StubConfig:
    """Nur was security_guard braucht: get_setting mit Standardwerten (Schwelle 3/600 s)."""

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        raise AssertionError("Test darf keine Einstellung schreiben")


_cfgmod.config = _StubConfig()
sys.modules.setdefault("backend.config", _cfgmod)
try:
    from backend import security_guard as sg
except Exception as e:                                    # noqa: BLE001
    print(f"  FAIL security_guard nicht importierbar ({e})")
    _fail += 1
    sg = None

if sg is not None:
    # Sandkasten-Schranke: NIEMALS in den echten data/security_state.json schreiben
    # (dieselbe Falle wie in tests/test_log_retention.py).
    _statefile = Path(_tmp) / "security_state.json"
    for _attr in ("_STATE_FILE", "STATE_FILE", "_FILE"):
        if hasattr(sg, _attr) and isinstance(getattr(sg, _attr), (str, Path)):
            setattr(sg, _attr, _statefile if isinstance(getattr(sg, _attr), Path) else str(_statefile))
    _still_real = [a for a in dir(sg)
                   if isinstance(getattr(sg, a, None), (str, Path))
                   and "security_state" in str(getattr(sg, a)) and _tmp not in str(getattr(sg, a))]
    if _still_real:
        print(f"  ABBRUCH: Pfad zeigt noch auf die echte Datei: {_still_real}")
        sys.exit(2)
    sg._cache = None if hasattr(sg, "_cache") else None

    U = "testnutzer.weich"
    r1 = r2 = r3 = None
    for i in range(3):
        r3 = sg.record_violation(U, "chat", "shell-write", f"grep {i} 2>/dev/null",
                                 escalate=False)
    check(not r3.get("blocked"), "3x weiche Ablehnung sperrt NICHT")
    st = json.loads(_statefile.read_text()) if _statefile.exists() else {}
    check(U not in st.get("blocked", {}), "Benutzer steht nicht in 'blocked'")
    check(len(st.get("violations", {}).get(U, [])) == 3, "alle 3 bleiben protokolliert (sichtbar)")
    check(all(e.get("soft") for e in st.get("violations", {}).get(U, [])), "Eintraege sind als 'soft' markiert")

    # Weiche Eintraege duerfen auch nicht als Futter fuer eine spaetere Sperre dienen:
    # zwei harte Verstoesse nach drei weichen ergeben 2, nicht 5.
    for i in range(2):
        rh = sg.record_violation(U, "chat", "shell-forbidden", f"rm -rf {i}")
    check(not rh.get("blocked"), "2 harte Verstoesse nach 3 weichen sperren noch nicht")
    rh = sg.record_violation(U, "chat", "shell-forbidden", "rm -rf 3")
    check(rh.get("blocked"), "der 3. harte Verstoss sperrt")
    st = json.loads(_statefile.read_text())
    check(st["blocked"][U]["reason"] == "policy:shell-forbidden", "Sperrgrund nennt den harten Verstoss")

    U2 = "testnutzer.hart"
    for i in range(2):
        rh = sg.record_violation(U2, "chat", "shell-write", "echo x > /etc/passwd")
    check(not rh.get("blocked"), "harter shell-write: 2 sperren nicht")
    rh = sg.record_violation(U2, "chat", "shell-write", "echo x > /etc/passwd")
    check(rh.get("blocked"), "harter shell-write: der 3. sperrt weiterhin")

# ── 6. Quelltext-Wache ──────────────────────────────────────────────────────
print("\n6. Verdrahtung in agent.py")
check("escalate=not _viol_soft" in _src, "record_violation bekommt escalate= mitgegeben")
check("_viol_soft = not _shell_write_is_attack" in _src, "shell-write setzt das soft-Flag")
check(re.search(r'_viol_soft\s*=\s*False', _src) is not None, "Vorgabe ist False (fail-closed: eskaliert)")
check("_shell_write_targets(_cmd_sh)" in _src, "Fehlermeldung nennt das beanstandete Ziel")
_sg_src = (ROOT / "backend" / "security_guard.py").read_text(encoding="utf-8")
check('not e.get("soft")' in _sg_src, "Zaehlung filtert weiche Eintraege")

print(f"\n{'='*60}\n{_ok} OK, {_fail} FAIL\n{'='*60}")
sys.exit(1 if _fail else 0)

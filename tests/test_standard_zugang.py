#!/usr/bin/env python3
"""Waechter: kein oeffentlich bekannter Zugang oeffnet eine Installation (2026-09-28).

DIE ZUSAGE: wer eine Jarvis-Installation erreicht, kommt nicht mit einem Wert
hinein, der in Repo oder Doku steht – weder ueber die Weboberflaeche noch ueber
das Linux-Konto noch ueber einen Nebenweg zum Desktop.

Anlass (gemeldet 2026-09-28, nach dem SECRET_KEY-Befund):
- ``docs/install.sh`` legte ``jarvis:jarvis`` an – ein ECHTES Linux-Konto, auf
  DEV in der Gruppe sudo, sshd mit PasswordAuthentication.
- Der Web-Wechselzwang hing nur am Merker ``must_change_password``; stand das
  Kennwort wieder auf "jarvis", galt ein alter Merker weiter.
- Docker gab ``JARVIS_PASSWORD=jarvis`` vor – wer den Container zuerst
  erreichte, vergab das Kennwort selbst.
- Docker veroeffentlichte 6080: websockify ohne Anmeldung vor x11vnc ``-nopw``
  (``-listen 0.0.0.0``) = Desktop ohne Kennwort. Die Haertung vom 2026-08-18
  (``test_desktop_zugang``) hatte nur die beiden Startskripte erfasst.

Gemessen – moeglichst AUSGEFUEHRT, sonst am Syntaxbaum, Regeln ueber ALLE Dateien:
1. ``standard_zugang`` im Sandkasten.
2. Login erzwingt den Wechsel bei Standardkennwort (AST, Reihenfolge).
3. install.sh-Funktionen mit bash + Attrappe fuer ``getent`` ausgefuehrt.
4. Jeder x11vnc-Start (Shell + Python) nur loopback, jeder websockify-Start
   nur 127.0.0.1, kein Compose/Dockerfile veroeffentlicht 5900/6080.
5. Keine Doku, kein Skript nennt ein festes Kennwort fuer ``jarvis``.
"""
import ast
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

_ok = 0
_fail = 0


def check(beschreibung, bedingung, zusatz=""):
    """check(TEXT, BEDINGUNG) – vertauscht waere jede Zeichenkette wahr. Exit 2."""
    global _ok, _fail
    if not isinstance(beschreibung, str) or isinstance(bedingung, str):
        print("ABBRUCH: check(beschreibung, bedingung) vertauscht")
        sys.exit(2)
    if bedingung:
        _ok += 1
        print(f"  \033[32m✓\033[0m {beschreibung}")
    else:
        _fail += 1
        print(f"  \033[31m✗\033[0m {beschreibung}" + (f"  [{zusatz}]" if zusatz else ""))


def sicher(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return ("__FEHLER__", f"{type(e).__name__}: {e}")


AUSGENOMMEN = ("tests/", "docs/historie/", "node_modules/", ".git/", "venv/", ".venv/")


def dateien(*muster):
    """Versionierte Dateien (git ls-files) plus neue, nach Endung gefiltert."""
    r = subprocess.run(["git", "-C", str(WURZEL), "ls-files", "-co", "--exclude-standard"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: git ls-files nicht moeglich")
        sys.exit(2)
    aus = []
    for rel in r.stdout.splitlines():
        if rel.startswith(AUSGENOMMEN) or "/node_modules/" in rel:
            continue
        name = rel.rsplit("/", 1)[-1]
        if any(re.fullmatch(m, name) for m in muster) and (WURZEL / rel).is_file():
            aus.append(rel)
    return aus


def ohne_sh_kommentare(s):
    return "\n".join(z for z in s.splitlines() if not z.lstrip().startswith("#"))


def fortsetzungen_zusammen(s):
    """Backslash-Fortsetzungen zu EINER Zeile – ein Aufruf ueber mehrere Zeilen
    ist sonst nur zur Haelfte sichtbar (docker/entrypoint.sh)."""
    return re.sub(r"\\\n\s*", " ", s)


try:
    from backend import standard_zugang as sz
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.standard_zugang nicht importierbar: {e}")
    sys.exit(2)

sandkasten = Path(tempfile.mkdtemp(prefix="stdzugang_"))

# ─── 1. standard_zugang ─────────────────────────────────────────────────────
print("1. standard_zugang im Sandkasten")
for k in ("jarvis", "JARVIS", " jarvis ", "", "password", "Passwort"):
    check(f"{k!r} gilt als Standardkennwort", sz.ist_standardkennwort(k, "jarvis") is True)
check("Kennwort == Benutzername gilt als Standard",
      sz.ist_standardkennwort("andreas", "Andreas") is True)
check("ein individuelles Kennwort gilt NICHT als Standard",
      sz.ist_standardkennwort("Tr0cken-Blume-17", "jarvis") is False)

d = sandkasten / "a" / "data" / ".erstkennwort"
k1 = sicher(sz.docker_erstkennwort, "jarvis", d)
if not isinstance(k1, str):
    print(f"ABBRUCH: docker_erstkennwort lief nicht: {k1}")
    sys.exit(2)
check("Docker: JARVIS_PASSWORD=jarvis wird NICHT angenommen", k1 != "jarvis" and len(k1) >= 12, k1)
check("Docker: Erstkennwort liegt in der Datei, 0600",
      d.exists() and d.read_text().strip() == k1 and stat.S_IMODE(d.stat().st_mode) == 0o600)
check("Docker: zweiter Start liefert DASSELBE Erstkennwort", sicher(sz.docker_erstkennwort, "", d) == k1)
k2 = sicher(sz.docker_erstkennwort, "", sandkasten / "b" / ".erstkennwort")
check("Docker: zwei Container bekommen verschiedene Erstkennwoerter", isinstance(k2, str) and k2 != k1)
check("Docker: ein eigenes JARVIS_PASSWORD gilt",
      sicher(sz.docker_erstkennwort, "Tr0cken-Blume-17", sandkasten / "c" / ".e") == "Tr0cken-Blume-17")
dj = sandkasten / "d" / ".erstkennwort"
dj.parent.mkdir(parents=True)
dj.write_text("jarvis")
check("Docker: 'jarvis' in der Datei wird ersetzt", sicher(sz.docker_erstkennwort, "", dj) != "jarvis")

# ─── 2. Login / Kennwortregeln (AST) ────────────────────────────────────────
print("2. backend/main.py: Wechsel wird am KENNWORT erzwungen")
MAIN = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(MAIN)


def ist_aufruf(knoten, name):
    return (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute)
            and knoten.func.attr == name and isinstance(knoten.func.value, ast.Name)
            and knoten.func.value.id == "_standard_zugang")


def dekoriert_mit(fn, pfad):
    for dek in fn.decorator_list:
        if (isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute)
                and dek.func.attr == "post" and dek.args
                and isinstance(dek.args[0], ast.Constant) and dek.args[0].value == pfad):
            return True
    return False


login = [f for f in ast.walk(baum) if isinstance(f, ast.AsyncFunctionDef) and dekoriert_mit(f, "/api/login")]
check("Positivkontrolle: genau EIN /api/login-Handler", len(login) == 1, str(len(login)))
if len(login) == 1:
    fn = login[0]
    # Seit BSI M2 (2026-10-05) protokolliert der Handler nur noch und delegiert
    # den Ablauf: gemessen wird die Funktion, an die er per await uebergibt –
    # erkannt an der EIGENSCHAFT (sie stellt das Token aus), nicht am Namen.
    def _stellt_token_aus(f):
        return any(isinstance(t, ast.Call) and isinstance(t.func, ast.Name)
                   and t.func.id == "generate_token" for t in ast.walk(f))

    _eigene = {f.name: f for f in baum.body if isinstance(f, ast.AsyncFunctionDef)}
    _ziele = [_eigene[k.value.func.id] for k in ast.walk(fn)
              if isinstance(k, ast.Await) and isinstance(k.value, ast.Call)
              and isinstance(k.value.func, ast.Name) and k.value.func.id in _eigene
              and _stellt_token_aus(_eigene[k.value.func.id])]
    if not _stellt_token_aus(fn) and len(_ziele) == 1:
        fn = _ziele[0]
    check("Positivkontrolle: der gemessene Ablauf stellt das Token aus", _stellt_token_aus(fn))
    erzwingt = []
    for knoten in ast.walk(fn):
        if isinstance(knoten, ast.If) and any(ist_aufruf(t, "ist_standardkennwort") for t in ast.walk(knoten.test)):
            # im Rumpf: _set_user_auth_state(..., {"must_change_password": True})
            for c in ast.walk(ast.Module(body=knoten.body, type_ignores=[])):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                        and c.func.id == "_set_user_auth_state" and len(c.args) >= 2
                        and isinstance(c.args[1], ast.Dict)):
                    paare = {getattr(k, "value", None): getattr(v, "value", None)
                             for k, v in zip(c.args[1].keys, c.args[1].values)}
                    if paare.get("must_change_password") is True:
                        erzwingt.append(knoten.lineno)
    check("Login: Standardkennwort setzt must_change_password=True", bool(erzwingt))
    mc = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign)
          and any(isinstance(t, ast.Name) and t.id == "must_change" for t in n.targets)]
    check("... und zwar BEVOR must_change ermittelt wird",
          bool(erzwingt) and bool(mc) and min(erzwingt) < min(mc), f"{erzwingt} / {mc}")
    tok = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
           and isinstance(n.func, ast.Name) and n.func.id == "generate_token"]
    check("... und BEVOR ein Token ausgestellt wird", bool(erzwingt) and bool(tok) and min(erzwingt) < min(tok))

stark = [f for f in ast.walk(baum) if isinstance(f, ast.FunctionDef) and f.name == "_validate_password_strength"]
check("Kennwortregel lehnt jedes Standardkennwort ab (gleiche Quelle)",
      len(stark) == 1 and any(ist_aufruf(n, "ist_standardkennwort") for n in ast.walk(stark[0])))
jp = [n for n in baum.body if isinstance(n, ast.Assign)
      and any(isinstance(t, ast.Name) and t.id == "_JARVIS_PASSWORD" for t in n.targets)]
check("Docker-Kennwort kommt aus docker_erstkennwort (kein fester Vorgabewert)",
      len(jp) == 1 and any(ist_aufruf(n, "docker_erstkennwort") for n in ast.walk(jp[0])))
check("kein os.getenv('JARVIS_PASSWORD', <nicht leer>) in backend/",
      not re.search(r"getenv\(\s*[\"']JARVIS_PASSWORD[\"']\s*,\s*[\"'][^\"']+[\"']",
                    "\n".join((WURZEL / r).read_text(encoding="utf-8") for r in dateien(r".*\.py")
                              if r.startswith("backend/"))))

# ─── 3. install.sh, ausgefuehrt ─────────────────────────────────────────────
print("3. docs/install.sh: Zufallskennwort, Bestand mit Standard wird erkannt")
SH = (WURZEL / "docs" / "install.sh").read_text(encoding="utf-8")
m = re.search(r"\n(_zufallskennwort\(\) \{.*?\n\}\n_hat_standardkennwort\(\) \{.*?\n\}\n)", SH, re.S)
check("Positivkontrolle: Funktionen im Skript gefunden", m is not None)
openssl = shutil.which("openssl")
if not openssl or not shutil.which("perl"):
    print("ABBRUCH: openssl/perl fehlen – Abschnitt 3 nicht messbar")
    sys.exit(2)
if m:
    funktionen = m.group(1)
    bindir = sandkasten / "bin"
    bindir.mkdir()

    def lauf(schatten_hash):
        (bindir / "getent").write_text(f"#!/bin/sh\necho 'jarvis:{schatten_hash}:19000:0:99999:7:::'\n")
        os.chmod(bindir / "getent", 0o755)
        skript = f'SUDO=""\n{funktionen}\n_hat_standardkennwort jarvis; echo "RC=$?"'
        r = subprocess.run(["bash", "-c", skript], capture_output=True, text=True, timeout=20,
                           env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"})
        mm = re.search(r"RC=(\d+)", r.stdout)
        return int(mm.group(1)) if mm else -1

    def h(kw):
        return subprocess.run([openssl, "passwd", "-6", kw], capture_output=True, text=True).stdout.strip()

    check("Positivkontrolle: openssl liefert SHA-512-Hash", h("x").startswith("$6$"))
    check("Konto mit Kennwort 'jarvis' -> erkannt (0)", lauf(h("jarvis")) == 0)
    check("Konto mit individuellem Kennwort -> nicht angefasst (1)", lauf(h("Tr0cken-Blume-17")) == 1)
    check("Konto OHNE Kennwort -> erkannt (0)", lauf("") == 0)
    check("gesperrtes Konto -> nicht angefasst (1)", lauf("!" + h("jarvis")) == 1)

    r = subprocess.run(["bash", "-c", f'{funktionen}\n_zufallskennwort; echo; _zufallskennwort'],
                       capture_output=True, text=True, timeout=20)
    zz = r.stdout.split()
    check("Zufallskennwort: zwei Aufrufe, je 16 Zeichen [A-Za-z0-9]",
          len(zz) == 2 and all(re.fullmatch(r"[A-Za-z0-9]{16}", z) for z in zz), str(zz))
    check("Zufallskennwort: die beiden unterscheiden sich", len(zz) == 2 and zz[0] != zz[1])
check("neuer Benutzer bekommt _erstkennwort_setzen, nicht ein festes Kennwort",
      bool(re.search(r"useradd[^\n]*jarvis[^\n]*\n\s*_erstkennwort_setzen\b", SH)))
check("Abschlussmeldung nennt das erzeugte Erstkennwort",
      "${JARVIS_ERSTKENNWORT" in ohne_sh_kommentare(SH.split("erfolgreich installiert", 1)[-1]))

# ─── 4. Desktop-Nebenwege ───────────────────────────────────────────────────
print("4. Kein Weg zum Desktop an der Anmeldung vorbei (alle Startstellen)")
SHELL = dateien(r".*\.sh", r"Dockerfile")
x_starts, w_starts = [], []
for rel in SHELL:
    code = fortsetzungen_zusammen(ohne_sh_kommentare((WURZEL / rel).read_text(encoding="utf-8")))
    for z in code.splitlines():
        s = z.strip()
        if re.match(r"^(\S*/)?x11vnc\s", s) or re.search(r"(^|[;&|]\s*)x11vnc\s+-", s):
            x_starts.append((rel, s))
        if re.search(r"(^|\s)(\S*/)?(python3? -m )?websockify\s", s) and "--web" in s:
            w_starts.append((rel, s))
# Seit BSI H11-Rest starten die Server-Skripte x11vnc nicht mehr selbst
# (backend/desktop_control.x11vnc_starten); uebrig sind run.sh (Nicht-root) und Docker.
check("Positivkontrolle: x11vnc-Starts gefunden (run.sh und Docker)",
      {"docker/entrypoint.sh", "run.sh"} <= {r for r, _ in x_starts}, str(len(x_starts)))
schlecht = [(r, s[:90]) for r, s in x_starts if "-localhost" not in s or re.search(r"-listen\s+0\.0\.0\.0", s)]
check("jeder x11vnc-Start (Shell) bindet nur loopback", not schlecht, str(schlecht))
check("Positivkontrolle: websockify-Starts gefunden (inkl. Docker, run.sh)",
      {"docker/entrypoint.sh", "run.sh"} <= {r for r, _ in w_starts}, str({r for r, _ in w_starts}))
schlecht = []
for r, s in w_starts:
    # das erste Argument nach den --optionen, das eine Portangabe ist
    ports = [t for t in s.split() if re.fullmatch(r"\"?(\S+:)?(\$\{?\w+\}?|\d+)\"?", t) and "localhost" not in t]
    if not ports or not ports[0].strip('"').startswith("127.0.0.1:"):
        schlecht.append((r, s[:100]))
check("jeder websockify-Start bindet nur 127.0.0.1", not schlecht, str(schlecht))

py_starts, py_schlecht = 0, []
for rel in dateien(r".*\.py"):
    try:
        b = ast.parse((WURZEL / rel).read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for n in ast.walk(b):
        # Ein Start ist eine Argumentliste mit x11vnc (Konstante oder _bin("x11vnc"))
        # UND -rfbport – seit BSI H11-Rest steht davor setpriv, nicht x11vnc selbst.
        if not isinstance(n, ast.List):
            continue
        werte = [e.value for e in n.elts if isinstance(e, ast.Constant)]
        hat_x11vnc = "x11vnc" in werte or any(
            isinstance(e, ast.Call) and any(isinstance(a, ast.Constant) and a.value == "x11vnc" for a in e.args)
            for e in n.elts)
        if hat_x11vnc and "-rfbport" in werte:
            py_starts += 1
            if "-localhost" not in werte or "0.0.0.0" in werte:
                py_schlecht.append(f"{rel}:{n.lineno}")
check("Positivkontrolle: x11vnc-Start in Python gefunden (seit H11-Rest genau eine Startstelle)", py_starts >= 1, str(py_starts))
check("jeder x11vnc-Start (Python) bindet nur loopback", not py_schlecht, str(py_schlecht))

for rel in dateien(r"docker-compose.*\.ya?ml"):
    txt = (WURZEL / rel).read_text(encoding="utf-8")
    offen = re.findall(r"^\s*-\s*[\"']?(?:[\d.]+:)?\d+:(5900|6080)[\"']?", ohne_sh_kommentare(txt), re.M)
    check(f"{rel}: veroeffentlicht weder 5900 noch 6080", not offen, str(offen))
DF = ohne_sh_kommentare((WURZEL / "Dockerfile").read_text(encoding="utf-8"))
exp = " ".join(re.findall(r"^EXPOSE\s+(.*)$", DF, re.M))
check("Positivkontrolle: Dockerfile hat EXPOSE", "443" in exp, exp)
check("Dockerfile: EXPOSE ohne 5900/6080", not re.search(r"\b(5900|6080)\b", exp), exp)

# ─── 5. kein festes Kennwort in Doku und Skripten ───────────────────────────
print("5. Kein festes Kennwort fuer 'jarvis' in Doku, Skripten, Vorlagen")
TEXTE = dateien(r".*\.(md|html|sh|ya?ml)", r"Dockerfile", r"\.env\.example")
check("Positivkontrolle: Doku und Skripte gefunden",
      {"README.md", "docs/index.html", "docs/install.sh", ".env.example"} <= set(TEXTE))
funde = []
for rel in TEXTE:
    txt = (WURZEL / rel).read_text(encoding="utf-8", errors="replace")
    for mm in re.finditer(r"jarvis\s*(?:</strong>\s*)?/\s*(?:<strong[^>]*>\s*)?jarvis\b"
                          r"|echo\s+[\"']?jarvis:[^\s\"'$]+[\"']?\s*\|\s*(?:\$SUDO\s+)?chpasswd"
                          r"|JARVIS_PASSWORD[=:]\s*[\"']?(?:\$\{JARVIS_PASSWORD:-)?jarvis\b", txt):
        funde.append(f"{rel}: {mm.group(0)[:50]}")
check("nirgends 'jarvis / jarvis', 'jarvis:<fest> | chpasswd' oder JARVIS_PASSWORD=jarvis",
      not funde, "; ".join(funde[:6]))

# ─── 6. Sandbox liest weder Schluessel noch 2FA-Geheimnisse ────────────────
print("6. Sandbox (jarvis_sandbox) kommt nicht an Schluessel und 2FA-Geheimnisse")
try:
    from backend import sandbox as sbx
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.sandbox nicht importierbar: {e}")
    sys.exit(2)
GEHEIM = ("data/.secret_key", "data/auth_state.json", "data/.erstkennwort")
wurzel = sandkasten / "proj"
for rel in GEHEIM + ("data/.mailkey",):
    f = wurzel / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x")
    os.chmod(f, 0o644)
_alt_root = sbx.PROJECT_ROOT
sbx.PROJECT_ROOT = wurzel
try:
    sicher(sbx.harden_data_dirs)
finally:
    sbx.PROJECT_ROOT = _alt_root
check("Positivkontrolle: harden_data_dirs wirkt im Sandkasten (.mailkey -> 0600)",
      stat.S_IMODE((wurzel / "data/.mailkey").stat().st_mode) == 0o600)
for rel in GEHEIM:
    modus = stat.S_IMODE((wurzel / rel).stat().st_mode)
    check(f"{rel}: beim Start auf 0600 gesetzt", modus == 0o600, oct(modus))
    check(f"{rel}: Shell-Befehl darauf wird gesperrt",
          bool(sbx.SHELL_SECRET_PATHS.search(f"cat /opt/jarvis/{rel}")))
    check(f"{rel}: Dateiwerkzeug gilt als sensibel",
          sicher(sbx.is_sensitive, Path("/opt/jarvis") / rel) is True)

# ─── 7. SSH: jarvis nur per Schluessel (install.sh, ausgefuehrt) ────────────
print("7. install.sh: SSH fuer 'jarvis' nur per Schluessel – gemessen mit sshd -T")
SSHD = shutil.which("sshd") or ("/usr/sbin/sshd" if os.access("/usr/sbin/sshd", os.X_OK) else None)
KEYGEN = shutil.which("ssh-keygen")
SH = (WURZEL / "docs" / "install.sh").read_text(encoding="utf-8")
mf = re.search(r"\n(_ssh_nur_schluessel\(\) \{.*?\n\}\n)", SH, re.S)
check("Positivkontrolle: _ssh_nur_schluessel im Skript gefunden", mf is not None)
if not (SSHD and KEYGEN):
    print("ABBRUCH: sshd/ssh-keygen fehlen – Abschnitt 7 nicht messbar")
    sys.exit(2)
if mf:
    ssh_d = sandkasten / "ssh"
    (ssh_d / "d").mkdir(parents=True)
    subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-N", "", "-f", str(ssh_d / "hk")], check=True)
    fake = ssh_d / "bin"
    fake.mkdir()
    (fake / "systemctl").write_text("#!/bin/sh\nexit 0\n")
    os.chmod(fake / "systemctl", 0o755)

    def haupt(mit_include):
        (ssh_d / "cfg").write_text(
            f"HostKey {ssh_d / 'hk'}\n" + (f"Include {ssh_d / 'd'}/*.conf\n" if mit_include else "")
            + "PasswordAuthentication yes\nKbdInteractiveAuthentication no\nUsePAM yes\n")

    def effektiv(user):
        r = subprocess.run([SSHD, "-T", "-f", str(ssh_d / "cfg"), "-C", f"user={user},host=x,addr=1.2.3.4"],
                           capture_output=True, text=True)
        mm = re.search(r"^passwordauthentication (\w+)$", r.stdout, re.M)
        return mm.group(1) if mm else f"?({r.stderr.strip()[:80]})"

    def ausfuehren():
        skript = ('SUDO=""\nsuccess(){ echo "OK $*"; }\nwarn(){ echo "WARN $*"; }\n'
                  + mf.group(1) + "\n_ssh_nur_schluessel")
        return subprocess.run(["bash", "-c", skript], capture_output=True, text=True, timeout=30, env={
            **os.environ, "PATH": f"{fake}:{os.path.dirname(SSHD)}:{os.environ['PATH']}",
            "JARVIS_SSHD_CONFIG": str(ssh_d / "cfg"), "JARVIS_SSHD_DROPIN_DIR": str(ssh_d / "d")})

    haupt(True)
    vorher = effektiv("jarvis")
    check("Positivkontrolle: vorher darf jarvis per Kennwort (sshd -T misst)", vorher == "yes", vorher)
    r = ausfuehren()
    check("Block laeuft durch und meldet Erfolg", r.returncode == 0 and "OK SSH" in r.stdout,
          (r.stdout + r.stderr).strip()[:160])
    check("danach: jarvis NUR per Schluessel", effektiv("jarvis") == "no", effektiv("jarvis"))
    check("alle anderen Benutzer unveraendert (root)", effektiv("root") == "yes", effektiv("root"))
    check("alle anderen Benutzer unveraendert (andreas)", effektiv("andreas") == "yes")
    for f in (ssh_d / "d").glob("*.conf"):
        f.unlink()
    haupt(False)
    r = ausfuehren()
    check("ohne Include in sshd_config: nichts angelegt, Warnung",
          not list((ssh_d / "d").glob("*.conf")) and "WARN SSH" in r.stdout, r.stdout.strip()[:120])
aufruf = re.search(r'if \[\[ "\$\{JARVIS_NEU_ANGELEGT:-0\}" == 1 \]\] \|\| \$SUDO test -s ~jarvis/\.ssh/authorized_keys; then\n\s*_ssh_nur_schluessel\n\s*else\n\s*warn ', SH)
check("Aufruf nur fuer NEUES Konto oder Konto MIT Schluessel (sonst Warnung)", aufruf is not None)
check("neu angelegtes Konto setzt JARVIS_NEU_ANGELEGT=1",
      bool(re.search(r"_erstkennwort_setzen\n\s*JARVIS_NEU_ANGELEGT=1\n", SH)))

shutil.rmtree(sandkasten, ignore_errors=True)
print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)

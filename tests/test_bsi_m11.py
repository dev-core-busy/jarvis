#!/usr/bin/env python3
"""Waechter BSI M11 – die Apps pruefen das Serverzertifikat.

  [A] Windows-App (Go): kein ``InsecureSkipVerify: true`` ausser im Paket
      ``tlsvertrauen`` (dort mit VerifyConnection), jede Server-Verbindung
      ueber ``tlsvertrauen.ServerTLS``; die Go-Tests des Pakets laufen
      (Regel, IP-/Namenspruefung, Pin je Rechner, echter TLS-Server).
  [B] Android-App (Kotlin, REGEL am Quelltext – die Uebersetzbarkeit prueft
      ``./gradlew --offline :app:compileDebugKotlin``): kein Trust-All, kein
      ``hostnameVerifier { _, _ -> true }``, jeder selbst gebaute OkHttpClient
      geht durch ``ServerVertrauen.anwenden``; Netzwerkkonfiguration vertraut
      System + Benutzer-CA, keine Ausnahme-Domains; Dialog im SettingsScreen.
  [C] Server: der Fingerabdruck in /api/settings/ssl stimmt mit openssl
      ueberein (Funktion per AST ausgefuehrt, Zertifikat frisch erzeugt).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:400] + "]") if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


def ohne_kommentare(text):
    """// und /* */ entfernen (Begruendungen nennen die alten Muster woertlich)."""
    text = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


# ═════════════════════════════════════════════════════════════════════════════
print("\n[A] Windows-App")
WIN = ROOT / "windows-app-go"
gos = [p for p in WIN.rglob("*.go") if "vendor" not in p.parts]
if len(gos) < 20:
    abbruch("nur %d Go-Dateien" % len(gos))
paket = WIN / "tlsvertrauen" / "tlsvertrauen.go"
if not paket.is_file():
    abbruch("tlsvertrauen.go fehlt")
unsicher = [str(p.relative_to(ROOT)) for p in gos if p != paket and not p.name.endswith("_test.go")
            and re.search(r"InsecureSkipVerify\s*:\s*true", ohne_kommentare(p.read_text(encoding="utf-8")))]
check("kein InsecureSkipVerify:true ausserhalb von tlsvertrauen", not unsicher, unsicher)
pk = ohne_kommentare(paket.read_text(encoding="utf-8"))
check("tlsvertrauen: InsecureSkipVerify nur zusammen mit VerifyConnection",
      "VerifyConnection:" in pk and pk.count("InsecureSkipVerify") == 1)
konfig = []
for p in gos:
    if p == paket or p.name.endswith("_test.go"):
        continue
    for m in re.finditer(r"TLSClientConfig\s*:\s*([^,\n]+)", ohne_kommentare(p.read_text(encoding="utf-8"))):
        konfig.append((p.name, m.group(1).strip()))
check("TLS-Konfigurationen gefunden (Positivkontrolle, %d)" % len(konfig), len(konfig) >= 8, konfig)
fremd = [k for k in konfig if not k[1].startswith("tlsvertrauen.ServerTLS(")
         and not (k[0] == "update.go" and "InsecureSkipVerify: false" in k[1])]
check("jede Server-Verbindung ueber tlsvertrauen.ServerTLS (Update-Server: normale Pruefung)", not fremd, fremd)
if shutil.which("go") is None:
    abbruch("go fehlt – die Paket-Tests sind nicht pruefbar")
r = subprocess.run(["go", "test", "-count=1", "./tlsvertrauen"], cwd=str(WIN), capture_output=True,
                   text=True, timeout=600)
if "no Go files" in r.stdout + r.stderr or ("ok" not in r.stdout and "FAIL" not in r.stdout):
    abbruch("go test lief nicht: %s" % (r.stdout + r.stderr)[-300:])
check("go test ./tlsvertrauen gruen", r.returncode == 0, (r.stdout + r.stderr)[-400:])
cfg = (WIN / "config.go").read_text(encoding="utf-8")
check("bestaetigte Zertifikate werden beim Laden uebernommen", "tlsvertrauen.SetzePins(cfg.ServerCertPins)" in cfg)
st = (WIN / "settings.go").read_text(encoding="utf-8")
check("Anmelden + Verbindungstest fragen nach (zwei Aufrufer)", st.count("mitZertifikatsBestaetigung(win,") == 2)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[B] Android-App")
AND = ROOT / "android" / "app" / "src" / "main"
kts = list(AND.rglob("*.kt"))
if len(kts) < 15:
    abbruch("nur %d Kotlin-Dateien" % len(kts))
sv = AND / "java" / "info" / "jarvisai" / "app" / "data" / "tls" / "ServerVertrauen.kt"
if not sv.is_file():
    abbruch("ServerVertrauen.kt fehlt")
trust_all, verifier_true, tm_fremd, builder_ohne = [], [], [], []
for p in kts:
    t = ohne_kommentare(p.read_text(encoding="utf-8"))
    rel = str(p.relative_to(ROOT))
    if re.search(r"checkServerTrusted\([^)]*\)\s*(\{\s*\}|=\s*Unit)", t):
        trust_all.append(rel)
    if re.search(r"hostnameVerifier\s*\{\s*_\s*,\s*_\s*->\s*true\s*\}", t):
        verifier_true.append(rel)
    if p != sv and re.search(r"object\s*:\s*X509TrustManager", t):
        tm_fremd.append(rel)
    for m in re.finditer(r"OkHttpClient\.Builder\(\)", t):
        davor = t[max(0, m.start() - 40):m.start()]
        if "ServerVertrauen.anwenden(" not in davor:
            builder_ohne.append("%s:%d" % (rel, t[:m.start()].count("\n") + 1))
check("kein Trust-All (leeres checkServerTrusted)", not trust_all, trust_all)
check("kein hostnameVerifier { _, _ -> true }", not verifier_true, verifier_true)
check("eigener TrustManager nur in ServerVertrauen", not tm_fremd, tm_fremd)
check("jeder OkHttpClient.Builder geht durch ServerVertrauen.anwenden", not builder_ohne, builder_ohne)
svt = ohne_kommentare(sv.read_text(encoding="utf-8"))
check("ServerVertrauen: Systempruefung zuerst, sonst nur bestaetigter Fingerabdruck",
      "systemTm.checkServerTrusted(chain, authType)" in svt and "throw UnbekanntesZertifikat(fp, e)" in svt)
check("ServerVertrauen: Pin an den Rechner gebunden (HostnameVerifier)", "pinFuer(host) == fp" in svt)
check("ServerVertrauen: System-vertraute Zertifikate mit normaler Namenspruefung",
      "getDefaultHostnameVerifier().verify(host, session)" in svt)
nsc = (AND / "res" / "xml" / "network_security_config.xml").read_text(encoding="utf-8")
nsc_ohne = re.sub(r"<!--.*?-->", "", nsc, flags=re.S)
check("Netzwerkkonfiguration: System + Benutzer-CA, keine Ausnahme-Domains",
      '<certificates src="system"' in nsc_ohne and '<certificates src="user"' in nsc_ohne
      and "domain-config" not in nsc_ohne and 'cleartextTrafficPermitted="true"' not in nsc_ohne)
ui = (AND / "java" / "info" / "jarvisai" / "app" / "ui" / "settings" / "SettingsScreen.kt").read_text(encoding="utf-8")
vm = (AND / "java" / "info" / "jarvisai" / "app" / "ui" / "settings" / "SettingsViewModel.kt").read_text(encoding="utf-8")
check("Dialog zeigt den Fingerabdruck und bestaetigt", "f.fingerabdruck" in ui and "viewModel.zertBestaetigen()" in ui)
check("Anmelden und Speichern stellen die Frage", vm.count("zertFrageStellen(e,") >= 2)
app = (AND / "java" / "info" / "jarvisai" / "app" / "JarvisApp.kt").read_text(encoding="utf-8")
check("Pins vor dem ersten Netzzugriff geladen", "ServerVertrauen.init(this)" in app)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[C] Server: Fingerabdruck in /api/settings/ssl")
if shutil.which("openssl") is None:
    abbruch("openssl fehlt")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(MAIN)
fn = next((n for n in baum.body if isinstance(n, ast.FunctionDef) and n.name == "_zertifikat_fingerabdruck"), None)
if fn is None:
    abbruch("_zertifikat_fingerabdruck fehlt")
ns = {"Path": Path}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "fp", "exec"), ns)
d = Path(tempfile.mkdtemp(prefix="m11_"))
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "k.pem"),
                "-out", str(d / "c.pem"), "-days", "1", "-subj", "/CN=probe"], capture_output=True, check=True)
soll = subprocess.run(["openssl", "x509", "-in", str(d / "c.pem"), "-noout", "-fingerprint", "-sha256"],
                      capture_output=True, text=True).stdout.strip().split("=", 1)[-1]
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "k2.pem"),
                "-out", str(d / "c2.pem"), "-days", "1", "-subj", "/CN=zwischen"], capture_output=True, check=True)
(d / "kette.pem").write_text((d / "c.pem").read_text() + (d / "c2.pem").read_text())
check("Fingerabdruck = openssl (SHA-256)", ns["_zertifikat_fingerabdruck"](d / "c.pem") == soll,
      (ns["_zertifikat_fingerabdruck"](d / "c.pem"), soll))
check("bei Kette zaehlt das ERSTE Zertifikat", ns["_zertifikat_fingerabdruck"](d / "kette.pem") == soll)
check("fehlende Datei: leer statt Absturz", ns["_zertifikat_fingerabdruck"](d / "fehlt.pem") == "")
ssl_fn = next((n for n in baum.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_ssl_info"), None)
check("/api/settings/ssl liefert den Fingerabdruck",
      ssl_fn is not None and "_zertifikat_fingerabdruck(cert_file)" in ast.unparse(ssl_fn))
appjs = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
check("Oberflaeche zeigt ihn an (i18n)", "d.fingerabdruck" in appjs and "profile.cert_fingerprint" in appjs)
shutil.rmtree(d, ignore_errors=True)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)

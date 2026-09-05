#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Waechter fuer die Freigaben-Diagnose und die Deutung von Mount-Fehlern.

ANLASS (gemeldet 2026-09-05, ECHT): eine SMB-Freigabe meldete
    "Der Server '//191.100.147.90/knowledgebase_an_rag' ist nicht erreichbar
     (ausgeschaltet, falscher Name, kein Netzweg)"
waehrend derselbe Server auf Ping in 7,9 ms und auf Port 445 in 10 ms
antwortete - er wies lediglich den SMB-Aufbau ab (Connection reset). Die
Meldung war also nicht nur unzureichend, sondern FALSCH.

Zwei Dinge werden hier gemessen, beide AUSGEFUEHRT statt im Quelltext gesucht:
  1. Die Deutung erkennt den Kernel-Errno in BEIDEN Formen - dmesg
     ("failed w/return code = -115") UND mount.cifs ("mount error(115)").
  2. Das URTEIL der Diagnose folgt den Messwerten: dieselben Zahlen muessen
     immer denselben Satz ergeben, und "nicht erreichbar" darf NICHT mehr
     herauskommen, wenn ein Port offen ist.
"""
import ast
import re
import sys
from pathlib import Path
import time

OK = FAIL = 0


def check(name, bedingung):
    global OK, FAIL
    if not isinstance(bedingung, bool):
        sys.exit(f"ABBRUCH: check('{name}') bekam {type(bedingung).__name__} "
                 f"statt bool - Argumente vertauscht?")
    if bedingung:
        OK += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {name}")


def sicher(fn, *a, **k):
    """Nie ungeprueft dereferenzieren: eine Pruefung, die WIRFT, bricht den
    Lauf ab - und ein abgebrochener Lauf ist von 'nicht gelaufen' nicht zu
    unterscheiden (Register)."""
    try:
        return fn(*a, **k)
    except Exception as e:                                    # noqa: BLE001
        return f"__WURF__ {type(e).__name__}: {e}"


def ohne_kommentare(quelle):
    """Kommentare tilgen, Code Zeichen fuer Zeichen erhalten.

    ⚠ VIERZEHNTER FALL DIESER KLASSE im Projekt: die Pruefung "die Sonde
    bietet 0x0311 nicht an" schlug an - im KOMMENTAR, der genau erklaert,
    warum sie es nicht tut. Ein Waechter, der seine eigene Begruendung liest,
    prueft nichts.
    """
    import io, tokenize
    zeichen = list(quelle)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if tok.type != tokenize.COMMENT:
                continue
            zeilen = quelle.splitlines(keepends=True)
            start = sum(len(z) for z in zeilen[:tok.start[0] - 1]) + tok.start[1]
            for i in range(start, start + len(tok.string)):
                if i < len(zeichen):
                    zeichen[i] = " "
    except tokenize.TokenError:
        return quelle          # fail-open: lieber pruefen als gar nicht
    return "".join(zeichen)


def schneide(quelle, namen):
    """Funktionen/Konstanten per AST herausloesen - nie per Zeilenfenster."""
    baum = ast.parse(quelle)
    teile = []
    for n in baum.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in namen:
            teile.append(ast.get_source_segment(quelle, n))
        elif isinstance(n, ast.Assign):
            for z in n.targets:
                if getattr(z, "id", "") in namen:
                    teile.append(ast.get_source_segment(quelle, n))
    return "\n\n".join(teile)


# ══════════════════════════════════════════════════════════════════════════
print("\n\033[1m1. Deutung: mount error(NNN) ist derselbe Kernel-Code\033[0m")

HAUPT = open("backend/main.py", encoding="utf-8").read()
ns = {"re": re}
exec(schneide(HAUPT, {"_mount_fehler_deuten", "_MOUNT_KERNCODES"}), ns)
deute = ns["_mount_fehler_deuten"]

GEMELDET = ("mount error(115): could not connect to 191.100.147.90"
            "Unable to find suitable address.")
t = sicher(deute, {"stderr": GEMELDET, "rc": 32}, "smb",
           "//191.100.147.90/knowledgebase_an_rag")
check("gemeldeter Fall: behauptet NICHT mehr, der Server sei nicht erreichbar",
      isinstance(t, str) and "ist nicht erreichbar (ausgeschaltet" not in t)
check("gemeldeter Fall: schliesst 'nicht erreichbar' ausdruecklich aus",
      isinstance(t, str) and "ausgeschlossen" in t)
check("gemeldeter Fall: nennt 'OBWOHL der Rechner antwortet'",
      isinstance(t, str) and "OBWOHL der Rechner antwortet" in t)
check("gemeldeter Fall: verweist auf den Analyse-Knopf",
      isinstance(t, str) and "Analysieren" in t)
check("gemeldeter Fall: der Rohtext bleibt woertlich erhalten",
      isinstance(t, str) and "mount error(115)" in t)

# Gegenrichtungen - kein Rueckschritt gegenueber der alten Fassung
t13 = sicher(deute, {"stderr": "mount error(13): Permission denied", "rc": 32}, "smb", "//s/f")
check("error(13) sagt weiterhin 'Zugang verweigert'",
      isinstance(t13, str) and "Zugang verweigert" in t13)
t2 = sicher(deute, {"stderr": "mount error(2): No such file or directory", "rc": 32}, "smb", "//s/f")
check("error(2) nennt weiterhin den Freigabenamen",
      isinstance(t2, str) and "gibt es auf dem Server nicht" in t2)
t126 = sicher(deute, {"stderr": "mount error(126): Required key not available", "rc": 32}, "smb", "//s/f")
check("error(126) faellt auf den generischen Zweig (kein 'Fehlercode -126')",
      isinstance(t126, str) and "Fehlercode" not in t126)
tdm = sicher(deute, {"stderr": "fsconfig() failed [Kernel: cifs_mount failed w/return code = -13]",
                     "rc": 32}, "smb", "//s/f")
check("dmesg-Form wirkt unveraendert",
      isinstance(tdm, str) and "Zugang verweigert" in tdm)
taus = sicher(deute, {"stderr": "fsconfig() failed: Operation now in progress", "rc": 32}, "smb", "//s/f")
check("ohne Code bleibt es beim generischen 'nicht erreichbar'",
      isinstance(taus, str) and "nicht erreichbar" in taus)

# ══════════════════════════════════════════════════════════════════════════
print("\n\033[1m2. Diagnose-Op: das Urteil folgt den Messwerten\033[0m")

OPS = open("backend/broker/ops.py", encoding="utf-8").read()
code = schneide(OPS, {"_op_mount_diagnose", "_tcp_offen", "_smb2_negotiate",
                      "_egress_offen_fuer_kernel", "_SMB_DIALEKTE"})
check("alle vier Bausteine geschnitten",
      all(x in code for x in ("_op_mount_diagnose", "_tcp_offen",
                              "_smb2_negotiate", "_egress_offen_fuer_kernel")))


# ⚠ Die Egress-Messung liegt seit 2026-09-05 in egress_guard.kette_veraltet() -
# ops.py baut sie NICHT mehr selbst nach (eine zweite Fassung waere beim
# naechsten Feinschliff auseinandergelaufen). Der Test stellt deshalb nicht
# mehr nur ops._run, sondern laesst die ECHTE Funktion laufen und stellt nur
# den nft-Aufruf darin - das ist die staerkere Aussage.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import egress_guard as _eg                        # noqa: E402


class _NftAntwort:
    """Was subprocess.run zurueckgibt - egress_guard._run liefert genau das."""
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def lauf(*, ports, smb, dns=True, egress=None, kern="", mounts=""):
    """Die ECHTE Op ausfuehren - nur Netz und Kernel sind gestellt."""
    _eg._run = lambda *a, **k: _NftAntwort(0 if egress is not None else 1, egress or "")
    ns = {"re": re, "time": time}
    ns["_run"] = lambda cmd, **k: (
        {"ok": True, "stdout": "rtt min/avg/max = 7.9/7.9/7.9 ms", "stderr": ""}
        if cmd[0] == "ping" else
        {"ok": egress is not None, "stdout": egress or "", "stderr": ""}
        if cmd[0] == "nft" else {"ok": True, "stdout": "", "stderr": ""})
    ns["_kernel_grund"] = lambda *a, **k: kern
    exec(code, ns)
    # Netzfunktionen stellen, NACHDEM der echte Code geladen ist
    ns["_tcp_offen"] = lambda h, p, timeout=5.0: (p in ports, 10.0, "refused")
    ns["_smb2_negotiate"] = lambda h, timeout=6.0: smb
    quelle = "//nicht.aufloesbar.invalid/share" if dns is not True else "//10.11.12.13/share"
    erg = ns["_op_mount_diagnose"]({"type": "smb", "source": quelle,
                                    "mountpoint": "/mnt/jarvis-kb/share_1"}, None)
    r = erg.get("result") or {}
    return " ".join(r.get("urteil") or []), r


SMB_OK = {"ok": True, "art": "ok", "dialekt": "SMB 3.1.1",
          "text": "Der Server antwortet und einigt sich auf SMB 3.1.1."}
SMB_RESET = {"ok": False, "art": "reset",
             "text": "Die Gegenstelle hat die Verbindung getrennt, sobald das erste SMB-Paket kam."}

# (a) DER GEMELDETE FALL: Port offen, SMB weist ab
u, r = lauf(ports={445, 139}, smb=SMB_RESET)
check("Port offen + SMB abgewiesen: 'nicht erreichbar' wird AUSGESCHLOSSEN",
      "ausgeschlossen" in u and "erreichbar" in u)
check("Port offen + SMB abgewiesen: nennt SMB-Version/Signierung/Zwischenstelle",
      "SMB-Version" in u and "Signierung" in u and "Firewall/IPS" in u)
check("Port offen + SMB abgewiesen: der Handshake steht als Schritt im Bericht",
      any(s["schritt"] == "SMB-Handshake" and not s["ok"] for s in r["schritte"]))

# (b) Server wirklich tot
u2, _ = lauf(ports=set(), smb=None)
check("kein Port offen: sagt weiterhin 'nimmt keine Verbindung an'",
      "keine Verbindung an" in u2)
check("kein Port offen: KEIN SMB-Handshake-Schritt (es gibt nichts zu reden)",
      not any(s["schritt"] == "SMB-Handshake" for s in _["schritte"]))

# (c) alles in Ordnung -> Zugangsdaten sind der naechste Verdacht
u3, _ = lauf(ports={445}, smb=SMB_OK)
check("alles offen: verweist auf Zugangsdaten/Rechte statt auf das Netz",
      "Zugangsdaten" in u3 and "nicht am Netz" in u3)

# (d) Egress-Kette mit nacktem drop
u4, _ = lauf(ports={445}, smb=SMB_OK,
             egress="table inet jarvis_egress {\n chain aus {\n  meta skuid 997 accept\n  drop\n }\n}")
check("nacktes 'drop' in der Egress-Kette wird benannt",
      "Egress-Firewall" in u4 and "JEDEN CIFS" in u4)
u5, _ = lauf(ports={445}, smb=SMB_OK,
             egress="table inet jarvis_egress {\n chain aus {\n  meta skuid 997 drop\n }\n}")
check("an eine Kennung gebundenes 'drop' wird NICHT als Ursache genannt",
      "Egress-Firewall" not in u5)

# (d2) Name nicht aufloesbar -> eigener Zweig, kein Portgerede
u6, r6 = lauf(ports={445}, smb=SMB_OK, dns=False)
check("unaufloesbarer Name: sagt genau das und nennt DNS",
      "nicht aufloesbar" in u6 and "DNS" in u6)
check("unaufloesbarer Name: es wird kein Port gemessen",
      not any(s["schritt"].startswith("TCP") for s in r6["schritte"]))

# (f) ⚠ DIE SONDE SELBST - am 2026-09-05 auf DEV war SIE der Fehler: sie
#     meldete "Server weist SMB ab", waehrend derselbe Server eine laufende
#     Freigabe mit vers=3.1.1 bediente. Ursache: MessageId 1 und der Dialekt
#     0x0311 ohne die dort pflichtigen Negotiate-Kontexte.
sonde_roh = schneide(OPS, {"_smb2_negotiate"})
sonde = ohne_kommentare(sonde_roh)
check("Positivkontrolle: die Kommentare sind wirklich weg",
      "NegotiateContextList" in sonde_roh
      and "NegotiateContextList" not in sonde
      and "def _smb2_negotiate" in sonde)
check("die Sonde bietet 3.1.1 NICHT an (Kontexte waeren Pflicht)",
      "0x0311" not in sonde)
check("die Sonde bietet die uebrigen Dialekte an",
      all(d in sonde for d in ("0x0202", "0x0210", "0x0300", "0x0302")))
check("der erste Request traegt MessageId 0",
      re.search(r'_st\.pack\("<Q", 1\) \+ _st\.pack\("<II", 0, 0\)', sonde) is None)

# (g) Ein LAUFENDER Mount der eigenen Quelle ist kein Problem, sondern der
#     staerkste Beweis, dass alles funktioniert.
def lauf_gemountet(zeile):
    ns = {"re": re, "time": time}
    ns["_run"] = lambda cmd, **k: {"ok": True, "stdout": "rtt min/avg = 0.2 ms", "stderr": ""} \
        if cmd[0] == "ping" else {"ok": False, "stdout": "", "stderr": ""}
    ns["_kernel_grund"] = lambda *a, **k: ""
    exec(code, ns)
    ns["_tcp_offen"] = lambda h, p, timeout=5.0: (True, 1.0, "")
    ns["_smb2_negotiate"] = lambda h, timeout=6.0: SMB_RESET
    import io
    ns["open"] = lambda pfad, *a, **k: io.StringIO(zeile) if pfad == "/proc/mounts" \
        else (_ for _ in ()).throw(OSError("nicht erlaubt"))
    r = ns["_op_mount_diagnose"]({"type": "smb", "source": "//10.11.12.13/share",
                                 "mountpoint": "/mnt/jarvis-kb/share_1"}, None)["result"]
    return " ".join(r["urteil"]), r

u7, r7 = lauf_gemountet("//10.11.12.13/share /mnt/jarvis-kb/share_1 cifs ro,vers=3.1.1 0 0\n")
check("laufender Mount: das Urteil sagt EINGEHAENGT statt einer Vermutung",
      "EINGEHAENGT" in u7)
check("laufender Mount: er behauptet NICHT, der Server weise SMB ab",
      "weist den SMB-Aufbau aber ab" not in u7)
check("laufender Mount: der Schritt gilt als in Ordnung",
      any(s["schritt"] == "Einhaengepunkt" and s["ok"] for s in r7["schritte"]))

u8, r8 = lauf_gemountet("//9.9.9.9/fremd /mnt/jarvis-kb/share_1 cifs ro 0 0\n")
check("FREMDER Mount unter dem Punkt bleibt ein Befund",
      any(s["schritt"] == "Einhaengepunkt" and not s["ok"] for s in r8["schritte"])
      and "EINGEHAENGT" not in u8)

# (h) Ein Server, der mit Fehlerstatus antwortet, ist erreichbar - das ist ein
#     Versionsthema und darf nicht wie Schweigen behandelt werden.
u9, _ = lauf(ports={445}, smb={"ok": False, "art": "status",
                               "text": "Der SMB-Dienst antwortet, einigt sich aber auf keinen Dialekt."})
check("Fehlerstatus: wird als Versionsthema benannt, nicht als Netzproblem",
      "Versionsthema" in u9 and "kein Netzproblem" in u9)

# (e) Die Op darf nichts veraendern - als REGEL ueber den Syntaxbaum
baum = ast.parse(schneide(OPS, {"_op_mount_diagnose"}))
befehle = [n.value for n in ast.walk(baum)
           if isinstance(n, ast.Constant) and isinstance(n.value, str)]
check("die Op ruft weder mount noch umount auf",
      not any(b in ("mount", "umount", "mount.cifs") for b in befehle))
check("die Op oeffnet keine Datei zum Schreiben",
      not any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "open"
              and len(n.args) > 1 and getattr(n.args[1], "value", "") != "r"
              for n in ast.walk(baum)))

# ══════════════════════════════════════════════════════════════════════════
print("\n\033[1m3. Kein frei waehlbares Ziel (sonst waere es ein Portscanner)\033[0m")

ep_ganz = schneide(HAUPT, {"diagnose_share"})
_b = ast.parse(ep_ganz).body[0]
if _b.body and isinstance(_b.body[0], ast.Expr) and isinstance(_b.body[0].value, ast.Constant):
    _b.body = _b.body[1:]          # Docstring abschneiden
ep = ast.unparse(_b)
check("der Endpunkt existiert", bool(ep_ganz))
check("er liest KEIN Ziel aus dem Request",
      "request" not in ep.lower() and "body" not in ep.lower())
# ⚠ ast.unparse normiert Anfuehrungszeichen - auf die EIGENSCHAFT pruefen,
# nicht auf die Schreibweise (sonst meldet der Waechter einen Fehler, den es
# nicht gibt).
check("er holt Typ und Quelle aus der gespeicherten Konfiguration",
      "_get_mounts_config()" in ep
      and re.search(r"m\.get\(['\"]source['\"]", ep) is not None)
check("er haengt an der Wissens-Editor-Schranke",
      "require_knowledge_editor" in ep)
check("er reicht den Index als Grenze durch (404 bei unbekannt)",
      "404" in ep)

_reg = re.search(r'"mount_diagnose": \((.*?)\n    \),', OPS, re.S)
check("die Op ist im Broker registriert", _reg is not None)
check("sie maskiert das Kennwort im Audit",
      _reg is not None and '("password",)' in _reg.group(1))
check("sie ist auto-allow wie die uebrigen System-Ops",
      _reg is not None and re.search(r"True, \(", _reg.group(1)) is not None)
check("sie steht NICHT in READONLY_OPS (Netzzugriff gehoert ins Audit)",
      "mount_diagnose" not in re.search(r"READONLY_OPS = \{[^}]*\}", OPS, re.S).group(0))

# ══════════════════════════════════════════════════════════════════════════
print("\n\033[1m4. Der Broker muss auf ANDEREN Servern mit ankommen\033[0m")

# ⚠ ANLASS: eine neue Broker-Op ist auf einem per Update-Pille aktualisierten
# Server WIRKUNGSLOS - der Broker ist ein eigener Prozess mit eigener Kopie und
# lief bisher mit altem Code weiter (502 "unbekannte Op"). Der Fallstrick steht
# seit Langem im Register; die automatischen Update-Wege beruecksichtigten ihn
# nie.
UPD = open("backend/update_manager.py", encoding="utf-8").read()
nsu = {}
exec(schneide(UPD, {"_broker_betroffen"}), {"_git": lambda *a, **k: nsu["_git"](*a, **k)}, nsu)

def betroffen(dateien, rc=0, hash_da=True):
    nsu["_git"] = lambda *a, **k: (rc, "\n".join(dateien), "")
    return nsu["_broker_betroffen"]("abc123" if hash_da else "")

check("Aenderung an backend/broker/ wird erkannt",
      betroffen(["backend/broker/ops.py", "frontend/js/x.js"]) is True)
check("ohne Broker-Aenderung bleibt es beim schlanken Neustart",
      betroffen(["frontend/js/x.js", "backend/main.py"]) is False)
check("fail-closed: ohne alten Stand wird der Broker vorsichtshalber mitgenommen",
      betroffen([], hash_da=False) is True)
check("fail-closed: antwortet git nicht, ebenfalls",
      betroffen([], rc=1) is True)

# ⚠ AUSGEFUEHRT, nicht am Text gemessen: eine Pruefung auf die REIHENFOLGE der
# Fundstellen im Quelltext bleibt gruen, wenn jemand den Zweig mit "if False:"
# ueberspringt - genau das hat eine Gegenprobe aufgedeckt.
import threading as _th, types as _ty
def neustart_spur(auch_broker):
    spur = []
    stub = _ty.ModuleType("broker_client")
    stub.SOCKET_PATH = "/run/jarvis-broker.sock"
    stub.systemctl_sync = lambda aktion, unit, **k: (spur.append(unit), {"ok": True})[1]
    backend = _ty.ModuleType("backend"); backend.broker_client = stub
    sys.modules["backend"] = backend
    sys.modules["backend.broker_client"] = stub
    ns2 = {"time": time, "threading": _th, "print": lambda *a, **k: None,
           "os": _ty.SimpleNamespace(path=_ty.SimpleNamespace(exists=lambda p: True))}
    exec(schneide(UPD, {"restart_service_delayed"}), ns2)
    ns2["restart_service_delayed"](delay_sec=0, auch_broker=auch_broker)
    for _ in range(100):
        if len(spur) >= (2 if auch_broker else 1):
            break
        time.sleep(0.02)
    return spur

sp_mit = neustart_spur(True)
check("mit Broker-Aenderung werden BEIDE Dienste neu gestartet",
      len(sp_mit) == 2, )
check("und der Broker ZUERST (sonst laeuft neues Backend gegen alten Broker)",
      sp_mit[:2] == ["jarvis-broker.service", "jarvis.service"])
sp_ohne = neustart_spur(False)
check("ohne Broker-Aenderung bleibt es beim einen Neustart",
      sp_ohne == ["jarvis.service"])

neu_code = ohne_kommentare(schneide(UPD, {"restart_service_delayed"}))
check("auf den neuen Socket wird gewartet",
      "SOCKET" in neu_code and "os.path.exists" in neu_code)
check("der Selbstneustart wird nicht als Fehler gewertet",
      "except Exception" in neu_code)

ep_upd = ohne_kommentare(schneide(HAUPT, {"apply_update_endpoint", "update_apply"})) or ""
if not ep_upd:                      # Endpunktname unbekannt -> am Aufruf messen
    i = HAUPT.find("restart_service_delayed(delay_sec=2.0")
    ep_upd = HAUPT[max(0, i - 400):i + 400] if i != -1 else ""
check("der Endpunkt reicht auch_broker durch (sonst bleibt die Funktion wirkungslos)",
      "auch_broker" in ep_upd and "broker_betroffen" in ep_upd)

# Der Startup-Check deckt ALLE Wege ab - auch scp und den Cron-Job.
sc = schneide(HAUPT, {"startup_broker_aktualitaet"})
check("es gibt einen Startup-Check auf einen veralteten Broker", bool(sc))
sc_o = ohne_kommentare(sc)
check("er misst Dateizeit gegen Broker-Startzeit",
      "ActiveEnterTimestampMonotonic" in sc_o and "st_mtime" in sc_o)
check("er ist abschaltbar", "JARVIS_BROKER_AUTORESTART" in sc_o)
check("ohne Socket passiert nichts (Alt-Betrieb)",
      "SOCKET_PATH" in sc_o and "return" in sc_o)
check("er haengt an einem startup-Ereignis",
      '@app.on_event("startup")' in HAUPT[:HAUPT.find("async def startup_broker_aktualitaet")][-120:])

print(f"\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)

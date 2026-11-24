#!/usr/bin/env python3
"""Waechter fuer den E-Mail-Versand (backend/mail_meldung.py und seine Anschluesse).

Alles laeuft in einem Sandkasten (JARVIS_MAIL_WURZEL); Befehle (sendmail,
postconf, systemctl …) gehen an eine Attrappe von ``mail_meldung._lauf`` mit
der ECHTEN Signatur, die jeden Aufruf festhaelt.

Die Zusagen:
  1. Eingaben: Adressen, Relay und Quellen werden geprueft, Unbekanntes abgewiesen.
  2. Speichern und Einrichten OHNE Freigabe-Code (Betreiberentscheid
     2026-11-24), Absender/Name/Betreff einzeilig geprueft, Audit mit Werten.
     Gemessen ueber den ECHTEN Broker-Weg (meta.behandeln).
  3. Postfix: lauscht nicht nach aussen (loopback-only, SMTP-Eingang aus),
     nur root darf abgeben, Relay wie eingestellt.
  4. root-Weiterleitung folgt der Quelle "system"; fremde root-Zeilen werden
     markiert auskommentiert, das Ergebnis ist stabil (zweimal = gleich).
  5. Senden: ausgeschaltete Quelle / kein Empfaenger -> nichts; Drosselung je
     Stunde, Zurueckgehaltenes wird in der naechsten Mail genannt.
  6. Sicherheitsmeldungen tragen nur die festen Felder, einzeilig – nie Inhalte.
  7. AIDE erklaert nur den byteweise selbst geschriebenen Stand.
  8. Anschluesse: Ueberwachung und AIDE-Abgleich rufen das Modul; security_guard,
     main.py und sicherheit_mail geben nur Metadaten weiter.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def pruefe(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


def abbruch(text):
    print("ABBRUCH: " + text)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="mail_meldung_"))
W = TMP / "w"
os.environ["JARVIS_MAIL_WURZEL"] = str(W)
os.environ["JARVIS_BROKER_CONF"] = "/etc/jarvis/broker.conf"
sys.path.insert(0, str(REPO))
try:
    from backend import mail_meldung as mm
finally:
    pass

if not str(mm._p(mm.BROKER_CONF)).startswith(str(TMP)):
    abbruch("broker.conf liegt nicht im Sandkasten: %s" % mm._p(mm.BROKER_CONF))

AUFRUFE = []


class Erg:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def lauf_attrappe(befehl, timeout=60, eingabe=None, umgebung=None):
    AUFRUFE.append({"befehl": list(befehl), "eingabe": eingabe})
    if befehl[0] == "hostname":
        return Erg(0, "probe.beispiel.de\n")
    if befehl[:2] == ["postconf", "-M"]:
        return Erg(0, "smtp inet n - y - - smtpd\n")
    return Erg(0, "")


mm._lauf = lauf_attrappe


def konf_setzen(text):
    p = mm._p(mm.BROKER_CONF)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def postfix_da():
    for f in (mm.POSTFIX, mm.SENDMAIL):
        mm._p(f).parent.mkdir(parents=True, exist_ok=True)
        mm._p(f).write_text("", encoding="utf-8")


def gesendet():
    return [a for a in AUFRUFE if a["befehl"][0] == mm.SENDMAIL]


try:
    # ── 0. Positivkontrolle ──────────────────────────────────────────────────
    print("[0] Positivkontrolle")
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_RELAY=relay.beispiel.de\n")
    postfix_da()
    AUFRUFE.clear()
    e = mm.senden("ueberwachung", "B13 ALARM: Probe", "Zeile 1")
    if not (e.get("gesendet") and len(gesendet()) == 1):
        abbruch("Grundfall sendet nicht: %s" % e)
    pruefe(True, "Grundfall: eine Meldung geht an sendmail")
    m = gesendet()[0]
    pruefe(m["befehl"][-1] == "a@beispiel.de" and "--" in m["befehl"],
           "Empfaenger hinter '--' (keine Option aus einer Adresse)")
    pruefe("Subject: [Jarvis probe] B13 ALARM: Probe" in m["eingabe"], "Betreff traegt Servername und Text")
    pruefe("Auto-Submitted: auto-generated" in m["eingabe"], "als automatische Nachricht gekennzeichnet")
    pruefe(mm.konf()["quellen"] == list(mm.QUELLEN), "ohne MAIL_QUELLEN sind alle Quellen an")

    # ── 1. Eingaben ──────────────────────────────────────────────────────────
    print("[1] Eingaben")
    pruefe(mm.empfaenger_pruefen("a@b.de, c@d.de;a@b.de")[0] == ["a@b.de", "c@d.de"],
           "Liste mit Komma/Semikolon, Doppelte entfernt")
    pruefe(mm.empfaenger_pruefen("a@b.de -oQ/tmp")[1] != "", "Option als Adresse abgewiesen")
    pruefe(mm.empfaenger_pruefen("x@localhost")[1] != "", "Adresse ohne Domaene abgewiesen")
    pruefe(mm.empfaenger_pruefen(",".join("a%d@b.de" % i for i in range(11)))[1] != "",
           "mehr als %d Empfaenger abgewiesen" % mm.EMPFAENGER_MAX)
    pruefe(mm.absender_pruefen("meldung@server") == ("meldung@server", ""),
           "Absender ohne Punkt im Domaenenteil erlaubt (Exchange nimmt name@server an)")
    pruefe(mm.absender_pruefen("a@b@c")[1] != "" and mm.absender_pruefen("a b@c")[1] != "",
           "Absender mit zweitem @ oder Leerzeichen abgewiesen")
    pruefe("gültige" in mm.absender_pruefen("kein-at")[1], "Meldung mit echten Umlauten (Oberflaechentext)")
    pruefe(mm.relay_pruefen("mail.firma.local")[0] == "mail.firma.local:25", "Relay ohne Port -> :25")
    pruefe(mm.relay_pruefen("[mail.firma.local]:587")[0] == "mail.firma.local:587", "Relay [host]:port")
    # ohne Leerzeichen: sonst scheitert es schon am ersten Muster, und die
    # Zeichenpruefung des Namens bliebe ungemessen (Gegenprobe 2026-11-24)
    pruefe(mm.relay_pruefen("mail;rm")[1] != "", "Relay mit Fremdzeichen abgewiesen")
    pruefe(mm.relay_pruefen("-oX")[1] != "", "Relay mit fuehrendem Bindestrich abgewiesen")
    pruefe(mm.relay_pruefen("host:70000")[1] != "", "Port ausserhalb abgewiesen")
    pruefe(mm.quellen_pruefen(["aide", "unbekannt"])[1] != "", "unbekannte Quelle abgewiesen")
    pruefe(mm.quellen_pruefen(["system", "aide"])[0] == ["aide", "system"], "Quellen in fester Reihenfolge")

    # ── 2. Speichern ueber den echten Broker-Weg – OHNE Freigabe-Code ────────
    # Betreiberentscheid 2026-11-24: Administratoren sind mit 2FA angemeldet.
    print("[2] Speichern (meta.behandeln), ohne Freigabe-Code")
    from backend.broker import freigabe, meta, policy
    CODES = []
    freigabe.pruefen = lambda code, *a, **k: (CODES.append(code) or False, "nachweis_fehlt")
    AUDIT = []
    policy.audit = lambda *a, **k: AUDIT.append((a, k))
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_RELAY=relay.beispiel.de:25\nMAIL_QUELLEN=aide,system\n")
    r = meta.behandeln("broker.mailversand", {"aktion": "speichern", "empfaenger": "b@beispiel.de",
                                              "relay": "anders.beispiel.de", "quellen": ["aide"],
                                              "absender": "meldung@beispiel.de", "absender_name": "Alarm {server}",
                                              "betreff": "[DP {server}]", "by": "admin"})
    k = mm.konf()
    pruefe(r.get("ok") and k["empfaenger"] == ["b@beispiel.de"] and k["relay"] == "anders.beispiel.de:25"
           and k["quellen"] == ["aide"], "Empfaenger, Relay, Quelle aus: ohne Code gespeichert")
    pruefe(not CODES, "der Freigabe-Code wird nicht einmal geprueft")
    pruefe(k["absender"] == "meldung@beispiel.de" and k["absender_name"] == "Alarm {server}"
           and k["betreff"] == "[DP {server}]", "Absender, Name und Betreff gespeichert")
    pruefe(any("b@beispiel.de" in str(kw.get("info", "")) for _, kw in AUDIT), "Aenderung steht mit Werten im Audit")
    r = meta.behandeln("broker.mailversand", {"aktion": "einrichten"})
    pruefe(r.get("ok") and not CODES, "Einrichten ohne Code")
    os.chmod(mm._p(mm.BROKER_CONF), 0o644)
    meta.behandeln("broker.mailversand", {"aktion": "speichern", "empfaenger": "b@beispiel.de",
                                          "relay": "relay.beispiel.de", "quellen": ["aide", "system"]})
    pruefe(mm._p(mm.BROKER_CONF).stat().st_mode & 0o777 == 0o644, "broker.conf behaelt ihre Rechte")
    pruefe(mm.konf()["absender"] == "" and mm.konf()["betreff"] == "", "leere Felder = zurueck auf die Vorgabe")
    for feld, wert, text in (("empfaenger", "x y", "ungueltige Adresse"),
                             ("absender", "kein-at", "ungueltiger Absender"),
                             ("absender", "a@b.de -oQ/tmp", "Absender mit Option"),
                             ("absender_name", "Name\nBcc: x@y.de", "Name mit Zeilenumbruch"),
                             ("betreff", "B\rX-Kopf: 1", "Betreff mit Steuerzeichen"),
                             ("betreff", "x" * 81, "Betreff zu lang")):
        args = {"aktion": "speichern", "empfaenger": "b@beispiel.de", "relay": "", "quellen": []}
        args[feld] = wert
        vorher = mm._p(mm.BROKER_CONF).read_text()
        r = meta.behandeln("broker.mailversand", args)
        pruefe(not r.get("ok") and mm._p(mm.BROKER_CONF).read_text() == vorher,
               "%s abgewiesen, broker.conf unveraendert" % text)

    # ── 3. Postfix-Konfiguration ─────────────────────────────────────────────
    print("[3] Postfix")
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_RELAY=relay.beispiel.de:25\n")
    AUFRUFE.clear()
    e = mm.anwenden()
    pruefe(e.get("ok"), "anwenden laeuft durch: %s" % e.get("meldung"))
    cf = mm._p(mm.MAIN_CF).read_text()
    zeilen = {z.split("=", 1)[0].strip(): z.split("=", 1)[1].strip() for z in cf.splitlines()
              if "=" in z and not z.startswith("#")}
    pruefe(zeilen.get("inet_interfaces") == "loopback-only", "inet_interfaces = loopback-only")
    pruefe(zeilen.get("authorized_submit_users") == "root", "nur root darf abgeben")
    pruefe(zeilen.get("relayhost") == "[relay.beispiel.de]:25", "relayhost aus broker.conf")
    pruefe("." in zeilen.get("myhostname", ""), "myhostname voll qualifiziert")
    pruefe(any(a["befehl"][:2] == ["postconf", "-M#"] and a["befehl"][2] == "smtp/inet" for a in AUFRUFE),
           "SMTP-Eingang wird abgeschaltet (postconf -M# smtp/inet)")
    pruefe(mm._p(mm.AIDE_DROPIN).read_text().count("MAILCMD=true") == 1,
           "Debians AIDE-Tagesbericht stillgelegt (Drop-in)")
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_RELAY=\n")
    mm.anwenden()
    pruefe("relayhost = \n" in mm._p(mm.MAIN_CF).read_text(), "leerer Relay = direkte Zustellung")

    # ── 4. root-Weiterleitung ────────────────────────────────────────────────
    print("[4] root-Weiterleitung")
    k_an = {"empfaenger": ["a@beispiel.de", "b@beispiel.de"], "relay": "", "quellen": list(mm.QUELLEN)}
    k_aus = dict(k_an, quellen=["aide"])
    alt_txt = "# Kopf\npostmaster: root\nroot: alter@beispiel.de\n"
    a1 = mm.aliases(alt_txt, k_an)
    pruefe("root: a@beispiel.de, b@beispiel.de" in a1, "Quelle system an: root an die Empfaenger")
    pruefe(mm._AUSKOMMENTIERT + "root: alter@beispiel.de" in a1, "fremde root-Zeile markiert auskommentiert")
    pruefe(sum(1 for z in a1.splitlines() if z.startswith("root:")) == 1, "genau eine wirksame root-Zeile")
    pruefe(mm.aliases(a1, k_an) == a1, "stabil: zweimal angewandt = gleich")
    a2 = mm.aliases(a1, k_aus)
    pruefe("root: /dev/null" in a2 and "a@beispiel.de" not in a2.split(mm._MARKE_AN)[1],
           "Quelle system aus: root ins Leere")
    pruefe(a2.count("postmaster: root") == 1, "postmaster nicht verdoppelt")

    # ── 5. Senden und Drosselung ─────────────────────────────────────────────
    print("[5] Senden")
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_ABSENDER=meldung@beispiel.de\n"
                "MAIL_ABSENDER_NAME=Alarm {server}\nMAIL_BETREFF=[DP {server}]\n")
    AUFRUFE.clear()
    mm.senden("aide", "Probe", "t")
    g = gesendet()[0] if gesendet() else {"befehl": [], "eingabe": ""}
    paare = list(zip(g["befehl"], g["befehl"][1:]))
    pruefe(("-f", "meldung@beispiel.de") in paare, "Umschlag-Absender (-f) aus der Einstellung")
    pruefe("From: Alarm probe <meldung@beispiel.de>" in g["eingabe"], "From mit Name, {server} ersetzt")
    pruefe("Subject: [DP probe] Probe" in g["eingabe"], "Betreff-Anfang aus der Einstellung, {server} ersetzt")
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_QUELLEN=aide\n")
    AUFRUFE.clear()
    e = mm.senden("ueberwachung", "x", "y")
    pruefe(not e.get("gesendet") and not gesendet(), "ausgeschaltete Quelle: nichts verschickt")
    konf_setzen("MAIL_QUELLEN=aide\n")
    e = mm.senden("aide", "x", "y")
    pruefe(not e.get("gesendet") and not gesendet(), "ohne Empfaenger: nichts verschickt")
    e = mm.senden("unbekannt", "x", "y")
    pruefe(not e.get("ok") and not gesendet(), "unbekannte Quelle abgewiesen")
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\n")
    mm._p(mm.ZUSTAND).unlink(missing_ok=True)
    grenze = mm.GRENZE_JE_STUNDE["sicherheit"]
    ergebnisse = [mm.senden("sicherheit", "S%d" % i, "t") for i in range(grenze + 3)]
    pruefe(len(gesendet()) == grenze, "Drosselung: %d von %d verschickt (Grenze %d)"
           % (len(gesendet()), grenze + 3, grenze))
    pruefe(all(r.get("gedrosselt") for r in ergebnisse[grenze:]), "darueber als gedrosselt gemeldet")
    z = json.loads(mm._p(mm.ZUSTAND).read_text())
    z["drossel"]["sicherheit"]["start"] -= 3601
    mm._p(mm.ZUSTAND).write_text(json.dumps(z))
    AUFRUFE.clear()
    mm.senden("sicherheit", "neu", "t")
    pruefe(gesendet() and "3 weitere Meldung(en)" in gesendet()[0]["eingabe"],
           "naechste Stunde: Zurueckgehaltenes wird genannt")
    AUFRUFE.clear()
    mm._p(mm.POSTFIX).unlink()
    e = mm.senden("aide", "x", "y")
    pruefe(not e.get("ok") and not gesendet(), "ohne Postfix: Fehler statt stiller Erfolg")
    postfix_da()

    # ── 6. Sicherheitsmeldungen ──────────────────────────────────────────────
    print("[6] Sicherheitsmeldungen")
    mm._p(mm.ZUSTAND).unlink(missing_ok=True)
    AUFRUFE.clear()
    e = mm.sicherheit({"art": "konto_gesperrt_angriff", "benutzer": "probe\nBcc: x@y.de",
                       "kanal": "web", "muster": "heuristic/persona", "snippet": "GEHEIMER PROMPT",
                       "detail": "rm -rf /", "task": "AUFTRAGSTEXT"})
    pruefe(e.get("gesendet"), "Sicherheitsmeldung verschickt")
    txt = gesendet()[0]["eingabe"] if gesendet() else ""
    pruefe("GEHEIMER PROMPT" not in txt and "rm -rf" not in txt and "AUFTRAGSTEXT" not in txt,
           "keine Inhalte (snippet/detail/task) in der Mail")
    pruefe("\nBcc:" not in txt, "Feldwerte einzeilig – kein eingeschleuster Kopf")
    pruefe("heuristic/persona" in txt and "Kanal:" in txt, "Metadaten stehen drin")
    pruefe(not mm.sicherheit({"art": "frei_erfunden"}).get("ok"), "unbekannte Art abgewiesen")

    # ── 7. AIDE-Erklaerung ───────────────────────────────────────────────────
    print("[7] AIDE")
    pruefe(mm.erklaert(mm.MAIN_CF), "selbst geschriebene main.cf ist erklaert")
    mm._p(mm.MAIN_CF).write_text(mm._p(mm.MAIN_CF).read_text() + "relayhost = [boese]\n")
    pruefe(not mm.erklaert(mm.MAIN_CF), "nachtraeglich geaenderte main.cf NICHT erklaert")
    pruefe(not mm.erklaert("/etc/passwd"), "fremde Datei nicht erklaert")

    # ── 8. Anschluesse ───────────────────────────────────────────────────────
    print("[8] Anschluesse")
    from backend import ueberwachung
    gerufen = []
    mm_orig = mm.senden
    mm.senden = lambda q, b, t: gerufen.append((q, b, t)) or {"ok": True}
    ueberwachung.mail_melden([("warnung", "B13 WARNUNG: a"), ("alarm", "B13 ALARM: b")])
    pruefe(gerufen and gerufen[0][0] == "ueberwachung" and gerufen[0][1].startswith("B13 ALARM: b"),
           "Ueberwachung: eine Mail, Betreff nach der hoechsten Stufe")
    gerufen.clear()
    ueberwachung.mail_melden([])
    pruefe(not gerufen, "Ueberwachung ohne Aenderung: keine Mail")
    lauf_src = ast.parse((REPO / "backend/ueberwachung.py").read_text())
    lauf_fn = next((f for f in ast.walk(lauf_src) if isinstance(f, ast.FunctionDef) and f.name == "lauf"), None)
    pruefe(lauf_fn is not None and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "mail_melden"
                                       for c in ast.walk(lauf_fn)), "ueberwachung.lauf ruft mail_melden")
    mm.senden = mm_orig

    from backend import aide_abgleich as aa
    t = aa.mail_text({"zustand": "offen", "offen_anzahl": 2, "bericht": {"summe": {"geaendert": 5}},
                      "offen": [{"art": "geaendert", "pfad": "/etc/x", "warum": "Inhalt weicht ab"}]})
    pruefe(t and "2 nicht erklärte" in t[0] and "/etc/x" in t[1], "AIDE offen: Betreff und Pfadliste")
    pruefe(aa.mail_text({"zustand": "uebernommen"}) is None and aa.mail_text({"zustand": "unveraendert"}) is None,
           "AIDE sauber: keine Mail")
    pruefe(aa.mail_text({"zustand": "fehler", "grund": "kaputt"})[0].startswith("AIDE-Abgleich fehlgeschlagen"),
           "AIDE Fehler: Mail")
    np_fn = next((f for f in ast.walk(ast.parse((REPO / "backend/aide_abgleich.py").read_text()))
                  if isinstance(f, ast.FunctionDef) and f.name == "nach_pruefung"), None)
    pruefe(np_fn is not None and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "mail_melden"
                                     for c in ast.walk(np_fn)), "aide_abgleich.nach_pruefung ruft mail_melden")

    from backend import sicherheit_mail as sm
    from backend import broker_client
    abgabe = []
    broker_client.call_sync = lambda op, args=None, **k: abgabe.append((op, args)) or {"ok": True}
    sm._aufruf({"art": "spruehangriff"})
    pruefe(abgabe and abgabe[0][0] == "broker.mail_melden", "Dienst gibt ueber den Broker ab")
    abgabe.clear()
    sm._aufruf_orig = sm._aufruf
    sm_args = []
    import threading
    alt_thread = threading.Thread

    class SofortThread:
        def __init__(self, target=None, args=(), **k):
            self.t, self.a = target, args

        def start(self):
            sm_args.append(self.a[0])

    sm.threading.Thread = SofortThread
    sm.melden("konto_gesperrt_angriff", benutzer="u", snippet="INHALT", task="AUFTRAG")
    sm.threading.Thread = alt_thread
    pruefe(sm_args and set(sm_args[0]) <= {"art"} | set(sm.FELDER) and "INHALT" not in json.dumps(sm_args),
           "sicherheit_mail reicht nur feste Felder weiter")
    pruefe(not sm.melden("frei_erfunden"), "sicherheit_mail: unbekannte Art -> nichts")
    pruefe(set(sm.ARTEN) == set(mm.SICHERHEIT_ARTEN), "Dienst und Broker kennen dieselben Arten")

    sg = ast.parse((REPO / "backend/security_guard.py").read_text())
    def ruft_mail(fname, art):
        f = next((x for x in ast.walk(sg) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and x.name == fname), None)
        return f is not None and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_mail"
                                     and c.args and getattr(c.args[0], "value", None) == art
                                     for c in ast.walk(f))
    pruefe(ruft_mail("_record", "konto_gesperrt_angriff"), "security_guard._record meldet neue Sperre")
    pruefe(ruft_mail("record_violation", "konto_gesperrt_verstoss"), "record_violation meldet Auto-Sperre")
    pruefe(ruft_mail("inspect", "angriff_protokolliert"), "inspect meldet hartes Muster ohne Sperre")
    for fname in ("_record", "record_violation", "inspect"):
        f = next(x for x in ast.walk(sg) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == fname)
        kw = {k.arg for c in ast.walk(f) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_mail"
              for k in c.keywords}
        pruefe(kw and kw <= set(sm.FELDER), "%s: nur Metadaten-Felder (%s)" % (fname, ", ".join(sorted(kw))))
    hm = (REPO / "backend/main.py").read_text()
    pruefe('_mail_sicherheit("konto_gesperrt_anmeldung"' in hm and '_mail_sicherheit("spruehangriff"' in hm,
           "main.py meldet Kontosperre und Spruehangriff")
    # ── 10. Sprache der Mails = Oberflaechensprache (gemeldet 2026-11-24) ───
    print("[10] Sprache")
    alle = mm._texte_laden()
    pruefe(all(len(alle.get(sp_, {})) >= 40 for sp_ in ("de", "en", "fr")),
           "Positivkontrolle: Texte aus i18n.js/i18n_fr.js gelesen (%s)" % {k_: len(v) for k_, v in alle.items()})
    # REGEL am Syntaxbaum: jeder Schluessel, den Mailmodul, Ueberwachung und
    # AIDE-Abgleich benutzen, steht in ALLEN drei Sprachen (fehlt einer, faellt
    # die Mail still auf Deutsch zurueck – genau der gemeldete Zustand).
    benutzt = set()
    for datei in ("backend/mail_meldung.py", "backend/ueberwachung.py", "backend/aide_abgleich.py"):
        for c in ast.walk(ast.parse((REPO / datei).read_text())):
            if isinstance(c, ast.Call) and c.args and isinstance(c.args[0], ast.Constant) \
                    and isinstance(c.args[0].value, str) and c.args[0].value.startswith("mvm."):
                benutzt.add(c.args[0].value)
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.startswith("mvm.") \
                    and not c.value.endswith(("_", ".s_", ".f_")):
                benutzt.add(c.value)
    # zusammengesetzte Schluessel: Praefix + bekannte Endungen
    benutzt |= {"mvm.s_" + a_ for a_ in mm.SICHERHEIT_ARTEN} | {"mvm.f_" + f_ for f_ in
                ("benutzer", "kanal", "muster", "ip", "anzahl")} | {"mvm.ue_" + s_ for s_ in
                ("alarm", "warnung", "behoben")} | {"mvm.aide_art_" + a_ for a_ in ("neu", "entfernt", "geaendert")}
    benutzt = {b_ for b_ in benutzt if not b_.endswith("_")}
    fehlt = sorted("%s:%s" % (sp_, k_) for k_ in benutzt for sp_ in ("de", "en", "fr") if k_ not in alle.get(sp_, {}))
    pruefe(len(benutzt) >= 30 and not fehlt, "jeder benutzte Mailtext steht in DE, EN und FR (%d)%s"
           % (len(benutzt), (" – fehlt: " + ", ".join(fehlt[:8])) if fehlt else ""))
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_SPRACHE=en\nMAIL_MARKE=Fabrikam\n")
    mm._p(mm.ZUSTAND).unlink(missing_ok=True)
    AUFRUFE.clear()
    mm.test()
    t_en = gesendet()[0]["eingabe"] if gesendet() else ""
    pruefe("Subject: [Jarvis probe] Test message" in t_en and "This test message confirms" in t_en
           and "This message is sent automatically" in t_en,
           "Testmail englisch (Betreff, Text, Fusszeile)")
    kopf_en = t_en.split("\n\n", 1)[1] if "\n\n" in t_en else ""
    pruefe(all(z in kopf_en for z in ("Server: ", "Time: ", "Type: Test message")) and "Zeit:" not in kopf_en
           and "Art:" not in kopf_en, "Kopfzeilen der Mail englisch (Server, Time, Type)")
    AUFRUFE.clear()
    mm.sicherheit({"art": "spruehangriff", "ip": "192.0.2.1"})
    t_en = gesendet()[0]["eingabe"] if gesendet() else ""
    pruefe("Password spraying" in t_en and "Source address: 192.0.2.1" in t_en, "Sicherheitsmail englisch")
    zu = {"befunde": [{"id": "zert", "art": "zert_ablauf", "stufe": "warnung", "text": "DEUTSCH",
                       "werte": {"tage": 5, "ablauf": 1796000000}}]}
    AUFRUFE.clear()
    ueberwachung.mail_melden([("warnung", "B13 WARNUNG zert: DEUTSCH")], zu, {})
    t_en = gesendet()[0]["eingabe"] if gesendet() else ""
    pruefe("WARNING: The server certificate expires" in t_en and "DEUTSCH" not in t_en,
           "Ueberwachung englisch aus Art und Werten, nicht der Journaltext")
    AUFRUFE.clear()
    ueberwachung.mail_melden([("behoben", "B13 BEHOBEN zert: DEUTSCH")], {"befunde": []}, zu)
    t_en = gesendet()[0]["eingabe"] if gesendet() else ""
    pruefe("RESOLVED: The server certificate" in t_en, "behobener Befund aus dem Vorzustand uebersetzt")
    t_aide = aa.mail_text({"zustand": "offen", "offen_anzahl": 1, "bericht": {"summe": {"neu": 1}},
                           "offen": [{"art": "neu", "pfad": "/etc/x", "warum": "w"}]})
    pruefe(t_aide and t_aide[0] == "AIDE: 1 unexplained change(s)" and "[added] /etc/x" in t_aide[1]
           and "signed Fabrikam release" in t_aide[1], "AIDE-Mail englisch, {marke} aus der Einstellung")
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_SPRACHE=fr\n")
    AUFRUFE.clear()
    mm.test()
    pruefe(gesendet() and "Message de test" in gesendet()[0]["eingabe"], "Testmail franzoesisch")
    konf_setzen("MAIL_EMPFAENGER=a@beispiel.de\nMAIL_SPRACHE=xx\n")
    pruefe(mm.konf()["sprache"] == "de", "unbekannte Sprache -> Deutsch")
    r = meta.behandeln("broker.mailversand", {"aktion": "sprache", "sprache": "en", "marke": "Fabrikam"})
    pruefe(r.get("ok") and mm.konf()["sprache"] == "en" and mm.konf()["empfaenger"] == ["a@beispiel.de"],
           "Aktion 'sprache' setzt nur die Sprache, Empfaenger bleibt")
    r = meta.behandeln("broker.mailversand", {"aktion": "sprache", "sprache": "xx"})
    pruefe(not r.get("ok") and mm.konf()["sprache"] == "en", "unbekannte Sprache abgewiesen")
    r = meta.behandeln("broker.mailversand", {"aktion": "speichern", "empfaenger": "a@beispiel.de",
                                              "relay": "", "quellen": ["aide"], "sprache": "fr"})
    pruefe(r.get("ok") and mm.konf()["sprache"] == "fr", "Speichern uebernimmt die Sprache")
    bi = (REPO / "deploy/security/broker_installieren.sh").read_text()
    pruefe('I18N_DATEIEN="frontend/js/i18n.js frontend/js/i18n_fr.js"' in bi and "$I18N_DATEIEN 2>/dev/null" in bi,
           "Broker-Kopie enthaelt die Uebersetzungen (root liest nicht die Datei des Dienstes)")
    pruefe(mm.I18N_JS.parent.parent.parent == REPO / "backend" / ".." or
           mm.I18N_JS == (REPO / "frontend/js/i18n.js").resolve(),
           "das Modul liest i18n.js NEBEN sich (Broker-Kopie), keinen festen /opt-Pfad")

    # ── 9. Ausrollen auf andere Server ohne Handarbeit ───────────────────────
    print("[9] Automatik")
    start = (REPO / "start_jarvis_root.sh").read_text()
    m6j = start.split("# 6j. E-Mail-Versand sicherstellen", 1)
    block = m6j[1].split("\n# 6", 1)[0] if len(m6j) == 2 else ""
    pruefe(bool(block), "start_jarvis_root.sh hat den Schritt 6j")
    pruefe('MAIL_PROG="$CODE_DIR/backend/mail_meldung.py"' in block,
           "6j ruft das Modul aus der root-eigenen Kopie ($CODE_DIR), nicht aus /opt/jarvis")
    pruefe("MAIL_AKTION=--anwenden; else MAIL_AKTION=--einrichten" in block,
           "6j: vorhanden -> anwenden, fehlt -> einrichten")
    pruefe(block.rstrip().endswith(") &\nfi"), "6j laeuft im Hintergrund (haelt den Broker-Start nicht auf)")
    pruefe("JARVIS_MAILVERSAND_AUTO" in block, "6j abschaltbar")
    um = ast.parse((REPO / "backend/update_manager.py").read_text())
    pf = next((n.value for n in ast.walk(um) if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "_BROKER_PFADE" for t in n.targets)), None)
    werte = {e.value for e in getattr(pf, "elts", []) if isinstance(e, ast.Constant)}
    fehlt = {"backend/mail_meldung.py", "backend/ueberwachung.py", "backend/aide_abgleich.py",
             "start_jarvis_root.sh", "backend/broker/", "frontend/js/i18n.js", "frontend/js/i18n_fr.js"} - werte
    pruefe(not fehlt, "Update startet den Broker bei Aenderung der root-Module neu (%s)" % (", ".join(sorted(fehlt)) or "alle da"))
    # Installer-Wechsel (0c): sonst kaemen neue mitkopierte Dateien (i18n)
    # erst beim UEBERNAECHSTEN Broker-Neustart an – auf DEV nachgestellt.
    m0c = start.split("# 0c. Installer-Wechsel nachholen", 1)
    b0c = m0c[1].split("\n# 0b.", 1)[0] if len(m0c) == 2 else ""
    pruefe(bool(b0c) and start.index("# 0c.") < start.index("# 0b."), "Startschritt 0c steht vor dem Rest des Starts")
    pruefe('[ "${JARVIS_BROKER_NACHINSTALL:-0}" != "1" ]' in b0c and "export JARVIS_BROKER_NACHINSTALL=1" in b0c,
           "0c laeuft hoechstens einmal (Schleifensperre)")
    pruefe('bash "$BROKER_INSTALL_DIR/$INSTALLER_REL"' in b0c and '.get("installer","")' in b0c,
           "0c vergleicht den Vermerk im STAND mit dem Installer DER KOPIE und ruft diesen")
    pruefe('"installer": installer' in bi and 'd["installer"] = sha' in bi,
           "Installer vermerkt sich im STAND – auch wenn der Inhalt gleich bleibt")
    mm.main.__doc__  # noqa: B018
    pruefe("--einrichten" in mm.__doc__ and "--anwenden" in mm.__doc__, "Kommandozeile kennt --einrichten/--anwenden")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\nERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)

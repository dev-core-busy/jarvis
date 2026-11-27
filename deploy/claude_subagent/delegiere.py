#!/usr/bin/env python3
"""Client fuer den Jarvis-Skill "Claude Subagent".

Gibt eine eng umrissene Codeaufgabe an Jarvis ab und holt das Ergebnis als
PATCH zurueck. Der Patch wird NICHT automatisch angewandt – das entscheidet
Claude nach dem Lesen.

ZUGANG – je Jarvis-Installation zu setzen, es gibt KEINE Vorgabe
    Schluessel  <MARKE>_CSA_KEY  oder  ~/.<marke>-csa-key
    Adresse     <MARKE>_CSA_URL  oder  ~/.<marke>-csa-url
    <MARKE> = Name des Assistenten aus dem Branding (z.B. NEXI/.nexi-).

    Bewusst KEIN voreingestellter Host: derselbe Client laeuft gegen jede
    Jarvis-Installation. Eine Vorgabe waere die Adresse genau einer davon – bei
    der naechsten falsch, und der Fehler saehe wie ein Schluesselproblem aus
    (ein fremder Server kennt den Schluessel nicht und antwortet 401).

    Der Schluessel gehoert NICHT ins Repo. ~/.<marke>-csa-key liegt ausserhalb,
    die Umgebungsvariable erst recht.

ZERTIFIKAT
    Geprueft wird wie im Browser (Systemspeicher, Name). Vertraut das System
    dem Serverzertifikat nicht (selbst ausgestellt, Zugriff per IP), gilt nur
    ein bestaetigter Fingerabdruck: einmalig `delegiere.py vertrauen` – er
    landet in ~/.<marke>-csa-cert (bzw. <MARKE>_CSA_CERT). http:// wird
    abgelehnt: der Schluessel geht in jeder Anfrage mit.

AUFRUF
    delegiere.py senden --spec-datei auftrag.txt \\
                        --dateien frontend/css/chat.css \\
                        --riegel tests/test_branding_aliase.py
    delegiere.py holen <id>
    delegiere.py warten <id>          # bis fertig, dann Patch auf stdout
    delegiere.py vertrauen            # Serverzertifikat bestaetigen (s. u.)

Die Basis (Commit-Hash) wird aus dem lokalen Repo ermittelt; der Client bricht
ab, wenn der Arbeitsbaum an den Zieldateien schmutzig ist – ein Patch gegen
einen anderen Stand liesse sich nachher nicht sauber anwenden.
"""

import argparse
import hashlib
import hmac
import http.client
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

def fehler(text: str, code: int = 1):
    print(f"FEHLER: {text}", file=sys.stderr)
    sys.exit(code)


def _aus_umgebung_oder_datei(endung: str, was: str) -> str:
    """Sucht `<MARKE>_CSA_<ENDUNG>` bzw. `~/.<marke>-csa-<endung>`.

    Der MARKENNAME steckt in beiden Namen – so steht in der Anleitung der Name
    des Assistenten und nicht "Jarvis". Der Client kann die Marke aber nicht
    kennen (sie liegt auf dem Server), deshalb wird nach dem MUSTER gesucht
    statt nach einem festen Namen.

    ⚠ MEHRERE TREFFER SIND EIN FEHLER, KEINE AUSWAHL (gemessen 2026-08-30).
    Wer neben einem bestehenden Zugang einen zweiten hinterlegt, bekam bis dahin
    weiter den ALTEN: die Liste war alphabetisch sortiert und der erste nicht
    leere Treffer gewann – `.jarvis-csa-key` steht vor `.fabrikam-csa-key`. Der
    neue Schluessel lag daneben und tat NICHTS, ohne eine einzige Meldung.
    Schlimmer ist die halbe Wahl: Schluessel und Adresse werden getrennt
    ermittelt, ein Zugang koennte also den Schluessel des einen Servers an den
    anderen schicken – der antwortet 401, und das sieht wie ein kaputter
    Schluessel aus statt wie eine falsche Adresse. Deshalb fail-closed mit
    Klartext, der beide Wege aus der Zwickmuehle nennt.
    """
    end = endung.upper()
    aus_env = sorted(n for n, w in os.environ.items()
                     if n.upper().endswith("_CSA_" + end) and w.strip())
    if len(aus_env) > 1:
        fehler(f"Mehrere Umgebungsvariablen fuer {was}: {', '.join(aus_env)}. "
               f"Es ist nicht erkennbar, welche Installation gemeint ist – "
               f"setze genau eine.", 2)
    if aus_env:
        return os.environ[aus_env[0]].strip()
    treffer = [p for p in sorted(Path.home().glob(".*-csa-" + endung.lower()))
               if p.read_text(encoding="utf-8").strip()]
    if len(treffer) > 1:
        namen = ", ".join("~/" + p.name for p in treffer)
        fehler(f"Mehrere Zugaenge fuer {was} hinterlegt: {namen}. Es ist nicht "
               f"erkennbar, welche Installation gemeint ist. Benenne die nicht "
               f"gewuenschte um (ein Name, der nicht auf '-csa-{endung.lower()}' "
               f"endet, wird nicht mehr gefunden) oder waehle die gewuenschte "
               f"per Umgebungsvariable <MARKE>_CSA_{end}.", 2)
    return treffer[0].read_text(encoding="utf-8").strip() if treffer else ""


def schluessel() -> str:
    k = _aus_umgebung_oder_datei("key", "Schluessel")
    if k:
        return k
    fehler("Kein Delegations-Schluessel. Setze <MARKE>_CSA_KEY oder lege "
           "~/.<marke>-csa-key an – <MARKE> ist der Name des Assistenten aus "
           "dem Branding (steht im Bereich /claude in der Anleitung).", 2)


def basis_url() -> str:
    u = _aus_umgebung_oder_datei("url", "Adresse")
    if not u:
        fehler("Keine Server-Adresse. Setze <MARKE>_CSA_URL oder lege "
               "~/.<marke>-csa-url an – <MARKE> ist der Name des Assistenten "
               "aus dem Branding (steht im Bereich /claude in der Anleitung). "
               "Es gibt bewusst keine Vorgabe: der Client laeuft gegen jede "
               "Installation.", 2)
    if u.lower().startswith("http://"):
        # Der Schluessel geht in JEDER Anfrage im Kopf mit – ueber http liest
        # ihn jeder im Netzpfad mit (Befund 2026-11-27). Kein Rueckfall.
        fehler("Die Server-Adresse beginnt mit http:// – der Delegations-"
               "Schluessel ginge unverschluesselt ueber das Netz. Trage die "
               "https://-Adresse ein.", 2)
    if not u.lower().startswith("https://"):
        u = "https://" + u
    return u.rstrip("/")


# ── Serverzertifikat (Befund 2026-11-27) ──────────────────────────────────
# Bis hierher lief jede Verbindung mit CERT_NONE: wer im Netzpfad sass, las den
# Delegations-Schluessel aus dem Kopf X-Jarvis-Key und konnte damit Code-
# Auftraege im Namen des Benutzers starten. Jetzt dieselbe Regel wie im
# Windows-Client (windows-app-go/tlsvertrauen, BSI M11):
#
#   1. Normal pruefen – Vertrauensspeicher des Systems (Firmen-CA) und Name.
#   2. Scheitert das (selbst ausgestelltes Zertifikat, Zugriff per IP), gilt
#      NUR ein ausdruecklich bestaetigter SHA-256-Fingerabdruck. Er liegt neben
#      Schluessel und Adresse: <MARKE>_CSA_CERT oder ~/.<marke>-csa-cert,
#      bestaetigt ueber `delegiere.py vertrauen`.
#   3. Ohne Bestaetigung oder bei abweichendem Fingerabdruck: Abbruch, BEVOR
#      der Schluessel gesendet wird. Die Pruefung laeuft auf DERSELBEN
#      Verbindung, ueber die danach die Anfrage geht.

def fingerabdruck(der: bytes) -> str:
    """SHA-256 des ganzen Zertifikats, AA:BB:… (wie Browser und openssl)."""
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _norm_fp(fp: str) -> str:
    return "".join(ch for ch in (fp or "").upper() if ch in "0123456789ABCDEF")


def _ziel() -> tuple:
    """(host, port, pfadpraefix) der Server-Adresse."""
    u = urllib.parse.urlsplit(basis_url())
    if not u.hostname:
        fehler(f"Server-Adresse ohne Rechnernamen: {basis_url()}", 2)
    return u.hostname, u.port or 443, u.path.rstrip("/")


def _oeffne(ctx: ssl.SSLContext) -> http.client.HTTPSConnection:
    host, port, _ = _ziel()
    c = http.client.HTTPSConnection(host, port, context=ctx, timeout=60)
    c.connect()
    return c


def _ungeprueft() -> ssl.SSLContext:
    """NUR fuer den Weg ueber den Fingerabdruck – geprueft wird danach von Hand."""
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _pin_datei() -> Path:
    """Ablage des bestaetigten Fingerabdrucks – gleicher Stamm wie die Adresse.

    Kam die Adresse aus ``FOO_CSA_URL``, heisst die Datei ``~/.foo-csa-cert``;
    kam sie aus ``~/.foo-csa-url``, ebenso. So findet ``_aus_umgebung_oder_datei``
    sie mit demselben Muster wieder, und mehrere Zugaenge bleiben getrennt."""
    for n, w in os.environ.items():
        if n.upper().endswith("_CSA_URL") and w.strip():
            return Path.home() / ("." + n[:-len("_CSA_URL")].lower() + "-csa-cert")
    for p in sorted(Path.home().glob(".*-csa-url")):
        if p.read_text(encoding="utf-8").strip():
            return p.with_name(p.name[:-len("url")] + "cert")
    fehler("Keine Server-Adresse hinterlegt – zuerst <MARKE>_CSA_URL bzw. "
           "~/.<marke>-csa-url setzen.", 2)


def verbindung() -> http.client.HTTPSConnection:
    """Gepruefte Verbindung zum Server oder Abbruch (vor jedem Senden)."""
    try:
        return _oeffne(ssl.create_default_context())
    except ssl.SSLCertVerificationError as e:
        grund = e.verify_message or str(e)
    except (OSError, ssl.SSLError) as e:
        fehler(f"Verbindung zu {basis_url()} gescheitert: {type(e).__name__}: {e}")
    try:
        c = _oeffne(_ungeprueft())
    except (OSError, ssl.SSLError) as e:
        fehler(f"Verbindung zu {basis_url()} gescheitert: {type(e).__name__}: {e}")
    fp = fingerabdruck(c.sock.getpeercert(binary_form=True) or b"")
    pin = _norm_fp(_aus_umgebung_oder_datei("cert", "Zertifikat-Fingerabdruck"))
    if not pin:
        c.close()
        fehler(f"Das Zertifikat von {basis_url()} ist nicht vertrauenswuerdig "
               f"({grund}) und nicht bestaetigt.\n"
               f"  Fingerabdruck (SHA-256): {fp}\n"
               f"Vergleiche ihn mit dem Zertifikat, das dein Browser fuer diese "
               f"Adresse zeigt (Schloss-Symbol), und bestaetige ihn mit:\n"
               f"  python3 deploy/claude_subagent/delegiere.py vertrauen\n"
               f"Der Schluessel wurde NICHT gesendet.", 3)
    if not hmac.compare_digest(pin, _norm_fp(fp)):
        c.close()
        fehler(f"Das Zertifikat von {basis_url()} weicht vom bestaetigten ab – "
               f"jemand koennte die Verbindung umleiten.\n"
               f"  bestaetigt: {_fmt_fp(pin)}\n"
               f"  vorgelegt:  {fp}\n"
               f"Wurde das Serverzertifikat erneuert, pruefe den neuen "
               f"Fingerabdruck im Browser und bestaetige ihn mit "
               f"`delegiere.py vertrauen`. Der Schluessel wurde NICHT gesendet.", 3)
    return c


def _fmt_fp(roh: str) -> str:
    return ":".join(roh[i:i + 2] for i in range(0, len(roh), 2))


def ruf(pfad: str, methode: str = "GET", rumpf: dict | None = None) -> dict:
    daten = json.dumps(rumpf).encode("utf-8") if rumpf is not None else None
    kopf = {"X-Jarvis-Key": schluessel()}
    if daten:
        kopf["Content-Type"] = "application/json"
    _, _, praefix = _ziel()
    c = verbindung()
    try:
        c.request(methode, praefix + pfad, body=daten, headers=kopf)
        r = c.getresponse()
        roh = r.read().decode("utf-8", "replace")
        status = r.status
    except (OSError, http.client.HTTPException) as e:
        fehler(f"{type(e).__name__}: {e}")
    finally:
        c.close()
    try:
        return json.loads(roh)
    except ValueError:
        if 200 <= status < 300:
            fehler(f"Antwort ist kein JSON (HTTP {status})")
        return {"ok": False, "error": f"HTTP {status}"}


def cmd_vertrauen(a) -> None:
    """Fingerabdruck des Servers anzeigen und nach Bestaetigung hinterlegen.

    Nicht automatisch beim ersten Kontakt (trust on first use): sonst wuerde
    genau der erste Abruf durch einen Angreifer dessen Zertifikat verankern.
    Bestaetigt wird interaktiv oder mit ``--fingerabdruck`` (aus dem Browser
    abgeschrieben) – beides vergleicht mit dem, was der Server vorlegt."""
    try:
        _oeffne(ssl.create_default_context()).close()
        print(f"Das Zertifikat von {basis_url()} wird bereits vom System als "
              f"vertrauenswuerdig erkannt – keine Bestaetigung noetig.")
        return
    except ssl.SSLCertVerificationError as e:
        grund = e.verify_message or str(e)
    except (OSError, ssl.SSLError) as e:
        fehler(f"Verbindung zu {basis_url()} gescheitert: {type(e).__name__}: {e}")
    try:
        c = _oeffne(_ungeprueft())
    except (OSError, ssl.SSLError) as e:
        fehler(f"Verbindung zu {basis_url()} gescheitert: {type(e).__name__}: {e}")
    fp = fingerabdruck(c.sock.getpeercert(binary_form=True) or b"")
    c.close()
    print(f"Server:        {basis_url()}")
    print(f"Pruefung:      {grund}")
    print(f"Fingerabdruck: {fp}  (SHA-256)")
    if a.fingerabdruck:
        if not hmac.compare_digest(_norm_fp(a.fingerabdruck), _norm_fp(fp)):
            fehler("Der angegebene Fingerabdruck stimmt NICHT mit dem vorgelegten "
                   "Zertifikat ueberein – nichts hinterlegt.", 3)
    else:
        if not sys.stdin.isatty():
            fehler("Keine Eingabe moeglich. Bestaetige mit --fingerabdruck "
                   "<AA:BB:…> (aus dem Zertifikat im Browser abgeschrieben).", 2)
        antwort = input("Stimmt er mit dem Fingerabdruck im Browser ueberein? "
                        "[ja/nein] ").strip().lower()
        if antwort not in ("ja", "j", "yes", "y"):
            fehler("Nicht bestaetigt – nichts hinterlegt.", 3)
    ziel = _pin_datei()
    alt = os.umask(0o077)
    try:
        ziel.write_text(fp + "\n", encoding="utf-8")
    finally:
        os.umask(alt)
    print(f"Hinterlegt in {ziel}.")


def git(*args) -> str:
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    return (p.stdout or "").strip()


def git_ok(*args) -> bool:
    """Nur der Exitcode zaehlt (fuer Existenzfragen wie `cat-file -e`)."""
    return subprocess.run(["git", *args], capture_output=True,
                          text=True).returncode == 0


def pruefe_riegel(riegel: str) -> None:
    """Der Riegel muss im GEPUSHTEN Stand liegen, nicht nur im Arbeitsbaum.

    DAS HAT EINEN LAUF GEKOSTET (2026-08-25): ein frisch geschriebener, noch
    nicht committeter Waechter existiert im Klon des Servers nicht. Der Lauf
    laeuft trotzdem an, der Agent arbeitet, und erst die Bewertung meldet
    "Riegel existiert im Arbeitsbereich nicht" – Ergebnis: kein Patch, und nach
    der Abbruchregel macht man die Aufgabe danach selbst. Die Vorbedingung
    gehoert VOR den Lauf.

    Zweiter Fall, subtiler: der Riegel ist committet, aber lokal GEAENDERT. Dann
    prueft der Server die alte Fassung – und ein gruener Riegel beweist etwas
    anderes als das, was man gerade geschrieben hat.
    """
    if not riegel:
        return
    if not git_ok("cat-file", "-e", f"origin/master:{riegel}"):
        fehler(f"Der Riegel '{riegel}' liegt nicht in origin/master. Der Server "
               f"klont von dort und findet ihn nicht – der Lauf wuerde ohne "
               f"Patch enden. Committe und pushe ihn zuerst.")
    stand = git("status", "--porcelain", "--", riegel).strip()
    if stand:
        fehler(f"Der Riegel '{riegel}' ist lokal geaendert, aber nicht gepusht. "
               f"Geprueft wuerde die Fassung aus origin/master – ein gruener "
               f"Riegel bewiese dann etwas anderes als das, was du geschrieben "
               f"hast. Pushe die Aenderung zuerst.")


def pruefe_arbeitsbaum(dateien: list) -> str:
    """Basis-Commit ermitteln und sicherstellen, dass der Patch spaeter passt."""
    kopf = git("rev-parse", "HEAD")
    if not kopf:
        fehler("Kein git-Repository im aktuellen Verzeichnis.")
    # Liegt der lokale Stand auf origin/master? Der Server klont von dort.
    vor = git("rev-list", "--count", "origin/master..HEAD")
    if vor and vor != "0":
        fehler(f"Der lokale Stand liegt {vor} Commit(s) VOR origin/master. "
               f"Jarvis klont origin/master – pushe zuerst, oder delegiere nicht.")
    schmutzig = [z[3:] for z in git("status", "--porcelain").splitlines()]
    kollision = [d for d in dateien if any(s.strip() == d for s in schmutzig)]
    if kollision:
        fehler("Diese Zieldateien haben lokale Aenderungen – der Patch liesse "
               "sich nachher nicht sauber anwenden: " + ", ".join(kollision))
    return kopf


def cmd_senden(a) -> None:
    spec = Path(a.spec_datei).read_text(encoding="utf-8") if a.spec_datei else a.spec
    if not spec or not spec.strip():
        fehler("Kein Auftragstext (--spec oder --spec-datei).")
    dateien = [x.strip() for x in a.dateien.split(",") if x.strip()]
    if not dateien:
        fehler("--dateien fehlt: nenne die Dateien, die geaendert werden duerfen.")
    pruefe_riegel(a.riegel)
    basis = a.basis or pruefe_arbeitsbaum(dateien)

    antwort = ruf("/api/claude/jobs", "POST", {
        "spec": spec, "basis": basis, "dateien": dateien, "riegel": a.riegel,
    })
    if not antwort.get("ok"):
        fehler(antwort.get("error", "unbekannt"))
    print(antwort["id"])


def _bericht(job: dict) -> int:
    """Ergebnis ausgeben. Rueckgabe = Exitcode (0 nur bei angenommenem Patch)."""
    erg = job.get("ergebnis") or {}
    print(f"# Auftrag {job.get('id')} – {job.get('status')}", file=sys.stderr)
    if job.get("fehler"):
        print(f"# Fehler: {job['fehler']}", file=sys.stderr)
        return 1
    if not erg:
        return 1
    print(f"# Riegel {erg.get('riegel')}: "
          f"{'GRUEN' if erg.get('riegel_ok') else 'ROT'}", file=sys.stderr)
    print(f"# Dateien: {', '.join(erg.get('dateien') or []) or '(keine)'}", file=sys.stderr)
    if not erg.get("angenommen"):
        print("# VERWORFEN:", file=sys.stderr)
        for g in erg.get("gruende") or []:
            print(f"#   - {g}", file=sys.stderr)
        aus = (erg.get("riegel_ausgabe") or "").strip()
        if aus:
            # ⚠ HIER STANDEN EINMAL NUR DIE LETZTEN 15 ZEILEN – und die
            # fehlgeschlagenen Pruefungen stehen fast nie am Ende. Am 2026-08-31
            # zeigte der Bericht ausschliesslich gruene Haken, waehrend unten
            # "12 OK, 2 FAIL" stand: die zwei ✗-Zeilen lagen in Abschnitt 2 und
            # waren abgeschnitten. Die Ursache war danach nur durch Nachstellen
            # des Laufs zu finden – eine halbe Stunde fuer eine Auskunft, die
            # der Bericht haette geben koennen.
            #
            # Deshalb ZUERST die Fehlzeilen, dann der Schluss. Erkannt an den
            # ueblichen Markierungen der Waechter dieses Projekts (✗, FAIL,
            # ✗ mit Farbcode davor) – reicht keine, bleibt es beim Ende.
            zeilen = aus.splitlines()
            schlecht = [z for z in zeilen
                        if "✗" in z or "FAIL " in z or z.strip().startswith("FAIL")]
            if schlecht:
                print(f"# Riegel-Ausgabe – FEHLGESCHLAGENE Pruefungen "
                      f"({len(schlecht)}):", file=sys.stderr)
                for z in schlecht[:25]:
                    print(f"#   {z}", file=sys.stderr)
                if len(schlecht) > 25:
                    print(f"#   … und {len(schlecht) - 25} weitere",
                          file=sys.stderr)
                print("# Riegel-Ausgabe (Schluss):", file=sys.stderr)
                for z in zeilen[-5:]:
                    print(f"#   {z}", file=sys.stderr)
            else:
                print("# Riegel-Ausgabe (letzte Zeilen):", file=sys.stderr)
                for z in zeilen[-15:]:
                    print(f"#   {z}", file=sys.stderr)
        return 1
    print("# ANGENOMMEN – Patch folgt auf stdout", file=sys.stderr)
    print(erg.get("diff") or "")
    return 0


def cmd_holen(a) -> None:
    antwort = ruf(f"/api/claude/jobs/{a.id}")
    if not antwort.get("ok"):
        fehler(antwort.get("error", "unbekannt"))
    sys.exit(_bericht(antwort["job"]))


def cmd_warten(a) -> None:
    ende = time.time() + a.timeout
    while time.time() < ende:
        antwort = ruf(f"/api/claude/jobs/{a.id}")
        if not antwort.get("ok"):
            fehler(antwort.get("error", "unbekannt"))
        job = antwort["job"]
        if job.get("status") in ("fertig", "fehler"):
            sys.exit(_bericht(job))
        time.sleep(a.takt)
    fehler(f"Auftrag {a.id} ist nach {a.timeout}s noch nicht fertig.")


def cmd_bericht(a) -> None:
    """Was die Delegation gekostet und gespart hat – aus GEMESSENEN Zeichen.

    Die Rechnung steht im Kopf von ``backend/claude_subagent.py``:
        ohne Delegation ~ Quelldateien lesen + Patch schreiben
        mit  Delegation ~ Auftrag schreiben  + Patch lesen
        Ersparnis       ~ Quelle - Auftrag
    Der Patch faellt heraus, er geht in beiden Faellen durch Claude.

    Ein ABGELEHNTER Auftrag ist ein Kostenpunkt, kein Nullwert: die
    Spezifikation wurde geschrieben und die Aufgabe danach selbst gemacht. Er
    zaehlt deshalb mit NEGATIVEM Beitrag.
    """
    antwort = ruf("/api/claude/jobs")
    jobs = antwort.get("jobs") or []
    zjt = float(antwort.get("zeichen_je_token") or 3.6)
    if not jobs:
        print("Noch kein Auftrag abgegeben – es gibt nichts zu berichten.")
        return

    print(f"{'Zeit':<12} {'Kennung':<13} {'St':<3} {'Dat':>4} "
          f"{'Auftrag':>9} {'Quelle':>9} {'Patch':>8} {'Bilanz':>9}  Riegel")
    print("-" * 100)
    sp = qu = pa = 0
    ang = abg = 0
    for j in jobs[::-1]:
        m = j.get("messwerte") or {}
        if not m:
            continue                      # Altbestand vor der Buchhaltung
        ok = bool(m.get("angenommen"))
        # Bei Ablehnung ist die Quelle NICHT gespart – die Arbeit fiel trotzdem an.
        bilanz = (m.get("quelle_zeichen", 0) if ok else 0) - m.get("spec_zeichen", 0)
        sp += m.get("spec_zeichen", 0)
        qu += m.get("quelle_zeichen", 0) if ok else 0
        pa += m.get("patch_zeichen", 0)
        ang += 1 if ok else 0
        abg += 0 if ok else 1
        zeit = time.strftime("%d.%m %H:%M", time.localtime(j.get("erstellt", 0)))
        riegel = j.get("riegel")
        riegel = riegel if isinstance(riegel, str) else ",".join(riegel or [])
        print(f"{zeit:<12} {j.get('id',''):<13} {'OK ' if ok else 'ABL':<3} "
              f"{m.get('dateien_anzahl',0):>4} "
              f"{m.get('spec_zeichen',0):>9,} {m.get('quelle_zeichen',0):>9,} "
              f"{m.get('patch_zeichen',0):>8,} {bilanz:>+9,}  {riegel.split('/')[-1]}")

    bilanz = qu - sp
    print("-" * 100)
    print(f"{ang + abg} Auftraege: {ang} angenommen, {abg} abgelehnt")
    print(f"Auftragstexte (gezahlt):        {sp:>12,} Zeichen  ~{sp/zjt:>10,.0f} Token")
    print(f"Quelldateien (nicht gelesen):   {qu:>12,} Zeichen  ~{qu/zjt:>10,.0f} Token")
    print(f"Patches (in beiden Faellen):    {pa:>12,} Zeichen  ~{pa/zjt:>10,.0f} Token")
    print(f"BILANZ:                         {bilanz:>+12,} Zeichen  ~{bilanz/zjt:>+10,.0f} Token")
    print()
    print("Gemessen sind die ZEICHEN; die Token sind daraus geschaetzt "
          f"({zjt} Zeichen/Token).")
    print("VORBEHALT: die Ersparnis gilt nur, soweit die Dateien vorher NICHT "
          "gelesen wurden.")
    print("Wer erst lesen muss, um den Auftrag zu schreiben, hat sie schon "
          "ausgegeben.")


def main() -> None:
    p = argparse.ArgumentParser(description="Codeaufgabe an Jarvis abgeben")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("senden")
    s.add_argument("--spec")
    s.add_argument("--spec-datei")
    s.add_argument("--dateien", required=True,
                   help="kommagetrennt, relativ zum Repo")
    s.add_argument("--riegel", required=True,
                   help="Testdatei, die das Ergebnis beweist (tests/*.py|js)")
    s.add_argument("--basis", help="Commit-Hash (Vorgabe: HEAD des Arbeitsbaums)")
    s.set_defaults(fn=cmd_senden)

    h = sub.add_parser("holen")
    h.add_argument("id")
    h.set_defaults(fn=cmd_holen)

    w = sub.add_parser("warten")
    w.add_argument("id")
    w.add_argument("--timeout", type=int, default=900)
    w.add_argument("--takt", type=int, default=10)
    w.set_defaults(fn=cmd_warten)

    b = sub.add_parser("bericht", help="Kosten und Ersparnis aller Auftraege")
    b.set_defaults(fn=cmd_bericht)

    v = sub.add_parser("vertrauen",
                       help="Serverzertifikat per Fingerabdruck bestaetigen "
                            "(nur noetig, wenn das System ihm nicht vertraut)")
    v.add_argument("--fingerabdruck",
                   help="SHA-256 aus dem Browser (AA:BB:…) – statt der Rueckfrage")
    v.set_defaults(fn=cmd_vertrauen)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

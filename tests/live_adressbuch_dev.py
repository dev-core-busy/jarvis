#!/usr/bin/env python3
"""Live-Probe auf DEV: Adressbuch-Suche gegen das ECHTE Exchange.

Was eine Einheitenprobe hier NICHT beantworten kann: ob ``ResolveNames`` auf
dem Server dieses Hauses wirklich antwortet, welche Postfacharten dabei
zurueckkommen und ob die Zugangsdaten reichen. Genau das misst diese Probe.

⚠ SIE MELDET SICH AM EXCHANGE AN. Das ist EIN Anmeldeversuch je Lauf – wie ein
Klick auf "Verbindung testen". Mehr darf es nicht werden: drei Fehlversuche
sperren das Domaenenkonto (siehe ``mail_accounts.MAX_ANMELDEFEHLER``). Die
Probe bricht deshalb ab, wenn das Postfach schon Fehlversuche zaehlt oder
ausgesetzt ist – sie legt NICHT den dritten drauf.

⚠ SIE VERAENDERT EINEN ZUSTAND, und das ist unvermeidlich: eine gelungene
Suche vermerkt ``letzter_erfolg`` am Konto (``merke_ergebnis``). Das ist die
WAHRHEIT ueber einen Vorgang, der wirklich stattgefunden hat – es
zurueckzudrehen waere die Faelschung, nicht die Wiederherstellung. Alles
andere bleibt unberuehrt.

Auf dem Server MIT Hauptschluessel starten, sonst sind die Kennwoerter nur
verpackt lesbar (BSI M5):

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_adressbuch_dev.py

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0
_bilanz = False


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def bilanz():
    global _bilanz
    _bilanz = True
    print("\n" + "=" * 62)
    print(f"Ergebnis: {_ok} ok, {_fail} fehlgeschlagen")
    print("=" * 62)


def abbruch(grund: str):
    print(f"ABBRUCH: {grund}")
    if _ok or _fail:
        bilanz()
    sys.exit(2)


try:
    from backend import adressbuch, mail_accounts
    from backend.mail_client import MailFehler
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht importierbar: {type(e).__name__}: {e}")

# ── Welches Postfach? Das einzige hinterlegte, nicht eines geraten ──────────
try:
    konten = mail_accounts.alle_konten() if hasattr(mail_accounts, "alle_konten") \
        else mail_accounts._laden()
except Exception as e:  # noqa: BLE001
    abbruch(f"Kontenliste nicht lesbar: {e}")

kandidaten = [(u, k) for u, k in (konten or {}).items()
              if k.get("pw_enc") and k.get("aktiv", True)]
if not kandidaten:
    abbruch("kein aktives Postfach mit Kennwort hinterlegt – ohne Konto ist "
            "der EWS-Weg nicht messbar")
benutzer, konto = kandidaten[0]

# ⚠ Schranke gegen den dritten Fehlversuch: lieber nicht messen als ein
# Domaenenkonto sperren.
if konto.get("ausgesetzt"):
    abbruch("das Postfach ist ausgesetzt – diese Probe legt keinen weiteren "
            "Anmeldeversuch drauf")
fehler_vorher = int(konto.get("anmeldefehler", 0) or 0)
if fehler_vorher:
    abbruch(f"das Postfach zaehlt schon {fehler_vorher} Anmeldefehler – "
            "diese Probe legt keinen weiteren drauf")

print(f"Postfach: {mail_accounts.norm_user(benutzer)[:3]}… (Name gekuerzt)\n")

# ── 0. DER KALTE WEG – und zwar als ERSTES ──────────────────────────────────
# ⚠ DIESE REIHENFOLGE IST DER KERN DER PROBE. Im Betrieb baut jede Anfrage
# einen FRISCHEN MailClient, die Adressbuch-Suche ist dort also die ERSTE
# Operation der Verbindung. Jede andere Operation (test, Ordnerliste) ermittelt
# als Nebenwirkung die Serverfassung, die `ResolveNames` braucht – eine Probe,
# die zuerst die Verbindung testet, bekommt sie geschenkt und sieht den Fehler
# NIE. Genau so ist er am 2026-10-23 fast durchgerutscht: in-Prozess gruen,
# ueber HTTP Rueckfall aufs Verzeichnis mit "'NoneType' object has no
# attribute 'api_version'".
#
# Deshalb steht der kalte Lauf VOR allem anderen. Scheitert er, ist das ein
# FAIL (Befund) und kein Abbruch – ob der Kanal grundsaetzlich steht, sagt
# Abschnitt 1 danach.
print("0. Kalter Lauf: Suche als ERSTE Operation einer frischen Verbindung")
_eigene_vorab = str(konto.get("adresse") or "").strip()
_frage_vorab = (_eigene_vorab.split("@")[0].split(".")[0]
                if "@" in _eigene_vorab else "")
if len(_frage_vorab) < adressbuch.MIN_FRAGE:
    abbruch("am Konto steht keine brauchbare Adresse – ohne bekannte Antwort "
            "ist der kalte Lauf nicht deutbar")
try:
    from backend.mail_client import MailClient as _MC
    _c = _MC(mail_accounts.konto_fuer(benutzer, trotz_aussetzer=True))
    try:
        _kalt = _c.adressen_suchen(_frage_vorab, limit=5)
    finally:
        _c.schliessen()
except Exception as e:  # noqa: BLE001
    pruefe(False, "die Suche gelingt OHNE vorherige Operation "
                  "(Serverfassung wird selbst ermittelt)",
           f"{type(e).__name__}: {e}")
else:
    pruefe(bool(_kalt), f"die Suche gelingt OHNE vorherige Operation "
           f"({len(_kalt)} Treffer)", str(_kalt)[:120])

# ── 1. Positivkontrolle: antwortet der Kanal ueberhaupt? ────────────────────
# Ohne sie ist ein leeres Suchergebnis nicht deutbar ("niemand dieses Namens"
# gegen "der Kanal steht nicht").
print("1. Positivkontrolle: steht der Kanal?")
try:
    from backend.mail_client import MailClient
    c = MailClient(mail_accounts.konto_fuer(benutzer, trotz_aussetzer=True))
    try:
        t = c.test()
    finally:
        c.schliessen()
except MailFehler as f:
    abbruch(f"Verbindungstest scheitert ({f.kategorie}): {f}")
except Exception as e:  # noqa: BLE001
    abbruch(f"Verbindungstest scheitert: {type(e).__name__}: {e}")
pruefe(t.get("ok") is True, "Verbindungstest gelingt", str(t)[:100])
pruefe(t.get("kanal") == "ews",
       "und zwar ueber EWS (nur dort gibt es ein Adressbuch)", str(t.get("kanal")))
if t.get("kanal") != "ews":
    abbruch("ohne EWS-Kanal ist ResolveNames nicht messbar – auf diesem "
            "Server laeuft das Postfach ueber IMAP")

# ── 2. Die eigene Adresse aufloesen ─────────────────────────────────────────
# Die einzige Frage, deren ANTWORT im Voraus bekannt ist: der Vorname des
# eigenen Postfachs muss die eigene Adresse finden. Eine Probe mit einem
# geratenen Fremdnamen koennte leer bleiben, ohne dass das etwas bedeutet.
eigene = str(konto.get("adresse") or "").strip()
if "@" not in eigene:
    abbruch("am Konto steht keine Adresse – die Probe braucht eine bekannte "
            "Antwort, sonst ist ein leeres Ergebnis nicht deutbar")
lokal = eigene.split("@")[0]
frage = lokal.split(".")[0] if "." in lokal else lokal[:4]
if len(frage) < adressbuch.MIN_FRAGE:
    abbruch(f"der abgeleitete Suchbegriff {frage!r} ist kuerzer als "
            f"MIN_FRAGE={adressbuch.MIN_FRAGE}")

print(f"\n2. Suche nach {frage!r} (soll die eigene Adresse finden)")
try:
    res = adressbuch.suchen(benutzer, frage)
except adressbuch.AdressbuchFehler as e:
    abbruch(f"die Suche konnte nicht laufen: {e}")
except Exception as e:  # noqa: BLE001
    pruefe(False, "die Suche laeuft ohne Ausnahme", f"{type(e).__name__}: {e}")
    bilanz()
    sys.exit(1)

pruefe(res.get("quelle") == "ews",
       "die Antwort kommt aus dem Exchange-Adressbuch", str(res.get("quelle")))
treffer = res.get("treffer") or []
pruefe(bool(treffer), f"es gibt mindestens einen Treffer ({len(treffer)})",
       str(res)[:160])
adressen = {str(x.get("adresse") or "").lower() for x in treffer}
pruefe(eigene.lower() in adressen,
       "die eigene Adresse ist darunter (die bekannte Antwort)",
       f"{len(adressen)} Adressen, eigene nicht dabei")
pruefe(all("@" in str(x.get("adresse") or "") for x in treffer),
       "JEDER Treffer traegt eine brauchbare Adresse (kein X500-Pfad)",
       str([x.get("adresse") for x in treffer])[:160])
pruefe(all(str(x.get("name") or "").strip() for x in treffer),
       "jeder Treffer traegt einen Namen")
pruefe(all(x.get("art") in ("person", "verteiler", "kontakt", "unbekannt")
           for x in treffer),
       "jede Art ist eine der vier bekannten",
       str(sorted({x.get("art") for x in treffer})))
pruefe(len(adressen) == len(treffer),
       "keine Adresse kommt doppelt vor", f"{len(treffer)} Treffer, "
       f"{len(adressen)} verschiedene Adressen")
print("   Arten im Ergebnis: %s" % sorted({x.get("art") for x in treffer}))

# ── 3. Deckel wirkt auch am echten Server ───────────────────────────────────
print("\n3. Deckel am echten Ergebnis")
try:
    res1 = adressbuch.suchen(benutzer, frage, 1)
except Exception as e:  # noqa: BLE001
    pruefe(False, "Suche mit Limit 1 laeuft", f"{type(e).__name__}: {e}")
else:
    pruefe(len(res1.get("treffer") or []) <= 1,
           "Limit 1 liefert hoechstens einen Treffer",
           str(len(res1.get("treffer") or [])))

# ── 4. Ein Name, den es nicht gibt: LEER, nicht Fehler ──────────────────────
print("\n4. Ein Name, den es sicher nicht gibt")
try:
    leer = adressbuch.suchen(benutzer, "zzqxwvutsrq")
except adressbuch.AdressbuchFehler as e:
    pruefe(False, "ein unbekannter Name ergibt ein LEERES Ergebnis, keinen "
                  "Fehler", str(e)[:100])
else:
    pruefe((leer.get("treffer") or []) == [],
           "ein unbekannter Name ergibt eine leere Trefferliste",
           str(leer)[:120])
    pruefe(leer.get("quelle") == "ews",
           "und sie kommt nachweislich aus dem Adressbuch (nicht vom Rueckfall)",
           str(leer.get("quelle")))

# ── 5. Der Zustand des Kontos ist nicht beschaedigt ─────────────────────────
print("\n5. Zustand des Postfachs nach der Probe")
try:
    nach = (mail_accounts._laden() or {}).get(benutzer, {})
except Exception as e:  # noqa: BLE001
    nach = {}
    print(f"   (Kontenliste nicht erneut lesbar: {e})")
pruefe(int(nach.get("anmeldefehler", 0) or 0) == 0,
       "das Konto zaehlt keine Anmeldefehler", str(nach.get("anmeldefehler")))
pruefe(not nach.get("ausgesetzt"),
       "das Konto ist nicht ausgesetzt", str(nach.get("ausgesetzt")))
pruefe(bool(nach.get("letzter_erfolg")),
       "der Erfolg ist vermerkt (erwartete, gewollte Zustandsaenderung)")

# ── 6. Der Endpunkt ueber HTTPS ─────────────────────────────────────────────
# Die Funktion zu pruefen ist nicht dasselbe wie den Weg zu pruefen: Dependency
# (Freigabe), Koerper-Auswertung und Antwortform haengen am Endpunkt.
print("\n6. POST /api/email/adressbuch")
try:
    import json as _json
    import ssl as _ssl
    import urllib.error as _ue
    import urllib.request as _ur
    from backend import main as _M
except Exception as e:  # noqa: BLE001
    print(f"   (uebersprungen: {type(e).__name__}: {e})")
else:
    _ktx = _ssl._create_unverified_context()

    def _post(koerper, token):
        kopf = {"Content-Type": "application/json"}
        if token:
            kopf["Authorization"] = "Bearer " + token
        req = _ur.Request("https://127.0.0.1/api/email/adressbuch",
                          data=_json.dumps(koerper).encode("utf-8"),
                          headers=kopf, method="POST")
        try:
            with _ur.urlopen(req, timeout=60, context=_ktx) as a:
                return a.status, _json.loads(a.read().decode("utf-8") or "{}")
        except _ue.HTTPError as h:
            roh = h.read().decode("utf-8", "replace")
            try:
                return h.code, _json.loads(roh or "{}")
            except Exception:  # noqa: BLE001
                return h.code, {"roh": roh[:200]}

    # Positivkontrolle ZUERST: ohne 200 sind die inhaltlichen Pruefungen
    # trivial wahr (eine leere Antwort erfuellt jede Formbedingung).
    code, d = _post({"q": frage}, _M.generate_token(benutzer))
    pruefe(code == 200, f"Positivkontrolle: der Endpunkt antwortet 200 ({code})",
           str(d)[:160])
    if code == 200:
        pruefe(d.get("ok") is True, "ok=True", str(d)[:120])
        # ⚠ Der HINWEIS gehoert in die Begruendung: er traegt den Grund, aus
        # dem der Exchange-Weg im DIENST nicht gegriffen hat. Ohne ihn stand
        # hier nur "ad" – das ist das Symptom, nicht die Ursache.
        pruefe(d.get("quelle") == "ews", "quelle=ews",
               "quelle=%s | hinweis=%s" % (d.get("quelle"), d.get("hinweis")))
        tr = d.get("treffer") or []
        pruefe(bool(tr), f"Treffer ueber HTTP ({len(tr)})", str(d)[:160])
        pruefe(all(set(x) >= {"name", "adresse", "art"} for x in tr),
               "jeder Treffer hat name/adresse/art",
               str(tr[:1])[:160])
        pruefe(eigene.lower() in {str(x.get("adresse") or "").lower() for x in tr},
               "die eigene Adresse kommt auch ueber HTTP")

    # Eine zu kurze Frage ist ein ERGEBNIS mit Begruendung, kein Fehler.
    code, d = _post({"q": "a"}, _M.generate_token(benutzer))
    pruefe(code == 200 and (d.get("treffer") or []) == [] and bool(d.get("hinweis")),
           "zu kurze Frage: 200 mit leerer Liste UND Begruendung", f"{code} {d}")

    # OHNE Token: die Freigabe des Bereichs traegt (kein Adressbuch fuer jeden)
    code, d = _post({"q": frage}, None)
    pruefe(code in (401, 403),
           f"ohne Sitzungstoken abgewiesen ({code})", str(d)[:120])

bilanz()
sys.exit(0 if _fail == 0 else 1)

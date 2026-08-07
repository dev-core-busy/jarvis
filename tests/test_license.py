#!/usr/bin/env python3
"""Tests der Lizenzierung (backend/license.py + license_enforce.py).

Laeuft ohne fastapi: `backend.config` wird durch einen Stub ersetzt, bevor
irgendetwas importiert wird. Das ist keine Bequemlichkeit – der echte Import
migriert beim Laden Profile und SCHREIBT die Live-`settings.json` zurueck
(siehe `_load_v2`), ein Testlauf wuerde also die Konfiguration des Systems
anfassen, auf dem er zufaellig laeuft.

Der Token-Aufbau wird hier UNABHAENGIG vom Ausgabewerkzeug nachgebaut. Genau
das ist der Zweck: `license-manager/` liegt ausserhalb des Repos und ist auf
den Servern gar nicht vorhanden – ein Test, der es importiert, wuerde dort
stillschweigend uebersprungen. Wenn beide Seiten dieselbe Beschreibung
erfuellen, passen sie zusammen.

    python3 tests/test_license.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

# ── backend.config stubben (siehe Modulkopf) ───────────────────────────────
_stub = types.ModuleType("backend.config")


class _ConfigStub:
    def __init__(self):
        self.profiles = []
        self.active_profile_id = ""
        self._skills = {}
        self._settings = {}

    def get_skill_states(self):
        return self._skills

    def save_skill_state(self, name, state):
        self._skills.setdefault(name, {}).update(state)

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)

    def save_setting(self, key, value):
        self._settings[key] = value


_stub.config = _ConfigStub()
sys.modules.setdefault("backend.config", _stub)

from backend import license as lic          # noqa: E402
from backend import license_enforce as enf  # noqa: E402

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

fehler: list[str] = []
anzahl = 0


def pruefe(bedingung, name, detail=""):
    global anzahl
    anzahl += 1
    if bedingung:
        print(f"  \033[32m✓\033[0m {name}")
    else:
        print(f"  \033[31m✗\033[0m {name}" + (f"  ({detail})" if detail else ""))
        fehler.append(name)


def gleich(ist, soll, name):
    pruefe(ist == soll, name, f"ist={ist!r} soll={soll!r}")


# ── Testschluessel + Token-Bau (Format nachgebaut) ─────────────────────────
ROOT = Ed25519PrivateKey.generate()
ISSUER = Ed25519PrivateKey.generate()


def pub_b64(key) -> str:
    from cryptography.hazmat.primitives import serialization
    return lic._b64e(key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw))


def zert_bauen(issuer=ISSUER, root=ROOT, bis="2099-01-01", kid="test") -> dict:
    kern = {"kid": kid, "pub": pub_b64(issuer), "gueltig_bis": bis}
    z = dict(kern)
    z["sig_root"] = lic._b64e(root.sign(lic.kanonisch(kern)))
    return z


def tage(n: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=n)).date().isoformat()


def nutzdaten(firma="Muster AG", abteilung="IT", mail="it@muster.de",
              art="BASIC", nr=1, bis=None) -> dict:
    d = {
        "v": 1, "firma": firma, "abteilung": abteilung, "mail": mail,
        "art": art, "nr": nr, "ausgestellt": tage(0),
        "gueltig_bis": tage(365) if bis is None else bis,
    }
    d["uuid"] = str(uuid.uuid5(lic.UUID_NAMESPACE,
                               "|".join([firma, abteilung, mail, str(nr)])))
    return d


def token_bauen(daten: dict, issuer=ISSUER, zert=None) -> str:
    return ".".join([
        lic.TOKEN_PREFIX,
        lic._b64e(lic.kanonisch(daten)),
        lic._b64e(issuer.sign(lic.kanonisch(daten))),
        lic._b64e(lic.kanonisch(zert or zert_bauen())),
    ])


def status_bauen(eintraege: dict, stand=None, issuer=ISSUER, zert=None) -> dict:
    kern = {"v": 1, "stand": stand or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "eintraege": eintraege}
    d = dict(kern)
    d["zert"] = zert or zert_bauen()
    d["sig"] = lic._b64e(issuer.sign(lic.kanonisch(kern)))
    return d


TMP = Path(tempfile.mkdtemp(prefix="jarvis-lic-test-"))
STATUS_DATEI = TMP / "status.json"


def status_schreiben(eintraege, **kw):
    STATUS_DATEI.write_text(json.dumps(status_bauen(eintraege, **kw)))


def umgebung_setzen():
    """Modul auf das Wegwerf-Verzeichnis umbiegen – und das PRUEFEN.

    Zeigt eine der Pfadvariablen noch auf die echte Installation, schreibt der
    Test in den Live-Zustand. Genau das ist bei einem frueheren Testmodul
    passiert (Gegenprobe gegen einen alten Stand, andere Variablennamen).
    """
    lic.STATE_FILE = TMP / "license.json"
    lic.ROOT_PUB_FILE = TMP / "root.pub"
    lic.ROOT_PUB_FILE.write_text(pub_b64(ROOT) + "\n")
    lic.STATUS_URL = "file://" + str(STATUS_DATEI)
    lic._hwid_cache = "H1-aaaaaaaaaaaa-bbbbbbbbbbbb-cccccccccccc"
    lic._reset_fuer_tests()
    lic._cache_leeren()
    for name in ("STATE_FILE", "ROOT_PUB_FILE"):
        p = Path(getattr(lic, name))
        if TMP not in p.parents and p != TMP:
            print(f"ABBRUCH: {name} zeigt auf {p} – nicht ins Wegwerf-Verzeichnis")
            sys.exit(2)


def zurueck():
    """Zustand zwischen Faellen verwerfen (Datei + Zwischenspeicher)."""
    try:
        Path(lic.STATE_FILE).unlink()
    except FileNotFoundError:
        pass
    lic._reset_fuer_tests()
    lic._cache_leeren()


umgebung_setzen()

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m1. Token: Aufbau, Signaturkette, Manipulation\033[0m")

nd = nutzdaten()
tok = token_bauen(nd)
geprueft, f = lic.token_pruefen(tok)
pruefe(geprueft is not None and not f, "gültiges Token wird angenommen", f)
gleich((geprueft or {}).get("art"), "BASIC", "Art wird gelesen")

pruefe(lic.token_pruefen("")[1] != "", "leeres Token wird abgelehnt")
pruefe(lic.token_pruefen("irgendwas")[1] != "", "Unsinn wird abgelehnt")
pruefe(lic.token_pruefen("JARVIS-LIC-1.a.b")[1] != "", "zu wenige Teile werden abgelehnt")
pruefe(lic.token_pruefen("JARVIS-LIC-9." + tok.split(".", 1)[1])[1] != "",
       "fremdes Präfix wird abgelehnt")

# Leerzeichen/Zeilenumbrueche aus Copy&Paste
zerhackt = tok[:40] + "\n  " + tok[40:80] + " " + tok[80:]
pruefe(lic.token_pruefen(zerhackt)[0] is not None,
       "Zeilenumbrüche aus Copy&Paste stören nicht")

# Nutzdaten veraendert -> Signatur passt nicht
teile = tok.split(".")
gefaelscht = dict(nd); gefaelscht["art"] = "ENTERPRISE"
tok_f = ".".join([teile[0], lic._b64e(lic.kanonisch(gefaelscht)), teile[2], teile[3]])
pruefe("Signatur" in lic.token_pruefen(tok_f)[1], "geänderte Art bricht die Signatur")

# Selbst signiert (fremder Ausgabe-Schluessel ohne Root-Segen)
fremd = Ed25519PrivateKey.generate()
tok_fremd = token_bauen(nd, issuer=fremd, zert=zert_bauen(issuer=fremd, root=fremd))
pruefe("Root" in lic.token_pruefen(tok_fremd)[1],
       "selbst ausgestelltes Zertifikat wird abgelehnt")

# Echtes Zertifikat, aber anderer Signierschluessel
tok_misch = token_bauen(nd, issuer=fremd, zert=zert_bauen())
pruefe("Signatur" in lic.token_pruefen(tok_misch)[1],
       "fremd signiertes Token mit echtem Zertifikat wird abgelehnt")

# Abgelaufenes Ausgabe-Zertifikat
tok_alt = token_bauen(nd, zert=zert_bauen(bis="2020-01-01"))
pruefe("abgelaufen" in lic.token_pruefen(tok_alt)[1].lower(),
       "abgelaufenes Ausgabe-Zertifikat wird abgelehnt")

# Die Kennung muss WOHLGEFORMT sein …
nd_ohne = nutzdaten(); nd_ohne["uuid"] = "keine-uuid"
pruefe("Lizenzkennung" in lic.token_pruefen(token_bauen(nd_ohne))[1],
       "unbrauchbare Lizenzkennung wird abgelehnt")
nd_leer = nutzdaten(); nd_leer["uuid"] = ""
pruefe(lic.token_pruefen(token_bauen(nd_leer))[0] is None, "leere Kennung wird abgelehnt")

# … muss sich aber NICHT mehr aus den Stammdaten ableiten lassen (2026-08-07).
# Sonst wären Firma und Abteilung unveränderlich: eine Umfirmierung verschöbe
# die Kennung, damit den Eintrag im Statusdienst und die Hardware-Bindung – der
# Kunde fiele ohne eigenes Zutun auf FREE. Die Probe schützte auch nichts: wer
# die Nutzdaten ändert, bricht die Signatur.
nd_umbenannt = nutzdaten()
nd_umbenannt["firma"] = "Nach der Umfirmierung GmbH"      # Kennung bleibt die alte
geprueft, f = lic.token_pruefen(token_bauen(nd_umbenannt))
pruefe(geprueft is not None, "Stammdaten dürfen von der Kennung abweichen", f)
gleich((geprueft or {}).get("firma"), "Nach der Umfirmierung GmbH",
       "geänderter Name kommt an")

# Unbekannte Art
nd_art = nutzdaten(art="PLATIN")
pruefe(lic.token_pruefen(token_bauen(nd_art))[1] != "", "unbekannte Art wird abgelehnt")

# Kein Root-Schluessel hinterlegt -> nichts ist prüfbar (fail-closed)
merk = lic.ROOT_PUB_FILE
lic.ROOT_PUB_FILE = TMP / "gibt-es-nicht.pub"
pruefe(lic.token_pruefen(tok)[0] is None, "ohne Root-Schlüssel gilt kein Token")
lic.ROOT_PUB_FILE = merk

# Deterministische UUID: gleiche Daten -> gleiche Kennung, andere Nr -> andere
gleich(nutzdaten(nr=1)["uuid"], nutzdaten(nr=1)["uuid"], "UUID ist deterministisch")
pruefe(nutzdaten(nr=1)["uuid"] != nutzdaten(nr=2)["uuid"],
       "laufende Nummer erzeugt eine eigene UUID")
pruefe(lic.lizenz_id(nd["uuid"]) != nd["uuid"] and len(lic.lizenz_id(nd["uuid"])) == 32,
       "öffentliche Kennung ist ein Hash, nicht die UUID")

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m2. Hardware-Kennung: 2 von 3\033[0m")

H = "H1-aaaaaaaaaaaa-bbbbbbbbbbbb-cccccccccccc"
pruefe(lic.hwid_passt(H, H), "identische Kennung passt")
pruefe(lic.hwid_passt(H, "H1-aaaaaaaaaaaa-bbbbbbbbbbbb-ffffffffffff"),
       "getauschte Netzwerkkarte (2 von 3) passt")
pruefe(lic.hwid_passt(H, "H1-ffffffffffff-bbbbbbbbbbbb-cccccccccccc"),
       "neue Maschinen-ID (2 von 3) passt")
pruefe(not lic.hwid_passt(H, "H1-aaaaaaaaaaaa-ffffffffffff-ffffffffffff"),
       "nur 1 von 3 passt NICHT")
pruefe(not lic.hwid_passt(H, "H1-111111111111-222222222222-333333333333"),
       "fremdes System passt nicht")
pruefe(not lic.hwid_passt(H, "H1-aaaaaaaaaaaa-bbbbbbbbbbbb"), "verstümmelte Kennung passt nicht")
pruefe(not lic.hwid_passt("", H), "leere ERWARTUNG passt nie")
# Der zweite Parameter ist optional: leer heisst "die eigene Kennung nehmen",
# nicht "leere Kennung". Das ist die Signatur, die zustand() benutzt.
pruefe(lic.hwid_passt(lic.hwid()), "ohne zweites Argument gilt die eigene Kennung")
pruefe(not lic.hwid_passt("H1----", "H1----"),
       "zwei fehlende Merkmale zählen nicht als Treffer")
pruefe(not lic.hwid_passt("H1-x-y-z", "H2-x-y-z"), "fremde Version passt nicht")

# Positionsgenau: dieselben Werte in anderer Reihenfolge sind KEIN Treffer
pruefe(not lic.hwid_passt(H, "H1-bbbbbbbbbbbb-aaaaaaaaaaaa-ffffffffffff"),
       "vertauschte Merkmale sind kein Treffer")

# Echte Kennung des laufenden Systems ist wohlgeformt
lic._hwid_cache = ""
echt = lic.hwid()
lic._hwid_cache = H
pruefe(echt.startswith("H1-") and len(echt.split("-")) == 4,
       "echte Kennung hat das Format H1-a-b-c", echt)
pruefe(sum(1 for t in echt.split("-")[1:] if t != "-") >= 2,
       "echtes System liefert mindestens zwei Merkmale", echt)

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m3. Zustand: die Kette der Ablehnungsgründe\033[0m")

LID = lic.lizenz_id(nd["uuid"])


def stand(eintrag=None, **kw):
    """Statusdatei mit genau diesem Eintrag schreiben."""
    status_schreiben({LID: eintrag} if eintrag else {}, **kw)


zurueck()
z = lic.zustand()
gleich(z["art"], "FREE", "ohne Schlüssel: FREE")
pruefe(z["einfuehrung_karenz"], "ohne Schlüssel läuft die Einführungs-Karenz")
gleich(z["grenzen"]["skills"], None, "während der Karenz gilt keine Grenze")
gleich(z["banner"], "", "kein Schlüssel ist KEIN Warnfall")

zurueck()
stand({"status": "active", "art": "BASIC", "gueltig_bis": tage(365), "hwid": H})
z = lic.setze_token(tok, "tester")
gleich(z["art"], "BASIC", "gebundene Lizenz gilt")
pruefe(z["gueltig"] and z["gebunden"], "gilt als gebunden")
gleich(z["grenzen"]["skills"], 5, "BASIC: fünf Skills")
gleich(z["grenzen"]["updates"], "manuell", "BASIC: manuelle Updates")
pruefe(not z["einfuehrung_karenz"], "gültige Lizenz beendet die Karenz")

# Nicht gebunden -> FREE (die zentrale Regel)
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": None})
z = lic.pruefen()
gleich(z["art"], "FREE", "ohne hinterlegte Hardware-Kennung: FREE")
pruefe(not z["gebunden"] and "gebunden" in z["grund"], "Grund nennt die fehlende Bindung")
gleich(z["banner"], "", "fehlende Bindung ist kein Manipulationsverdacht")

# Fremde Hardware
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365),
       "hwid": "H1-111111111111-222222222222-333333333333"})
z = lic.pruefen()
gleich(z["art"], "FREE", "fremde Hardware: FREE")
pruefe(z["banner"] != "", "fremde Hardware erzeugt ein Banner")

# Widerruf
stand({"status": "revoked", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H})
z = lic.pruefen()
gleich(z["art"], "FREE", "Widerruf: FREE")
pruefe("widerrufen" in z["banner"].lower(), "Widerruf erzeugt ein Banner")

# Unbekannt im Statusdienst
stand(None)
z = lic.pruefen()
gleich(z["art"], "FREE", "unbekannte Lizenz: FREE")

# Ablauf laut Statusdienst
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(-1), "hwid": H})
z = lic.pruefen()
gleich(z["art"], "FREE", "abgelaufen laut Statusdienst: FREE")

# Laufzeit: der Statusdienst ist massgeblich (seit 2026-08-07).
# Beide Angaben tragen dieselbe Signatur derselben Ausgabestelle – die aus dem
# Statusdienst ist nur die frischere. Damit braucht eine Verlaengerung KEINEN
# neuen Schluesseltext beim Kunden.
zurueck()
tok_abgelaufen = token_bauen(nutzdaten(bis=tage(-1)))
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H})
z = lic.setze_token(tok_abgelaufen, "tester")
gleich(z["art"], "ENTERPRISE", "Statusdienst verlängert ein abgelaufenes Token")
gleich(z["gueltig_bis"], tage(365), "angezeigt wird das maßgebliche Datum")

# … und er darf genauso verkuerzen
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(-1), "hwid": H})
gleich(lic.pruefen()["art"], "FREE", "Statusdienst verkürzt: abgelaufen")

zurueck()
tok_lang = token_bauen(nutzdaten(bis=tage(365)))
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(-1), "hwid": H})
z = lic.setze_token(tok_lang, "tester")
gleich(z["art"], "FREE", "Statusdienst verkürzt auch ein langlaufendes Token")

# FEHLT das Feld (älterer/fremder Statusgenerator), gilt weiter das Token –
# ein fehlender Wert ist keine Aussage, ein leerer schon ("unbegrenzt").
zurueck()
status_schreiben({lic.lizenz_id(nutzdaten(bis=tage(-1))["uuid"]):
                  {"status": "active", "art": "ENTERPRISE", "hwid": H}})
z = lic.setze_token(tok_abgelaufen, "tester")
gleich(z["art"], "FREE", "ohne Datum im Statusdienst zählt das Token-Datum")

zurueck()
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": "", "hwid": H})
z = lic.setze_token(tok_abgelaufen, "tester")
gleich(z["art"], "ENTERPRISE", "leeres Datum im Statusdienst = unbegrenzt")
gleich(z["gueltig_bis"], "", "unbegrenzt wird auch so angezeigt")

# Ohne erreichbaren Statusdienst bleibt das Token-Datum die Grenze
zurueck()
daten = lic._laden(); daten["token"] = tok_abgelaufen; lic._speichern()
gleich(lic.zustand()["art"], "FREE",
       "abgelaufenes Token ohne Statusabruf: FREE (Offline-Grenze bleibt)")

# Hochstufen ueber den Statusdienst, ohne neuen Schluessel
zurueck()
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H})
z = lic.setze_token(tok, "tester")
gleich(z["art"], "ENTERPRISE", "Statusdienst stuft hoch (Token sagt BASIC)")
gleich(z["grenzen"]["skills"], None, "ENTERPRISE: keine Skill-Grenze")
gleich(z["grenzen"]["auto_update"], True, "ENTERPRISE: automatische Updates")

# Herabstufen
stand({"status": "active", "art": "FREE", "gueltig_bis": tage(365), "hwid": H})
z = lic.pruefen()
gleich(z["art"], "FREE", "Statusdienst stuft herab")
gleich(z["grenzen"]["benutzer"], 5, "FREE: fünf Benutzer")
gleich(z["grenzen"]["rag"], 50, "FREE: 50 Wissensdateien")

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m4. Statusdatei: Signatur, Rückspielschutz, Netz-Karenz\033[0m")

zurueck()
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H})
lic.setze_token(tok, "tester")
gleich(lic.zustand()["art"], "ENTERPRISE", "Ausgangslage steht")

# Unsignierte/verbogene Datei wird nicht uebernommen
gut = STATUS_DATEI.read_text()
verbogen = json.loads(gut)
verbogen["eintraege"][LID]["status"] = "revoked"
STATUS_DATEI.write_text(json.dumps(verbogen))
z = lic.pruefen()
gleich(z["art"], "ENTERPRISE", "manipulierte Statusdatei ändert nichts")
pruefe("signiert" in z["letzter_fehler"], "Grund: Signatur", z["letzter_fehler"])
pruefe(z["banner"] != "", "manipulierte Statusdatei erzeugt ein Banner")

# Fremd signierte Datei
STATUS_DATEI.write_text(json.dumps(status_bauen(
    {LID: {"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H}},
    issuer=fremd, zert=zert_bauen(issuer=fremd, root=fremd))))
z = lic.pruefen()
pruefe("Root" in z["letzter_fehler"], "fremd signierte Statusdatei wird abgelehnt",
       z["letzter_fehler"])

# Rueckspielschutz: echte, korrekt signierte ALTE Datei
STATUS_DATEI.write_text(gut)
lic.pruefen()
neu = status_bauen({LID: {"status": "revoked", "art": "ENTERPRISE",
                          "gueltig_bis": tage(365), "hwid": H}},
                   stand=(datetime.now(timezone.utc) + timedelta(seconds=5))
                   .isoformat(timespec="seconds"))
STATUS_DATEI.write_text(json.dumps(neu))
gleich(lic.pruefen()["art"], "FREE", "Widerruf greift")
STATUS_DATEI.write_text(gut)      # alter, gueltig signierter Stand
z = lic.pruefen()
gleich(z["art"], "FREE", "alter Stand hebt den Widerruf NICHT auf")
pruefe("älter" in z["letzter_fehler"], "Grund: älterer Stand", z["letzter_fehler"])

# Netz-Karenz
zurueck()
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H})
lic.setze_token(tok, "tester")
lic.STATUS_URL = "file://" + str(TMP / "weg.json")     # nicht erreichbar
z = lic.pruefen()
gleich(z["art"], "ENTERPRISE", "kurzer Ausfall: letzter Stand gilt weiter")
pruefe(z["letzter_fehler"] != "", "Ausfall wird vermerkt")

daten = lic._laden()
daten["letzter_erfolg"] = time.time() - (lic.NETZ_KARENZ_TAGE + 1) * 86400
lic._speichern()
z = lic.zustand()
gleich(z["art"], "FREE", "nach 14 Tagen ohne Kontakt: FREE")
pruefe(z["banner"] != "", "abgelaufene Netz-Karenz erzeugt ein Banner")

daten = lic._laden()
daten["letzter_erfolg"] = time.time() - 3 * 86400
lic._speichern()
z = lic.zustand()
gleich(z["art"], "ENTERPRISE", "drei Tage ohne Kontakt sind unkritisch")
gleich(z["karenz_tage_rest"], lic.NETZ_KARENZ_TAGE - 3, "Restlaufzeit der Karenz stimmt")
lic.STATUS_URL = "file://" + str(STATUS_DATEI)

# Nie erfolgreich geprueft -> FREE, auch mit gueltigem Token
zurueck()
daten = lic._laden()
daten["token"] = tok
lic._speichern()
gleich(lic.zustand()["art"], "FREE", "ohne je erfolgten Statusabruf: FREE")

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m5. Einführungs-Karenz (30 Tage)\033[0m")

zurueck()
z = lic.zustand()
pruefe(z["einfuehrung_karenz"] and z["durchsetzung_aktiv"] is False,
       "frisches System: Karenz läuft, keine Durchsetzung")
gleich(z["einfuehrung_rest_tage"], lic.EINFUEHRUNG_KARENZ_TAGE, "volle 30 Tage")

daten = lic._laden()
daten["ohne_lizenz_seit"] = time.time() - 29 * 86400
lic._speichern()
z = lic.zustand()
pruefe(z["einfuehrung_karenz"], "Tag 29: Karenz läuft noch")
gleich(z["einfuehrung_rest_tage"], 1, "ein Tag Rest")

daten = lic._laden()
daten["ohne_lizenz_seit"] = time.time() - 31 * 86400
lic._speichern()
z = lic.zustand()
pruefe(not z["einfuehrung_karenz"], "Tag 31: Karenz vorbei")
pruefe(z["durchsetzung_aktiv"], "Durchsetzung aktiv")
gleich(z["grenzen"]["skills"], 5, "jetzt greift die FREE-Grenze")
gleich(z["grenzen"]["updates"], "keine", "FREE: keine Updates")

# Eine gueltige Lizenz setzt die Karenz zurueck – und ihr Verlust startet sie neu
zurueck()
stand({"status": "active", "art": "BASIC", "gueltig_bis": tage(365), "hwid": H})
lic.setze_token(tok, "tester")
pruefe(lic._laden().get("ohne_lizenz_seit") is None,
       "gültige Lizenz löscht den Karenz-Beginn")

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m6. Update-Tore\033[0m")

zurueck()
stand({"status": "active", "art": "FREE", "gueltig_bis": tage(365), "hwid": H})
lic.setze_token(tok, "tester")
daten = lic._laden(); daten["ohne_lizenz_seit"] = None; lic._speichern()
pruefe(not lic.updates_erlaubt()[0], "FREE: kein Update")
pruefe(not lic.auto_update_erlaubt()[0], "FREE: kein Auto-Update")

stand({"status": "active", "art": "BASIC", "gueltig_bis": tage(365), "hwid": H})
lic.pruefen()
pruefe(lic.updates_erlaubt()[0], "BASIC: manuelles Update erlaubt")
pruefe(not lic.auto_update_erlaubt()[0], "BASIC: kein Auto-Update")
pruefe("ENTERPRISE" in lic.auto_update_erlaubt()[1],
       "Meldung nennt die nötige Stufe")

stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H})
lic.pruefen()
pruefe(lic.updates_erlaubt()[0] and lic.auto_update_erlaubt()[0],
       "ENTERPRISE: beides erlaubt")

# Waehrend der Karenz ist alles offen
zurueck()
pruefe(lic.updates_erlaubt()[0] and lic.auto_update_erlaubt()[0],
       "Einführungs-Karenz: Updates bleiben möglich")

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m7. Durchsetzung: Torwächter und Nachführung\033[0m")

cfg = _stub.config


def lizenz_setzen(art):
    """Zustand auf eine wirksame Lizenz dieser Art bringen."""
    zurueck()
    stand({"status": "active", "art": art, "gueltig_bis": tage(365), "hwid": H})
    lic.setze_token(tok, "tester")
    assert lic.zustand()["art"] == art


lizenz_setzen("BASIC")
cfg.profiles = [{"id": "p1"}]
cfg.active_profile_id = "p1"
pruefe(not enf.darf_profil_anlegen()[0], "BASIC: kein zweites Profil")
cfg.profiles = []
pruefe(enf.darf_profil_anlegen()[0], "erstes Profil geht immer")

cfg.profiles = [{"id": "p1"}, {"id": "p2"}]
cfg.active_profile_id = "p2"
pruefe(enf.profil_nutzbar("p2"), "aktives Profil ist nutzbar")
pruefe(not enf.profil_nutzbar("p1"), "zweites Profil ist bei BASIC nicht nutzbar")

lizenz_setzen("ENTERPRISE")
pruefe(enf.darf_profil_anlegen()[0], "ENTERPRISE: Profile unbegrenzt")
pruefe(enf.profil_nutzbar("p1") and enf.profil_nutzbar("p2"),
       "ENTERPRISE: alle Profile nutzbar")

# Skills: Reihenfolge des Abschaltens.
# Der SkillManager wird gestubbt – geprueft wird die AUSWAHL (welcher Skill
# fliegt), nicht das Abschalten selbst; ein echter Manager wuerde hier das
# skills/-Verzeichnis lesen und systemd-Dienste anfassen. Der Stub MUSS vor
# der ersten Skill-Pruefung stehen, sonst zieht `_skill_manager()` den echten.
manager_stub = types.ModuleType("backend.skills.manager")
abgeschaltet: list[str] = []
# Skills OHNE Eintrag in den Zustaenden, die per Manifest-Vorgabe laufen.
# Genau diese Gruppe fehlte in der ersten Fassung der Zaehlung (auf DEV live
# aufgefallen: 13 gezaehlt, 19 tatsaechlich aktiv).
manifest_aktiv: list[str] = []


class _SM:
    def list_skills(self):
        """Bildet die echte Regel nach: gespeicherter Zustand, sonst Manifest."""
        aus = []
        zustaende = cfg.get_skill_states()
        for name, st in zustaende.items():
            aus.append({"path": f"/opt/jarvis/skills/{name}", "name": name.upper(),
                        "enabled": bool(st.get("enabled"))})
        for name in manifest_aktiv:
            if name in zustaende:
                continue          # ein Eintrag schlägt die Manifest-Vorgabe
            aus.append({"path": f"/opt/jarvis/skills/{name}", "name": name.upper(),
                        "enabled": True})
        return aus

    def disable_skill(self, name):
        abgeschaltet.append(name)
        cfg.save_skill_state(name, {"enabled": False, "installed": True})
        return True


manager_stub.SkillManager = _SM
sys.modules["backend.skills.manager"] = manager_stub

lizenz_setzen("BASIC")
jetzt = time.time()
cfg._skills = {
    "alt_a":   {"enabled": True},                              # Bestand ohne Stempel
    "alt_b":   {"enabled": True},
    "alt_c":   {"enabled": True},
    "neu_1":   {"enabled": True, "enabled_at": jetzt - 100},
    "neu_2":   {"enabled": True, "enabled_at": jetzt - 10},
    "aus":     {"enabled": False},
}
gleich(enf.anzahl_skills(), 5, "fünf aktive Skills gezählt (aus zählt nicht)")
gleich(enf.aktive_skills()[:2], ["neu_2", "neu_1"],
       "zuletzt aktivierte stehen vorn (fliegen zuerst)")
gleich(enf.aktive_skills()[2:], ["alt_c", "alt_b", "alt_a"],
       "Bestand ohne Stempel: umgekehrte Listenreihenfolge")
pruefe(not enf.darf_skill_aktivieren("weiterer")[0], "BASIC: sechster Skill abgelehnt")
pruefe(enf.darf_skill_aktivieren("neu_1")[0], "bereits aktiver Skill bleibt erlaubt")

cfg._skills["ueberzaehlig"] = {"enabled": True, "enabled_at": jetzt}
bericht = enf.anwenden()
gleich(bericht["skills_deaktiviert"], ["ueberzaehlig"],
       "Nachführung schaltet genau den jüngsten ab")
gleich(enf.anzahl_skills(), 5, "danach sind es wieder fünf")

# Zwei zu viel -> beide juengsten
cfg._skills["x1"] = {"enabled": True, "enabled_at": jetzt + 1}
cfg._skills["x2"] = {"enabled": True, "enabled_at": jetzt + 2}
bericht = enf.anwenden()
gleich(sorted(bericht["skills_deaktiviert"]), ["x1", "x2"], "beide jüngsten fliegen")

# Skills ohne gespeicherten Zustand (Manifest-Vorgabe): zählen mit, gelten als
# Bestand und sind abschaltbar. Auf DEV war genau das der Live-Befund – 19
# tatsächlich aktive Skills, aber nur 13 mit Eintrag in settings.json.
cfg._skills = {"mit_stempel": {"enabled": True, "enabled_at": jetzt}}
manifest_aktiv[:] = [f"m{i}" for i in range(1, 8)]     # m1 … m7
gleich(enf.anzahl_skills(), 8, "sieben ohne Eintrag + einer mit = acht")
pruefe("m4" in enf.aktive_skills(), "Skill ohne Eintrag zählt als aktiv")
pruefe(not enf.darf_skill_aktivieren("noch_einer")[0],
       "Grenze greift auch, wenn die Mehrheit keinen Eintrag hat")
gleich(enf.aktive_skills()[0], "mit_stempel",
       "der frisch aktivierte fliegt zuerst, auch gegen eintragslosen Bestand")
bericht = enf.anwenden()
gleich(bericht["skills_deaktiviert"], ["mit_stempel", "m7", "m6"],
       "drei zu viel: der jüngste, dann der Bestand von hinten")
for n in ("m7", "m6"):
    pruefe(cfg.get_skill_states().get(n, {}).get("enabled") is False,
           f"{n} ist danach ausdrücklich abgeschaltet")
gleich(enf.anzahl_skills(), 5, "danach genau fünf")
pruefe("m1" in enf.aktive_skills() and "m5" in enf.aktive_skills(),
       "die vorderen Bestands-Skills bleiben an")
manifest_aktiv[:] = []
cfg._skills = {}
abgeschaltet.clear()

lizenz_setzen("ENTERPRISE")
cfg._skills["y1"] = {"enabled": True, "enabled_at": jetzt}
gleich(enf.anwenden()["skills_deaktiviert"], [], "ENTERPRISE schaltet nichts ab")
pruefe(enf.darf_skill_aktivieren("noch_einer")[0], "ENTERPRISE: Skills unbegrenzt")

# Waehrend der Karenz wird NICHTS abgeschaltet – die wichtigste Zusage beim
# Ausrollen auf Bestandssysteme.
zurueck()
cfg._skills = {f"s{i}": {"enabled": True} for i in range(12)}
gleich(enf.anwenden()["skills_deaktiviert"], [],
       "Einführungs-Karenz: keine Abschaltung")
pruefe(enf.darf_skill_aktivieren("weiterer")[0], "Karenz: Aktivieren bleibt erlaubt")

# Auto-Update-Auftrag wird abgeraeumt
lizenz_setzen("BASIC")
cfg._skills = {}
cfg._settings["auto_update_schedule"] = "daily"
geloescht = {}
scheduler_stub = types.ModuleType("backend.scheduler")


class _Cron:
    def delete_job(self, job_id):
        geloescht["id"] = job_id
        return True


scheduler_stub.cron_manager = _Cron()
sys.modules["backend.scheduler"] = scheduler_stub
bericht = enf.anwenden()
gleich(geloescht.get("id"), "system_auto_update", "Auto-Update-Auftrag wird entfernt")
gleich(cfg._settings["auto_update_schedule"], "never", "Einstellung wird zurückgesetzt")

lizenz_setzen("ENTERPRISE")
geloescht.clear()
cfg._settings["auto_update_schedule"] = "daily"
enf.anwenden()
pruefe("id" not in geloescht, "ENTERPRISE lässt den Auto-Update-Auftrag stehen")
gleich(cfg._settings["auto_update_schedule"], "daily", "Einstellung bleibt")

# Benutzergrenze
lizenz_setzen("BASIC")
sessions = types.ModuleType("backend.user_sessions")
_liste = [{"username": f"benutzer{i}", "last_seen": time.time(), "last_login": time.time()}
          for i in range(10)]
sessions.list_users = lambda: _liste
sys.modules["backend.user_sessions"] = sessions
gleich(enf.anzahl_benutzer(), 10, "zehn aktive Benutzer gezählt")
pruefe(not enf.darf_benutzer_anmelden("neuer")[0], "elfter Benutzer wird abgewiesen")
pruefe(enf.darf_benutzer_anmelden("benutzer3")[0], "bekannter Benutzer kommt durch")
pruefe(enf.darf_benutzer_anmelden("NEXUS\\benutzer3")[0],
       "Domänen-Schreibweise wird normalisiert")
pruefe(enf.darf_benutzer_anmelden("benutzer3@nexus.int")[0],
       "UPN-Schreibweise wird normalisiert")
pruefe(enf.darf_benutzer_anmelden("jarvis")[0],
       "lokaler jarvis kommt IMMER durch (Rückweg in die Einstellungen)")
pruefe(enf.darf_benutzer_anmelden("api")[0], "API-Benutzer zählt nicht")

_liste.append({"username": "jarvis", "last_seen": time.time(), "last_login": time.time()})
gleich(enf.anzahl_benutzer(), 10, "jarvis zählt nicht gegen die Grenze")

# Alte Anmeldungen zaehlen nicht
_liste[:] = [{"username": f"alt{i}", "last_seen": time.time() - 40 * 86400,
              "last_login": time.time() - 40 * 86400} for i in range(20)]
gleich(enf.anzahl_benutzer(), 0, "Anmeldungen älter als 30 Tage zählen nicht")
pruefe(enf.darf_benutzer_anmelden("neuer")[0], "danach ist wieder Platz")

lizenz_setzen("ENTERPRISE")
_liste[:] = [{"username": f"b{i}", "last_seen": time.time(), "last_login": time.time()}
             for i in range(500)]
pruefe(enf.darf_benutzer_anmelden("noch_einer")[0], "ENTERPRISE: Benutzer unbegrenzt")

# Wissensdatenbank
know = types.ModuleType("backend.tools.knowledge")
_dateien = {"n": 49}
know.get_disk_file_count = lambda: _dateien["n"]
sys.modules["backend.tools.knowledge"] = know

lizenz_setzen("BASIC")
_dateien["n"] = 99
pruefe(enf.darf_wissen_hinzufuegen(1)[0], "BASIC: 99 + 1 geht")
pruefe(not enf.darf_wissen_hinzufuegen(2)[0], "BASIC: 99 + 2 überschreitet 100")
_dateien["n"] = 100
pruefe(not enf.darf_wissen_hinzufuegen(1)[0], "BASIC: bei 100 ist Schluss")
pruefe("bleiben nutzbar" in enf.darf_wissen_hinzufuegen(1)[1],
       "Meldung sagt, dass der Bestand nutzbar bleibt")

lizenz_setzen("ENTERPRISE")
_dateien["n"] = 100000
pruefe(enf.darf_wissen_hinzufuegen(500)[0], "ENTERPRISE: unbegrenzt")

zurueck()
_dateien["n"] = 100000
pruefe(enf.darf_wissen_hinzufuegen(1)[0], "Karenz: Wissen unbegrenzt")

# Uebersicht fuer die Oberflaeche
lizenz_setzen("BASIC")
u = enf.uebersicht()
pruefe(set(u) >= {"profile", "skills", "benutzer", "rag", "updates"},
       "Übersicht nennt alle Grenzen")
gleich(u["rag"]["max"], 100, "Übersicht: RAG-Grenze")
gleich(u["benutzer"]["fenster_tage"], 30, "Übersicht: Zeitfenster")

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m8. Zustand auf Platte: Rechte, Robustheit\033[0m")

lizenz_setzen("BASIC")
modus = os.stat(lic.STATE_FILE).st_mode & 0o777
gleich(modus, 0o640, "license.json ist 0640 (Sandbox kommt nicht heran)")
inhalt = json.loads(Path(lic.STATE_FILE).read_text())
pruefe("token" in inhalt and "gebunden_hwid" in inhalt, "Zustand wird gespeichert")

# Beschaedigte Datei -> Vorgabe, kein Absturz
Path(lic.STATE_FILE).write_text("{kaputt")
lic._reset_fuer_tests(); lic._cache_leeren()
z = lic.zustand()
gleich(z["art"], "FREE", "beschädigte Zustandsdatei: FREE statt Absturz")

# Schluesselwechsel verwirft die alte Bindung
zurueck()
stand({"status": "active", "art": "BASIC", "gueltig_bis": tage(365), "hwid": H})
lic.setze_token(tok, "tester")
tok2 = token_bauen(nutzdaten(nr=2))
lic.setze_token(tok2, "tester")
d = lic._laden()
pruefe(d["status_eintrag"] is None or d["status_stand"] == "" or not lic.zustand()["gueltig"],
       "neuer Schlüssel verwirft Bindung und Statuscache")

# Entfernen
zurueck()
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H})
lic.setze_token(tok, "tester")
z = lic.entferne_token("tester")
gleich(z["art"], "FREE", "nach dem Entfernen: FREE")
pruefe(not z["hat_token"], "kein Schlüssel mehr hinterlegt")

# Zwischenspeicher: nach einer Aenderung sofort neuer Wert
zurueck()
stand({"status": "active", "art": "ENTERPRISE", "gueltig_bis": tage(365), "hwid": H})
lic.zustand()
lic.setze_token(tok, "tester")
gleich(lic.zustand()["art"], "ENTERPRISE", "Zwischenspeicher wird bei Änderung verworfen")

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m9. Verdrahtung im Quelltext\033[0m")

main_py = (WURZEL / "backend" / "main.py").read_text()
sandbox_py = (WURZEL / "backend" / "sandbox.py").read_text()
gitignore = (WURZEL / ".gitignore").read_text()

for route, methode in [('@app.get("/api/license")', "get"),
                       ('@app.post("/api/license")', "post"),
                       ('@app.delete("/api/license")', "delete"),
                       ('@app.post("/api/license/check")', "post")]:
    i = main_py.find(route)
    rumpf = main_py[i:i + 400] if i >= 0 else ""
    pruefe(i >= 0 and "require_local_auth" in rumpf,
           f"{route} verlangt Administrator-Rechte")

pruefe("startup_license" in main_py, "täglicher Prüflauf ist verdrahtet")
pruefe("license_enforce.darf_benutzer_anmelden" in main_py
       or "darf_benutzer_anmelden(username)" in main_py,
       "Login prüft die Benutzergrenze")
i_login = main_py.find("darf_benutzer_anmelden")
i_record = main_py.find("record_login", i_login)
i_token = main_py.find("generate_token(username)", i_login)
pruefe(0 < i_login < i_token < i_record,
       "Benutzergrenze wird VOR record_login geprüft (sonst zählt sie sich selbst mit)")

pruefe("darf_profil_anlegen" in main_py, "Profil-Anlegen prüft die Grenze")
pruefe("darf_skill_aktivieren" in main_py, "Skill-Aktivieren prüft die Grenze")
pruefe(main_py.count("darf_wissen_hinzufuegen") >= 2,
       "beide Upload-Wege prüfen die Wissensgrenze")
i_apply = main_py.find('@app.post("/api/update/apply")')
pruefe("updates_erlaubt" in main_py[i_apply:i_apply + 900], "Update-Knopf ist lizenzpflichtig")
i_set = main_py.find('@app.post("/api/update/settings")')
pruefe("auto_update_erlaubt" in main_py[i_set:i_set + 1500],
       "Auto-Update-Einstellung ist lizenzpflichtig")
i_status = main_py.find('@app.get("/api/update/status")')
pruefe("updates_erlaubt" not in main_py[i_status:i_status + 400],
       "die Update-ANZEIGE bleibt bewusst offen")

pruefe('"data/license.json"' in sandbox_py, "license.json steht in den Sandbox-Sperrlisten")
pruefe(sandbox_py.count('"data/license.json"') >= 2,
       "license.json ist in _APP_DENY_REL UND PRIVATE_FILES")
pruefe("license\\.json" in sandbox_py, "license.json steht im Shell-Muster")
pruefe("license-manager/" in gitignore, "das Ausgabewerkzeug ist von git ausgenommen")
pruefe("data/license.json" in gitignore, "der Lizenz-Zustand ist von git ausgenommen")

manager_py = (WURZEL / "backend" / "skills" / "manager.py").read_text()
pruefe("enabled_at" in manager_py, "enable_skill schreibt einen Zeitstempel")

app_js = (WURZEL / "frontend" / "js" / "app.js").read_text()
settings_html = (WURZEL / "frontend" / "settings.html").read_text()
i18n_js = (WURZEL / "frontend" / "js" / "i18n.js").read_text()
portal_html = (WURZEL / "frontend" / "portal.html").read_text()

for el in ("lic-status", "lic-hwid", "lic-token", "btn-lic-save",
           "btn-lic-check", "btn-lic-clear", "btn-lic-copy-hwid"):
    pruefe(f'id="{el}"' in settings_html, f"Markup: #{el}")
pruefe("_initLicensePanel" in app_js, "app.js verdrahtet das Lizenz-Panel")
pruefe("'license.section'" in i18n_js and i18n_js.count("'license.section'") == 2,
       "i18n-Schlüssel in DE und EN vorhanden")
pruefe('id="pt-lic-banner"' in portal_html and "license_banner" in portal_html,
       "Portal zeigt das Admin-Banner")
pruefe("license_banner" in main_py and "ist_admin" in main_py,
       "/api/me liefert das Banner nur für Administratoren")

# Kein Text im Panel ohne Übersetzung
import re as _re
block = settings_html[settings_html.find('data-i18n="license.section"'):]
block = block[:block.find("</div>\n\n                            </div>")]
ohne = [m for m in _re.findall(r'<(?:button|h4|label|small)[^>]*>', block)
        if "data-i18n" not in m]
pruefe(not ohne, "jedes Textelement im Panel hat einen i18n-Schlüssel", str(ohne[:2]))

# ═══════════════════════════════════════════════════════════════════════════
print("\n\033[1m10. Zusammenspiel mit dem Ausgabewerkzeug (falls vorhanden)\033[0m")

lm_pfad = WURZEL / "license-manager"
if (lm_pfad / "lizenzmanager.py").exists():
    sys.path.insert(0, str(lm_pfad))
    import lizenzmanager as lm  # noqa: E402
    gleich(lm.UUID_NAMESPACE, lic.UUID_NAMESPACE, "gleicher UUID-Namensraum")
    gleich(lm.TOKEN_PREFIX, lic.TOKEN_PREFIX, "gleiches Token-Präfix")
    probe = {"b": 2, "a": "ä"}
    gleich(lm.kanonisch(probe), lic.kanonisch(probe), "gleiche kanonische Form")
    gleich(lm.lizenz_id("abc"), lic.lizenz_id("abc"), "gleiche öffentliche Kennung")
    gleich(tuple(lm.ARTEN), lic.ARTEN, "gleiche Lizenzarten")

    # Automatische Verlaengerung – auf einer WEGWERF-Datenbank, damit der echte
    # Kundenbestand nicht angefasst wird.
    lm.DB_DIR = TMP
    lm.DB_FILE = TMP / "lizenzen-test.json"
    a = lm.anlegen("A GmbH", "IT", "a@a.de", "BASIC", 5, auto_renew=True)
    b = lm.anlegen("B GmbH", "IT", "b@b.de", "BASIC", 5)              # ohne auto_renew
    c = lm.anlegen("C GmbH", "IT", "c@c.de", "BASIC", 0, auto_renew=True)  # unbegrenzt
    gleich([x["firma"] for x in lm.faellige(14)], ["A GmbH"],
           "fällig ist nur die auto_renew-Lizenz mit Ablauf")
    gleich(lm.faellige(1), [], "mit einem Tag Vorlauf ist noch nichts fällig")

    trocken = lm.faellige_verlaengern(14, trocken=True, veroeffentlichen_danach=False)
    gleich(lm.finden(a["uuid"])["gueltig_bis"], a["gueltig_bis"],
           "Trockenlauf ändert nichts")
    gleich(len(trocken["verlaengert"]), 1, "Trockenlauf meldet den Fall trotzdem")

    bericht = lm.faellige_verlaengern(14, veroeffentlichen_danach=False)
    neu = lm.finden(a["uuid"])
    pruefe(neu["gueltig_bis"] > a["gueltig_bis"], "Wartungslauf verlängert",
           f"{a['gueltig_bis']} → {neu['gueltig_bis']}")
    gleich(len(bericht["verlaengert"]), 1, "genau eine Lizenz verlängert")
    gleich(lm.finden(b["uuid"])["gueltig_bis"], b["gueltig_bis"],
           "ohne auto_renew wird nicht verlängert")
    gleich(lm.finden(c["uuid"])["gueltig_bis"], "", "unbegrenzte bleibt unbegrenzt")

    # Ab dem BISHERIGEN Ablauf verlängern, nicht ab heute – sonst wandert der
    # Ablauftag mit jedem Lauf nach vorn und Restlaufzeit geht verloren.
    from datetime import date
    erwartet = (date.fromisoformat(a["gueltig_bis"]) + timedelta(days=5)).isoformat()
    gleich(neu["gueltig_bis"], erwartet, "verlängert ab dem bisherigen Ablauf")

    lm.auto_renew_setzen(a["uuid"], False)
    gleich(lm.faellige(9999), [], "ausgeschaltet ist nichts mehr fällig")

    # Stammdaten nachträglich ändern – die Kennung MUSS bleiben, sonst verliert
    # der Kunde bei einer Umfirmierung Statuseintrag und Hardware-Bindung.
    vorher = lm.finden(b["uuid"])
    umbenannt = lm.stammdaten_aendern(b["uuid"], firma="B Holding SE",
                                      abteilung="Konzern-IT")
    gleich(umbenannt["uuid"], vorher["uuid"], "Umbenennen lässt die Kennung unberührt")
    gleich(lm.lizenz_id(umbenannt["uuid"]), lm.lizenz_id(vorher["uuid"]),
           "damit bleibt auch der Eintrag im Statusdienst derselbe")
    gleich(umbenannt["firma"], "B Holding SE", "neuer Firmenname steht in der Datenbank")
    pruefe(umbenannt["token"] != vorher["token"], "Token wird neu signiert")

    # Ab hier gegen den ECHTEN Root-Schlüssel der Ausgabestelle prüfen (bisher
    # lief alles gegen einen Testschlüssel). Das belegt zugleich, dass die im
    # Repo hinterlegte Datei zum Werkzeug passt – wer `init --kraft` ausführt
    # und `backend/license_root.pub` vergisst, entwertet sonst unbemerkt jede
    # künftig ausgestellte Lizenz.
    merk_root = lic.ROOT_PUB_FILE
    lic.ROOT_PUB_FILE = lm.ROOT_PUB
    echt = lic.token_pruefen(umbenannt["token"])
    lic.ROOT_PUB_FILE = merk_root
    pruefe(echt[0] is not None, "neu signiertes Token ist gültig", echt[1])
    gleich((echt[0] or {}).get("firma"), "B Holding SE",
           "der neue Name steckt im neuen Token")
    gleich((WURZEL / "backend" / "license_root.pub").read_text().strip().splitlines()[-1],
           lm.ROOT_PUB.read_text().strip(),
           "backend/license_root.pub trägt den Root-Schlüssel der Ausgabestelle")
    pruefe(any(h["was"] == "stammdaten" for h in lm.finden(b["uuid"])["historie"]),
           "Umbenennung steht in der Historie")

    try:
        lm.stammdaten_aendern(b["uuid"], mail="kein-at-zeichen")
        pruefe(False, "ungültige Mailadresse wird abgewiesen")
    except ValueError:
        pruefe(True, "ungültige Mailadresse wird abgewiesen")

    # Kollisionsschutz: nach einer Umbenennung darf eine NEUE Lizenz mit den
    # alten Angaben nicht dieselbe Kennung bekommen (in der Statusdatei wären
    # es sonst ein Eintrag, und ein Widerruf träfe beide).
    d = lm.anlegen("B GmbH", "IT", "b@b.de", "BASIC", 5)
    pruefe(d["uuid"] != vorher["uuid"], "Kollisionsschutz vergibt eine eigene Kennung")
    gleich(len(lm.statusdatei_bauen()["eintraege"]),
           len(lm.db_laden()["lizenzen"]), "jede Lizenz hat einen eigenen Eintrag")
    lm.widerrufen(c["uuid"])
    lm.auto_renew_setzen(c["uuid"], True, 30)
    gleich(lm.faellige(9999), [], "widerrufene Lizenzen werden nicht verlängert")
else:
    print("  (übersprungen – license-manager/ ist auf diesem System nicht vorhanden)")

# ═══════════════════════════════════════════════════════════════════════════
import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)

print(f"\n\033[1m{anzahl - len(fehler)}/{anzahl} Prüfungen bestanden\033[0m")
if fehler:
    print("\033[31mFehlgeschlagen:\033[0m")
    for f in fehler:
        print("  - " + f)
sys.exit(1 if fehler else 0)

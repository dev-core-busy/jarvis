#!/usr/bin/env python3
"""Live-Abnahme auf DEV: Zertifikatsanker fuer LLM-Profile ueber die echte API.

Gegenstelle ist Jarvis' EIGENER HTTPS-Port – selbst ausgestelltes Zertifikat,
also genau der Fall, um den es geht. Gemessen wird ueber HTTP am laufenden
Dienst (Probe, Verbindungstest, Anlegen, Entfernen), nicht an einer zweiten
Instanz der Konfiguration.

Aufruf AUF dem Server (stellt ein Token aus, braucht den Hauptschluessel):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_llm_tls_dev.py

Legt EIN Testprofil an und loescht es am Ende wieder (eigenes Material); am
aktiven Profil und an den uebrigen Profilen aendert sich nichts – das wird am
Ende nachgeprueft.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")

BASIS = "https://127.0.0.1"
ZIEL = "https://localhost/api"        # eigener Port, selbst ausgestellt
_KTX = ssl._create_unverified_context()
ok = fail = 0


def check(bed, text, info=""):
    global ok, fail
    if bed:
        ok += 1
        print("  OK   " + text)
    else:
        fail += 1
        print("  FAIL " + text + (f"  [{info}]" if info else ""))


from backend import main as M         # noqa: E402

TOKEN = M.generate_token("jarvis")


def api(methode, pfad, rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + TOKEN)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def zertfehler(txt) -> bool:
    t = str(txt or "").lower()
    return "certificate" in t or "zertifikat" in t or "ssl" in t


# ── Vorgefundener Zustand ───────────────────────────────────────────────
st, vorher = api("GET", "/api/profiles")
if st != 200 or "profiles" not in vorher:
    print(f"ABBRUCH: /api/profiles antwortet {st} – Token oder Dienst fehlt")
    sys.exit(2)
vorher_ids = sorted(p["id"] for p in vorher["profiles"])
vorher_aktiv = vorher.get("active_profile_id")
print(f"vorgefunden: {len(vorher_ids)} Profile, aktiv={vorher_aktiv}")

print("1. Zertifikat abrufen")
st, pr = api("POST", "/api/profiles/zertifikat/probe", {"api_url": ZIEL})
check(st == 200 and pr.get("ok"), "Probe antwortet", f"{st} {pr}")
z = pr.get("zert") or {}
FP = z.get("fingerprint", "")
check(FP.startswith("sha256:") and len(FP) == 71, "Fingerabdruck geliefert", FP)
check("pem" not in z, "Antwort ohne PEM")
check(z.get("system_ok") is False, "gegen certifi nicht bestaetigt (Positivkontrolle)",
      z.get("system_grund"))
if not FP:
    print("ABBRUCH: ohne Fingerabdruck ist keine weitere Messung deutbar")
    sys.exit(2)
st, pr = api("POST", "/api/profiles/zertifikat/probe", {"api_url": "http://localhost/api"})
check(st == 400 and "HTTPS" in str(pr.get("error")), "http-Adresse abgewiesen", pr)

print("2. Verbindungstest mit und ohne Fingerabdruck (ungespeichert)")
basis = {"provider": "openai_compatible", "api_url": ZIEL, "api_key": "", "model": "x"}
st, ohne = api("POST", "/api/profiles/test", basis)
check(not ohne.get("success") and zertfehler(ohne.get("error")),
      "ohne Fingerabdruck scheitert der Test am Zertifikat", ohne.get("error"))
st, mit = api("POST", "/api/profiles/test", dict(basis, cert_fingerprint=FP))
check(not zertfehler(mit.get("error")),
      "mit Fingerabdruck kein Zertifikatsfehler mehr", mit.get("error") or mit.get("message"))
st, falsch = api("POST", "/api/profiles/test", dict(basis, cert_fingerprint="sha256:" + "0" * 64))
check(not falsch.get("success") and "anderes Zertifikat" in str(falsch.get("error")),
      "falscher Fingerabdruck wird im Test benannt", falsch.get("error"))

print("3. Anlegen / Aendern / Entfernen")
neu_id = None
try:
    st, r = api("POST", "/api/profiles",
                dict(basis, name="LLM-TLS-Probe", cert_fingerprint="sha256:" + "1" * 64))
    check(st == 400 and not r.get("success"), "falscher Fingerabdruck: Profil abgelehnt", r)
    st, zw = api("GET", "/api/profiles")
    check(sorted(p["id"] for p in zw.get("profiles", [])) == vorher_ids,
          "…und kein halbes Profil angelegt")

    st, r = api("POST", "/api/profiles", dict(basis, name="LLM-TLS-Probe", cert_fingerprint=FP))
    if st == 403:
        print(f"ABBRUCH: Anlegen verweigert (Lizenz?): {r}")
        sys.exit(2)
    neu_id = (r.get("profile") or {}).get("id")
    c = (r.get("profile") or {}).get("cert") or {}
    check(r.get("success") and c.get("fingerprint") == FP, "Profil mit Anker angelegt", r)
    check(c.get("aktiv") is True, "Anker passt zur Adresse (aktiv)", c)
    check("pem" not in c, "Antwort ohne PEM")

    # Der gespeicherte Anker muss im Test OHNE Formularfeld wirken
    st, gesp = api("POST", "/api/profiles/test", dict(basis, profile_id=neu_id))
    check(not zertfehler(gesp.get("error")),
          "gespeicherter Anker wirkt im Verbindungstest", gesp.get("error"))

    # Speichern mit unveraendertem Fingerabdruck laesst den Anker stehen
    st, r = api("PUT", f"/api/profiles/{neu_id}", {"name": "LLM-TLS-Probe 2",
                                                    "cert_fingerprint": FP})
    c2 = (r.get("profile") or {}).get("cert") or {}
    check(r.get("success") and c2.get("gebunden_am") == c.get("gebunden_am"),
          "unveraendertes Feld: Anker bleibt (kein Neubinden)", c2)

    # Versuch, einen Anker ueber die Whitelist einzuschleusen
    st, r = api("PUT", f"/api/profiles/{neu_id}",
                {"cert": {"host": "localhost", "port": 443, "fingerprint": "sha256:" + "2" * 64,
                          "pem": "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----"}})
    c3 = (r.get("profile") or {}).get("cert") or {}
    check(c3.get("fingerprint") == FP, "'cert' im Rumpf wird ignoriert", c3)

    st, r = api("PUT", f"/api/profiles/{neu_id}", {"cert_fingerprint": ""})
    check(r.get("success") and not (r.get("profile") or {}).get("cert"),
          "leeres Feld entfernt den Anker", r.get("profile", {}).get("cert"))
finally:
    if neu_id:
        st, r = api("DELETE", f"/api/profiles/{neu_id}")
        check(st == 200 and r.get("success"), "Testprofil entfernt", r)

st, nach = api("GET", "/api/profiles")
check(sorted(p["id"] for p in nach.get("profiles", [])) == vorher_ids
      and nach.get("active_profile_id") == vorher_aktiv,
      "Profile und aktives Profil wie vorgefunden")

print(f"\nErgebnis: {ok} OK, {fail} FAIL")
sys.exit(0 if fail == 0 else 1)

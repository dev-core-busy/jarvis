#!/usr/bin/env python3
"""Live auf DEV: arbeitet ein SENSIBLER Chat nur mit internen Modellen?

Zusage (backend/llm_standort.py, 2026-11-24): ein sensibler Lauf wechselt auf
ein internes LLM-Profil; gibt es keines, wird er gesperrt statt gesendet.

Ueber den echten Chat-WebSocket des laufenden Dienstes, drei Phasen:

  A  OHNE internes Profil (Liste "Interne Netze" leer – die Haus-Server
     liegen in einem oeffentlich registrierten Bereich und gelten dann als
     extern): sensibler Lauf -> Sperrtext, keine Antwort vom Modell.
  B  MIT der Liste: das Profil des Benutzers ist intern -> Statuszeile
     "es arbeitet das interne Modell", Antwort kommt.
  C  Benutzer waehlt ein EXTERNES Profil: sensibler Lauf -> Statuszeile
     "<extern> ist extern – es arbeitet stattdessen <intern>", Antwort kommt.
     Positivkontrolle: derselbe Auftrag OHNE Schalter hat keine Statuszeile
     (sonst misst die Suche nach der Zeile nichts).

Danach wird der VORGEFUNDENE Zustand zurueckgestellt (Liste und Profilwahl
des Benutzers) und gegen den Vorzustand verglichen.

Der Netzbereich kommt als Argument (keine Adressen im Repo):

    python3 tests/live_mit_brokercode.py tests/live_llm_standort_dev.py \\
        <benutzer> <netz/praefix>        (root, auf DEV)

Exit 0 = gehalten, 1 = Befund, 2 = konnte nicht laufen.
"""
import asyncio
import ipaddress
import json
import ssl
import sys
import time
import urllib.request
import uuid
from urllib.parse import urlparse

sys.path.insert(0, "/opt/jarvis")
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(c, label, detail=""):
    global _ok, _fail
    if c:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def api(tok, methode, pfad, rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    req = urllib.request.Request("https://127.0.0.1" + pfad, data=daten, method=methode,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_KTX, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


async def lauf(tok, sensibel: bool, sid: str = "") -> str:
    import websockets
    # Die erwartete Antwort (42) steht NICHT im Auftrag – sonst faende die
    # Suche sie schon in der Zeile "Starte Aufgabe: …".
    nachricht = {"type": "task", "text": "Wie viel ist 17 plus 25? Antworte nur mit der Zahl.",
                 "token": tok,
                 "lang": "de", "bestaetigung": True,
                 "session_id": ("sens-" + uuid.uuid4().hex[:12]) if sensibel else sid}
    if sensibel:
        nachricht["sensibel"] = True
    texte = []
    async with websockets.connect("wss://127.0.0.1/ws", ssl=_KTX, max_size=None) as ws:
        await ws.send(json.dumps(nachricht))
        ende = time.time() + 300
        while time.time() < ende:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            except asyncio.TimeoutError:
                continue
            if m.get("type") == "status" and not str(m.get("message", "")).startswith("🚀"):
                texte.append(str(m.get("message", "")))
            if m.get("type") == "agent_event" and m.get("event") == "finished":
                texte.append("<<finished>>")
                break
        await asyncio.sleep(2)
    return "\n".join(texte)


def main(benutzer: str, netz: str) -> int:
    try:
        ipaddress.ip_network(netz, strict=False)
        import websockets  # noqa: F401
    except Exception as e:  # noqa: BLE001
        print(f"ABBRUCH: {e}")
        return 2
    from backend import main as M
    tok = M.generate_token(benutzer)
    if not M.verify_token(tok):
        print("ABBRUCH: Token gilt nicht – nicht ueber als_dienst.sh gestartet")
        return 2
    # Einstellungen braucht einen Administrator, und den gibt es nur ueber
    # das Zahnrad mit eigenem 2FA-Code (BSI M3) – derselbe Weg wie
    # live_cve_bedrohung_dev.py; die Codes liefert live_mit_brokercode.py.
    sys.path.insert(0, "/opt/jarvis/tests/lib")
    from zweifaktor_code import code_quelle
    auth = M._get_user_auth_state(benutzer)
    if not auth.get("totp_enabled"):
        print(f"ABBRUCH: Konto {benutzer} hat keine 2FA – ohne Code keine Admin-Sitzung")
        return 2
    st, r = api(tok, "POST", "/api/admin/erhoehen", {"code": code_quelle(auth.get("totp_secret"))()})
    if st != 200 or not r.get("erhoeht"):
        print(f"ABBRUCH: Erhoehung am Zahnrad gelang nicht -> {st} {str(r)[:200]}")
        return 2
    adm = tok
    st, s = api(adm, "GET", "/api/settings")
    if st != 200 or "standorte" not in s:
        print(f"ABBRUCH: /api/settings {st} ohne standorte – Stand nicht eingespielt?")
        return 2
    vor_netze = s.get("interne_netze", "")
    st, lp = api(tok, "GET", "/api/llm/profiles")
    vor_wahl = lp.get("active_id", "")
    profile = s["profiles"]
    netzobj = ipaddress.ip_network(netz, strict=False)

    def im_netz(p):
        h = urlparse(p.get("api_url") or "").hostname or ""
        try:
            return ipaddress.ip_address(h) in netzobj
        except ValueError:
            return False

    intern = next((p for p in profile if im_netz(p) and p["id"] == vor_wahl), None) \
        or next((p for p in profile if im_netz(p)), None)
    extern = next((p for p in profile if p.get("provider") == "google"), None)
    if not intern:
        print("ABBRUCH: kein Profil mit Adresse im angegebenen Netz")
        return 2
    print(f"Profil intern: {intern['name']} · extern: {extern['name'] if extern else '-'} · "
          f"Wahl vorher: {vor_wahl or '(global)'} · Netze vorher: {vor_netze!r}")
    try:
        # ── A ──
        print("\n── A  ohne internes Profil")
        api(adm, "POST", "/api/settings", {"interne_netze": ""})
        st, s = api(adm, "GET", "/api/settings")
        check(s["standorte"][intern["id"]]["standort"] != "intern",
              "Positivkontrolle: ohne Liste gilt der Haus-Server nicht als intern",
              str(s["standorte"][intern["id"]]))
        t = asyncio.run(lauf(tok, True))
        check("Sensible Daten" in t and "gesperrt" in t, "sensibler Lauf wird gesperrt (Sperrtext im Chat)",
              t[-300:])
        check("42" not in t, "keine Antwort eines Modells")
        check("kein internes KI-Modell" in t or "internes LLM-Profil" in t,
              "der Text nennt den Weg (internes Profil einrichten)")
        # ── B ──
        print("\n── B  mit interner Liste")
        st, r = api(adm, "POST", "/api/settings", {"interne_netze": "quatsch/99"})
        check(st == 400, "ungueltiger Bereich wird mit Grund abgewiesen", f"{st} {r}")
        api(adm, "POST", "/api/settings", {"interne_netze": netz})
        st, s = api(adm, "GET", "/api/settings")
        e = s["standorte"][intern["id"]]
        check(e["standort"] == "intern" and "Netz" in e["grund"], "Haus-Server jetzt intern", str(e))
        api(tok, "POST", f"/api/llm/profiles/{intern['id']}/activate")
        t = asyncio.run(lauf(tok, True))
        check("es arbeitet das interne Modell" in t and intern["name"] in t,
              "Statuszeile nennt das interne Modell")
        check("gesperrt" not in t and "42" in t, "Antwort kommt an", t[-300:])
        # ── C ──
        print("\n── C  externes Profil gewaehlt")
        if not extern:
            print("  (uebersprungen: kein Google-Profil)")
        else:
            st, r = api(tok, "POST", f"/api/llm/profiles/{extern['id']}/activate")
            if st != 200:
                print(f"  (uebersprungen: Profil fuer {benutzer} nicht freigegeben, {st})")
            else:
                # Ein normaler Lauf braucht eine echte Sitzung (wie im Browser);
                # sie wird danach wieder entfernt.
                from backend import chat_sessions as cs
                sid = cs.create_session(benutzer, "standortprobe")["id"]
                try:
                    t0 = asyncio.run(lauf(tok, False, sid))
                finally:
                    cs.delete_session(benutzer, sid)
                # Ob das externe Modell antwortet, ist hier nicht die Frage (auf DEV
                # hat das Google-Profil keinen Schluessel) – nur: ohne Schalter
                # wird NICHT gewechselt und keine Zeile gezeigt.
                check("Sensible Daten" not in t0 and "<<finished>>" in t0,
                      "Positivkontrolle: ohne Schalter keine Statuszeile, Lauf endet", t0[-400:])
                t = asyncio.run(lauf(tok, True))
                check("ist extern" in t and extern["name"] in t and intern["name"] in t,
                      "Statuszeile: extern -> intern gewechselt")
                check("gesperrt" not in t and "42" in t, "Antwort kommt vom internen Modell", t[-300:])
    finally:
        api(adm, "POST", "/api/settings", {"interne_netze": vor_netze})
        if vor_wahl:
            api(tok, "POST", f"/api/llm/profiles/{vor_wahl}/activate")
        st, s = api(adm, "GET", "/api/settings")
        st2, lp = api(tok, "GET", "/api/llm/profiles")
        check(s.get("interne_netze", "") == vor_netze and lp.get("active_id", "") == vor_wahl,
              "Zustand wie vorgefunden (Liste und Profilwahl)",
              f"{s.get('interne_netze')!r} {lp.get('active_id')}")
    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    return 1 if _fail else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))

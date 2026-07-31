#!/usr/bin/env python3
"""Tests fuer die Anwesenheits-Uebersicht (user_sessions.py).

Laeuft ohne pytest:  python3 tests/test_user_sessions.py
"""

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.user_sessions as US  # noqa: E402

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    print(("  ✅ " if cond else "  ❌ ") + name + ((" – " + detail) if detail and not cond else ""))


def section(t):
    print("\n" + t)


def frisch(tmp):
    """Modulzustand auf eine leere Datei im Testordner umbiegen."""
    US.STORE_PATH = Path(tmp) / "user_sessions.json"
    US._users.clear()
    US._loaded = False
    US._dirty = False
    US._last_flush = 0.0


def test_schluessel():
    section("Schluessel-Normalisierung")
    # Dieselbe Person darf nicht mehrfach in der Liste stehen, nur weil sie sich
    # einmal mit UPN und einmal mit blossem Namen angemeldet hat.
    check("Grossschreibung egal", US._key("Andrea.Ladd") == "andrea.ladd")
    check("UPN-Anteil faellt weg", US._key("andrea.ladd@firma.local") == "andrea.ladd")
    check("Domaenen-Praefix faellt weg", US._key("FIRMA\\andrea.ladd") == "andrea.ladd")
    check("leer bleibt leer", US._key("") == "" and US._key(None) == "")


def test_lebenszyklus():
    section("An-/Abmelden und Aktivitaet")
    with tempfile.TemporaryDirectory() as tmp:
        frisch(tmp)
        US.record_login("Anna", "10.0.0.5")
        u = US.list_users()[0]
        check("nach Anmeldung online", u["online"] is True, str(u))
        check("Anmeldezeit gesetzt", u["last_login"] > 0)
        check("Abmeldezeit noch leer", u["last_logout"] == 0)
        check("IP festgehalten", u["last_ip"] == "10.0.0.5", u["last_ip"])
        check("Zaehler bei 1", u["logins"] == 1, str(u["logins"]))

        US.record_logout("anna")
        u = US.list_users()[0]
        # Kern: Abmelden macht SOFORT offline. Wuerde record_logout last_seen
        # hochsetzen, bliebe der Benutzer noch ONLINE_WINDOW lang "online".
        check("nach Abmeldung sofort offline", u["online"] is False, str(u))
        check("Abmeldezeit gesetzt", u["last_logout"] > 0)

        US.touch("anna")
        u = US.list_users()[0]
        check("Aktivitaet nach Abmeldung macht wieder online", u["online"] is True, str(u))

        US.record_login("anna", "10.0.0.6")
        u = US.list_users()[0]
        check("zweite Anmeldung zaehlt hoch", u["logins"] == 2, str(u["logins"]))
        check("alte Abmeldezeit bleibt sichtbar", u["last_logout"] > 0)


def test_anwesenheit_vs_aktivitaet():
    section("Anwesenheit ist nicht Aktivitaet")
    with tempfile.TemporaryDirectory() as tmp:
        frisch(tmp)
        US.record_login("erna")
        u = US.list_users()[0]
        check("nach der Anmeldung noch keine Handlung", u["last_action"] == 0, str(u["last_action"]))
        check("idle_seconds ist None, solange nichts getan wurde", u["idle_seconds"] is None,
              str(u["idle_seconds"]))

        # 50 Hintergrund-Abrufe (so verhaelt sich ein offener Tab)
        for _ in range(50):
            US.touch("erna")
        u = US.list_users()[0]
        check("Polls machen anwesend", u["online"] is True)
        # DAS ist der Kern: ein offener Tab darf NICHT als "aktiv" gelten.
        check("Polls zaehlen NICHT als Handlung", u["last_action"] == 0, str(u["last_action"]))
        check("Handlungszaehler bleibt 0", u["actions"] == 0, str(u["actions"]))

        US.note_action("erna", "Chat-Anfrage")
        u = US.list_users()[0]
        check("Handlung wird festgehalten", u["last_action"] > 0)
        check("Beschriftung wird uebernommen", u["last_action_label"] == "Chat-Anfrage",
              u["last_action_label"])
        check("Handlungszaehler steigt", u["actions"] == 1, str(u["actions"]))
        check("untaetig seit ~0 Sekunden", u["idle_seconds"] is not None and u["idle_seconds"] < 3,
              str(u["idle_seconds"]))
        check("Handlung macht auch anwesend", u["online"] is True)

        # Untaetigkeit waechst, Anwesenheit bleibt
        US._users[US._key("erna")]["last_action"] = time.time() - 1800
        US.touch("erna")
        u = US.list_users()[0]
        check("30 Minuten untaetig, aber online", u["online"] is True and 1750 < u["idle_seconds"] < 1850,
              str(u["idle_seconds"]))
        check("lange Beschriftung wird gekuerzt",
              len(US.note_action("erna", "x" * 200) or "") == 0
              and len(US.list_users()[0]["last_action_label"]) <= 60,
              str(len(US.list_users()[0]["last_action_label"])))


def test_klassifizierung():
    section("Welche Anfrage gilt als Handlung")
    root = Path(__file__).resolve().parent.parent
    src = (root / "backend" / "main.py").read_text(encoding="utf-8")
    check("GET zaehlt nicht als Handlung",
          'request.method in ("POST", "PUT", "PATCH", "DELETE")' in src)
    check("technisches Rauschen ausgenommen", "_ACTION_IGNORE" in src
          and "/api/logout" in src.split("_ACTION_IGNORE = (")[1].split(")")[0])
    check("Beschriftungen vorhanden", "_ACTION_LABELS" in src and '"Chat-Anfrage"' in src)
    check("WebSocket-Chat meldet die Handlung",
          '_user_sessions.note_action(_ws_user, "Chat-Anfrage")' in src)
    check("Benutzer kommt dort aus der WS-Registrierung",
          "_ws_usernames.get(id(ws), \"\")" in src)
    js = (root / "frontend" / "js" / "sessions.js").read_text(encoding="utf-8")
    check("Oberflaeche zeigt Untaetigkeit", "sessions.idle_for" in js and "IDLE_AB" in js)
    check("Oberflaeche zeigt die letzte Handlung", "last_action_label" in js)


def test_online_fenster():
    section("Online-Fenster")
    with tempfile.TemporaryDirectory() as tmp:
        frisch(tmp)
        jetzt = time.time()
        e_frisch = {"last_seen": jetzt - 10, "last_logout": 0}
        e_alt = {"last_seen": jetzt - US.ONLINE_WINDOW - 5, "last_logout": 0}
        e_abgemeldet = {"last_seen": jetzt - 10, "last_logout": jetzt - 5}
        e_wieder_da = {"last_seen": jetzt - 5, "last_logout": jetzt - 10}
        check("kuerzlich aktiv = online", US.is_online(e_frisch, jetzt))
        check("lange still = offline", not US.is_online(e_alt, jetzt))
        check("Abmeldung nach letzter Aktivitaet = offline", not US.is_online(e_abgemeldet, jetzt))
        check("Aktivitaet nach Abmeldung = online", US.is_online(e_wieder_da, jetzt))


def test_persistenz():
    section("Persistenz ueber Neustart")
    with tempfile.TemporaryDirectory() as tmp:
        frisch(tmp)
        US.record_login("bob", "1.2.3.4")
        US.record_logout("bob")
        pfad = US.STORE_PATH
        check("Datei geschrieben", pfad.exists())

        # "Neustart": Speicher leeren, aus der Datei laden
        US._users.clear()
        US._loaded = False
        u = US.list_users()[0]
        check("Benutzer ueberlebt Neustart", u["username"] == "bob", str(u))
        check("Anmeldezeit ueberlebt", u["last_login"] > 0)
        check("Abmeldezeit ueberlebt", u["last_logout"] > 0)
        # Nach einem Neustart ist niemand online, bis wieder eine Anfrage kommt.
        check("nach Neustart offline", u["online"] is False, str(u))

        roh = json.loads(pfad.read_text(encoding="utf-8"))
        check("Dateiformat wie erwartet", "users" in roh and "bob" in roh["users"], str(roh)[:120])


def test_kaputte_datei():
    section("Beschaedigte Datei")
    with tempfile.TemporaryDirectory() as tmp:
        frisch(tmp)
        US.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        US.STORE_PATH.write_text("{kein json", encoding="utf-8")
        US._loaded = False
        # Darf NICHT werfen – eine kaputte Datei ist kein Grund, den Dienst
        # oder jede authentifizierte Anfrage scheitern zu lassen.
        try:
            users = US.list_users()
            ok = True
        except Exception as e:  # noqa: BLE001
            ok = False
            users = str(e)
        check("Start mit kaputter Datei geht", ok, str(users))
        US.record_login("carl")
        check("danach wieder benutzbar", any(u["username"] == "carl" for u in US.list_users()))


def test_drosselung():
    section("Gedrosseltes Schreiben")
    def gespeichert():
        """last_seen aus der DATEI (nicht aus dem Speicher).

        Bewusst ueber den Inhalt statt ueber die mtime: Linux vergibt
        Datei-Zeitstempel aus einer groben Uhr (Jiffies). Zwei Schreibvorgaenge
        im Abstand von 0,3 ms bekommen denselben Wert – ein mtime-Vergleich
        haette hier „nicht geschrieben" gemeldet, obwohl geschrieben wurde.
        """
        return json.loads(US.STORE_PATH.read_text(encoding="utf-8"))["users"]["dora"]["last_seen"]

    with tempfile.TemporaryDirectory() as tmp:
        frisch(tmp)
        US.record_login("dora")          # schreibt sofort
        stand = gespeichert()
        for _ in range(50):
            US.touch("dora")             # darf NICHT 50x schreiben
        check("touch schreibt nicht bei jedem Aufruf", gespeichert() == stand,
              f"{gespeichert()} != {stand}")
        check("im Speicher ist der Wert trotzdem aktuell",
              US.list_users()[0]["last_seen"] > stand)
        US._last_flush = 0.0             # Drosselfenster abgelaufen
        US.touch("dora")
        check("nach Ablauf des Fensters wird geschrieben", gespeichert() > stand,
              f"{gespeichert()} <= {stand}")
        # flush() muss ausstehende Aenderungen sichern (Dienst-Ende)
        US.touch("dora")
        US.flush()
        check("flush() sichert ausstehende Aenderungen", US._dirty is False)


def test_sortierung_und_stats():
    section("Sortierung und Kennzahlen")
    with tempfile.TemporaryDirectory() as tmp:
        frisch(tmp)
        US.record_login("alt")
        US._users[US._key("alt")]["last_seen"] = time.time() - 9999   # laengst weg
        US.record_login("neu")
        US.record_login("api")
        st = US.stats()
        namen = [u["username"] for u in st["users"]]
        check("online zuerst", namen.index("neu") < namen.index("alt"), str(namen))
        check("Online-Zahl stimmt", st["online"] == 2, str(st["online"]))
        check("Gesamtzahl stimmt", st["total"] == 3, str(st["total"]))
        check("Fenster wird mitgeliefert", st["online_window"] == US.ONLINE_WINDOW)
        api = [u for u in st["users"] if u["username"] == "api"][0]
        check("API-Schluessel ist als solcher gekennzeichnet", api["kind"] == "api", str(api))


def test_verdrahtung():
    section("Verdrahtung in main.py und Frontend")
    root = Path(__file__).resolve().parent.parent
    main_src = (root / "backend" / "main.py").read_text(encoding="utf-8")
    check("touch() haengt in require_auth", "_user_sessions.touch(username" in main_src)
    check("record_login im Login-Erfolgspfad", "_user_sessions.record_login(username" in main_src)
    check("/api/logout vorhanden", '@app.post("/api/logout")' in main_src)
    check("/api/sessions vorhanden", '@app.get("/api/sessions")' in main_src)
    check("Uebersicht ist Admin-only",
          '@app.get("/api/sessions")' in main_src
          and "require_local_auth" in main_src.split('@app.get("/api/sessions")')[1].split("\n")[1])
    check("flush beim Herunterfahren", "_user_sessions.flush()" in main_src)

    portal = (root / "frontend" / "portal.html").read_text(encoding="utf-8")
    # Der Knopf muss ZWISCHEN Desktop und Dokumente stehen.
    i_vnc = portal.index("pt-vnc-btn")
    i_usr = portal.index('id="pt-usr-wrap"')
    i_doc = portal.index('id="pt-info-wrap"')
    check("Knopf steht zwischen Desktop und Dokumente", i_vnc < i_usr < i_doc,
          f"vnc={i_vnc} usr={i_usr} doc={i_doc}")
    check("Panel startet versteckt", 'id="pt-usr-wrap" style="display:none;"' in portal)
    check("nur im Admin-Zweig freigeschaltet",
          "window.UserSessions.init()" in portal.split("if (d.is_admin)")[1].split("}")[0]
          or "window.UserSessions.init()" in portal.split("if (d.is_admin)")[1][:1200])
    check("Abmeldung meldet sich beim Server ab", "JarvisSession.logout()" in portal)

    js = (root / "frontend" / "js" / "sessions.js").read_text(encoding="utf-8")
    check("keepalive gesetzt (Navigation bricht die Anfrage sonst ab)", "keepalive: true" in js)
    check("gruene/graue Pille", "is-on" in js and "is-off" in js)

    i18n = (root / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
    for k in ("sessions.title", "sessions.online", "sessions.offline",
              "sessions.last_login", "sessions.last_logout", "sessions.hint"):
        check(f"i18n {k} in DE und EN", i18n.count("'" + k + "'") == 2,
              str(i18n.count("'" + k + "'")))


def main():
    print("=" * 70)
    print("Tests Anwesenheits-Uebersicht")
    print("=" * 70)
    for fn in (test_schluessel, test_lebenszyklus, test_anwesenheit_vs_aktivitaet,
               test_klassifizierung, test_online_fenster, test_persistenz,
               test_kaputte_datei, test_drosselung, test_sortierung_und_stats,
               test_verdrahtung):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(fn.__name__ + " (Ausnahme)", False, str(e))
    ok = sum(1 for _, c, _ in _results if c)
    print("\n" + "=" * 70)
    print(f"ERGEBNIS: {ok}/{len(_results)} Pruefungen bestanden")
    print("=" * 70)
    if ok != len(_results):
        for n, c, d in _results:
            if not c:
                print(f"  FEHLGESCHLAGEN: {n} – {d}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

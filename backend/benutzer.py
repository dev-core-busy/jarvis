"""Benutzernamen: EINE Normalisierung, EIN Pfadteil.

WARUM DIESES MODUL EXISTIERT (Vorfall 2026-09-07): derselbe Mensch hatte je
Tippform des Anmeldefelds ZWEI Ablagen. Gemeldet als
``memory_nexus_karsten_moeller.json`` neben ``memory_karsten_moeller.json``;
auf DEV nachgemessen betraf es fuenf Ablagen mit FUENF verschiedenen
Sanitizern, von denen keiner den Domaenenanteil entfernte:

    data/memory_<u>.json          [^a-zA-Z0-9_-] -> _
    data/chats/<u>/               behalte alnum + ._-@
    data/chat_history/<u>.json    lower, behalte alnum + ._-@
    data/sap_instructions/<u>.md  lower, [^A-Za-z0-9_.-] -> _
    data/support_instructions/... behalte alnum + ._-

Der Schaden ist nicht der Plattenplatz, sondern der VERLUST: wer sich einmal
als ``nexus\\x`` und einmal als ``x`` anmeldet, findet sein Gedaechtnis und
seinen Chatverlauf nicht mehr – ohne Fehlermeldung, es sieht wie ein leerer
Neuanfang aus.

Neun Module hatten die richtige Normalisierung laengst (``norm_user`` in
audit_log, conv_log, security_guard, short_tracks, mail_/sap_/vemas_/
jira_accounts, ``_key`` in user_sessions) – ausgerechnet die Stellen, die auf
die PLATTE schreiben, hatten sie nicht. Deshalb liegt sie ab jetzt HIER, und
``tests/test_benutzer_pfade.py`` haelt als REGEL fest, dass kein Modul einen
Benutzerpfad mit eigenem Sanitizer bildet.
"""

_KANAL_PRAEFIXE = ("wa:", "tg:", "api:")


def norm_user(name: str) -> str:
    """Benutzername auf den blossen Kontonamen: ohne ``DOMAIN\\``, ohne
    ``@domain``, klein.

    Kanal-Kennungen (``wa:``/``tg:``/``api:``) bleiben GANZ – sie tragen keinen
    Domaenenanteil, und ein Zerlegen am Doppelpunkt wuerde sie ruinieren
    (``api:Externes System`` waere sonst schlicht ``api``, und alle
    API-Quellen fielen auf EINE Ablage zusammen).

    Zeichengleich mit den neun vorhandenen ``norm_user``-Fassungen; ein Test
    fuehrt alle gegen dieselben Eingaben aus und vergleicht das Ergebnis –
    laufen sie auseinander, bedeutet derselbe Name in zwei Modulen etwas
    Verschiedenes.
    """
    s = (name or "").strip()
    if not s or ":" in s:
        return s.lower()
    return s.split("@")[0].split("\\")[-1].strip().lower()


def pfad_teil(name: str, fallback: str = "anonymous") -> str:
    """Datei-/ordnersicherer Namensteil fuer die Ablage EINES Benutzers.

    Erst normalisieren, dann entschaerfen – die Reihenfolge ist die Semantik:
    wer nur entschaerft, macht aus ``nexus\\x`` ein ``nexusx`` und hat eine
    zweite Ablage fuer denselben Menschen.

    Der PUNKT bleibt erhalten. Das ist eine Migrationsentscheidung und keine
    Geschmacksfrage: ``data/chats/andreas.bender`` und
    ``data/chat_history/andreas.bender.json`` gibt es so schon, ein Umstellen
    auf Unterstriche haette VIER Ablagen umbenannt statt einer. So aendert sich
    nur ``memory_<u>.json`` (Punkt statt Unterstrich), und das nimmt die
    Migration mit.

    Traversal ist ausgeschlossen: ``/``, ``\\`` und ``..`` koennen das Ergebnis
    nicht ueberleben – ``.`` bleibt zwar erlaubt, aber ein reiner Punktname
    faellt auf den Fallback (sonst waere ``..`` ein gueltiger Pfadteil).
    """
    s = norm_user(name)
    out = "".join(c if (c.isalnum() or c in "._-") else "_" for c in s)
    # Mehrfache Unterstriche zusammenfassen: aus "api:Externes System" wird
    # sonst "api_externes_system" mit wechselnder Zahl von Trennern, je nachdem
    # wie viele Sonderzeichen der Absender im Namen hatte.
    while "__" in out:
        out = out.replace("__", "_")
    out = out.strip("_")
    # Ein Name, der nur aus Punkten besteht, ist kein Name (und ".."/"." waeren
    # Pfadwechsel).
    if not out or set(out) <= {"."}:
        return fallback
    return out

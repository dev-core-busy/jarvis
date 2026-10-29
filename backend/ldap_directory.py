"""AD/LDAP-Verzeichnis durchsuchen für den User-/Gruppen-Browser (Admin-UI).

Read-only. Bind-Reihenfolge: explizit übergebene Credentials (On-Demand-
Admin-Passwort) → sonst Service-Konto (ad_bind_user/ad_bind_password). Ist
weder das eine noch das andere vorhanden, wird RuntimeError("NO_CREDENTIALS")
geworfen, damit die UI nach dem Passwort fragen kann.
"""
from backend.config import config


def _base_dn(domain):
    return ",".join("DC=" + p for p in domain.split(".")) if domain else ""


def _esc(s):
    """LDAP-Filter-Escaping (RFC 4515) – verhindert LDAP-Injection."""
    return ((s or "")
            .replace("\\", "\\5c").replace("*", "\\2a")
            .replace("(", "\\28").replace(")", "\\29").replace("\x00", "\\00"))


def _bind(bind_user=None, bind_password=None):
    """Baut eine gebundene, read-only ldap3-Verbindung auf. Gibt (conn, base_dn)
    zurück. Wirft RuntimeError('NO_CREDENTIALS' | 'BIND_FAILED' | 'TLS_FAILED: …'
    | Klartext)."""
    import ldap3

    ad_server = (config.get_setting("ad_server", "") or "").strip()
    ad_domain = (config.get_setting("ad_domain", "") or "").strip()
    if not ad_server or not ad_domain:
        raise RuntimeError("AD ist nicht konfiguriert (Server/Domain fehlen).")

    user = (bind_user or "").strip()
    pw = bind_password or ""
    if not user:
        user = (config.get_setting("ad_bind_user", "") or "").strip()
        pw = config.get_setting("ad_bind_password", "") or ""
        if not user:
            raise RuntimeError("NO_CREDENTIALS")

    # Bind-Form: reiner sAMAccountName -> UPN (user@domain); DN/UPN/DOMAIN\user unverändert
    if "@" not in user and "\\" not in user and "=" not in user:
        user = user + "@" + ad_domain

    # TLS ist Pflicht, das Zertifikat wird geprueft (BSI H5) – bis 2026-09-29
    # band diese Stelle nach gescheitertem StartTLS still im Klartext.
    from backend import ldap_tls
    try:
        conn = ldap_tls.verbinden(ad_server, user, pw, timeout=6)
    except ldap_tls.TlsFehler as e:
        raise RuntimeError("TLS_FAILED: " + str(e)[:160])
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("BIND_FAILED: " + str(e)[:120])
    try:
        ok = conn.bind()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("BIND_FAILED: " + str(e)[:120])
    if not ok:
        raise RuntimeError("BIND_FAILED")
    return conn, _base_dn(ad_domain)


# ── Weitere ldap3-Zugriffe der Anwendung (aus main.py hierher, 2026-10-21) ──────
# ldap3 ist seit 2021 ohne neue Fassung. Damit ein spaeterer Tausch auf diese
# Datei und backend/ldap_tls.py begrenzt bleibt, liegen die direkten Aufrufe hier.

def erreichbar(ad_server, timeout=5):
    """Reiner Verbindungstest zum DC – OHNE Bind, ohne Anmeldedaten. Oeffnet und
    schliesst die Verbindung (vorher blieb je Klick auf "AD testen" ein Socket
    offen). Wirft ImportError, wenn ldap3 fehlt, sonst die Netzwerk-Ausnahme."""
    import ldap3
    server = ldap3.Server(ad_server, get_info=ldap3.NONE, connect_timeout=timeout)
    conn = ldap3.Connection(server, auto_bind=False)
    try:
        conn.open()
    finally:
        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass


def sperrrichtlinie():
    """Sperrrichtlinie der Domaene ueber das Dienstkonto: {schwelle, fenster_s},
    None ohne Domaenenobjekt. Wirft RuntimeError, wenn Bind oder Suche scheitern.

    ``lockoutThreshold`` = Fehlversuche bis zur Sperre (0 = nie),
    ``lockOutObservationWindow`` = Zeitraum, in dem sie zaehlen. ldap3 liefert
    das Fenster je nach Schema als ``timedelta`` oder als negative Zahl in
    100-ns-Schritten – beides wird verstanden."""
    import ldap3
    conn, base_dn = _bind()
    try:
        conn.search(search_base=base_dn, search_filter="(objectClass=domain)",
                    search_scope=ldap3.BASE,
                    attributes=["lockoutThreshold", "lockOutObservationWindow"])
        if not conn.entries:
            return None
        e = conn.entries[0]
        schwelle = int(e["lockoutThreshold"].value or 0) if "lockoutThreshold" in e else 0
        roh = e["lockOutObservationWindow"].value if "lockOutObservationWindow" in e else 0
        if hasattr(roh, "total_seconds"):
            fenster = abs(roh.total_seconds())
        else:
            fenster = abs(int(roh or 0)) / 1e7
        return {"schwelle": schwelle, "fenster_s": fenster}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Suche gescheitert ({e})")
    finally:
        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass


def _val(entry, attr):
    try:
        if attr in entry and entry[attr]:
            return str(entry[attr])
    except Exception:  # noqa: BLE001
        pass
    return ""


def search_users(query, bind_user=None, bind_password=None, limit=100):
    q = _esc((query or "").strip())
    conn, base = _bind(bind_user, bind_password)
    try:
        flt = "(&(objectCategory=person)(objectClass=user)(!(objectClass=computer))(sAMAccountName=*)"
        if q:
            flt += ("(|(sAMAccountName=*%s*)(displayName=*%s*)(mail=*%s*)(userPrincipalName=*%s*))"
                    % (q, q, q, q))
        flt += ")"
        conn.search(search_base=base, search_filter=flt,
                    attributes=["sAMAccountName", "displayName", "mail"],
                    paged_size=limit)
        out = []
        for e in conn.entries:
            sam = _val(e, "sAMAccountName")
            if not sam:
                continue
            out.append({"sam": sam,
                        "display": _val(e, "displayName") or sam,
                        "mail": _val(e, "mail")})
        out.sort(key=lambda x: x["display"].lower())
        return out[:limit]
    finally:
        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass


def group_members(group, bind_user=None, bind_password=None, limit=500):
    """Listet die DIREKTEN Mitglieder einer Gruppe (Benutzer und verschachtelte
    Gruppen). Gibt ``{"cn","dn","members":[{sam,display,mail,kind}],"count"}`` zurück.

    ``group`` darf ein DN ODER ein blosser CN sein – die Token-Liste im Frontend
    erlaubt beides (Auswahl liefert den DN, manuelle Eingabe oft nur den Namen).
    Ist es kein DN (kein ``=`` enthalten), wird erst der DN dazu gesucht.

    Bewusst ueber ``(memberOf=<dn>)`` statt ueber das ``member``-Attribut der
    Gruppe: dessen Werte liefert AD ab ~1500 Eintraegen nur in Haeppchen
    (Range-Retrieval), die Liste waere dann stillschweigend unvollstaendig.

    Bewusst NUR direkte Mitgliedschaften: genau die prueft auch die Anmeldung
    (``_ad_user_allowed`` vergleicht ``memberOf``). Eine Liste, die zusaetzlich
    verschachtelte Mitglieder zeigt, wuerde Zugriff versprechen, den der Login
    verweigert. Verschachtelte Gruppen erscheinen daher als Eintrag mit
    ``kind="group"`` – sichtbar, aber nicht als Benutzer ausgewiesen.
    Ebenfalls nicht enthalten: Mitglieder ueber die PRIMAERGRUPPE
    (``primaryGroupID``, typisch "Domaenen-Benutzer") – die stehen bei AD nicht
    in ``memberOf``, weder hier noch beim Login.
    """
    conn, base = _bind(bind_user, bind_password)
    try:
        g = (group or "").strip()
        dn, cn = "", ""
        if "=" in g:
            dn = g
        else:
            # Blosser Name → DN nachschlagen
            conn.search(search_base=base,
                        search_filter="(&(objectClass=group)(cn=%s))" % _esc(g),
                        attributes=["cn", "distinguishedName"], paged_size=2)
            if not conn.entries:
                raise RuntimeError("Gruppe '%s' nicht gefunden." % g[:80])
            dn = _val(conn.entries[0], "distinguishedName") or str(conn.entries[0].entry_dn)
            cn = _val(conn.entries[0], "cn")
        if not cn:
            cn = dn.split(",")[0][3:] if dn[:3].lower() == "cn=" else dn.split(",")[0]

        conn.search(search_base=base,
                    search_filter="(memberOf=%s)" % _esc(dn),
                    attributes=["sAMAccountName", "displayName", "mail", "objectClass"],
                    paged_size=limit)
        out = []
        for e in conn.entries:
            classes = []
            try:
                if "objectClass" in e and e["objectClass"]:
                    classes = [str(c).lower() for c in e["objectClass"].values]
            except Exception:  # noqa: BLE001
                pass
            sam = _val(e, "sAMAccountName")
            out.append({"sam": sam,
                        "display": _val(e, "displayName") or sam or str(e.entry_dn),
                        "mail": _val(e, "mail"),
                        "kind": "group" if "group" in classes else "user"})
        # Benutzer zuerst, danach verschachtelte Gruppen – jeweils alphabetisch
        out.sort(key=lambda x: (x["kind"] != "user", x["display"].lower()))
        return {"cn": cn, "dn": dn, "members": out[:limit], "count": len(out)}
    finally:
        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass


def _dn_wert(v):
    """Escapes eines DN-Werts aufloesen (RFC 4514): ``\\,`` -> ``,``; ``\\c3\\a4`` sind
    UTF-8-Bytes (-> ``ae``-Umlaut) und werden deshalb als Bytes gesammelt."""
    v = v or ""
    out = bytearray()
    i = 0
    while i < len(v):
        if v[i] == "\\" and i + 1 < len(v):
            h = v[i + 1:i + 3]
            if len(h) == 2 and all(x in "0123456789abcdefABCDEF" for x in h):
                out.append(int(h, 16))
                i += 3
                continue
            out += v[i + 1].encode("utf-8")
            i += 2
            continue
        out += v[i].encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def dn_lage(dn):
    """Ort eines Objekts aus seinem DN: ``{"name", "ou", "container", "domaene"}``.

    ``ou`` ist der Pfad aus OUs/Containern von AUSSEN nach INNEN (so liest ihn ein
    Mensch in "Active Directory-Benutzer und -Computer"), ``container`` der DN ohne
    den eigenen RDN. Kommata im Namen (``CN=Muster\\, Erika``) bleiben Teil des
    Namens – deshalb ueber ``parse_dn`` und nicht ueber ``split(",")``."""
    from ldap3.utils.dn import parse_dn
    leer = {"name": dn or "", "ou": [], "container": "", "domaene": ""}
    try:
        teile = parse_dn(dn or "")
    except Exception:  # noqa: BLE001 – kaputter DN: roh zeigen statt werfen
        return leer
    if not teile:
        return leer
    ou = [_dn_wert(w) for a, w, _s in teile[1:] if a.upper() in ("OU", "CN")]
    return {"name": _dn_wert(teile[0][1]),
            "ou": list(reversed(ou)),
            "container": ",".join("%s=%s" % (a, w) for a, w, _s in teile[1:]),
            "domaene": ".".join(_dn_wert(w) for a, w, _s in teile if a.upper() == "DC")}


def _sid_text(roh):
    """objectSid als ``S-1-5-21-…``. ldap3 liefert ihn ohne Schema (``get_info=NONE``,
    siehe ldap_tls) als Bytes, mit Schema schon als Text."""
    if isinstance(roh, str):
        return roh if roh.startswith("S-") else ""
    if not isinstance(roh, (bytes, bytearray)) or len(roh) < 8:
        return ""
    b = bytes(roh)
    anzahl = b[1]
    if len(b) < 8 + 4 * anzahl:
        return ""
    autoritaet = int.from_bytes(b[2:8], "big")
    unter = [str(int.from_bytes(b[8 + 4 * i:12 + 4 * i], "little")) for i in range(anzahl)]
    return "S-%d-%d%s" % (b[0], autoritaet, "".join("-" + u for u in unter))


def _benutzer_filter(benutzer):
    """Suchfilter fuer EINEN Benutzer aus dem, was ein Admin eintippt:
    ``name``, ``DOMAENE\\name``, ``name@domaene`` (UPN) oder eine Mailadresse."""
    b = (benutzer or "").strip()
    if "\\" in b:
        b = b.split("\\", 1)[1]
    q = _esc(b)
    basis = "(&(objectCategory=person)(objectClass=user)%s)"
    if "@" in b:
        return basis % ("(|(userPrincipalName=%s)(mail=%s)(proxyAddresses=smtp:%s))" % (q, q, q))
    return basis % ("(sAMAccountName=%s)" % q)


def user_groups(benutzer, bind_user=None, bind_password=None):
    """Wo steht ein Benutzer im Verzeichnis, und in welchen Gruppen ist er?

    Antwort ``{"sam","display","mail","upn","dn","lage","direkt","indirekt",
    "primaer"}`` – ``lage`` aus ``dn_lage``; ``direkt``/``indirekt`` je
    ``[{cn, dn, lage}]``, alphabetisch.

    ``direkt`` ist ``memberOf`` – GENAU die Liste, die auch die Anmeldung und
    die Bereichs-Freigaben pruefen (``_ad_user_allowed``). ``indirekt`` sind
    Gruppen, in die der Benutzer nur ueber eine verschachtelte Gruppe gelangt
    (``LDAP_MATCHING_RULE_IN_CHAIN``); sie stehen hier, damit man sieht, warum
    jemand "doch in der Gruppe ist" – fuer die Freigaben zaehlen sie NICHT.
    ``indirekt`` ist ``None``, wenn das Verzeichnis die Kettenabfrage nicht
    beantwortet hat (unbekannt ist nicht leer). ``primaer`` ist die Gruppe aus
    ``primaryGroupID`` (typisch "Domaenen-Benutzer"); sie steht bei AD nie in
    ``memberOf`` und zaehlt deshalb ebenfalls nicht. ``None``, wenn nicht
    aufloesbar.

    Wirft RuntimeError, wenn der Benutzer nicht gefunden wird oder der Name
    mehrdeutig ist (eine Mailadresse kann an zwei Konten haengen)."""
    if not (benutzer or "").strip():
        raise RuntimeError("Kein Benutzer angegeben.")
    conn, base = _bind(bind_user, bind_password)
    try:
        conn.search(search_base=base, search_filter=_benutzer_filter(benutzer),
                    attributes=["sAMAccountName", "displayName", "mail", "userPrincipalName",
                                "distinguishedName", "memberOf", "primaryGroupID", "objectSid"],
                    paged_size=3)
        treffer = list(conn.entries)
        if not treffer:
            raise RuntimeError("Benutzer '%s' nicht im Verzeichnis gefunden." % benutzer.strip()[:120])
        if len(treffer) > 1:
            raise RuntimeError("'%s' passt auf mehrere Konten (%s) – bitte den Anmeldenamen angeben."
                               % (benutzer.strip()[:120],
                                  ", ".join(_val(e, "sAMAccountName") for e in treffer)))
        e = treffer[0]
        dn = _val(e, "distinguishedName") or str(e.entry_dn)

        def gruppe(gdn):
            lage = dn_lage(gdn)
            return {"cn": lage["name"], "dn": gdn, "lage": lage}

        direkt_dns = []
        try:
            if "memberOf" in e and e["memberOf"]:
                direkt_dns = [str(g) for g in e["memberOf"].values]
        except Exception:  # noqa: BLE001
            direkt_dns = []
        direkt = sorted((gruppe(g) for g in direkt_dns), key=lambda g: g["cn"].lower())

        indirekt = None
        try:
            conn.search(search_base=base,
                        search_filter="(&(objectClass=group)(member:1.2.840.113556.1.4.1941:=%s))"
                                      % _esc(dn),
                        attributes=["distinguishedName"], paged_size=1000)
            schon = {g.lower() for g in direkt_dns}
            alle = [_val(g, "distinguishedName") or str(g.entry_dn) for g in conn.entries]
            indirekt = sorted((gruppe(g) for g in alle if g.lower() not in schon),
                              key=lambda g: g["cn"].lower())
        except Exception:  # noqa: BLE001 – Kettenabfrage ist Zusatz, kein Muss
            indirekt = None

        primaer = None
        try:
            rid = int(str(_val(e, "primaryGroupID")) or "0")
            sid = _sid_text(e["objectSid"].value) if "objectSid" in e else ""
            if rid and sid.count("-") >= 3:
                gruppen_sid = sid.rsplit("-", 1)[0] + "-" + str(rid)
                conn.search(search_base=base,
                            search_filter="(&(objectClass=group)(objectSid=%s))" % _esc(gruppen_sid),
                            attributes=["distinguishedName"], paged_size=1)
                if conn.entries:
                    primaer = gruppe(_val(conn.entries[0], "distinguishedName")
                                     or str(conn.entries[0].entry_dn))
        except Exception:  # noqa: BLE001
            primaer = None

        return {"sam": _val(e, "sAMAccountName"),
                "display": _val(e, "displayName") or _val(e, "sAMAccountName"),
                "mail": _val(e, "mail"), "upn": _val(e, "userPrincipalName"),
                "dn": dn, "lage": dn_lage(dn),
                "direkt": direkt, "indirekt": indirekt, "primaer": primaer}
    finally:
        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass


def search_groups(query, bind_user=None, bind_password=None, limit=100):
    q = _esc((query or "").strip())
    conn, base = _bind(bind_user, bind_password)
    try:
        if q:
            flt = "(&(objectClass=group)(|(cn=*%s*)(sAMAccountName=*%s*)(description=*%s*)))" % (q, q, q)
        else:
            flt = "(objectClass=group)"
        conn.search(search_base=base, search_filter=flt,
                    attributes=["cn", "distinguishedName", "description"],
                    paged_size=limit)
        out = []
        for e in conn.entries:
            dn = _val(e, "distinguishedName") or str(e.entry_dn)
            cn = _val(e, "cn") or dn
            out.append({"cn": cn, "dn": dn, "desc": _val(e, "description")})
        out.sort(key=lambda x: x["cn"].lower())
        return out[:limit]
    finally:
        try:
            conn.unbind()
        except Exception:  # noqa: BLE001
            pass

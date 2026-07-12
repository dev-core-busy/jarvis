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
    zurück. Wirft RuntimeError('NO_CREDENTIALS' | 'BIND_FAILED' | Klartext)."""
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

    use_ssl = ad_server.lower().startswith("ldaps://")
    server = ldap3.Server(ad_server, use_ssl=use_ssl, get_info=ldap3.NONE, connect_timeout=6)
    conn = ldap3.Connection(server, user=user, password=pw, auto_bind=False)
    if not use_ssl:
        try:
            conn.open()
            conn.start_tls()
        except Exception:
            pass  # Fallback auf Plain, falls der DC kein StartTLS kann
    try:
        ok = conn.bind()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("BIND_FAILED: " + str(e)[:120])
    if not ok:
        raise RuntimeError("BIND_FAILED")
    return conn, _base_dn(ad_domain)


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

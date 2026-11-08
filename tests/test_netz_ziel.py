#!/usr/bin/env python3
"""Waechter: SSRF-Schranke fuer Server-Abrufe (backend/netz_ziel.py, Befund B4).

Gemessen wird die WIRKUNG an der echten Funktion ``sicher_holen`` – mit
umgebogener Namensaufloesung (``socket.getaddrinfo``) und einem
httpx-MockTransport, der jede tatsaechlich abgeschickte Anfrage protokolliert:

  1. Adressklassen: intern/loopback/link-local/IPv4-gemappt/eigene gesperrt.
  2. Festnageln: die Anfrage geht an die GEPRUEFTE IP, Host-Kopf und SNI tragen
     den Namen (gegen DNS-Rebinding).
  3. Ein Name mit EINER internen Adresse unter mehreren wird abgewiesen.
  4. Weiterleitung auf ein internes Ziel: abgewiesen, das Ziel nie kontaktiert.
  5. Relative Weiterleitung wird gefolgt, resp.url ist die echte Adresse.
  6. Die drei Aufrufer (web_extractor, short_tracks_runner, Bildsuche) laufen
     WIRKLICH ueber die Schranke (Aufruf, nicht Vorkommen).

Keine echte Netzverbindung, kein ``backend.config``.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

try:
    import httpx
except ImportError:
    print("ABBRUCH: httpx fehlt", flush=True)
    sys.exit(2)

if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist geladen", flush=True)
    sys.exit(2)

from backend import netz_ziel as nz  # noqa: E402

OK = FAIL = 0


def check(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


# Oeffentliche Probeadressen OHNE Literal (Repo-Regel: keine IPs im Code).
OEFF4 = str(ipaddress.IPv4Address((11 << 24) + 1))
OEFF4B = str(ipaddress.IPv4Address((11 << 24) + 2))
OEFF6 = str(ipaddress.IPv6Address((0x2a00 << 112) + 1))
LOOP = str(ipaddress.IPv4Address((127 << 24) + 1))
META = str(ipaddress.IPv4Address((169 << 24) + (254 << 16) + (169 << 8) + 254))

# ── Positivkontrolle der Probeadressen ─────────────────────────────────────
if not (ipaddress.ip_address(OEFF4).is_global and ipaddress.ip_address(OEFF6).is_global):
    print("ABBRUCH: Probeadressen sind nicht oeffentlich", flush=True)
    sys.exit(2)

# ── Namensaufloesung umbiegen ──────────────────────────────────────────────
DNS: dict[str, list[str]] = {}
DNS_AUFRUFE: list[str] = []
_echt_gai = socket.getaddrinfo


def _gai(host, port, *a, **k):
    DNS_AUFRUFE.append(host)
    try:
        ipaddress.ip_address(host)
        adressen = [host]
    except ValueError:
        if host not in DNS:
            raise socket.gaierror(-2, "Name or service not known")
        adressen = DNS[host]
    raus = []
    for adr in adressen:
        fam = socket.AF_INET6 if ":" in adr else socket.AF_INET
        sa = (adr, port or 0, 0, 0) if fam == socket.AF_INET6 else (adr, port or 0)
        raus.append((fam, socket.SOCK_STREAM, 6, "", sa))
    return raus


socket.getaddrinfo = _gai

# ── HTTP umbiegen: jede Anfrage wird protokolliert ─────────────────────────
ANFRAGEN: list[dict] = []
ANTWORTEN: dict = {}       # (host_kopf, pfad) -> (status, headers, body)


def _handler(req: httpx.Request):
    ANFRAGEN.append({"ip": req.url.host, "host": req.headers.get("host"),
                     "sni": req.extensions.get("sni_hostname"),
                     "pfad": req.url.path, "schema": req.url.scheme})
    st, kopf, body = ANTWORTEN.get((req.headers.get("host"), req.url.path),
                                   (200, {"content-type": "text/plain"}, b"hallo"))
    return httpx.Response(st, headers=kopf, content=body)


_EchtClient = httpx.AsyncClient


class _MockClient(_EchtClient):
    def __init__(self, *a, **k):
        k.pop("transport", None)
        k["transport"] = httpx.MockTransport(_handler)
        super().__init__(*a, **k)


httpx.AsyncClient = _MockClient
nz._eigene_cache = set()


def holen(url, **k):
    return asyncio.run(nz.sicher_holen(url, **k))


def fehler(url, **k):
    try:
        holen(url, **k)
        return ""
    except nz.ZielFehler as e:
        return str(e) or "ZielFehler"


try:
    # ── Positivkontrolle: der Messaufbau holt ueberhaupt etwas ─────────────
    DNS["seite.beispiel.de"] = [OEFF4]
    r = holen("https://seite.beispiel.de/a?x=1")
    if not ANFRAGEN or r.status_code != 200:
        print("ABBRUCH: Positivkontrolle – keine Anfrage durch den Mock", flush=True)
        sys.exit(2)

    print("\n1. Adressklassen")
    for adr, name in ((LOOP, "loopback"), (META, "Cloud-Metadaten/link-local"),
                      ("::1", "IPv6-loopback"), ("::ffff:" + LOOP, "IPv4-gemappt loopback"),
                      ("fc00::1", "IPv6 ULA"), ("0.0.0.0", "unspezifiziert"),
                      (str(ipaddress.IPv4Address((10 << 24) + 5)), "privat 10/8"),
                      (str(ipaddress.IPv4Address((100 << 24) + (64 << 16) + 1)), "CGNAT"),
                      (str(ipaddress.IPv4Address((224 << 24) + 1)), "multicast")):
        check(nz.adresse_sperrgrund(adr, set()) != "", "gesperrt: %s" % name)
    check(nz.adresse_sperrgrund(OEFF4, set()) == "", "oeffentliche IPv4 erlaubt")
    check(nz.adresse_sperrgrund(OEFF6, set()) == "", "oeffentliche IPv6 erlaubt")
    check(nz.adresse_sperrgrund(OEFF4B, {OEFF4B}) == "eigen", "eigene Adresse gesperrt")
    # Ab Python 3.13 beurteilt ipaddress gemappte Adressen fuer is_private &
    # Co. selbst als IPv4 – fuer die EIGENEN Adressen gilt das nicht, dort
    # traegt allein das Entpacken in netz_ziel.
    check(nz.adresse_sperrgrund("::ffff:" + OEFF4B, {OEFF4B}) == "eigen",
          "eigene Adresse auch IPv4-gemappt gesperrt")

    print("\n2. Festnageln auf die gepruefte Adresse")
    a = ANFRAGEN[0]
    check(a["ip"] == OEFF4, "Verbindung geht an die gepruefte IP (nicht an den Namen)")
    check(a["host"] == "seite.beispiel.de", "Host-Kopf traegt den Namen")
    check(a["sni"] == "seite.beispiel.de", "SNI/Zertifikatspruefung auf den Namen")
    check(str(r.url) == "https://seite.beispiel.de/a?x=1", "resp.url ist die echte Adresse")
    ANFRAGEN.clear()
    DNS["v6.beispiel.de"] = [OEFF6]
    holen("http://v6.beispiel.de:8080/p")
    a = ANFRAGEN[0] if ANFRAGEN else {}
    check(a.get("ip") == OEFF6, "IPv6-Ziel festgenagelt")
    check(a.get("host") == "v6.beispiel.de:8080", "Host-Kopf mit Port")
    check(a.get("sni") is None, "kein SNI bei http")
    # DNS-Rebinding: Aufloesung wird nur EINMAL (bei der Pruefung) befragt
    ANFRAGEN.clear()
    DNS_AUFRUFE.clear()
    holen("https://seite.beispiel.de/b")
    check(DNS_AUFRUFE.count("seite.beispiel.de") == 1,
          "Name wird genau einmal aufgeloest (kein zweites Nachschlagen beim Verbinden)")

    print("\n3. Ein Name, eine interne Adresse darunter")
    ANFRAGEN.clear()
    DNS["gemischt.beispiel.de"] = [OEFF4, LOOP]
    f = fehler("https://gemischt.beispiel.de/")
    check("intern" in f, "abgewiesen (eine interne Adresse genuegt)")
    check(not ANFRAGEN, "keine Anfrage abgeschickt")
    DNS["eigen.beispiel.de"] = [OEFF4B]
    nz._eigene_cache = {OEFF4B}
    f = fehler("https://eigen.beispiel.de/")
    check("Jarvis-Server selbst" in f, "eigene Serveradresse abgewiesen")
    nz._eigene_cache = set()
    check("Schema" in fehler("ftp://seite.beispiel.de/x") or "http" in fehler("ftp://seite.beispiel.de/x"),
          "nur http/https")
    check("aufloesbar" in fehler("https://gibtsnicht.beispiel.de/"), "unaufloesbar abgewiesen")
    check(fehler("http://" + LOOP + ":9081/") != "", "IP-Literal intern abgewiesen")

    print("\n4. Weiterleitung auf internes Ziel")
    ANFRAGEN.clear()
    DNS["meta.beispiel.de"] = [META]
    ANTWORTEN[("seite.beispiel.de", "/umleitung")] = (
        302, {"location": "http://meta.beispiel.de/latest/meta-data/"}, b"")
    f = fehler("https://seite.beispiel.de/umleitung")
    check("intern" in f, "Weiterleitung auf link-local abgewiesen")
    check(len(ANFRAGEN) == 1 and all(x["ip"] != META for x in ANFRAGEN),
          "das interne Ziel wurde nie kontaktiert")
    ANFRAGEN.clear()
    ANTWORTEN[("seite.beispiel.de", "/kreis")] = (302, {"location": "/kreis"}, b"")
    check("Weiterleitungen" in fehler("https://seite.beispiel.de/kreis", max_spruenge=3),
          "Weiterleitungsschleife endet")
    check(len(ANFRAGEN) == 4, "hoechstens max_spruenge+1 Anfragen (%d)" % len(ANFRAGEN))

    print("\n5. Relative Weiterleitung")
    ANFRAGEN.clear()
    ANTWORTEN[("seite.beispiel.de", "/alt")] = (301, {"location": "/neu"}, b"")
    r = holen("https://seite.beispiel.de/alt")
    check(r.status_code == 200 and str(r.url) == "https://seite.beispiel.de/neu",
          "gefolgt, resp.url = echte Zieladresse")
    check([x["pfad"] for x in ANFRAGEN] == ["/alt", "/neu"], "beide Spruenge gezaehlt")
    ANTWORTEN[("seite.beispiel.de", "/weg")] = (404, {}, b"")
    try:
        holen("https://seite.beispiel.de/weg")
        check(False, "HTTP 404 wirft HTTPStatusError")
    except httpx.HTTPStatusError:
        check(True, "HTTP 404 wirft HTTPStatusError")

    print("\n6. Die Aufrufer laufen ueber die Schranke")
    from backend import web_extractor as we
    ANFRAGEN.clear()
    try:
        asyncio.run(we._http_get("http://meta.beispiel.de/"))
        check(False, "web_extractor._http_get weist internes Ziel ab")
    except nz.ZielFehler:
        check(True, "web_extractor._http_get weist internes Ziel ab")
    check(not ANFRAGEN, "web_extractor: keine Anfrage an das interne Ziel")
    r = asyncio.run(we._http_get("https://seite.beispiel.de/c"))
    check(r.status_code == 200 and ANFRAGEN and ANFRAGEN[-1]["ip"] == OEFF4,
          "web_extractor: oeffentliches Ziel festgenagelt geholt")
    ANFRAGEN.clear()
    ANTWORTEN[("seite.beispiel.de", "/um")] = (302, {"location": "http://" + LOOP + "/"}, b"")
    try:
        asyncio.run(we._http_get("https://seite.beispiel.de/um"))
        check(False, "web_extractor: Weiterleitung nach loopback abgewiesen")
    except nz.ZielFehler:
        check(True, "web_extractor: Weiterleitung nach loopback abgewiesen")

    from backend import short_tracks_runner as run
    run._eigene_ips_cache = set()
    try:
        asyncio.run(run.url_holen("https://seite.beispiel.de/um"))
        check(False, "short_tracks: Weiterleitung nach loopback abgewiesen")
    except run.UrlFehler as e:
        check("Short Tracks" in str(e), "short_tracks: Weiterleitung nach loopback abgewiesen (eigener Text)")
    ANFRAGEN.clear()
    titel, text, ziel = asyncio.run(run.url_holen("https://seite.beispiel.de/alt"))
    check(text == "hallo" and ziel.endswith("/neu") and ANFRAGEN and ANFRAGEN[0]["ip"] == OEFF4,
          "short_tracks: festgenagelt geholt, Ziel nach Weiterleitung")

    # Bildsuche: image_gen (zieht config) als Attrappe
    tmp = Path(tempfile.mkdtemp(prefix="netz_ziel_"))
    gespeichert = []
    attrappe = types.ModuleType("backend.tools.image_gen")
    attrappe._IMG_DIR = tmp
    attrappe.record_task_image = lambda p, u: gespeichert.append(u)
    sys.modules["backend.tools.image_gen"] = attrappe
    from backend.tools import image_search as ims
    if not str(attrappe._IMG_DIR).startswith(tempfile.gettempdir()):
        print("ABBRUCH: Bildablage zeigt aus dem Sandkasten", flush=True)
        sys.exit(2)
    DNS["bild.beispiel.de"] = [OEFF4]
    ANTWORTEN[("bild.beispiel.de", "/b.png")] = (200, {"content-type": "image/png"},
                                                 b"\x89PNG" + b"x" * 400)
    ANTWORTEN[("meta.beispiel.de", "/i.png")] = (200, {"content-type": "image/png"},
                                                 b"\x89PNG" + b"y" * 400)

    async def _urls(q, limit=6):
        return ["http://meta.beispiel.de/i.png", "https://bild.beispiel.de/b.png"]
    ims._ddg_image_urls = _urls
    ANFRAGEN.clear()
    erg = asyncio.run(ims.SearchImageTool().execute(query="Berg"))
    check("BILD_GEFUNDEN" in erg and len(gespeichert) == 1, "Bildsuche: oeffentliches Bild geladen")
    check(all(x["host"] != "meta.beispiel.de" for x in ANFRAGEN),
          "Bildsuche: internes Ergebnis nie kontaktiert")
    dateien = list(tmp.iterdir())
    check(len(dateien) == 1 and b"y" not in dateien[0].read_bytes(),
          "Bildsuche: nur das oeffentliche Bild abgelegt")
finally:
    socket.getaddrinfo = _echt_gai
    httpx.AsyncClient = _EchtClient

print("\n" + "=" * 60)
print("  %d OK, %d FAIL" % (OK, FAIL))
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)

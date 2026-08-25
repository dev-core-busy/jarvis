#!/usr/bin/env python3
"""Abgleich Repo <-> Server: welche ausgelieferte Datei weicht vom Repo ab?

WARUM ES DAS GIBT (Vorfall DEV 2026-08-25): auf dem Server lag eine
``settings.html``, die ``icons.js`` nicht einband, waehrend die JS-Dateien
daneben aktuell waren. Ergebnis war ein ``ReferenceError`` mitten im Rendern,
den ein ``catch`` verschluckte – die Skills-Seite blieb ohne Fehlermeldung
halb leer. Die Datei war dabei SPAETER geschrieben als die Repo-Fassung und
trotzdem 30 KB kleiner.

Daraus die beiden Regeln, auf denen dieses Skript steht:

1. **Verglichen wird der INHALT (md5), nie die mtime.** Ein Deploy, der eine
   aeltere Fassung aufspielt, hebt die mtime trotzdem an. Aus demselben Grund
   ist auch ``git rev-parse`` auf dem Server kein Versionsindikator – dort
   wird nicht committet (siehe CLAUDE.md).
2. **Ein halber FRONTEND-Deploy ist der gefaehrlichste Fall**, weil HTML und
   JS getrennte Dateien sind: passen sie nicht zusammen, faellt kein Skript
   aus, es wirft mitten im Rendern.

Das Skript AENDERT von sich aus nichts. ``--nachziehen`` ist die ausdrueckliche
Ausnahme und sichert vorher.

Aufruf:
    python3 deploy/abgleich.py                       # ganzes Repo gegen DEV
    python3 deploy/abgleich.py --nur frontend/       # nur das Frontend
    python3 deploy/abgleich.py --server root@1.2.3.4 --ziel /opt/jarvis
    python3 deploy/abgleich.py --nur frontend/ --nachziehen

Exit: 0 = deckungsgleich · 1 = Drift gefunden · 2 = konnte nicht laufen.
Der Unterschied zwischen 1 und 2 ist wichtig – „konnte nicht laufen" darf
nie wie „alles in Ordnung" aussehen.
"""
import argparse
import hashlib
import os
import shlex
import subprocess
import sys
import tempfile
import time

VORGABE_SERVER = "root@191.100.144.1"   # DEV, steht so auch in CLAUDE.md
VORGABE_ZIEL = "/opt/jarvis"
AGENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "abgleich_agent.py")
ABLAGE = "/root/.jarvis-abgleich"       # 0700, nicht /tmp (dort 1777)

# Dateien, die auf dem Server absichtlich anders sind. Sie hier NICHT
# aufzufuehren waere kein Sicherheitsgewinn, sondern Rauschen, in dem der
# echte Fund untergeht.
SERVER_HOHEIT = (
    "data/instructions/",   # pro Server gepflegt, der Server ist die Wahrheit
    "settings.json",
    ".env",
)


class Fehler(Exception):
    """Der Lauf konnte nicht durchgefuehrt werden (Exit 2), kein Drift-Befund."""


# ── reine Auswertung (ohne Netz, damit testbar) ────────────────────────────

def sparse_praefixe(inhalt):
    """Praefixe, die eine sparse-checkout-Datei AUSBLENDET.

    ``deploy/sparse_checkout.sh`` schreibt ``/*`` plus ``!/tests/`` &Co.
    Ausgeblendete Pfade duerfen NICHT als „fehlt auf dem Server" erscheinen –
    sonst meldet der Lauf auf Produktion hunderte Fehlbefunde und wird nach
    dem zweiten Mal nicht mehr gelesen.
    """
    raus = []
    for zeile in (inhalt or "").splitlines():
        z = zeile.strip()
        if not z.startswith("!"):
            continue
        z = z[1:].lstrip("/")
        if z:
            raus.append(z)
    return raus


def ist_ausgeblendet(pfad, praefixe):
    return any(pfad == p.rstrip("/") or pfad.startswith(p if p.endswith("/") else p + "/")
               for p in praefixe)


def vergleiche(repo, server, sparse=(), hoheit=SERVER_HOHEIT):
    """repo/server: {pfad: md5}; server-Wert ``None`` heisst „nicht vorhanden".

    Liefert vier Listen. Getrennt gehalten, weil sie verschiedene Handlungen
    nach sich ziehen: ``verschieden`` und ``fehlt`` sind Deploy-Rueckstand,
    ``ausgeblendet`` ist Absicht, ``server_hoheit`` darf gar nicht angefasst
    werden.
    """
    verschieden, fehlt, ausgeblendet, eigen = [], [], [], []
    for pfad in sorted(repo):
        if any(pfad.startswith(h) or pfad == h.rstrip("/") for h in hoheit):
            eigen.append(pfad)
            continue
        drueben = server.get(pfad)
        if drueben is None:
            (ausgeblendet if ist_ausgeblendet(pfad, sparse) else fehlt).append(pfad)
        elif drueben != repo[pfad]:
            verschieden.append(pfad)
    return {"verschieden": verschieden, "fehlt": fehlt,
            "ausgeblendet": ausgeblendet, "server_hoheit": eigen}


def verirrt_filtern(kandidaten, ignoriert):
    """Serverdateien ohne Repo-Pendant, die auch nicht von .gitignore gedeckt sind.

    Die Ignore-Pruefung laeuft LOKAL (dort liegt die .gitignore) – ohne sie
    waeren ``data/``, Zertifikate und Laufzeitdateien allesamt „verirrt".
    """
    return [k for k in kandidaten if k not in ignoriert]


# ── Umgebung ───────────────────────────────────────────────────────────────

def _lauf(befehl, eingabe=None, pruefen=True):
    p = subprocess.run(befehl, input=eingabe, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if pruefen and p.returncode != 0:
        raise Fehler("%s scheiterte (Exit %d): %s"
                     % (befehl[0], p.returncode,
                        p.stderr.decode("utf-8", "replace").strip()[:400]))
    return p


def repo_wurzel():
    p = _lauf(["git", "rev-parse", "--show-toplevel"])
    return p.stdout.decode().strip()


def repo_dateien(wurzel, nur):
    p = _lauf(["git", "-C", wurzel, "ls-files", "-z"])
    alle = [x.decode("utf-8", "surrogateescape") for x in p.stdout.split(b"\0") if x]
    if nur:
        alle = [a for a in alle if a.startswith(nur)]
    return alle


def lokale_hashes(wurzel, dateien):
    raus = {}
    for rel in dateien:
        voll = os.path.join(wurzel, rel)
        try:
            if not os.path.isfile(voll) or os.path.islink(voll):
                continue
            h = hashlib.md5()
            with open(voll, "rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(block)
            raus[rel] = h.hexdigest()
        except OSError:
            continue
    return raus


def ssh_basis(server, key):
    b = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if key:
        b += ["-i", key]
    return b + [server]


def scp_basis(key):
    b = ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-q"]
    if key:
        b += ["-i", key]
    return b


def server_lesen(server, key, ziel, dateien, praefix_liste):
    """Agent + Dateiliste hochladen, beide Auftraege ausfuehren, aufraeumen."""
    ssh = ssh_basis(server, key)
    _lauf(ssh + ["mkdir -p %s && chmod 700 %s" % (shlex.quote(ABLAGE), shlex.quote(ABLAGE))])
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"\0".join(d.encode("utf-8", "surrogateescape") for d in dateien))
        listendatei = tmp.name
    try:
        _lauf(scp_basis(key) + [AGENT, "%s:%s/abgleich_agent.py" % (server, ABLAGE)])
        _lauf(scp_basis(key) + [listendatei, "%s:%s/liste.bin" % (server, ABLAGE)])

        def agent(auftrag, extra=()):
            teile = ["python3", ABLAGE + "/abgleich_agent.py", auftrag, ziel,
                     ABLAGE + "/liste.bin"] + list(extra)
            return _lauf(ssh + [" ".join(shlex.quote(t) for t in teile)]) \
                .stdout.decode("utf-8", "surrogateescape")

        roh_h = agent("hashes")
        roh_f = agent("fremde", praefix_liste)

        sparse = _lauf(ssh + ["cat %s 2>/dev/null || true"
                              % shlex.quote(ziel + "/.git/info/sparse-checkout")],
                       pruefen=False).stdout.decode("utf-8", "replace")
    finally:
        os.unlink(listendatei)
        _lauf(ssh + ["rm -rf %s" % shlex.quote(ABLAGE)], pruefen=False)

    hashes, kaputt = {}, []
    for zeile in roh_h.splitlines():
        if "\t" not in zeile:
            continue
        wert, pfad = zeile.split("\t", 1)
        if wert == "-":
            hashes[pfad] = None
        elif wert.startswith("FEHLER:"):
            kaputt.append((pfad, wert[7:]))
        else:
            hashes[pfad] = wert

    fremd = []
    for zeile in roh_f.splitlines():
        if "\t" not in zeile:
            continue
        art, pfad = zeile.split("\t", 1)
        fremd.append((pfad, art))
    return hashes, fremd, sparse, kaputt


def gitignore_treffer(wurzel, pfade):
    """Welche der Pfade deckt die .gitignore ab? (lokal, ohne Netz)"""
    if not pfade:
        return set()
    p = subprocess.run(["git", "-C", wurzel, "check-ignore", "--stdin"],
                       input="\n".join(pfade).encode("utf-8", "surrogateescape"),
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    # Exit 1 heisst hier „keiner ist ignoriert" und ist KEIN Fehler.
    return set(p.stdout.decode("utf-8", "surrogateescape").splitlines())


def nachziehen(server, key, ziel, wurzel, pfade):
    """Abweichende Dateien aus dem Repo aufspielen – mit Sicherung, als jarvis.

    Liefert ``(sicherungspfad, anzahl_gesicherter_dateien)``. Die Anzahl wird
    ausgegeben, weil eine Sicherung, deren Erfolg niemand prueft, keine ist:
    die erste Fassung rief ``cp --parents`` mit relativem Pfad, ohne vorher
    ins Zielverzeichnis zu wechseln, und verschluckte den Fehlschlag mit
    ``2>/dev/null || true`` – der Ordner blieb LEER, waehrend die Meldung
    „Sicherung des alten Standes" behauptete, es gaebe einen Rueckweg.
    """
    ssh = ssh_basis(server, key)
    marke = time.strftime("%Y%m%d-%H%M%S")
    sicher = "/root/abgleich-sicherung-%s" % marke
    stapel = ABLAGE + "-neu"
    _lauf(ssh + ["mkdir -p %s %s" % (shlex.quote(sicher), shlex.quote(stapel))])
    gesichert = 0
    try:
        for i, rel in enumerate(pfade):
            fern = "%s/%s" % (ziel, rel)
            unter = os.path.dirname(rel)
            zielordner = sicher + ("/" + unter if unter else "")
            # Eine Datei, die es drueben noch gar nicht gibt (Kategorie
            # „fehlt"), kann nicht gesichert werden – das ist kein Fehler.
            # Existiert sie und das Kopieren scheitert, MUSS es auffallen:
            # kein 2>/dev/null, kein || true.
            p = _lauf(ssh + ["cd %s && if [ -f %s ]; then mkdir -p %s && cp -p %s %s && echo GESICHERT; fi"
                             % (shlex.quote(ziel), shlex.quote(rel),
                                shlex.quote(zielordner), shlex.quote(rel),
                                shlex.quote(zielordner + "/" + os.path.basename(rel)))])
            if b"GESICHERT" in p.stdout:
                gesichert += 1
            # Getrennte Namen im Stapel: zwei Repo-Dateien koennen gleich
            # heissen (backend/main.py und skills/office/main.py) – ein
            # basename als Zielname wuerde eine davon still verschlucken.
            stapelname = "%s/%04d.bin" % (stapel, i)
            _lauf(scp_basis(key) + [os.path.join(wurzel, rel), "%s:%s" % (server, stapelname)])
            _lauf(ssh + ["mkdir -p %s && install -o jarvis -g jarvis -m 644 %s %s"
                         % (shlex.quote(os.path.dirname(fern)),
                            shlex.quote(stapelname), shlex.quote(fern))])
    finally:
        _lauf(ssh + ["rm -rf %s" % shlex.quote(stapel)], pruefen=False)
    return sicher, gesichert


# ── Ausgabe ────────────────────────────────────────────────────────────────

def _liste(titel, eintraege, deckel=40):
    if not eintraege:
        return
    print("\n%s (%d)" % (titel, len(eintraege)))
    for e in eintraege[:deckel]:
        print("   %s" % e)
    if len(eintraege) > deckel:
        # Beziffern, nicht still abschneiden: eine gekuerzte Liste, die sich
        # fuer vollstaendig ausgibt, ist schlimmer als eine kurze.
        print("   … und %d weitere" % (len(eintraege) - deckel))


def main():
    ap = argparse.ArgumentParser(
        description="Vergleicht die ausgelieferten Dateien eines Servers mit dem Repo (md5, nicht mtime).")
    ap.add_argument("--server", default=os.environ.get("JARVIS_ABGLEICH_SERVER", VORGABE_SERVER))
    ap.add_argument("--ziel", default=VORGABE_ZIEL)
    ap.add_argument("--key", default=os.path.expanduser("~/.ssh/id_rsa"))
    ap.add_argument("--nur", default="", metavar="PRAEFIX",
                    help="nur dieser Pfad-Praefix, z.B. frontend/")
    ap.add_argument("--nachziehen", action="store_true",
                    help="abweichende/fehlende Dateien aus dem Repo aufspielen (sichert vorher)")
    a = ap.parse_args()

    try:
        wurzel = repo_wurzel()
        dateien = repo_dateien(wurzel, a.nur)
        if not dateien:
            raise Fehler("Kein Treffer fuer --nur %r." % a.nur)
        repo = lokale_hashes(wurzel, dateien)

        praefixe = [a.nur] if a.nur else sorted(
            {d.split("/", 1)[0] for d in dateien if "/" in d})
        server, fremd_roh, sparse_txt, kaputt = server_lesen(
            a.server, a.key, a.ziel.rstrip("/"), dateien, praefixe)
    except Fehler as e:
        print("ABBRUCH: %s" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("ABBRUCH: %s" % e, file=sys.stderr)
        return 2

    sparse = sparse_praefixe(sparse_txt)
    b = vergleiche(repo, server, sparse)
    ignoriert = gitignore_treffer(wurzel, [p for p, _ in fremd_roh])
    verirrt = [(p, art) for p, art in fremd_roh if p not in ignoriert]

    gleich = len(repo) - len(b["verschieden"]) - len(b["fehlt"]) \
        - len(b["ausgeblendet"]) - len(b["server_hoheit"])
    print("Abgleich %s : %s%s" % (a.server, a.ziel, ("/" + a.nur) if a.nur else ""))
    # Die Grenze gehoert in die Ausgabe, nicht nur in den Docstring: Basis ist
    # `git ls-files`. Eine Datei, die lokal existiert, aber noch nicht zum
    # Repo hinzugefuegt wurde, ist fuer diesen Lauf UNSICHTBAR – sie kann
    # weder als "fehlt" noch als "abweichend" erscheinen.
    print("  Basis: git-verfolgte Dateien · verglichen wird der Inhalt (md5), nicht die mtime")
    print("  geprueft %d · deckungsgleich %d · abweichend %d · fehlt %d · verirrt %d"
          % (len(repo), gleich, len(b["verschieden"]), len(b["fehlt"]), len(verirrt)))
    if b["ausgeblendet"]:
        print("  ausgeblendet durch sparse-checkout: %d (kein Befund)" % len(b["ausgeblendet"]))
    if b["server_hoheit"]:
        print("  Server-Hoheit, nicht verglichen: %d" % len(b["server_hoheit"]))

    _liste("ABWEICHEND (Server-Inhalt != Repo)", b["verschieden"])
    _liste("FEHLT auf dem Server", b["fehlt"])
    _liste("VERIRRT (auf dem Server, kein Repo-Pendant, nicht gitignored)",
           ["%s  [%s]" % (p, art) for p, art in verirrt])
    _liste("NICHT LESBAR", ["%s  (%s)" % (p, g) for p, g in kaputt])

    drift = b["verschieden"] + b["fehlt"]
    if a.nachziehen and drift:
        print("\nZiehe %d Datei(en) nach …" % len(drift))
        try:
            sicher, gesichert = nachziehen(a.server, a.key, a.ziel.rstrip("/"), wurzel, drift)
        except Fehler as e:
            print("ABBRUCH beim Nachziehen: %s" % e, file=sys.stderr)
            return 2
        print("  Sicherung des alten Standes: %s (%d Datei(en))" % (sicher, gesichert))
        if not gesichert:
            print("  HINWEIS: nichts gesichert – alle nachgezogenen Dateien fehlten drueben.")
        print("  Bitte erneut ohne --nachziehen laufen lassen und den Dienst pruefen.")
        return 1
    if a.nachziehen:
        print("\nNichts nachzuziehen.")

    if drift or verirrt or kaputt:
        print("\nDrift gefunden.")
        return 1
    print("\nDeckungsgleich.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(2)

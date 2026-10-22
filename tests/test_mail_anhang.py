#!/usr/bin/env python3
"""Dateien aus dem Chat als E-Mail-Anhang (2026-10-22).

GEMELDET: "/chat kann weder Anhaenge noch im Chat angezeigte Bilder per E-Mail
versenden" – ``email_senden`` kannte nur Nur-Text.

WAS DIESER TEST FESTHAELT:
  1. **Jede Verweisform, die das Werkzeug dem Modell nennt, loest auf** –
     Arbeitskopie, Ablage-Name, /api/documents, /api/chat/attachment,
     /api/generated, Ergebnisdatei im Arbeitsverzeichnis, Markdown-Verweis.
  2. **Eine ausgelieferte Ergebnisdatei wird ueber ihren alten /tmp-Pfad
     gefunden** (``_deliver_docs`` loescht die Quelle) – aber nur die EIGENE.
  3. **Nur eigene Dateien aus dem Chat:** fremde Anhaenge, fremde Ablage,
     Wissensordner, Freigaben, Geheimnisse und ``..`` werden abgewiesen.
  4. **Ohne Menschen nur unerratbare Namen** (Regel-Lauf, Cron).
  5. **Die Bytes kommen an:** SMTP-Nachricht traegt die Datei mit Namen und
     Typ, der EWS-Weg haengt ``FileAttachment(name=, content=)`` an.
  6. **Ein unzulaessiger Anhang kostet keinen Anmeldeversuch** – das Werkzeug
     prueft VOR dem Verbindungsaufbau (Sperrpolitik der Domaene).

Laeuft ohne exchangelib, fastapi und Netz; alle Wurzeln zeigen in ein
Wegwerf-Verzeichnis (Positivkontrolle, sonst Exit 2).

Exit 2 = konnte nicht laufen, 1 = Pruefung fehlgeschlagen, 0 = bestanden.

    python3 tests/test_mail_anhang.py
"""
import asyncio
import email
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("JARVIS_MAIL_ANHANG_MAX_MB", None)

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


try:
    from backend import documents, lauf_tmp, mail_anhang, mail_client, sandbox, wirkung
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Module nicht importierbar: {e}")
    sys.exit(2)

# ── Sandkasten ──────────────────────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="test_mail_anhang_")).resolve()
DOCS = TMP / "documents"
GEN = TMP / "generated"
ECHT = TMP / "tmp"
ANH = ECHT / "jarvis-anhaenge"
ARB = ECHT / "jarvis-arbeit"
RAG = TMP / "rag"
for d in (DOCS, GEN, ANH, ARB, RAG):
    d.mkdir(parents=True)
documents.DOCS_DIR = DOCS
documents._REGISTRY = DOCS / ".owners.json"
mail_anhang.GEN_DIR = GEN
lauf_tmp.TMP_ECHT = ECHT
lauf_tmp.ANH_ROOT = ANH
lauf_tmp.ARBEIT_ROOT = ARB

section("0. Positivkontrolle: alle Wurzeln liegen im Sandkasten")
_wurzeln = [documents.DOCS_DIR, documents._REGISTRY, mail_anhang.GEN_DIR,
            lauf_tmp.ANH_ROOT, lauf_tmp.ARBEIT_ROOT, lauf_tmp.TMP_ECHT]
if not all(str(Path(w).resolve()).startswith(str(TMP)) for w in _wurzeln):
    print("ABBRUCH: eine Wurzel zeigt aus dem Sandkasten heraus")
    sys.exit(2)
check(True, "Wurzeln umgebogen")

ICH, FREMD = "m.mustermann", "e.musterfrau"
K_ICH, K_FREMD = lauf_tmp.benutzer_kennung(ICH), lauf_tmp.benutzer_kennung(FREMD)
if not K_ICH or K_ICH == K_FREMD:
    print("ABBRUCH: Benutzerkennungen nicht unterscheidbar")
    sys.exit(2)


def datei(p: Path, inhalt: bytes = b"inhalt") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(inhalt)
    return p


# Material, wie es die ERZEUGER ablegen (main._anhang_ablegen, _deliver_docs, image_gen)
anh_ich = datei(ANH / K_ICH / "anhang_0123456789ab_Bericht.pdf", b"%PDF-ich")
anh_fremd = datei(ANH / K_FREMD / "anhang_ba9876543210_Geheim.pdf", b"%PDF-fremd")
upload_ich = datei(DOCS / "Bericht.pdf", b"%PDF-ich")
documents.register_upload(upload_ich.name, ICH)
upload_fremd = datei(DOCS / "Angebot.pdf", b"%PDF-fremd")
documents.register_upload(upload_fremd.name, FREMD)
CAP_ICH = "a" * 32 + "__Umsatz_Diagramm.png"
cap_ich = datei(DOCS / CAP_ICH, b"\x89PNG-ich")
documents.register(CAP_ICH, ICH)
CAP_FREMD = "b" * 32 + "__Umsatz_Diagramm.png"
cap_fremd = datei(DOCS / CAP_FREMD, b"\x89PNG-fremd")
documents.register(CAP_FREMD, FREMD)
# Die FREMDE Datei ist juenger – ein Namensabgleich ohne Eigentuemer naehme sie.
os.utime(cap_ich, (1_000_000, 1_000_000))
GEN_NAME = "c" * 32 + ".png"
datei(GEN / GEN_NAME, b"\x89PNG-gen")
arb_ich = datei(ARB / K_ICH / "auswertung.xlsx", b"PK-ich")
arb_fremd = datei(ARB / K_FREMD / "auswertung.xlsx", b"PK-fremd")
rag = datei(RAG / "preisliste.pdf", b"%PDF-wissen")
geheim = datei(DOCS / ".owners.json.bak", b"x")


def ok(verweis, mensch=True, benutzer=ICH):
    try:
        return mail_anhang.aufloesen(verweis, benutzer, mensch)
    except mail_client.MailFehler as f:
        return ("FEHLER", str(f))


def abgewiesen(verweis, mensch=True, benutzer=ICH):
    r = ok(verweis, mensch, benutzer)
    return isinstance(r, tuple) and r[0] == "FEHLER"


section("1. Jede genannte Verweisform loest auf")
r = ok(str(anh_ich))
check(r[0] == anh_ich.resolve() and r[1] == "Bericht.pdf",
      "Arbeitskopie eines Anhangs, Anzeigename ohne anhang_-Praefix", r)
r = ok("Bericht.pdf")
check(r[0] == upload_ich.resolve(), "blosser Name in data/documents", r)
r = ok("data/documents/Bericht.pdf")
check(r[0] == upload_ich.resolve(), "data/documents/<name>", r)
r = ok("/api/documents/" + CAP_ICH)
check(r[0] == cap_ich.resolve() and r[1] == "Umsatz_Diagramm.png",
      "/api/documents/<cap>, Anzeigename ohne Kennung", r)
r = ok("/api/chat/attachment/Bericht.pdf")
check(r[0] == upload_ich.resolve(), "/api/chat/attachment/<name>", r)
r = ok("/api/generated/" + GEN_NAME)
check(r[0] == (GEN / GEN_NAME).resolve(), "/api/generated/<32 Hex>.png", r)
r = ok("![Diagramm](/api/documents/%s)" % CAP_ICH)
check(r[0] == cap_ich.resolve(), "Markdown-Verweis aus dem Verlauf", r)
r = ok("https://jarvis.beispiel.de/api/documents/%s?token=x" % CAP_ICH)
check(r[0] == cap_ich.resolve(), "volle Adresse mit Abfrage-Schluessel", r)
r = ok(str(arb_ich))
check(r[0] == arb_ich.resolve(), "eigene Ergebnisdatei im Arbeitsverzeichnis", r)

section("2. Ausgelieferte Datei ueber ihren alten /tmp-Pfad")
r = ok(str(ARB / K_ICH / "Umsatz Diagramm.png"))
check(r[0] == cap_ich.resolve(),
      "verschwundener /tmp-Pfad findet die EIGENE ausgelieferte Fassung", r)
r = ok("Umsatz_Diagramm.png")
check(r[0] == cap_ich.resolve(), "blosser Anzeigename ebenso", r)
check(abgewiesen("Umsatz_Diagramm.png", benutzer="x.niemand"),
      "ohne eigene Fassung keine fremde (juengere) Datei")
check(abgewiesen(str(ARB / K_ICH / "Umsatz Diagramm.png"), mensch=False),
      "ohne Menschen kein Namensabgleich (Name erratbar)")

section("3. Nur eigene Dateien aus dem Chat")
check(abgewiesen(str(anh_fremd)), "fremde Anhang-Arbeitskopie")
check(abgewiesen("Angebot.pdf"), "fremder Upload in data/documents")
check(abgewiesen("/api/documents/" + CAP_FREMD), "fremde ausgelieferte Datei")
check(abgewiesen(str(arb_fremd)), "fremdes Arbeitsverzeichnis")
check(abgewiesen(str(rag)), "Wissensordner")
check(abgewiesen("/mnt/rag/share/preisliste.pdf"), "Freigabe unter /mnt")
check(abgewiesen("/api/documents/../../rag/preisliste.pdf"),
      "'..' in einer Download-Adresse")
check(abgewiesen("data/documents/../rag/preisliste.pdf"), "'..' in data/documents")
check(abgewiesen(".owners.json"), "Eigentuemer-Registry")
check(abgewiesen(geheim.name), "Datei ohne Eigentuemer-Vermerk")
check(abgewiesen("/api/generated/../../documents/" + CAP_FREMD),
      "'..' aus den erzeugten Bildern in die Ablage")
check(abgewiesen("/api/generated/kurz.png"), "erzeugtes Bild mit erratbarem Namen")
datei(ECHT / "fremd_im_echten_tmp.txt")
_marke = sandbox.set_tool_user(ICH)
try:
    check(abgewiesen(str(ECHT / "fremd_im_echten_tmp.txt")),
          "echtes /tmp fuer einen Domain-Benutzer (tool_user gesetzt)")
finally:
    sandbox.reset_tool_user(_marke)
r = ok(str(ECHT / "fremd_im_echten_tmp.txt"))
check(r[0] == (ECHT / "fremd_im_echten_tmp.txt").resolve(),
      "Positivkontrolle: privilegierter Lauf (kein tool_user, kein Lauf) darf /tmp", r)
check(abgewiesen(str(ECHT / "fremd_im_echten_tmp.txt"), mensch=False),
      "echtes /tmp ohne Menschen auch privilegiert nicht")

section("4. Ohne Menschen nur unerratbare Namen")
check(abgewiesen("Bericht.pdf", mensch=False), "Klarname eines Uploads")
check(abgewiesen(str(arb_ich), mensch=False), "Ergebnisdatei mit Klarnamen")
check(ok("/api/documents/" + CAP_ICH, mensch=False)[0] == cap_ich.resolve(),
      "Capability-Adresse bleibt erlaubt")
check(ok(str(anh_ich), mensch=False)[0] == anh_ich.resolve(),
      "Anhang-Arbeitskopie (12 Hex) bleibt erlaubt")
check(mail_anhang.mit_mensch() is False, "ohne Kanal gilt: kein Mensch")
_k = wirkung.kanal_cv.set(wirkung.Kanal(ws=None, username=ICH, kann_bestaetigen=True))
try:
    check(mail_anhang.mit_mensch() is True, "mit Kanal gilt: Mensch sieht zu")
finally:
    wirkung.kanal_cv.reset(_k)

section("5. laden(): Liste, Grenzen, alles oder nichts")
check(mail_anhang.liste("a.pdf, b.pdf\nc.pdf") == ["a.pdf", "b.pdf", "c.pdf"],
      "Zeichenkette mit Komma und Zeilenumbruch")
check(mail_anhang.liste(["a.pdf", {"pfad": "b.pdf"}]) == ["a.pdf", "b.pdf"],
      "Liste mit Zeichenketten und Objekten")
check(mail_anhang.liste("") == [] and mail_anhang.liste(None) == [], "leer = keine")
geladen = mail_anhang.laden([str(anh_ich), "/api/documents/" + CAP_ICH], ICH, True)
check([n for n, _ in geladen] == ["Bericht.pdf", "Umsatz_Diagramm.png"]
      and geladen[0][1] == b"%PDF-ich", "Namen und Inhalt", geladen)
check(len(mail_anhang.laden([str(upload_ich), "Bericht.pdf"], ICH, True)) == 1,
      "dieselbe Datei zweimal genannt = einmal angehaengt")
try:
    mail_anhang.laden(["Bericht.pdf", "Angebot.pdf"], ICH, True)
    check(False, "ein fremder Anhang verhindert die ganze Mail")
except mail_client.MailFehler:
    check(True, "ein fremder Anhang verhindert die ganze Mail")
try:
    mail_anhang.laden(["x%d.pdf" % i for i in range(mail_anhang.MAX_ANZAHL + 1)], ICH, True)
    check(False, "mehr als MAX_ANZAHL Anhaenge abgewiesen")
except mail_client.MailFehler:
    check(True, "mehr als MAX_ANZAHL Anhaenge abgewiesen")
os.environ["JARVIS_MAIL_ANHANG_MAX_MB"] = "0.000001"
try:
    mail_anhang.laden(["Bericht.pdf"], ICH, True)
    check(False, "Groessendeckel greift")
except mail_client.MailFehler as f:
    check("MB" in str(f), "Groessendeckel greift und nennt die Grenze", f)
finally:
    os.environ.pop("JARVIS_MAIL_ANHANG_MAX_MB", None)
try:
    mail_anhang.laden(["Bericht.pdf"], "", True)
    check(False, "ohne Benutzer keine Anhaenge")
except mail_client.MailFehler:
    check(True, "ohne Benutzer keine Anhaenge")

section("6. Die Bytes kommen an: SMTP-Weg")
konto = mail_client.MailKonto(adresse="m.mustermann@beispiel.de") \
    if "adresse" in mail_client.MailKonto.__dataclass_fields__ else None
if konto is None:
    print("ABBRUCH: MailKonto hat kein Feld 'adresse'")
    sys.exit(2)
imap = mail_client._Imap.__new__(mail_client._Imap)
imap.konto = konto
nachricht = imap._bauen(["x@beispiel.de"], "Betreff", "Hallo", [], anhaenge=geladen)
roh = email.message_from_bytes(nachricht.as_bytes())
teile = [(p.get_filename(), p.get_content_type(), p.get_payload(decode=True))
         for p in roh.walk() if p.get_filename()]
check(("Bericht.pdf", "application/pdf", b"%PDF-ich") in teile, "PDF als Anhang", teile)
check(("Umsatz_Diagramm.png", "image/png", b"\x89PNG-ich") in teile, "PNG als Anhang", teile)
texte = [p.get_payload(decode=True) for p in roh.walk()
         if p.get_content_type() == "text/plain" and not p.get_filename()]
check(any(t and t.strip() == b"Hallo" for t in texte), "Textteil bleibt erhalten", texte)
ohne = email.message_from_bytes(imap._bauen(["x@beispiel.de"], "B", "T", []).as_bytes())
check(not ohne.is_multipart(), "ohne Anhang unveraendert eine einfache Nachricht")

section("7. Die Bytes kommen an: EWS-Weg (Attrappe mit echter Signatur)")


class _FA:
    def __init__(self, *, name, content):
        self.name, self.content = name, content


class _Msg:
    gesendet = None

    def __init__(self, **kw):
        self.kw, self.attachments = kw, []

    def attach(self, a):
        self.attachments.append(a)

    def send_and_save(self):
        _Msg.gesendet = self

    def save(self):
        _Msg.gesendet = self


class _Xl:
    Message, FileAttachment = _Msg, _FA

    class Mailbox:
        def __init__(self, *, email_address):
            self.email_address = email_address


class _Acc:
    drafts, sent = "drafts", "sent"


ews = mail_client._Ews.__new__(mail_client._Ews)
ews._konto = lambda: _Acc()
ews._lib = lambda: _Xl
erg = ews.senden("x@beispiel.de", "B", "T", anhaenge=geladen)
anh = [(a.name, a.content) for a in (_Msg.gesendet.attachments if _Msg.gesendet else [])]
check(anh == geladen, "FileAttachment(name=, content=) je Datei", anh)
_Msg.gesendet = None
ews.senden("", "B", "T", entwurf=True, anhaenge=geladen)
check(_Msg.gesendet is not None and len(_Msg.gesendet.attachments) == 2,
      "auch im Entwurf")

section("8. Werkzeug: Schema, und Pruefung VOR dem Verbindungsaufbau")
spec = importlib.util.spec_from_file_location("emailskill_anhang", ROOT / "skills/email/main.py")
skill = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(skill)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Skill nicht ladbar: {e}")
    sys.exit(2)
werkzeuge = {t.name: t for t in skill.get_tools()}
for n in ("email_senden", "email_entwurf"):
    feld = werkzeuge[n].parameters_schema()["properties"].get("anhaenge") or {}
    check(feld.get("type") == "ARRAY", f"{n}: Feld anhaenge (ARRAY)", feld)
    check("anhaenge" in werkzeuge[n].description, f"{n}: Beschreibung nennt das Feld")
_verbindungen = []


class _Client:
    def senden(self, *a, **kw):
        _verbindungen.append(("senden", kw.get("anhaenge")))
        return "E-Mail gesendet."

    def schliessen(self):
        pass


def _client(self):
    _verbindungen.append("aufbau")
    return _Client()


skill._Base._client = _client
from backend import mail_accounts  # noqa: E402
_m = mail_accounts.current_mail_user.set(ICH)
_k = wirkung.kanal_cv.set(wirkung.Kanal(ws=None, username=ICH, kann_bestaetigen=True))
try:
    aus = asyncio.run(werkzeuge["email_senden"].execute(
        an="x@beispiel.de", betreff="B", text="T", anhaenge=["Angebot.pdf"]))
    check(aus.startswith("❌") and not _verbindungen,
          "fremder Anhang: Abweisung ohne Verbindungsaufbau", (aus, _verbindungen))
    aus = asyncio.run(werkzeuge["email_senden"].execute(
        an="x@beispiel.de", betreff="B", text="T",
        anhaenge="/api/documents/" + CAP_ICH))
    gesendet = [v for v in _verbindungen if isinstance(v, tuple)]
    check(aus.startswith("✅") and "Umsatz_Diagramm.png" in aus,
          "Erfolg nennt den Anhang", aus)
    check(gesendet and gesendet[-1][1] == [("Umsatz_Diagramm.png", b"\x89PNG-ich")],
          "die geladenen Bytes erreichen den Client", gesendet)
    _verbindungen.clear()
    aus = asyncio.run(werkzeuge["email_entwurf"].execute(
        betreff="B", text="T", anhaenge=[str(anh_ich)]))
    gesendet = [v for v in _verbindungen if isinstance(v, tuple)]
    check(aus.startswith("✅") and gesendet and gesendet[-1][1][0][0] == "Bericht.pdf",
          "email_entwurf haengt ebenso an", (aus, gesendet))
    _verbindungen.clear()
    aus = asyncio.run(werkzeuge["email_senden"].execute(
        an="x@beispiel.de", betreff="B", text="T"))
    gesendet = [v for v in _verbindungen if isinstance(v, tuple)]
    check(aus.startswith("✅") and gesendet and gesendet[-1][1] == [],
          "ohne Feld wie bisher: keine Anhaenge", (aus, gesendet))
finally:
    wirkung.kanal_cv.reset(_k)
    mail_accounts.current_mail_user.reset(_m)

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)

#!/usr/bin/env python3
"""Waechter: ein gespeichertes Kennwort im Klartext – POST /api/secret/reveal.

⚠ HIER WIRD EINE UMGEKEHRTE ZUSAGE ABGESICHERT. Bis 2026-09-04 galt in
mail/sap/vemas/jira_accounts woertlich "kein Endpunkt gibt ein Kennwort heraus,
auch nicht maskiert". Auf ausdrueckliche, wiederholte Anweisung des Betreibers
zeigt das Auge am Kennwortfeld jetzt den gespeicherten Wert. Weil damit eine
Schutzzusage gefallen ist, MUESSEN die Schranken darum herum gemessen sein:

  1. die RECHTEMATRIX je Bereich (sie ist nicht einheitlich – genau deshalb
     steht sie im Rumpf und nicht in einer Dependency)
  2. KEIN Benutzername aus dem Rumpf – sonst waere der Endpunkt der Weg in
     fremde Zugangsdaten (gleiche Regel wie beim Empfaenger einer Erinnerung)
  3. JEDER Abruf ins Audit-Log, auch der abgelehnte – und NIE der Wert
  4. fail-closed: wirft die Freigabepruefung, wird abgelehnt
  5. KEIN freier Zugriff auf settings.json (Erlaubnisliste, keine Sperrliste) –
     sonst kaeme der Signierschluessel der Sitzungstoken heraus
  6. die UEBERSICHTEN geben weiterhin nichts heraus (die alte Zusage gilt dort)

GEMESSEN WIRD AUSGEFUEHRT: der Endpunkt wird per ``ast`` aus ``backend/main.py``
geschnitten und wirklich aufgerufen. Eine Quelltext-Suche wuerde die
Begruendungen im eigenen Docstring mitlesen (im Projekt inzwischen der
dreizehnte Fall dieser Klasse).

Lauf:  timeout 120 python3 tests/test_secret_reveal.py
"""
import ast
import asyncio
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    """(Beschreibung, Bedingung) – NICHT umgekehrt."""
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def abbruch(text):
    print("\033[31mABBRUCH: %s\033[0m" % text)
    sys.exit(2)


def sicher(fn, *a, **k):
    """Nie ungeprueft dereferenzieren: eine Pruefung darf FEHLSCHLAGEN,
    nicht ABBRECHEN (sonst endet der Lauf ohne Bilanz und ist von
    'nicht gelaufen' nicht zu unterscheiden)."""
    try:
        return fn(*a, **k), ""
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


# ── Attrappen fuer die Konten-Module und die Konfiguration ─────────────────
# Sie werden VOR dem Import von backend.secret_reveal gestellt: das Modul holt
# sie lazy, ein echter Import zoege Fernet und die echten Datendateien nach.
GERUFEN = []


def _mach_konto(name, felder, werte):
    m = types.ModuleType("backend.%s_accounts" % name)
    m.GEHEIMFELDER = felder

    def klartext(user, feld, _n=name, _f=felder, _w=werte):
        GERUFEN.append((_n, user, feld))
        f = (feld or "").strip() or _f[0]
        if f not in _f:
            return "", "Das Feld '%s' ist kein Geheimfeld dieses Zugangs." % f
        wert = (_w.get(user) or {}).get(f, "")
        if not wert:
            return "", "In diesem Feld ist nichts gespeichert."
        return wert, ""

    m.klartext = klartext
    return m


KONTEN = {
    "mail": _mach_konto("mail", ("passwort",), {"anna": {"passwort": "Post!1"}}),
    "sap": _mach_konto("sap", ("password", "bearer_token", "hana_password",
                               "rfc_password"), {"anna": {"password": "Sap!2"}}),
    "vemas": _mach_konto("vemas", ("password", "api_token"),
                         {"anna": {"api_token": "Vem!3"}}),
    "jira": _mach_konto("jira", ("api_token",), {"anna": {"api_token": "Jir!4"}}),
}
for n, m in KONTEN.items():
    sys.modules["backend.%s_accounts" % n] = m


class _Cfg:
    """Steht fuer backend.config.config – nur die Felder, die geprueft werden."""

    def __init__(self):
        self.llm_profiles = [{"id": "p1", "api_key": "sk-geheim", "session_key": ""}]
        self.ad_bind_password = "BindGeheim"
        # ⚠ Das ist der Grund fuer die Erlaubnisliste: dieses Feld darf NIE
        # ueber den Endpunkt herauskommen.
        self.jwt_secret = "SIGNIERSCHLUESSEL"

    def get_skill_states(self):
        return {
            "knowledge": {"config": {"mounts": [
                {"source": "//srv/a", "username": "ki_read", "password": "MntGeheim"},
                {"source": "//srv/b", "username": "x"},
            ]}},
            "jira": {"config": {"api_token": "SammelToken", "base_url": "https://j"}},
        }


_cfgmod = types.ModuleType("backend.config")
_cfgmod.config = _Cfg()
sys.modules["backend.config"] = _cfgmod

from backend import secret_reveal as sr  # noqa: E402

# ══ 1. Drossel ═════════════════════════════════════════════════════════════
abschnitt("1 – Die Drossel bremst, sie sperrt nicht")

sr._reset_fuer_tests()
check("Positivkontrolle: der erste Abruf ist erlaubt", sr.drossel_ok("anna")[0])
for _ in range(sr.MAX_JE_STUNDE - 1):
    sr.drossel_ok("anna")
erl, grund = sr.drossel_ok("anna")
check("⚠ nach MAX_JE_STUNDE Abrufen wird gebremst", not erl, str(erl))
check("… und der Grund sagt, dass es keine Aussage ueber die Berechtigung ist",
      "Berechtigung" in grund, grund[:80])
check("⚠ ein ANDERER Benutzer ist davon nicht betroffen",
      sr.drossel_ok("bert")[0])
sr._reset_fuer_tests()
check("… nach dem Zurcksetzen wieder frei", sr.drossel_ok("anna")[0])

# ══ 2. Quellen ═════════════════════════════════════════════════════════════
abschnitt("2 – Jede Quelle liefert (wert, fehler), nie beides leer")

for b in ("mail", "sap", "vemas", "jira"):
    q = sr.benutzer_quelle(b)
    check("Bereich '%s' hat eine Quelle" % b, callable(q))
check("⚠ ein unbekannter Bereich hat KEINE Quelle (fail-closed)",
      sr.benutzer_quelle("wolke") is None)
check("… und ein leerer auch nicht", sr.benutzer_quelle("") is None)
check("Gross/Klein ist unerheblich", callable(sr.benutzer_quelle("SAP")))

w, f = sr.benutzer_quelle("mail")("anna", "passwort")
check("die Quelle gibt den Wert heraus", w == "Post!1" and not f, "%r/%r" % (w, f))
w, f = sr.benutzer_quelle("sap")("anna", "hana_password")
check("⚠ ein leeres Feld meldet einen GRUND, nicht nur nichts",
      w == "" and bool(f), "%r/%r" % (w, f))
w, f = sr.benutzer_quelle("sap")("anna", "connection_type")
check("⚠ ein Nicht-Geheimfeld wird abgewiesen (fail-closed)",
      w == "" and "Geheimfeld" in f, f)

abschnitt("2b – Freigabe, Profil, Skill, Einstellung")

w, f = sr.mount("0")
check("mount: das Kennwort einer Freigabe kommt heraus", w == "MntGeheim", "%r" % w)
w, f = sr.mount("1")
check("mount: eine Freigabe ohne Kennwort meldet den Grund", not w and bool(f), f)
w, f = sr.mount("7")
check("mount: ein Index ausserhalb wird abgewiesen", not w and bool(f), f)
w, f = sr.mount("../etc")
check("⚠ mount: eine Kennung, die kein Index ist, wird abgewiesen",
      not w and bool(f), f)

# ⚠ ES GIBT KEINE BEREICHE "profil" UND "skill" – und das ist gewollt: die
# betreffenden Formulare laden ihr Geheimnis laengst selbst im Klartext
# (`/api/profiles/{id}/key`, `/api/skills/{name}/config`). Ein Zweig ohne
# Aufrufer waere eine zweite Rechtefrage auf dasselbe Geheimnis.
for tot in ("profil", "skill"):
    check("⚠ das Modul hat keinen Zweig '%s' (waere toter Code)" % tot,
          not hasattr(sr, tot))

w, f = sr.einstellung("ad_bind_password")
check("einstellung: ein freigegebenes Feld kommt heraus", w == "BindGeheim", "%r" % w)
w, f = sr.einstellung("jwt_secret")
check("⚠⚠ DER SIGNIERSCHLUESSEL DER SITZUNGSTOKEN KOMMT NICHT HERAUS",
      not w and "nicht zum Ansehen freigegeben" in f, "%r/%r" % (w, f))
check("… und er steht nicht in der Erlaubnisliste",
      "jwt_secret" not in sr.EINSTELLUNG_ERLAUBT)
check("⚠ die Liste ist eine ERLAUBNIS-, keine Sperrliste (endlich und klein)",
      0 < len(sr.EINSTELLUNG_ERLAUBT) <= 12, str(len(sr.EINSTELLUNG_ERLAUBT)))
w, f = sr.einstellung("")
check("einstellung: ein leeres Feld wird abgewiesen", not w and bool(f), f)

# ══ 3. Der Endpunkt: Schnitt aus backend/main.py ════════════════════════════
abschnitt("3 – Der Endpunkt wird geschnitten und AUSGEFUEHRT")

MAIN = ROOT / "backend" / "main.py"
QUELL = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)
FUNKTIONEN = {n.name: n for n in BAUM.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
if "secret_reveal" not in FUNKTIONEN:
    abbruch("secret_reveal nicht in backend/main.py gefunden")

# Der Pfad wird am Quelltext geprueft, damit er nicht unbemerkt wandert.
_dek = ast.unparse(ast.Module(body=[ast.Expr(d) for d in
                                    FUNKTIONEN["secret_reveal"].decorator_list],
                              type_ignores=[]))
check("die Route heisst POST /api/secret/reveal",
      "app.post('/api/secret/reveal')" in _dek.replace('"', "'"), _dek)
check("⚠ sie haengt an require_auth (die Matrix steht im Rumpf, s. Kopf)",
      "require_auth" in ast.unparse(FUNKTIONEN["secret_reveal"].args))


class Antwort:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class Anfrage:
    def __init__(self, body=None, roh=False):
        self._body, self._roh = body, roh

    async def json(self):
        if self._roh:
            raise ValueError("kein JSON")
        return self._body


AUDIT = []


class _Audit:
    @staticmethod
    def log_tool(user, tool, args, a=0, b=0):
        AUDIT.append({"user": user, "tool": tool, "args": args})


# ⚠ DIE ATTRAPPE WIRD ALS MODUL GESTELLT, NICHT ALS GLOBALER NAME – und das ist
# der Unterschied zwischen einem Waechter, der wirkt, und einem, der nicht
# wirkt: `audit_log` ist in main.py KEIN Modulname, der Rumpf muss es selbst
# importieren. Die erste Fassung dieses Tests reichte `audit_log` in den
# Namensraum und war damit gruen, waehrend der Endpunkt live NULL Eintraege
# schrieb (NameError, verschluckt vom breiten `except`). Erst die Live-Probe
# auf DEV hat es gezeigt.
_al_mod = types.ModuleType("backend.audit_log")
_al_mod.log_tool = _Audit.log_tool
sys.modules["backend.audit_log"] = _al_mod


RECHTE = {"admin": set(), "email": set(), "sap": set(), "vemas": set(),
          "jira": set(), "kb": set()}
WIRFT = set()


def _darf(schluessel):
    def fn(user):
        if schluessel in WIRFT:
            raise RuntimeError("Freigabeliste nicht lesbar")
        return user in RECHTE[schluessel]
    return fn


AUSGABE = []

NS = {
    "time": time, "asyncio": asyncio, "print": lambda *a, **k: AUSGABE.append(a),
    "Request": Anfrage, "JSONResponse": Antwort,
    "Depends": lambda x: None, "require_auth": None,
    "app": type("App", (), {"post": staticmethod(lambda *a, **k: (lambda f: f))})(),
    "_is_admin_user": _darf("admin"),
    "_user_may_use_email": _darf("email"),
    "_user_may_use_sap": _darf("sap"),
    "_user_may_use_vemas": _darf("vemas"),
    "_user_may_use_jira_assist": _darf("jira"),
    "_may_edit_knowledge": _darf("kb"),
}
kopie = ast.parse(ast.unparse(FUNKTIONEN["secret_reveal"])).body[0]
kopie.decorator_list = []
exec(compile(ast.fix_missing_locations(ast.Module(body=[kopie], type_ignores=[])),
             "<main-schnitt>", "exec"), NS)
endpunkt = NS["secret_reveal"]

_LOOP = asyncio.new_event_loop()


def ruf(user, bereich, kennung="", extra=None):
    """Ein Abruf. Gibt (status, rumpf) zurueck."""
    body = {"bereich": bereich, "kennung": kennung}
    if extra:
        body.update(extra)
    AUDIT.clear()
    sr._reset_fuer_tests()
    a, f = sicher(_LOOP.run_until_complete, endpunkt(Anfrage(body), user=user))
    if a is None:
        return -1, {"_abbruch": f}
    return a.status_code, a.content


# ══ 4. Die Rechtematrix ════════════════════════════════════════════════════
abschnitt("4 – Die Rechtematrix, je Bereich gemessen")

for b, sch, feld, wert in (("mail", "email", "passwort", "Post!1"),
                           ("sap", "sap", "password", "Sap!2"),
                           ("vemas", "vemas", "api_token", "Vem!3"),
                           ("jira", "jira", "api_token", "Jir!4")):
    RECHTE[sch] = set()
    s, r = ruf("anna", b, feld)
    check("⚠ %-5s ohne Bereichs-Freigabe: 403" % b, s == 403, "%s %s" % (s, r))
    check("… und der Wert kommt NICHT mit",
          wert not in str(r), str(r)[:120])
    RECHTE[sch] = {"anna"}
    s, r = ruf("anna", b, feld)
    check("… mit Freigabe: der eigene Wert (Positivkontrolle)",
          s == 200 and r.get("wert") == wert, "%s %s" % (s, r))
    # Ein Administrator ohne Bereichs-Freigabe kommt NICHT an fremde
    # Zugangsdaten – die vier Bereiche kennen bewusst keinen Admin-Bypass.
    RECHTE["admin"] = {"chef"}
    RECHTE[sch] = set()
    s, r = ruf("chef", b, feld)
    check("⚠ %-5s: ein ADMIN ohne Bereichs-Freigabe wird abgewiesen" % b,
          s == 403, "%s %s" % (s, r))
    RECHTE["admin"] = set()

RECHTE["kb"] = set()
RECHTE["admin"] = set()
s, r = ruf("anna", "mount", "0")
check("⚠ mount ohne Wissens-Editor-Recht: 403", s == 403, "%s %s" % (s, r))
check("… ohne das Kennwort im Text", "MntGeheim" not in str(r), str(r)[:120])
RECHTE["kb"] = {"anna"}
s, r = ruf("anna", "mount", "0")
check("mount als Wissens-Editor: der Wert (Positivkontrolle)",
      s == 200 and r.get("wert") == "MntGeheim", "%s %s" % (s, r))
RECHTE["kb"] = set()
RECHTE["admin"] = {"chef"}
s, r = ruf("chef", "mount", "0")
check("mount als Administrator: ebenfalls erlaubt",
      s == 200 and r.get("wert") == "MntGeheim", "%s %s" % (s, r))
RECHTE["admin"] = set()

for b, kennung, wert in (("einstellung", "ad_bind_password", "BindGeheim"),):
    RECHTE["admin"] = set()
    RECHTE["kb"] = {"anna"}          # ein anderes Recht hilft hier NICHT
    s, r = ruf("anna", b, kennung)
    check("⚠ %-12s nur fuer Administratoren: 403" % b, s == 403, "%s %s" % (s, r))
    check("… ohne den Wert im Text", wert not in str(r), str(r)[:120])
    RECHTE["admin"] = {"chef"}
    s, r = ruf("chef", b, kennung)
    check("… als Administrator: der Wert (Positivkontrolle)",
          s == 200 and r.get("wert") == wert, "%s %s" % (s, r))
RECHTE["admin"] = set()
RECHTE["kb"] = set()

s, r = ruf("anna", "wolke", "x")
check("⚠ ein unbekannter Bereich: 400, kein Rateweg", s == 400, "%s %s" % (s, r))
RECHTE["admin"] = {"chef"}
for tot, kennung in (("profil", "p1:api_key"), ("skill", "jira:api_token")):
    s, r = ruf("chef", tot, kennung)
    check("⚠ '%s' wird ABGEWIESEN, auch fuer einen Administrator" % tot,
          s == 400, "%s %s" % (s, r))
RECHTE["admin"] = set()
s, r = ruf("anna", "", "")
check("… ein leerer Bereich ebenso", s == 400, "%s %s" % (s, r))

# ══ 5. Kein Benutzername aus dem Rumpf ═════════════════════════════════════
abschnitt("5 – Der Benutzer kommt AUSSCHLIESSLICH aus der Anmeldung")

RECHTE["mail"] = set()
RECHTE["email"] = {"bert"}
GERUFEN.clear()
s, r = ruf("bert", "mail", "passwort",
           extra={"user": "anna", "benutzer": "anna", "username": "anna",
                  "owner": "anna"})
check("⚠ vier Benutzerfelder im Rumpf aendern NICHTS",
      all(u == "bert" for _n, u, _f in GERUFEN) and GERUFEN,
      str(GERUFEN))
check("… es kommt kein fremder Wert heraus",
      "Post!1" not in str(r), "%s %s" % (s, r))
quelle = ast.unparse(FUNKTIONEN["secret_reveal"])
_ohne_doc = quelle.split('"""')
_rumpf = "".join(_ohne_doc[2:]) if len(_ohne_doc) > 2 else quelle
for feld in ("'user'", '"user"', "'benutzer'", "'owner'", "'username'"):
    check("… und der Rumpf liest %s nicht aus data" % feld,
          ("data.get(%s" % feld) not in _rumpf)

# ══ 6. Audit ═══════════════════════════════════════════════════════════════
abschnitt("6 – Jeder Abruf ins Audit, NIE der Wert")

RECHTE["email"] = {"anna"}
s, r = ruf("anna", "mail", "passwort")
check("Positivkontrolle: der erfolgreiche Abruf steht im Audit",
      len(AUDIT) == 1 and AUDIT[0]["tool"] == "secret_reveal", str(AUDIT))
check("… mit Bereich und Kennung",
      AUDIT and AUDIT[0]["args"].get("bereich") == "mail"
      and AUDIT[0]["args"].get("kennung") == "passwort", str(AUDIT))
check("⚠⚠ DER WERT STEHT NICHT IM AUDIT",
      "Post!1" not in str(AUDIT), str(AUDIT))
check("… und auch nicht in der Journal-Zeile",
      "Post!1" not in str(AUSGABE), str(AUSGABE)[-200:])

RECHTE["email"] = set()
s, r = ruf("anna", "mail", "passwort")
check("⚠ auch der ABGELEHNTE Abruf steht im Audit", len(AUDIT) == 1, str(AUDIT))
check("… und ist als solcher erkennbar",
      AUDIT and AUDIT[0]["args"].get("ergebnis") not in (None, "herausgegeben"),
      str(AUDIT))

s, r = ruf("anna", "wolke", "x")
check("⚠ ein unbekannter Bereich ebenfalls", len(AUDIT) == 1, str(AUDIT))
RECHTE["email"] = {"anna"}
s, r = ruf("anna", "mail", "gibtsnicht")
check("⚠ und ein Abruf ohne Wert ebenfalls (404)",
      s == 404 and len(AUDIT) == 1, "%s %s" % (s, AUDIT))

# Die Drossel wird VOR der Rechtepruefung angewandt – sonst waere sie ueber
# einen Bereich ohne Freigabe umgehbar.
sr._reset_fuer_tests()
for _ in range(sr.MAX_JE_STUNDE):
    sr.drossel_ok("anna")
AUDIT.clear()
a, _f = sicher(_LOOP.run_until_complete,
               endpunkt(Anfrage({"bereich": "mail", "kennung": "passwort"}),
                        user="anna"))
check("⚠ die Drossel antwortet mit 429", a is not None and a.status_code == 429,
      str(a and a.status_code))
check("… und auch das steht im Audit", len(AUDIT) == 1, str(AUDIT))
sr._reset_fuer_tests()

# ══ 7. Fail-closed ═════════════════════════════════════════════════════════
abschnitt("7 – Fail-closed")

RECHTE["email"] = {"anna"}
WIRFT.add("email")
s, r = ruf("anna", "mail", "passwort")
check("⚠ wirft die Freigabepruefung, wird ABGEWIESEN (nicht durchgelassen)",
      s == 403, "%s %s" % (s, r))
WIRFT.discard("email")

s, r = -1, None
AUDIT.clear()
sr._reset_fuer_tests()
a, f = sicher(_LOOP.run_until_complete, endpunkt(Anfrage(None, roh=True), user="anna"))
check("ein Rumpf ohne JSON bricht nicht ab, sondern antwortet",
      a is not None and a.status_code == 400, f or str(a and a.status_code))

# ══ 8. Die alten Zusagen gelten fuer die UEBERSICHTEN weiter ════════════════
abschnitt("8 – Die Uebersichten geben weiterhin nichts heraus")

def _ohne_docstring(knoten):
    """Der Rumpf OHNE Docstring.

    ⚠ NOETIG, UND ZWAR VOM ERSTEN LAUF AN GEMESSEN: die Uebersicht von
    ``sap_accounts`` erklaert in ihrem Docstring, dass den Klartext
    ``klartext()`` herausgibt – und der Waechter las damit seine eigene
    Begruendung und meldete einen Fehler, den es nicht gab. Dreizehnter Fall
    dieser Klasse im Projekt.
    """
    kopie = ast.parse(ast.unparse(knoten)).body[0]
    if (kopie.body and isinstance(kopie.body[0], ast.Expr)
            and isinstance(kopie.body[0].value, ast.Constant)
            and isinstance(kopie.body[0].value.value, str)):
        kopie.body = kopie.body[1:] or [ast.Pass()]
    return ast.unparse(kopie)


# Die Uebersichtsfunktion heisst je Modul anders (mail: konto_info) – gesucht
# wird die, die es gibt, nicht ein geratener Name.
UEBERSICHT = {"mail": "konto_info", "sap": "zugang_info",
              "vemas": "zugang_info", "jira": "zugang_info"}
for name in ("mail", "sap", "vemas", "jira"):
    q = (ROOT / "backend" / ("%s_accounts.py" % name)).read_text(encoding="utf-8")
    baum = ast.parse(q)
    fns = {n.name: n for n in baum.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    check("%s_accounts hat genau eine Abruf-Funktion 'klartext'" % name,
          "klartext" in fns)
    info = fns.get(UEBERSICHT[name])
    if info is None:
        check("%s_accounts: %s gefunden" % (name, UEBERSICHT[name]), False, "fehlt")
        continue
    txt = _ohne_docstring(info)
    check("Positivkontrolle: der Docstring ist heraus",
          "Klartext" not in txt or "klartext(" in txt, txt[:100])
    # Die Uebersicht darf kein Geheimnis entschluesseln – sonst haette die
    # Trennung "nur auf benannten Abruf" keinen Bestand.
    check("⚠ %s_accounts.%s entschluesselt NICHTS" % (name, UEBERSICHT[name]),
          "entschluesseln(" not in txt and "klartext(" not in txt, txt[:160])

# Der Modulkopf muss die Umkehrung BENENNEN – sonst haelt der naechste Leser
# die alte Zusage fuer unveraendert gueltig.
kopf = (ROOT / "backend" / "secret_reveal.py").read_text(encoding="utf-8")[:4000]
check("secret_reveal.py nennt die Anweisung des Betreibers",
      "Anweisung des Betreibers" in kopf or "ANWEISUNG DES BETREIBERS" in kopf)
check("… und benennt den PREIS (was eine uebernommene Sitzung jetzt kann)",
      "AUSLESEN" in kopf or "auslesen" in kopf, kopf[:80])

abschnitt("9 – Der Rumpf holt audit_log SELBST (kein Modulname in main.py)")
check("⚠ das Protokoll wird ueber einen eigenen Import geschrieben",
      "from backend import audit_log" in ast.unparse(FUNKTIONEN["secret_reveal"]))
check("Positivkontrolle: main.py hat audit_log NICHT als Modulnamen",
      not any(isinstance(n, ast.ImportFrom) and n.module == "backend"
              and any(a.name == "audit_log" and a.asname is None for a in n.names)
              for n in BAUM.body))

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)

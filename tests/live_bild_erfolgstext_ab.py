#!/usr/bin/env python3
"""A/B am ECHTEN Modell: liest das Modell den Ersatztext als Fehler?

DER VORFALL (ECHT, 2026-08-30): das Werkzeug lieferte ein fertiges Bild, das
Modell antwortete "Die Bildgenerierung ist fehlgeschlagen. Fehlermeldung:
'Failed to parse as a valid JSON'." - eine frei erfundene Meldung.

Verdacht: der Ersatztext des Werkzeug-Ergebnisses liest sich wie eine
Stoerungsmeldung. Hier wird das gemessen, nicht vermutet: derselbe Dialog,
einmal mit dem ALTEN und einmal mit dem NEUEN Text, je N Laeufe.

Exit 0 = der neue Text ist nicht schlechter, 1 = FAIL, 2 = konnte nicht laufen.
"""
import asyncio, re, sys
sys.path.insert(0, "/opt/jarvis")

from backend.llm import get_provider          # noqa: E402
from backend.config import config             # noqa: E402
from google.genai import types                # noqa: E402


def _c(rolle, text):
    """Verlaufs-Eintrag im Format, das der Agent benutzt (types.Content)."""
    return types.Content(role=rolle, parts=[types.Part.from_text(text=text)])


def _aktiver_provider():
    """Baut den Provider aus dem AKTIVEN Profil - so wie run_task es tut."""
    # Direkt aus data/settings.json - config.get_setting("profiles") liefert
    # sie nicht heraus (eigene interne Struktur), und der Test soll genau die
    # Konfiguration benutzen, mit der der Dienst arbeitet.
    import json
    _d = json.load(open("/opt/jarvis/data/settings.json"))
    aktiv = _d.get("active_profile_id")
    profs = _d.get("profiles") or []
    p = next((x for x in profs if x.get("id") == aktiv), None) or (profs[0] if profs else None)
    if not p:
        print("KONNTE NICHT LAUFEN: kein LLM-Profil konfiguriert")
        sys.exit(2)
    return get_provider(
        p.get("provider") or "openai_compatible",
        p.get("api_key") or "",
        p.get("api_url"),
        auth_method=p.get("auth_method") or "api_key",
        session_key=p.get("session_key"),
        prompt_tool_calling=bool(p.get("prompt_tool_calling")),
    ), p

URL = "/api/generated/cb20b70daaf9e720a7f7591c49b6644e.png"

ALT = ("[BILDDATEN AUSGELAGERT: PNG, 1966 KB. "
       "Base64 gehoert NICHT in deine Antwort – sie wird nicht angezeigt und "
       "fuellt den Kontext. Gib stattdessen GENAU diese Zeile unveraendert aus, "
       f"damit das Bild erscheint:]\n![Bild]({URL})")

NEU = ("[BILD ERFOLGREICH ERZEUGT – KEIN FEHLER. "
       "PNG, 1966 KB, fertig gespeichert. "
       "Uebernimm die folgende Zeile unveraendert in deine Antwort, dann "
       "sieht der Benutzer das Bild. Melde KEINEN Fehlschlag.]\n"
       f"![Bild]({URL})")

SYS = ("Du bist ein hilfreicher Agent. Der Benutzer hat um ein Bild gebeten. "
       "Du hast das Werkzeug 'delegate' mit der Rolle 'image_builder' aufgerufen. "
       "Formuliere jetzt deine Antwort an den Benutzer.")

FEHLERWORT = re.compile(r"fehlgeschlagen|fehler|scheiterte|nicht m\w+glich|"
                        r"konnte nicht|problem|failed", re.IGNORECASE)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5


MODELL = None


async def einmal(prov, ergebnis):
    """Ein echter Modellaufruf. WIRFT bei einem Aufrufproblem - ein
    gescheiterter Aufruf ist KEIN Messwert. Die erste Fassung gab den
    Fehlertext als Antwort zurueck; weil darin "Fehler" steht, zaehlte der Test
    ihn als Fehler-Behauptung, beide Varianten waren gleich schlecht und der
    Lauf meldete BESTANDEN, ohne ein einziges Mal das Modell gefragt zu haben."""
    contents = [
        _c("user", "setze der Kuh einen Helm auf"),
        _c("model", "Ich delegiere das an die Rolle image_builder."),
        _c("user", f"Ergebnis der Rolle 'image_builder':\n{ergebnis}"),
    ]
    r = await prov.generate_response(MODELL, SYS, contents, tools=None)
    # Der Text kann als .text ODER in .parts stecken (Denkmodus liefert
    # zusaetzlich thinking-Parts). Beides abklopfen, sonst misst der Test
    # eine leere Zeichenkette und haelt sie fuer eine Antwort.
    t = (getattr(r, "text", None) or "").strip()
    if not t:
        stuecke = []
        for pt in (getattr(r, "parts", None) or []):
            x = getattr(pt, "text", None)
            if x:
                stuecke.append(x)
        t = "\n".join(stuecke).strip()
    if not t:
        raise RuntimeError(f"kein Text in der Antwort (Felder: {dir(r)[:6]}...)")
    return t


async def main():
    global MODELL
    prov, p = _aktiver_provider()
    MODELL = p.get("model")
    print(f"  Provider: {type(prov).__name__}  Modell: {p.get('model')!r}  "
          f"Laeufe je Variante: {N}\n")
    ergebnis = {}
    for name, txt in (("ALT", ALT), ("NEU", NEU)):
        fehler = url_da = 0
        for i in range(N):
            try:
                a = await einmal(prov, txt)
            except Exception as e:  # noqa: BLE001
                print(f"KONNTE NICHT LAUFEN: Modellaufruf scheiterte: {type(e).__name__}: {e}")
                sys.exit(2)
            if not a:
                print("KONNTE NICHT LAUFEN: Modell lieferte leeren Text")
                sys.exit(2)
            f = bool(FEHLERWORT.search(a))
            u = URL in a
            fehler += f
            url_da += u
            print(f"    {name} {i+1}: {'FEHLER-BEHAUPTUNG' if f else 'ok':18} "
                  f"{'Bild drin' if u else 'BILD FEHLT':10} | {a[:70]!r}")
        ergebnis[name] = (fehler, url_da)
        print()
    (fa, ua), (fn, un) = ergebnis["ALT"], ergebnis["NEU"]
    print(f"  ALT: {fa}/{N} behaupten einen Fehler, {ua}/{N} zeigen das Bild")
    print(f"  NEU: {fn}/{N} behaupten einen Fehler, {un}/{N} zeigen das Bild")
    ok = (fn <= fa) and (un >= ua)
    print(f"\n  -> {'BESTANDEN' if ok else 'FAIL'}: der neue Text ist nicht schlechter")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))

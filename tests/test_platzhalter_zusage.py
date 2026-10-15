"""Ein Platzhalter darf seine ZUSAGE nicht beim ersten Sprachwechsel verlieren.

DER FEHLER, DEN DAS VERHINDERT: `d9b3e43b` ("Kennwortfelder mit Sternen + Auge")
hat in i18n.js SIEBEN Platzhalter auf `••••••••` gesetzt - darunter sechs, die
keinen maskierten Wert trugen, sondern eine ZUSAGE:

    'mail.pw_ph':        'leer = unveraendert'          ->  '••••••••'
    'sap.acc_pass_ph':   'leer = unveraendert'          ->  '••••••••'
    'kbsync.f_token_keep': 'leer lassen = unveraendert' ->  '••••••••'
    ... und vier weitere

⚠ DIE ZUSAGE IST NICHT DEKORATION - jedes dieser Felder implementiert sie im
Backend, woertlich dokumentiert ("**Leeres Kennwortfeld heisst UNVERAENDERT**,
nicht 'loeschen'" in mail_accounts, sap_accounts, vemas_accounts,
jira_accounts, confluence_accounts; `if tok:  # leer = unveraendert` in
knowledge_sync; `uebernehme_kennwort()` fuer die Freigaben). Wer stattdessen
Punkte sieht, weiss NICHT, dass ein leeres Feld das Kennwort behaelt - und
tippt es entweder neu ein oder haelt das Feld fuer kaputt. Schlimmer: Punkte
legen nahe, dass dort ein Wert STEHT, obwohl das Feld leer ist.

⚠ DAS MARKUP WAR DIE GANZE ZEIT RICHTIG. In sechs Seiten steht der Hinweis als
Fallback im Tag (`placeholder="leer = unveraendert"`) - `applyLang()` ersetzt
ihn beim ersten Sprachwechsel durch den i18n-Wert. Die Seite sah also beim
ersten Aufbau korrekt aus und wurde danach falsch; genau deshalb ist es
niemandem aufgefallen. (Register: `data-i18n` setzt den Wert neu und loescht,
was im Markup stand.)

⚠ GEFUNDEN HAT ES EIN WAECHTER, DER SEIT WOCHEN NICHT LIEF
(`test_knowledge_sync_ui.js`, siehe `18923738`) - und auch der kannte nur
EINEN der sieben Faelle. Deshalb hier eine REGEL statt einer Nachbesserung.

DIE REGEL, und sie ist rauschfrei: wo ein Feld BEIDES traegt - einen
Markup-Fallback und `data-i18n-placeholder` -, duerfen die beiden sich nicht
WIDERSPRECHEN. Nennt der Fallback eine Zusage ("leer", "unveraendert"), muss
der deutsche i18n-Wert sie auch nennen. Gemessen beim Anlegen: 68 solche
Felder, 0 Widersprueche.

⚠ KEINE GEPFLEGTE SCHLUESSELLISTE. Eine Liste der sieben Schluessel waere an
dem Tag unvollstaendig, an dem jemand ein achtes Kennwortfeld baut - und genau
so ist der Fehler entstanden (`caddon.acc_token_ph` kam NACH dem Sweep dazu und
hat die Punkte mitkopiert).

Lauf:  python3 tests/test_platzhalter_zusage.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N = ROOT / "frontend" / "js" / "i18n.js"

# Woerter, die eine ZUSAGE tragen - nicht die Schluesselnamen, sondern das, was
# der Benutzer liest. „leer"/„unver" decken beide Schreibweisen ab, die im
# Haus vorkommen ("leer = unveraendert", "leer lassen = unveraendert").
_ZUSAGE = ("unver", "leer")

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def abbruch(text):
    """Exit 2 = konnte nicht laufen, NICHT 'Waechter beisst'."""
    print(f"\n\033[31mABBRUCH: {text}\033[0m")
    sys.exit(2)


if not I18N.exists():
    abbruch("frontend/js/i18n.js gibt es nicht")
i18n = I18N.read_text(encoding="utf-8", errors="replace")


def de_wert(key):
    """Der DEUTSCHE Wert eines Schluessels.

    i18n.js fuehrt erst den DE-, dann den EN-Block - das ERSTE Vorkommen ist
    also der deutsche Wert. Verglichen wird bewusst nur gegen ihn: die
    Markup-Fallbacks sind durchweg deutsch, ein englischer Wert („empty =
    unchanged") traegt die Zusage in anderen Worten und waere hier ein
    Fehlalarm.
    """
    m = re.search(r"'" + re.escape(key) + r"':\s*'([^']*)'", i18n)
    return m.group(1) if m else None


print("\n\033[1m1. Grundlage und Positivkontrollen\033[0m")

paare = []
for seite in sorted((ROOT / "frontend").rglob("*.html")):
    text = seite.read_text(encoding="utf-8", errors="replace")
    for tag in re.finditer(r"<input[^>]*>", text):
        roh = tag.group(0)
        k = re.search(r'data-i18n-placeholder="([^"]+)"', roh)
        fb = re.search(r'\splaceholder="([^"]*)"', roh)
        if k and fb:
            paare.append((k.group(1), fb.group(1), seite.name))

if len(paare) < 20:
    abbruch(f"nur {len(paare)} Felder mit Fallback UND data-i18n-placeholder "
            "gefunden (erwartet: Dutzende) - der Messaufbau greift nicht")
check(f"{len(paare)} Felder tragen Fallback UND data-i18n-placeholder", True)

# ⚠ OHNE DIESE KONTROLLE IST DIE REGEL TRIVIAL GRUEN: findet `de_wert` nie
# etwas (umbenannte Datei, geaendertes Format), waere jeder Vergleich leer.
aufgeloest = sum(1 for k, _, _ in paare if de_wert(k) is not None)
check(f"{aufgeloest} davon lassen sich in i18n.js aufloesen",
      aufgeloest >= len(paare) // 2, f"{aufgeloest} von {len(paare)}")

# Die Zusage-Erkennung selbst gegen einen bekannten Fall - sonst koennte
# `_ZUSAGE` ins Leere greifen und alles waere still in Ordnung.
check("die Zusage-Erkennung trifft einen bekannten Text",
      any(w in "leer = unveraendert" for w in _ZUSAGE))
check("und NICHT einen beliebigen Platzhalter",
      not any(w in "vorname.nachname@firma.de" for w in _ZUSAGE))

if res.count(False):
    abbruch(f"{res.count(False)} Positivkontrolle(n) durchgefallen - das "
            "Messwerkzeug ist defekt, Abschnitt 2 waere wertlos")

print("\n\033[1m2. Der i18n-Wert widerspricht dem Markup-Fallback nicht\033[0m")

funde = []
for key, fallback, datei in paare:
    wert = de_wert(key)
    if wert is None:
        continue
    for wort in _ZUSAGE:
        if wort in fallback.lower() and wort not in wert.lower():
            funde.append((key, datei, fallback, wert))
            break

for key, datei, fallback, wert in funde:
    check(f"{key} ({datei})", False,
          f"Markup verspricht '{fallback}', i18n setzt '{wert}' – "
          "applyLang() ueberschreibt die Zusage beim ersten Sprachwechsel")
if not funde:
    check(f"kein Widerspruch in {len(paare)} Feldern", True)

schlecht = res.count(False)
print(f"\n\033[1mErgebnis: {len(res) - schlecht}/{len(res)}\033[0m")
sys.exit(1 if schlecht else 0)

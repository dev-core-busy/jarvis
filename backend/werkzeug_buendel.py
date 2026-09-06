"""Aufgabenabhaengiger Werkzeug-Zuschnitt - weniger Angebot, gleicher Umfang.

═══ WARUM ES DAS GIBT (gemessen 2026-09-06) ═══

Je Anfrage gehen die Schemata ALLER Werkzeuge an das Modell. Auf DEV sind das
85 Stueck = 70.309 Zeichen, zusammen mit dem System-Prompt 25.866 Prompt-Token.
Gemessen am echten vLLM des aktiven Profils:

    alle Werkzeuge, stabil (heute)      257 ms   25.866 Token
    zugeschnitten, stabile Teilmenge    221 ms    8.349 Token   (-68 % / -14 %)
    zugeschnitten, je Aufgabe NEU       381 ms    8.247 Token   (-68 % / +48 %)

Der Zuschnitt spart also gut zwei Drittel der Prompt-Token - aber NUR, wenn die
Teilmenge STABIL bleibt. Jede neue Zusammenstellung ist ein Cache-Miss, und der
kostet hier +81 % (16 Laeufe je Variante, gleiche Token-Zahl, Positivkontrolle).
Deshalb gibt es WENIGE FESTE BUENDEL statt einer Auswahl je Aufgabe: nach dem
ersten Lauf liegt jedes im Prefix-Cache.

⚠ UND DESHALB IST DIE SORTIERUNG TEIL DER SACHE, NICHT KOSMETIK: dieselbe
Werkzeugmenge in anderer REIHENFOLGE kostete in derselben Messung +364 %
(1.194 ms statt 257 ms). ``zuschnitt()`` gibt die Werkzeuge deshalb immer in
der Reihenfolge des Aufrufers zurueck - nie in der einer Menge.

═══ WAS DIE BUENDEL SIND - UND WAS SIE NICHT SIND ═══

Sie sind eine ANZEIGE-Entscheidung: was das Modell zu sehen bekommt. Die harte
Schranke bleibt der Dispatch (``_execute_tool``) - genau wie bei
``_BLOCKED_TOOLS_FOR_LDAP``. Ein Buendel gibt NIE ein Werkzeug frei, das der
Auftraggeber nicht ohnehin haette: ``zuschnitt()`` bekommt die bereits
gefilterte Liste und kann daraus nur WEGNEHMEN. Dieselbe Formel wie bei den
Rollen-Agenten - wer die Richtung umkehrt, macht daraus einen Weg um die
Rechtepruefung.

═══ FAIL-OPEN, UND ZWAR AN DREI STELLEN ═══

Ein zu enger Zuschnitt ist der teure Fehler: fehlt dem Modell das Werkzeug,
sagt es nicht "ich habe es nicht", sondern erfindet eine Begruendung und weicht
aus (im Projekt belegt: "Die Base64-URL war zu lang", "matplotlib statt
generate_image"). Deshalb:
  1. Der KERN ist immer dabei - er deckt die Werkzeuge ab, die in echten
     Laeufen quer durch alle Aufgaben vorkommen.
  2. Erkennt die Heuristik nichts Eindeutiges, gilt der VOLLE Satz.
  3. ``nachladen()`` schaltet fuer den restlichen Lauf auf den vollen Satz -
     der Weg zurueck existiert immer.
Ein zu WEITER Zuschnitt kostet dagegen nur Token. Die Fehlerlagen sind nicht
gleich schwer, also faellt die Vorgabe in die harmlose Richtung.
"""
from __future__ import annotations

import re

# ── Kern: geht in JEDEM Buendel mit ────────────────────────────────────────
# Abgeleitet aus 403 echten Laeufen auf DEV (Audit-Log gegen Konversations-
# Index): diese Werkzeuge tauchen quer durch alle Aufgabenarten auf, ihre
# Abwesenheit waere in jedem zweiten Lauf ein Fehlschlag.
KERN = (
    "knowledge_search",     # 24x - Punkt 1 des Prompts macht sie zur Vorbedingung
    "memory_manage",        # 62x - Punkt 3 und 12
    "filesystem",
    "shell_execute",        # 26x - der Ausweichweg fuer fast alles
    "werkzeuge_anfordern",  # der Rueckweg, siehe nachladen()
    # ⚠ Delegation gehoert in den KERN, nicht in ein Thema: sie kann bei JEDER
    # Aufgabe noetig sein, und ihr Fehlen macht Rollen-Agenten unbenutzbar.
    # Auf ECHT gemessen: delegate 91x, spawn_agent 10x in 30 Tagen.
    "delegate", "spawn_agent",
    # Auskunft ueber das eigene System - thematisch nirgends zuhause.
    "branding_info", "knowledge_manage",
)
# ⚠ `create_chart` gehoert NICHT in den Kern, obwohl es naheliegt: Punkt 20 des
# System-Prompts (4.270 Zeichen) nennt ausschliesslich Kern-Werkzeuge und waere
# damit UNENTFERNBAR - der Prompt-Zuschnitt unten koennte ihn nie weglassen.
# Es liegt stattdessen in drei Buendeln, in denen Zahlen vorkommen.

# ── Thematische Buendel ───────────────────────────────────────────────────
# Bewusst GROB: fuenf Themen, nicht fuenfzehn. Jedes zusaetzliche Buendel ist
# eine weitere Cache-Variante und eine weitere Stelle, an der die Heuristik
# danebenliegen kann.
BUENDEL: dict[str, tuple[str, ...]] = {
    "bild": (
        "generate_image", "search_image", "screenshot",
    ),
    "diagramm": (
        "create_chart",
    ),
    "dokument": (
        "office_create_word", "office_create_excel", "office_create_powerpoint",
        "office_read", "office_to_pdf", "office_template_info",
        "xlsx_inspect", "xlsx_read_range", "xlsx_merge", "xlsx_edit",
        "pdf_formular_extrakt", "excel_vorschlag", "create_chart",
    ),
    "desktop": (
        "desktop_control", "windows_desktop", "android_desktop", "screenshot",
        "read_clipboard", "write_clipboard", "browser_control", "browser_cdp",
    ),
    # 'fach' und 'kommunikation' kommen ueber PRAEFIXE (sap_/jira_/email_/...) -
    # Einzelnamen waeren hier genau die Liste, die unvollstaendig wird.
    "fach": (),
    "kommunikation": (),
}

# ── Heuristik ─────────────────────────────────────────────────────────────
# ⚠ Die Muster sind ABSICHTLICH breit und die Entscheidung ist ADDITIV: eine
# Aufgabe darf mehrere Buendel treffen ("erzeuge ein Bild und pack es in eine
# Praesentation"). Eng zu treffen waere hier der Fehler - siehe Fail-open oben.
_MUSTER: dict[str, str] = {
    # ⚠ DEUTSCHE KOMPOSITA: ein fuehrendes \b laesst "Balkendiagramm",
    # "Kundenvorgang", "Umsatztabelle" und "Bildschirmfoto" durchfallen - im
    # Deutschen steht das Schluesselwort meistens HINTEN im Wort. Wo das
    # vorkommt, faengt das Muster mit \w* an. Fehltreffer gehen dabei in die
    # harmlose Richtung (mehr Werkzeuge, nicht weniger).
    "bild": r"(\bbild\b|\w*bildschirm|\bfoto|\bgrafik|\billustration|\blogo\b|"
            r"\bmale\b|\bzeichne|\brender|\bscreenshot|\bimage\b|\bpicture\b)",
    "diagramm": r"(\w*diagramm|\w*chart\b|\bbalken|\bkurve|\btorte|\bplot\b|"
                r"\bvisualisier|\w*auswertung|\w*statistik|\w*kennzahl)",
    "dokument": r"(\bword\b|\bexcel|\bpowerpoint|\bpptx\b|\bxlsx\b|\bdocx\b|\bpdf\b|"
                r"\w*tabelle|\w*praesentation|\w*präsentation|\w*folie|\w*dokument|"
                r"\bbericht|\breport\b|\w*arbeitsmappe|\bcsv\b|\bspalte|\bzeile)",
    "desktop": r"(\w*desktop|\w*bildschirm|\w*fenster\b|\bmaus\b|\bklicke?\b|"
               r"\btastatur|\bbrowser|\w*webseite|\burl\b|\w*zwischenablage|"
               r"\bclipboard\b|\bwindows\b|\bandroid\b)",
    "fach": r"(\bjira\b|\w*ticket|\w*vorgang|\bconfluence\b|\bwiki\b|\bsap\b|"
            r"\bhana\b|\bodata\b|\bvemas\b|\bkunde|\bissue\b)",
    "kommunikation": r"(\bwhatsapp\b|\btelegram\b|\w*mail\b|\w*nachricht|\bsenden\b|"
                     r"\bschicke|\w*kalender|\w*termin|\bdrive\b|\bgmail\b)",
}
_KOMPILIERT = {k: re.compile(v, re.I) for k, v in _MUSTER.items()}

# Praefixe je Buendel - damit faellt ein KUENFTIGES sap_xyz von selbst richtig.
# ⚠ AM 2026-09-06 AUF ECHT BEZAHLT: die Buendel waren aus DEV-Daten abgeleitet,
# und DEV hat weder SAP noch E-Mail. Gemessen am dortigen Audit-Log waren
# 24 von 56 benutzten Werkzeugen in KEINEM Buendel - darunter sap_odata_query
# (174x), delegate (91x) und die ganze email_*-Familie. Eine Namensliste ist
# fuer eine Entscheidung dieser Tragweite die falsche Grundlage: sie ist an dem
# Tag unvollstaendig, an dem jemand einen Skill hinzufuegt.
PRAEFIXE: dict[str, tuple[str, ...]] = {
    "dokument":      ("office_", "xlsx_"),
    "desktop":       ("desktop_", "browser_", "windows_", "android_"),
    "fach":          ("sap_", "jira_", "confluence_", "vemas_", "kv_", "ibs_"),
    "kommunikation": ("email_", "mail_", "google_", "whatsapp_", "telegram_"),
}


def _themen_eines(name: str) -> set:
    """Welchen Themen ist dieses Werkzeug zugeordnet? LEER = keinem."""
    tr = {b for b, namen in BUENDEL.items() if name in namen}
    for b, prae in PRAEFIXE.items():
        if any(name.startswith(x) for x in prae):
            tr.add(b)
    return tr


def themen(aufgabe: str) -> set[str]:
    """Welche Buendel passen zu diesem Auftragstext? Leer = keine Aussage."""
    if not isinstance(aufgabe, str) or not aufgabe.strip():
        return set()
    return {name for name, rx in _KOMPILIERT.items() if rx.search(aufgabe)}


def erlaubte_namen(aufgabe: str) -> set[str] | None:
    """Namen, die das Modell sehen soll - oder ``None`` fuer "alle".

    ⚠ ``None`` HEISST "KEINE BESCHRAENKUNG", nicht "nichts". Die leere Menge
    waere das Gegenteil. Aufrufer duerfen deshalb NIE auf Falsyness pruefen -
    dieselbe Falle wie bei ``_role_tools`` (siehe agent.py).
    """
    tr = themen(aufgabe)
    if not tr:
        return None                      # fail-open: nichts erkannt = alles
    namen = set(KERN)
    for t in tr:
        namen |= set(BUENDEL.get(t, ()))
    return namen


def zuschnitt(werkzeuge: list, aufgabe: str) -> tuple[list, str]:
    """Die Liste des Aufrufers kuerzen - auf das, was NICHT fremd ist.

    ⚠ DIE REGEL IST UMGEKEHRT, UND DAS IST DER KERN: entfernt wird NUR, was
    einem ANDEREN Thema eindeutig zugeordnet ist. Ein Werkzeug, das zu KEINEM
    Thema gehoert, BLEIBT - auch wenn niemand es in eine Liste eingetragen hat.

    Die erste Fassung machte es andersherum ("nur was im Buendel steht, bleibt")
    und haette auf ECHT den kompletten SAP- und E-Mail-Zugriff weggenommen.
    Der Unterschied ist die Richtung der Halbfehlerstellung: ein zu weiter
    Zuschnitt kostet Token, ein zu enger ein Ergebnis.

    Gibt ``(liste, grund)`` zurueck. Die REIHENFOLGE des Aufrufers bleibt
    erhalten - eine Menge zu sortieren waere hier ein Cache-Miss (+364 %).
    Kann nur WEGNEHMEN, nie hinzufuegen.
    """
    tr = themen(aufgabe)
    if not tr:
        return werkzeuge, "voll (kein Thema erkannt)"
    kern = set(KERN)
    behalten = [t for t in werkzeuge
                if getattr(t, "name", "") in kern
                or not _themen_eines(getattr(t, "name", ""))
                or (_themen_eines(getattr(t, "name", "")) & tr)]
    # ⚠ Ein leeres Ergebnis waere ein Agent ohne Werkzeuge - das kann nur ein
    # Fehler in den Buendeln sein, nie eine gewollte Lage. Dann lieber alles.
    if not behalten:
        return werkzeuge, "voll (Zuschnitt waere leer)"
    return behalten, "+".join(sorted(tr))


# ══ Prompt-Zuschnitt ══════════════════════════════════════════════════════
# Die Punkte 15 (Bilder, 1.916 Z.), 16 (Office, 7.063 Z.) und 20 (Diagramme,
# 4.270 Z.) sind zusammen 62 % des Basis-Prompts und nennen ausschliesslich
# Skill-Werkzeuge. Fehlt das Werkzeug, ist die Regel dazu keine Anweisung mehr,
# sondern Rauschen - und im schlechtesten Fall verlangt sie etwas Unmoegliches.
#
# ⚠ DIE ZUORDNUNG WIRD GEMESSEN, NICHT GEPFLEGT: welcher Abschnitt zu welchem
# Werkzeug gehoert, steht im Abschnitt selbst. Eine gepflegte Liste liefe beim
# naechsten Prompt-Feinschliff auseinander - und die vergessene Zeile meldet
# sich nicht, sie laesst nur eine Regel still verschwinden.

import re as _re

_WERKZEUG_IM_TEXT = _re.compile(
    r"\b(office_[a-z_]+|xlsx_[a-z_]+|create_chart|generate_image|search_image|"
    r"knowledge_search|memory_manage|shell_execute|filesystem|screenshot|"
    r"desktop_control|windows_desktop|android_desktop|read_clipboard|"
    r"write_clipboard|spawn_agent|delegate|pdf_formular_extrakt|browser_control|"
    r"browser_cdp|werkzeuge_anfordern)\b")

# Ein Abschnitt beginnt mit "16. " oder "1b. " am Zeilenanfang.
_ABSCHNITT = _re.compile(r"(?m)^(?=(\d+[a-z]?)\.\s)")


def _bloecke(prompt: str) -> list[tuple[str, str]]:
    """(Nummer, Text) je Prompt-Abschnitt; der Kopf traegt die Nummer ''."""
    teile = _ABSCHNITT.split(prompt)
    out, i = [], 0
    if teile and not _re.match(r"^\d+[a-z]?\.\s", teile[0]):
        out.append(("", teile[0]))
        i = 1
    while i < len(teile):
        nummer = teile[i] if i + 1 < len(teile) else ""
        text = teile[i + 1] if i + 1 < len(teile) else ""
        out.append((nummer, text))
        i += 2
    return out


def prompt_zuschnitt(prompt: str, erlaubt: set | None) -> tuple[str, list[str]]:
    """Prompt-Abschnitte entfernen, deren Werkzeuge nicht angeboten werden.

    Gibt ``(text, entfernte_nummern)`` zurueck.

    DIE REGEL: ein Abschnitt faellt weg, wenn seine KENNZEICHNENDEN Werkzeuge
    (genannte minus KERN) nicht leer sind und keines davon angeboten wird.
    - Kern-Werkzeuge zaehlen NICHT als Kennzeichen: sie sind immer da und sagen
      deshalb nichts ueber den Abschnitt aus. Ohne diese Einschraenkung waere
      jeder Abschnitt, der irgendwo ``shell_execute`` erwaehnt, unentfernbar.
    - Ein Abschnitt ohne jede Werkzeug-Nennung bleibt IMMER (Sicherheits-
      Grundregel, Autonomie, Antwortsprache, Fehlerverhalten).
    - ``erlaubt is None`` (= voller Satz) laesst den Prompt unangetastet.

    ⚠ TOTE QUERVERWEISE WERDEN MITENTFERNT. Der Prompt verweist an mehreren
    Stellen auf Punkte ("reine Office-Dateien siehe Punkt 16"). Bleibt so ein
    Verweis stehen, waehrend sein Ziel fehlt, schickt er das Modell zu einer
    Regel, die es nicht gibt - dieselbe Fehlerklasse wie eine Anleitung, die ein
    Bedienelement bei einem Namen nennt, den es nicht mehr gibt.
    """
    if erlaubt is None or not isinstance(prompt, str) or not prompt:
        return prompt, []
    behalten, entfernt = [], []
    for nummer, text in _bloecke(prompt):
        genannt = set(_WERKZEUG_IM_TEXT.findall(text))
        kennzeichnend = genannt - set(KERN)
        if nummer and kennzeichnend and not (kennzeichnend & erlaubt):
            entfernt.append(nummer)
            continue
        behalten.append((nummer, text))
    if not entfernt:
        return prompt, []
    text = "".join(f"{n}. {t}" if n and not t.startswith(f"{n}.") else t
                   for n, t in behalten)
    return _verweise_entschaerfen(text, entfernt), entfernt


def _verweise_entschaerfen(text: str, entfernt: list[str]) -> str:
    """Saetze und Klammern streichen, die auf einen entfernten Punkt zeigen.

    Bewusst chirurgisch: erst der Klammerausdruck (so steht der bekannte
    Verweis in Punkt 17), dann - falls noetig - der ganze Satz. Was nach dem
    Streichen keinen Verweis mehr traegt, bleibt unangetastet.
    """
    if not entfernt:
        return text
    nummern = "|".join(_re.escape(n) for n in entfernt)
    # 1. Klammerausdruck mit Verweis
    text = _re.sub(rf"\s*\([^()]*Punkt\s+(?:{nummern})\b[^()]*\)", "", text)
    # 2. Ganzer Satz mit Verweis (nur, wenn danach noch etwas steht)
    def _satz_weg(m):
        return "" if len(m.group(0)) < 400 else m.group(0)
    text = _re.sub(rf"[^.\n]*\bPunkt\s+(?:{nummern})\b[^.\n]*\.\s*", _satz_weg, text)
    return text


def offene_verweise(text: str, entfernt: list[str]) -> list[str]:
    """Welche Verweise auf entfernte Punkte stehen noch im Text? (Waechter)"""
    if not entfernt:
        return []
    nummern = "|".join(_re.escape(n) for n in entfernt)
    return _re.findall(rf"Punkt\s+(?:{nummern})\b", text)

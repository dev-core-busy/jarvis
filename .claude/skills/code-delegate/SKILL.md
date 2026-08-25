---
name: code-delegate
description: >-
  Gibt eine eng umrissene Codeaufgabe an den Jarvis-Agenten ab und holt sie als
  geprueften Patch zurueck – spart Anthropic-Tokens bei mechanischer
  Breitenarbeit. Nutzen, wenn eine Aenderung VIEL Datei-Lesen und WENIG
  Beschreibung braucht und eine vorhandene Testdatei das Ergebnis beweist.
---

# Codearbeit an Jarvis abgeben

Jarvis rechnet auf kostenlosen Tokens. Diese Faehigkeit verschiebt **Lesen und
Suchen** dorthin – nicht das Denken.

## Die Entscheidungsregel

**Delegiere nur, wenn die Beschreibung kurz und die Dateiarbeit breit ist.**

Musst du den Code erst lesen, um eine brauchbare Spezifikation zu schreiben,
hast du die Ersparnis schon ausgegeben. Dann mach es selbst.

### Geeignet

| Klasse | Beispiel |
|---|---|
| Mechanische Breitenarbeit | „`-localhost` an alle x11vnc-Aufrufe" (16 Stellen), „Cache-Buster an 40 Skript-Tags" |
| Eine kleine Aenderung mit vorhandenem Waechter | „Variable ergaenzen, `tests/test_branding_aliase.py` muss gruen bleiben" |
| Zwei Stellen, die zusammenpassen muessen | Deklaration in `:root` UND `body`, Feld in `create_*` UND der Whitelist von `update_*` |

### NICHT geeignet – hier selbst arbeiten

- **Alles Konventionslastige.** CLAUDE.md hat ~167.000 Token. Ein 35B-Modell
  wendet die Regeln darin nicht zuverlaessig an.
- **Alles Sicherheitsrelevante** (Gates, Sandbox, Rechte, Auth).
- **Zustandswechsel.** „Aendere X, miss, mach rueckgaengig" ist reproduzierbar
  gescheitert (17 Schritte, kein Ergebnis). **Eine Delegation = ein
  Zielzustand.** Den Rueckbau macht der Server per `git checkout`.
- **Alles ohne mechanischen Riegel.** Kein Test, der es beweist → nicht
  delegieren. Die Modellantwort allein ist kein Nachweis.

## Vorbedingung – kostet sonst einen ganzen Lauf

**Der Riegel muss in `origin/master` liegen.** Der Server klont von dort; ein
frisch geschriebener, noch nicht gepushter Waechter existiert im Arbeitsbereich
gar nicht. Der Lauf startet trotzdem, der Agent arbeitet, und erst die Bewertung
meldet „Riegel existiert im Arbeitsbereich nicht" – kein Patch, und nach der
Abbruchregel machst du die Aufgabe danach selbst. Genauso: ein committeter, aber
lokal **geaenderter** Riegel – geprueft wuerde die alte Fassung, ein gruener
Riegel bewiese dann etwas anderes als das, was du geschrieben hast.

`senden` faengt beides seit 2026-08-25 **vor** dem Lauf ab. Reihenfolge also:
**Waechter schreiben -> committen und pushen -> delegieren.**

## Ablauf

```bash
S=deploy/claude_subagent/delegiere.py   # im Repo versioniert, nicht in .claude/

# 1. Auftrag schreiben (Datei, damit Anfuehrungszeichen nicht stoeren)
cat > /tmp/auftrag.txt <<'EOF'
In frontend/css/chat.css im :root-Block die Variable ergaenzen:
    --accent-soft: color-mix(in srgb, var(--accent) 20%, transparent);
EOF

# 2. Abgeben -> gibt die Auftragskennung aus
ID=$(python3 $S senden --spec-datei /tmp/auftrag.txt \
        --dateien frontend/css/chat.css \
        --riegel tests/test_branding_aliase.py)

# 3. Warten; bei Erfolg kommt der Patch auf stdout, der Bericht auf stderr
python3 $S warten "$ID" > /tmp/patch.diff
```

## Die Abbruchregel – ausnahmslos

Der Server prueft **alles-oder-nichts** und liefert nur dann einen Patch:
Patch nicht leer · nur die freigegebenen Dateien angefasst · Riegel gruen ·
Patch nicht gekuerzt.

Kommt **kein** Patch (Exitcode ≠ 0), dann **mach die Aufgabe selbst**. Nicht
nachbessern lassen, nicht ein zweites Mal delegieren, nicht „fast richtig"
uebernehmen. Ein zweiter Versuch kostet mehr als die Ersparnis.

Kommt ein Patch, **lies ihn**, bevor du ihn anwendest:

```bash
git apply --check /tmp/patch.diff && git apply /tmp/patch.diff
```

Ein gruener Riegel beweist, dass die Aenderung *funktioniert* – nicht, dass sie
zu den Projektkonventionen passt (Einrueckung, Spaltenausrichtung, Kommentare).
Das ist deine Aufgabe und der Grund, warum der Patch klein sein muss.

## Was es gebracht hat

```bash
python3 $S bericht
```

Zeigt je Auftrag die GEMESSENEN Zeichen (Auftragstext, Quelldateien,
Patch) und die Bilanz. Die Rechnung:

    ohne Delegation ~ Quelldateien lesen + Patch schreiben
    mit  Delegation ~ Auftrag schreiben  + Patch lesen
    Ersparnis       ~ Quelle - Auftrag

Der Patch faellt heraus – er geht in beiden Faellen durch Claude. Ein
**abgelehnter** Auftrag zaehlt mit negativem Beitrag: die Spezifikation wurde
geschrieben und die Aufgabe danach trotzdem selbst gemacht.

**Der Vorbehalt steht im Bericht und ist der Kern der Entscheidungsregel:** die
Ersparnis gilt nur, soweit die Dateien vorher NICHT gelesen wurden. Wer erst
lesen muss, um den Auftrag zu schreiben, hat sie schon ausgegeben.

## Was der Auftragstext enthalten muss

Der Agent kennt die Projektregeln **nicht**. Schreibe deshalb:

- **Was genau** wo hinein soll – woertlich, wenn es ein fester Text ist.
- **Keine** Begruendung, keine Historie, kein „wie ueblich".
- **Kein** „raeum dabei auf", „formatiere mit", „pruefe auch noch".

Zahlen aus der Antwort des Agenten sind **wertlos** – er zaehlt nachweislich
falsch (drei von drei Probelaeufen). Verlass dich auf Patch und Riegel; beides
rechnet der Server selbst.

## Voraussetzungen

Diese Datei ist bereits auf DIESE Installation ausgestellt – die beiden Befehle
unten sind vollstaendig, es fehlt nur der Schluessel:

```bash
printf '%s' 'HIER-DEINEN-SCHLUESSEL-EINSETZEN' > ~/.jarvis-csa-key
printf '%s' 'https://191.100.144.1' > ~/.jarvis-csa-url
chmod 600 ~/.jarvis-csa-key
```

- **Schluessel** in `JARVIS_CSA_KEY` oder `~/.jarvis-csa-key` – in Jarvis
  unter `https://191.100.144.1/claude` erzeugen. **Nie ins Repo.**
- **Adresse** ist oben schon eingesetzt: `https://191.100.144.1`. (Ueber `JARVIS_CSA_URL`
  bzw. die Datei laesst sich der Client auch gegen eine andere Installation
  richten – eine feste Vorgabe im Code gibt es bewusst nicht.)
- Der lokale Stand muss auf `origin/master` liegen und die Zieldateien duerfen
  keine ungespeicherten Aenderungen haben – der Client prueft beides und bricht
  sonst ab.

Laeuft gegen **jede** Jarvis-Installation, auch produktive. Der Riegel ist dort
verfuegbar, weil der Arbeitsbereich frisch von `origin/master` geklont wird –
ein `sparse-checkout` auf dem Server (der `tests/` in `/opt/jarvis` ausblendet)
wirkt nur auf dessen eigene Arbeitskopie, nicht auf einen neuen Klon.

## Beiblatt: CLAUDE.md schlank halten

Die Ausschlussregel „nichts Konventionslastiges" oben haengt an der Groesse von
CLAUDE.md – je dicker die Datei, desto weniger laesst sich abgeben. Ein
paste-fertiger Auftrag zum Verschlanken steht in **`claude-md-diaet.md`**
(Download im Bereich `https://191.100.144.1/claude`, Abschnitt „Anleitung"). Er ist
eigenstaendig – kein Jarvis, keine Delegation – und wird ausdruecklich **nicht**
delegiert: CLAUDE.md ist die Konvention selbst.

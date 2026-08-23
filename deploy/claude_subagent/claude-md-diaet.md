# CLAUDE.md auf Token-Diaet

Beiblatt zum Delegations-Skill, **aber eigenstaendig**: dieser Auftrag braucht
weder {marke} noch eine Delegation. Er laeuft in einer normalen
Claude-Code-Sitzung in deinem Projekt.

**Warum es sich lohnt:** CLAUDE.md geht in **jede** Anfrage **jeder** Sitzung.
Eine Diaet zahlt sich dauerhaft aus, waehrend eine einzelne delegierte Aenderung
einmal spart. Und sie erweitert den Zuschnitt der Delegation: die Ausschlussregel
„nichts Konventionslastiges" haengt genau an der Groesse dieser Datei.

**⚠ NICHT delegieren.** CLAUDE.md IST die Konvention. Ein kleines Modell soll
nicht die Datei umschreiben, deren Regeln es selbst nicht zuverlaessig anwendet –
und es gibt keinen mechanischen Riegel, der „richtig gekuerzt" beweisen koennte.

---

## Der Auftragstext (paste-fertig)

Zwei Stellen anpassen: `<BUDGET>` (Zielmarke, siehe unten) und `<X>`/`<Y>` im
letzten Absatz – dort zwei Themen einsetzen, die in **deiner** Datei wirklich
stehen. Diese Stichprobe ist der einzige Beweis, dass nicht zu tief geschnitten
wurde.

> **Auftrag: CLAUDE.md auf Token-Diaet. Drei Phasen, nichts ohne meine Freigabe.**
>
> **Phase 0 – messen, nicht schaetzen.** Bevor du eine Zeile aenderst:
> ```bash
> python3 -c "z=open('CLAUDE.md',encoding='utf-8').read(); print(len(z),'Zeichen ~',round(len(z)/3.6),'Token')"
> ```
> Dazu die Groesse je `##`-Abschnitt, absteigend, als Tabelle. Und sag mir, was
> ueberhaupt pro Anfrage zahlt: CLAUDE.md, der `MEMORY.md`-Index und die
> Skill-**Beschreibungen**. `.claude/settings*.json` (Berechtigungen, Hooks)
> landet **nicht** im Modellkontext – dort ist nichts zu holen; nenne das, statt
> daran zu kuerzen. Noch keine Aenderung.
>
> **Phase 1 – Plan vorlegen, nicht umsetzen.** Je Abschnitt eine Zeile:
> heutige Groesse → Zielgroesse → was rausfliegt (Kategorie, kein Zitat). Dazu:
> welche Lehren mehrfach dastehen und wohin sie **einmal zentral** wandern.
> Zielmarke fuer die ganze Datei: **≤ <BUDGET> Token**. Dann warte auf mein OK.
>
> **Phase 2 – umsetzen, abschnittsweise.** Groesster Abschnitt zuerst, einer pro
> Schritt. Nach jedem: neue Gesamtgroesse und in einem Satz, was gestrichen
> wurde. Kein Ein-Schuss-Umschreiben der ganzen Datei – ich pruefe den
> `git diff`, nicht die neue Fassung.
>
> **Der Behalte-Test entscheidet, nicht der Klang.** Fuer jeden Satz gilt:
> *Wuerde ein Modell ohne diesen Satz denselben Fehler wieder machen?*
> Ja → bleibt, gekuerzt auf **eine** Zeile, aber mit der Folge („X tun → Y
> bricht"). Nein → weg.
> Der Test „klingt allgemein" ist **verboten**: Saetze wie „nie `.index()` in
> einer Pruefung" oder „eine Anzeige darf keinen Zustand behaupten" lesen sich
> wie Best Practice und sind in Wahrheit bezahlte Vorfaelle.
>
> **Niemals streichen:** Messwerte und Grenzen (ohne den Server nicht
> reproduzierbar) · ausdrueckliche Entscheidungen des Nutzers **samt verworfener
> Alternativen** (sonst kommt der abgelehnte Vorschlag zurueck) · Ausrollstaende
> („noch nicht ausgerollt" = offene Handlung) · exakte Befehle, Pfade, Datei- und
> Feldnamen, Endpunkte · Sicherheits- und Rechte-Invarianten mit Begruendung.
>
> **Streichbar:** Baugeschichte fertiger Features (der Weg der Anlaeufe, nicht
> das Ergebnis) · Verifikations-Absaetze („N Pruefungen, Gegenprobe greift,
> md5-gleich") → auf den Testdateinamen eindampfen · mehrfach wiederholte Lehren
> → einmal zentral plus Verweis · allgemeines Programmier-, Git- und
> Sprachwissen, das ein Modell ohnehin hat.
>
> **Form:** Stichpunkte, ein Gedanke pro Zeile, Regel und Folge in derselben
> Zeile. **Ueberschriften bleiben unveraendert** – Memories und Code-Kommentare
> verweisen darauf. Lege **kein Archiv** an: der alte Text steht in der
> Git-Historie.
>
> **Abschluss:** `git diff --stat CLAUDE.md`, die **gemessene** Ersparnis in
> Zeichen und Token, und beantworte drei Stichproben ausschliesslich aus der
> gekuerzten Datei: Wie wird deployt? Wie heisst der Testlauf fuer `<X>`? Was ist
> die Falle bei `<Y>`? Findet die neue Fassung darauf keine Antwort, war der
> Schnitt zu tief – dann sag es, statt es zu kaschieren.

---

## Warum nicht die kurze Fassung

Die verbreitete Kurzfassung lautet: „loesche alles, was ein modernes LLM ohnehin
weiss, schreib den Rest als Stichpunkte, zeig mir den Entwurf und schaetze die
Ersparnis." Fuenf Punkte daran kosten mehr, als sie sparen.

1. **Sofort-Umschreiben statt Phasen.** Ein Entwurf ueber die ganze Datei ist bei
   sechsstelliger Token-Zahl nicht pruefbar, und ein still gestrichener Satz
   faellt erst auf, wenn der Fehler wiederkommt. Pruefstueck ist der `diff` – die
   neue Fassung liest sich immer gut.
2. **„Das weiss ein LLM ohnehin" ist der gefaehrlichste Filter.** Er trifft genau
   die Saetze, die aus Vorfaellen stammen:

   | Sieht aus wie Standard | Ist in Wahrheit |
   |---|---|
   | „nie `.index()` in einer Pruefung" | ein Waechter, der abbrach statt fehlzuschlagen – und dadurch als bestanden galt |
   | „eine Anzeige darf keinen Zustand behaupten" | drei Anzeigen, die einen Zustand behaupteten, den sie nicht kannten – je Fall Stunden Fehlersuche |
   | „Kommentare vor dem Vergleich entfernen" | Waechter, die ihre eigene Begruendung lasen und deshalb nichts prueften |
   | „`asyncio.wait_for` bricht nicht ab" | 20-Sekunden-Freeze fuer ALLE Benutzer, live nachgemessen |

   Deshalb der Behalte-Test: nicht „klingt allgemein", sondern „passiert es ohne
   den Satz wieder".
3. **„Radikal" ist keine Vorgabe.** Eine Zahl ist eine.
4. **„Geschaetzte" Ersparnis** – bei einer Datei, deren Groesse ein Einzeiler
   ausrechnet. Messen, vorher und nachher.
5. **Falscher Scope.** `.claude/settings*.json` kostet **kein** Token pro
   Anfrage; die Skill-*Beschreibungen* und der `MEMORY.md`-Index dagegen schon.
   Ein Schnitt an den Berechtigungen spart nichts und erzeugt Zugriffsfehler.

Nicht Teil des Auftrags, aber fuer die Sitzung: die Diaet **nicht** mit
Feature-Arbeit mischen (die Datei ist die Grundlage genau dieser Arbeit), und
danach die Memory-Dateien gegen die gekuerzte Fassung pruefen – Verweise auf
gestrichene Abschnitte zeigen sonst ins Leere.

---

## Zielmarke und eigene Fettstellen finden

`<BUDGET>` herleiten statt raten: **Zahl der `##`-Abschnitte × ~3.000 Zeichen**,
das Ergebnis durch 3,6 (Deutsch) bzw. 4 (Englisch). Drei Befehle, die die
Kandidaten zeigen:

```bash
# 1. Die groessten Abschnitte - dort liegt fast immer die Haelfte
python3 - <<'EOF'
import re
z=open("CLAUDE.md",encoding="utf-8").read()
t=re.split(r"(?m)^(## .*)$", z)
p=sorted(((t[i].strip(),len(t[i+1])) for i in range(1,len(t),2)), key=lambda x:-x[1])
print(len(z),"Zeichen ~",round(len(z)/3.6),"Token |",len(p),"Abschnitte")
for name,n in p[:10]: print(f"{n:7d}  {name[:70]}")
EOF

# 2. Verifikations-Absaetze: oft ein Zehntel der Datei, Archiv nach dem Rollout
grep -cE "^[-*] \*\*(Verifiziert|Live)" CLAUDE.md

# 3. Mehrfach erzaehlte Lehren: einmal zentral, danach Verweis
grep -oE "Merkregel|FALLSTRICK" CLAUDE.md | sort | uniq -c
```

Erfahrungswert aus einem gewachsenen Projekt: die drei groessten Abschnitte
machten 22 % aus, die Verifikations-Absaetze 11 %, und einzelne Lehren standen
fuenfmal wortgleich in verschiedenen Abschnitten.

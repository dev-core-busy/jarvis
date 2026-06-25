# Support-Assistent API

Programmatischer Zugriff auf die Support-Suche von Jarvis. Liefert exakt die
Ergebnisse, die auch unter `/support` angezeigt werden (inkl. Quelle), als JSON –
fallbezogen aus **RAG (Wissensdatenbank)**, **Jira** und/oder **Confluence**.

## Endpoint

```
POST https://<jarvis-host>/api/support/query
Content-Type: application/json
```

Voraussetzung: Der Skill **„Support Assistent"** ist installiert und aktiv
(sonst `403`). Jira-/Confluence-Quellen liefern nur Treffer, wenn der jeweilige
Skill aktiv und konfiguriert ist.

## Authentifizierung

Eine der folgenden Varianten:

| Variante | Header |
|----------|--------|
| **Externer API-Key** (empfohlen für Fremdanwendungen) | `X-API-Key: <AGENT_API_KEY>` |
| API-Key als Bearer | `Authorization: Bearer <AGENT_API_KEY>` |
| Benutzer-Token (interaktiv) | `Authorization: Bearer <Login-Token>` |

`AGENT_API_KEY` wird serverseitig gesetzt (Umgebungsvariable `AGENT_API_KEY`
oder `agent_api_key` in `settings.json`). Ohne gültige Auth: `401`.

## Request-Body

| Feld | Typ | Default | Beschreibung |
|------|-----|---------|--------------|
| `text` | string | – | **Pflicht.** Anfrage/Kontext (mehrzeilig erlaubt). Alias: `query`. |
| `rag` | bool | `true` | Wissensdatenbank (RAG) durchsuchen. |
| `jira` | bool | `true` | Jira-Tickets durchsuchen (nur wenn Jira-Skill aktiv). |
| `confluence` | bool | `true` | Confluence-Seiten durchsuchen (nur wenn Confluence-Skill aktiv). |
| `ai` | bool | `true` | LLM-Kurzzusammenfassung erzeugen (`false` = schneller, kein LLM-Aufruf). |

Pro Anfrage frei kombinierbar – z. B. nur Jira (`{"rag":false,"confluence":false}`).
Die im Skill konfigurierte Confluence-White-/Blacklist wird automatisch angewandt.

## Response (200)

```jsonc
{
  "ok": true,
  "query": "KIM eArztbrief Versand",
  "jira_active": true,
  "confluence_active": true,
  "result_lines": 2,            // empfohlene Zeilen-Begrenzung der Kurzfassung
  "took_ms": 1840,
  "ai_summary": "…",            // leer wenn ai=false oder kein Treffer
  "blocks": [
    {
      "source": "WISSEN",        // "WISSEN" | "JIRA" | "CONFLUENCE"
      "title": "Versandprozess",
      "summary": "Wie werden KIM eArztbriefe versendet? …",
      "score": 90,               // Relevanz „Zutreffend in %" (0–100)
      "link": "https://…",       // direkter Quell-Link (kann leer sein)
      "source_label": "Versandprozess",
      "doc": "data/knowledge/…", // nur WISSEN: Pfad des Quelldokuments
      "doc_name": "faq.json"     // nur WISSEN: Dateiname
    }
  ]
}
```

Die Liste `blocks` ist bereits absteigend nach `score` sortiert (alle Quellen
gemischt). Felder `doc`/`doc_name` erscheinen nur bei `source = "WISSEN"`.

### Fehlerantworten

| Status | Body | Ursache |
|--------|------|---------|
| `400` | `{"ok":false,"error":"Bitte eine Anfrage eingeben."}` | `text` fehlt/leer |
| `401` | `{"ok":false,"error":"Nicht authentifiziert"}` | Auth fehlt/ungültig |
| `403` | `{"ok":false,"error":"Support-Assistent ist nicht aktiv."}` | Skill inaktiv |

## Beispiel – curl

```bash
curl -sk -X POST "https://jarvis.example.com/api/support/query" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "text": "Wie werden KIM eArztbriefe versendet?",
        "rag": true,
        "jira": true,
        "confluence": true,
        "ai": true
      }'
```

## Beispiel – Python

```python
import requests

JARVIS = "https://jarvis.example.com"
API_KEY = "…"   # AGENT_API_KEY

def support_query(text, rag=True, jira=True, confluence=True, ai=True):
    r = requests.post(
        f"{JARVIS}/api/support/query",
        headers={"X-API-Key": API_KEY},
        json={"text": text, "rag": rag, "jira": jira,
              "confluence": confluence, "ai": ai},
        timeout=60,
        verify=False,   # self-signed Zertifikat; in Produktion CA hinterlegen
    )
    r.raise_for_status()
    return r.json()

res = support_query("KIM eArztbrief Versand", jira=False)  # nur RAG + Confluence
print("Zusammenfassung:", res.get("ai_summary"))
for b in res["blocks"]:
    print(f"[{b['source']}] {b['score']}% {b['title']} -> {b.get('link') or b.get('doc_name')}")
```

## Hinweise

- **Antwortzeit:** Mit `ai=true` ist ein LLM-Aufruf enthalten (typisch einige
  Sekunden). Für reine Trefferlisten `ai=false` setzen.
- **Trefferzahl:** intern bis zu 8 RAG-, 10 Jira- und 6 Confluence-Treffer.
- **Score:** RAG = semantische Ähnlichkeit; Jira/Confluence = rangbasiert +
  Wort-Überlappung; Bereich ca. 20–96 %.
- **TLS:** Jarvis nutzt ein selbstsigniertes Zertifikat – in Fremdanwendungen
  entweder das CA-Zertifikat hinterlegen oder (nur intern) die Prüfung abschalten.

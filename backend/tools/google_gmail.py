"""
Gmail Tool für Jarvis.

Tool-Name: google_gmail
Aktionen:
  read_inbox   – Letzte N E-Mails aus dem Posteingang
  read_mail    – Eine E-Mail vollständig lesen (per ID)
  search_mail  – E-Mails suchen (Gmail-Query)
  send_mail    – E-Mail senden
  reply_mail   – E-Mail beantworten
  list_labels  – Alle Labels anzeigen
"""

import base64
import email as _email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from backend.tools.base import BaseTool


def _get_service():
    from backend.tools.google_auth import get_service
    return get_service("gmail", "v1")


def _decode_body(payload) -> str:
    """Extrahiert den Textinhalt aus dem Gmail-Payload."""
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    break
            elif part["mimeType"] == "text/html" and not body:
                data = part["body"].get("data", "")
                if data:
                    body = "[HTML] " + base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")[:500]
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return body.strip()


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


class GoogleGmailTool(BaseTool):
    name = "google_gmail"
    description = (
        "Liest und sendet E-Mails über Gmail. "
        "Aktionen: read_inbox, read_mail, search_mail, send_mail, reply_mail, list_labels."
    )

    def execute(self, action: str, **kwargs) -> str:
        try:
            svc = _get_service()
        except RuntimeError as e:
            return f"❌ Nicht authentifiziert: {e}"
        except Exception as e:
            return f"❌ Fehler beim Verbinden: {e}"

        try:
            if action == "read_inbox":
                return self._read_inbox(svc, kwargs.get("max_results", 10))
            elif action == "read_mail":
                return self._read_mail(svc, kwargs.get("message_id", ""))
            elif action == "search_mail":
                return self._search_mail(svc, kwargs.get("query", ""), kwargs.get("max_results", 10))
            elif action == "send_mail":
                return self._send_mail(svc, kwargs.get("to", ""), kwargs.get("subject", ""), kwargs.get("body", ""))
            elif action == "reply_mail":
                return self._reply_mail(svc, kwargs.get("message_id", ""), kwargs.get("body", ""))
            elif action == "list_labels":
                return self._list_labels(svc)
            else:
                return f"❌ Unbekannte Aktion: {action}. Verfügbar: read_inbox, read_mail, search_mail, send_mail, reply_mail, list_labels"
        except Exception as e:
            return f"❌ Gmail-Fehler: {e}"

    def _read_inbox(self, svc, max_results: int) -> str:
        result = svc.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return "📭 Posteingang ist leer."
        lines = [f"📬 Posteingang ({len(messages)} E-Mails):"]
        for msg in messages:
            detail = svc.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()
            hdrs = detail.get("payload", {}).get("headers", [])
            lines.append(
                f"  ID: {msg['id']}\n"
                f"  Von: {_header(hdrs, 'From')}\n"
                f"  Betreff: {_header(hdrs, 'Subject')}\n"
                f"  Datum: {_header(hdrs, 'Date')}\n"
            )
        return "\n".join(lines)

    def _read_mail(self, svc, message_id: str) -> str:
        if not message_id:
            return "❌ Bitte message_id angeben."
        msg = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
        hdrs = msg.get("payload", {}).get("headers", [])
        body = _decode_body(msg.get("payload", {}))
        return (
            f"📧 E-Mail ID: {message_id}\n"
            f"Von:      {_header(hdrs, 'From')}\n"
            f"An:       {_header(hdrs, 'To')}\n"
            f"Betreff:  {_header(hdrs, 'Subject')}\n"
            f"Datum:    {_header(hdrs, 'Date')}\n"
            f"─────────────────────────\n"
            f"{body[:3000]}"
        )

    def _search_mail(self, svc, query: str, max_results: int) -> str:
        if not query:
            return "❌ Bitte query angeben (z.B. 'from:chef@firma.de subject:Rechnung')."
        result = svc.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return f"🔍 Keine E-Mails gefunden für: {query}"
        lines = [f"🔍 {len(messages)} Ergebnis(se) für '{query}':"]
        for msg in messages:
            detail = svc.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()
            hdrs = detail.get("payload", {}).get("headers", [])
            lines.append(
                f"  ID: {msg['id']}\n"
                f"  Von: {_header(hdrs, 'From')}\n"
                f"  Betreff: {_header(hdrs, 'Subject')}\n"
            )
        return "\n".join(lines)

    def _send_mail(self, svc, to: str, subject: str, body: str) -> str:
        if not to or not subject or not body:
            return "❌ Bitte to, subject und body angeben."
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"]      = to
        msg["Subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"✅ E-Mail an {to} gesendet (Betreff: {subject})"

    def _reply_mail(self, svc, message_id: str, body: str) -> str:
        if not message_id or not body:
            return "❌ Bitte message_id und body angeben."
        orig = svc.users().messages().get(userId="me", id=message_id, format="metadata",
            metadataHeaders=["Subject", "From", "To", "Message-ID", "References"]
        ).execute()
        hdrs = orig.get("payload", {}).get("headers", [])
        to      = _header(hdrs, "From")
        subject = "Re: " + _header(hdrs, "Subject").removeprefix("Re: ")
        msg_id  = _header(hdrs, "Message-ID")
        refs    = _header(hdrs, "References")

        reply = MIMEText(body, "plain", "utf-8")
        reply["To"]         = to
        reply["Subject"]    = subject
        reply["In-Reply-To"] = msg_id
        reply["References"] = f"{refs} {msg_id}".strip()
        raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()

        thread_id = orig.get("threadId")
        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id
        svc.users().messages().send(userId="me", body=send_body).execute()
        return f"✅ Antwort an {to} gesendet."

    def _list_labels(self, svc) -> str:
        result = svc.users().labels().list(userId="me").execute()
        labels = result.get("labels", [])
        lines = ["📁 Gmail-Labels:"]
        for lbl in labels:
            lines.append(f"  {lbl['name']} (ID: {lbl['id']})")
        return "\n".join(lines)

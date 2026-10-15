"""Selbstbereinigende Telemetrie-Logs – eine Frist, ein Zeitplan, drei Speicher.

WARUM ES DAS GIBT
-----------------
Vor diesem Modul wuchsen die Telemetrie-Speicher nur gegen *Stueckzahlen*, nie
gegen *Alter*:

* ``conv_log`` behielt die letzten 200 Konversationen – auf DEV waren das
  37,9 Tage, auf einem stillen System Jahre, auf einem lauten drei Tage.
  Wie weit der Verlauf zurueckreicht, war damit reine Zufallsgroesse.
* ``telemetry_errors.json`` behielt 200 Fehler – ein Server ohne Fehler trug
  ewig die Fehler von vorletztem Jahr mit sich.
* ``audit.jsonl`` rotierte erst bei 10 MB und legte die alte Datei als ``.bak``
  daneben. Danach war der Inhalt fuer die Oberflaeche unsichtbar, lag aber
  weiter auf Platte – Loeschen war *nie* vorgesehen.

Eine Frist in TAGEN ist die einzige Groesse, die man einem Betreiber gegenueber
zusagen kann ("Diagnosedaten werden nach 90 Tagen entfernt"). Stueckzahlen
bleiben als ZWEITE Schranke bestehen: sie begrenzen die Datei, wenn an einem
Tag ungewoehnlich viel anfaellt, und schuetzen so vor dem Fall, in dem die
Zeitfrist allein noch nichts entfernen wuerde.

VORGABE: 90 Tage, umstellbar ueber ``JARVIS_LOG_RETENTION_DAYS``.
``0`` schaltet die Bereinigung ab (dauerhaft aufbewahren) – bewusst moeglich,
weil ein Audit-Log in manchen Haeusern laenger vorgehalten werden muss.

FALLSTRICK: ``retention_days()`` ist eine FUNKTION, keine Modulkonstante.
Ein beim Import gelesener Wert waere bis zum naechsten Dienststart eingefroren
(gleiche Begruendung wie bei ``documents.retention_days()``).
"""

import os
import time

DEFAULT_RETENTION_DAYS = 90
_ENV_VAR = "JARVIS_LOG_RETENTION_DAYS"

# Nachweis des letzten Laufs – die Oberflaeche zeigt ihn im Telemetrie-Reiter.
# Nur im Speicher: ein Neustart setzt die Bereinigung ohnehin sofort erneut an.
_last_run: dict = {"ts": None, "removed": {}, "error": None}


def retention_days() -> int:
    """Aufbewahrungsfrist in Tagen (0 = dauerhaft aufbewahren).

    Seit BSI M9 (2026-10-12) aus ``loeschfristen.tage("protokoll")``: zuerst
    die Einstellung der Oberflaeche, dann ``JARVIS_LOG_RETENTION_DAYS``, dann
    90 – mit denselben Regeln wie zuvor (0 = dauerhaft, Deckel 3650)."""
    from backend import loeschfristen
    return loeschfristen.tage("protokoll")


# Zusaetzliche Laeufe, die Zustand im Speicher eines anderen Moduls bereinigen
# (Direktnachrichten in main.py). Werden mit dem Schnitt der Chat-Frist gerufen.
ZUSATZ_CHATS: list = []


def cutoff_ts() -> float | None:
    """Zeitstempel, VOR dem geloescht wird – oder None bei "dauerhaft"."""
    days = retention_days()
    if days <= 0:
        return None
    return time.time() - days * 86400


def run_all() -> dict:
    """Bereinigt alle Telemetrie-Speicher und liefert die Anzahl je Speicher.

    Fehlerrobust je Speicher: schlaegt einer fehl, laufen die anderen weiter.
    Ein Aufraeumlauf, der beim ersten Problem abbricht, laesst genau die
    Datei stehen, die am dringendsten aufgeraeumt werden muss.
    """
    cut = cutoff_ts()
    removed: dict[str, int] = {}
    errors: list[str] = []

    # Sicherheitsprotokoll (BSI M2): EIGENE Frist (Vorgabe 365 Tage), laeuft
    # deshalb auch, wenn die Telemetrie dauerhaft aufbewahrt wird.
    try:
        from backend import sicherheits_log
        _tage = sicherheits_log.aufbewahrung_tage()
        if _tage:
            removed["sicherheits_log"] = int(
                sicherheits_log.prune_older_than(time.time() - _tage * 86400) or 0)
    except Exception as e:  # noqa: BLE001
        errors.append(f"sicherheits_log: {e}")
        print(f"[Retention] sicherheits_log fehlgeschlagen: {e}", flush=True)

    # Loeschkonzept (BSI M9): Chats und volle Prompts haben EIGENE Fristen und
    # laufen deshalb auch, wenn die Protokolle dauerhaft aufbewahrt werden.
    try:
        from backend import loeschfristen
        erg = loeschfristen.chats_bereinigen()
        if not erg.get("dauerhaft"):
            removed["chat_sitzungen"] = int(erg.get("sitzungen") or 0)
            removed["chat_verlauf"] = int(erg.get("verlauf_nachrichten") or 0)
            _cut_chats = loeschfristen.schnitt("chats")
            n_dm = 0
            for fn in list(ZUSATZ_CHATS):
                n_dm += int(fn(_cut_chats) or 0)
            removed["direktnachrichten"] = n_dm
        _cut_prompts = loeschfristen.schnitt("prompts")
        if _cut_prompts is not None:
            from backend import conv_log
            removed["volle_prompts"] = int(conv_log.prompts_entfernen(_cut_prompts) or 0)
    except Exception as e:  # noqa: BLE001
        errors.append(f"loeschfristen: {e}")
        print(f"[Retention] Loeschfristen fehlgeschlagen: {e}", flush=True)

    if cut is None:
        _last_run.update({"ts": time.time(), "removed": removed,
                          "error": "; ".join(errors) or None, "skipped": True})
        return {"ok": not errors, "skipped": True, "removed": removed}

    for name, fn in (("conv_log", _prune_conv_log),
                     ("telemetry_errors", _prune_telemetry_errors),
                     ("audit_log", _prune_audit_log),
                     ("email_log", _prune_email_log),
                     ("short_tracks_log", _prune_short_tracks_log),
                     ("cron_log", _prune_cron_log),
                     ("csp_berichte", _prune_csp_berichte)):
        try:
            removed[name] = int(fn(cut) or 0)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            print(f"[Retention] {name} fehlgeschlagen: {e}", flush=True)

    _last_run.update({
        "ts": time.time(),
        "removed": removed,
        "error": "; ".join(errors) or None,
        "skipped": False,
    })
    total = sum(removed.values())
    if total:
        print(f"[Retention] {total} Eintraege aelter als {retention_days()} Tage "
              f"entfernt ({removed})", flush=True)
    return {"ok": not errors, "removed": removed,
            "error": "; ".join(errors) or None}


def last_run() -> dict:
    """Nachweis des letzten Laufs fuer die Oberflaeche."""
    return {
        "days": retention_days(),
        "last_run_ts": _last_run.get("ts"),
        "removed": _last_run.get("removed") or {},
        "error": _last_run.get("error"),
    }


# ─── Adapter je Speicher (Import lokal: keine Ladereihenfolge-Abhaengigkeit) ──

def _prune_conv_log(cut: float) -> int:
    from backend import conv_log
    return conv_log.prune_older_than(cut)


def _prune_telemetry_errors(cut: float) -> int:
    from backend.telemetry import tracer
    return tracer.prune_errors_older_than(cut)


def _prune_audit_log(cut: float) -> int:
    from backend import audit_log
    return audit_log.prune_older_than(cut)


def _prune_email_log(cut: float) -> int:
    """Protokoll der E-Mail-Regeln (data/email_log.jsonl).

    Gehoert hierher und nicht in einen eigenen Zeitplan: es ist derselbe
    Diagnosespeicher-Typ wie die uebrigen drei, und es soll dieselbe Frist
    gelten. Auch hier gibt es AUSDRUECKLICH keine Stueckzahl- oder
    Groessengrenze – die Eintraege, die man nach einer falsch beantworteten
    Kundenmail braucht, sind genau die, die eine Mengengrenze verdraengt haette.
    """
    from backend import mail_rules
    return mail_rules.protokoll_kuerzen(cut)


def _prune_short_tracks_log(cut: float) -> int:
    """Protokoll der Short Tracks (data/short_tracks_log.jsonl).

    Gleiche Begruendung wie beim E-Mail-Protokoll: derselbe Diagnosespeicher-Typ,
    dieselbe Frist, und AUSDRUECKLICH keine Stueckzahl- oder Groessengrenze – wer
    nach einem missglueckten Lauf nachsehen will, braucht genau die Eintraege,
    die eine Mengengrenze verdraengt haette.
    """
    from backend import short_tracks
    return short_tracks.protokoll_kuerzen(cut)


def _prune_cron_log(cut: float) -> int:
    """Protokoll der zeitgesteuerten Auftraege (data/logs/cron/<id>.jsonl).

    Gleiche Begruendung wie bei E-Mail- und Short-Tracks-Protokoll: derselbe
    Diagnosespeicher-Typ, dieselbe Frist, AUSDRUECKLICH keine Stueckzahlgrenze.
    """
    from backend import cron_log
    return cron_log.kuerzen(cut)


def _prune_csp_berichte(cut: float) -> int:
    """CSP-Verstossmeldungen (data/logs/csp_berichte.jsonl, BSI H4) – derselbe
    Diagnosespeicher-Typ, dieselbe Frist, keine Stueckzahlgrenze."""
    from backend import csp
    return csp.kuerzen(cut)

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
    """Aufbewahrungsfrist in Tagen (0 = dauerhaft aufbewahren)."""
    raw = os.environ.get(_ENV_VAR)
    if raw is None or str(raw).strip() == "":
        return DEFAULT_RETENTION_DAYS
    try:
        days = int(float(str(raw).replace(",", ".").strip()))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS
    if days <= 0:
        return 0
    # Deckel, damit ein Tippfehler ("9000") nicht faktisch "dauerhaft" bedeutet,
    # ohne dass es jemand als solches erkennt.
    return min(days, 3650)


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

    if cut is None:
        _last_run.update({"ts": time.time(), "removed": {}, "error": None,
                          "skipped": True})
        return {"ok": True, "skipped": True, "removed": {}}

    for name, fn in (("conv_log", _prune_conv_log),
                     ("telemetry_errors", _prune_telemetry_errors),
                     ("audit_log", _prune_audit_log)):
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

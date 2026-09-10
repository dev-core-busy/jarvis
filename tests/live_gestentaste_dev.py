#!/usr/bin/env python3
"""Live auf DEV: die Entscheidung „Lasso oder Rechtsziehen" WIRKLICH ausgeführt.

Ein Quelltext-Grep beantwortet nicht, ob der Hook den Klick bei gehaltener
Taste durchreicht und – der teure Teil – ob dabei ``_pressWithheld`` richtig
steht: bleibt es fälschlich ``true``, verschluckt der spätere BUTTONUP den
Klick, und der Benutzer verliert ihn ganz.

Der Hook selbst haengt an ``SetWindowsHookEx`` und laeuft auf Linux nicht. Die
ENTSCHEIDUNG haengt aber an nichts davon – sie wird hier aus der ECHTEN Datei
in ein Konsolenprogramm gehoben und gegen die vier Tasten und beide
Klick-Arten laufen gelassen. Nachgebildet wird nur, was der Hook UMGIBT
(P/Invoke, InjectionGuard, InputReplay); die Verzweigung selbst ist Original.

Aufruf auf DEV: cd /opt/jarvis && python3 tests/live_gestentaste_dev.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/ai-mouse").is_dir() else \
    Path(__file__).resolve().parent.parent
DOTNET = Path("/opt/jarvis/vendor/dotnet/dotnet")
HOOK = ROOT / "ai-mouse" / "src" / "AiMouse" / "Input" / "MouseGestureHook.cs"
TASTE = ROOT / "ai-mouse" / "src" / "AiMouse" / "Input" / "GestenTaste.cs"

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


if not DOTNET.exists():
    print(f"ABBRUCH: kein dotnet unter {DOTNET}")
    sys.exit(2)

roh = HOOK.read_text(encoding="utf-8")

# ── Den ECHTEN HookProc + TasteGehalten herausschneiden ─────────────────────
def block(quelle, kopf):
    i = quelle.find(kopf)
    if i < 0:
        return ""
    auf = quelle.find("{", i)
    tief = 0
    for j in range(auf, len(quelle)):
        if quelle[j] == "{":
            tief += 1
        elif quelle[j] == "}":
            tief -= 1
            if tief == 0:
                return quelle[i:j + 1]
    return ""


PROC = block(roh, "private IntPtr HookProc")
TG = block(roh, "private static bool TasteGehalten")
if not PROC or not TG:
    print("ABBRUCH: HookProc/TasteGehalten nicht gefunden (umbenannt?).")
    sys.exit(2)
# ⚠ Positivkontrolle des Schnitts: ohne sie koennte er halben Code messen.
if "WM_RBUTTONDOWN" not in PROC or "TasteGehalten(Durchreichen)" not in PROC:
    print("ABBRUCH: der Schnitt enthaelt die zu messende Verzweigung nicht.")
    sys.exit(2)

ARB = Path(tempfile.mkdtemp(prefix="gtaste-", dir="/tmp"))
try:
    (ARB / "P.csproj").write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>
  <Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings></PropertyGroup>
</Project>""", encoding="utf-8")

    shutil.copy(TASTE, ARB / "GestenTaste.cs")

    # Die Umgebung des Hooks nachbilden – NICHT seine Entscheidung.
    # ⚠ ZWEI DATEIEN: C# erlaubt nur EINEN file-scoped Namespace je Datei.
    (ARB / "UmgebungInterop.cs").write_text("""
namespace AiMouse.Interop;

internal static class NativeMethods
{
    internal const int WM_MOUSEMOVE = 0x0200;
    internal const int WM_RBUTTONDOWN = 0x0204;
    internal const int WM_RBUTTONUP = 0x0205;
    internal const int VK_SHIFT = 0x10;
    internal const int VK_CONTROL = 0x11;
    internal const int VK_MENU = 0x12;

    /// <summary>Statt der echten Tastatur: der Test sagt, was gehalten wird.
    /// `NurNachwirkung` setzt das NIEDRIGE Bit (0x0001) – Windows meldet damit
    /// "war seit dem letzten Abruf einmal gedrueckt", NICHT "ist unten".</summary>
    internal static int Gehalten = 0;
    internal static bool NurNachwirkung;
    internal static short GetAsyncKeyState(int vKey)
        => vKey == Gehalten
            ? (NurNachwirkung ? (short)0x0001 : unchecked((short)0x8000))
            : (short)0;

    internal static IntPtr CallNextHookEx(IntPtr h, int c, IntPtr w, IntPtr l) => (IntPtr)0;

    internal struct POINT { public int x; public int y; }
    internal struct MSLLHOOKSTRUCT { public POINT pt; public IntPtr dwExtraInfo; }
}
""", encoding="utf-8")

    (ARB / "UmgebungInput.cs").write_text("""
namespace AiMouse.Input;

using AiMouse.Interop;

internal static class InputReplay
{
    internal static int Nachgespielt;
    public static bool IsOwnInput(in NativeMethods.MSLLHOOKSTRUCT d) => false;
    public static string? SendRightClick() { Nachgespielt++; return null; }
}

internal static class InjectionGuard
{
    internal static bool Blockt;
    public static bool BlocksInjection() => Blockt;
}
""", encoding="utf-8")

    # Der ECHTE Entscheidungsteil in einer schlanken Huelle.
    huelle = """
using System.Runtime.InteropServices;
using AiMouse.Interop;

namespace AiMouse.Input;

internal sealed class Hook
{
    private int _threshold = 8;
    private IntPtr _hookHandle;
    private bool _pressWithheld;
    private bool _isDragging;
    private Point _start;

    public GestenTaste Durchreichen { get; set; } = GestenTaste.Keine;
    public event Action<Point>? DragStarted;
    public event Action<Point>? DragMoved;
    public event Action<Rectangle>? DragCompleted;
    public event Action<string>? ReplayFailed;

    public bool PressWithheld => _pressWithheld;

    private void Post(Action a) => a();

__PROC__

__TG__

    // ⚠ NICHT geschnitten: `Normalise` ist expression-bodied (kein `{`), ein
    // Klammer-Schnitt landet im naechsten Rumpf und zieht fremden Code mit
    // (beim ersten Lauf genau so passiert). Sie ist reine Geometrie und nicht
    // Gegenstand dieser Messung.
    private static Rectangle Normalise(Point a, Point b) => Rectangle.FromLTRB(
        Math.Min(a.X, b.X), Math.Min(a.Y, b.Y),
        Math.Max(a.X, b.X), Math.Max(a.Y, b.Y));
}

internal readonly record struct Point(int X, int Y);
internal readonly record struct Rectangle(int L, int T, int R, int B)
{
    public static Rectangle FromLTRB(int l, int t, int r, int b) => new(l, t, r, b);
}

internal static class Programm
{
    private static NativeMethods.MSLLHOOKSTRUCT Pt(int x, int y)
        => new() { pt = new NativeMethods.POINT { x = x, y = y } };

    private static object Lauf(GestenTaste taste, int gehalten, bool ziehen)
    {
        var h = new Hook { Durchreichen = taste };
        NativeMethods.Gehalten = gehalten;
        InputReplay.Nachgespielt = 0;
        int lasso = 0;
        h.DragStarted += _ => lasso++;

        IntPtr Send(int msg, int x, int y)
        {
            var d = Pt(x, y);
            IntPtr p = Marshal.AllocHGlobal(Marshal.SizeOf<NativeMethods.MSLLHOOKSTRUCT>());
            Marshal.StructureToPtr(d, p, false);
            IntPtr r = h.Test(0, (IntPtr)msg, p);
            Marshal.FreeHGlobal(p);
            return r;
        }

        IntPtr down = Send(NativeMethods.WM_RBUTTONDOWN, 100, 100);
        if (ziehen)
        {
            Send(NativeMethods.WM_MOUSEMOVE, 160, 160);
        }
        IntPtr up = Send(NativeMethods.WM_RBUTTONUP, ziehen ? 160 : 100, ziehen ? 160 : 100);

        return new
        {
            taste = taste.ToString(), gehalten, ziehen,
            downGeschluckt = down == (IntPtr)1,
            upGeschluckt = up == (IntPtr)1,
            lasso, nachgespielt = InputReplay.Nachgespielt,
            withheld = h.PressWithheld,
        };
    }

    /// <summary>Ein Down OHNE Up (der Up geht verloren – z.B. ein UAC-Dialog
    /// kommt dazwischen), danach ein Down MIT Taste und dessen Up. Nur so ist
    /// messbar, ob der Durchreich-Zweig `_pressWithheld` wirklich zuruecksetzt:
    /// bleibt es stehen, verschluckt dieser zweite Up den Klick des Benutzers
    /// – er ist dann ganz weg.</summary>
    private static object LaufNachHaenger(GestenTaste taste, int gehalten)
    {
        var h = new Hook { Durchreichen = taste };
        NativeMethods.Gehalten = 0;
        NativeMethods.NurNachwirkung = false;
        InputReplay.Nachgespielt = 0;

        IntPtr Send(int msg, int x, int y)
        {
            var d = Pt(x, y);
            IntPtr p = Marshal.AllocHGlobal(Marshal.SizeOf<NativeMethods.MSLLHOOKSTRUCT>());
            Marshal.StructureToPtr(d, p, false);
            IntPtr r = h.Test(0, (IntPtr)msg, p);
            Marshal.FreeHGlobal(p);
            return r;
        }

        Send(NativeMethods.WM_RBUTTONDOWN, 100, 100);   // verschluckt, Up bleibt aus
        NativeMethods.Gehalten = gehalten;
        IntPtr down2 = Send(NativeMethods.WM_RBUTTONDOWN, 200, 200);
        IntPtr up2 = Send(NativeMethods.WM_RBUTTONUP, 200, 200);
        return new
        {
            fall = "nachHaenger", taste = taste.ToString(), gehalten,
            downGeschluckt = down2 == (IntPtr)1, upGeschluckt = up2 == (IntPtr)1,
            withheld = h.PressWithheld,
        };
    }

    /// <summary>Taste war gedrueckt, ist es aber NICHT mehr (nur das niedrige
    /// Bit). Das darf den Klick nicht durchreichen.</summary>
    private static object LaufNachwirkung(GestenTaste taste, int gehalten)
    {
        var h = new Hook { Durchreichen = taste };
        NativeMethods.Gehalten = gehalten;
        NativeMethods.NurNachwirkung = true;
        InputReplay.Nachgespielt = 0;
        var d = Pt(100, 100);
        IntPtr p = Marshal.AllocHGlobal(Marshal.SizeOf<NativeMethods.MSLLHOOKSTRUCT>());
        Marshal.StructureToPtr(d, p, false);
        IntPtr down = h.Test(0, (IntPtr)NativeMethods.WM_RBUTTONDOWN, p);
        Marshal.FreeHGlobal(p);
        NativeMethods.NurNachwirkung = false;
        return new
        {
            fall = "nachwirkung", taste = taste.ToString(), gehalten,
            downGeschluckt = down == (IntPtr)1,
        };
    }

    public static void Main()
    {
        var raus = new List<object>();
        raus.Add(LaufNachHaenger(GestenTaste.Strg, NativeMethods.VK_CONTROL));
        raus.Add(LaufNachwirkung(GestenTaste.Strg, NativeMethods.VK_CONTROL));
        foreach (var t in new[] { GestenTaste.Keine, GestenTaste.Strg,
                                  GestenTaste.Alt, GestenTaste.Umschalt })
        {
            foreach (var g in new[] { 0, NativeMethods.VK_CONTROL,
                                      NativeMethods.VK_MENU, NativeMethods.VK_SHIFT })
            {
                raus.Add(Lauf(t, g, false));
                raus.Add(Lauf(t, g, true));
            }
        }
        Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(raus));
    }
}
"""
    # HookProc ist privat – fuer den Lauf oeffnen (nur die Sichtbarkeit).
    proc_offen = PROC.replace("private IntPtr HookProc", "public IntPtr Test", 1)
    (ARB / "Hook.cs").write_text(
        huelle.replace("__PROC__", proc_offen).replace("__TG__", TG),
        encoding="utf-8")

    umg = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1",
               HOME="/tmp/dotnethome")
    Path("/tmp/dotnethome").mkdir(exist_ok=True)
    b = subprocess.run([str(DOTNET), "build", "-c", "Release", "--nologo"],
                       cwd=ARB, capture_output=True, text=True, timeout=420, env=umg)
    if b.returncode != 0:
        print("ABBRUCH: Testprogramm liess sich nicht uebersetzen:")
        print((b.stdout + b.stderr)[-2000:])
        sys.exit(2)
    dll = next(ARB.glob("bin/Release/net8.0/P.dll"), None)
    r = subprocess.run([str(DOTNET), str(dll)], capture_output=True, text=True,
                       timeout=120, env=umg)
    if r.returncode != 0:
        print("ABBRUCH: Lauf gescheitert:", (r.stdout + r.stderr)[-800:])
        sys.exit(2)
    erg = json.loads(r.stdout)

    print("=" * 74)
    print("LIVE: Lasso oder Rechtsziehen – die echte Verzweigung, ausgefuehrt")
    print("=" * 74)

    VK = {0: "keine", 0x11: "Strg", 0x12: "Alt", 0x10: "Umschalt"}

    def hol(taste, gehalten, ziehen):
        return next(e for e in erg if e.get("fall") is None and e["taste"] == taste
                    and e["gehalten"] == gehalten and e["ziehen"] == ziehen)

    print("\n── Vorgabe Strg: die Taste gibt den Klick frei ──")
    for ziehen in (False, True):
        e = hol("Strg", 0x11, ziehen)
        check(f"Strg gehalten, {'ziehen' if ziehen else 'klicken'}: Klick geht DURCH",
              not e["downGeschluckt"] and not e["upGeschluckt"], json.dumps(e))
        check(f"  … und es entsteht KEIN Lasso", e["lasso"] == 0, json.dumps(e))
        # ⚠ Der teure Fehler: bliebe `_pressWithheld` stehen, verschluckte der
        #   naechste BUTTONUP den Klick des Benutzers.
        check("  … und nichts bleibt zurueckgehalten", e["withheld"] is False, json.dumps(e))
        check("  … und es wird nichts nachgespielt (der Klick war nie weg)",
              e["nachgespielt"] == 0, json.dumps(e))

    print("\n── Ohne die Taste bleibt alles wie bisher ──")
    e = hol("Strg", 0, True)
    check("ohne Taste + ziehen: Lasso wie gehabt",
          e["downGeschluckt"] and e["upGeschluckt"] and e["lasso"] == 1
          and e["nachgespielt"] == 0, json.dumps(e))
    e = hol("Strg", 0, False)
    check("ohne Taste + klicken: Klick wird nachgespielt",
          e["downGeschluckt"] and e["upGeschluckt"] and e["lasso"] == 0
          and e["nachgespielt"] == 1, json.dumps(e))

    print("\n── Eine ANDERE Taste greift nicht ──")
    for g in (0x12, 0x10):
        e = hol("Strg", g, True)
        check(f"{VK[g]} gehalten (eingestellt ist Strg): Lasso wie gehabt",
              e["downGeschluckt"] and e["lasso"] == 1, json.dumps(e))

    print("\n── Die anderen Einstellungen ──")
    for taste, vk in (("Alt", 0x12), ("Umschalt", 0x10)):
        e = hol(taste, vk, True)
        check(f"eingestellt {taste}, {taste} gehalten: Klick geht durch",
              not e["downGeschluckt"] and e["lasso"] == 0 and e["withheld"] is False,
              json.dumps(e))
        e = hol(taste, 0x11, True)
        check(f"eingestellt {taste}, Strg gehalten: Lasso (Strg zaehlt dort nicht)",
              e["downGeschluckt"] and e["lasso"] == 1, json.dumps(e))

    print("\n── 'Keine': das Verhalten von vor der Aenderung ──")
    for g in (0, 0x11, 0x12, 0x10):
        e = hol("Keine", g, True)
        check(f"Keine + {VK[g]}: immer Lasso",
              e["downGeschluckt"] and e["lasso"] == 1, json.dumps(e))

    print("\n── Die Zustands-Invariante ──")
    nh = next(e for e in erg if e.get("fall") == "nachHaenger")
    check("nach einem haengengebliebenen Down reicht die Taste den naechsten Klick durch",
          not nh["downGeschluckt"], json.dumps(nh))
    # ⚠ DAS IST DER TEURE FALL: bliebe `_pressWithheld` stehen, verschluckte
    #    dieser Up den Klick – der Benutzer verliert ihn ganz.
    check("⚠ und der zugehoerige BUTTONUP wird NICHT verschluckt",
          not nh["upGeschluckt"], json.dumps(nh))
    check("nichts bleibt zurueckgehalten", nh["withheld"] is False, json.dumps(nh))

    nw = next(e for e in erg if e.get("fall") == "nachwirkung")
    check("⚠ eine losgelassene Taste (nur niedriges Bit) reicht NICHT durch",
          nw["downGeschluckt"], json.dumps(nw))

    # Positivkontrolle: der Aufbau KANN beide Ausgaenge erzeugen – sonst waeren
    # die Pruefungen oben trivial.
    check("Positivkontrolle: es gibt sowohl geschluckte als auch durchgereichte Klicks",
          any(e["downGeschluckt"] for e in erg) and any(not e["downGeschluckt"] for e in erg))

finally:
    shutil.rmtree(ARB, ignore_errors=True)

print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(1 if _fail else 0)

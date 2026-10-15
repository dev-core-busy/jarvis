using System.Runtime.InteropServices;
using AiMouse.Localization;

namespace AiMouse.Ui;

/// <summary>Die EINE Stelle, an der ein Bild in die Zwischenablage geht.
///
/// ⚠ WARUM GEMEINSAM: es gibt zwei Wege dorthin – das Auswahl-Menue nach dem
/// Aufziehen des Rahmens und (seit 2026-09-10) der Knopf im Antwortfenster.
/// Zwei Fassungen liefen beim naechsten Feinschliff auseinander, und dann legt
/// der eine Weg etwas anderes ab als der andere, an demselben Bild.
///
/// ⚠ UND EIN FEHLSCHLAG DARF NIE STILL BLEIBEN: in der Zwischenablage sieht
/// man nichts. Windows gibt sie jeweils nur EINEM Prozess; haelt ein anderer
/// sie gerade offen (Fernwartung, Passwortmanager, Office), scheitert
/// <c>SetImage</c> – und ohne Rueckmeldung fuegt der Benutzer ahnungslos den
/// alten Inhalt ein. Deshalb liefert diese Funktion den GRUND zurueck, statt
/// ihn zu verschlucken; wie er angezeigt wird, entscheidet der Aufrufer (Tray
/// oder Fensterkopf).
/// </summary>
internal static class Zwischenablage
{
    /// <summary>Legt das Bild ab. Rueckgabe: <c>null</c> bei Erfolg, sonst der
    /// anzuzeigende Grund.</summary>
    public static string? BildSetzen(Image bild)
    {
        try
        {
            Clipboard.SetImage(bild);
            return null;
        }
        catch (ExternalException ex)
        {
            // Der Regelfall: ein anderer Prozess haelt die Zwischenablage.
            return Texte.ZwischenablageBelegt + ex.Message;
        }
        catch (Exception ex)
        {
            // ⚠ BREIT, UND ZWAR ABSICHTLICH: `SetImage` kann je nach
            //    Bildzustand auch andere Ausnahmen werfen. Ein Absturz des
            //    ganzen Fensters waere hier die schlechteste Antwort auf einen
            //    Kopierversuch.
            return Texte.ZwischenablageBelegt + ex.Message;
        }
    }
}

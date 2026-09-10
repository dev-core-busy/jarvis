using AiMouse.Configuration;
using AiMouse.Localization;

namespace AiMouse.Ui;

/// <summary>Anmeldemaske: Benutzername, Kennwort, bei Bedarf Einmal-Code.
///
/// ⚠ DIESES FENSTER IST DER GRUND, WARUM DIE MARKE IM PAKET STEHT. Es erscheint,
/// BEVOR es eine Sitzung gibt – ein Serverabruf erreicht es also nicht. Marke
/// und Akzentfarbe kommen deshalb aus der <c>settings.json</c>, die der Server
/// beim Herunterladen des Pakets schreibt (dieselbe Lehre wie beim Fenster der
/// Jira-Erweiterung, wo sie als <c>&lt;meta name="marke"&gt;</c> steht).
///
/// DAS KENNWORT WIRD NIRGENDS GESPEICHERT – weder in der settings.json noch in
/// der Registry. Die Datei liegt im Klartext neben der Exe und wird per
/// Netzfreigabe verteilt. Gemerkt wird nur der BENUTZERNAME, und auch das nur
/// als Bequemlichkeit.
/// </summary>
internal sealed class LoginWindow : Form
{
    private readonly TextBox _benutzer = new() { Dock = DockStyle.Fill };
    private readonly TextBox _kennwort = new() { Dock = DockStyle.Fill, UseSystemPasswordChar = true };
    private readonly TextBox _totp = new() { Dock = DockStyle.Fill };
    private readonly Label _totpLabel;

    public string Benutzer => _benutzer.Text.Trim();

    public string Kennwort => _kennwort.Text;

    public string Totp => _totp.Text.Trim();

    public LoginWindow(AppSettings settings, bool totpNoetig = false, string benutzer = "")
    {
        Text = settings.Marke + " — " + Texte.AnmeldenTitel;
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MinimizeBox = false;
        MaximizeBox = false;
        ShowInTaskbar = true;
        // ⚠ DPI-SKALIERUNG – gemeldet 2026-09-10: „bei Zoom groesser als 100%
        // werden Felder unvollstaendig und abgeschnitten angezeigt".
        //
        // Die Ursache ist eine Kette aus drei Teilen:
        //   1. `app.manifest` deklariert PerMonitorV2 – die Anwendung sagt
        //      Windows damit „ich skaliere selbst", und Windows streckt das
        //      Fenster NICHT mehr (kein Bitmap-Stretching als Notnagel).
        //   2. `AutoScaleMode.Font` braucht `AutoScaleDimensions` als
        //      Referenz. Die setzt sonst der Designer – diese Fenster sind
        //      aber von Hand gebaut, der Wert blieb (0,0), und der
        //      Skalierungsfaktor war damit 1.0. Es wurde also NICHT skaliert.
        //   3. Die Schrift skaliert trotzdem: `new Font("Segoe UI", 9f)` ist
        //      in PUNKT angegeben, und Punkt→Pixel haengt an der DPI.
        // Ergebnis: groessere Schrift in unveraenderten Kaesten – abgeschnitten.
        //
        // `Dpi` statt `Font`: der Faktor kommt dann direkt aus der DPI und
        // nicht aus einem Schriftvergleich, der bei fest gesetzter Punktgroesse
        // ohnehin immer 1.0 ergibt. 96 ist 100%.
        AutoScaleDimensions = new SizeF(96F, 96F);
        AutoScaleMode = AutoScaleMode.Dpi;
        Font = new Font("Segoe UI", 9f);
        // Je sichtbarer Zeile rund 30 px – sonst steht der Anmelden-Knopf
        // ausserhalb des Fensters (im Projekt mehrfach bezahlt).
        ClientSize = new Size(460, 160 + (totpNoetig ? 40 : 0));

        var kopf = Marken.Kopf(settings);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            Padding = new Padding(12, 4, 12, 4),
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 130));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        AddRow(layout, Texte.Benutzername, _benutzer);
        AddRow(layout, Texte.Kennwort, _kennwort);
        _totpLabel = AddRow(layout, Texte.EinmalCode, _totp);
        _totpLabel.Visible = totpNoetig;
        _totp.Visible = totpNoetig;

        var anmelden = new Button
        {
            Text = "&" + Texte.Anmelden, Width = 110, Height = 28,
            DialogResult = DialogResult.OK,
        };
        var abbrechen = new Button
        {
            Text = Texte.Abbrechen, Width = 110, Height = 28,
            DialogResult = DialogResult.Cancel,
        };

        var knoepfe = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            FlowDirection = FlowDirection.RightToLeft,
            Height = 46,
            Padding = new Padding(12, 8, 12, 8),
        };
        knoepfe.Controls.Add(abbrechen);
        knoepfe.Controls.Add(anmelden);

        Controls.Add(layout);
        Controls.Add(knoepfe);
        Controls.Add(kopf);

        AcceptButton = anmelden;
        CancelButton = abbrechen;

        // ⚠ DIE PRUEFUNG SITZT IM SCHLIESSEN, nicht am Knopf: `DialogResult.OK`
        // am Button schliesst das Fenster, BEVOR ein Click-Handler laufen
        // koennte. Ohne diesen Zweig ginge eine leere oder unbrauchbare Adresse
        // durch und die Anmeldung scheiterte danach mit einer Meldung, aus der
        // niemand ableiten kann, dass die ADRESSE das Problem ist.
        FormClosing += (_, e) =>
        {
            if (DialogResult != DialogResult.OK) { return; }
            if (Benutzer.Length == 0)
            {
                e.Cancel = true;
                ActiveControl = _benutzer;
            }
        };

        // Vorbelegen und den Fokus auf das erste LEERE Feld setzen: bei
        // bekanntem Benutzer ist das Kennwort gemeint, beim Nachfragen des
        // Einmal-Codes dieser.
        _benutzer.Text = benutzer.Length > 0 ? benutzer : settings.Benutzer;
        if (totpNoetig)
        {
            ActiveControl = _totp;
        }
        else if (_benutzer.Text.Length > 0)
        {
            ActiveControl = _kennwort;
        }
    }


    private static Label AddRow(TableLayoutPanel layout, string caption, Control editor)
    {
        var label = new Label
        {
            Text = caption,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            Margin = new Padding(0, 0, 8, 0),
        };

        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.Controls.Add(label);
        layout.Controls.Add(editor);
        editor.Margin = new Padding(0, 3, 0, 6);
        return label;
    }
}

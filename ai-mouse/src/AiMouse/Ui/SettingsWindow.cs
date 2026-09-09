using AiMouse.Configuration;
using AiMouse.Localization;
using AiMouse.Vision;

namespace AiMouse.Ui;

/// <summary>
/// Editor for <c>settings.json</c>. Writing the file stays the single source of truth —
/// the dialog only produces a validated <see cref="AppSettings"/>; the caller persists it
/// and applies it to the running instance.
///
/// ⚠ ANGEPASST FUER JARVIS (2026-09-09). Die Felder Modell, API-Key,
/// System-Prompt, Max-Tokens und Temperatur sind ENTFALLEN – sie gehoeren jetzt
/// dem Server. Das ist keine Vereinfachung, sondern die Schranke: stuende der
/// System-Prompt hier, koennte ihn jeder Arbeitsplatz frei setzen und die
/// Regeln aushebeln, die den Lauf begrenzen.
///
/// <c>Marke</c> und <c>Akzent</c> stehen ebenfalls nicht im Dialog: sie kommen
/// beim Herunterladen aus dem Paket. Ein Feld dafuer waere die Einladung, das
/// Branding des Hauses am Arbeitsplatz zu verstellen.
/// </summary>
internal sealed class SettingsWindow : Form
{
    private readonly TextBox _endpoint = new() { Dock = DockStyle.Fill };
    private readonly TextBox _benutzer = new() { Dock = DockStyle.Fill };
    private readonly TextBox _kennwort = new() { Dock = DockStyle.Fill, UseSystemPasswordChar = true };
    private readonly ComboBox _sprache = new()
    {
        Dock = DockStyle.Fill,
        DropDownStyle = ComboBoxStyle.DropDownList,
    };
    private readonly NumericUpDown _timeout = Number(5, 3600);
    private readonly NumericUpDown _dragThreshold = Number(1, 100);
    private readonly CheckBox _copyResult = new() { AutoSize = true };

    /// <summary>Prueft die eingetippten Einstellungen wirklich gegen den Server;
    /// eingespritzt, damit der Dialog nichts von HTTP wissen muss.</summary>
    /// <summary>Verbindungstest: Einstellungen, Benutzer, Kennwort, Abbruch.
    ///
    /// ⚠ BENUTZER UND KENNWORT GEHEN MIT. Vorher nahm der Tester nur die
    /// Einstellungen und fragte die Zugangsdaten in einem EIGENEN Fenster ab –
    /// waehrend sie zwei Zeilen darueber im Dialog standen (2026-09-09
    /// gemeldet). Wer sie gerade eingetippt hat, will sie nicht noch einmal
    /// eingeben.
    /// </summary>
    private readonly Func<AppSettings, string, string, CancellationToken, Task<string>> _tester;

    private readonly Button _testButton;
    private readonly Label _status;

    /// <summary>Der Stand beim Oeffnen. Traegt die Felder, die der Dialog NICHT
    /// zeigt (Marke, Akzent, zuletzt benutzter Benutzername) – sie werden beim
    /// Speichern durchgereicht statt neu erzeugt.</summary>
    private readonly AppSettings _ausgang;

    private CancellationTokenSource? _testCts;

    /// <summary>Only meaningful once <see cref="DialogResult.OK"/> was returned.</summary>
    public AppSettings Result { get; private set; } = new();

    /// <summary>Das eingegebene Kennwort – LEER heisst „nicht neu anmelden".
    ///
    /// ⚠ ES GEHOERT NICHT IN `AppSettings`: das wird gespeichert, und ein
    /// Kennwort wird in diesem Projekt nie gespeichert (auch nicht
    /// verschluesselt – gespeichert wird das ablaufende Sitzungstoken). Es
    /// lebt nur, bis der Aufrufer sich damit angemeldet hat.
    /// </summary>
    public string Kennwort { get; private set; } = string.Empty;

    public SettingsWindow(AppSettings current,
                          Func<AppSettings, string, string, CancellationToken, Task<string>> tester)
    {
        _tester = tester;
        _ausgang = current;

        // Die Marke steht im Titel – sie kommt aus der settings.json, also aus
        // dem Paket. Ein Serverabruf erreicht diesen Dialog nicht zuverlaessig
        // (er ist auch ohne Anmeldung erreichbar).
        Text = current.Marke + " — " + Texte.Einstellungen.TrimEnd('…');
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MinimizeBox = false;
        MaximizeBox = true;
        ShowInTaskbar = true;
        AutoScaleMode = AutoScaleMode.Font;
        Font = new Font("Segoe UI", 9f);
        ClientSize = new Size(520, 420);

        _copyResult.Text = Texte.ErgebnisKopieren;
        _sprache.Items.AddRange(["Deutsch", "English"]);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            Padding = new Padding(12),
            AutoSize = false,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        AddRow(layout, Texte.Serveradresse, _endpoint);
        // ⚠ DIE ZUGANGSDATEN GEHOEREN HIERHER (Vorgabe 2026-09-09, zweite
        // Aufforderung). Ein Benutzer, der sein Kennwort geaendert hat oder
        // sich als jemand anders anmelden will, sucht sie in den
        // Einstellungen – nicht in einer Maske, die nur beim ersten Start
        // erscheint. Die Anmeldemaske bleibt fuer den Fall, dass die Sitzung
        // waehrend der Arbeit ablaeuft.
        AddRow(layout, Texte.Benutzername, _benutzer);
        AddRow(layout, Texte.Kennwort, _kennwort);
        AddRow(layout, Texte.Sprache, _sprache);
        AddRow(layout, Texte.Zeitlimit, _timeout);
        AddRow(layout, Texte.Ziehschwelle, _dragThreshold);
        AddRow(layout, string.Empty, _copyResult);

        _status = new Label
        {
            Dock = DockStyle.Bottom,
            Height = 52,
            Padding = new Padding(14, 0, 14, 6),
            ForeColor = SystemColors.GrayText,
            Text = ConfigStore.SettingsPath,
        };

        var save = new Button { Text = "&" + Texte.Speichern, Width = 100, Height = 28, DialogResult = DialogResult.None };
        save.Click += OnSave;

        var cancel = new Button { Text = Texte.Abbrechen, Width = 100, Height = 28, DialogResult = DialogResult.Cancel };

        _testButton = new Button { Text = Texte.VerbindungTesten, Width = 150, Height = 28, DialogResult = DialogResult.None };
        _testButton.Click += OnTestConnection;

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            FlowDirection = FlowDirection.RightToLeft,
            Height = 46,
            Padding = new Padding(12, 8, 12, 8),
        };
        // RightToLeft flow: first added sits rightmost.
        buttons.Controls.Add(cancel);
        buttons.Controls.Add(save);
        buttons.Controls.Add(_testButton);

        // Docked last means docked outermost, so the status line ends up at the bottom.
        Controls.Add(layout);
        Controls.Add(buttons);
        // ⚠ ZULETZT hinzugefuegt, damit er OBEN sitzt: bei `Dock = Top` gewinnt
        // das ZULETZT eingefuegte Element den oberen Platz (WinForms fuellt in
        // umgekehrter Reihenfolge der Controls-Sammlung).
        Controls.Add(Marken.Kopf(current));
        Controls.Add(_status);

        AcceptButton = save;
        CancelButton = cancel;

        Populate(current);
    }

    private void Populate(AppSettings s)
    {
        _endpoint.Text = s.Endpoint;
        _benutzer.Text = s.Benutzer ?? string.Empty;
        // Das Kennwort steht NIRGENDS gespeichert (nur das Sitzungstoken),
        // also gibt es hier auch nichts vorzubelegen. LEER heisst "nicht
        // aendern" – wer sich neu anmelden will, tippt es ein.
        _kennwort.Text = string.Empty;
        _sprache.SelectedIndex = (s.Sprache ?? string.Empty)
            .Trim().StartsWith("en", StringComparison.OrdinalIgnoreCase) ? 1 : 0;
        _timeout.Value = Clamp(_timeout, s.TimeoutSeconds);
        _dragThreshold.Value = Clamp(_dragThreshold, s.DragThreshold);
        _copyResult.Checked = s.CopyResultToClipboard;
    }

    private void OnSave(object? sender, EventArgs e)
    {
        Kennwort = _kennwort.Text;
        if (BuildSettings() is not { } settings)
        {
            return;
        }

        Result = settings;
        DialogResult = DialogResult.OK;
        Close();
    }

    private async void OnTestConnection(object? sender, EventArgs e)
    {
        if (BuildSettings() is not { } candidate)
        {
            return;
        }

        _testCts?.Cancel();
        _testCts?.Dispose();
        _testCts = new CancellationTokenSource();

        _testButton.Enabled = false;
        SetStatus(Texte.AnmeldungLaeuft, SystemColors.GrayText);

        try
        {
            // Die eingetippten Zugangsdaten mitgeben – ein leeres Kennwort
            // heisst „nimm die laufende Sitzung", nicht „frag nach".
            string antwort = await _tester(candidate, _benutzer.Text.Trim(),
                                           _kennwort.Text, _testCts.Token);
            SetStatus(Texte.VerbindungOk + " " + Shorten(antwort), Color.SeaGreen);
        }
        catch (OperationCanceledException)
        {
            SetStatus(Texte.Abbrechen, SystemColors.GrayText);
        }
        catch (Exception ex)
        {
            // Der Fehlertext des Servers steht WOERTLICH da: er unterscheidet
            // die haeufigen Faelle (falsche Adresse, Zertifikat, keine
            // Freigabe, Skill aus) und ist die einzige Spur fuer den Benutzer.
            SetStatus(Shorten(ex.Message), Color.Firebrick);
        }
        finally
        {
            if (!IsDisposed)
            {
                _testButton.Enabled = true;
            }
        }
    }

    private void SetStatus(string text, Color color)
    {
        if (IsDisposed)
        {
            return;
        }

        _status.ForeColor = color;
        _status.Text = text.ReplaceLineEndings(" ");
    }

    private static string Shorten(string value)
    {
        string flat = value.ReplaceLineEndings(" ").Trim();
        return flat.Length <= 200 ? flat : flat[..200] + " …";
    }

    /// <summary>Validated snapshot of the form, or <c>null</c> if the user was told why not.</summary>
    private AppSettings? BuildSettings()
    {
        // ⚠ Geprueft wird ueber `EndpointResolver.Basis` und NICHT mit einem
        // eigenen Uri.TryCreate: sonst laufen Dialog und Client auseinander,
        // und der Dialog lehnt eine Adresse ab, die der Client versteht (oder
        // umgekehrt). Eine leere Rueckgabe heisst "unbrauchbar".
        string basis = EndpointResolver.Basis(_endpoint.Text);
        if (basis.Length == 0)
        {
            Complain(Texte.KeinServer, _endpoint);
            return null;
        }

        return new AppSettings
        {
            // Normalisiert gespeichert, damit im Feld die Adresse steht, die
            // wirklich aufgerufen wird.
            Endpoint = basis,
            Sprache = _sprache.SelectedIndex == 1 ? "en" : "de",
            TimeoutSeconds = (int)_timeout.Value,
            DragThreshold = (int)_dragThreshold.Value,
            CopyResultToClipboard = _copyResult.Checked,
            // ⚠ MARKE UND AKZENT DURCHREICHEN, NICHT NEU ERZEUGEN. Sie stehen
            // nicht im Dialog; wuerden sie hier ausgelassen, ueberschriebe das
            // Speichern das Branding des Pakets mit den Vorgabewerten – die
            // Anwendung hiesse nach der ersten Einstellungsaenderung wieder
            // "Jarvis". Dieselbe Falle wie ein Formular, das eine Teilmenge
            // sendet und den Rest ueberschreibt.
            Marke = _ausgang.Marke,
            Akzent = _ausgang.Akzent,
            // Der Benutzername kommt jetzt AUS DEM DIALOG (Vorgabe
            // 2026-09-09). Leer bleibt der bisherige stehen – sonst loeschte
            // ein Speichern ohne Eingabe die Anmeldung.
            Benutzer = _benutzer.Text.Trim().Length > 0
                ? _benutzer.Text.Trim() : _ausgang.Benutzer,
        };
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        // Abandon a test still in flight rather than leaving it to time out.
        _testCts?.Cancel();
        _testCts?.Dispose();
        _testCts = null;

        base.OnFormClosed(e);
    }

    private void Complain(string message, Control focus)
    {
        MessageBox.Show(this, message, Texte.FehlerTitel, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        focus.Focus();
    }

    private static void AddRow(TableLayoutPanel layout, string caption, Control editor)
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
    }

    private static NumericUpDown Number(decimal min, decimal max, int decimals = 0, decimal increment = 1m) => new()
    {
        Minimum = min,
        Maximum = max,
        DecimalPlaces = decimals,
        Increment = increment,
        Width = 110,
        Anchor = AnchorStyles.Left,
    };

    /// <summary>Keeps a hand-edited out-of-range value from throwing on assignment.</summary>
    private static decimal Clamp(NumericUpDown box, decimal value) => Math.Clamp(value, box.Minimum, box.Maximum);
}

using AiMouse.Configuration;
using AiMouse.Localization;
using AiMouse.Start;
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
    /// <summary>Taste, die den Rechtsklick durchreicht (Windows-Drag&Drop).</summary>
    private readonly ComboBox _rightDrag = new()
    {
        Dock = DockStyle.Fill,
        DropDownStyle = ComboBoxStyle.DropDownList,
    };
    /// <summary>Taste, die die GESTE ausloest – die Umkehrung von
    /// <see cref="_rightDrag"/>. Vorgabe leer = wie bisher.</summary>
    private readonly ComboBox _gesteTaste = new()
    {
        Dock = DockStyle.Fill,
        DropDownStyle = ComboBoxStyle.DropDownList,
    };

    /// <summary>Sagt, WARUM das Feld darunter gesperrt ist.
    ///
    /// ⚠ GESPERRT MIT BEGRUENDUNG STATT VERBORGEN (Projektregel): ein
    /// Bedienelement, das je nach Einstellung verschwindet, ist von einem
    /// fehlenden nicht zu unterscheiden – und niemand kann erklaeren, warum
    /// es weg ist.</summary>
    private readonly Label _rdHinweis = new()
    {
        Dock = DockStyle.Fill,
        // ⚠ Kein `Height = 30`: der Satz bricht bei groesserer Schrift um.
        AutoSize = true,
        ForeColor = SystemColors.GrayText,
        Visible = false,
    };

    private readonly CheckBox _copyResult = new() { AutoSize = true };

    /// <summary>Mit Windows starten (Verknuepfung im Autostart-Ordner).</summary>
    private readonly CheckBox _mitWindows = new() { AutoSize = true };

    /// <summary>AUFNAHMEFELD fuer die Tastenkombination – bewusst kein
    /// Freitextfeld.
    ///
    /// ⚠ EIN TEXTFELD WAERE HIER DIE FALSCHE BAUFORM: der Benutzer muesste die
    /// Schreibweise kennen („CTRL+ALT+A"), ein Tippfehler faellt erst auf, wenn
    /// die Kombination spaeter nicht wirkt – und ein `.lnk`-Hotkey meldet
    /// nicht, dass er unbrauchbar ist. Er tut dann einfach nichts. Aufnehmen
    /// heisst: was hier steht, ist genau das, was gedrueckt wurde.
    /// </summary>
    private readonly TextBox _hotkey = new()
    {
        Dock = DockStyle.Fill,
        ReadOnly = true,
        TextAlign = HorizontalAlignment.Center,
    };

    private readonly Button _hotkeyLoeschen = new()
    {
        Dock = DockStyle.Right,
        Width = 90,
    };

    /// <summary>Erklaert die zwei Einschraenkungen, die niemand erraten kann
    /// (Strg+Alt Pflicht; wirkt ueber eine Verknuepfung im Startmenue).</summary>
    private readonly Label _hotkeyHinweis = new()
    {
        Dock = DockStyle.Fill,
        AutoSize = true,
        ForeColor = SystemColors.GrayText,
    };

    /// <summary>Aufgenommene Kombination; <c>(0, 0)</c> = keine.</summary>
    private int _hkModifier;
    private int _hkVk;

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

    /// <summary>Gespeicherte Werte in der Reihenfolge des Pulldowns.</summary>
    private static readonly string[] _RD_WERTE = ["none", "ctrl", "alt", "shift"];

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
        // ⚠ `Sizable` STATT `FixedDialog` – gemeldet 2026-09-14: „ich kann
        //    keine Einstellung fuer die Tastenkombination finden". Sie war da,
        //    nur unerreichbar: die Zeilenzahl dieses Dialogs hat sich seit dem
        //    Erstimport von 7 auf 14 verdoppelt, `ClientSize` blieb bei 420 px.
        //    Ein `FixedDialog` ohne `AutoScroll` schneidet ueberzaehlige Zeilen
        //    nicht ab – er laesst sie GANZ WEG, und nichts weist darauf hin.
        //    Drei Netze gegen dieselbe Lage, in dieser Reihenfolge:
        //      1. die Hoehe wird aus dem Inhalt GERECHNET (siehe unten),
        //      2. `AutoScroll` faengt auf, was die Rechnung nicht trifft,
        //      3. der Benutzer kann das Fenster selbst ziehen.
        FormBorderStyle = FormBorderStyle.Sizable;
        MinimizeBox = false;
        MaximizeBox = true;
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
        // Startwert; die tatsaechliche Hoehe rechnet `HoeheAnInhaltBinden()`
        // am Ende des Konstruktors aus dem fertig gefuellten Layout aus.
        ClientSize = new Size(520, 420);
        // Damit niemand den Dialog unbrauchbar klein zieht. Kleiner als die
        // Startbreite, sonst laesst er sich gar nicht mehr schmaler machen.
        MinimumSize = new Size(420, 320);

        _copyResult.Text = Texte.ErgebnisKopieren;
        _sprache.Items.AddRange(["Deutsch", "English"]);
        // Reihenfolge = _RD_WERTE. Eine Umsortierung hier ohne die Liste dort
        // waere eine still falsche Zuordnung – der Test haelt beide zusammen.
        _rightDrag.Items.AddRange([Texte.RdKeine, "Strg", "Alt", Texte.RdUmschalt]);
        // Reihenfolge = _RD_WERTE, dieselbe Liste.
        _gesteTaste.Items.AddRange([Texte.GkKeine, "Strg", "Alt", Texte.RdUmschalt]);
        // ⚠ Sofort umschalten, nicht erst beim Speichern: sonst steht die
        //    Sperre erst da, wenn der Dialog schon zu ist.
        _gesteTaste.SelectedIndexChanged += (_, _) => TastenfelderAbgleichen();

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            Padding = new Padding(12),
            AutoSize = false,
            // ⚠ DAS NETZ, NICHT DER REGELWEG: reicht der Platz doch nicht
            //    (sehr grosser Zoom, kuenftige Zeilen, eine Schrift mit
            //    hoeheren Zeilen), erscheint ein Rollbalken – statt dass die
            //    unteren Zeilen wortlos verschwinden. Im Normalfall ist er
            //    unsichtbar, weil die gerechnete Hoehe passt.
            AutoScroll = true,
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
        // ⚠ DIE GESTENTASTE STEHT VOR DER DURCHREICH-TASTE: sie entscheidet,
        //    ob jene ueberhaupt eine Bedeutung hat. Andersherum gelesen waere
        //    die Sperre darunter nicht erklaerbar.
        AddRow(layout, Texte.GesteTaste, _gesteTaste);
        AddRow(layout, Texte.RechtsziehTaste, _rightDrag);
        AddRow(layout, string.Empty, _rdHinweis);
        AddRow(layout, string.Empty, _copyResult);

        // ── Start ────────────────────────────────────────────────────────────
        // Eigener Abschnitt: darunter stehen keine Einstellungen der GESTE
        // mehr, sondern zwei, die das Verhalten von WINDOWS betreffen (was beim
        // Anmelden startet, worauf eine Tastenkombination liegt). Ohne die
        // Trennlinie liest sich das wie ein weiteres Gestenfeld.
        AddRow(layout, string.Empty, Trennlinie(Texte.StartAbschnitt));

        _hotkey.KeyDown += OnHotkeyTaste;
        // ⚠ RUECKMELDUNG, DASS DAS FELD AUFNIMMT. Ein schreibgeschuetztes Feld
        //    sieht aus wie eine Anzeige – ohne diesen Wechsel probiert niemand,
        //    einfach Tasten zu druecken.
        _hotkey.Enter += (_, _) => _hotkey.Text = Texte.HotkeyDruecken;
        _hotkey.Leave += (_, _) => HotkeySetzen(_hkModifier, _hkVk);
        // ⚠ Auch `KeyPress` abfangen: sonst quittiert Windows die Eingabe in
        //   einem ReadOnly-Feld mit einem Systemton bei jedem Tastendruck.
        _hotkey.KeyPress += (_, ke) => ke.Handled = true;
        _hotkeyLoeschen.Text = Texte.HotkeyKeine;
        _hotkeyLoeschen.Click += (_, _) => HotkeySetzen(0, 0);

        var hkZeile = new Panel { Dock = DockStyle.Fill, Height = 26 };
        // Reihenfolge: der gefuellte Dock=Right-Knopf zuerst, sonst nimmt das
        // Dock=Fill-Feld die ganze Breite und der Knopf landet ausserhalb.
        hkZeile.Controls.Add(_hotkey);
        hkZeile.Controls.Add(_hotkeyLoeschen);

        AddRow(layout, Texte.StartHotkey, hkZeile);
        _hotkeyHinweis.Text = Texte.HotkeyHinweis + " " + Texte.HotkeyBelegtHinweis;
        AddRow(layout, string.Empty, _hotkeyHinweis);

        _mitWindows.Text = Texte.MitWindowsStarten;
        AddRow(layout, string.Empty, _mitWindows);

        _status = new Label
        {
            Dock = DockStyle.Bottom,
            // ⚠ `AutoSize` STATT FESTER HOEHE: hier steht Fliesstext (Pfad,
            //    Fehlermeldungen), der bei groesserer Schrift umbricht. Eine
            //    feste Hoehe schneidet dann die zweite Zeile ab – und genau
            //    das ist das gemeldete Symptom, nur eine Ebene tiefer als die
            //    fehlende DPI-Skalierung. `AutoSize` mit `Bottom` waechst nach
            //    oben, der Kasten bleibt also im Fenster.
            // (`AutoSizeMode` gibt es am Label nicht – das ist eine
            //  Eigenschaft von Containern.)
            AutoSize = true,
            MinimumSize = new Size(0, 52),
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
        var kopf = Marken.Kopf(current);
        Controls.Add(kopf);
        Controls.Add(_status);

        // ⚠ ZULETZT: erst jetzt steht fest, wie hoch der Inhalt wirklich ist.
        HoeheAnInhaltBinden(layout, kopf, buttons);

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
        int rd = Array.IndexOf(_RD_WERTE, (s.RightDragKey ?? string.Empty).Trim().ToLowerInvariant());
        // Unbekannter Wert -> „Strg": dieselbe Richtung wie im Tray, damit die
        // Anzeige nicht etwas anderes behauptet als das, was wirklich gilt.
        _rightDrag.SelectedIndex = rd >= 0 ? rd : 1;
        // ⚠ HIER FAELLT UNBEKANNTES AUF 0 („keine"), oben auf 1 („Strg") –
        //    die Vorgaben der zwei Felder sind entgegengesetzt, und beide
        //    zeigen damit das BISHERIGE Verhalten an (Begruendung in
        //    `TrayApplicationContext.GestenTasteAus`).
        int gk = Array.IndexOf(_RD_WERTE, (s.GestureKey ?? string.Empty).Trim().ToLowerInvariant());
        _gesteTaste.SelectedIndex = gk >= 0 ? gk : 0;
        TastenfelderAbgleichen();

        _mitWindows.Checked = s.MitWindowsStarten;
        // Ein unbrauchbarer gespeicherter Wert ergibt (0,0) = „keine" – das ist
        // dasselbe, was die Anwendung daraus macht (`Startwege` entfernt die
        // Verknuepfung dann). Anzeige und Wirkung koennen so nicht
        // auseinanderlaufen.
        (int m, int v) = HotkeyWort.AusText(s.StartHotkey);
        HotkeySetzen(m, v);
    }

    /// <summary>Nimmt einen Tastendruck als Kombination auf.</summary>
    private void OnHotkeyTaste(object? sender, KeyEventArgs e)
    {
        // ⚠ BEIDES SETZEN: `Handled` allein laesst die Eingabe noch an die
        //   Dialog-Mnemonics durch – Alt+S wuerde „Speichern" ausloesen,
        //   waehrend der Benutzer eine Kombination aufnimmt.
        e.Handled = true;
        e.SuppressKeyPress = true;

        int vk = (int)e.KeyCode;

        // Eine gedrueckte Modifikatortaste ist noch keine Kombination – sonst
        // stuende schon beim Greifen nach Strg etwas im Feld.
        if (e.KeyCode is Keys.ControlKey or Keys.Menu or Keys.ShiftKey
                      or Keys.LWin or Keys.RWin)
        {
            return;
        }

        // Rücktaste/Entf leeren – die naheliegende Geste, um etwas loszuwerden.
        if (e.KeyCode is Keys.Back or Keys.Delete)
        {
            HotkeySetzen(0, 0);
            return;
        }

        int mod = (e.Control ? HotkeyWort.ModStrg : 0)
                | (e.Alt ? HotkeyWort.ModAlt : 0)
                | (e.Shift ? HotkeyWort.ModUmschalt : 0);

        // ⚠ UNZULAESSIGES WIRD NICHT UEBERNOMMEN UND NICHT KOMMENTIERT: der
        //   Hinweis unter dem Feld steht ohnehin da und nennt die Regel. Ein
        //   Dialogfenster bei jedem Tastendruck waere hier eine Zumutung –
        //   man probiert beim Aufnehmen zwangslaeufig etwas aus.
        if (HotkeyWort.IstZulaessig(mod, vk))
        {
            HotkeySetzen(mod, vk);
        }
    }

    private void HotkeySetzen(int modifier, int vk)
    {
        bool gut = HotkeyWort.IstZulaessig(modifier, vk);
        _hkModifier = gut ? modifier : 0;
        _hkVk = gut ? vk : 0;
        _hotkey.Text = gut ? HotkeyWort.AlsText(modifier, vk) : Texte.HotkeyKeine;
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
            RightDragKey = _RD_WERTE[Math.Clamp(_rightDrag.SelectedIndex, 0, _RD_WERTE.Length - 1)],
            GestureKey = _RD_WERTE[Math.Clamp(_gesteTaste.SelectedIndex, 0, _RD_WERTE.Length - 1)],
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
            // Aus der aufgenommenen Kombination, nicht aus dem Feldtext: dort
            // steht bei „keine" ein uebersetztes Wort, das kein Hotkey ist.
            StartHotkey = HotkeyWort.AlsText(_hkModifier, _hkVk),
            MitWindowsStarten = _mitWindows.Checked,
        };
    }

    /// <summary>Waagerechte Linie mit Beschriftung – trennt die Start-Optionen
    /// von den Gesten-Einstellungen darueber.</summary>
    private static Control Trennlinie(string text)
    {
        var box = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            // ⚠ `AutoSize` + `WrapContents`: bei groesserer Schrift (Zoom)
            //    rutscht die Linie unter den Text, statt abgeschnitten zu
            //    werden – dieselbe Regel wie beim Marken-Kopf.
            WrapContents = true,
            Margin = new Padding(0, 10, 0, 2),
        };

        box.Controls.Add(new Label
        {
            Text = text,
            AutoSize = true,
            Font = new Font(SystemFonts.DefaultFont, FontStyle.Bold),
            Margin = new Padding(0, 0, 8, 0),
        });

        box.Controls.Add(new Label
        {
            // Eine 1px-Linie als Label: ein eigenes Control dafuer waere mehr
            // Aufwand als Gewinn.
            AutoSize = false,
            Height = 1,
            Width = 300,
            BorderStyle = BorderStyle.Fixed3D,
            Margin = new Padding(0, 8, 0, 0),
        });

        return box;
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

    /// <summary>Setzt die Fensterhoehe auf das, was der Inhalt WIRKLICH
    /// braucht – gedeckelt auf den nutzbaren Bildschirm.
    ///
    /// ⚠ GERECHNET, NICHT GERATEN. Eine feste Zahl ist an dem Tag falsch, an
    /// dem eine Zeile dazukommt – hier geschehen: von 7 Zeilen beim Erstimport
    /// auf 14, waehrend `ClientSize` bei 420 px stehenblieb. Die vier Zeilen
    /// des Start-Abschnitts (Tastenkombination, Autostart) lagen damit
    /// ausserhalb des Fensters, und ohne Rollbalken gab es keinen Weg dorthin:
    /// gemeldet als „ich kann keine Einstellung fuer die Tastenkombination
    /// finden". Bei Zoom &gt; 100% gilt dasselbe eine Stufe frueher, weil jede
    /// Zeile dann hoeher ist – `GetPreferredSize` fragt WinForms nach dem
    /// bereits skalierten Ergebnis und trifft deshalb beide Faelle.
    ///
    /// Faellt die Rechnung zu knapp aus – umbrechende Hinweiszeilen sind der
    /// wahrscheinlichste Grund –, faengt `AutoScroll` am Layout den Rest auf.
    /// Ein Fehler hier ist deshalb billig; eine feste Hoehe war es nicht.
    /// </summary>
    private void HoeheAnInhaltBinden(Control layout, Control kopf, Control buttons)
    {
        try
        {
            int zeilen = layout.GetPreferredSize(new Size(ClientSize.Width, 0)).Height;
            int rand = Math.Max(kopf.Height, kopf.PreferredSize.Height)
                     + buttons.Height
                     + Math.Max(_status.PreferredSize.Height, _status.MinimumSize.Height);

            // Die Reserve deckt Titelleiste und Rahmen ab – die zaehlen NICHT
            // zu `ClientSize`, wuerden ein randvoll gerechnetes Fenster also
            // unten aus dem Bildschirm schieben.
            int platz = Screen.FromPoint(Cursor.Position).WorkingArea.Height - 80;

            // Untergrenze ist die bisherige Hoehe: kleiner soll der Dialog nie
            // starten, auch wenn die Rechnung etwas Absurdes liefert.
            ClientSize = new Size(
                ClientSize.Width,
                Math.Clamp(zeilen + rand, 420, Math.Max(420, platz)));
        }
        catch
        {
            // ⚠ FAIL-SAFE IN DIE GROSSZUEGIGE RICHTUNG: lieber ein Fenster,
            //    das mehr Platz nimmt als noetig, als eines, das
            //    Bedienelemente verschluckt. Die Startgroesse bleibt stehen,
            //    `AutoScroll` traegt den Rest.
        }
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

    /// <summary>Sperrt die Durchreich-Taste, sobald eine Gestentaste gilt.
    ///
    /// ⚠ Die beiden sind entgegengesetzt: mit Gestentaste geht der Rechtsklick
    /// ohnehin an die Anwendung – „durchreichen mit Taste" haette dann keine
    /// Bedeutung mehr, und dieselbe Taste koennte zweierlei heissen.
    /// Die Sperre ist nur die ANZEIGE; durchgesetzt wird sie in
    /// `TrayApplicationContext.TastenAus` (sonst haenge das Verhalten daran,
    /// dass niemand die Registry von Hand anfasst).
    /// </summary>
    private void TastenfelderAbgleichen()
    {
        bool mitGeste = _gesteTaste.SelectedIndex > 0;
        _rightDrag.Enabled = !mitGeste;
        _rdHinweis.Text = mitGeste ? Texte.RdGesperrt : string.Empty;
        _rdHinweis.Visible = mitGeste;
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

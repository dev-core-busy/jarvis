using System.Diagnostics;
using AiMouse.Capture;
using AiMouse.Configuration;
using AiMouse.Localization;
using AiMouse.Input;
using AiMouse.Interop;
using AiMouse.Ui;
using AiMouse.Vision;

namespace AiMouse;

/// <summary>
/// Wires everything together: the global gesture hook, the selection overlay, the
/// prompt menu and the vision request. Lives for the whole process lifetime.
/// </summary>
internal sealed class TrayApplicationContext : ApplicationContext
{
    /// <summary>Time given to the compositor to repaint the area the overlay covered.</summary>
    private const int OverlayRepaintDelayMs = 60;

    private readonly Form _owner;
    private readonly NotifyIcon _trayIcon;
    private readonly SelectionOverlay _overlay;
    private readonly MouseGestureHook _hook;
    private readonly ContextMenuStrip _promptMenu;

    private AppSettings _settings;

    /// <summary>Der Jarvis-Client – LANGLEBIG, nicht je Auswertung neu.
    ///
    /// ⚠ Er traegt das Sitzungstoken. Bis 2026-09-09 wurde der Client je
    /// Auswertung erzeugt und wieder verworfen; das war richtig, solange er nur
    /// eine Adresse und einen API-Key hielt. Mit einer Anmeldung waere es der
    /// Zwang, sich bei JEDEM aufgezogenen Rahmen neu anzumelden.
    /// </summary>
    private JarvisClient _client;
    private IReadOnlyList<PromptItem> _prompts;

    /// <summary>Screenshot waiting for the user to pick a prompt; owned by this class.</summary>
    private Bitmap? _pendingCapture;

    private bool _promptChosen;

    /// <summary>Throttles the replay warning: it repeats per click while it applies.</summary>
    private DateTime _lastReplayWarningUtc = DateTime.MinValue;

    /// <summary>Non-null while the settings dialog is open, to keep it single-instance.</summary>
    private SettingsWindow? _settingsWindow;

    public TrayApplicationContext()
    {
        _settings = ConfigStore.LoadSettings(out string? settingsError);
        // Die Sprache steht in der settings.json (der Server schreibt sie beim
        // Paketbau) und muss VOR dem ersten Fenster gelten – sonst traegt die
        // Anmeldemaske deutsche Beschriftungen in einem englischen Haus.
        Texte.Anwenden(_settings);
        _client = new JarvisClient(_settings);
        // ⚠ KEINE prompts.json MEHR. Bis zur ersten Anmeldung gelten die
        // eingebauten Fragen; danach holt `FragenNachladenAsync` die des
        // Benutzers vom Server. Ohne diesen Zwischenzustand waere das Menue
        // beim allerersten Rahmen leer.
        // ⚠ GEMERKTE SITZUNG UND FRAGEN – ohne Serveraufruf.
        //
        // Nach dem ERSTEN Start ist alles eingerichtet: das Token liegt (per
        // DPAPI an dieses Windows-Konto gebunden) in der Registry, die Fragen
        // daneben. Damit steht das Menue sofort und richtig, auch wenn der
        // Server gerade langsam oder nicht erreichbar ist.
        //
        // Ist das Token abgelaufen, faellt das beim ersten echten Aufruf auf
        // (401 -> AnmeldungNoetigException) und der vorhandene Weg fragt neu.
        // Es hier zu pruefen kostete einen Serveraufruf bei JEDEM Start und
        // beantwortete doch nur dieselbe Frage.
        _client.TokenSetzen(ConfigStore.LoadToken());
        List<PromptItem> gemerkt = ConfigStore.LoadPrompts();
        // Die eingebauten Fragen sind der Zwischenzustand VOR der ersten
        // Anmeldung – ohne sie waere das Menue beim allerersten Rahmen leer.
        _prompts = gemerkt.Count > 0 ? gemerkt : PromptItem.Defaults;
        string? promptsError = null;

        // Off-screen 1×1 window: owns the message pump for the hook callbacks and
        // gives the context menu a foreground window so it dismisses correctly.
        _owner = new Form
        {
            FormBorderStyle = FormBorderStyle.None,
            StartPosition = FormStartPosition.Manual,
            Location = new Point(-32000, -32000),
            Size = new Size(1, 1),
            ShowInTaskbar = false,
            Opacity = 0d,
        };
        _owner.Show();

        _overlay = new SelectionOverlay();

        _promptMenu = new ContextMenuStrip { ShowImageMargin = false };
        _promptMenu.Closed += OnPromptMenuClosed;
        BuildPromptMenu();

        _trayIcon = new NotifyIcon
        {
            Icon = TrayIconFactory.Create(),
            Visible = true,
            Text = "AI Mouse — right-click + drag to capture",
            ContextMenuStrip = BuildTrayMenu(),
        };

        _hook = new MouseGestureHook(_owner, _settings.DragThreshold);
        _hook.DragStarted += point => _overlay.BeginSelection(point);
        _hook.DragMoved += point => _overlay.UpdateSelection(point);
        _hook.DragCompleted += OnDragCompleted;
        _hook.ReplayFailed += OnReplayFailed;

        try
        {
            _hook.Install();
        }
        catch
        {
            // Nothing is running yet, so tear the half-built context down here rather
            // than leaving a stray tray icon behind; Program reports the failure.
            Dispose(true);
            throw;
        }

        string? startupWarning = settingsError ?? promptsError;
        if (startupWarning is not null)
        {
            _trayIcon.ShowBalloonTip(5000, "AI Mouse", startupWarning, ToolTipIcon.Warning);
        }

        // ⚠ ANMELDUNG UND FRAGEN BEIM START – ausdrueckliche Vorgabe vom
        // 2026-09-09 ("Die Anwendung muss das beim Start laden!").
        //
        // `BeginInvoke` und nicht der direkte Aufruf: der Konstruktor laeuft,
        // BEVOR die Nachrichtenschleife steht. Ein modaler Dialog von hier aus
        // haette kein Fenster, an dem er haengen kann – die Anmeldemaske
        // erschiene hinter allem anderen oder gar nicht. So wird sie im ersten
        // freien Takt geoeffnet, wenn die Anwendung bereits laeuft.
        _owner.BeginInvoke(new Action(() => { _ = StartAnmeldungAsync(); }));
    }

    private void BuildPromptMenu()
    {
        _promptMenu.Items.Clear();

        foreach (PromptItem prompt in _prompts)
        {
            var item = new ToolStripMenuItem(prompt.Title) { Tag = prompt };
            item.Click += OnPromptItemClicked;
            _promptMenu.Items.Add(item);
        }

        _promptMenu.Items.Add(new ToolStripSeparator());

        var copyItem = new ToolStripMenuItem("Copy image to clipboard");
        copyItem.Click += OnCopyImageClicked;
        _promptMenu.Items.Add(copyItem);

        var saveItem = new ToolStripMenuItem("Save image as…");
        saveItem.Click += OnSaveImageClicked;
        _promptMenu.Items.Add(saveItem);

        // The tray icon lives in the Windows 11 overflow flyout by default, so for most
        // users this popup is the only part of the app they ever see. Settings has to be
        // reachable from here or it is effectively missing.
        _promptMenu.Items.Add(new ToolStripSeparator());

        var settingsItem = new ToolStripMenuItem(Texte.Einstellungen);
        settingsItem.Click += (_, _) => ShowSettings();
        _promptMenu.Items.Add(settingsItem);

        // ⚠ HIER STAND "Exit AI Mouse" – das BEENDETE die Anwendung. In einem
        // Menue, das nach einem versehentlich aufgezogenen Rahmen aufgeht, ist
        // das der falsche Eintrag an der gefaehrlichsten Stelle: direkt unter
        // den Fragen, einen Fehlklick entfernt. Wer abbrechen will, will das
        // Menue los – nicht das Programm.
        //
        // Beendet wird ueber das Tray-Symbol (dort steht "Beenden"). Das ist
        // die einzige Stelle, an der die Zusage "alles ist an beiden Stellen
        // erreichbar" bewusst nicht gilt.
        var abbrechenItem = new ToolStripMenuItem(Texte.Abbrechen);
        abbrechenItem.Click += (_, _) => DiscardPendingCapture();
        _promptMenu.Items.Add(abbrechenItem);
    }

    /// <summary>Beim Start anmelden und die Fragen holen.
    ///
    /// ⚠ AUSDRUECKLICHE VORGABE (2026-09-09): "Die Anwendung muss das beim
    /// Start laden." Vorher passierte die Anmeldung erst beim ERSTEN Rahmen –
    /// mitten in der Geste, mit einem Dialog ueber dem gerade markierten
    /// Bildschirmausschnitt, und das Menue trug bis dahin die Vorgabeliste
    /// statt der eigenen Fragen.
    ///
    /// Es wird NICHT gewartet: die Anwendung ist sofort benutzbar, und wer die
    /// Anmeldung wegklickt, wird beim ersten Rahmen erneut gefragt (der Weg
    /// ueber `SicherstellenAngemeldetAsync` bleibt unveraendert). Ein
    /// blockierender Start waere bei einem Autostart-Eintrag genau das
    /// Verhalten, das niemand will.
    /// </summary>
    /// <summary>Mit den im Einstellungsdialog eingegebenen Daten anmelden.
    ///
    /// Danach werden Sitzung und Fragen gemerkt – derselbe Weg wie nach der
    /// Anmeldemaske, nur ohne zweites Fenster.
    /// </summary>
    private async Task AnmeldenMitKennwortAsync(string benutzer, string kennwort)
    {
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(2));
            try
            {
                await _client.AnmeldenAsync(benutzer, kennwort, string.Empty, cts.Token)
                    .ConfigureAwait(true);
            }
            catch (TotpNoetigException)
            {
                // Den Einmal-Code kann nur die Oberflaeche erfragen.
                (_, _, string code) = FrageAnmeldung(_settings, totpNoetig: true,
                                                        benutzer: benutzer);
                if (code.Length == 0) { return; }
                await _client.AnmeldenAsync(benutzer, kennwort, code, cts.Token)
                    .ConfigureAwait(true);
            }
            ConfigStore.SaveToken(_client.Token);
            await FragenNachladenAsync().ConfigureAwait(true);
            _trayIcon.ShowBalloonTip(3000, "AI Mouse", Texte.Angemeldet, ToolTipIcon.Info);
        }
        catch (Exception ex)
        {
            // Der Grund gehoert dem Benutzer: er hat gerade Zugangsdaten
            // eingegeben und muss wissen, ob sie stimmen.
            ShowTrayError(ex.Message);
        }
    }

    private async Task StartAnmeldungAsync()
    {
        try
        {
            // Ohne Serveradresse waere die Anmeldemaske eine Sackgasse – dann
            // gehoert zuerst der Einstellungsdialog geoeffnet, und das
            // entscheidet der Benutzer selbst.
            // ⚠ BEIM ERSTEN START FUEHRT DER WEG IN DIE EINSTELLUNGEN, nicht in
            // eine eigene Anmeldemaske (Vorgabe 2026-09-09, zweite
            // Aufforderung). Dort stehen Serveradresse, Benutzer und Kennwort
            // beieinander – und dorthin geht ein Benutzer auch spaeter, wenn
            // sich etwas aendert. Zwei Masken fuer dieselbe Sache waeren zwei
            // Orte, an denen man suchen muss.
            if (!ConfigStore.Eingerichtet())
            {
                ShowSettings();
                return;
            }

            // ⚠ BEIM START WIRD NICHT NACH DEM KENNWORT GEFRAGT (2026-09-09
            // gemeldet: „direkt nach dem Start noch so ein Anmeldefenster").
            // Wer die Anwendung startet, will sie im Infobereich haben – nicht
            // ungefragt einen Dialog. Die Anmeldung passiert dort, wo sie
            // gebraucht wird: beim ersten Rahmen.
            //
            // Ist eine Sitzung gemerkt, werden hier nur die Fragen geholt.
            // Ist sie abgelaufen, faellt das beim ersten echten Aufruf auf und
            // `SicherstellenAngemeldetAsync` fragt DANN.
            if (!_client.Angemeldet)
            {
                return;
            }
            await FragenNachladenAsync().ConfigureAwait(true);
        }
        catch (Exception)
        {
            // Bewusst still: ein Fehlerfenster beim Windows-Start waere
            // Stoerung. Der naechste Rahmen fragt erneut und zeigt dann den
            // Grund.
        }
    }

    private ContextMenuStrip BuildTrayMenu()
    {
        var menu = new ContextMenuStrip();

        var settings = new ToolStripMenuItem(Texte.Einstellungen);
        settings.Click += (_, _) => ShowSettings();

        // ⚠ "Edit prompts.json" IST ENTFALLEN. Die Fragen liegen seit dem
        // 2026-09-09 auf dem Server und werden im Portal gepflegt (Kachel
        // "AI Mouse"); ein Menuepunkt, der eine Datei oeffnet, die es nicht
        // mehr gibt, waere die Sorte Text, die einen Benutzer suchen schickt.


        var exit = new ToolStripMenuItem(Texte.Beenden);
        exit.Click += (_, _) => ExitThread();

        menu.Items.AddRange([settings, new ToolStripSeparator(), exit]);
        return menu;
    }

    private async void OnDragCompleted(Rectangle bounds)
    {
        _overlay.EndSelection();

        DiscardPendingCapture();

        if (bounds.Width < ScreenCapture.MinimumEdge || bounds.Height < ScreenCapture.MinimumEdge)
        {
            return;
        }

        // The overlay window is hidden but the desktop underneath has not necessarily
        // repainted yet — capturing immediately would bake the dimming into the image.
        await Task.Delay(OverlayRepaintDelayMs).ConfigureAwait(true);

        try
        {
            _pendingCapture = ScreenCapture.Capture(bounds);
        }
        catch (Exception ex)
        {
            ShowTrayError($"Screen capture failed: {ex.Message}");
            return;
        }

        if (_pendingCapture is null)
        {
            return;
        }

        _promptChosen = false;

        NativeMethods.SetForegroundWindow(_owner.Handle);
        _promptMenu.Show(Cursor.Position);
    }

    private void OnReplayFailed(string message)
    {
        DateTime now = DateTime.UtcNow;

        if (now - _lastReplayWarningUtc < TimeSpan.FromSeconds(30))
        {
            return;
        }

        _lastReplayWarningUtc = now;
        ShowTrayError(message);
    }

    private void OnPromptMenuClosed(object? sender, ToolStripDropDownClosedEventArgs e)
    {
        // Item handlers run after this event, so the capture may only be released
        // once we know nothing claimed it.
        BeginInvokeOnOwner(() =>
        {
            if (!_promptChosen)
            {
                DiscardPendingCapture();
            }
        });
    }

    private async void OnPromptItemClicked(object? sender, EventArgs e)
    {
        if (sender is not ToolStripMenuItem { Tag: PromptItem prompt })
        {
            return;
        }

        Bitmap? capture = TakePendingCapture();
        if (capture is null)
        {
            return;
        }

        var cts = new CancellationTokenSource();
        var window = new ResultWindow(prompt.Title, cts);
        window.PositionNear(Cursor.Position);
        window.Show();

        try
        {
            string dataUri;
            using (capture)
            {
                dataUri = ScreenCapture.ToDataUri(capture);
            }

            // Anmelden, falls noch keine Sitzung steht. Das Fenster steht
            // dabei schon offen und zeigt den Wartezustand – ohne das saehe
            // der Benutzer nach dem Aufziehen des Rahmens erst einmal nichts.
            if (!_client.Angemeldet && !await SicherstellenAngemeldetAsync(cts.Token).ConfigureAwait(true))
            {
                if (!window.IsDisposed) { window.ShowError(Texte.AnmeldungFehlt); }
                return;
            }

            var bereiche = new List<string>();
            string answer = await _client.AnalysierenAsync(
                prompt.Prompt, dataUri, bereiche, cts.Token).ConfigureAwait(true);

            // WAS DER LAUF DURFTE, gehoert zur Antwort. Ohne diese Zeile ist
            // eine Antwort mit nachgeschlagenem Hintergrund von einer ohne
            // nicht zu unterscheiden - und genau das muss ein Mensch wissen,
            // der den Text gleich weiterverwendet.
            if (bereiche.Count > 0)
            {
                answer += "\n\n— " + Texte.Nachgeschlagen + string.Join(", ", bereiche);
            }

            if (!window.IsDisposed)
            {
                window.ShowAnswer(answer, _settings.CopyResultToClipboard);
            }
        }
        catch (OperationCanceledException)
        {
            // Window closed while the request was running.
        }
        catch (AnmeldungNoetigException)
        {
            // Das Token ist abgelaufen. EINMAL neu anmelden und den Lauf
            // wiederholen - eine Fehlermeldung waere hier eine Zumutung: der
            // Benutzer hat den Rahmen bereits aufgezogen, und die Sitzung
            // laeuft im Hintergrund ab, ohne dass er etwas falsch gemacht hat.
            try
            {
                if (await SicherstellenAngemeldetAsync(cts.Token).ConfigureAwait(true))
                {
                    var bereiche2 = new List<string>();
                    string answer2 = await _client.AnalysierenAsync(
                        prompt.Prompt, ScreenCapture.ToDataUri(capture), bereiche2, cts.Token)
                        .ConfigureAwait(true);
                    if (!window.IsDisposed) { window.ShowAnswer(answer2, _settings.CopyResultToClipboard); }
                }
                else if (!window.IsDisposed)
                {
                    window.ShowError(Texte.AnmeldungFehlt);
                }
            }
            catch (Exception zweit)
            {
                if (!window.IsDisposed) { window.ShowError(zweit.Message); }
            }
        }
        catch (Exception ex) when (ex is VisionException or IOException)
        {
            if (!window.IsDisposed)
            {
                window.ShowError(ex.Message);
            }
        }
        catch (Exception ex)
        {
            if (!window.IsDisposed)
            {
                window.ShowError($"{ex.GetType().Name}: {ex.Message}");
            }
        }
    }

    private void OnCopyImageClicked(object? sender, EventArgs e)
    {
        using Bitmap? capture = TakePendingCapture();
        if (capture is null)
        {
            return;
        }

        try
        {
            Clipboard.SetImage(capture);
        }
        catch (Exception ex)
        {
            ShowTrayError($"Clipboard is busy: {ex.Message}");
        }
    }

    private void OnSaveImageClicked(object? sender, EventArgs e)
    {
        using Bitmap? capture = TakePendingCapture();
        if (capture is null)
        {
            return;
        }

        using var dialog = new SaveFileDialog
        {
            Filter = "PNG image|*.png",
            FileName = $"ai-mouse-{DateTime.Now:yyyyMMdd-HHmmss}.png",
            InitialDirectory = ConfigStore.BaseDirectory,
        };

        if (dialog.ShowDialog(_owner) != DialogResult.OK)
        {
            return;
        }

        try
        {
            File.WriteAllBytes(dialog.FileName, ScreenCapture.ToPng(capture));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            ShowTrayError($"Could not save the image: {ex.Message}");
        }
    }

    /// <summary>Hands ownership of the pending capture to the caller.</summary>
    private Bitmap? TakePendingCapture()
    {
        _promptChosen = true;
        Bitmap? capture = _pendingCapture;
        _pendingCapture = null;
        return capture;
    }

    private void DiscardPendingCapture()
    {
        _pendingCapture?.Dispose();
        _pendingCapture = null;
    }

    private void ShowSettings()
    {
        if (_settingsWindow is { IsDisposed: false })
        {
            _settingsWindow.Activate();
            return;
        }

        using var dialog = new SettingsWindow(_settings, TestConnectionAsync);
        _settingsWindow = dialog;

        // The popup that launched this has no foreground window of its own.
        NativeMethods.SetForegroundWindow(_owner.Handle);

        try
        {
            if (dialog.ShowDialog(_owner) != DialogResult.OK)
            {
                return;
            }

            if (ConfigStore.SaveSettings(dialog.Result) is { } error)
            {
                ShowTrayError(error);
                return;
            }

            ApplySettings(dialog.Result);
            _trayIcon.ShowBalloonTip(3000, "AI Mouse", Texte.Gespeichert, ToolTipIcon.Info);

            // ⚠ MIT KENNWORT WIRD ANGEMELDET (Vorgabe 2026-09-09: die
            // Zugangsdaten gehoeren in diesen Dialog). LEER heisst
            // ausdruecklich „nicht anmelden" – sonst wuerde jedes Speichern
            // einer Kleinigkeit die Sitzung wegwerfen.
            //
            // Nicht abgewartet: der Dialog soll sich schliessen, nicht
            // sekundenlang stehen bleiben. Das Ergebnis meldet die Anwendung
            // ueber die Sprechblase.
            if (dialog.Kennwort.Length > 0)
            {
                _ = AnmeldenMitKennwortAsync(dialog.Result.Benutzer, dialog.Kennwort);
            }
        }
        finally
        {
            _settingsWindow = null;
        }
    }

    /// <summary>
    /// Exercises the exact path a real capture takes — same endpoint, same model, same
    /// multimodal payload shape — so a green result means captures will work, not merely
    /// that the port is open.
    /// </summary>
    private async Task<string> TestConnectionAsync(AppSettings settings, string benutzer,
                                                   string kennwort, CancellationToken cancellationToken)
    {
        // ⚠ WER SICH HIER ANMELDET, IST DANACH ANGEMELDET. Eine erste Fassung
        // benutzte IMMER einen Wegwerf-Client (`using var`), und dessen Token
        // starb mit ihm: der Benutzer gab Kennwort und Einmal-Code ein, bekam
        // "Verbindung steht" – und wurde beim naechsten Rahmen erneut gefragt
        // (gemeldet am 2026-09-09).
        //
        // Getestet wird die EINGETIPPTE Adresse. Stimmt sie mit der laufenden
        // ueberein, ist die Sitzung auch fuer den echten Client gueltig und
        // wird uebernommen. Bei einer ANDEREN Adresse bleibt es beim
        // Wegwerf-Client – das Token gehoert dort einem anderen Server.
        bool gleicheAdresse = string.Equals(
            EndpointResolver.Basis(settings.Endpoint),
            EndpointResolver.Basis(_settings.Endpoint),
            StringComparison.OrdinalIgnoreCase);

        // ⚠ DIE EINGETIPPTEN DATEN NEHMEN, NICHT NEU FRAGEN (2026-09-09
        // gemeldet). Sie stehen im Dialog, aus dem dieser Test gestartet
        // wurde – ein zweites Fenster daneben ist eine Zumutung.
        //
        // Ohne Kennwort wird NICHT gefragt: dann ist der Test die Probe, ob
        // die LAUFENDE Sitzung noch traegt. Das ist der haeufigere Fall (man
        // aendert eine Kleinigkeit und drueckt "Verbindung testen").
        string totp = string.Empty;
        if (benutzer.Length == 0)
        {
            throw new VisionException(Texte.AnmeldungFehlt);
        }
        if (kennwort.Length == 0)
        {
            if (!gleicheAdresse || !_client.Angemeldet)
            {
                // Bei fremder Adresse oder ohne Sitzung gibt es nichts zu
                // pruefen – und raten waere schlechter als eine klare Absage.
                throw new VisionException(Texte.KennwortFehlt);
            }
            await _client.FragenAsync(cancellationToken).ConfigureAwait(true);
            return Texte.VerbindungOk;
        }

        // try/finally, damit der Client auch bei einem Anmeldefehler freigegeben
        // wird – der Fehler fliegt bewusst weiter, der Dialog zeigt ihn an.
        var probeClient = new JarvisClient(settings);
        try
        {
            try
            {
                await probeClient.AnmeldenAsync(benutzer, kennwort, totp, cancellationToken)
                    .ConfigureAwait(true);
            }
            catch (TotpNoetigException)
            {
                (_, _, string code) = FrageAnmeldung(settings, totpNoetig: true, benutzer: benutzer);
                await probeClient.AnmeldenAsync(benutzer, kennwort, code, cancellationToken)
                    .ConfigureAwait(true);
            }

            // Die Sitzung uebernehmen und den Benutzernamen merken – sonst war
            // die Anmeldung von eben umsonst.
            if (gleicheAdresse)
            {
                _client.SitzungUebernehmen(probeClient);
                // Die Fragen des Benutzers gleich mitholen: er ist jetzt
                // angemeldet, und beim ersten Rahmen soll SEIN Menue stehen.
                _ = FragenNachladenAsync();
            }
            if (!string.Equals(_settings.Benutzer, benutzer, StringComparison.Ordinal))
            {
                _settings.Benutzer = benutzer;
                try { ConfigStore.SaveSettings(_settings); } catch (Exception) { }
            }
        }
        finally
        {
            probeClient.Dispose();
        }

        // Ein Probebild schicken wir NICHT mehr. Frueher war das noetig, weil
        // die Anwendung selbst Modell und Endpunkt waehlte und ein offener Port
        // nichts ueber die Bildfaehigkeit sagte. Jetzt entscheidet der Server:
        // eine gelungene Anmeldung heisst, dass Adresse, Zertifikat und
        // Freigabe stimmen - und ein echter Modellaufruf kostet hier Tokens
        // fuer eine Frage, die er nicht mehr beantwortet.
        return benutzer;
    }

    /// <summary>A small but non-degenerate image; some servers reject 1×1 payloads.</summary>
    private static Bitmap CreateProbeImage()
    {
        var probe = new Bitmap(64, 64);

        using (Graphics g = Graphics.FromImage(probe))
        {
            g.Clear(Color.White);
            using var brush = new SolidBrush(Color.Black);
            g.FillEllipse(brush, 16, 16, 32, 32);
        }

        return probe;
    }

    /// <summary>Fragt Anmeldedaten ab. Rueckgabe leer = abgebrochen.</summary>
    private (string, string, string) FrageAnmeldung(AppSettings settings,
                                                    bool totpNoetig = false,
                                                    string benutzer = "")
    {
        using var dlg = new LoginWindow(settings, totpNoetig, benutzer);
        return dlg.ShowDialog(_owner) == DialogResult.OK
            ? (dlg.Benutzer, dlg.Kennwort, dlg.Totp)
            : (string.Empty, string.Empty, string.Empty);
    }

    /// <summary>Stellt sicher, dass eine Sitzung steht. <c>false</c> = abgebrochen.
    ///
    /// Der zweistufige Fall (Einmal-Code) wird HIER aufgeloest und nicht im
    /// Client: nur die Oberflaeche kann nachfragen. Der Client sagt mit einem
    /// eigenen Ausnahmetyp, dass ein Code fehlt – eine Fehlermeldung
    /// "Anmeldung fehlgeschlagen" waere an dieser Stelle schlicht falsch.
    ///
    /// Der BENUTZERNAME wird nach einer gelungenen Anmeldung gemerkt, das
    /// Kennwort nie.
    /// </summary>
    private async Task<bool> SicherstellenAngemeldetAsync(CancellationToken ct)
    {
        if (_client.Angemeldet)
        {
            return true;
        }

        // ⚠ IST NOCH GAR NICHTS EINGERICHTET, gehoert der Benutzer in die
        // EINSTELLUNGEN und nicht in diese Maske: dort stehen Adresse,
        // Benutzer und Kennwort beieinander (Vorgabe 2026-09-09). Diese Maske
        // ist der Weg fuer die ABGELAUFENE Sitzung – da ist die Adresse
        // laengst bekannt, und nach ihr zu fragen waere Rauschen.
        if (!ConfigStore.Eingerichtet())
        {
            ShowSettings();
            return _client.Angemeldet;
        }

        // Die Adresse wird hier NICHT abgefragt: sie steht in den
        // Einstellungen. Der vierte Rueckgabewert bleibt deshalb ungenutzt.
        (string benutzer, string kennwort, string totp) = FrageAnmeldung(_settings);
        if (benutzer.Length == 0)
        {
            return false;
        }

        try
        {
            await _client.AnmeldenAsync(benutzer, kennwort, totp, ct).ConfigureAwait(true);
        }
        catch (TotpNoetigException)
        {
            (_, _, string code) = FrageAnmeldung(_settings, totpNoetig: true, benutzer: benutzer);
            if (code.Length == 0)
            {
                return false;
            }
            await _client.AnmeldenAsync(benutzer, kennwort, code, ct).ConfigureAwait(true);
        }

        // ⚠ ERST JETZT SCHREIBEN – nach der GELUNGENEN Anmeldung.
        // Eine Adresse, die nicht funktioniert, darf sich nicht festsetzen:
        // sonst traegt die Registry beim naechsten Start einen Tippfehler,
        // "Eingerichtet()" ist wahr, und die Maske fragt die Adresse nicht mehr
        // ab – der Benutzer kaeme aus der Lage nicht mehr heraus.
        _settings.Benutzer = benutzer;
        try { ConfigStore.SaveSettings(_settings); } catch (Exception) { }

        // Die Sitzung merken. NIE das Kennwort – das Token laeuft ab und ist
        // serverseitig entwertbar (Zwangsabmeldung), ein Kennwort waere beides
        // nicht. DPAPI bindet es an dieses Windows-Konto.
        ConfigStore.SaveToken(_client.Token);

        // ⚠ DIE FRAGEN DES BENUTZERS HOLEN – hier und nicht irgendwo sonst.
        // Sie liegen seit dem 2026-09-09 auf dem Server, und VOR der Anmeldung
        // gibt es sie nicht. Ohne diese Zeile stand im Menue dauerhaft die
        // eingebaute Vorgabeliste, und was jemand im Portal eintrug, tauchte
        // nie auf (gemeldet am 2026-09-09).
        //
        // AWAIT, nicht "fire and forget": der Aufrufer baut unmittelbar danach
        // das Menue bzw. wertet aus. Ein nebenherlaufender Abruf waere ein
        // Wettlauf, den der Benutzer als "die erste Frage fehlt noch" sieht.
        await FragenNachladenAsync().ConfigureAwait(true);
        return true;
    }

    /// <summary>Takes effect on the next capture; nothing needs restarting.</summary>
    private void ApplySettings(AppSettings settings)
    {
        bool adresseNeu = !string.Equals(_settings.Endpoint, settings.Endpoint,
                                         StringComparison.OrdinalIgnoreCase);
        _settings = settings;
        _hook.Threshold = settings.DragThreshold;
        Texte.Anwenden(settings);

        // ⚠ BEI EINER NEUEN ADRESSE MUSS DIE SITZUNG WEG. Das Token gilt fuer
        // den alten Server; es weiterzubenutzen ergaebe einen 401, der wie ein
        // Serverfehler aussieht. Auch das Zeitlimit steckt im HttpClient, also
        // wird er ohnehin neu gebaut.
        JarvisClient alt = _client;
        _client = new JarvisClient(settings);
        // ⚠ DIE SITZUNG WIRD MITGENOMMEN, solange die Adresse dieselbe ist.
        // Eine erste Fassung liess sie fallen ("Preis des neuen Zeitlimits") –
        // das war eine schlechte Abwaegung: JEDES Speichern im
        // Einstellungsdialog, auch ein blosser Sprachwechsel, warf damit die
        // Anmeldung weg, und der naechste Rahmen fragte erneut nach dem
        // Kennwort (gemeldet am 2026-09-09).
        //
        // Bei GEAENDERTER Adresse bleibt sie bewusst weg: das Token gilt fuer
        // den alten Server.
        if (!adresseNeu)
        {
            _client.SitzungUebernehmen(alt);
        }
        else
        {
            // Die gemerkte Sitzung gehoert zum ALTEN Server – sie hier stehen
            // zu lassen hiesse, sie beim naechsten Start gegen den NEUEN zu
            // schicken: ein 401, der wie ein Serverfehler aussieht. Dasselbe
            // gilt fuer die Fragen: sie sind die des alten Kontos.
            ConfigStore.SaveToken(null);
            ConfigStore.SavePrompts([]);
        }
        alt.Dispose();
    }


    private void OpenInEditor(string path, Action createDefault)
    {
        try
        {
            if (!File.Exists(path))
            {
                createDefault();
            }

            Process.Start(new ProcessStartInfo(path) { UseShellExecute = true })?.Dispose();
        }
        catch (Exception ex)
        {
            ShowTrayError($"Could not open {Path.GetFileName(path)}: {ex.Message}");
        }
    }

    /// <summary>Holt die Fragen des angemeldeten Benutzers vom Server.
    ///
    /// Fehlertolerant: schlaegt der Abruf fehl, bleibt die zuletzt geholte
    /// Liste stehen (beim Erststart also die eingebauten). Ein leeres Menue
    /// nach einem Netzhaenger waere der schlechtere Ausgang – die Geste waere
    /// dann ohne jede Wirkung.
    /// </summary>
    private async Task FragenNachladenAsync()
    {
        if (!_client.Angemeldet)
        {
            return;
        }
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            List<PromptItem> neu = await _client.FragenAsync(cts.Token).ConfigureAwait(true);
            if (neu.Count > 0)
            {
                // Merken, damit sie beim naechsten Start sofort dastehen.
                ConfigStore.SavePrompts(neu);
                _prompts = neu;
                BuildPromptMenu();
            }
        }
        catch (Exception)
        {
            // Bewusst still: die vorhandene Liste bleibt gueltig, und ein
            // Fehlerfenster beim Start waere hier reine Stoerung.
        }
    }

    private void ShowTrayError(string message) => _trayIcon.ShowBalloonTip(5000, "AI Mouse", message, ToolTipIcon.Error);

    private void BeginInvokeOnOwner(Action action)
    {
        if (_owner.IsDisposed)
        {
            return;
        }

        _owner.BeginInvoke(action);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _hook.Dispose();
            _client.Dispose();
            DiscardPendingCapture();
            _trayIcon.Visible = false;

            // NotifyIcon does not own the icon it was handed.
            Icon? icon = _trayIcon.Icon;
            _trayIcon.Dispose();
            icon?.Dispose();
            _promptMenu.Dispose();
            _overlay.Dispose();
            _owner.Dispose();
        }

        base.Dispose(disposing);
    }
}

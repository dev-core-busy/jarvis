package main

import (
	"fmt"
	"image/color"
	"net/url"
	"os"
	"path/filepath"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/layout"
	"fyne.io/fyne/v2/storage"
	"fyne.io/fyne/v2/widget"
)

// ── tightVBox: VBox mit 2px Abstand (statt Fyne-Standard ~4px) ───────────────
// Wird verwendet wo Label direkt über dem zugehörigen Control sitzt (Android-Stil).

type tightVBoxLayout struct{ gap float32 }

func (t *tightVBoxLayout) Layout(objects []fyne.CanvasObject, size fyne.Size) {
	y := float32(0)
	for _, o := range objects {
		h := o.MinSize().Height
		o.Move(fyne.NewPos(0, y))
		o.Resize(fyne.NewSize(size.Width, h))
		y += h + t.gap
	}
}

func (t *tightVBoxLayout) MinSize(objects []fyne.CanvasObject) fyne.Size {
	w, h := float32(0), float32(0)
	for i, o := range objects {
		ms := o.MinSize()
		if ms.Width > w {
			w = ms.Width
		}
		if i > 0 {
			h += t.gap
		}
		h += ms.Height
	}
	return fyne.NewSize(w, h)
}

func tightVBox(objects ...fyne.CanvasObject) *fyne.Container {
	return container.New(&tightVBoxLayout{gap: 2}, objects...)
}

// vSpacer erzeugt einen unsichtbaren vertikalen Abstandshalter (in Pixeln).
func vSpacer(h float32) fyne.CanvasObject {
	return container.NewGridWrap(fyne.NewSize(1, h))
}

// ── Wiederverwendbare Layout-Bausteine (analog Android) ──────────────────────

// sectionHeader: Abschnitts-Titel, fett, mit Trennlinie darunter (Android SectionHeader).
// Schriftgröße = Theme-Standard (13) × 1.5 = 20
func sectionHeader(text string) fyne.CanvasObject {
	lbl := canvas.NewText(text, jc.textPrimary)
	lbl.TextStyle = fyne.TextStyle{Bold: true}
	lbl.TextSize = 20
	return tightVBox(lbl, widget.NewSeparator())
}

// settingRow: Label + optionale Beschreibung links, Control rechts (Android SettingRow).
func settingRow(label, description string, control fyne.CanvasObject) fyne.CanvasObject {
	title := widget.NewLabel(label)
	if description == "" {
		return container.NewBorder(nil, nil, nil, control, title)
	}
	desc := widget.NewLabel(description)
	desc.Importance = widget.LowImportance
	return container.NewBorder(nil, nil, nil, control,
		tightVBox(title, desc))
}

// labelAbove: Label direkt über einem Eingabefeld (2px Abstand, Android-Stil).
func labelAbove(text string, field fyne.CanvasObject) fyne.CanvasObject {
	lbl := widget.NewLabel(text)
	return tightVBox(lbl, field)
}

// audioFieldRow: Label (fett) direkt über Dropdown + Test-Button rechts.
func audioFieldRow(label string, sel *widget.Select, testBtn *widget.Button, statusLbl *widget.Label) fyne.CanvasObject {
	lbl := widget.NewLabel(label)
	lbl.TextStyle = fyne.TextStyle{Bold: true}
	return tightVBox(
		lbl,
		container.NewBorder(nil, nil, nil, container.NewHBox(testBtn, statusLbl), sel),
	)
}

// sliderRow: Label + Wert-Anzeige direkt über Slider (2px Abstand).
func sliderRow(label string, min, max, step, initial float64, unit string, onChange func(float64)) (*widget.Slider, fyne.CanvasObject) {
	valLbl := widget.NewLabel(fmt.Sprintf("%.0f %s", initial, unit))
	valLbl.Importance = widget.LowImportance
	slider := widget.NewSlider(min, max)
	slider.Step = step
	slider.Value = initial
	slider.OnChanged = func(v float64) {
		valLbl.SetText(fmt.Sprintf("%.0f %s", v, unit))
		if onChange != nil {
			onChange(v)
		}
	}
	header := container.NewBorder(nil, nil, nil, valLbl, widget.NewLabel(label))
	return slider, tightVBox(header, slider)
}

// showSettingsWindow öffnet Einstellungen als scrollbare Einzelspalte (Android-Stil).
// Singleton: wenn bereits ein Settings-Fenster offen ist, wird es in den Vordergrund gebracht.
func showSettingsWindow(a fyne.App, app *JarvisApp, onSave func()) {
	app.chatMu.Lock()
	if app.settingsWin != nil {
		app.chatMu.Unlock()
		app.settingsWin.RequestFocus()
		return
	}
	app.chatMu.Unlock()

	win := a.NewWindow(t("Jarvis – Einstellungen", "Jarvis – Settings"))
	app.chatMu.Lock()
	app.settingsWin = win
	app.chatMu.Unlock()
	win.SetOnClosed(func() {
		app.chatMu.Lock()
		app.settingsWin = nil
		app.chatMu.Unlock()
	})
	win.SetFixedSize(false)

	// ── VERBINDUNG ────────────────────────────────────────────────────────────
	hostEntry := widget.NewEntry()
	hostEntry.SetText(urlToHost(app.cfg.ServerURL))
	hostEntry.SetPlaceHolder(t("IP oder Hostname  z.B.  191.100.144.1", "IP or hostname  e.g.  191.100.144.1"))

	// Domain-Login-Felder
	domainUserEntry := widget.NewEntry()
	domainUserEntry.SetText(app.cfg.DomainUsername)
	domainUserEntry.SetPlaceHolder(t("Domain\\Benutzername oder user@domain.com", "Domain\\Username or user@domain.com"))
	domainPassEntry := widget.NewPasswordEntry()
	domainPassEntry.SetPlaceHolder(t("Passwort", "Password"))
	domainLoginStatusLbl := widget.NewLabel("")
	if app.cfg.DomainUsername != "" && app.cfg.APIKey != "" {
		domainLoginStatusLbl.SetText(t("✓ Aktive Domain-Sitzung", "✓ Active domain session"))
	}
	domainLoginBtn := widget.NewButton(t("Anmelden", "Login"), nil)
	domainLoginBtn.Importance = widget.HighImportance
	domainLoginBtn.Disable()
	domainPassEntry.OnChanged = func(s string) {
		if s == "" {
			domainLoginBtn.Disable()
		} else {
			domainLoginBtn.Enable()
		}
	}
	domainLoginOk := app.cfg.DomainUsername != "" && app.cfg.APIKey != ""

	keyEntry := widget.NewPasswordEntry()
	keyEntry.SetText(app.cfg.APIKey)
	keyEntry.SetPlaceHolder(t("API-Schlüssel", "API key"))

	domainLoginBtn.OnTapped = func() {
		domainLoginStatusLbl.SetText(t("Anmelden…", "Logging in…"))
		domainLoginBtn.Disable()
		go func() {
			defer domainLoginBtn.Enable()
			svr := serverToURL(hostEntry.Text)
			token, err := doLogin(svr, domainUserEntry.Text, domainPassEntry.Text)
			if err != nil {
				domainLoginStatusLbl.SetText("✗ " + err.Error())
				domainLoginOk = false
				return
			}
			keyEntry.SetText(token)
			domainLoginStatusLbl.SetText(t("✓ Angemeldet!", "✓ Logged in!"))
			domainLoginOk = true
		}()
	}

	connStatusLbl := widget.NewLabel("")
	testBtn := widget.NewButton(t("Verbindung testen", "Test connection"), func() {
		connStatusLbl.SetText(t("Verbinde…", "Connecting…"))
		go func() {
			if err := testConnection(serverToURL(hostEntry.Text), keyEntry.Text); err != nil {
				connStatusLbl.SetText("✗ " + err.Error())
			} else {
				connStatusLbl.SetText(t("✓ Verbunden!", "✓ Connected!"))
			}
		}()
	})
	testBtn.Importance = widget.MediumImportance

	// ── AUDIO ─────────────────────────────────────────────────────────────────
	speakerSel := widget.NewSelect([]string{"Standard"}, nil)
	micSel := widget.NewSelect([]string{"Standard"}, nil)
	speakerIDs := []string{}
	micIDs := []string{}

	if app.audio != nil {
		speakers := app.audio.ListSpeakers()
		spNames := make([]string, len(speakers))
		for i, s := range speakers {
			spNames[i] = s.Name
			speakerIDs = append(speakerIDs, s.ID)
		}
		if len(spNames) > 0 {
			speakerSel.Options = spNames
			if app.cfg.SpeakerName != "" {
				speakerSel.SetSelected(app.cfg.SpeakerName)
			}
		}
		mics := app.audio.ListMics()
		micNames := make([]string, len(mics))
		for i, m := range mics {
			micNames[i] = m.Name
			micIDs = append(micIDs, m.ID)
		}
		if len(micNames) > 0 {
			micSel.Options = micNames
			if app.cfg.MicName != "" {
				micSel.SetSelected(app.cfg.MicName)
			}
		}
	}

	speakerTestLbl := widget.NewLabel("")
	speakerTestBtn := widget.NewButton(t("🔊 Testen", "🔊 Test"), func() {
		speakerTestLbl.SetText("♪")
		go func() { PlayTestTone(); speakerTestLbl.SetText("✓") }()
	})
	speakerTestBtn.Importance = widget.LowImportance

	micTestLbl := widget.NewLabel("")
	micTestBtn := widget.NewButton(t("🎤 Testen", "🎤 Test"), func() {
		micTestLbl.SetText("3s…")
		go func() {
			if app.audio == nil {
				micTestLbl.SetText("✗ N/A")
				return
			}
			maxRMS, got, err := app.audio.TestMicLevel(3)
			if err != nil {
				micTestLbl.SetText("✗ " + err.Error())
			} else if !got {
				micTestLbl.SetText(t("✗ Kein Signal!", "✗ No signal!"))
			} else {
				micTestLbl.SetText(fmt.Sprintf("✓ %.0f", maxRMS))
			}
		}()
	})
	micTestBtn.Importance = widget.LowImportance

	voiceIDList := []string{""}
	voiceSel := widget.NewSelect([]string{t("Standard (Windows SAPI)", "Default (Windows SAPI)")}, nil)
	voiceSel.SetSelected(t("Standard (Windows SAPI)", "Default (Windows SAPI)"))

	restoreVoiceSel := func() {
		if app.cfg.TTSVoice == "" {
			voiceSel.SetSelected(t("Standard (Windows SAPI)", "Default (Windows SAPI)"))
			return
		}
		for i, id := range voiceIDList {
			if id == app.cfg.TTSVoice && i < len(voiceSel.Options) {
				voiceSel.SetSelected(voiceSel.Options[i])
				return
			}
		}
	}

	sapiVoices := ListTTSVoices()
	{
		names := []string{t("Standard (Windows SAPI)", "Default (Windows SAPI)")}
		ids := []string{""}
		for _, v := range sapiVoices {
			names = append(names, "💻 "+v)
			ids = append(ids, "sapi:"+v)
		}
		voiceIDList = ids
		voiceSel.Options = names
		restoreVoiceSel()
	}
	go func() {
		bkNames, bkIDs := FetchBackendVoices(app.cfg.ServerURL, app.cfg.APIKey)
		if len(bkNames) == 0 {
			return
		}
		names := []string{t("Standard (Windows SAPI)", "Default (Windows SAPI)")}
		ids := []string{""}
		for i, n := range bkNames {
			names = append(names, "☁ "+n)
			ids = append(ids, bkIDs[i])
		}
		for _, v := range sapiVoices {
			names = append(names, "💻 "+v)
			ids = append(ids, "sapi:"+v)
		}
		voiceIDList = ids
		voiceSel.Options = names
		voiceSel.Refresh()
		restoreVoiceSel()
	}()

	voiceTestLbl := widget.NewLabel("")
	voiceTestBtn := widget.NewButton(t("🔊 Testen", "🔊 Test"), func() {
		voiceTestLbl.SetText(t("Spreche…", "Speaking…"))
		go func() {
			selIdx := -1
			for i, n := range voiceSel.Options {
				if n == voiceSel.Selected {
					selIdx = i
					break
				}
			}
			voiceID := ""
			if selIdx > 0 && selIdx < len(voiceIDList) {
				voiceID = voiceIDList[selIdx]
			}
			PlayTestVoice(voiceID)
			voiceTestLbl.SetText("✓")
		}()
	})
	voiceTestBtn.Importance = widget.LowImportance

	// ── HINTERGRUND ───────────────────────────────────────────────────────────
	// Dynamischer Bereich: wird je nach Typ-Auswahl neu befüllt
	bgExtraBox := container.NewVBox()

	bgType := app.cfg.BackgroundType
	if bgType == "" {
		bgType = "gradient"
	}
	bgColorIdx := app.cfg.BackgroundColor
	bgImagePath := app.cfg.BackgroundImagePath
	bgAlpha := app.cfg.BackgroundAlpha
	if bgAlpha == 0 {
		bgAlpha = 0.5
	}
	if bgImagePath == "" {
		bgImagePath = BG_DEFAULT_URI
	}

	// Farbauswahl-Dropdown (für Typ "color")
	bgNames := BgColorNames()
	colorSel := widget.NewSelect(bgNames, func(s string) {
		for i, n := range bgNames {
			if n == s {
				bgColorIdx = i
				break
			}
		}
	})
	if bgColorIdx >= 0 && bgColorIdx < len(bgNames) {
		colorSel.SetSelected(bgNames[bgColorIdx])
	}

	// Foto-Widgets (für Typ "photo")
	imagePathLbl := widget.NewLabel("")
	imagePathLbl.Importance = widget.LowImportance

	// "Standard"-Button – setzt zurück auf eingebettetes Jarvis-Bild
	var imageResetBtn *widget.Button
	var imagePickBtn *widget.Button

	refreshImageWidgets := func() {
		if bgImagePath == BG_DEFAULT_URI || bgImagePath == "" {
			imagePathLbl.SetText(t("Jarvis Standard-Bild", "Jarvis default image"))
			if imageResetBtn != nil {
				imageResetBtn.Hide()
			}
		} else {
			imagePathLbl.SetText(bgImagePath)
			if imageResetBtn != nil {
				imageResetBtn.Show()
			}
		}
	}

	imageResetBtn = widget.NewButton(t("Standard", "Default"), func() {
		bgImagePath = BG_DEFAULT_URI
		refreshImageWidgets()
	})
	imageResetBtn.Importance = widget.LowImportance

	imagePickBtn = widget.NewButton(t("📂 Foto auswählen", "📂 Choose photo"), func() {
		fd := dialog.NewFileOpen(func(reader fyne.URIReadCloser, err error) {
			if err != nil || reader == nil {
				return
			}
			bgImagePath = reader.URI().Path()
			reader.Close()
			refreshImageWidgets()
		}, win)
		fd.SetFilter(storage.NewExtensionFileFilter([]string{".jpg", ".jpeg", ".png", ".bmp"}))
		fd.Show()
	})
	imagePickBtn.Importance = widget.MediumImportance

	refreshImageWidgets() // initialen Zustand setzen

	alphaSlider, alphaRow := sliderRow(t("Helligkeit", "Brightness"), 10, 100, 5, float64(bgAlpha*100), "%",
		func(v float64) { bgAlpha = float32(v / 100) })

	// updateBgExtra: befüllt bgExtraBox je nach gewähltem Hintergrundtyp
	updateBgExtra := func(bgT string) {
		bgExtraBox.Objects = nil
		switch bgT {
		case "color":
			bgExtraBox.Objects = []fyne.CanvasObject{
				labelAbove(t("Hintergrundfarbe", "Background color"), colorSel),
			}
		case "photo":
			bgExtraBox.Objects = []fyne.CanvasObject{
				container.NewHBox(imagePickBtn, imageResetBtn),
				imagePathLbl,
				alphaRow,
			}
			alphaSlider.Value = float64(bgAlpha * 100)
			alphaSlider.Refresh()
			refreshImageWidgets()
		}
		bgExtraBox.Refresh()
	}

	bgLabelColor := t("Farbe", "Color")
	bgLabelPhoto := t("Foto", "Photo")
	bgTypeRadio := widget.NewRadioGroup([]string{"Gradient", bgLabelColor, bgLabelPhoto}, func(s string) {
		switch s {
		case bgLabelColor:
			bgType = "color"
		case bgLabelPhoto:
			bgType = "photo"
		default:
			bgType = "gradient"
		}
		updateBgExtra(bgType)
	})
	bgTypeRadio.Horizontal = true
	switch bgType {
	case "color":
		bgTypeRadio.SetSelected(bgLabelColor)
	case "photo":
		bgTypeRadio.SetSelected(bgLabelPhoto)
	default:
		bgTypeRadio.SetSelected("Gradient")
	}
	updateBgExtra(bgType)

	// ── SPRACHSTEUERUNG ───────────────────────────────────────────────────────
	autoSendCheck := widget.NewCheck("", nil)
	autoSendCheck.SetChecked(app.cfg.AutoSendVoice)

	wakeCheck := widget.NewCheck("", nil)
	wakeCheck.SetChecked(app.cfg.WakeWordEnabled)

	wakeEntry := widget.NewEntry()
	wakeEntry.SetText(app.cfg.WakeWord)
	wakeEntry.SetPlaceHolder(t("z.B. hallo jarvis", "e.g. hello jarvis"))

	silenceVal := float64(app.cfg.SilenceMs)
	minSpeechVal := float64(app.cfg.MinSpeechMs)
	vadVal := float64(app.cfg.VADThreshold)

	silenceSlider, silenceRow := sliderRow(
		t("Sprech-Pause", "Speech pause"), 300, 3000, 100, silenceVal, "ms",
		func(v float64) { silenceVal = v })
	minSpeechSlider, minSpeechRow := sliderRow(
		t("Mindest-Sprechzeit", "Min. speech length"), 100, 1000, 50, minSpeechVal, "ms",
		func(v float64) { minSpeechVal = v })
	vadSlider, vadRow := sliderRow(
		t("Mikrofon-Schwellwert (VAD)", "Mic threshold (VAD)"), 0, 500, 10, vadVal, "",
		func(v float64) { vadVal = v })

	wakeFormBox := container.NewVBox(
		labelAbove(t("Aktivierungswort", "Wake word"), wakeEntry),
		vSpacer(8),
		silenceRow,
		vSpacer(8),
		minSpeechRow,
		vSpacer(8),
		vadRow,
	)

	setWakeFormEnabled := func(enabled bool) {
		if enabled {
			wakeEntry.Enable()
			silenceSlider.Enable()
			minSpeechSlider.Enable()
			vadSlider.Enable()
		} else {
			wakeEntry.Disable()
			silenceSlider.Disable()
			minSpeechSlider.Disable()
			vadSlider.Disable()
		}
	}
	setWakeFormEnabled(app.cfg.WakeWordEnabled)
	wakeCheck.OnChanged = setWakeFormEnabled

	// ── SPRACHE / LANGUAGE ────────────────────────────────────────────────────
	uiLang := app.cfg.UILang
	if uiLang == "" {
		uiLang = "de"
	}
	langRadio := widget.NewRadioGroup([]string{"Deutsch", "English"}, func(s string) {
		if s == "English" {
			uiLang = "en"
		} else {
			uiLang = "de"
		}
	})
	langRadio.Horizontal = true
	if uiLang == "en" {
		langRadio.SetSelected("English")
	} else {
		langRadio.SetSelected("Deutsch")
	}

	// ── ANZEIGE ───────────────────────────────────────────────────────────────
	dialogCheck := widget.NewCheck("", nil)
	dialogCheck.SetChecked(app.cfg.DialogMode)

	avatarCheck := widget.NewCheck("", nil)
	avatarCheck.SetChecked(app.cfg.AvatarVisible)

	debugCheck := widget.NewCheck("", nil)
	debugCheck.SetChecked(app.debugMode)

	// ── LAYOUT: scrollbare Einzelspalte (Android-Stil) ────────────────────────
	content := container.NewVBox(
		// — Verbindung —
		sectionHeader(t("Verbindung", "Connection")),
		labelAbove("Server-URL", hostEntry),
		vSpacer(2),
		func() fyne.CanvasObject {
			l := widget.NewLabel(t("Tailscale- oder lokale Adresse des Jarvis-Servers", "Tailscale or local address of the Jarvis server"))
			l.Importance = widget.LowImportance
			return l
		}(),
		vSpacer(8),
		// — Domain-Anmeldung —
		sectionHeader(t("Domain-Anmeldung (optional)", "Domain Login (optional)")),
		labelAbove(t("Benutzername", "Username"), domainUserEntry),
		func() fyne.CanvasObject {
			l := widget.NewLabel(t("Format: DOMAIN\\Benutzername  oder  benutzername@domain.com", "Format: DOMAIN\\Username  or  user@domain.com"))
			l.Importance = widget.LowImportance
			return l
		}(),
		vSpacer(4),
		labelAbove(t("Passwort", "Password"), domainPassEntry),
		vSpacer(4),
		container.NewHBox(domainLoginBtn, domainLoginStatusLbl),
		vSpacer(8),
		func() fyne.CanvasObject {
			l := widget.NewLabel(t("── oder API-Key direkt eingeben ──", "── or enter API key directly ──"))
			l.Importance = widget.LowImportance
			return l
		}(),
		labelAbove(t("Agent API-Key", "Agent API Key"), keyEntry),
		vSpacer(2),
		func() fyne.CanvasObject {
			l := widget.NewLabel(t("Einstellungen → Agent API-Key in der Jarvis Web-UI", "Settings → Agent API Key in the Jarvis Web UI"))
			l.Importance = widget.LowImportance
			return l
		}(),
		vSpacer(4),
		container.NewHBox(testBtn, connStatusLbl),

		widget.NewSeparator(),

		// — Audio —
		sectionHeader("Audio"),
		audioFieldRow(t("Lautsprecher", "Speaker"), speakerSel, speakerTestBtn, speakerTestLbl),
		vSpacer(8),
		audioFieldRow(t("Mikrofon", "Microphone"), micSel, micTestBtn, micTestLbl),
		vSpacer(8),
		audioFieldRow(t("Antwortstimme", "Response voice"), voiceSel, voiceTestBtn, voiceTestLbl),

		widget.NewSeparator(),

		// — Hintergrund —
		sectionHeader(t("Hintergrund", "Background")),
		bgTypeRadio,
		bgExtraBox,

		widget.NewSeparator(),

		// — Spracheingabe —
		sectionHeader(t("Spracheingabe", "Voice Input")),
		settingRow(t("Automatisch senden", "Auto-send"),
			t("Transkribierter Text wird nach der Sprech-Pause direkt gesendet",
				"Transcribed text is sent automatically after the speech pause"),
			autoSendCheck),

		widget.NewSeparator(),

		// — Spracherkennung (Whisper) —
		sectionHeader(t("Spracherkennung (Whisper)", "Speech Recognition (Whisper)")),
		buildWhisperSection(win, app),

		widget.NewSeparator(),

		// — Dialogmodus —
		sectionHeader(t("Dialogmodus", "Dialog Mode")),
		settingRow(t("Aktivierungswort verwenden", "Use wake word"),
			t("Mikrofon hört passiv zu bis das Aktivierungswort erkannt wird",
				"Microphone listens passively until the wake word is detected"),
			wakeCheck),
		vSpacer(8),
		wakeFormBox,

		widget.NewSeparator(),

		// — Textmodus —
		sectionHeader(t("Textmodus", "Text Mode")),
		settingRow(t("Avatar anzeigen", "Show avatar"),
			t("Iron Man Avatar im Chat-Fenster einblenden", "Show Iron Man avatar in the chat window"),
			avatarCheck),

		widget.NewSeparator(),

		// — Sprache / Language —
		sectionHeader("Sprache / Language"),
		langRadio,
		func() fyne.CanvasObject {
			l := widget.NewLabel(t("Bestimmt die Sprache der KI-Antworten", "Sets the language for AI responses"))
			l.Importance = widget.LowImportance
			return l
		}(),

		widget.NewSeparator(),

		// — Anzeige —
		sectionHeader(t("Anzeige", "Display")),
		settingRow(t("Dialog-Modus", "Dialog mode"),
			t("Avatar-Fenster mit Sprachdialog statt Chat-Fenster", "Avatar window with voice dialog instead of chat window"),
			dialogCheck),
		vSpacer(8),
		settingRow(t("Debug-Modus", "Debug mode"),
			t("Nachrichten als Volltext, fett/weiß — zeigt alle LLM-Details", "Messages as full text, bold/white — shows all LLM details"),
			debugCheck),

		widget.NewSeparator(),

		// — Info & Version —
		buildInfoCard(),
	)

	scroll := container.NewVScroll(content)

	// Speichern-Button volle Breite (Android-Stil)
	saveBtn := widget.NewButton(t("Speichern", "Save"), func() {
		if hostEntry.Text == "" {
			dialog.ShowError(fmt.Errorf(t("Bitte Server-URL eingeben", "Please enter a server URL")), win)
			return
		}
		if keyEntry.Text == "" && !domainLoginOk {
			dialog.ShowError(fmt.Errorf(t("Bitte entweder API-Key eingeben oder zuerst via Domain-Anmeldung anmelden",
				"Please enter an API key or login via domain authentication first")), win)
			return
		}
		app.cfg.ServerURL = serverToURL(hostEntry.Text)
		app.cfg.APIKey = keyEntry.Text
		app.cfg.DomainUsername = domainUserEntry.Text

		selSp := speakerSel.Selected
		app.cfg.SpeakerName = selSp
		for i, name := range speakerSel.Options {
			if name == selSp && i < len(speakerIDs) {
				app.cfg.SpeakerID = speakerIDs[i]
				break
			}
		}
		selMic := micSel.Selected
		app.cfg.MicName = selMic
		for i, name := range micSel.Options {
			if name == selMic && i < len(micIDs) {
				app.cfg.MicID = micIDs[i]
				break
			}
		}
		{
			selIdx := -1
			for i, n := range voiceSel.Options {
				if n == voiceSel.Selected {
					selIdx = i
					break
				}
			}
			if selIdx > 0 && selIdx < len(voiceIDList) {
				app.cfg.TTSVoice = voiceIDList[selIdx]
			} else {
				app.cfg.TTSVoice = ""
			}
			SetTTSVoice(app.cfg.TTSVoice)
			SetTTSServer(app.cfg.ServerURL, app.cfg.APIKey)
		}

		// Hintergrund
		app.cfg.BackgroundType = bgType
		app.cfg.BackgroundColor = bgColorIdx
		app.cfg.BackgroundImagePath = bgImagePath
		app.cfg.BackgroundAlpha = bgAlpha

		// Sprache / Language
		app.cfg.AutoSendVoice = autoSendCheck.Checked
		app.cfg.UILang = uiLang
		appLang = uiLang // i18n: sofort wirksam für neue Fenster

		// Wake-Word
		app.cfg.WakeWordEnabled = wakeCheck.Checked
		app.cfg.WakeWord = wakeEntry.Text
		app.cfg.SilenceMs = int(silenceVal)
		app.cfg.MinSpeechMs = int(minSpeechVal)
		app.cfg.VADThreshold = int(vadVal)

		app.cfg.AvatarVisible = avatarCheck.Checked
		app.chat.SetAvatarVisible(app.cfg.AvatarVisible)

		// Anzeige
		if debugCheck.Checked != app.debugMode {
			app.toggleDebug()
		}
		if dialogCheck.Checked != app.cfg.DialogMode {
			if dialogCheck.Checked {
				go app.switchToDialogMode()
			} else {
				go app.switchToTextMode()
			}
		}

		_ = app.cfg.Save()
		win.Close()
		if onSave != nil {
			onSave()
		}
	})
	saveBtn.Importance = widget.HighImportance

	// Leicht hellerer Hintergrund (#1E1E35) damit Dropdowns (#1A1A2E) sich abgrenzen
	settingsBg := canvas.NewRectangle(color.RGBA{0x1E, 0x1E, 0x35, 0xFF})
	win.SetContent(container.NewStack(
		settingsBg,
		container.NewBorder(nil, container.NewPadded(saveBtn), nil, nil, scroll),
	))
	win.Resize(fyne.NewSize(440, 620))
	win.Show()
}

// buildWhisperSection zeigt Whisper-Binary-Status und Modell-Auswahl mit Download.
func buildWhisperSection(win fyne.Window, app *JarvisApp) fyne.CanvasObject {
	// ── Binary-Status ──────────────────────────────────────────────────
	exeLbl := widget.NewLabel("")
	hasExe, _ := WhisperStatus()
	if hasExe {
		exeLbl.SetText("✓  whisper-cli.exe")
		exeLbl.Importance = widget.SuccessImportance
	} else {
		exeLbl.SetText("✗  whisper-cli.exe  (fehlt)")
		exeLbl.Importance = widget.DangerImportance
	}

	exeDlBtn := widget.NewButton(t("whisper-cli.exe herunterladen", "Download whisper-cli.exe"), nil)
	exeDlBtn.Importance = widget.HighImportance
	exeProgress := widget.NewProgressBar()
	exeProgress.Hide()
	exeStatusLbl := widget.NewLabel("")
	exeStatusLbl.Importance = widget.LowImportance
	if hasExe {
		exeDlBtn.Hide()
	}
	exeDlBtn.OnTapped = func() {
		exeDlBtn.Disable()
		exeProgress.Show()
		go func() {
			defer func() {
				exeProgress.Hide()
				h, _ := WhisperStatus()
				if h {
					exeLbl.SetText("✓  whisper-cli.exe")
					exeLbl.Importance = widget.SuccessImportance
					exeLbl.Refresh()
					exeDlBtn.Hide()
				}
				exeDlBtn.Enable()
			}()
			exeStatusLbl.SetText(t("Lade whisper-cli.exe …", "Downloading whisper-cli.exe…"))
			if err := DownloadWhisperExe(func(p float64) { exeProgress.SetValue(p) }); err != nil {
				exeStatusLbl.SetText("✗ " + err.Error())
				return
			}
			exeStatusLbl.SetText(t("✓ whisper-cli.exe bereit", "✓ whisper-cli.exe ready"))
		}()
	}

	// ── Modell-Zeilen ──────────────────────────────────────────────────
	activeName := app.cfg.STTModel
	if activeName == "" {
		// Detect first installed model as active if none configured
		if models := ListSTTModels(); len(models) > 0 {
			activeName = models[0]
		}
	}

	modelRows := container.NewVBox()
	globalProgress := widget.NewProgressBar()
	globalProgress.Hide()
	globalStatusLbl := widget.NewLabel("")
	globalStatusLbl.Importance = widget.LowImportance

	var rebuildModelRows func()
	rebuildModelRows = func() {
		modelRows.Objects = nil
		currentActive := getActiveSTTModel()
		if currentActive == "" {
			currentActive = app.cfg.STTModel
		}

		for _, def := range STTModels {
			def := def // capture
			installed := false
			dir := sttDir()
			if _, err := os.Stat(filepath.Join(dir, def.Filename)); err == nil {
				installed = true
			}

			nameLbl := widget.NewLabel(def.Label)
			noteLbl := widget.NewLabel(def.Note)
			noteLbl.Importance = widget.LowImportance
			noteLbl.TextStyle = fyne.TextStyle{Italic: true}

			var actionBtn *widget.Button
			if installed {
				if def.Filename == currentActive {
					nameLbl.TextStyle = fyne.TextStyle{Bold: true}
					actionBtn = widget.NewButton(t("✓ Aktiv", "✓ Active"), nil)
					actionBtn.Disable()
					actionBtn.Importance = widget.SuccessImportance
				} else {
					actionBtn = widget.NewButton(t("Aktivieren", "Activate"), func() {
						app.cfg.STTModel = def.Filename
						_ = app.cfg.Save()
						SetActiveSTTModel(def.Filename)
						RestartWhisperServer()
						globalStatusLbl.SetText("✓ " + def.Filename + t(" aktiviert – Server neu gestartet", " activated – server restarted"))
						rebuildModelRows()
					})
					actionBtn.Importance = widget.MediumImportance
				}
			} else {
				actionBtn = widget.NewButton(fmt.Sprintf(t("Laden (%d MB)", "Download (%d MB)"), def.SizeMB), func() {
					actionBtn.Disable()
					globalProgress.SetValue(0)
					globalProgress.Show()
					globalStatusLbl.SetText(t("Lade ", "Downloading ") + def.Filename + " …")
					go func() {
						defer func() {
							globalProgress.Hide()
							actionBtn.Enable()
							rebuildModelRows()
						}()
						if err := DownloadSTTModel(def, func(p float64) {
							globalProgress.SetValue(p)
						}); err != nil {
							globalStatusLbl.SetText("✗ " + err.Error())
							return
						}
						// Automatisch aktivieren wenn noch kein Modell aktiv
						if getActiveSTTModel() == "" || app.cfg.STTModel == "" {
							app.cfg.STTModel = def.Filename
							_ = app.cfg.Save()
							SetActiveSTTModel(def.Filename)
							RestartWhisperServer()
						}
						globalStatusLbl.SetText("✓ " + def.Filename + t(" heruntergeladen", " downloaded"))
					}()
				})
				actionBtn.Importance = widget.LowImportance
			}

			row := container.NewBorder(nil, nil,
				container.NewVBox(nameLbl, noteLbl),
				actionBtn,
			)
			modelRows.Add(row)
			modelRows.Add(widget.NewSeparator())
		}
		modelRows.Refresh()
	}

	rebuildModelRows()

	infoLbl := widget.NewLabel(t("Lokale Spracherkennung – keine Verbindung zum Server nötig.", "Local speech recognition – no server connection needed."))
	infoLbl.Importance = widget.LowImportance
	infoLbl.Wrapping = fyne.TextWrapWord

	return container.NewVBox(
		container.NewHBox(exeLbl, exeDlBtn),
		exeProgress,
		exeStatusLbl,
		vSpacer(6),
		modelRows,
		globalProgress,
		globalStatusLbl,
		vSpacer(4),
		infoLbl,
	)
}

// buildInfoCard erstellt die Info-Karte am Ende der Einstellungen (analog Android).
func buildInfoCard() fyne.CanvasObject {
	link, _ := url.Parse("https://jarvis-ai.info")
	hyperlink := widget.NewHyperlink("jarvis-ai.info", link)

	verLbl := widget.NewLabel("v" + AppVersion)
	verLbl.Importance = widget.LowImportance

	infoLbl := widget.NewLabel(t(
		"Verbindet sich über verschlüsselte WebSocket-Verbindung\nmit dem Jarvis-Backend. Mikrofon wird lokal verarbeitet.",
		"Connects via encrypted WebSocket\nto the Jarvis backend. Microphone is processed locally."))
	infoLbl.Importance = widget.LowImportance
	infoLbl.Wrapping = fyne.TextWrapWord

	return container.NewVBox(
		container.NewBorder(nil, nil, nil, verLbl, hyperlink),
		infoLbl,
		layout.NewSpacer(),
	)
}

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

	win := a.NewWindow("Jarvis – Einstellungen")
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
	hostEntry.SetPlaceHolder("IP oder Hostname  z.B.  191.100.144.1")

	// Domain-Login-Felder
	domainUserEntry := widget.NewEntry()
	domainUserEntry.SetText(app.cfg.DomainUsername)
	domainUserEntry.SetPlaceHolder("Domain\\Benutzername oder user@domain.com")
	domainPassEntry := widget.NewPasswordEntry()
	domainPassEntry.SetPlaceHolder("Passwort")
	domainLoginStatusLbl := widget.NewLabel("")
	if app.cfg.DomainUsername != "" && app.cfg.APIKey != "" {
		domainLoginStatusLbl.SetText("✓ Aktive Domain-Sitzung")
	}
	domainLoginBtn := widget.NewButton("Anmelden", nil)
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
	keyEntry.SetPlaceHolder("API-Schlüssel")

	domainLoginBtn.OnTapped = func() {
		domainLoginStatusLbl.SetText("Anmelden…")
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
			domainLoginStatusLbl.SetText("✓ Angemeldet!")
			domainLoginOk = true
		}()
	}

	connStatusLbl := widget.NewLabel("")
	testBtn := widget.NewButton("Verbindung testen", func() {
		connStatusLbl.SetText("Verbinde…")
		go func() {
			if err := testConnection(serverToURL(hostEntry.Text), keyEntry.Text); err != nil {
				connStatusLbl.SetText("✗ " + err.Error())
			} else {
				connStatusLbl.SetText("✓ Verbunden!")
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
	speakerTestBtn := widget.NewButton("🔊 Testen", func() {
		speakerTestLbl.SetText("♪")
		go func() { PlayTestTone(); speakerTestLbl.SetText("✓") }()
	})
	speakerTestBtn.Importance = widget.LowImportance

	micTestLbl := widget.NewLabel("")
	micTestBtn := widget.NewButton("🎤 Testen", func() {
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
				micTestLbl.SetText("✗ Kein Signal!")
			} else {
				micTestLbl.SetText(fmt.Sprintf("✓ %.0f", maxRMS))
			}
		}()
	})
	micTestBtn.Importance = widget.LowImportance

	voiceIDList := []string{""}
	voiceSel := widget.NewSelect([]string{"Standard (Windows SAPI)"}, nil)
	voiceSel.SetSelected("Standard (Windows SAPI)")

	restoreVoiceSel := func() {
		if app.cfg.TTSVoice == "" {
			voiceSel.SetSelected("Standard (Windows SAPI)")
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
		names := []string{"Standard (Windows SAPI)"}
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
		names := []string{"Standard (Windows SAPI)"}
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
	voiceTestBtn := widget.NewButton("🔊 Testen", func() {
		voiceTestLbl.SetText("Spreche…")
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
	colorSel := widget.NewSelect(BgColorNames, func(s string) {
		for i, n := range BgColorNames {
			if n == s {
				bgColorIdx = i
				break
			}
		}
	})
	if bgColorIdx >= 0 && bgColorIdx < len(BgColorNames) {
		colorSel.SetSelected(BgColorNames[bgColorIdx])
	}

	// Foto-Widgets (für Typ "photo")
	imagePathLbl := widget.NewLabel("")
	imagePathLbl.Importance = widget.LowImportance

	// "Standard"-Button – setzt zurück auf eingebettetes Jarvis-Bild
	var imageResetBtn *widget.Button
	var imagePickBtn *widget.Button

	refreshImageWidgets := func() {
		if bgImagePath == BG_DEFAULT_URI || bgImagePath == "" {
			imagePathLbl.SetText("Jarvis Standard-Bild")
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

	imageResetBtn = widget.NewButton("Standard", func() {
		bgImagePath = BG_DEFAULT_URI
		refreshImageWidgets()
	})
	imageResetBtn.Importance = widget.LowImportance

	imagePickBtn = widget.NewButton("📂 Foto auswählen", func() {
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

	alphaSlider, alphaRow := sliderRow("Helligkeit", 10, 100, 5, float64(bgAlpha*100), "%",
		func(v float64) { bgAlpha = float32(v / 100) })

	// updateBgExtra: befüllt bgExtraBox je nach gewähltem Hintergrundtyp
	updateBgExtra := func(t string) {
		bgExtraBox.Objects = nil
		switch t {
		case "color":
			bgExtraBox.Objects = []fyne.CanvasObject{
				labelAbove("Hintergrundfarbe", colorSel),
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

	bgTypeRadio := widget.NewRadioGroup([]string{"Gradient", "Farbe", "Foto"}, func(s string) {
		switch s {
		case "Farbe":
			bgType = "color"
		case "Foto":
			bgType = "photo"
		default:
			bgType = "gradient"
		}
		updateBgExtra(bgType)
	})
	bgTypeRadio.Horizontal = true
	switch bgType {
	case "color":
		bgTypeRadio.SetSelected("Farbe")
	case "photo":
		bgTypeRadio.SetSelected("Foto")
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
	wakeEntry.SetPlaceHolder("z.B. hallo jarvis")

	silenceVal := float64(app.cfg.SilenceMs)
	minSpeechVal := float64(app.cfg.MinSpeechMs)
	vadVal := float64(app.cfg.VADThreshold)

	silenceSlider, silenceRow := sliderRow(
		"Sprech-Pause", 300, 3000, 100, silenceVal, "ms",
		func(v float64) { silenceVal = v })
	minSpeechSlider, minSpeechRow := sliderRow(
		"Mindest-Sprechzeit", 100, 1000, 50, minSpeechVal, "ms",
		func(v float64) { minSpeechVal = v })
	vadSlider, vadRow := sliderRow(
		"Mikrofon-Schwellwert (VAD)", 0, 500, 10, vadVal, "",
		func(v float64) { vadVal = v })

	wakeFormBox := container.NewVBox(
		labelAbove("Aktivierungswort", wakeEntry),
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
		sectionHeader("Verbindung"),
		labelAbove("Server-URL", hostEntry),
		vSpacer(2),
		func() fyne.CanvasObject {
			l := widget.NewLabel("Tailscale- oder lokale Adresse des Jarvis-Servers")
			l.Importance = widget.LowImportance
			return l
		}(),
		vSpacer(8),
		// — Domain-Anmeldung —
		sectionHeader("Domain-Anmeldung (optional)"),
		labelAbove("Benutzername", domainUserEntry),
		func() fyne.CanvasObject {
			l := widget.NewLabel("Format: DOMAIN\\Benutzername  oder  benutzername@domain.com")
			l.Importance = widget.LowImportance
			return l
		}(),
		vSpacer(4),
		labelAbove("Passwort", domainPassEntry),
		vSpacer(4),
		container.NewHBox(domainLoginBtn, domainLoginStatusLbl),
		vSpacer(8),
		func() fyne.CanvasObject {
			l := widget.NewLabel("── oder API-Key direkt eingeben ──")
			l.Importance = widget.LowImportance
			return l
		}(),
		labelAbove("Agent API-Key", keyEntry),
		vSpacer(2),
		func() fyne.CanvasObject {
			l := widget.NewLabel("Einstellungen → Agent API-Key in der Jarvis Web-UI")
			l.Importance = widget.LowImportance
			return l
		}(),
		vSpacer(4),
		container.NewHBox(testBtn, connStatusLbl),

		widget.NewSeparator(),

		// — Audio —
		sectionHeader("Audio"),
		audioFieldRow("Lautsprecher", speakerSel, speakerTestBtn, speakerTestLbl),
		vSpacer(8),
		audioFieldRow("Mikrofon", micSel, micTestBtn, micTestLbl),
		vSpacer(8),
		audioFieldRow("Antwortstimme", voiceSel, voiceTestBtn, voiceTestLbl),

		widget.NewSeparator(),

		// — Hintergrund —
		sectionHeader("Hintergrund"),
		bgTypeRadio,
		bgExtraBox,

		widget.NewSeparator(),

		// — Spracheingabe —
		sectionHeader("Spracheingabe"),
		settingRow("Automatisch senden",
			"Transkribierter Text wird nach der Sprech-Pause direkt gesendet",
			autoSendCheck),

		widget.NewSeparator(),

		// — Spracherkennung (Whisper) —
		sectionHeader("Spracherkennung (Whisper)"),
		buildWhisperSection(win, app),

		widget.NewSeparator(),

		// — Dialogmodus —
		sectionHeader("Dialogmodus"),
		settingRow("Aktivierungswort verwenden",
			"Mikrofon hört passiv zu bis das Aktivierungswort erkannt wird",
			wakeCheck),
		vSpacer(8),
		wakeFormBox,

		widget.NewSeparator(),

		// — Textmodus —
		sectionHeader("Textmodus"),
		settingRow("Avatar anzeigen",
			"Iron Man Avatar im Chat-Fenster einblenden",
			avatarCheck),

		widget.NewSeparator(),

		// — Anzeige —
		sectionHeader("Anzeige"),
		settingRow("Dialog-Modus",
			"Avatar-Fenster mit Sprachdialog statt Chat-Fenster",
			dialogCheck),
		vSpacer(8),
		settingRow("Debug-Modus",
			"Nachrichten als Volltext, fett/weiß — zeigt alle LLM-Details",
			debugCheck),

		widget.NewSeparator(),

		// — Info & Version —
		buildInfoCard(),
	)

	scroll := container.NewVScroll(content)

	// Speichern-Button volle Breite (Android-Stil)
	saveBtn := widget.NewButton("Speichern", func() {
		if hostEntry.Text == "" {
			dialog.ShowError(fmt.Errorf("Bitte Server-URL eingeben"), win)
			return
		}
		if keyEntry.Text == "" && !domainLoginOk {
			dialog.ShowError(fmt.Errorf("Bitte entweder API-Key eingeben oder zuerst via Domain-Anmeldung anmelden"), win)
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

		// Sprache
		app.cfg.AutoSendVoice = autoSendCheck.Checked

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

	exeDlBtn := widget.NewButton("whisper-cli.exe herunterladen", nil)
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
			exeStatusLbl.SetText("Lade whisper-cli.exe …")
			if err := DownloadWhisperExe(func(p float64) { exeProgress.SetValue(p) }); err != nil {
				exeStatusLbl.SetText("✗ " + err.Error())
				return
			}
			exeStatusLbl.SetText("✓ whisper-cli.exe bereit")
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
					actionBtn = widget.NewButton("✓ Aktiv", nil)
					actionBtn.Disable()
					actionBtn.Importance = widget.SuccessImportance
				} else {
					actionBtn = widget.NewButton("Aktivieren", func() {
						app.cfg.STTModel = def.Filename
						_ = app.cfg.Save()
						SetActiveSTTModel(def.Filename)
						RestartWhisperServer()
						globalStatusLbl.SetText("✓ " + def.Filename + " aktiviert – Server neu gestartet")
						rebuildModelRows()
					})
					actionBtn.Importance = widget.MediumImportance
				}
			} else {
				actionBtn = widget.NewButton(fmt.Sprintf("Laden (%d MB)", def.SizeMB), func() {
					actionBtn.Disable()
					globalProgress.SetValue(0)
					globalProgress.Show()
					globalStatusLbl.SetText("Lade " + def.Filename + " …")
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
						globalStatusLbl.SetText("✓ " + def.Filename + " heruntergeladen")
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

	infoLbl := widget.NewLabel("Lokale Spracherkennung – keine Verbindung zum Server nötig.")
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

	infoLbl := widget.NewLabel("Verbindet sich über verschlüsselte WebSocket-Verbindung\nmit dem Jarvis-Backend. Mikrofon wird lokal verarbeitet.")
	infoLbl.Importance = widget.LowImportance
	infoLbl.Wrapping = fyne.TextWrapWord

	return container.NewVBox(
		container.NewBorder(nil, nil, nil, verLbl, hyperlink),
		infoLbl,
		layout.NewSpacer(),
	)
}

package main

import (
	"fmt"
	"strconv"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/widget"
)

// showSettingsWindow öffnet das Einstellungs-Fenster mit Tabs.
func showSettingsWindow(a fyne.App, app *JarvisApp, onSave func()) {
	win := a.NewWindow("Jarvis – Einstellungen")
	win.SetFixedSize(false)

	// ── Tab 1: Verbindung ─────────────────────────────────────────────────────
	hostEntry := widget.NewEntry()
	hostEntry.SetText(urlToHost(app.cfg.ServerURL))
	hostEntry.SetPlaceHolder("IP oder Hostname  z.B.  191.100.144.1")

	keyEntry := widget.NewPasswordEntry()
	keyEntry.SetText(app.cfg.APIKey)
	keyEntry.SetPlaceHolder("API-Schlüssel")

	statusLbl := widget.NewLabel("")
	testBtn := widget.NewButton("Verbindung testen", func() {
		statusLbl.SetText("Verbinde…")
		go func() {
			if err := testConnection(serverToURL(hostEntry.Text), keyEntry.Text); err != nil {
				statusLbl.SetText("✗ " + err.Error())
			} else {
				statusLbl.SetText("✓ Verbindung erfolgreich!")
			}
		}()
	})

	connForm := widget.NewForm(
		widget.NewFormItem("Server-Adresse", hostEntry),
		widget.NewFormItem("API-Key", keyEntry),
	)
	connTab := container.NewVBox(connForm, testBtn, statusLbl)

	// ── Tab 2: Audio-Geräte ───────────────────────────────────────────────────
	speakerSel := widget.NewSelect([]string{"Standard"}, nil)
	micSel := widget.NewSelect([]string{"Standard"}, nil)
	speakerIDs := []string{""}
	micIDs := []string{""}

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
			} else {
				speakerSel.SetSelected("Standard")
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
			} else {
				micSel.SetSelected("Standard")
			}
		}
	}

	// ── Lautsprecher-Test ─────────────────────────────────────────────────────
	speakerTestLbl := widget.NewLabel("")
	speakerTestBtn := widget.NewButton("🔊  Testen", func() {
		speakerTestLbl.SetText("♪")
		go func() {
			PlayTestTone()
			speakerTestLbl.SetText("✓")
		}()
	})
	speakerTestBtn.Importance = widget.MediumImportance

	// ── Mikrofon-Test ─────────────────────────────────────────────────────────
	micTestLbl := widget.NewLabel("")
	micTestBtn := widget.NewButton("🎤  Testen", func() {
		micTestLbl.SetText("Aufnahme 3s…")
		go func() {
			if app.audio == nil {
				micTestLbl.SetText("✗ Audio N/A")
				return
			}
			maxRMS, got, err := app.audio.TestMicLevel(3)
			if err != nil {
				micTestLbl.SetText("✗ " + err.Error())
			} else if !got {
				micTestLbl.SetText("✗ Kein Signal!")
			} else {
				micTestLbl.SetText(fmt.Sprintf("✓ Pegel: %.0f", maxRMS))
			}
		}()
	})
	micTestBtn.Importance = widget.MediumImportance

	// ── TTS-Antwortstimme ─────────────────────────────────────────────────────
	// voiceIDList wird async befüllt; Closure im Save-Handler nutzt es.
	voiceIDList := []string{""}
	voiceSel := widget.NewSelect([]string{"Standard (Windows SAPI)"}, nil)
	voiceSel.SetSelected("Standard (Windows SAPI)")

	// Gespeicherte Stimme vorselektieren sobald Liste geladen
	restoreVoiceSel := func() {
		if app.cfg.TTSVoice == "" {
			voiceSel.SetSelected("Standard (Windows SAPI)")
			return
		}
		for i, id := range voiceIDList {
			if id == app.cfg.TTSVoice {
				if i < len(voiceSel.Options) {
					voiceSel.SetSelected(voiceSel.Options[i])
				}
				return
			}
		}
	}

	// Stimmen laden: zuerst SAPI (sofort), dann Backend-Stimmen (async via Netzwerk)
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

	// Backend-Stimmen asynchron laden und in die Liste einpflegen
	go func() {
		bkNames, bkIDs := FetchBackendVoices(app.cfg.ServerURL, app.cfg.APIKey)
		if len(bkNames) == 0 {
			return
		}
		// Backend-Stimmen zuerst (bessere Qualität), dann SAPI
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
	voiceTestBtn := widget.NewButton("🔊  Stimme testen", func() {
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
	voiceTestBtn.Importance = widget.MediumImportance

	// Layout: je Zeile [Dropdown | Test-Button | Status-Label]
	audioTab := container.NewVBox(
		widget.NewForm(
			widget.NewFormItem("🔊 Lautsprecher", container.NewBorder(nil, nil, nil,
				container.NewHBox(speakerTestBtn, speakerTestLbl), speakerSel)),
			widget.NewFormItem("🎤 Mikrofon", container.NewBorder(nil, nil, nil,
				container.NewHBox(micTestBtn, micTestLbl), micSel)),
			widget.NewFormItem("🗣 Antwortstimme", container.NewBorder(nil, nil, nil,
				container.NewHBox(voiceTestBtn, voiceTestLbl), voiceSel)),
		),
	)

	// ── Tab 3: Sprachsteuerung (Wake-Word) ────────────────────────────────────
	// Eindeutiges Label: Haken gesetzt = Wake-Word IST aktiv
	wakeCheck := widget.NewCheck("Aktivierungswort verwenden (Haken = aktiv)", nil)
	wakeCheck.SetChecked(app.cfg.WakeWordEnabled)

	wakeEntry := widget.NewEntry()
	wakeEntry.SetText(app.cfg.WakeWord)
	wakeEntry.SetPlaceHolder("z.B. hallo jarvis")

	silenceEntry := widget.NewEntry()
	silenceEntry.SetText(strconv.Itoa(app.cfg.SilenceMs))
	silenceEntry.SetPlaceHolder("ms  (Standard: 900)")

	minSpeechEntry := widget.NewEntry()
	minSpeechEntry.SetText(strconv.Itoa(app.cfg.MinSpeechMs))
	minSpeechEntry.SetPlaceHolder("ms  (Standard: 200)")

	vadEntry := widget.NewEntry()
	vadEntry.SetText(strconv.Itoa(app.cfg.VADThreshold))
	vadEntry.SetPlaceHolder("0–32767  (Standard: 400)")

	voiceForm := widget.NewForm(
		widget.NewFormItem("Aktivierungswort", wakeEntry),
		widget.NewFormItem("Stille-Erkennungs-Dauer (ms)", silenceEntry),
		widget.NewFormItem("Mindest-Sprechzeit (ms)", minSpeechEntry),
		widget.NewFormItem("Lautstärke-Schwellwert (VAD)", vadEntry),
	)

	// Form-Felder de/aktivieren je nach Checkbox
	setVoiceFormEnabled := func(enabled bool) {
		if enabled {
			wakeEntry.Enable()
			silenceEntry.Enable()
			minSpeechEntry.Enable()
			vadEntry.Enable()
		} else {
			wakeEntry.Disable()
			silenceEntry.Disable()
			minSpeechEntry.Disable()
			vadEntry.Disable()
		}
	}
	setVoiceFormEnabled(app.cfg.WakeWordEnabled)
	wakeCheck.OnChanged = setVoiceFormEnabled

	voiceInfo := widget.NewLabel(
		"Wenn aktiviert: Mikrofon hört passiv zu und startet\n" +
			"die Aufnahme erst nach Erkennung des Aktivierungsworts.\n" +
			"Das Aktivierungswort wird per Whisper (Backend) erkannt.")
	voiceInfo.Wrapping = fyne.TextWrapWord

	voiceTab := container.NewVBox(wakeCheck, widget.NewSeparator(), voiceForm, widget.NewSeparator(), voiceInfo)

	// ── Tabs zusammenbauen ────────────────────────────────────────────────────
	tabs := container.NewAppTabs(
		container.NewTabItem("🔗 Verbindung", container.NewPadded(connTab)),
		container.NewTabItem("🔊 Audio", container.NewPadded(audioTab)),
		container.NewTabItem("🎤 Sprachsteuerung", container.NewPadded(voiceTab)),
	)
	tabs.SetTabLocation(container.TabLocationTop)

	// ── Buttons ───────────────────────────────────────────────────────────────
	saveBtn := widget.NewButton("Speichern", func() {
		if hostEntry.Text == "" || keyEntry.Text == "" {
			dialog.ShowError(fmt.Errorf("Bitte Server-Adresse und API-Key eingeben"), win)
			return
		}
		app.cfg.ServerURL = serverToURL(hostEntry.Text)
		app.cfg.APIKey = keyEntry.Text

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

		// TTS-Antwortstimme – ID (nicht Anzeigename) speichern
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

		// Wake-Word
		app.cfg.WakeWordEnabled = wakeCheck.Checked
		app.cfg.WakeWord = wakeEntry.Text
		if v, err := strconv.Atoi(silenceEntry.Text); err == nil && v > 0 {
			app.cfg.SilenceMs = v
		}
		if v, err := strconv.Atoi(minSpeechEntry.Text); err == nil && v > 0 {
			app.cfg.MinSpeechMs = v
		}
		if v, err := strconv.Atoi(vadEntry.Text); err == nil && v >= 0 {
			app.cfg.VADThreshold = v
		}

		_ = app.cfg.Save()
		win.Close()
		if onSave != nil {
			onSave()
		}
	})
	// Buttons – Android-Stil: Primär=Lila (HighImportance), Sekundär=gedimmt
	saveBtn.Importance = widget.HighImportance // lila #6366F1
	cancelBtn := widget.NewButton("Abbrechen", func() { win.Close() })
	cancelBtn.Importance = widget.LowImportance

	// Verbindungstest-Button ebenfalls stylen
	testBtn.Importance = widget.MediumImportance

	btnRow := container.NewGridWithColumns(2, cancelBtn, saveBtn)
	content := container.NewBorder(nil, container.NewPadded(btnRow), nil, nil, tabs)

	win.SetContent(content)
	win.Resize(fyne.NewSize(480, 440))
	win.Show()
}

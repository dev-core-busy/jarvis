package main

import (
	"fmt"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/widget"
)

// showSettingsWindow öffnet das Einstellungs-Fenster.
// onSave wird aufgerufen wenn der Benutzer speichert.
func showSettingsWindow(a fyne.App, app *JarvisApp, onSave func()) {
	win := a.NewWindow("Jarvis – Einstellungen")
	win.SetFixedSize(false)

	// ── Server ───────────────────────────────────────────────────────────────
	hostEntry := widget.NewEntry()
	hostEntry.SetText(urlToHost(app.cfg.ServerURL))
	hostEntry.SetPlaceHolder("IP oder Hostname  z.B.  191.100.144.1")

	keyEntry := widget.NewPasswordEntry()
	keyEntry.SetText(app.cfg.APIKey)
	keyEntry.SetPlaceHolder("API-Schlüssel")

	// Verbindungstest
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

	// ── Audio-Geräte ─────────────────────────────────────────────────────────
	speakerSel := widget.NewSelect([]string{"Standard"}, nil)
	micSel := widget.NewSelect([]string{"Standard"}, nil)

	speakerIDs := []string{""}
	micIDs := []string{""}

	if app.audio != nil {
		// Lautsprecher laden
		speakers := app.audio.ListSpeakers()
		spNames := make([]string, len(speakers))
		for i, s := range speakers {
			spNames[i] = s.Name
			speakerIDs = append(speakerIDs, s.ID)
		}
		if len(spNames) > 0 {
			speakerSel.Options = spNames
			// Aktuell konfiguriertes Gerät auswählen
			if app.cfg.SpeakerName != "" {
				speakerSel.SetSelected(app.cfg.SpeakerName)
			} else {
				speakerSel.SetSelected("Standard")
			}
		}

		// Mikrofone laden
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

	// ── Formular ─────────────────────────────────────────────────────────────
	form := widget.NewForm(
		widget.NewFormItem("Server-Adresse", hostEntry),
		widget.NewFormItem("API-Key", keyEntry),
		widget.NewFormItem("Lautsprecher", speakerSel),
		widget.NewFormItem("Mikrofon", micSel),
	)

	// ── Buttons ───────────────────────────────────────────────────────────────
	saveBtn := widget.NewButton("Speichern & Verbinden", func() {
		if hostEntry.Text == "" || keyEntry.Text == "" {
			dialog.ShowError(fmt.Errorf("Bitte Server-Adresse und API-Key eingeben"), win)
			return
		}
		app.cfg.ServerURL = serverToURL(hostEntry.Text)
		app.cfg.APIKey = keyEntry.Text

		// Lautsprecher
		selSp := speakerSel.Selected
		app.cfg.SpeakerName = selSp
		for i, name := range speakerSel.Options {
			if name == selSp && i < len(speakerIDs) {
				app.cfg.SpeakerID = speakerIDs[i]
				break
			}
		}

		// Mikrofon
		selMic := micSel.Selected
		app.cfg.MicName = selMic
		for i, name := range micSel.Options {
			if name == selMic && i < len(micIDs) {
				app.cfg.MicID = micIDs[i]
				break
			}
		}

		_ = app.cfg.Save()
		win.Close()
		if onSave != nil {
			onSave()
		}
	})
	saveBtn.Importance = widget.HighImportance

	cancelBtn := widget.NewButton("Abbrechen", func() { win.Close() })

	btnRow := container.NewGridWithColumns(2, cancelBtn, saveBtn)

	content := container.NewVBox(
		form,
		testBtn,
		statusLbl,
		widget.NewSeparator(),
		btnRow,
	)

	win.SetContent(container.NewPadded(content))
	win.Resize(fyne.NewSize(460, 320))
	win.Show()
}

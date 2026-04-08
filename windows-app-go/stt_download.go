package main

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/widget"
)

const (
	// Stabile Download-URLs über jarvis-ai.info (Redirect zu upstream, nur .htaccess ändern bei URL-Wechsel)
	whisperZipURL   = "https://jarvis-ai.info/downloads/whisper-bin-x64.zip"
	whisperModelURL = "https://jarvis-ai.info/downloads/ggml-small.bin"
	whisperModelName = "ggml-small.bin"
)

// WhisperStatus prüft ob whisper-cli.exe und ein Sprachmodell im Unterordner speech-to-text vorhanden sind.
func WhisperStatus() (hasExe, hasModel bool) {
	dir := sttDir()
	for _, name := range []string{"whisper-cli.exe", "whisper.exe", "main.exe"} {
		if _, err := os.Stat(filepath.Join(dir, name)); err == nil {
			hasExe = true
			break
		}
	}
	for _, name := range []string{
		"ggml-small.bin", "ggml-small-q5_1.bin", "ggml-small-q8_0.bin",
		"ggml-base.bin", "ggml-base-q5_1.bin",
		"ggml-tiny.bin", "ggml-tiny-q5_1.bin",
	} {
		if _, err := os.Stat(filepath.Join(dir, name)); err == nil {
			hasModel = true
			break
		}
	}
	return
}

// WhisperReady gibt true zurück wenn sowohl Binary als auch Modell vorhanden sind.
func WhisperReady() bool {
	hasExe, hasModel := WhisperStatus()
	return hasExe && hasModel
}

// showWhisperDownloadDialog zeigt einen Dialog der erklärt dass Whisper-Komponenten fehlen
// und bietet einen direkten Download-Start an.
func showWhisperDownloadDialog(a fyne.App, missing string, parent fyne.Window) {
	progress := widget.NewProgressBar()
	statusLbl := widget.NewLabel("Bereit zum Herunterladen.")
	statusLbl.Importance = widget.LowImportance

	dlBtn := widget.NewButton("Jetzt herunterladen", nil)
	dlBtn.Importance = widget.HighImportance

	cancelBtn := widget.NewButton("Abbrechen", nil)

	content := container.NewVBox(
		widget.NewLabel(fmt.Sprintf(
			"Für die Spracheingabe werden folgende Komponenten benötigt:\n\n"+
				"  %s\n\n"+
				"Diese werden neben jarvis.exe gespeichert.\n"+
				"Danach ist die Spracheingabe sofort verfügbar.",
			missing,
		)),
		vSpacer(8),
		progress,
		statusLbl,
		container.NewGridWithColumns(2, dlBtn, cancelBtn),
	)

	win := a.NewWindow("Spracherkennung einrichten")
	win.SetContent(container.NewPadded(content))
	win.Resize(fyne.NewSize(420, 240))
	win.SetFixedSize(true)

	cancelBtn.OnTapped = func() { win.Close() }

	dlBtn.OnTapped = func() {
		dlBtn.Disable()
		cancelBtn.Disable()
		progress.SetValue(0)

		go func() {
			hasExe, hasModel := WhisperStatus()
			steps := 0
			if !hasExe {
				steps++
			}
			if !hasModel {
				steps++
			}
			stepSize := 1.0 / float64(steps)
			offset := 0.0

			if !hasExe {
				statusLbl.SetText("Lade whisper-cli.exe …")
				if err := DownloadWhisperExe(func(p float64) {
					progress.SetValue(offset + p*stepSize)
				}); err != nil {
					statusLbl.SetText("✗ " + err.Error())
					dlBtn.Enable()
					cancelBtn.Enable()
					return
				}
				offset += stepSize
			}

			if !hasModel {
				statusLbl.SetText("Lade ggml-small.bin (466 MB) …")
				if err := DownloadWhisperModel(func(p float64) {
					progress.SetValue(offset + p*stepSize)
				}); err != nil {
					statusLbl.SetText("✗ " + err.Error())
					dlBtn.Enable()
					cancelBtn.Enable()
					return
				}
			}

			statusLbl.SetText("✓ Whisper einsatzbereit – bitte Mikrofon-Taste erneut drücken.")
			cancelBtn.SetText("Schließen")
			cancelBtn.Enable()
		}()
	}

	if parent != nil {
		win.SetOnClosed(nil)
	}
	win.Show()
}

// downloadWithProgress lädt eine URL herunter und ruft progress(0..1) regelmäßig auf.
func downloadWithProgress(url, dest string, progress func(float64)) error {
	resp, err := http.Get(url) //nolint:gosec
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d von %s", resp.StatusCode, url)
	}
	total := resp.ContentLength
	f, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer f.Close()

	buf := make([]byte, 64*1024)
	var downloaded int64
	for {
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := f.Write(buf[:n]); werr != nil {
				return werr
			}
			downloaded += int64(n)
			if total > 0 && progress != nil {
				progress(float64(downloaded) / float64(total))
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return readErr
		}
	}
	return nil
}

// DownloadWhisperExe lädt das whisper.cpp Release-ZIP herunter und extrahiert .exe/.dll Dateien.
func DownloadWhisperExe(progress func(float64)) error {
	tmpZip := filepath.Join(os.TempDir(), "whisper-bin-x64.zip")
	defer os.Remove(tmpZip)

	// ZIP herunterladen (0–90 % des Fortschritts)
	if err := downloadWithProgress(whisperZipURL, tmpZip, func(p float64) {
		if progress != nil {
			progress(p * 0.9)
		}
	}); err != nil {
		return fmt.Errorf("Download fehlgeschlagen: %w", err)
	}

	zipData, err := os.ReadFile(tmpZip)
	if err != nil {
		return err
	}
	zr, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return fmt.Errorf("ZIP ungültig: %w", err)
	}

	dir := sttDir()
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("Ordner speech-to-text: %w", err)
	}
	extracted := 0
	for _, f := range zr.File {
		name := filepath.Base(f.Name)
		lower := strings.ToLower(name)
		if !strings.HasSuffix(lower, ".exe") && !strings.HasSuffix(lower, ".dll") {
			continue
		}
		if err := extractZipEntry(f, filepath.Join(dir, name)); err != nil {
			return fmt.Errorf("Extrahieren von %s: %w", name, err)
		}
		extracted++
	}
	if extracted == 0 {
		return fmt.Errorf("keine Binaries im ZIP gefunden – möglicherweise geänderte Dateistruktur")
	}
	if progress != nil {
		progress(1.0)
	}
	return nil
}

func extractZipEntry(f *zip.File, dest string) error {
	rc, err := f.Open()
	if err != nil {
		return err
	}
	defer rc.Close()
	out, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, rc)
	return err
}

// DownloadWhisperModel lädt ggml-small.bin herunter und speichert es in speech-to-text/.
func DownloadWhisperModel(progress func(float64)) error {
	dir := sttDir()
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("Ordner speech-to-text: %w", err)
	}
	dest := filepath.Join(dir, whisperModelName)
	tmp := dest + ".downloading"
	if err := downloadWithProgress(whisperModelURL, tmp, progress); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("Modell-Download fehlgeschlagen: %w", err)
	}
	return os.Rename(tmp, dest)
}

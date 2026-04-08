package main

import (
	"os"
	"os/exec"
	"strings"
	"syscall"
)

// TranscribeLocal transkribiert WAV-Daten über Windows SAPI (System.Speech.Recognition).
// Kein externes Tool nötig – läuft auf jedem Windows ohne Installation.
func TranscribeLocal(wavData []byte) (string, error) {
	f, err := os.CreateTemp("", "jarvis-stt-*.wav")
	if err != nil {
		return "", err
	}
	tmpPath := f.Name()
	defer os.Remove(tmpPath)
	if _, err := f.Write(wavData); err != nil {
		f.Close()
		return "", err
	}
	f.Close()

	winPath := strings.ReplaceAll(tmpPath, "/", "\\")

	// System.Speech.Recognition: WAV-Datei einlesen, offline erkennen
	script := `
Add-Type -AssemblyName System.Speech
$rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$rec.SetInputToWaveFile('` + winPath + `')
$g = New-Object System.Speech.Recognition.DictationGrammar
$rec.LoadGrammar($g)
$rec.BabbleTimeout = [TimeSpan]::FromSeconds(0)
$rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds(10)
$rec.EndSilenceTimeout = [TimeSpan]::FromSeconds(1)
try {
    $r = $rec.Recognize()
    if ($r -ne $null) { Write-Output $r.Text }
} catch {}
$rec.Dispose()
`
	cmd := exec.Command("powershell.exe",
		"-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
		"-Command", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(out)), nil
}

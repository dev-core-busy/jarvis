package main

import (
	"os"
	"os/exec"
	"strings"
)

// TranscribeLocal transkribiert WAV-Daten lokal mit whisper.cpp.
// Gibt das Transkript oder einen Fehler zurück.
func TranscribeLocal(wavData []byte, exePath, modelPath string) (string, error) {
	// WAV in Temp-Datei schreiben
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

	// whisper.cpp aufrufen:
	//   -m  Modelldatei
	//   -l  Sprache
	//   -f  Eingabedatei
	//   -nt keine Zeitstempel in der Ausgabe
	cmd := exec.Command(exePath,
		"-m", modelPath,
		"-l", "de",
		"-f", tmpPath,
		"-nt",
	)
	out, err := cmd.Output()
	if err != nil {
		return "", err
	}

	// Ausgabe bereinigen: leere Zeilen und Zeitstempel-Zeilen entfernen
	var parts []string
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "[") {
			continue
		}
		parts = append(parts, line)
	}
	return strings.Join(parts, " "), nil
}

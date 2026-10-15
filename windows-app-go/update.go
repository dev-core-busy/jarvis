package main

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type WindowsVersionInfo struct {
	VersionCode int    `json:"versionCode"`
	VersionName string `json:"versionName"`
	DownloadURL string `json:"downloadUrl"`
}

// currentBuildNum parst die Build-Nummer aus AppVersion ("0.836" → 836).
func currentBuildNum() int {
	parts := strings.Split(AppVersion, ".")
	if len(parts) < 2 {
		return 0
	}
	n, _ := strconv.Atoi(parts[len(parts)-1])
	return n
}

// httpClient gibt einen HTTP-Client mit 60s Timeout zurück.
func httpClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: false},
		},
	}
}

// CheckForUpdate prüft version_windows.json auf jarvis-ai.info.
// Gibt nil zurück wenn kein Update verfügbar oder bei Fehler.
func CheckForUpdate() *WindowsVersionInfo {
	url := fmt.Sprintf("https://jarvis-ai.info/downloads/version_windows.json?t=%d", time.Now().UnixMilli())
	resp, err := httpClient(10 * time.Second).Get(url)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil
	}
	var info WindowsVersionInfo
	if err := json.Unmarshal(body, &info); err != nil {
		return nil
	}
	if info.VersionCode > currentBuildNum() {
		return &info
	}
	return nil
}

// PerformUpdate lädt die neue EXE herunter, ersetzt die aktuelle per Batch-Script
// und startet die Anwendung neu. progressFn wird mit 0.0–1.0 aufgerufen.
// Bei Fehler wird die Fehlermeldung zurückgegeben.
func PerformUpdate(info *WindowsVersionInfo, progressFn func(float64)) error {
	// Download-URL bestimmen
	downloadURL := info.DownloadURL
	if downloadURL == "" {
		downloadURL = "https://jarvis-ai.info/downloads/jarvis.exe"
	}

	// Pfad der laufenden EXE
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("EXE-Pfad nicht ermittelbar: %w", err)
	}
	exePath, err = filepath.EvalSymlinks(exePath)
	if err != nil {
		return fmt.Errorf("EXE-Symlink nicht auflösbar: %w", err)
	}
	exeDir := filepath.Dir(exePath)

	// Neue EXE in dasselbe Verzeichnis herunterladen
	newExePath := filepath.Join(exeDir, "jarvis_update.exe")
	if err := downloadFile(downloadURL, newExePath, progressFn); err != nil {
		_ = os.Remove(newExePath)
		return fmt.Errorf("Download fehlgeschlagen: %w", err)
	}

	// Batch-Script schreiben das:
	// 1. Wartet bis aktuelle EXE freigegeben ist
	// 2. Alte EXE umbenennt
	// 3. Neue EXE an richtige Stelle kopiert
	// 4. Neue EXE startet
	// 5. Sich selbst und die alte EXE löscht
	batchPath := filepath.Join(exeDir, "jarvis_updater.bat")
	oldExePath := filepath.Join(exeDir, "jarvis_old.exe")
	batchContent := fmt.Sprintf(`@echo off
chcp 65001 >nul
timeout /t 2 /nobreak >nul
:waitloop
tasklist /fi "imagename eq jarvis.exe" 2>nul | find /i "jarvis.exe" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
move /y "%s" "%s" >nul
move /y "%s" "%s" >nul
start "" "%s"
timeout /t 3 /nobreak >nul
del "%s" >nul 2>&1
del "%%~f0"
`, exePath, oldExePath, newExePath, exePath, exePath, oldExePath)

	if err := os.WriteFile(batchPath, []byte(batchContent), 0755); err != nil {
		_ = os.Remove(newExePath)
		return fmt.Errorf("Updater-Script konnte nicht geschrieben werden: %w", err)
	}

	// Batch-Script starten (unsichtbar, unabhängig vom aktuellen Prozess)
	cmd := exec.Command("cmd", "/c", "start", "", "/b", batchPath)
	cmd.Dir = exeDir
	if err := cmd.Start(); err != nil {
		_ = os.Remove(newExePath)
		_ = os.Remove(batchPath)
		return fmt.Errorf("Updater-Script konnte nicht gestartet werden: %w", err)
	}

	// App beenden – Batch übernimmt
	go func() {
		time.Sleep(500 * time.Millisecond)
		os.Exit(0)
	}()
	return nil
}

// downloadFile lädt eine Datei herunter und ruft progressFn mit 0.0–1.0 auf.
func downloadFile(url, dest string, progressFn func(float64)) error {
	resp, err := httpClient(5 * time.Minute).Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	f, err := os.Create(dest)
	if err != nil {
		return err
	}
	defer f.Close()

	total := resp.ContentLength
	var downloaded int64
	buf := make([]byte, 32*1024)
	for {
		n, err := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := f.Write(buf[:n]); werr != nil {
				return werr
			}
			downloaded += int64(n)
			if total > 0 && progressFn != nil {
				progressFn(float64(downloaded) / float64(total))
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
	}
	if progressFn != nil {
		progressFn(1.0)
	}
	return nil
}

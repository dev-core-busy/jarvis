package main

// Bild-Anzeige in Chat-Bubbles: erkennt von Jarvis generierte/gesuchte Bilder
// (/api/generated/<uuid>.<ext>) in der Antwort und laedt sie inline als Bild.

import (
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/theme"

	"jarvis-windows/tlsvertrauen"
)

// imgServerBase ist die HTTPS-Basis (z.B. "https://jarvis.firma.local"), gesetzt aus der ServerURL.
var imgServerBase string

// imgToken liefert das AKTUELLE Token (Funktion statt Wert: der Einstellungs-
// dialog kann es zur Laufzeit aendern). Seit 2026-10-15 verlangt der Server fuer
// /api/generated/ eine Anmeldung; vorher war die Adresse ohne Anmeldung abrufbar.
var imgToken = func() string { return "" }

// SetImageAuth setzt die Quelle des Tokens fuer den Bildabruf.
func SetImageAuth(f func() string) {
	if f != nil {
		imgToken = f
	}
}

// SetImageServer leitet die HTTPS-Basis aus der konfigurierten ServerURL ab.
func SetImageServer(serverURL string) {
	u := strings.TrimSpace(serverURL)
	for _, p := range []string{"wss://", "https://", "ws://", "http://"} {
		u = strings.TrimPrefix(u, p)
	}
	if i := strings.IndexByte(u, '/'); i >= 0 {
		u = u[:i]
	}
	if u != "" {
		imgServerBase = "https://" + u
	}
}

var genImgURLRe = regexp.MustCompile(`/api/generated/[0-9a-f]{32}\.[a-z]+`)
var genImgMdRe = regexp.MustCompile(`!\[[^\]]*\]\([^)]*?/api/generated/[0-9a-f]{32}\.[a-z]+\)`)

// extractGenImages liefert die relativen Bild-URLs und den um die Bild-Referenzen
// bereinigten Text.
func extractGenImages(text string) ([]string, string) {
	urls := genImgURLRe.FindAllString(text, -1)
	clean := genImgMdRe.ReplaceAllString(text, "")
	clean = genImgURLRe.ReplaceAllString(clean, "")
	clean = strings.TrimSpace(clean)
	return urls, clean
}

func fetchImageBytes(url string) ([]byte, error) {
	client := &http.Client{
		Timeout:   20 * time.Second,
		Transport: &http.Transport{TLSClientConfig: tlsvertrauen.ServerTLS(url)},
	}
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	if tok := imgToken(); tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, io.EOF
	}
	return io.ReadAll(resp.Body)
}

// buildJarvisBody baut den Inhalt einer Jarvis-Bubble: Text und – falls vorhanden –
// inline geladene Bilder.
func buildJarvisBody(text string) fyne.CanvasObject {
	urls, clean := extractGenImages(text)
	if len(urls) == 0 {
		return newBoldWhiteText(text, true)
	}

	items := []fyne.CanvasObject{}
	if clean != "" {
		items = append(items, newBoldWhiteText(clean, true))
	}
	for _, u := range urls {
		img := canvas.NewImageFromResource(theme.FileImageIcon()) // Platzhalter bis geladen
		img.FillMode = canvas.ImageFillContain
		img.SetMinSize(fyne.NewSize(260, 200))
		full := imgServerBase + u
		go func(url string, target *canvas.Image) {
			data, err := fetchImageBytes(url)
			if err != nil || len(data) == 0 {
				return
			}
			target.Resource = fyne.NewStaticResource("genimg", data)
			canvas.Refresh(target)
		}(full, img)
		items = append(items, img)
	}
	return container.NewVBox(items...)
}

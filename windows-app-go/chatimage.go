package main

// Bild-Anzeige in Chat-Bubbles: erkennt von Jarvis generierte/gesuchte Bilder
// (/api/generated/<uuid>.<ext>) in der Antwort und laedt sie inline als Bild.

import (
	"crypto/tls"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/theme"
)

// imgServerBase ist die HTTPS-Basis (z.B. "https://191.100.144.1"), gesetzt aus der ServerURL.
var imgServerBase string

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
		Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}, //nolint:gosec
	}
	resp, err := client.Get(url)
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

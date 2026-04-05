package main

import (
	"bytes"
	"image"
	"image/draw"
	_ "image/png"
	"math"
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/widget"
	"github.com/fogleman/gg"
)

// ── Modus ─────────────────────────────────────────────────────────────────────

type AvatarMode int

const (
	ModeIdle      AvatarMode = iota
	ModeSpeaking             // Jarvis antwortet
	ModeListening            // Mikrofon aktiv
	ModeChecking             // Wake-Word wird geprüft (blau)
)

// ── Animations-State ──────────────────────────────────────────────────────────

type avatarState struct {
	mu         sync.Mutex
	mode       AvatarMode
	eyePhase   float64
	speakPhase float64
}

func (s *avatarState) tick(dt float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	speed := 1.0
	if s.mode == ModeSpeaking {
		speed = 1.6
	} else if s.mode == ModeListening {
		speed = 1.2
	}
	// Ruhigeres Pulsieren: 0.4 statt 1.1 → ~2s Periode im Idle-Modus
	s.eyePhase = math.Mod(s.eyePhase+dt*speed*0.4, 1.0)
	s.speakPhase = math.Mod(s.speakPhase+dt*speed*3.0, 1.0)
}

func (s *avatarState) snap() (mode AvatarMode, eye, speak float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.mode,
		math.Sin(s.eyePhase*math.Pi*2)*0.5 + 0.5,
		math.Abs(math.Sin(s.speakPhase * math.Pi))
}

// ── Fyne-Widget ───────────────────────────────────────────────────────────────

type AvatarWidget struct {
	widget.BaseWidget

	state      avatarState
	raster     *canvas.Raster
	ironManImg image.Image // dekodiertes PNG
	ticker     *time.Ticker
	stopCh     chan struct{}

}

func NewAvatarWidget() *AvatarWidget {
	// Iron Man PNG dekodieren
	img, _, err := image.Decode(bytes.NewReader(ironManAvatarBytes))
	if err != nil {
		img = nil
	}

	// Falls PNG transparent ist: in RGBA konvertieren damit draw.Over funktioniert
	if img != nil {
		rgba := image.NewRGBA(img.Bounds())
		draw.Draw(rgba, rgba.Bounds(), img, image.Point{}, draw.Src)
		img = rgba
	}

	a := &AvatarWidget{
		stopCh:     make(chan struct{}),
		ironManImg: img,
	}
	a.raster = canvas.NewRaster(a.drawFrame)
	a.ExtendBaseWidget(a)
	a.ticker = time.NewTicker(33 * time.Millisecond) // ~30 fps
	go a.animate()
	return a
}

func (a *AvatarWidget) SetMode(m AvatarMode) {
	a.state.mu.Lock()
	a.state.mode = m
	a.state.mu.Unlock()
}

func (a *AvatarWidget) SetSpeaking(v bool) {
	if v {
		a.SetMode(ModeSpeaking)
	} else {
		a.SetMode(ModeIdle)
	}
}

func (a *AvatarWidget) Stop() {
	a.ticker.Stop()
	close(a.stopCh)
}

func (a *AvatarWidget) animate() {
	for {
		select {
		case <-a.stopCh:
			return
		case <-a.ticker.C:
			a.state.tick(0.033)
			canvas.Refresh(a.raster)
		}
	}
}

func (a *AvatarWidget) CreateRenderer() fyne.WidgetRenderer {
	return widget.NewSimpleRenderer(a.raster)
}

func (a *AvatarWidget) MinSize() fyne.Size { return fyne.NewSize(260, 260) }

// Drag wird vollständig durch Win32 WM_NCHITTEST → HTCAPTION gehandelt
// (MakeAvatarWindowFrameless subclasst die WndProc).
// Fyne Draggable-Interface wird NICHT mehr implementiert.

// ── Zeichnen ──────────────────────────────────────────────────────────────────

// Colorkey-Farbe: RGB(2,2,2) – wird via Win32 SetLayeredWindowAttributes transparent.
// MUSS mit MakeAvatarWindowTransparent() übereinstimmen!
const colorkeyR = 2.0 / 255.0
const colorkeyG = 2.0 / 255.0
const colorkeyB = 2.0 / 255.0

func (a *AvatarWidget) drawFrame(w, h int) image.Image {
	mode, eye, speak := a.state.snap()
	dc := gg.NewContext(w, h)
	W, H := float64(w), float64(h)

	// ── 1. Hintergrund mit Colorkey füllen (wird transparent) ─────────────────
	dc.SetRGB(colorkeyR, colorkeyG, colorkeyB)
	dc.Clear()

	// ── 2. Iron Man Helm skaliert zeichnen ────────────────────────────────────
	if a.ironManImg != nil {
		b := a.ironManImg.Bounds()
		iW, iH := float64(b.Dx()), float64(b.Dy())
		dc.Push()
		dc.Scale(W/iW, H/iH)
		dc.DrawImage(a.ironManImg, 0, 0)
		dc.Pop()
	}

	// ── 3. Modus-Farbe für Glow-Effekte ──────────────────────────────────────
	var rC, gC, bC float64
	switch mode {
	case ModeSpeaking:
		rC, gC, bC = 0.0, 0.88, 1.0  // Cyan
	case ModeListening:
		rC, gC, bC = 0.15, 1.0, 0.40 // Grün
	case ModeChecking:
		rC, gC, bC = 0.3, 0.5, 1.0   // Blau – "prüfe Wake-Word"
	default:
		rC, gC, bC = 0.8, 0.55, 0.10 // Gold/Orange – passt zum Helm
	}

	eyeI := 0.50 + eye*0.50 // Pulsieren 50–100%

	// ── 4. Augen-Glow (kalibrierte Positionen aus Android IronManComposable.kt) ─
	// Quellbild 512×512; gemessene Schlitzpixel:
	//   Linkes Auge:  cols 149–215, rows 252–274  (Breite 66, Höhe 22)
	//   Rechtes Auge: cols 290–356, rows 252–274
	imgOffY := (H - W) / 2.0 // 0 wenn quadratisches Fenster (260×260)
	eyeW := W * (66.0 / 512.0)
	eyeH := eyeW * (22.0 / 66.0) // = W*(22/512)
	eyeYtop := imgOffY + W*(252.0/512.0)
	eyeLXedge := W * (149.0 / 512.0)
	eyeRXedge := W * (290.0 / 512.0)

	for _, exEdge := range []float64{eyeLXedge, eyeRXedge} {
		cx := exEdge + eyeW/2.0
		cy := eyeYtop + eyeH/2.0

		// Äußerer Glow-Halo: kompakter Schein, bleibt innerhalb des Helms
		// Maximaler Radius bei i=6: eyeW*0.52 × eyeH*0.95 – kein Überlauf
		for i := 6; i >= 1; i-- {
			fi := float64(i)
			alpha := eyeI * (1.0 - fi/7.0) * 0.50
			dc.DrawEllipse(cx, cy, eyeW*(0.52+fi*0.08), eyeH*(0.90+fi*0.10))
			dc.SetRGBA(rC, gC, bC, alpha)
			dc.Fill()
		}
		// Innerer Kern: exakte Schlitz-Form als gerundetes Rechteck
		dc.DrawRoundedRectangle(exEdge, eyeYtop, eyeW, eyeH, eyeH*0.4)
		dc.SetRGBA(rC, gC, bC, eyeI*0.95)
		dc.Fill()
		// Weißer Glanzpunkt mittig
		dc.DrawEllipse(cx, cy, eyeW*0.20, eyeH*0.38)
		dc.SetRGBA(1.0, 1.0, 1.0, eyeI*0.82)
		dc.Fill()
	}

	// ── 5. Equalizer-Balken am Mund (Speaking / Listening) ───────────────────
	if mode == ModeSpeaking || mode == ModeListening {
		numBars := 7
		barW := W * 0.032
		barGap := W * 0.010
		total := float64(numBars)*(barW+barGap) - barGap
		startX := W/2 - total/2
		barBaseY := imgOffY + W*0.775 // Mundöffnung des Helms

		for i := 0; i < numBars; i++ {
			phase := speak + float64(i)*0.20
			barH := H * 0.058 * (0.25 + 0.75*math.Abs(math.Sin(phase*math.Pi*2+float64(i))))
			bx := startX + float64(i)*(barW+barGap)
			by := barBaseY - barH/2
			dc.SetRGBA(rC, gC, bC, 0.85)
			dc.DrawRectangle(bx, by, barW, barH)
			dc.Fill()
		}
	}

	return dc.Image()
}

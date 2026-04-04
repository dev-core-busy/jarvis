package main

import (
	"image"
	"math"
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/widget"
	"github.com/fogleman/gg"
)

// ── Avatar-Modus ──────────────────────────────────────────────────────────────

type AvatarMode int

const (
	ModeIdle      AvatarMode = iota
	ModeSpeaking             // Jarvis antwortet
	ModeListening            // Mikrofon aktiv
)

// ── Animations-State ──────────────────────────────────────────────────────────

type avatarState struct {
	mu         sync.Mutex
	mode       AvatarMode
	glowPhase  float64
	eyePhase   float64
	ringPhase  float64
	scanPhase  float64
	speakPhase float64
}

func (s *avatarState) tick(dt float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	speed := 1.0
	if s.mode == ModeSpeaking {
		speed = 2.2
	} else if s.mode == ModeListening {
		speed = 1.6
	}
	s.glowPhase = math.Mod(s.glowPhase+dt*speed*0.7, 1.0)
	s.eyePhase = math.Mod(s.eyePhase+dt*speed*1.1, 1.0)
	s.ringPhase = math.Mod(s.ringPhase+dt*speed*0.4, 1.0)
	s.scanPhase = math.Mod(s.scanPhase+dt*speed*0.9, 1.0)
	s.speakPhase = math.Mod(s.speakPhase+dt*speed*3.0, 1.0)
}

func (s *avatarState) snap() (mode AvatarMode, glow, eye, ring, scan, speak float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.mode,
		math.Sin(s.glowPhase*math.Pi*2)*0.5 + 0.5,
		math.Sin(s.eyePhase*math.Pi*2)*0.5 + 0.5,
		s.ringPhase,
		s.scanPhase,
		math.Abs(math.Sin(s.speakPhase * math.Pi))
}

// ── Fyne-Widget ───────────────────────────────────────────────────────────────

type AvatarWidget struct {
	widget.BaseWidget
	state  avatarState
	raster *canvas.Raster
	ticker *time.Ticker
	stopCh chan struct{}
}

func NewAvatarWidget() *AvatarWidget {
	a := &AvatarWidget{stopCh: make(chan struct{})}
	a.raster = canvas.NewRaster(a.drawFrame)
	a.ExtendBaseWidget(a)
	a.ticker = time.NewTicker(16 * time.Millisecond)
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
			a.state.tick(0.016)
			canvas.Refresh(a.raster)
		}
	}
}

func (a *AvatarWidget) CreateRenderer() fyne.WidgetRenderer {
	return widget.NewSimpleRenderer(a.raster)
}

func (a *AvatarWidget) MinSize() fyne.Size { return fyne.NewSize(180, 200) }

// ── Zeichnen: Jarvis Iron-Man Kopf ───────────────────────────────────────────

func (a *AvatarWidget) drawFrame(w, h int) image.Image {
	mode, glow, eye, ring, scan, speak := a.state.snap()
	dc := gg.NewContext(w, h)
	W, H := float64(w), float64(h)

	// Farben je nach Modus
	var rC, gC, bC float64
	switch mode {
	case ModeSpeaking:
		rC, gC, bC = 0.0, 0.85, 1.0 // Cyan
	case ModeListening:
		rC, gC, bC = 0.2, 1.0, 0.45 // Grün
	default:
		rC, gC, bC = 0.1, 0.6, 1.0 // Blau
	}

	// ── 1. Hintergrund ────────────────────────────────────────────────────────
	dc.SetRGB(0.02, 0.04, 0.08)
	dc.Clear()

	cx, cy := W/2, H*0.50

	// ── 2. Äußerer Glow-Ring ─────────────────────────────────────────────────
	outerR := W * 0.44
	glowI := 0.25 + glow*0.4
	for i := 8; i >= 0; i-- {
		alpha := glowI * (1.0 - float64(i)/9.0) * 0.55
		dc.DrawCircle(cx, cy, outerR+float64(i)*2.0)
		dc.SetLineWidth(2.5)
		dc.SetRGBA(rC, gC, bC, alpha)
		dc.Stroke()
	}
	dc.DrawCircle(cx, cy, outerR)
	dc.SetLineWidth(1.5)
	dc.SetRGBA(rC, gC, bC, 0.7+glow*0.3)
	dc.Stroke()

	// Rotierende Ring-Ticks
	for i := 0; i < 8; i++ {
		angle := ring*math.Pi*2 + float64(i)*math.Pi/4
		x1 := cx + math.Cos(angle)*outerR*0.90
		y1 := cy + math.Sin(angle)*outerR*0.90
		x2 := cx + math.Cos(angle)*outerR*1.02
		y2 := cy + math.Sin(angle)*outerR*1.02
		alpha := 0.4 + 0.4*math.Abs(math.Sin(float64(i)*0.8+ring*math.Pi*2))
		dc.SetRGBA(rC, gC, bC, alpha)
		dc.SetLineWidth(2.0)
		dc.DrawLine(x1, y1, x2, y2)
		dc.Stroke()
	}

	// ── 3. Kopf-Silhouette ────────────────────────────────────────────────────
	headH := H * 0.80
	headW := W * 0.70
	headTop := cy - headH*0.52
	headBot := cy + headH*0.48

	dc.SetRGB(0.06, 0.08, 0.14)
	helmPath(dc, cx, cy, headW, headH, headTop, headBot)
	dc.Fill()

	// ── 4. Gold-Platten (layered, kein Gradient – heller/dunkler mit Überlagerung) ─
	// Stirn-Panel
	dc.SetRGBA(0.85, 0.65, 0.18, 1.0)
	dc.MoveTo(cx-headW*0.30, headTop+H*0.04)
	dc.LineTo(cx+headW*0.30, headTop+H*0.04)
	dc.LineTo(cx+headW*0.28, cy-headH*0.08)
	dc.LineTo(cx-headW*0.28, cy-headH*0.08)
	dc.ClosePath()
	dc.Fill()
	// Stirn-Aufhellung (oben heller)
	dc.SetRGBA(1.0, 0.92, 0.5, 0.22)
	dc.MoveTo(cx-headW*0.28, headTop+H*0.04)
	dc.LineTo(cx+headW*0.28, headTop+H*0.04)
	dc.LineTo(cx+headW*0.22, headTop+H*0.10)
	dc.LineTo(cx-headW*0.22, headTop+H*0.10)
	dc.ClosePath()
	dc.Fill()

	// Wangen links/rechts
	dc.SetRGBA(0.78, 0.58, 0.14, 1.0)
	dc.MoveTo(cx-headW*0.45, cy-headH*0.05)
	dc.LineTo(cx-headW*0.28, cy-headH*0.08)
	dc.LineTo(cx-headW*0.26, cy+headH*0.20)
	dc.LineTo(cx-headW*0.38, cy+headH*0.28)
	dc.ClosePath()
	dc.Fill()

	dc.MoveTo(cx+headW*0.45, cy-headH*0.05)
	dc.LineTo(cx+headW*0.28, cy-headH*0.08)
	dc.LineTo(cx+headW*0.26, cy+headH*0.20)
	dc.LineTo(cx+headW*0.38, cy+headH*0.28)
	dc.ClosePath()
	dc.Fill()

	// Kinn
	dc.SetRGBA(0.85, 0.65, 0.18, 1.0)
	dc.MoveTo(cx-headW*0.22, cy+headH*0.20)
	dc.LineTo(cx+headW*0.22, cy+headH*0.20)
	dc.LineTo(cx+headW*0.12, headBot-H*0.02)
	dc.LineTo(cx-headW*0.12, headBot-H*0.02)
	dc.ClosePath()
	dc.Fill()
	// Kinn-Aufhellung
	dc.SetRGBA(1.0, 0.92, 0.5, 0.15)
	dc.MoveTo(cx-headW*0.14, cy+headH*0.20)
	dc.LineTo(cx+headW*0.14, cy+headH*0.20)
	dc.LineTo(cx+headW*0.08, cy+headH*0.33)
	dc.LineTo(cx-headW*0.08, cy+headH*0.33)
	dc.ClosePath()
	dc.Fill()

	// ── 5. Visor (dunkles Sichtfeld) ─────────────────────────────────────────
	visorTop := headTop + H*0.16
	visorH := H * 0.18
	visorW := headW * 0.62

	dc.SetRGBA(0.03, 0.05, 0.11, 0.97)
	dc.MoveTo(cx-visorW*0.48, visorTop)
	dc.LineTo(cx+visorW*0.48, visorTop)
	dc.LineTo(cx+visorW*0.52, visorTop+visorH)
	dc.LineTo(cx-visorW*0.52, visorTop+visorH)
	dc.ClosePath()
	dc.Fill()

	// ── 6. Glühende Augen ────────────────────────────────────────────────────
	eyeY := visorTop + visorH*0.50
	eyeW := visorW * 0.25
	eyeH := visorH * 0.38
	eyeLX := cx - visorW*0.22
	eyeRX := cx + visorW*0.22
	eyeI := 0.70 + eye*0.30
	eyeS := 1.0 + eye*0.10

	for _, ex := range []float64{eyeLX, eyeRX} {
		// Glow-Ringe
		for i := 7; i >= 0; i-- {
			fi := float64(i)
			alpha := eyeI * (1.0 - fi/8.0) * 0.45
			dc.DrawEllipse(ex, eyeY, eyeW*eyeS*(1+fi*0.14), eyeH*eyeS*(1+fi*0.20))
			dc.SetRGBA(rC, gC, bC, alpha)
			dc.Fill()
		}
		// Haupt-Auge
		dc.DrawEllipse(ex, eyeY, eyeW*eyeS, eyeH*eyeS)
		dc.SetRGBA(rC*0.5+0.4, gC*0.9+0.08, bC, eyeI)
		dc.Fill()
		// Heller Kern
		dc.DrawEllipse(ex, eyeY, eyeW*eyeS*0.45, eyeH*eyeS*0.45)
		dc.SetRGBA(1.0, 1.0, 1.0, eyeI*0.85)
		dc.Fill()
	}

	// ── 7. Nase (kleines Gold-Panel) ─────────────────────────────────────────
	noseY := visorTop + visorH + H*0.005
	dc.SetRGBA(0.75, 0.55, 0.12, 0.9)
	dc.MoveTo(cx, noseY)
	dc.LineTo(cx-W*0.045, noseY+H*0.055)
	dc.LineTo(cx+W*0.045, noseY+H*0.055)
	dc.ClosePath()
	dc.Fill()

	// ── 8. Tech-Detail-Linien ─────────────────────────────────────────────────
	dc.SetLineWidth(0.8)
	dc.SetRGBA(0.9, 0.72, 0.22, 0.4)
	// Stirn-Linien
	for _, yo := range []float64{0.05, 0.11} {
		dc.DrawLine(cx-headW*0.24, headTop+H*yo, cx+headW*0.24, headTop+H*yo)
		dc.Stroke()
	}
	// Platten-Trennlinien
	dc.DrawLine(cx-headW*0.28, cy-headH*0.08, cx-headW*0.28, cy+headH*0.22)
	dc.Stroke()
	dc.DrawLine(cx+headW*0.28, cy-headH*0.08, cx+headW*0.28, cy+headH*0.22)
	dc.Stroke()
	// Kinn-Mittellinie
	dc.DrawLine(cx, cy+headH*0.21, cx, headBot-H*0.04)
	dc.Stroke()

	// ── 9. Scan-Linie ─────────────────────────────────────────────────────────
	scanY := headTop + scan*(headBot-headTop)
	for i := 0; i < 4; i++ {
		alpha := (0.12 - float64(i)*0.025) * glowI * 1.5
		dc.SetLineWidth(1.5)
		dc.SetRGBA(rC, gC, bC, alpha)
		dc.DrawLine(cx-headW*0.47, scanY-float64(i)*1.8, cx+headW*0.47, scanY-float64(i)*1.8)
		dc.Stroke()
	}

	// ── 10. Equalizer / Mund-Bereich ──────────────────────────────────────────
	barBaseY := cy + headH*0.28
	if mode == ModeSpeaking || mode == ModeListening {
		numBars := 7
		barW := W * 0.033
		barGap := W * 0.011
		total := float64(numBars)*(barW+barGap) - barGap
		startX := cx - total/2
		for i := 0; i < numBars; i++ {
			phase := speak + float64(i)*0.19
			barH := H * 0.032 * (0.25 + 0.75*math.Abs(math.Sin(phase*math.Pi*2+float64(i))))
			bx := startX + float64(i)*(barW+barGap)
			by := barBaseY - barH/2
			alpha := 0.55 + 0.45*speak
			dc.SetRGBA(rC, gC, bC, alpha)
			dc.DrawRectangle(bx, by, barW, barH)
			dc.Fill()
		}
	} else {
		dc.SetRGBA(0.9, 0.70, 0.22, 0.4)
		dc.SetLineWidth(1.5)
		dc.DrawLine(cx-W*0.09, barBaseY, cx+W*0.09, barBaseY)
		dc.Stroke()
	}

	// ── 11. Helm-Kontur (Gold) ────────────────────────────────────────────────
	dc.SetLineWidth(1.2)
	dc.SetRGBA(0.85, 0.65, 0.20, 0.55)
	helmPath(dc, cx, cy, headW, headH, headTop, headBot)
	dc.Stroke()

	return dc.Image()
}

// helmPath zeichnet die Kopf-Silhouette-Kurve.
func helmPath(dc *gg.Context, cx, cy, headW, headH, headTop, headBot float64) {
	dc.MoveTo(cx, headTop)
	dc.CubicTo(cx+headW/2, headTop, cx+headW/2, cy, cx+headW*0.45, cy+headH*0.15)
	dc.CubicTo(cx+headW*0.32, cy+headH*0.38, cx+headW*0.15, headBot-headH*0.02, cx, headBot)
	dc.CubicTo(cx-headW*0.15, headBot-headH*0.02, cx-headW*0.32, cy+headH*0.38, cx-headW*0.45, cy+headH*0.15)
	dc.CubicTo(cx-headW/2, cy, cx-headW/2, headTop, cx, headTop)
	dc.ClosePath()
}

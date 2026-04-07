# Jarvis – Projektweit einheitliches Design

> **Zentrales Nachschlagewerk für alle Design-Entscheidungen im Jarvis-Projekt.**
> Gilt für: Web-Frontend, Landing Page (jarvis-ai.info), Android App, Windows App, CLI-Tools.

---

## Inhalt

1. [Leitprinzip & Fehlendes Design](#1-leitprinzip--fehlendes-design)
2. [Markenkern & Identität](#2-markenkern--identität)
3. [Logo-System: „J im Kreis"](#3-logo-system-j-im-kreis)
4. [Ironman-Avatar](#4-ironman-avatar)
5. [Farbpalette](#5-farbpalette)
6. [Typografie](#6-typografie)
7. [Glassmorphism-System](#7-glassmorphism-system)
8. [Abstands- & Radius-System](#8-abstands---radius-system)
9. [Schatten- & Glow-System](#9-schatten---glow-system)
10. [Animations-System](#10-animations-system)
11. [Komponenten-Muster](#11-komponenten-muster)
12. [Android App – Spezifika](#12-android-app--spezifika)
13. [Landing Page (jarvis-ai.info) – Spezifika](#13-landing-page-jarvis-aiinfo--spezifika)
14. [Datei-Referenzen](#14-datei-referenzen)

---

## 1. Leitprinzip & Fehlendes Design

### Wenn kein passendes Design vorhanden ist:

**Reihenfolge der Entscheidung:**

1. **Nächstliegendes Design verwenden** – Gibt es ein ähnliches Element im vorhandenen System (z. B. ein ähnlicher Button, eine ähnliche Karte), dessen Stil übernehmen und anpassen. Dabei strikt an Farbpalette, Radius, Schrift und Glassmorphism-System halten.

2. **Aus den Grundprinzipien ableiten** – Das Design folgt immer diesen Kernwerten:
   - Dunkler Hintergrund (`#0a0e17` / `#111827`)
   - Indigo-Akzent (`#6366f1`) als primäre Highlight-Farbe
   - Glassmorphism mit `backdrop-filter: blur()`
   - Subtile Borders (`rgba(255,255,255,0.08)`)
   - Sanfte Glow-Effekte statt harter Schatten
   - Futuristisch, aber lesbar – kein reiner Cyberpunk-Overload

3. **Rücksprache mit Benutzer halten** – Wenn das neue Element von bestehenden Mustern deutlich abweicht (z. B. ein komplett neuer Screen-Typ, ein Onboarding-Flow, ein neues Icon-Set), **immer zuerst fragen**. Keinen neuen Design-Stil eigenmächtig einführen.

> ⚠️ **Niemals:** Hardcodierte Farben verwenden. Immer CSS-Variablen (`var(--accent)`, `var(--bg-glass)` etc.) nutzen.

---

## 2. Markenkern & Identität

| Eigenschaft | Ausprägung |
|---|---|
| **Name** | JARVIS (Abkürzung, immer Großbuchstaben im Logo) |
| **Charakter** | Autonomer KI-Agent – futuristisch, präzise, vertrauenswürdig |
| **Stil** | Dark Glassmorphism · Indigo-Akzent · Sci-Fi ohne Kitsch |
| **Ton** | Technisch kompetent, direkt, leicht futuristisch |
| **Referenz** | Iron Man's J.A.R.V.I.S. – daher der Ironman-Kopf als Avatar |
| **Primäre Plattformen** | Web (HTTPS Frontend), Android App, Landing Page |

---

## 3. Logo-System: „J im Kreis"

Das zentrale Markenelement des Projekts. Kommt in zwei Größen vor:

### 3a. Logo-Ring (groß) – Login-Screen & Splash

```
┌─────────────────────────────────────────────────────────┐
│  Größe:     120 × 120 px                                │
│  Form:      Kreis (border-radius: 50%)                  │
│  Border:    2px solid #6366f1 (--accent)                │
│  Box-Shadow: 0 0 40px rgba(99,102,241,0.4) (außen)      │
│              inset 0 0 40px rgba(99,102,241,0.4)         │
│                                                         │
│  Inner Ring: 1px solid rgba(99,102,241,0.3)             │
│              rotiert permanent (10s linear infinite)     │
│              border-top-color + border-left-color: transp│
│                                                         │
│  J (Logo-Core):                                         │
│    font-size: 3rem                                      │
│    font-weight: 800                                     │
│    color: #6366f1 (--accent)                            │
│    text-shadow: 0 0 20px rgba(99,102,241,0.4)           │
│    font-family: Inter                                   │
│                                                         │
│  Animation: pulse-ring (3s ease-in-out infinite)        │
│    Glow pulsiert zwischen 30px und 50px blur            │
└─────────────────────────────────────────────────────────┘
```

**HTML-Struktur:**
```html
<div class="jarvis-logo">
    <div class="logo-ring">
        <div class="logo-ring-inner"></div>
        <div class="logo-core">J</div>
    </div>
</div>
```

**Vollständiges CSS:**
```css
.logo-ring {
    width: 120px;
    height: 120px;
    border-radius: 50%;
    border: 2px solid var(--accent);
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    animation: pulse-ring 3s ease-in-out infinite;
    box-shadow: 0 0 40px var(--accent-glow), inset 0 0 40px var(--accent-glow);
}

.logo-ring-inner {
    position: absolute;
    width: 100%;
    height: 100%;
    border-radius: 50%;
    border: 1px solid rgba(99, 102, 241, 0.3);
    animation: rotate-ring 10s linear infinite;
    border-top-color: transparent;
    border-left-color: transparent;
}

.logo-core {
    font-size: 3rem;
    font-weight: 800;
    color: var(--accent);
    text-shadow: 0 0 20px var(--accent-glow);
    font-family: var(--font-body);
}

@keyframes pulse-ring {
    0%, 100% { box-shadow: 0 0 30px var(--accent-glow), inset 0 0 30px var(--accent-glow); }
    50%       { box-shadow: 0 0 50px var(--accent-glow), inset 0 0 50px var(--accent-glow); }
}

@keyframes rotate-ring {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
}
```

---

### 3b. Logo-Mini-Ring – Header (App-Leiste oben links)

```
┌──────────────────────────────────────────┐
│  Größe:   36 × 36 px                    │
│  Border:  1.5px solid #6366f1            │
│  Form:    Kreis (border-radius: 50%)     │
│  J-Core:  font-size: 1rem, weight: 800   │
│           color: #6366f1 (--accent)      │
│  Keine Animation (statisch)              │
└──────────────────────────────────────────┘
```

**HTML-Struktur:**
```html
<div class="logo-mini-ring">
    <div class="logo-mini-core">J</div>
</div>
```

---

### 3c. Android App Icon

```
┌──────────────────────────────────────────────────────┐
│  Format:       Adaptive Icon (Android 8.0+)          │
│                + Bitmap-Fallbacks (mdpi → xxxhdpi)   │
│  Hintergrund:  #0A0A0F (fast schwarz)                │
│  Vordergrund:  "J" in Weiß (#FFFFFF)                 │
│  Icon-Shape:   Runder/quadratischer Clip (System)    │
│  Datei:        ic_launcher_fg.png (alle Dichten)     │
│  Viewbox:      108 × 108 dp                          │
└──────────────────────────────────────────────────────┘
```

Pfad: `android/app/src/main/res/mipmap-*/ic_launcher*.png`

---

### 3d. Favicon (Web)

Pfad: `frontend/favicon*.png`

| Datei | Größe |
|---|---|
| `favicon_16.png` | 16 × 16 px |
| `favicon_32.png` | 32 × 32 px |
| `favicon_48.png` | 48 × 48 px |
| `favicon_64.png` | 64 × 64 px |
| `favicon_128.png` | 128 × 128 px |
| `favicon_256.png` | 256 × 256 px |
| `favicon_512.png` | 512 × 512 px |

---

## 4. Ironman-Avatar

```
┌──────────────────────────────────────────────────────┐
│  Datei:   windows-app-go/ironman_avatar.png          │
│  Motiv:   Iron Man Helm – Frontansicht               │
│           Gold/Rot Farbgebung, leuchtende Augen      │
│  Einsatz: Avatar/Profilbild des Agenten in der       │
│           Windows App, ggf. Chat-Avatare             │
│  Style:   Freigestellt (transparenter Hintergrund)   │
│                                                      │
│  Bedeutung: Referenz auf Marvel's J.A.R.V.I.S. –    │
│  Iron Man's KI-Assistent. Verstärkt die Marken-      │
│  identität des Projekts als smarter KI-Agent.        │
└──────────────────────────────────────────────────────┘
```

Weitere Bildreferenz: `jarvis.jpg` im Projektstamm (allgemeines Branding-Bild).

> **Einsatz-Regel:** Der Ironman-Avatar ist das "Gesicht" des Agenten in Chat-Interfaces. Das „J im Kreis" ist das abstrakte Markenzeichen für App-Icons, Header und Login-Screens.

---

## 5. Farbpalette

### CSS-Variablen (`:root` in `frontend/css/style.css`)

```css
/* ── Hintergründe ── */
--bg-primary:      #0a0e17;                    /* Deep Navy – Main Background */
--bg-secondary:    #111827;                    /* Dark Gray-Blue – Secondary Areas */
--bg-glass:        rgba(15, 23, 42, 0.75);     /* Glassmorphic – Cards, Panels */
--bg-glass-heavy:  rgba(15, 23, 42, 0.9);      /* Starkes Glas – dichte Bereiche */

/* ── Borders ── */
--border:          rgba(255, 255, 255, 0.08);  /* Standard */
--border-hover:    rgba(255, 255, 255, 0.15);  /* Hover-State */

/* ── Text ── */
--text-primary:    #f8fafc;   /* Off-White – Haupttext */
--text-secondary:  #94a3b8;   /* Slate-Gray – Sekundärtext */
--text-muted:      #64748b;   /* Dim Gray – deaktiviert, Platzhalter */

/* ── Akzentfarbe (Indigo) ── */
--accent:          #6366f1;                    /* Primäre Highlight-Farbe */
--accent-glow:     rgba(99, 102, 241, 0.4);    /* Glow/Halos */
--accent-hover:    #818cf8;                    /* Hover-State */
--accent-light:    rgba(99, 102, 241, 0.1);    /* Sehr heller Hintergrund */

/* ── Status-Farben ── */
--success:  #10b981;   /* Emerald – aktiv, OK, verbunden */
--warning:  #f59e0b;   /* Amber – Warnungen */
--danger:   #ef4444;   /* Rot – Fehler, Löschen */
--info:     #3b82f6;   /* Blau – Information */
```

### Visuelle Referenz

| Farbe | Hex | Verwendung |
|---|---|---|
| ![#0a0e17](https://via.placeholder.com/12/0a0e17/0a0e17) Deep Navy | `#0a0e17` | Haupthintergrund |
| ![#111827](https://via.placeholder.com/12/111827/111827) Dark Gray-Blue | `#111827` | Sekundärer Hintergrund |
| ![#6366f1](https://via.placeholder.com/12/6366f1/6366f1) Indigo | `#6366f1` | Akzent, Buttons, Icons, Logo |
| ![#818cf8](https://via.placeholder.com/12/818cf8/818cf8) Light Indigo | `#818cf8` | Akzent Hover |
| ![#10b981](https://via.placeholder.com/12/10b981/10b981) Emerald | `#10b981` | Erfolg / Online |
| ![#f59e0b](https://via.placeholder.com/12/f59e0b/f59e0b) Amber | `#f59e0b` | Warnung |
| ![#ef4444](https://via.placeholder.com/12/ef4444/ef4444) Rot | `#ef4444` | Fehler / Gefahr |
| ![#3b82f6](https://via.placeholder.com/12/3b82f6/3b82f6) Blau | `#3b82f6` | Info |
| ![#f8fafc](https://via.placeholder.com/12/f8fafc/f8fafc) Off-White | `#f8fafc` | Primärtext |
| ![#94a3b8](https://via.placeholder.com/12/94a3b8/94a3b8) Slate | `#94a3b8` | Sekundärtext |
| ![#64748b](https://via.placeholder.com/12/64748b/64748b) Dim Gray | `#64748b` | Muted / inaktiv |

### Landing Page Zusatzfarben (jarvis-ai.info)

| Farbe | Hex | Verwendung |
|---|---|---|
| Cyan | `#06b6d4` | Gradient-Zweite-Farbe im Logo-Text |
| Indigo Dunkel | `#4f46e5` | Button-Gradient-Endpunkt |

---

## 6. Typografie

### Schriftarten

| Font | Quelle | Gewichte | Verwendung |
|---|---|---|---|
| **Inter** | Google Fonts | 300, 400, 500, 600, 700, 800 | Hauptschrift – Body, UI, Headlines, Logo-J |
| **JetBrains Mono** | Google Fonts | 400, 500 | Code, Logs, Terminal-Output |
| **Orbitron** | Google Fonts | 900 | Nur Landing Page – Haupttitel JARVIS |

**Import (Frontend):**
```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

**CSS-Variablen:**
```css
--font-body: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', monospace;
```

### Hierarchie

| Element | Größe | Gewicht | Stil |
|---|---|---|---|
| Login-Titel „JARVIS" | 2.5rem | 800 | Gradient, letter-spacing: 0.3em |
| Landing-Titel | clamp(3.5rem, 10vw, 7rem) | 900 (Orbitron) | Indigo→Cyan Gradient |
| Hauptüberschriften | 1.5–2rem | 700 | `--text-primary` |
| Unterüberschriften | 1–1.25rem | 600 | `--text-primary` |
| Body-Text | 0.875–1rem | 400 | `--text-secondary` |
| Muted/Labels | 0.75–0.875rem | 400–500 | `--text-muted` |
| Code/Logs | 0.875rem | 400 | `--font-mono`, `--text-secondary` |
| Login-Subtitle | 0.95rem | 400 | letter-spacing: 0.15em |

### Logo-Text „JARVIS"
```css
background: linear-gradient(135deg, var(--accent), var(--accent-hover), #a78bfa);
-webkit-background-clip: text;
-webkit-text-fill-color: transparent;
background-clip: text;
letter-spacing: 0.3em;
font-weight: 800;
```

---

## 7. Glassmorphism-System

Das zentrale visuelle Stilmittel des Projekts.

```css
/* Standard Glas-Panel */
background: var(--bg-glass);           /* rgba(15, 23, 42, 0.75) */
border: 1px solid var(--border);       /* rgba(255, 255, 255, 0.08) */
border-radius: var(--radius-md);       /* 12px */
backdrop-filter: blur(20px);
-webkit-backdrop-filter: blur(20px);

/* Schwereres Glas (Modals, Overlays) */
background: var(--bg-glass-heavy);     /* rgba(15, 23, 42, 0.9) */
backdrop-filter: blur(12px);

/* Hover-State (immer) */
border-color: var(--border-hover);     /* rgba(255, 255, 255, 0.15) */
```

### Blur-Stufen

| Stufe | Blur | Einsatz |
|---|---|---|
| Leicht | `blur(8px)` | Tooltips, kleine Popovers |
| Standard | `blur(16px)` | Navigation, Sidebar |
| Stark | `blur(20px)` | Cards, Input-Gruppen |
| Modal | `blur(12px)` | Modale Dialoge (bg-glass-heavy kompensiert) |

---

## 8. Abstands- & Radius-System

```css
--radius-sm:  8px;    /* Kleine Elemente: Badges, Tags, Chips */
--radius-md:  12px;   /* Karten, Inputs, Buttons */
--radius-lg:  16px;   /* Panels, Sidebars, größere Modals */
--radius-xl:  24px;   /* Große Modals, Login-Container */
```

**Spacing-Prinzip:** Multiples von `0.5rem` (8px). Typische Werte: `0.5rem`, `1rem`, `1.5rem`, `2rem`, `2.5rem`.

---

## 9. Schatten- & Glow-System

```css
--shadow-sm:   0 2px 8px rgba(0, 0, 0, 0.3);    /* Subtil, kleine Elemente */
--shadow-md:   0 4px 16px rgba(0, 0, 0, 0.4);   /* Karten, Panels */
--shadow-lg:   0 8px 32px rgba(0, 0, 0, 0.5);   /* Modale, große Overlays */
--shadow-glow: 0 0 30px var(--accent-glow);      /* Akzent-Glow (Focus, Logo) */
```

**Glow-Prinzip:**
- Kein harter Schatten ohne Glow-Komponente
- Glow immer in `--accent-glow` (Indigo) oder Status-Farbe
- `inset` Glow für Logo-Ring und spezielle UI-Elemente

---

## 10. Animations-System

**Standard-Transition:**
```css
--transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
```

### Definierte Animationen

| Name | Dauer | Einsatz |
|---|---|---|
| `pulse-ring` | 3s, ease-in-out, infinite | Logo-Ring – Glow pulsiert |
| `rotate-ring` | 10s, linear, infinite | Logo-Ring-Inner – rotiert |
| `fadeInUp` | 0.8s | Elemente erscheinen von unten |
| `micPulse` | 1.5s | Mikrofon-Button beim Aufnehmen |
| `status-pulse` | 2s | Status-Indikatoren (Online-Punkte) |
| `spin` | 0.6s, linear | Lade-Spinner |
| `countdownPulse` | 1s | VNC-Countdown |
| `wa-pulse` | 1.5s | WhatsApp-Verbindungsanzeige |

**Hover-Muster (Standard):**
```css
transition: var(--transition);
/* Hover: */
transform: translateY(-2px);      /* leichtes Anheben */
border-color: var(--border-hover); /* Border aufhellen */
box-shadow: var(--shadow-glow);    /* Glow einblenden */
```

---

## 11. Komponenten-Muster

### Buttons

**Primary Button:**
```css
background: linear-gradient(135deg, var(--accent), #4f46e5);
color: #fff;
border: none;
border-radius: var(--radius-md);
padding: 0.75rem 1.5rem;
font-weight: 600;
box-shadow: 0 0 24px var(--accent-glow);
/* Hover: */
transform: translateY(-2px);
box-shadow: 0 0 36px var(--accent-glow);
```

**Secondary Button:**
```css
background: var(--bg-glass);
border: 1px solid var(--border);
border-radius: var(--radius-md);
color: var(--text-primary);
backdrop-filter: blur(16px);
/* Hover: */
border-color: var(--border-hover);
```

**Danger Button:**
```css
background: rgba(239, 68, 68, 0.15);
border: 1px solid rgba(239, 68, 68, 0.3);
color: var(--danger);
```

### Input-Felder

```css
background: transparent;
border: none;
color: var(--text-primary);
font-family: var(--font-body);
/* Wrapper .input-group: */
background: var(--bg-glass);
border: 1px solid var(--border);
border-radius: var(--radius-lg);
backdrop-filter: blur(20px);
/* Focus: */
border-color: var(--accent);
box-shadow: var(--shadow-glow);
```

### Karten / Cards

```css
background: var(--bg-glass);
border: 1px solid var(--border);
border-radius: var(--radius-lg);
padding: 1.5rem;
backdrop-filter: blur(20px);
transition: var(--transition);
/* Hover: */
border-color: var(--border-hover);
transform: translateY(-3px);
```

### Status-Indikatoren (Punkte)

```css
/* Online/Aktiv: */
width: 8px; height: 8px;
border-radius: 50%;
background: var(--success);   /* #10b981 */
animation: status-pulse 2s infinite;

/* Warnung: */
background: var(--warning);   /* #f59e0b */

/* Fehler: */
background: var(--danger);    /* #ef4444 */
```

### Navigationsleiste (Header)

```css
background: var(--bg-glass);
border-bottom: 1px solid var(--border);
backdrop-filter: blur(16px);
height: 60px;
position: fixed;
top: 0;
```

---

## 12. Android App – Spezifika

### Theme

```xml
<!-- themes.xml -->
<style name="Theme.JarvisApp" parent="Theme.AppCompat.DayNight.NoActionBar">
    <item name="android:windowBackground">@android:color/black</item>
    <item name="android:statusBarColor">@android:color/transparent</item>
    <item name="android:navigationBarColor">@android:color/transparent</item>
    <item name="android:windowLightStatusBar">false</item>
</style>
```

- **Vollbild / Edge-to-Edge:** Ja (transparente System-Bars)
- **Modus:** DayNight NoActionBar → immer Dark
- **Hintergrund:** Schwarz als Base

### Icon-Spezifikationen

| Dichte | dpi | Icon-Größe |
|---|---|---|
| mdpi | 160 | 48 × 48 px |
| hdpi | 240 | 72 × 72 px |
| xhdpi | 320 | 96 × 96 px |
| xxhdpi | 480 | 144 × 144 px |
| xxxhdpi | 640 | 192 × 192 px |

**Adaptive Icon Layering:**
- Background Layer: `#0A0A0F` (Vollflächig dunkel)
- Foreground Layer: Datei `ic_launcher_fg.png` (J-Motiv)
- Safe Zone: 66dp × 66dp (innerste Zone, kein Clipping)

### Farben (Android)

```xml
<!-- colors.xml -->
<color name="ic_launcher_background">#FF060A12</color>
```

Alle weiteren Farben werden durch das WebView (Frontend-CSS) gesteuert.

---

## 13. Landing Page (jarvis-ai.info) – Spezifika

Die Landing Page teilt die Kernpalette, hat aber eigene Ergänzungen:

### Zusätzliche Design-Elemente

**Logo-Text „JARVIS" auf Landing Page:**
```css
font-family: 'Orbitron', sans-serif;
font-weight: 900;
font-size: clamp(3.5rem, 10vw, 7rem);
background: linear-gradient(135deg, #6366f1, #06b6d4);  /* Indigo → Cyan */
-webkit-background-clip: text;
-webkit-text-fill-color: transparent;
letter-spacing: 0.04em;
```

**Eyebrow-Badge (über Haupttitel):**
```css
display: inline-flex;
align-items: center;
gap: 0.5rem;
background: rgba(255,255,255,0.04);
border: 1px solid rgba(255,255,255,0.12);
border-radius: 999px;
padding: 0.375rem 1rem;
font-size: 0.875rem;
/* Grüner Puls-Punkt: */
width: 6px; height: 6px;
background: #10b981;
border-radius: 50%;
animation: pulse 2s infinite;
```

**Feature-Cards:**
```css
background: rgba(255,255,255,0.04);
border: 1px solid rgba(255,255,255,0.08);
border-radius: 16px;
padding: 2rem;
/* Hover: */
border-color: rgba(255,255,255,0.20);
transform: translateY(-3px);
transition: 0.2s cubic-bezier(0.4,0,0.2,1);
```

**Sprach-Buttons (DE/EN Navigation):**
```css
background: rgba(255,255,255,0.08);
border: 1px solid rgba(255,255,255,0.12);
border-radius: 6px;
padding: 0.25rem 0.75rem;
font-size: 0.75rem;
font-weight: 600;
```

### Breakpoints Landing Page

```css
@media (max-width: 768px) {
    /* Navigation: .nav-links → display: none */
    /* Grids → single-column */
    /* Font-Sizes → via clamp() angepasst */
}
```

---

## 14. Datei-Referenzen

### Design-Quelldateien

| Datei | Beschreibung |
|---|---|
| `frontend/css/style.css` | Haupt-CSS (5000+ Zeilen), alle CSS-Variablen, Komponenten |
| `frontend/index.html` | HTML-Struktur, Logo-DOM, Font-Imports |
| `frontend/favicon*.png` | Favicon-Set (7 Größen) |
| `android/app/src/main/res/values/colors.xml` | Android-Farben |
| `android/app/src/main/res/values/themes.xml` | Android-Theme |
| `android/app/src/main/res/drawable/ic_launcher_background.xml` | Icon-Hintergrund-Vektor |
| `android/app/src/main/res/mipmap-*/ic_launcher*.png` | App-Icons (15 Dateien, 5 Dichten × 3 Varianten) |
| `windows-app-go/ironman_avatar.png` | Ironman-Avatar (freigestellt, Gold/Rot) |
| `windows-app-go/jarvis_icon.png` | Jarvis-Icon für Windows-App |
| `jarvis.jpg` | Allgemeines Branding-Bild |
| `docs/favicon.png` | Favicon für Docs |

### Live-Referenzen

| URL | Beschreibung |
|---|---|
| `https://jarvis-ai.info` | Landing Page (öffentlich) |
| `https://191.100.144.1` | Jarvis Web-Frontend (Produktiv, Login erforderlich) |

---

*Zuletzt aktualisiert: 2026-04-06*

# FFmpeg MJPEG Kamera-Stream mit Auto-Restart
# Startet den Stream neu bei Verbindungsabbruch (Error -10054 etc.)
#
# Features:
#   - Automatische Kamera-Erkennung via DirectShow
#   - Auswahlmenue bei mehreren Kameras
#   - Auto-Restart bei Verbindungsabbruch
#
# Strategie:
#   Input: NV12 1080p@60fps (25% kleiner als YUYV)
#   Filter: fps=15 ZUERST (droppt 75% der Frames sofort), dann scale
#   Output: MJPEG 640px @15fps via HTTP
#
# Buffer-Warnungen beim Start sind normal! Zwischen FFmpeg-Start und
# Client-Verbindung staut sich der Buffer, weil -listen 1 blockiert.
# Sobald Jarvis sich verbindet, stabilisiert sich der Stream.

# -- Konfiguration -------------------------------------------------------
$ListenPort   = 8090
$Resolution   = "640:-2"        # Breite 640, Hoehe automatisch
$Quality      = 5               # MJPEG Qualitaet (2=beste, 31=schlechteste)
$BufSize      = "1G"            # Grosser Buffer fuer Rohbild-Daten
$RestartDelay = 3               # Sekunden Pause vor Neustart
$FFmpegPath   = ".\ffmpeg.exe"  # Pfad zu ffmpeg (im selben Ordner)

# -- Kamera-Erkennung ---------------------------------------------------
function Get-AvailableCameras {
    <#
    .SYNOPSIS
        Listet alle DirectShow-Videoquellen via ffmpeg auf.
    #>
    $output = & $FFmpegPath -list_devices true -f dshow -i dummy 2>&1 | Out-String
    $cameras = @()
    $lines = $output -split "`n"
    foreach ($line in $lines) {
        if ($line -match '\[dshow\s+@\s+[0-9a-fx]+\]\s+"(.+?)"\s*\(video\)') {
            $cameras += $Matches[1]
        }
        elseif ($line -match '\[dshow\s+@\s+[0-9a-fx]+\]\s+"(.+?)"' -and $line -notmatch '\(audio\)' -and $line -notmatch 'Alternative name') {
            $name = $Matches[1]
            if ($cameras -notcontains $name -and $name -ne "dummy") {
                $cameras += $name
            }
        }
    }
    return $cameras
}

function Select-Camera {
    <#
    .SYNOPSIS
        Findet automatisch die Kamera oder zeigt ein Auswahlmenue.
        1. Genau eine Kamera → direkt verwenden
        2. Keine Kamera → Fehlermeldung + Abbruch
        3. Mehrere Kameras → Auswahlmenue
    #>
    Write-Host ""
    Write-Host "Suche Kameras..." -ForegroundColor Gray

    $cameras = Get-AvailableCameras

    if ($cameras.Count -eq 0) {
        Write-Host ""
        Write-Host "  FEHLER: Keine Kamera gefunden!" -ForegroundColor Red
        Write-Host "  Bitte USB-Kamera anschliessen und erneut starten." -ForegroundColor Red
        Write-Host ""
        Read-Host "Druecke Enter zum Beenden"
        exit 1
    }

    # Genau eine Kamera → direkt verwenden
    if ($cameras.Count -eq 1) {
        $cam = $cameras[0]
        Write-Host "  Kamera gefunden: $cam" -ForegroundColor Green
        return $cam
    }

    # Mehrere Kameras → Auswahlmenue
    Write-Host ""
    Write-Host "  Mehrere Kameras gefunden:" -ForegroundColor Yellow
    Write-Host ""
    for ($i = 0; $i -lt $cameras.Count; $i++) {
        Write-Host "    [$($i + 1)] $($cameras[$i])" -ForegroundColor Cyan
    }
    Write-Host ""

    while ($true) {
        $input = Read-Host "  Kamera auswaehlen (1-$($cameras.Count))"
        $num = 0
        if ([int]::TryParse($input, [ref]$num) -and $num -ge 1 -and $num -le $cameras.Count) {
            $selected = $cameras[$num - 1]
            Write-Host "  Ausgewaehlt: $selected" -ForegroundColor Green
            return $selected
        }
        Write-Host "  Ungueltige Eingabe. Bitte 1-$($cameras.Count) eingeben." -ForegroundColor Red
    }
}

# -- Kamera ermitteln ----------------------------------------------------
$CameraName = Select-Camera

# -- Hauptschleife --------------------------------------------------------
$restartCount = 0

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  FFmpeg MJPEG Kamera-Stream (Auto-Restart)" -ForegroundColor Cyan
Write-Host "  Kamera:  $CameraName" -ForegroundColor Gray
Write-Host "  URL:     http://0.0.0.0:$ListenPort/feed" -ForegroundColor Gray
Write-Host "  Buffer:  $BufSize (Warnungen beim Start sind normal!)" -ForegroundColor Gray
Write-Host "  Stoppen: Ctrl+C" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Diese URL in Jarvis Vision-Einstellungen eintragen:" -ForegroundColor Green
Write-Host "  http://<DEINE-IP>:$ListenPort/feed" -ForegroundColor White
Write-Host ""

while ($true) {
    $restartCount++
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    if ($restartCount -eq 1) {
        Write-Host "[$timestamp] Stream wird gestartet..." -ForegroundColor Green
        Write-Host "[$timestamp] HINWEIS: Buffer-Warnungen vor Client-Verbindung sind normal." -ForegroundColor DarkGray
    } else {
        Write-Host "[$timestamp] Neustart #$($restartCount - 1) nach Verbindungsabbruch..." -ForegroundColor Yellow
    }

    $filter = "fps=15,scale=$Resolution"
    $ffArgs = "-f dshow -rtbufsize $BufSize -thread_queue_size 1024 -pixel_format nv12 -i `"video=$CameraName`" -vf `"$filter`" -q:v $Quality -f mjpeg -listen 1 http://0.0.0.0:${ListenPort}/feed"
    $process = Start-Process -FilePath $FFmpegPath -ArgumentList $ffArgs -NoNewWindow -PassThru -Wait

    $exitCode = $process.ExitCode
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    if ($exitCode -eq 0) {
        Write-Host "[$timestamp] FFmpeg normal beendet (Exit 0)." -ForegroundColor Gray
    } else {
        Write-Host "[$timestamp] FFmpeg beendet mit Exit-Code $exitCode - Neustart in ${RestartDelay}s..." -ForegroundColor Red
    }

    Start-Sleep -Seconds $RestartDelay
}

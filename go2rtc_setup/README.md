# go2rtc Setup – USB-Kamera als Netzwerk-Stream (Windows)

## 1. Download

go2rtc herunterladen:
https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_win64.zip

ZIP entpacken → `go2rtc.exe` in diesen Ordner legen.

## 2. Kamera-Name herausfinden

```powershell
.\go2rtc.exe --dshow
```

Zeigt alle verfuegbaren DirectShow-Geraete (Kameras + Mikrofone).
Den Kamera-Namen in `go2rtc.yaml` eintragen.

## 3. Starten

```powershell
.\go2rtc.exe
```

Web-UI: http://localhost:1984
RTSP-Stream: rtsp://DEINE_IP:8554/webcam

## 4. In Jarvis verwenden

In Vision-Einstellungen als Kamera-Quelle eintragen:
```
rtsp://192.168.x.x:8554/webcam
```

## 5. Windows-Firewall

Falls Jarvis-Server nicht zugreifen kann:
- Windows Firewall → Eingehende Regel → Port 8554 (TCP) freigeben
- Oder: go2rtc.exe bei erster Ausfuehrung Netzwerkzugriff erlauben

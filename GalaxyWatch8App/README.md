# GalaxyWatch8App

Minimales, lauffähiges Wear-OS-Projekt für die **Samsung Galaxy Watch 8**
(Wear OS 6 / One UI Watch) mit **Kotlin** und **Jetpack Compose for Wear OS**.

Die App zeigt die Uhrzeit (`TimeText`), einen zentrierten Text und einen Button.
Jeder Tap erhöht einen Zähler.

## Tech-Stack
- Kotlin 2.0.21, Android Gradle Plugin 8.7.3
- Jetpack Compose (BOM 2024.12.01) + Compose for Wear OS 1.4.1
- compileSdk 35, minSdk 30 (Wear OS 3+), targetSdk 34
- Gradle 8.11.1 (Wrapper enthalten)

## Projektstruktur
```
GalaxyWatch8App/
├── settings.gradle.kts
├── build.gradle.kts                 # Root-Build (Plugins)
├── gradle.properties
├── gradle/
│   ├── libs.versions.toml           # Version-Catalog
│   └── wrapper/                      # Gradle-Wrapper (inkl. JAR)
├── gradlew / gradlew.bat
└── app/
    ├── build.gradle.kts
    ├── proguard-rules.pro
    └── src/main/
        ├── AndroidManifest.xml
        ├── java/com/example/galaxywatch8/presentation/
        │   ├── MainActivity.kt
        │   └── theme/ (Theme.kt, Color.kt)
        └── res/
            ├── values/ (strings.xml, styles.xml)
            ├── drawable/ + mipmap-anydpi-v26/   # Adaptive Launcher-Icon
```

## Bauen & Installieren

```bash
# Debug-APK bauen
./gradlew assembleDebug

# Auf verbundene Watch / Emulator installieren (ADB über WLAN gekoppelt)
./gradlew installDebug
```

Alternativ einfach den Ordner in **Android Studio** (Ladybug+) öffnen und auf
einem Wear-OS-Emulator oder der Galaxy Watch 8 (Developer Mode + ADB-Debugging)
starten.

## Hinweise
- `local.properties` mit `sdk.dir=...` wird von Android Studio automatisch
  erzeugt. Beim CLI-Build ggf. die Umgebungsvariable `ANDROID_HOME` setzen.
- Das Standalone-Flag im Manifest erlaubt den Betrieb ohne gekoppeltes Phone.

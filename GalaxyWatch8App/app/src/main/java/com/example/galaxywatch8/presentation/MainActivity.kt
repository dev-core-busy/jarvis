package com.example.galaxywatch8.presentation

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.TimeText
import androidx.wear.tooling.preview.devices.WearDevices
import com.example.galaxywatch8.presentation.theme.GalaxyWatch8AppTheme

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        // Wear-OS-Splashscreen anzeigen, solange die Activity startet
        installSplashScreen()

        super.onCreate(savedInstanceState)

        setContent {
            WearApp()
        }
    }
}

/**
 * Hauptbildschirm der App: zeigt die Uhrzeit, einen zaehlenden Text und einen
 * zentrierten Button. Bei jedem Tippen wird der Zaehler erhoeht.
 */
@Composable
fun WearApp() {
    GalaxyWatch8AppTheme {
        // Zustand fuer den Klick-Zaehler – ueberlebt Recompositions
        var counter by remember { mutableIntStateOf(0) }

        // TimeText zeigt die aktuelle Uhrzeit am oberen Rand (Wear-OS-Konvention)
        TimeText()

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text(
                textAlign = TextAlign.Center,
                color = MaterialTheme.colors.primary,
                text = if (counter == 0) {
                    "Galaxy Watch 8\nTippe den Button"
                } else {
                    "Geklickt: $counter"
                }
            )

            Button(
                modifier = Modifier.padding(top = 12.dp),
                onClick = { counter++ }
            ) {
                Text(text = "Tippen")
            }
        }
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showSystemUi = true)
@Composable
fun DefaultPreview() {
    WearApp()
}

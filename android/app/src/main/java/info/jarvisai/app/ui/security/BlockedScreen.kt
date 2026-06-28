package info.jarvisai.app.ui.security

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import info.jarvisai.app.data.model.BlockInfo
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Vollbild-Sperr-Ansicht: zeigt Grund + Protokoll der verdaechtigen
 * Aktivitaeten. Wird ueber allem angezeigt, solange das Konto gesperrt ist –
 * nur ein lokaler Administrator kann serverseitig wieder freischalten.
 */
@Composable
fun BlockedScreen(info: BlockInfo) {
    val fmt = remember { SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()) }
    val cs = MaterialTheme.colorScheme
    Box(
        Modifier
            .fillMaxSize()
            .background(cs.background)
            .systemBarsPadding(),
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(20.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Text("🚫 Konto gesperrt", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = cs.onBackground)
            Spacer(Modifier.height(12.dp))
            Text(
                "Dein Konto wurde wegen eines erkannten Sicherheitsverstoßes " +
                    "(Jailbreak-/Manipulationsversuch) gesperrt. Bitte wende dich an einen " +
                    "lokalen Administrator, um es wieder freischalten zu lassen.",
                fontSize = 14.sp, color = cs.onSurfaceVariant,
            )
            if (info.reason.isNotBlank()) {
                Spacer(Modifier.height(10.dp))
                Text("Grund: ${info.reason}", fontSize = 14.sp, color = cs.error)
            }
            Spacer(Modifier.height(18.dp))
            Text("Protokoll der verdächtigen Aktivitäten", fontWeight = FontWeight.Bold, color = cs.onBackground)
            Spacer(Modifier.height(8.dp))
            if (info.incidents.isEmpty()) {
                Text("Keine Vorfälle protokolliert.", fontSize = 14.sp, color = cs.onSurfaceVariant)
            } else {
                // neueste zuerst
                info.incidents.reversed().forEach { inc ->
                    Spacer(Modifier.height(10.dp))
                    Text(
                        "${fmt.format(Date(inc.ts * 1000))} · ${inc.channel} · ${inc.pattern}",
                        fontSize = 12.sp, color = cs.onSurfaceVariant,
                    )
                    Text(inc.snippet, fontSize = 14.sp, color = cs.onBackground)
                    Spacer(Modifier.height(6.dp))
                    Box(Modifier.fillMaxWidth().height(1.dp).background(cs.outlineVariant))
                }
            }
        }
    }
}

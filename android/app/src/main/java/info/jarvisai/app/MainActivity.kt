package info.jarvisai.app

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import dagger.hilt.android.AndroidEntryPoint
import info.jarvisai.app.ui.chat.ChatScreen
import info.jarvisai.app.ui.issues.IssuesScreen
import info.jarvisai.app.ui.security.BlockViewModel
import info.jarvisai.app.ui.security.BlockedScreen
import info.jarvisai.app.ui.settings.SettingsScreen
import info.jarvisai.app.ui.theme.JarvisTheme

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* Permissions verarbeitet */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Berechtigungen anfragen
        val perms = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permissionLauncher.launch(perms.toTypedArray())

        setContent {
            JarvisTheme {
                JarvisNavGraph()
            }
        }
    }

    /** Wird aufgerufen wenn eine zweite Instanz gestartet wird (singleTask).
     *  Bringt das bestehende Fenster in den Vordergrund – keine Notification. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        moveTaskToFront()
    }

    private fun moveTaskToFront() {
        val am = getSystemService(ACTIVITY_SERVICE) as android.app.ActivityManager
        am.moveTaskToFront(taskId, 0)
    }
}

@Composable
private fun JarvisNavGraph() {
    // Sicherheitsschicht: ist das Konto gesperrt, alles durch den Sperr-Screen ersetzen.
    val blockVm: BlockViewModel = hiltViewModel()
    val blockInfo by blockVm.blockInfo.collectAsState()
    if (blockInfo?.blocked == true) {
        BlockedScreen(blockInfo!!)
        return
    }

    val navController = rememberNavController()
    NavHost(navController = navController, startDestination = "chat") {
        composable("chat") {
            ChatScreen(
                onOpenSettings = { navController.navigate("settings") },
                onOpenIssues = { navController.navigate("issues") },
            )
        }
        composable("settings") {
            SettingsScreen(
                onBack = { navController.popBackStack() }
            )
        }
        composable("issues") {
            IssuesScreen(
                onBack = { navController.popBackStack() }
            )
        }
    }
}

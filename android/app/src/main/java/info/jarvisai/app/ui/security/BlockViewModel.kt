package info.jarvisai.app.ui.security

import androidx.lifecycle.ViewModel
import dagger.hilt.android.lifecycle.HiltViewModel
import info.jarvisai.app.data.model.BlockInfo
import info.jarvisai.app.data.repository.ChatRepository
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject

/**
 * Schlankes ViewModel nur fuer die Konto-Sperre. Liest den (Singleton-)
 * ChatRepository-Flow OHNE Seiteneffekte (kein WS-Connect), damit es auf
 * NavGraph-Ebene neben dem ChatViewModel existieren kann.
 */
@HiltViewModel
class BlockViewModel @Inject constructor(
    repo: ChatRepository,
) : ViewModel() {
    val blockInfo: StateFlow<BlockInfo?> = repo.blockInfo
}

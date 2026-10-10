package com.ifinmail.app.shared.ui.platform

import android.content.Intent
import android.os.Environment
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import java.io.File

@Composable
actual fun PlatformBackHandler(enabled: Boolean, onBack: () -> Unit) {
    BackHandler(enabled = enabled, onBack = onBack)
}

@Composable
actual fun rememberPlatformSaveText(): (String, String) -> String? {
    val context = LocalContext.current
    return remember(context) {
        { fileName: String, content: String ->
            val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: context.filesDir
            val file = File(dir, fileName)
            try {
                file.writeText(content)
                val share = Intent(Intent.ACTION_SEND)
                share.type = "text/plain"
                share.putExtra(Intent.EXTRA_SUBJECT, fileName)
                share.putExtra(Intent.EXTRA_TEXT, content)
                context.startActivity(Intent.createChooser(share, "Export $fileName"))
                file.absolutePath
            } catch (t: Throwable) {
                null
            }
        }
    }
}

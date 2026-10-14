package com.ifinmail.app.shared.ui.platform

import android.content.ClipData
import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.FileProvider
import java.io.File

@Composable
actual fun PlatformBackHandler(enabled: Boolean, onBack: () -> Unit) {
    BackHandler(enabled = enabled, onBack = onBack)
}

/**
 * Writes the export to the app cache and offers it to the share sheet through a FileProvider URI.
 * The content is never put in the Intent itself: a mailbox export easily exceeds the ~1MB binder
 * limit, which would make the share fail.
 *
 * Returns the file path, or null if the export could not be written or shared.
 */
@Composable
actual fun rememberPlatformSaveText(): (fileName: String, content: String) -> String? {
    val context = LocalContext.current
    return remember(context) {
        { fileName: String, content: String ->
            try {
                val dir = File(context.cacheDir, "exports").apply { mkdirs() }
                // The name comes from the app, but never let a separator escape the export folder.
                val file = File(dir, File(fileName).name)
                file.writeText(content)
                val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
                val share = Intent(Intent.ACTION_SEND).apply {
                    type = "application/mbox"
                    putExtra(Intent.EXTRA_STREAM, uri)
                    putExtra(Intent.EXTRA_SUBJECT, file.name)
                    clipData = ClipData.newRawUri(file.name, uri)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                val chooser = Intent.createChooser(share, "Export ${file.name}")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(chooser)
                file.absolutePath
            } catch (t: Throwable) {
                null
            }
        }
    }
}

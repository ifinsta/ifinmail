package com.ifinmail.app.shared.ui.screens

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import android.webkit.WebView

@Composable
internal actual fun HtmlContentView(html: String) {
    AndroidView(
        factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = false
                setBackgroundColor(0x00000000)
            }
        },
        update = { webView ->
            webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
        }
    )
}

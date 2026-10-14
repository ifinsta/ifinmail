package com.ifinmail.app.shared.ui.screens

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.viewinterop.AndroidView

/**
 * Renders an HTML mail body. Mail is untrusted input, so the view is locked down: no script, no
 * file or content access, and no network loads at all, which also stops tracking pixels and remote
 * images from phoning home when a message is opened. Links leave the app for the system handler
 * instead of navigating inside this view.
 */
@Composable
internal actual fun HtmlContentView(html: String) {
    val textColor = MaterialTheme.colorScheme.onSurface
    val linkColor = MaterialTheme.colorScheme.primary
    val document = remember(html, textColor, linkColor) { wrap(html, textColor, linkColor) }

    AndroidView(
        modifier = Modifier,
        factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = false
                settings.allowFileAccess = false
                settings.allowContentAccess = false
                settings.domStorageEnabled = false
                settings.blockNetworkLoads = true
                settings.setSupportZoom(false)
                setBackgroundColor(android.graphics.Color.TRANSPARENT)
                isVerticalScrollBarEnabled = false
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        val uri: Uri = request.url
                        if (uri.scheme in OPENABLE_SCHEMES) {
                            try {
                                view.context.startActivity(
                                    Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                )
                            } catch (_: ActivityNotFoundException) {
                                // No handler installed for this link; swallow the tap.
                            }
                        }
                        return true
                    }
                }
            }
        },
        update = { webView ->
            webView.loadDataWithBaseURL(null, document, "text/html", "utf-8", null)
        }
    )
}

private val OPENABLE_SCHEMES = setOf("http", "https", "mailto", "tel")

private fun cssColor(color: Color): String {
    val argb = color.toArgb()
    return "#%06X".format(argb and 0xFFFFFF)
}

/** Fits the message to the screen and gives plain HTML the app's text colours in either theme. */
private fun wrap(html: String, text: Color, link: Color): String = """
    <html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      html, body { margin: 0; padding: 0; background: transparent; color: ${cssColor(text)};
                   font-family: sans-serif; font-size: 15px; line-height: 1.5;
                   overflow-wrap: anywhere; word-wrap: break-word; }
      a { color: ${cssColor(link)}; }
      img, table, video { max-width: 100%; height: auto; }
      pre { white-space: pre-wrap; }
    </style>
    </head><body>$html</body></html>
""".trimIndent()

package com.ifinmail.app.shared.ui.screens

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

@Composable
internal actual fun HtmlContentView(html: String) {
    Text(stripHtmlCommonJs(html), style = MaterialTheme.typography.bodyLarge)
}

internal fun stripHtmlCommonJs(html: String): String =
    html.replace(Regex("<[^>]+>"), "").replace("&nbsp;", " ").replace("&amp;", "&")

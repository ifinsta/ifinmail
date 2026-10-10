package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
internal actual fun HtmlContentView(html: String) {
    val stripped = html
        .replace(Regex("<(script|style)[^>]*>[\\s\\S]*?</(script|style)>", RegexOption.IGNORE_CASE), "")
        .replace(Regex("<br\\s*/?>|</p>|</div>", RegexOption.IGNORE_CASE), "\n")
        .replace(Regex("<[^>]+>"), "")
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
    Text(stripped, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.fillMaxWidth())
}

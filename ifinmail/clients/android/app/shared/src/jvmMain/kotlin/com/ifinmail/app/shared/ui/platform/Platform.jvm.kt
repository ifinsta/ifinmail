package com.ifinmail.app.shared.ui.platform

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember

@Composable
actual fun PlatformBackHandler(enabled: Boolean, onBack: () -> Unit) {
}

@Composable
actual fun rememberPlatformSaveText(): (String, String) -> String? = remember { { _, _ -> null } }

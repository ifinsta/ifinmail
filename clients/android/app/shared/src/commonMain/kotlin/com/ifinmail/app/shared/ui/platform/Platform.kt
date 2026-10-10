package com.ifinmail.app.shared.ui.platform

import androidx.compose.runtime.Composable

@Composable
expect fun PlatformBackHandler(enabled: Boolean = true, onBack: () -> Unit)

@Composable
expect fun rememberPlatformSaveText(): (fileName: String, content: String) -> String?

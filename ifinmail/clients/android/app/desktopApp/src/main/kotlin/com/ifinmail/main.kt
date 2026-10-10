package com.ifinmail

import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import com.ifinmail.app.shared.ui.App

fun main() = application {
    Window(
        onCloseRequest = ::exitApplication,
        title = "Ifinmail",
    ) {
        App()
    }
}

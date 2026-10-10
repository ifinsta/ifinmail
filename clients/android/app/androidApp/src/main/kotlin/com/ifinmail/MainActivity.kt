package com.ifinmail

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.ifinmail.app.shared.ui.App

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        val controller = RealMailController(storeDirPath = filesDir.absolutePath, context = this)

        setContent {
            App(mailController = controller)
        }
    }
}

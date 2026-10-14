package com.ifinmail

import android.app.Application
import android.graphics.Color
import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.lifecycle.AndroidViewModel
import com.ifinmail.app.shared.ui.App
import com.ifinmail.update.AppUpdates

/**
 * Owns the mail engine for the lifetime of the process-bound view model, so configuration
 * changes never rebuild the engine or its credential store.
 */
class MailViewModel(application: Application) : AndroidViewModel(application) {
    val controller = RealMailController(
        storeDirPath = application.filesDir.absolutePath,
        context = application
    )
}

class MainActivity : ComponentActivity() {
    private val mail: MailViewModel by viewModels()
    private val updates by lazy { AppUpdates.get(this) }

    private val notificationPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { updates.refreshNotificationState() }

    private val preferences by lazy { getSharedPreferences("ifinmail_preferences", MODE_PRIVATE) }

    /** "system" (default), "light" or "dark". */
    private fun storedThemeOverride(): Boolean? = when (preferences.getString(KEY_THEME, THEME_SYSTEM)) {
        THEME_DARK -> true
        THEME_LIGHT -> false
        else -> null
    }

    private fun storeThemeOverride(dark: Boolean?) {
        val value = when (dark) {
            true -> THEME_DARK
            false -> THEME_LIGHT
            null -> THEME_SYSTEM
        }
        preferences.edit().putString(KEY_THEME, value).apply()
    }

    private companion object {
        const val KEY_THEME = "theme"
        const val THEME_SYSTEM = "system"
        const val THEME_LIGHT = "light"
        const val THEME_DARK = "dark"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        // A permission prompt where Android has one (13+); the app's notification settings elsewhere.
        updates.notificationPermissionRequester = {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else {
                startActivity(
                    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                        .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                )
            }
        }
        AppUpdates.scheduleBackgroundChecks(this)

        setContent {
            App(
                mailController = mail.controller,
                updateController = if (updates.enabled) updates else null,
                initialThemeOverride = storedThemeOverride(),
                onThemeOverrideChanged = ::storeThemeOverride,
                onDarkThemeChanged = { dark ->
                    // The in-app theme can differ from the system's, so the system bar icons
                    // are restyled to stay legible against the colour Compose draws behind them.
                    val style = if (dark) {
                        SystemBarStyle.dark(Color.TRANSPARENT)
                    } else {
                        SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
                    }
                    enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
                }
            )
        }
    }

    override fun onResume() {
        super.onResume()
        // Back from the install-permission screen, or simply back to the app: keep updates current.
        updates.onResumed()
        updates.checkIfDue()
    }
}

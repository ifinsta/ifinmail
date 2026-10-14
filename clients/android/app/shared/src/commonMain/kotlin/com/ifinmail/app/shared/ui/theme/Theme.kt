package com.ifinmail.app.shared.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

object IfinmailColors {
    val Blue600 = Color(0xFF1A56DB)
    val Blue500 = Color(0xFF3B6FE8)
    val Blue100 = Color(0xFFE8F0FE)
    val Blue050 = Color(0xFFF0F4FF)
    val Navy = Color(0xFF0F2B5B)

    val Gray900 = Color(0xFF111827)
    val Gray700 = Color(0xFF374151)
    val Gray500 = Color(0xFF6B7280)
    /** Darkest of the "subtle" greys that still clears 4.5:1 on Gray100 cards (Gray500 is 4.4:1). */
    val Gray550 = Color(0xFF656C78)
    val Gray400 = Color(0xFF9CA3AF)
    val Gray300 = Color(0xFFD1D5DB)
    val Gray200 = Color(0xFFE5E7EB)
    val Gray100 = Color(0xFFF3F4F6)
    val Gray050 = Color(0xFFF9FAFB)
    val White = Color(0xFFFFFFFF)

    val Red600 = Color(0xFFDC2626)
    val Red700 = Color(0xFFB91C1C)
    val Red100 = Color(0xFFFEE2E2)
    val Amber600 = Color(0xFFD97706)
    val Amber100 = Color(0xFFFEF3C7)
    val Green600 = Color(0xFF059669)
    val Green700 = Color(0xFF047857)
    val Green100 = Color(0xFFD1FAE5)

    val DarkBlue600 = Color(0xFF3B82F6)
    val DarkBlue500 = Color(0xFF60A5FA)
    val DarkBlue100Tint = Color(0xFF1E3A8A)
    val DarkBlue050 = Color(0xFF172554)
    val DarkNavy = Color(0xFF1E3A8A)
}

internal fun ifinmailLightSchema() = lightColorScheme(
    primary = IfinmailColors.Blue600,
    onPrimary = IfinmailColors.White,
    primaryContainer = IfinmailColors.Blue100,
    onPrimaryContainer = IfinmailColors.Navy,
    inversePrimary = IfinmailColors.Blue500,
    secondary = IfinmailColors.Navy,
    onSecondary = IfinmailColors.White,
    secondaryContainer = IfinmailColors.Blue100,
    onSecondaryContainer = IfinmailColors.Navy,
    tertiary = IfinmailColors.Green700,
    onTertiary = IfinmailColors.White,
    tertiaryContainer = IfinmailColors.Green100,
    onTertiaryContainer = IfinmailColors.Gray900,
    background = IfinmailColors.Gray050,
    onBackground = IfinmailColors.Gray900,
    surface = IfinmailColors.White,
    onSurface = IfinmailColors.Gray900,
    surfaceVariant = IfinmailColors.Gray100,
    onSurfaceVariant = IfinmailColors.Gray700,
    surfaceTint = Color.Transparent,
    inverseSurface = IfinmailColors.Gray900,
    inverseOnSurface = IfinmailColors.Gray050,
    error = IfinmailColors.Red700,
    onError = IfinmailColors.White,
    errorContainer = IfinmailColors.Red100,
    onErrorContainer = IfinmailColors.Gray900,
    // outline doubles as the colour for helper text, placeholders and timestamps, so it has to
    // clear 4.5:1 on white (Gray500 = 4.8:1). Gray300 was 1.5:1.
    outline = IfinmailColors.Gray550,
    outlineVariant = IfinmailColors.Gray200,
    // Menus, dialogs and sheets read the surfaceContainer* roles; leaving them at their
    // baseline defaults paints light popups over the dark scheme.
    surfaceDim = IfinmailColors.Gray200,
    surfaceBright = IfinmailColors.White,
    surfaceContainerLowest = IfinmailColors.White,
    surfaceContainerLow = IfinmailColors.Gray050,
    surfaceContainer = IfinmailColors.Gray100,
    surfaceContainerHigh = IfinmailColors.White,
    surfaceContainerHighest = IfinmailColors.Gray100,
    scrim = Color(0x80000000)
)

internal fun ifinmailDarkSchema() = darkColorScheme(
    primary = IfinmailColors.DarkBlue500,
    onPrimary = IfinmailColors.Gray900,
    primaryContainer = IfinmailColors.DarkBlue100Tint,
    onPrimaryContainer = IfinmailColors.Blue100,
    inversePrimary = IfinmailColors.DarkBlue600,
    secondary = IfinmailColors.DarkNavy,
    onSecondary = IfinmailColors.Blue100,
    secondaryContainer = Color(0xFF1E3A5F),
    onSecondaryContainer = IfinmailColors.Gray100,
    tertiary = Color(0xFF10B981),
    onTertiary = IfinmailColors.Gray900,
    tertiaryContainer = Color(0xFF064E3B),
    onTertiaryContainer = IfinmailColors.Green100,
    background = Color(0xFF0B1220),
    onBackground = IfinmailColors.Gray050,
    surface = IfinmailColors.Gray900,
    onSurface = IfinmailColors.Gray050,
    surfaceVariant = Color(0xFF1F2937),
    onSurfaceVariant = IfinmailColors.Gray300,
    surfaceTint = Color.Transparent,
    inverseSurface = IfinmailColors.Gray050,
    inverseOnSurface = IfinmailColors.Gray900,
    error = Color(0xFFF87171),
    onError = IfinmailColors.Gray900,
    errorContainer = Color(0xFF7F1D1D),
    onErrorContainer = IfinmailColors.Red100,
    outline = IfinmailColors.Gray400,
    outlineVariant = Color(0xFF374151),
    surfaceDim = Color(0xFF0B1220),
    surfaceBright = Color(0xFF2F3B4F),
    surfaceContainerLowest = Color(0xFF0B1220),
    surfaceContainerLow = IfinmailColors.Gray900,
    surfaceContainer = Color(0xFF1F2937),
    surfaceContainerHigh = Color(0xFF273244),
    surfaceContainerHighest = Color(0xFF2F3B4F),
    scrim = Color(0xB3000000)
)

private val IfinmailTypography = Typography(
    displayLarge = TextStyle(fontSize = 30.sp, lineHeight = 36.sp, fontWeight = FontWeight.SemiBold),
    headlineMedium = TextStyle(fontSize = 20.sp, lineHeight = 26.sp, fontWeight = FontWeight.SemiBold),
    titleLarge = TextStyle(fontSize = 16.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.SemiBold),
    titleSmall = TextStyle(fontSize = 13.sp, lineHeight = 18.sp, fontWeight = FontWeight.Medium),
    bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 24.sp, fontWeight = FontWeight.Normal),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 21.sp, fontWeight = FontWeight.Normal),
    bodySmall = TextStyle(fontSize = 13.sp, lineHeight = 19.sp, fontWeight = FontWeight.Normal),
    labelLarge = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Medium),
    labelMedium = TextStyle(fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium),
    labelSmall = TextStyle(fontSize = 11.sp, lineHeight = 15.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.8.sp)
)

@Composable
fun IfinmailTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = if (darkTheme) ifinmailDarkSchema() else ifinmailLightSchema(),
        typography = IfinmailTypography
    ) {
        // Screens such as Accounts and Add account draw no background of their own; without this
        // they show the window background, which is light even when dark is forced in-app.
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background,
            contentColor = MaterialTheme.colorScheme.onBackground,
            content = content
        )
    }
}

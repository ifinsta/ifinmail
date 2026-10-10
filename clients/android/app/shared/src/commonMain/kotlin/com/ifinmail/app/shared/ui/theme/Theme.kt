package com.ifinmail.app.shared.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
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
    val Gray400 = Color(0xFF9CA3AF)
    val Gray300 = Color(0xFFD1D5DB)
    val Gray200 = Color(0xFFE5E7EB)
    val Gray100 = Color(0xFFF3F4F6)
    val Gray050 = Color(0xFFF9FAFB)
    val White = Color(0xFFFFFFFF)

    val Red600 = Color(0xFFDC2626)
    val Red100 = Color(0xFFFEE2E2)
    val Amber600 = Color(0xFFD97706)
    val Amber100 = Color(0xFFFEF3C7)
    val Green600 = Color(0xFF059669)
    val Green100 = Color(0xFFD1FAE5)

    val DarkBlue600 = Color(0xFF3B82F6)
    val DarkBlue500 = Color(0xFF60A5FA)
    val DarkBlue100Tint = Color(0xFF1E3A8A)
    val DarkBlue050 = Color(0xFF172554)
    val DarkNavy = Color(0xFF1E3A8A)
}

private fun ifinmailLightSchema() = ColorScheme(
    primary = IfinmailColors.Blue600,
    onPrimary = IfinmailColors.White,
    primaryContainer = IfinmailColors.Blue100,
    onPrimaryContainer = IfinmailColors.Navy,
    inversePrimary = IfinmailColors.Blue500,
    secondary = IfinmailColors.Navy,
    onSecondary = IfinmailColors.White,
    secondaryContainer = IfinmailColors.Gray100,
    onSecondaryContainer = IfinmailColors.Gray900,
    tertiary = IfinmailColors.Green600,
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
    error = IfinmailColors.Red600,
    onError = IfinmailColors.White,
    errorContainer = IfinmailColors.Red100,
    onErrorContainer = IfinmailColors.Gray900,
    outline = IfinmailColors.Gray300,
    outlineVariant = IfinmailColors.Gray200,
    scrim = Color(0x80000000)
)

private fun ifinmailDarkSchema() = ColorScheme(
    primary = IfinmailColors.DarkBlue600,
    onPrimary = IfinmailColors.Gray900,
    primaryContainer = IfinmailColors.DarkBlue100Tint,
    onPrimaryContainer = IfinmailColors.Blue100,
    inversePrimary = IfinmailColors.DarkBlue500,
    secondary = IfinmailColors.DarkNavy,
    onSecondary = IfinmailColors.Blue100,
    secondaryContainer = IfinmailColors.Gray700,
    onSecondaryContainer = IfinmailColors.Gray100,
    tertiary = Color(0xFF10B981),
    onTertiary = IfinmailColors.Gray900,
    tertiaryContainer = Color(0xFF064E3B),
    onTertiaryContainer = IfinmailColors.Green100,
    background = IfinmailColors.Gray900,
    onBackground = IfinmailColors.Gray050,
    surface = Color(0xFF111827),
    onSurface = IfinmailColors.Gray050,
    surfaceVariant = IfinmailColors.Gray700,
    onSurfaceVariant = IfinmailColors.Gray300,
    surfaceTint = Color.Transparent,
    inverseSurface = IfinmailColors.Gray050,
    inverseOnSurface = IfinmailColors.Gray900,
    error = Color(0xFFEF4444),
    onError = IfinmailColors.Gray900,
    errorContainer = Color(0xFF7F1D1D),
    onErrorContainer = IfinmailColors.Red100,
    outline = IfinmailColors.Gray500,
    outlineVariant = Color(0xFF4B5563),
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
        typography = IfinmailTypography,
        content = content
    )
}

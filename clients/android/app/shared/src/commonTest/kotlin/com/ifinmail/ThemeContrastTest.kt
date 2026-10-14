package com.ifinmail

import androidx.compose.material3.ColorScheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import com.ifinmail.app.shared.ui.components.avatarPalette
import com.ifinmail.app.shared.ui.theme.ifinmailDarkSchema
import com.ifinmail.app.shared.ui.theme.ifinmailLightSchema
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * WCAG 2.1 contrast audit of the colour pairs the UI actually draws text and controls with.
 * Body text must reach 4.5:1; the pairs listed under [largeOrGraphic] are only used for large
 * text, icons or component outlines, where 3:1 applies.
 */
class ThemeContrastTest {

    private fun ratio(a: Color, b: Color): Double {
        val l1 = a.luminance().toDouble()
        val l2 = b.luminance().toDouble()
        val (hi, lo) = if (l1 >= l2) l1 to l2 else l2 to l1
        return (hi + 0.05) / (lo + 0.05)
    }

    private fun textPairs(s: ColorScheme): List<Triple<String, Color, Color>> = listOf(
        Triple("onSurface/surface", s.onSurface, s.surface),
        Triple("onBackground/background", s.onBackground, s.background),
        Triple("onSurfaceVariant/surface", s.onSurfaceVariant, s.surface),
        Triple("onSurfaceVariant/background", s.onSurfaceVariant, s.background),
        Triple("onSurfaceVariant/surfaceVariant", s.onSurfaceVariant, s.surfaceVariant),
        Triple("onSurface/surfaceVariant", s.onSurface, s.surfaceVariant),
        // outline doubles as the colour for helper text, placeholders and timestamps.
        Triple("outline/surface", s.outline, s.surface),
        Triple("outline/background", s.outline, s.background),
        Triple("outline/surfaceVariant", s.outline, s.surfaceVariant),
        Triple("onPrimary/primary", s.onPrimary, s.primary),
        Triple("primary/surface", s.primary, s.surface),
        Triple("primary/background", s.primary, s.background),
        Triple("primary/surfaceVariant", s.primary, s.surfaceVariant),
        Triple("onPrimaryContainer/primaryContainer", s.onPrimaryContainer, s.primaryContainer),
        Triple("onSecondaryContainer/secondaryContainer", s.onSecondaryContainer, s.secondaryContainer),
        Triple("onTertiaryContainer/tertiaryContainer", s.onTertiaryContainer, s.tertiaryContainer),
        Triple("onErrorContainer/errorContainer", s.onErrorContainer, s.errorContainer),
        Triple("error/surface", s.error, s.surface),
        Triple("error/surfaceVariant", s.error, s.surfaceVariant),
        Triple("tertiary/surface", s.tertiary, s.surface),
        Triple("tertiary/surfaceVariant", s.tertiary, s.surfaceVariant),
        Triple("onSurface/surfaceContainerHigh (dialogs)", s.onSurface, s.surfaceContainerHigh),
        Triple("onSurface/surfaceContainer (menus)", s.onSurface, s.surfaceContainer)
    )

    private val largeOrGraphic: (ColorScheme) -> List<Triple<String, Color, Color>> = { s ->
        listOf(
            // Text-field and chip outlines against the surface they sit on.
            Triple("outline border/surface", s.outline, s.surface),
            Triple("outline border/background", s.outline, s.background)
        )
    }

    private fun assertAll(name: String, scheme: ColorScheme, minimum: Double, pairs: List<Triple<String, Color, Color>>) {
        val failures = pairs
            .map { (label, fg, bg) -> Triple(label, ratio(fg, bg), minimum) }
            .filter { it.second < it.third }
            .map { "${it.first}: ${(it.second * 100).toInt() / 100.0} < ${it.third}" }
        assertTrue(failures.isEmpty(), "$name contrast failures: $failures")
    }

    @Test
    fun lightSchemeTextPairsMeetAA() =
        assertAll("light", ifinmailLightSchema(), 4.5, textPairs(ifinmailLightSchema()))

    @Test
    fun darkSchemeTextPairsMeetAA() =
        assertAll("dark", ifinmailDarkSchema(), 4.5, textPairs(ifinmailDarkSchema()))

    @Test
    fun lightSchemeGraphicPairsMeetNonTextContrast() =
        assertAll("light", ifinmailLightSchema(), 3.0, largeOrGraphic(ifinmailLightSchema()))

    @Test
    fun darkSchemeGraphicPairsMeetNonTextContrast() =
        assertAll("dark", ifinmailDarkSchema(), 3.0, largeOrGraphic(ifinmailDarkSchema()))

    @Test
    fun avatarBackgroundsCarryWhiteInitialsAtAA() {
        val failures = avatarPalette
            .filter { ratio(Color.White, it) < 4.5 }
            .map { "${it} -> ${(ratio(Color.White, it) * 100).toInt() / 100.0}" }
        assertTrue(failures.isEmpty(), "avatar colours below 4.5:1 with white text: $failures")
    }
}

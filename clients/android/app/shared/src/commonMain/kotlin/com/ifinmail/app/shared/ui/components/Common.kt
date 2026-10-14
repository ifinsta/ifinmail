package com.ifinmail.app.shared.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.hide_password
import com.ifinmail.app.shared.resources.show_password
import com.ifinmail.app.shared.resources.star_star
import com.ifinmail.app.shared.resources.star_starred
import org.jetbrains.compose.resources.stringResource

@Composable
fun PrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(8.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
            disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant,
            disabledContentColor = MaterialTheme.colorScheme.outline
        ),
        modifier = modifier.height(44.dp)
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
fun GhostButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(8.dp),
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
            disabledContentColor = MaterialTheme.colorScheme.outline
        ),
        modifier = modifier.height(44.dp)
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
fun LabeledField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    isError: Boolean = false,
    errorText: String? = null,
    helperText: String? = null,
    singleLine: Boolean = true,
    minLines: Int = 1,
    isPassword: Boolean = false,
    keyboardType: KeyboardType = KeyboardType.Text,
    imeAction: ImeAction = ImeAction.Next,
    /** Stable identifier for UI tests; labels are translated, so it must not be derived from them. */
    testTag: String? = null
) {
    var revealed by remember { mutableStateOf(false) }
    val caption = when {
        isError && errorText != null -> errorText
        else -> helperText
    }
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        isError = isError,
        singleLine = singleLine,
        minLines = minLines,
        shape = RoundedCornerShape(8.dp),
        visualTransformation = if (isPassword && !revealed) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions.Default.copy(
            keyboardType = if (isPassword) KeyboardType.Password else keyboardType,
            imeAction = imeAction
        ),
        trailingIcon = if (isPassword) {
            {
                IconButton(onClick = { revealed = !revealed }) {
                    Icon(
                        imageVector = if (revealed) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                        contentDescription = stringResource(if (revealed) Res.string.hide_password else Res.string.show_password)
                    )
                }
            }
        } else {
            null
        },
        supportingText = caption?.let { text -> { Text(text) } },
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = MaterialTheme.colorScheme.primary,
            unfocusedBorderColor = MaterialTheme.colorScheme.outline,
            errorBorderColor = MaterialTheme.colorScheme.error,
            focusedContainerColor = MaterialTheme.colorScheme.surface,
            unfocusedContainerColor = MaterialTheme.colorScheme.surface
        ),
        modifier = modifier.fillMaxWidth().testTag(testTag ?: fieldTestTag(label))
    )
}

fun fieldTestTag(label: String): String =
    label.lowercase()
        .split(Regex("[^a-z0-9]+"))
        .filter { it.isNotBlank() }
        .joinToString("-")
        .let { "field-$it" }

@Composable
fun AvatarCircle(
    initialSource: String,
    modifier: Modifier = Modifier,
    size: Int = 40,
    tint: Color = MaterialTheme.colorScheme.primary,
    container: Color = MaterialTheme.colorScheme.primaryContainer
) {
    val initial = initialSource.trim().take(1).uppercase().ifBlank { "?" }
    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier.size(size.dp).background(container, CircleShape)
    ) {
        Text(
            initial,
            style = MaterialTheme.typography.titleMedium,
            color = tint
        )
    }
}

/** Backgrounds for white initials; every entry clears 4.5:1 against white (see ThemeContrastTest). */
internal val avatarPalette = listOf(
    Color(0xFF1D4ED8), Color(0xFFB91C1C), Color(0xFF047857), Color(0xFFB45309),
    Color(0xFF7E22CE), Color(0xFF0E7490), Color(0xFFBE185D)
)

fun avatarColorFor(source: String): Color {
    val hash = source.lowercase().fold(0) { acc, c -> acc + c.code }
    return avatarPalette[hash % avatarPalette.size]
}

@Composable
fun StarToggle(
    starred: Boolean,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier
) {
    val description = stringResource(if (starred) Res.string.star_starred else Res.string.star_star)
    IconButton(
        onClick = onToggle,
        modifier = modifier
            .size(48.dp)
            .semantics { contentDescription = description }
    ) {
        Icon(
            imageVector = if (starred) Icons.Filled.Star else Icons.Outlined.StarBorder,
            contentDescription = null,
            tint = if (starred) Color(0xFFF4B400) else MaterialTheme.colorScheme.outline,
            modifier = Modifier.size(22.dp)
        )
    }
}

@Composable
fun GlyphAction(
    glyph: String,
    contentDescriptionText: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    tint: Color = MaterialTheme.colorScheme.onSurfaceVariant
) {
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.semantics { contentDescription = contentDescriptionText }
    ) {
        Text(
            glyph,
            style = MaterialTheme.typography.titleLarge,
            color = if (enabled) tint else MaterialTheme.colorScheme.outline
        )
    }
}

@Composable
fun MaterialIconAction(
    imageVector: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    tint: Color = MaterialTheme.colorScheme.onSurfaceVariant
) {
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.semantics { this.contentDescription = contentDescription }
    ) {
        Icon(
            imageVector = imageVector,
            contentDescription = null,
            tint = if (enabled) tint else MaterialTheme.colorScheme.outline
        )
    }
}

@Composable
fun UnreadDot(visible: Boolean, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .size(8.dp)
            .background(
                color = if (visible) MaterialTheme.colorScheme.primary else Color.Transparent,
                shape = CircleShape
            )
    )
}

@Composable
fun StatusBadge(text: String, tint: Color, background: Color) {
    Box(
        modifier = Modifier
            .background(color = background, shape = RoundedCornerShape(5.dp))
            .padding(horizontal = 8.dp, vertical = 2.dp)
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.SemiBold),
            color = tint
        )
    }
}

@Composable
fun EmptyState(
    icon: ImageVector,
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 48.dp)
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.outline,
            modifier = Modifier.size(56.dp)
        )
        Text(
            title,
            style = MaterialTheme.typography.headlineMedium,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 16.dp)
        )
        Text(
            subtitle,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 8.dp)
        )
        if (actionLabel != null && onAction != null) {
            PrimaryButton(
                text = actionLabel,
                onClick = onAction,
                modifier = Modifier.padding(top = 24.dp)
            )
        }
    }
}

/**
 * Filter chip that does not rely on colour alone to show selection: the selected state also
 * carries a check mark.
 */
@Composable
fun SelectableChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label, style = MaterialTheme.typography.labelLarge) },
        leadingIcon = if (selected) {
            { Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.size(18.dp)) }
        } else {
            null
        },
        modifier = modifier
    )
}

@Composable
fun InlineError(message: String?) {
    if (message.isNullOrBlank()) return
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.errorContainer, RoundedCornerShape(8.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp)
    ) {
        Text(
            message,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onErrorContainer
        )
    }
}

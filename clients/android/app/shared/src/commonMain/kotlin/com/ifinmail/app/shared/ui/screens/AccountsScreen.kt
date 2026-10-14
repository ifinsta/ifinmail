package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.MailOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import com.ifinmail.app.shared.ui.components.MaterialIconAction
import com.ifinmail.app.shared.ui.platform.rememberPlatformSaveText
import androidx.compose.runtime.Composable
import com.ifinmail.app.shared.ui.update.UpdateSettingsSection
import com.ifinmail.app.shared.update.UpdateController
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.ui.components.AvatarCircle
import com.ifinmail.app.shared.ui.components.EmptyState
import com.ifinmail.app.shared.ui.components.PrimaryButton
import com.ifinmail.app.shared.ui.components.avatarColorFor
import kotlinx.coroutines.launch
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.accounts_empty_subtitle
import com.ifinmail.app.shared.resources.accounts_empty_title
import com.ifinmail.app.shared.resources.accounts_title
import com.ifinmail.app.shared.resources.action_back
import com.ifinmail.app.shared.resources.action_cancel
import com.ifinmail.app.shared.resources.action_remove
import com.ifinmail.app.shared.resources.add_account
import com.ifinmail.app.shared.resources.export_failed
import com.ifinmail.app.shared.resources.export_failed_file
import com.ifinmail.app.shared.resources.export_mailbox
import com.ifinmail.app.shared.resources.export_ready
import com.ifinmail.app.shared.resources.preferences_header
import com.ifinmail.app.shared.resources.remove_account_message
import com.ifinmail.app.shared.resources.remove_account_title
import com.ifinmail.app.shared.resources.settings_title
import com.ifinmail.app.shared.resources.theme_dark
import com.ifinmail.app.shared.resources.theme_light
import com.ifinmail.app.shared.resources.theme_subtitle
import com.ifinmail.app.shared.resources.theme_system
import com.ifinmail.app.shared.resources.theme_title
import org.jetbrains.compose.resources.stringResource
import org.jetbrains.compose.resources.getString

@Composable
fun AccountsScreen(
    controller: MailController,
    onAddAccount: () -> Unit,
    onBack: () -> Unit,
    themeOverride: Boolean?,
    onThemeChange: (Boolean?) -> Unit,
    updateController: UpdateController? = null
) {
    val accounts by controller.accounts.collectAsState()
    val scope = rememberCoroutineScope()
    val saveText = rememberPlatformSaveText()
    var removeTarget by remember { mutableStateOf<com.ifinmail.app.shared.mail.UiAccount?>(null) }
    var exportFeedback by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            MaterialIconAction(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(Res.string.action_back),
                onClick = onBack
            )
            Text(stringResource(Res.string.settings_title), style = MaterialTheme.typography.titleMedium)
        }
        Text(
            stringResource(Res.string.accounts_title),
            style = MaterialTheme.typography.displayLarge
        )

        if (accounts.isEmpty()) {
            EmptyState(
                icon = Icons.Default.MailOutline,
                title = stringResource(Res.string.accounts_empty_title),
                subtitle = stringResource(Res.string.accounts_empty_subtitle)
            )
        }

        accounts.forEach { account ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .padding(14.dp)
            ) {
                AvatarCircle(
                    account.email,
                    tint = androidx.compose.ui.graphics.Color.White,
                    container = avatarColorFor(account.email)
                )
                Spacer(Modifier.size(14.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(account.displayName, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        account.email,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                TextButton(
                    onClick = { removeTarget = account },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)
                ) { Text(stringResource(Res.string.action_remove), style = MaterialTheme.typography.labelLarge) }
            }
        }

        PrimaryButton(text = stringResource(Res.string.add_account), onClick = onAddAccount, modifier = Modifier.fillMaxWidth())

        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Text(stringResource(Res.string.preferences_header), style = MaterialTheme.typography.labelSmall.copy(
            fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
            letterSpacing = 1.2.sp
        ), color = MaterialTheme.colorScheme.outline)

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .padding(14.dp)
        ) {
            Text(stringResource(Res.string.theme_title), style = MaterialTheme.typography.titleSmall)
            Text(
                stringResource(Res.string.theme_subtitle),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.size(12.dp))
            val options = listOf<Pair<String, Boolean?>>(
                stringResource(Res.string.theme_system) to null,
                stringResource(Res.string.theme_light) to false,
                stringResource(Res.string.theme_dark) to true
            )
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                options.forEachIndexed { index, (label, value) ->
                    SegmentedButton(
                        selected = themeOverride == value,
                        onClick = { onThemeChange(value) },
                        shape = SegmentedButtonDefaults.itemShape(index = index, count = options.size),
                        label = { Text(label) }
                    )
                }
            }
        }

        if (updateController != null) UpdateSettingsSection(updateController)

        exportFeedback?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary)
        }
        com.ifinmail.app.shared.ui.components.GhostButton(
            text = stringResource(Res.string.export_mailbox),
            onClick = {
                scope.launch {
                    controller.exportMbox().fold(
                        onSuccess = { mbox ->
                            val path = saveText("ifinmail-export.mbox", mbox)
                            exportFeedback = if (path != null) getString(Res.string.export_ready) else getString(Res.string.export_failed_file)
                        },
                        onFailure = { exportFeedback = getString(Res.string.export_failed, it.message ?: "") }
                    )
                }
            },
            modifier = Modifier.fillMaxWidth()
        )
    }

    removeTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { removeTarget = null },
            title = { Text(stringResource(Res.string.remove_account_title, target.email)) },
            text = { Text(stringResource(Res.string.remove_account_message)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        scope.launch { controller.removeAccount(target.id) }
                        removeTarget = null
                    },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)
                ) { Text(stringResource(Res.string.action_remove)) }
            },
            dismissButton = {
                TextButton(onClick = { removeTarget = null }) { Text(stringResource(Res.string.action_cancel)) }
            }
        )
    }
}

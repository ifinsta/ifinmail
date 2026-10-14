package com.ifinmail.app.shared.ui.update

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.update_action_allow
import com.ifinmail.app.shared.resources.update_action_check
import com.ifinmail.app.shared.resources.update_action_install
import com.ifinmail.app.shared.resources.update_action_later
import com.ifinmail.app.shared.resources.update_action_retry
import com.ifinmail.app.shared.resources.update_action_update
import com.ifinmail.app.shared.resources.update_available_subtitle
import com.ifinmail.app.shared.resources.update_available_title
import com.ifinmail.app.shared.resources.update_downloading
import com.ifinmail.app.shared.resources.update_failed_title
import com.ifinmail.app.shared.resources.update_installed_version
import com.ifinmail.app.shared.resources.update_installing
import com.ifinmail.app.shared.resources.update_notifications_body
import com.ifinmail.app.shared.resources.update_notifications_title
import com.ifinmail.app.shared.resources.update_permission_body
import com.ifinmail.app.shared.resources.update_permission_title
import com.ifinmail.app.shared.resources.update_ready_title
import com.ifinmail.app.shared.resources.update_required_body
import com.ifinmail.app.shared.resources.update_required_title
import com.ifinmail.app.shared.resources.update_server
import com.ifinmail.app.shared.resources.update_settings_title
import com.ifinmail.app.shared.resources.update_status_checking
import com.ifinmail.app.shared.resources.update_status_idle
import com.ifinmail.app.shared.resources.update_status_up_to_date
import com.ifinmail.app.shared.resources.update_whats_new
import com.ifinmail.app.shared.ui.components.GhostButton
import com.ifinmail.app.shared.ui.components.PrimaryButton
import com.ifinmail.app.shared.update.UiUpdateInfo
import com.ifinmail.app.shared.update.UpdateController
import com.ifinmail.app.shared.update.UpdateUiState
import org.jetbrains.compose.resources.stringResource

/** "12.4 MB": one decimal, no locale machinery needed for a size. */
internal fun formatSize(bytes: Long): String {
    val tenths = bytes * 10 / 1_000_000
    return "${tenths / 10}.${tenths % 10} MB"
}

/**
 * The inbox banner for an optional update. Mandatory updates use [UpdateRequiredScreen] instead,
 * so this renders nothing for them.
 */
@Composable
fun UpdateBanner(
    controller: UpdateController,
    onLater: () -> Unit,
    modifier: Modifier = Modifier
) {
    val state by controller.state.collectAsState()
    val info = when (state) {
        is UpdateUiState.Available -> (state as UpdateUiState.Available).info
        is UpdateUiState.Downloading -> (state as UpdateUiState.Downloading).info
        is UpdateUiState.ReadyToInstall -> (state as UpdateUiState.ReadyToInstall).info
        is UpdateUiState.NeedsInstallPermission -> (state as UpdateUiState.NeedsInstallPermission).info
        is UpdateUiState.Installing -> (state as UpdateUiState.Installing).info
        is UpdateUiState.Failed -> (state as UpdateUiState.Failed).info
        else -> null
    } ?: return
    if (info.required) return

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.primaryContainer)
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Icon(
                Icons.Default.SystemUpdate,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.size(24.dp)
            )
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                BannerText(state, info)
            }
        }
        val current = state
        if (current is UpdateUiState.Downloading) {
            Spacer(Modifier.height(12.dp))
            LinearProgressIndicator(
                progress = { current.percent / 100f },
                modifier = Modifier.fillMaxWidth()
            )
        }
        Spacer(Modifier.height(8.dp))
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End),
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth()
        ) {
            val busy = current is UpdateUiState.Downloading || current is UpdateUiState.Installing
            if (!busy) {
                TextButton(onClick = onLater) {
                    Text(
                        stringResource(Res.string.update_action_later),
                        color = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                }
            }
            when (current) {
                is UpdateUiState.Available -> PrimaryButton(
                    text = stringResource(Res.string.update_action_update),
                    onClick = controller::downloadAndInstall
                )
                is UpdateUiState.ReadyToInstall -> PrimaryButton(
                    text = stringResource(Res.string.update_action_install),
                    onClick = controller::downloadAndInstall
                )
                is UpdateUiState.NeedsInstallPermission -> PrimaryButton(
                    text = stringResource(Res.string.update_action_allow),
                    onClick = controller::openInstallPermissionSettings
                )
                is UpdateUiState.Failed -> PrimaryButton(
                    text = stringResource(Res.string.update_action_retry),
                    onClick = controller::downloadAndInstall
                )
                else -> Unit
            }
        }
    }
}

@Composable
private fun BannerText(state: UpdateUiState, info: UiUpdateInfo) {
    val title: String
    val subtitle: String?
    when (state) {
        is UpdateUiState.Available -> {
            title = stringResource(Res.string.update_available_title, info.versionName)
            subtitle = stringResource(Res.string.update_available_subtitle, formatSize(info.sizeBytes))
        }
        is UpdateUiState.Downloading -> {
            title = stringResource(Res.string.update_downloading)
            subtitle = "${state.percent}%"
        }
        is UpdateUiState.ReadyToInstall -> {
            title = stringResource(Res.string.update_ready_title, info.versionName)
            subtitle = null
        }
        is UpdateUiState.NeedsInstallPermission -> {
            title = stringResource(Res.string.update_permission_title)
            subtitle = stringResource(Res.string.update_permission_body)
        }
        is UpdateUiState.Installing -> {
            title = stringResource(Res.string.update_installing)
            subtitle = null
        }
        is UpdateUiState.Failed -> {
            title = stringResource(Res.string.update_failed_title)
            subtitle = state.message
        }
        else -> return
    }
    Text(title, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
    if (subtitle != null) {
        Text(
            subtitle,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onPrimaryContainer
        )
    }
}

/**
 * Full screen shown instead of the app when this device is below the mandatory floor. It offers
 * one action and has no way around it, because the server has declared this version unusable.
 */
@Composable
fun UpdateRequiredScreen(controller: UpdateController, modifier: Modifier = Modifier) {
    val state by controller.state.collectAsState()
    val info = (state as? UpdateUiState.Available)?.info
        ?: (state as? UpdateUiState.Downloading)?.info
        ?: (state as? UpdateUiState.ReadyToInstall)?.info
        ?: (state as? UpdateUiState.NeedsInstallPermission)?.info
        ?: (state as? UpdateUiState.Installing)?.info
        ?: (state as? UpdateUiState.Failed)?.info
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 32.dp, vertical = 24.dp)
    ) {
        Icon(
            Icons.Default.SystemUpdate,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(56.dp)
        )
        Text(
            stringResource(Res.string.update_required_title),
            style = MaterialTheme.typography.headlineMedium,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 16.dp)
        )
        Text(
            stringResource(Res.string.update_required_body, info?.versionName.orEmpty()),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 8.dp)
        )
        val current = state
        when (current) {
            is UpdateUiState.Downloading -> {
                LinearProgressIndicator(
                    progress = { current.percent / 100f },
                    modifier = Modifier.padding(top = 24.dp).fillMaxWidth()
                )
                Text(
                    "${current.percent}%",
                    style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
            is UpdateUiState.NeedsInstallPermission -> {
                Text(
                    stringResource(Res.string.update_permission_body),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 16.dp)
                )
                PrimaryButton(
                    text = stringResource(Res.string.update_action_allow),
                    onClick = controller::openInstallPermissionSettings,
                    modifier = Modifier.padding(top = 16.dp).fillMaxWidth()
                )
            }
            is UpdateUiState.Failed -> {
                Text(
                    current.message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 16.dp)
                )
                PrimaryButton(
                    text = stringResource(Res.string.update_action_retry),
                    onClick = controller::downloadAndInstall,
                    modifier = Modifier.padding(top = 16.dp).fillMaxWidth()
                )
            }
            is UpdateUiState.Installing -> Text(
                stringResource(Res.string.update_installing),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 24.dp)
            )
            else -> PrimaryButton(
                text = stringResource(
                    if (current is UpdateUiState.ReadyToInstall) Res.string.update_action_install
                    else Res.string.update_action_update
                ),
                onClick = controller::downloadAndInstall,
                modifier = Modifier.padding(top = 24.dp).fillMaxWidth()
            )
        }
    }
}

/** The "App updates" block of the settings page. */
@Composable
fun UpdateSettingsSection(controller: UpdateController, modifier: Modifier = Modifier) {
    val state by controller.state.collectAsState()
    val notificationsAllowed by controller.notificationsAllowed.collectAsState()
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(stringResource(Res.string.update_settings_title), style = MaterialTheme.typography.titleSmall)
        SettingLine(
            stringResource(Res.string.update_installed_version),
            "${controller.currentVersionName} (${controller.currentVersionCode})"
        )
        if (controller.serverLabel.isNotBlank()) {
            SettingLine(stringResource(Res.string.update_server), controller.serverLabel)
        }

        val checking = state is UpdateUiState.Checking
        val status = when (val s = state) {
            UpdateUiState.Idle -> stringResource(Res.string.update_status_idle)
            UpdateUiState.Checking -> stringResource(Res.string.update_status_checking)
            is UpdateUiState.UpToDate -> stringResource(Res.string.update_status_up_to_date)
            is UpdateUiState.Available -> stringResource(Res.string.update_available_title, s.info.versionName)
            is UpdateUiState.Downloading -> stringResource(Res.string.update_downloading) + " ${s.percent}%"
            is UpdateUiState.ReadyToInstall -> stringResource(Res.string.update_ready_title, s.info.versionName)
            is UpdateUiState.NeedsInstallPermission -> stringResource(Res.string.update_permission_title)
            is UpdateUiState.Installing -> stringResource(Res.string.update_installing)
            is UpdateUiState.Failed -> s.message
        }
        Text(
            status,
            style = MaterialTheme.typography.bodyMedium,
            color = if (state is UpdateUiState.Failed) MaterialTheme.colorScheme.error
            else MaterialTheme.colorScheme.onSurface
        )

        val info = (state as? UpdateUiState.Available)?.info
        if (info != null && info.notes.isNotBlank()) {
            Text(
                stringResource(Res.string.update_whats_new),
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(top = 4.dp)
            )
            Text(
                info.notes,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        // One action at a time: what the person can do about the update in this state.
        val retryable = (state as? UpdateUiState.Failed)?.info != null
        when (state) {
            is UpdateUiState.Downloading, is UpdateUiState.Installing -> Unit
            is UpdateUiState.NeedsInstallPermission -> PrimaryButton(
                text = stringResource(Res.string.update_action_allow),
                onClick = controller::openInstallPermissionSettings,
                modifier = Modifier.fillMaxWidth()
            )
            is UpdateUiState.Available, is UpdateUiState.ReadyToInstall -> PrimaryButton(
                text = stringResource(
                    if (state is UpdateUiState.ReadyToInstall) Res.string.update_action_install
                    else Res.string.update_action_update
                ),
                onClick = controller::downloadAndInstall,
                modifier = Modifier.fillMaxWidth()
            )
            is UpdateUiState.Failed -> if (retryable) {
                PrimaryButton(
                    text = stringResource(Res.string.update_action_retry),
                    onClick = controller::downloadAndInstall,
                    modifier = Modifier.fillMaxWidth()
                )
            } else {
                GhostButton(
                    text = stringResource(Res.string.update_action_check),
                    onClick = controller::check,
                    modifier = Modifier.fillMaxWidth()
                )
            }
            else -> GhostButton(
                text = stringResource(Res.string.update_action_check),
                onClick = controller::check,
                enabled = !checking,
                modifier = Modifier.fillMaxWidth()
            )
        }

        if (!notificationsAllowed) {
            Text(
                stringResource(Res.string.update_notifications_title),
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(top = 8.dp)
            )
            Text(
                stringResource(Res.string.update_notifications_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            GhostButton(
                text = stringResource(Res.string.update_action_allow),
                onClick = controller::requestNotificationPermission,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

@Composable
private fun SettingLine(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}

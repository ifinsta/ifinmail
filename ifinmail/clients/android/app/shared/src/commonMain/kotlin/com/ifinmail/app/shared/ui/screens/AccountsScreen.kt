package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import com.ifinmail.app.shared.ui.components.MaterialIconAction
import com.ifinmail.app.shared.ui.platform.rememberPlatformSaveText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.ui.components.AvatarCircle
import com.ifinmail.app.shared.ui.components.EmptyState
import com.ifinmail.app.shared.ui.components.PrimaryButton
import com.ifinmail.app.shared.ui.components.avatarColorFor
import kotlinx.coroutines.launch

@Composable
fun AccountsScreen(
    controller: MailController,
    onAddAccount: () -> Unit,
    onBack: () -> Unit,
    darkTheme: Boolean,
    onToggleTheme: (Boolean) -> Unit
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
            .padding(horizontal = 24.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            MaterialIconAction(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = "Back",
                onClick = onBack
            )
            Text("Settings", style = MaterialTheme.typography.titleMedium)
        }
        Text("Accounts", style = MaterialTheme.typography.displayLarge)

        if (accounts.isEmpty()) {
            EmptyState(
                iconText = "✉",
                title = "No accounts yet",
                subtitle = "Connect a mailbox to get started. IMAP, POP3 and SMTP are supported."
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
                    Text(account.displayName, style = MaterialTheme.typography.titleMedium)
                    Text(account.email, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Text(
                    "Remove",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.clickable { removeTarget = account }.padding(start = 12.dp)
                )
            }
        }

        PrimaryButton(text = "Add account", onClick = onAddAccount, modifier = Modifier.fillMaxWidth())

        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Text("PREFERENCES", style = MaterialTheme.typography.labelSmall.copy(
            fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
            letterSpacing = 1.2.sp
        ), color = MaterialTheme.colorScheme.outline)

        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .padding(14.dp)
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text("Dark theme", style = MaterialTheme.typography.titleSmall)
                Text("Forces dark mode instead of following your system", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            androidx.compose.material3.Switch(
                checked = darkTheme,
                onCheckedChange = { onToggleTheme(it) }
            )
        }

        exportFeedback?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary)
        }
        com.ifinmail.app.shared.ui.components.GhostButton(
            text = "Export mailbox (MBOX)",
            onClick = {
                scope.launch {
                    controller.exportMbox().fold(
                        onSuccess = { mbox ->
                            val path = saveText("ifinmail-export.mbox", mbox)
                            exportFeedback = if (path != null) "Exported to $path" else "Export generated"
                        },
                        onFailure = { exportFeedback = "Export failed: ${it.message}" }
                    )
                }
            },
            modifier = Modifier.fillMaxWidth()
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }

    removeTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { removeTarget = null },
            title = { Text("Remove ${target.email}?") },
            text = { Text("This disconnects the mailbox from ifinmail. Messages on the server are not deleted.") },
            confirmButton = {
                TextButton(
                    onClick = {
                        scope.launch { controller.removeAccount(target.id) }
                        removeTarget = null
                    },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)
                ) { Text("Remove") }
            },
            dismissButton = {
                TextButton(onClick = { removeTarget = null }) { Text("Cancel") }
            }
        )
    }
}

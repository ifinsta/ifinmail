package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiProviderProfile
import com.ifinmail.app.shared.mail.UiProtocol
import com.ifinmail.app.shared.mail.UiSecurity
import com.ifinmail.app.shared.ui.components.GhostButton
import com.ifinmail.app.shared.ui.components.InlineError
import com.ifinmail.app.shared.ui.components.LabeledField
import com.ifinmail.app.shared.ui.components.PrimaryButton
import kotlinx.coroutines.launch

private enum class SetupStep { Email, Profile, Credentials, Verifying }

@Composable
fun AddAccountScreen(
    controller: MailController,
    onDone: () -> Unit,
    onCancel: () -> Unit
) {
    val scope = rememberCoroutineScope()
    var step by remember { mutableStateOf(SetupStep.Email) }
    var email by remember { mutableStateOf("") }
    var emailError by remember { mutableStateOf<String?>(null) }
    var profiles by remember { mutableStateOf<List<UiProviderProfile>>(emptyList()) }
    var selectedProfile by remember { mutableStateOf<UiProviderProfile?>(null) }
    var password by remember { mutableStateOf("") }
    var oauthToken by remember { mutableStateOf("") }
    var useOAuth by remember { mutableStateOf(false) }
    var formError by remember { mutableStateOf<String?>(null) }
    var verifyLog by remember { mutableStateOf<List<String>>(emptyList()) }
    var discovering by remember { mutableStateOf(false) }
    var manualOpen by remember { mutableStateOf(false) }
    var manualProtocol by remember { mutableStateOf(UiProtocol.IMAP) }
    var manualInHost by remember { mutableStateOf("") }
    var manualInPort by remember { mutableStateOf("993") }
    var manualInSecurity by remember { mutableStateOf(UiSecurity.SSL_TLS) }
    var manualOutHost by remember { mutableStateOf("") }
    var manualOutPort by remember { mutableStateOf("465") }
    var manualOutSecurity by remember { mutableStateOf(UiSecurity.SSL_TLS) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 24.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onCancel) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Spacer(Modifier.width(8.dp))
            Text("Add account", style = MaterialTheme.typography.displayLarge)
        }
        Text(
            "Connect an existing mailbox via IMAP, POP3 or SMTP.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp, bottom = 16.dp)
        )

        if (manualOpen) {
            Text("Manual server configuration", style = MaterialTheme.typography.headlineMedium)
            Text(
                "INCOMING",
                style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.outline
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterPill("IMAP", manualProtocol == UiProtocol.IMAP) { manualProtocol = UiProtocol.IMAP }
                FilterPill("POP3", manualProtocol == UiProtocol.POP3) { manualProtocol = UiProtocol.POP3 }
            }
            Spacer(Modifier.height(8.dp))
            LabeledField(label = "Incoming host", value = manualInHost, onValueChange = { manualInHost = it }, helperText = "e.g. mail.example.com")
            LabeledField(label = "Incoming port", value = manualInPort, onValueChange = { manualInPort = it })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterPill("SSL/TLS", manualInSecurity == UiSecurity.SSL_TLS) { manualInSecurity = UiSecurity.SSL_TLS }
                FilterPill("STARTTLS", manualInSecurity == UiSecurity.STARTTLS) { manualInSecurity = UiSecurity.STARTTLS }
                FilterPill("None", manualInSecurity == UiSecurity.NONE) { manualInSecurity = UiSecurity.NONE }
            }
            Spacer(Modifier.height(16.dp))
            Text(
                "OUTGOING",
                style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.outline
            )
            LabeledField(label = "SMTP host", value = manualOutHost, onValueChange = { manualOutHost = it })
            LabeledField(label = "SMTP port", value = manualOutPort, onValueChange = { manualOutPort = it })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterPill("SSL/TLS", manualOutSecurity == UiSecurity.SSL_TLS) { manualOutSecurity = UiSecurity.SSL_TLS }
                FilterPill("STARTTLS", manualOutSecurity == UiSecurity.STARTTLS) { manualOutSecurity = UiSecurity.STARTTLS }
                FilterPill("None", manualOutSecurity == UiSecurity.NONE) { manualOutSecurity = UiSecurity.NONE }
            }
            Spacer(Modifier.height(16.dp))
            InlineError(formError)
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                GhostButton(text = "Cancel", onClick = { manualOpen = false })
                PrimaryButton(
                    text = "Use settings",
                    enabled = manualInHost.isNotBlank() && manualOutHost.isNotBlank(),
                    onClick = {
                        val manualProfile = UiProviderProfile(
                            label = "Custom \u00b7 ${manualProtocol.name}",
                            protocol = manualProtocol,
                            incomingHost = manualInHost.trim(),
                            incomingPort = manualInPort.trim().toIntOrNull() ?: 993,
                            incomingSecurity = manualInSecurity,
                            outgoingHost = manualOutHost.trim(),
                            outgoingPort = manualOutPort.trim().toIntOrNull() ?: 465,
                            outgoingSecurity = manualOutSecurity,
                            note = "Manually configured"
                        )
                        profiles = listOf(manualProfile)
                        selectedProfile = manualProfile
                        manualOpen = false
                        step = SetupStep.Credentials
                    }
                )
            }
        } else {
            StepIndicator(current = step)

            when (step) {
                SetupStep.Email -> {
                    LabeledField(
                        label = "Email address *",
                        value = email,
                        onValueChange = { email = it; emailError = null },
                        isError = emailError != null,
                        errorText = emailError,
                        helperText = "Providers like Gmail, Outlook, Yahoo and iCloud are detected automatically"
                    )
                    Spacer(Modifier.height(20.dp))
                    InlineError(formError)
                    if (discovering) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(top = 12.dp)
                        ) {
                            CircularProgressIndicator(Modifier.width(20.dp).height(20.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(12.dp))
                            Text("Looking up server configuration\u2026", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        GhostButton(text = "Cancel", onClick = onCancel, enabled = true)
                        PrimaryButton(
                            text = "Continue",
                            enabled = email.isNotBlank(),
                            onClick = {
                                val trimmed = email.trim()
                                if (!trimmed.contains('@') || trimmed.endsWith("@") || trimmed.startsWith("@")) {
                                    emailError = "Enter a valid email address"
                                } else {
                                    formError = null
                                    discovering = true
                                    scope.launch {
                                        val found = controller.autoConfigure(trimmed)
                                        discovering = false
                                        if (found.isEmpty()) {
                                            formError = "No automatic configuration found for this domain. Proton Mail requires their Bridge app; other custom servers must be entered manually."
                                        } else {
                                            profiles = found
                                            selectedProfile = found.first()
                                            step = SetupStep.Profile
                                        }
                                    }
                                }
                            }
                        )
                    }
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "Use manual configuration for custom servers",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .clickable { manualOpen = true }
                            .padding(vertical = 4.dp)
                    )
                }

                SetupStep.Profile -> {
                    Text("Detected configuration", style = MaterialTheme.typography.headlineMedium)
                    Text(
                        "Choose how ifinmail should connect to ${email.trim()}.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp, bottom = 16.dp)
                    )
                    profiles.forEach { profile ->
                        val selected = profile == selectedProfile
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(8.dp))
                                .background(if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant)
                                .clickable { selectedProfile = profile }
                                .padding(horizontal = 16.dp, vertical = 12.dp)
                        ) {
                            Text(profile.label, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                            Text(profile.summaryLine, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            profile.note?.let {
                                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary, modifier = Modifier.padding(top = 4.dp))
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        GhostButton(text = "Back", onClick = { step = SetupStep.Email })
                        PrimaryButton(text = "Continue", enabled = selectedProfile != null, onClick = { step = SetupStep.Credentials })
                    }
                }

                SetupStep.Credentials -> {
                    Text("Sign in", style = MaterialTheme.typography.headlineMedium)
                    Text(
                        email.trim(),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp, bottom = 16.dp)
                    )
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterPill("App password", !useOAuth) { useOAuth = false }
                        FilterPill("OAuth2 token (XOAUTH2)", useOAuth) { useOAuth = true }
                    }
                    Spacer(Modifier.height(16.dp))
                    if (useOAuth) {
                        LabeledField(
                            label = "Access token *",
                            value = oauthToken,
                            onValueChange = { oauthToken = it },
                            helperText = "Token needs the https://mail.google.com/ scope for Gmail (XOAUTH2)"
                        )
                    } else {
                        LabeledField(
                            label = "Password / app password *",
                            value = password,
                            onValueChange = { password = it },
                            helperText = selectedProfile?.note ?: "Use your regular password, or an app password if your provider requires one"
                        )
                    }
                    Spacer(Modifier.height(20.dp))
                    InlineError(formError)
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        GhostButton(text = "Back", onClick = { step = SetupStep.Profile })
                        PrimaryButton(
                            text = "Verify & add account",
                            enabled = (!useOAuth && password.isNotBlank()) || (useOAuth && oauthToken.isNotBlank()),
                            onClick = {
                                val profile = selectedProfile ?: return@PrimaryButton
                                step = SetupStep.Verifying
                                verifyLog = listOf("Connecting to ${profile.incomingHost}\u2026")
                                scope.launch {
                                    val result = controller.addAccount(
                                        email = email.trim(),
                                        displayName = email.trim().substringBefore('@'),
                                        profile = profile,
                                        password = if (useOAuth) null else password,
                                        oauthAccessToken = if (useOAuth) oauthToken.trim() else null
                                    )
                                    result.fold(
                                        onSuccess = {
                                            verifyLog = verifyLog + "Account added"
                                            onDone()
                                        },
                                        onFailure = { failure ->
                                            step = SetupStep.Credentials
                                            formError = failure.message ?: "Verification failed"
                                        }
                                    )
                                }
                            }
                        )
                    }
                }

                SetupStep.Verifying -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.width(24.dp).height(24.dp), strokeWidth = 3.dp)
                        Spacer(Modifier.width(16.dp))
                        Text("Verifying connection\u2026", style = MaterialTheme.typography.titleMedium)
                    }
                    verifyLog.forEach {
                        Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline, modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun StepIndicator(current: SetupStep) {
    val labels = listOf(
        SetupStep.Email to "Email",
        SetupStep.Profile to "Server",
        SetupStep.Credentials to "Sign in",
        SetupStep.Verifying to "Verify"
    )
    val currentIndex = labels.indexOfFirst { it.first == current }.coerceAtLeast(0)
    Row(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.padding(bottom = 16.dp)
    ) {
        labels.forEachIndexed { index, (_, label) ->
            if (index > 0) {
                Text("\u203a", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
            }
            Text(
                label,
                style = MaterialTheme.typography.labelMedium.copy(
                    fontWeight = if (index <= currentIndex) FontWeight.SemiBold else FontWeight.Normal
                ),
                color = if (index <= currentIndex) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline
            )
        }
    }
}

@Composable
private fun FilterPill(label: String, active: Boolean, onClick: () -> Unit) {
    Text(
        label,
        style = MaterialTheme.typography.labelLarge,
        color = if (active) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier
            .clip(RoundedCornerShape(16.dp))
            .background(if (active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 6.dp)
    )
}

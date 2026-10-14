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
import androidx.compose.foundation.layout.imePadding
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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.core.domain.error.MailError
import com.ifinmail.core.domain.error.MailException
import com.ifinmail.app.shared.mail.UiProviderProfile
import com.ifinmail.app.shared.mail.UiProtocol
import com.ifinmail.app.shared.mail.UiSecurity
import com.ifinmail.app.shared.ui.components.GhostButton
import com.ifinmail.app.shared.ui.components.InlineError
import com.ifinmail.app.shared.ui.components.LabeledField
import com.ifinmail.app.shared.ui.components.PrimaryButton
import com.ifinmail.app.shared.ui.components.SelectableChip
import kotlinx.coroutines.launch
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.access_token
import com.ifinmail.app.shared.resources.access_token_helper
import com.ifinmail.app.shared.resources.account_added
import com.ifinmail.app.shared.resources.action_back
import com.ifinmail.app.shared.resources.action_cancel
import com.ifinmail.app.shared.resources.action_continue
import com.ifinmail.app.shared.resources.add_account
import com.ifinmail.app.shared.resources.add_account_subtitle
import com.ifinmail.app.shared.resources.cert_message
import com.ifinmail.app.shared.resources.cert_not_trusted
import com.ifinmail.app.shared.resources.cert_title
import com.ifinmail.app.shared.resources.cert_trust
import com.ifinmail.app.shared.resources.choose_connection
import com.ifinmail.app.shared.resources.connecting_to
import com.ifinmail.app.shared.resources.credential_app_password
import com.ifinmail.app.shared.resources.credential_oauth_token
import com.ifinmail.app.shared.resources.detected_configuration
import com.ifinmail.app.shared.resources.email_address
import com.ifinmail.app.shared.resources.email_helper
import com.ifinmail.app.shared.resources.invalid_email
import com.ifinmail.app.shared.resources.looking_up
import com.ifinmail.app.shared.resources.manual_host_hint
import com.ifinmail.app.shared.resources.manual_incoming_header
import com.ifinmail.app.shared.resources.manual_incoming_host
import com.ifinmail.app.shared.resources.manual_incoming_port
import com.ifinmail.app.shared.resources.manual_outgoing_header
import com.ifinmail.app.shared.resources.manual_profile_label
import com.ifinmail.app.shared.resources.manual_profile_note
import com.ifinmail.app.shared.resources.manual_smtp_host
import com.ifinmail.app.shared.resources.manual_smtp_port
import com.ifinmail.app.shared.resources.manual_title
import com.ifinmail.app.shared.resources.manual_use_settings
import com.ifinmail.app.shared.resources.no_autoconfig
import com.ifinmail.app.shared.resources.password_helper
import com.ifinmail.app.shared.resources.password_label
import com.ifinmail.app.shared.resources.security_none
import com.ifinmail.app.shared.resources.server_summary
import com.ifinmail.app.shared.resources.sign_in_title
import com.ifinmail.app.shared.resources.step_email
import com.ifinmail.app.shared.resources.step_progress
import com.ifinmail.app.shared.resources.step_server
import com.ifinmail.app.shared.resources.step_sign_in
import com.ifinmail.app.shared.resources.step_verify
import com.ifinmail.app.shared.resources.use_manual
import com.ifinmail.app.shared.resources.verification_failed
import com.ifinmail.app.shared.resources.verify_and_add
import com.ifinmail.app.shared.resources.verifying
import org.jetbrains.compose.resources.stringResource
import org.jetbrains.compose.resources.getString

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
    // A new server starts with a temporary self-signed certificate; the person confirms its fingerprint once.
    var untrustedCertificate by remember { mutableStateOf<MailError.CertificateUntrusted?>(null) }
    var discovering by remember { mutableStateOf(false) }
    var manualOpen by remember { mutableStateOf(false) }
    var manualProtocol by remember { mutableStateOf(UiProtocol.IMAP) }
    var manualInHost by remember { mutableStateOf("") }
    var manualInPort by remember { mutableStateOf("993") }
    var manualInSecurity by remember { mutableStateOf(UiSecurity.SSL_TLS) }
    var manualOutHost by remember { mutableStateOf("") }
    var manualOutPort by remember { mutableStateOf("465") }
    var manualOutSecurity by remember { mutableStateOf(UiSecurity.SSL_TLS) }

    // Strings needed inside plain (non-composable) callbacks are resolved here.
    val invalidEmailText = stringResource(Res.string.invalid_email)
    val certNotTrustedText = stringResource(Res.string.cert_not_trusted)
    val manualProfileLabel = stringResource(Res.string.manual_profile_label, manualProtocol.name)
    val manualProfileNote = stringResource(Res.string.manual_profile_note)

    fun submit(trustedCertificateSha256: String?) {
        val profile = selectedProfile ?: return
        formError = null
        step = SetupStep.Verifying
        verifyLog = emptyList()
        scope.launch {
            verifyLog = listOf(getString(Res.string.connecting_to, profile.incomingHost))
            val result = controller.addAccount(
                email = email.trim(),
                displayName = email.trim().substringBefore('@'),
                profile = profile,
                password = if (useOAuth) null else password,
                oauthAccessToken = if (useOAuth) oauthToken.trim() else null,
                trustedCertificateSha256 = trustedCertificateSha256
            )
            result.fold(
                onSuccess = {
                    verifyLog = verifyLog + getString(Res.string.account_added)
                    onDone()
                },
                onFailure = { failure ->
                    step = SetupStep.Credentials
                    val untrusted = (failure as? MailException)?.error as? MailError.CertificateUntrusted
                    if (untrusted != null && trustedCertificateSha256 == null) {
                        untrustedCertificate = untrusted
                    } else {
                        formError = failure.message ?: getString(Res.string.verification_failed)
                    }
                }
            )
        }
    }

    untrustedCertificate?.let { cert ->
        AlertDialog(
            onDismissRequest = { untrustedCertificate = null },
            title = { Text(stringResource(Res.string.cert_title)) },
            text = {
                Column {
                    Text(stringResource(Res.string.cert_message, cert.host))
                    Text(
                        cert.sha256.uppercase().chunked(2).joinToString(":"),
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 12.dp)
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    untrustedCertificate = null
                    submit(cert.sha256)
                }) { Text(stringResource(Res.string.cert_trust)) }
            },
            dismissButton = {
                TextButton(onClick = {
                    untrustedCertificate = null
                    formError = certNotTrustedText
                }) { Text(stringResource(Res.string.action_cancel)) }
            }
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 8.dp)
    ) {
        IconButton(onClick = onCancel) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(Res.string.action_back))
        }
        Text(
            stringResource(Res.string.add_account),
            style = MaterialTheme.typography.displayLarge
        )
        Text(
            stringResource(Res.string.add_account_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp, bottom = 16.dp)
        )

        if (manualOpen) {
            Text(stringResource(Res.string.manual_title), style = MaterialTheme.typography.headlineMedium)
            Text(
                stringResource(Res.string.manual_incoming_header),
                style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.outline
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterPill("IMAP", manualProtocol == UiProtocol.IMAP) { manualProtocol = UiProtocol.IMAP }
                FilterPill("POP3", manualProtocol == UiProtocol.POP3) { manualProtocol = UiProtocol.POP3 }
            }
            Spacer(Modifier.height(8.dp))
            LabeledField(
                label = stringResource(Res.string.manual_incoming_host),
                testTag = "field-incoming-host",
                value = manualInHost,
                onValueChange = { manualInHost = it },
                helperText = stringResource(Res.string.manual_host_hint),
                keyboardType = KeyboardType.Uri
            )
            Spacer(Modifier.height(8.dp))
            LabeledField(
                label = stringResource(Res.string.manual_incoming_port),
                testTag = "field-incoming-port",
                value = manualInPort,
                onValueChange = { manualInPort = it.filter(Char::isDigit).take(5) },
                keyboardType = KeyboardType.Number
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterPill("SSL/TLS", manualInSecurity == UiSecurity.SSL_TLS) { manualInSecurity = UiSecurity.SSL_TLS }
                FilterPill("STARTTLS", manualInSecurity == UiSecurity.STARTTLS) { manualInSecurity = UiSecurity.STARTTLS }
                FilterPill(stringResource(Res.string.security_none), manualInSecurity == UiSecurity.NONE) { manualInSecurity = UiSecurity.NONE }
            }
            Spacer(Modifier.height(16.dp))
            Text(
                stringResource(Res.string.manual_outgoing_header),
                style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.outline
            )
            Spacer(Modifier.height(8.dp))
            LabeledField(
                label = stringResource(Res.string.manual_smtp_host),
                testTag = "field-smtp-host",
                value = manualOutHost,
                onValueChange = { manualOutHost = it },
                keyboardType = KeyboardType.Uri
            )
            Spacer(Modifier.height(8.dp))
            LabeledField(
                label = stringResource(Res.string.manual_smtp_port),
                testTag = "field-smtp-port",
                value = manualOutPort,
                onValueChange = { manualOutPort = it.filter(Char::isDigit).take(5) },
                keyboardType = KeyboardType.Number
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterPill("SSL/TLS", manualOutSecurity == UiSecurity.SSL_TLS) { manualOutSecurity = UiSecurity.SSL_TLS }
                FilterPill("STARTTLS", manualOutSecurity == UiSecurity.STARTTLS) { manualOutSecurity = UiSecurity.STARTTLS }
                FilterPill(stringResource(Res.string.security_none), manualOutSecurity == UiSecurity.NONE) { manualOutSecurity = UiSecurity.NONE }
            }
            Spacer(Modifier.height(16.dp))
            InlineError(formError)
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                GhostButton(modifier = Modifier.weight(1f), text = stringResource(Res.string.action_cancel), onClick = { manualOpen = false })
                PrimaryButton(
                    modifier = Modifier.weight(1.5f),
                    text = stringResource(Res.string.manual_use_settings),
                    enabled = manualInHost.isNotBlank() && manualOutHost.isNotBlank(),
                    onClick = {
                        val manualProfile = UiProviderProfile(
                            label = manualProfileLabel,
                            protocol = manualProtocol,
                            incomingHost = manualInHost.trim(),
                            incomingPort = manualInPort.trim().toIntOrNull() ?: 993,
                            incomingSecurity = manualInSecurity,
                            outgoingHost = manualOutHost.trim(),
                            outgoingPort = manualOutPort.trim().toIntOrNull() ?: 465,
                            outgoingSecurity = manualOutSecurity,
                            note = manualProfileNote
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
                        label = stringResource(Res.string.email_address),
                        testTag = "field-email-address",
                        value = email,
                        onValueChange = { email = it; emailError = null },
                        isError = emailError != null,
                        errorText = emailError,
                        helperText = stringResource(Res.string.email_helper),
                        keyboardType = KeyboardType.Email,
                        imeAction = ImeAction.Go
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
                            Text(stringResource(Res.string.looking_up), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        GhostButton(modifier = Modifier.weight(1f), text = stringResource(Res.string.action_cancel), onClick = onCancel, enabled = true)
                        PrimaryButton(
                            modifier = Modifier.weight(1.5f),
                            text = stringResource(Res.string.action_continue),
                            enabled = email.isNotBlank(),
                            onClick = {
                                val trimmed = email.trim()
                                if (!trimmed.contains('@') || trimmed.endsWith("@") || trimmed.startsWith("@")) {
                                    emailError = invalidEmailText
                                } else {
                                    formError = null
                                    discovering = true
                                    scope.launch {
                                        val found = controller.autoConfigure(trimmed)
                                        discovering = false
                                        if (found.isEmpty()) {
                                            formError = getString(Res.string.no_autoconfig)
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
                    TextButton(onClick = { manualOpen = true }) {
                        Text(stringResource(Res.string.use_manual), style = MaterialTheme.typography.labelLarge)
                    }
                }

                SetupStep.Profile -> {
                    Text(stringResource(Res.string.detected_configuration), style = MaterialTheme.typography.headlineMedium)
                    Text(
                        stringResource(Res.string.choose_connection, email.trim()),
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
                                .clickable(role = androidx.compose.ui.semantics.Role.RadioButton) { selectedProfile = profile }
                                .padding(horizontal = 16.dp, vertical = 12.dp)
                        ) {
                            Text(profile.label, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                            Text(
                                stringResource(
                                    Res.string.server_summary,
                                    profile.incomingHost,
                                    profile.incomingPort,
                                    securityLabel(profile.incomingSecurity),
                                    profile.outgoingHost,
                                    profile.outgoingPort,
                                    securityLabel(profile.outgoingSecurity)
                                ),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            profile.note?.let {
                                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary, modifier = Modifier.padding(top = 4.dp))
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        GhostButton(modifier = Modifier.weight(1f), text = stringResource(Res.string.action_back), onClick = { step = SetupStep.Email })
                        PrimaryButton(modifier = Modifier.weight(1.5f), text = stringResource(Res.string.action_continue), enabled = selectedProfile != null, onClick = { step = SetupStep.Credentials })
                    }
                }

                SetupStep.Credentials -> {
                    Text(stringResource(Res.string.sign_in_title), style = MaterialTheme.typography.headlineMedium)
                    Text(
                        email.trim(),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp, bottom = 16.dp)
                    )
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterPill(stringResource(Res.string.credential_app_password), !useOAuth) { useOAuth = false }
                        FilterPill(stringResource(Res.string.credential_oauth_token), useOAuth) { useOAuth = true }
                    }
                    Spacer(Modifier.height(16.dp))
                    if (useOAuth) {
                        LabeledField(
                            label = stringResource(Res.string.access_token),
                            testTag = "field-access-token",
                            value = oauthToken,
                            onValueChange = { oauthToken = it },
                            helperText = stringResource(Res.string.access_token_helper),
                            isPassword = true,
                            imeAction = ImeAction.Done
                        )
                    } else {
                        LabeledField(
                            label = stringResource(Res.string.password_label),
                            testTag = "field-password-app-password",
                            value = password,
                            onValueChange = { password = it },
                            helperText = selectedProfile?.note ?: stringResource(Res.string.password_helper),
                            isPassword = true,
                            imeAction = ImeAction.Done
                        )
                    }
                    Spacer(Modifier.height(20.dp))
                    InlineError(formError)
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        GhostButton(modifier = Modifier.weight(1f), text = stringResource(Res.string.action_back), onClick = { step = SetupStep.Profile })
                        PrimaryButton(
                            modifier = Modifier.weight(1.5f),
                            text = stringResource(Res.string.verify_and_add),
                            enabled = (!useOAuth && password.isNotBlank()) || (useOAuth && oauthToken.isNotBlank()),
                            onClick = { submit(null) }
                        )
                    }
                }

                SetupStep.Verifying -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.width(24.dp).height(24.dp), strokeWidth = 3.dp)
                        Spacer(Modifier.width(16.dp))
                        Text(stringResource(Res.string.verifying), style = MaterialTheme.typography.titleMedium)
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
        SetupStep.Email to stringResource(Res.string.step_email),
        SetupStep.Profile to stringResource(Res.string.step_server),
        SetupStep.Credentials to stringResource(Res.string.step_sign_in),
        SetupStep.Verifying to stringResource(Res.string.step_verify)
    )
    val currentIndex = labels.indexOfFirst { it.first == current }.coerceAtLeast(0)
    // The chevrons are decoration; assistive tech gets one sentence for the whole indicator.
    val progressDescription = stringResource(
        Res.string.step_progress,
        currentIndex + 1,
        labels.size,
        labels[currentIndex].second
    )
    Row(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .padding(bottom = 16.dp)
            .clearAndSetSemantics { contentDescription = progressDescription }
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
    SelectableChip(label = label, selected = active, onClick = onClick)
}

/** SSL/TLS and STARTTLS are protocol names and stay as they are; only "None" is translated. */
@Composable
private fun securityLabel(security: UiSecurity): String = when (security) {
    UiSecurity.SSL_TLS -> "SSL/TLS"
    UiSecurity.STARTTLS -> "STARTTLS"
    UiSecurity.NONE -> stringResource(Res.string.security_none)
}

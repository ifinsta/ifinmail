package com.ifinmail.app.shared.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ifinmail.app.shared.mail.MailController
import com.ifinmail.app.shared.mail.UiDraft
import com.ifinmail.app.shared.ui.components.MaterialIconAction
import kotlinx.coroutines.launch
import com.ifinmail.app.shared.resources.Res
import com.ifinmail.app.shared.resources.action_back
import com.ifinmail.app.shared.resources.delete_draft
import com.ifinmail.app.shared.resources.draft_no_recipient
import com.ifinmail.app.shared.resources.draft_preview
import com.ifinmail.app.shared.resources.drafts_empty_subtitle
import com.ifinmail.app.shared.resources.drafts_empty_title
import com.ifinmail.app.shared.resources.mailbox_drafts
import com.ifinmail.app.shared.resources.no_subject
import org.jetbrains.compose.resources.stringResource

@Composable
fun DraftsScreen(
    controller: MailController,
    onOpen: (UiDraft) -> Unit,
    onBack: () -> Unit
) {
    val drafts by controller.drafts.collectAsState()
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.statusBars)
            .windowInsetsPadding(WindowInsets.navigationBars)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp)
        ) {
            MaterialIconAction(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(Res.string.action_back),
                onClick = onBack
            )
            Text(stringResource(Res.string.mailbox_drafts), style = MaterialTheme.typography.titleLarge)
            if (drafts.isNotEmpty()) {
                Spacer(Modifier.width(8.dp))
                Text("(${drafts.size})", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }

        if (drafts.isEmpty()) {
            Column(
                modifier = Modifier.fillMaxSize().padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text(stringResource(Res.string.drafts_empty_title), style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.size(6.dp))
                Text(
                    stringResource(Res.string.drafts_empty_subtitle),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            LazyColumn(modifier = Modifier.fillMaxSize()) {
                items(drafts, key = { it.id }) { draft ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onOpen(draft) }
                            .padding(start = 16.dp, end = 4.dp, top = 8.dp, bottom = 8.dp)
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                draft.subject.ifBlank { stringResource(Res.string.no_subject) },
                                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold),
                                maxLines = 1,
                                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                            )
                            val recipients = draft.to.joinToString(", ")
                                .ifBlank { stringResource(Res.string.draft_no_recipient) }
                            Text(
                                if (draft.body.isNotBlank()) {
                                    stringResource(Res.string.draft_preview, recipients, draft.body.take(60))
                                } else {
                                    recipients
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                            )
                        }
                        MaterialIconAction(
                            imageVector = Icons.Default.Delete,
                            contentDescription = stringResource(Res.string.delete_draft),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            onClick = { scope.launch { controller.deleteDraft(draft.id) } }
                        )
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant, thickness = 0.5.dp)
                }
            }
        }
    }
}

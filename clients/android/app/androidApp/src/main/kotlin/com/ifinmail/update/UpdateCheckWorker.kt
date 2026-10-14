package com.ifinmail.update

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.ifinmail.MainActivity
import com.ifinmail.R

/**
 * Asks the update server in the background and, when a build is waiting, posts one notice per
 * version. It never downloads: that waits for the person (data, battery, and consent).
 */
class UpdateCheckWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val updates = AppUpdates.get(applicationContext)
        val offer = try {
            updates.peekOffer()
        } catch (e: com.ifinmail.update.UpdateException) {
            return Result.retry() // offline or the server is down: try again later
        } ?: return Result.success()

        val prefs = applicationContext.getSharedPreferences("ifinmail_updates", Context.MODE_PRIVATE)
        val lastNotified = prefs.getInt(KEY_NOTIFIED, 0)
        if (offer.release.versionCode > lastNotified) {
            if (notify(offer)) prefs.edit().putInt(KEY_NOTIFIED, offer.release.versionCode).apply()
        }
        return Result.success()
    }

    private fun notify(offer: com.ifinmail.update.UpdateOffer): Boolean {
        val context = applicationContext
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return false // the in-app banner still shows it
        }
        val manager = NotificationManagerCompat.from(context)
        if (!manager.areNotificationsEnabled()) return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.update_channel_name),
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply { description = context.getString(R.string.update_channel_description) }
            context.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
        val open = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val title = context.getString(
            if (offer.required) R.string.update_notice_required_title else R.string.update_notice_title
        )
        val text = context.getString(R.string.update_notice_text, offer.release.versionName)
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(open)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        @Suppress("MissingPermission") // checked above
        manager.notify(NOTIFICATION_ID, notification)
        return true
    }

    companion object {
        const val UNIQUE_NAME = "ifinmail-update-check"
        private const val CHANNEL_ID = "updates"
        private const val NOTIFICATION_ID = 4101
        private const val KEY_NOTIFIED = "notified_version_code"
    }
}

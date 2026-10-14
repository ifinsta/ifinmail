package com.ifinmail.update

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/** One update controller per process, shared by the activity, the install receiver and the worker. */
object AppUpdates {
    @Volatile
    private var controller: AndroidUpdateController? = null

    fun get(context: Context): AndroidUpdateController =
        controller ?: synchronized(this) {
            controller ?: AndroidUpdateController(context.applicationContext).also { controller = it }
        }

    /** Checks about twice a day while the device is online, even when the app is not open. */
    fun scheduleBackgroundChecks(context: Context) {
        if (!get(context).enabled) return
        val request = PeriodicWorkRequestBuilder<UpdateCheckWorker>(12, TimeUnit.HOURS)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context.applicationContext).enqueueUniquePeriodicWork(
            UpdateCheckWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request
        )
    }
}

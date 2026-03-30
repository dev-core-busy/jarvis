package info.jarvisai.app

import android.app.Application
import dagger.hilt.android.HiltAndroidApp
import info.jarvisai.app.service.JarvisNotificationService

@HiltAndroidApp
class JarvisApp : Application() {
    override fun onCreate() {
        super.onCreate()
        JarvisNotificationService.createChannel(this)
    }
}

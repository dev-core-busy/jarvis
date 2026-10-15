package info.jarvisai.app

import android.app.Application
import dagger.hilt.android.HiltAndroidApp
import info.jarvisai.app.service.JarvisNotificationService

@HiltAndroidApp
class JarvisApp : Application() {
    override fun onCreate() {
        super.onCreate()
        JarvisNotificationService.createChannel(this)
        // vor dem ersten Netzzugriff: bestaetigte Serverzertifikate (BSI M11)
        info.jarvisai.app.data.tls.ServerVertrauen.init(this)
    }
}

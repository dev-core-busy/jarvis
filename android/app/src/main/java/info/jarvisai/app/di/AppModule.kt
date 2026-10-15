package info.jarvisai.app.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import info.jarvisai.app.data.tls.ServerVertrauen
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    /**
     * Gemeinsamer OkHttpClient. Zertifikat: System/Firmen-CA oder vom Benutzer
     * bestaetigt (BSI M11, ServerVertrauen) – frueher Trust-All mit der
     * Begruendung "nur via Tailscale", die der Code nie durchgesetzt hat.
     */
    @Provides
    @Singleton
    fun provideOkHttpClient(@ApplicationContext context: Context): OkHttpClient {
        ServerVertrauen.init(context)
        val logger = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }

        return ServerVertrauen.anwenden(OkHttpClient.Builder())
            .addInterceptor(logger)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS)   // WebSocket: kein Read-Timeout
            .writeTimeout(10, TimeUnit.SECONDS)
            .pingInterval(30, TimeUnit.SECONDS)
            .build()
    }
}

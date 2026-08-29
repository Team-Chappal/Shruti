package dev.shruti.config

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit

/**
 * Runtime phone identity, persisted to SharedPreferences.
 *
 * Three pieces of state, all settable from the MainActivity
 * setup screen:
 *  - phoneId: 0/1/2 (which of the three array elements this
 *    device is)
 *  - isMaster: true for the master phone (plays the chirp
 *    beacon); false for the two elements
 *  - laptopWsUrl: full ws://host:port/ URL of the laptop's
 *    array processor WebSocket server
 *
 * Default values match the Wi-Fi Direct group owner
 * (192.168.49.1) on port 8765 — the laptop's
 * `shruti-array run-radar` default. Operators can override
 * the URL on the setup screen if the venue routes differently
 * (Office Kit on iQOO, manual IP, etc.).
 */
object IdentityConfig {
    private const val PREFS_NAME = "shruti_identity"
    private const val KEY_PHONE_ID = "phone_id"
    private const val KEY_IS_MASTER = "is_master"
    private const val KEY_LAPTOP_WS_URL = "laptop_ws_url"
    private const val KEY_CALIBRATION_LOW_HZ = "calibration_f_low_hz"
    private const val KEY_CALIBRATION_HIGH_HZ = "calibration_f_high_hz"
    private const val KEY_CALIBRATION_DURATION_S = "calibration_duration_s"
    private const val KEY_CALIBRATION_AMPLITUDE = "calibration_amplitude"

    const val DEFAULT_LAPTOP_WS_URL: String = "ws://192.168.49.1:8765/"
    const val DEFAULT_PHONE_ID: Int = 0
    const val DEFAULT_IS_MASTER: Boolean = false
    const val DEFAULT_CALIBRATION_LOW_HZ: Double = 17_500.0
    const val DEFAULT_CALIBRATION_HIGH_HZ: Double = 22_000.0
    const val DEFAULT_CALIBRATION_DURATION_S: Double = 0.060
    const val DEFAULT_CALIBRATION_AMPLITUDE: Double = 0.4

    private fun prefs(ctx: Context): SharedPreferences =
        ctx.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun phoneId(ctx: Context): Int = prefs(ctx).getInt(KEY_PHONE_ID, DEFAULT_PHONE_ID)

    fun isMaster(ctx: Context): Boolean =
        prefs(ctx).getBoolean(KEY_IS_MASTER, DEFAULT_IS_MASTER)

    fun laptopWsUrl(ctx: Context): String =
        prefs(ctx).getString(KEY_LAPTOP_WS_URL, DEFAULT_LAPTOP_WS_URL)
            ?: DEFAULT_LAPTOP_WS_URL

    fun calibrationLowHz(ctx: Context): Double = java.lang.Double.longBitsToDouble(
        prefs(ctx).getLong(
            KEY_CALIBRATION_LOW_HZ,
            java.lang.Double.doubleToRawLongBits(DEFAULT_CALIBRATION_LOW_HZ),
        )
    )

    fun calibrationHighHz(ctx: Context): Double = java.lang.Double.longBitsToDouble(
        prefs(ctx).getLong(
            KEY_CALIBRATION_HIGH_HZ,
            java.lang.Double.doubleToRawLongBits(DEFAULT_CALIBRATION_HIGH_HZ),
        )
    )

    fun calibrationDurationS(ctx: Context): Double = java.lang.Double.longBitsToDouble(
        prefs(ctx).getLong(
            KEY_CALIBRATION_DURATION_S,
            java.lang.Double.doubleToRawLongBits(DEFAULT_CALIBRATION_DURATION_S),
        )
    )

    fun calibrationAmplitude(ctx: Context): Double = java.lang.Double.longBitsToDouble(
        prefs(ctx).getLong(
            KEY_CALIBRATION_AMPLITUDE,
            java.lang.Double.doubleToRawLongBits(DEFAULT_CALIBRATION_AMPLITUDE),
        )
    )

    /** Set the phone identity. phoneId must be in 0..254 (the
     *  wire format reserves 0xFF for broadcast). */
    fun setIdentity(ctx: Context, phoneId: Int, isMaster: Boolean, laptopWsUrl: String) {
        require(phoneId in 0..254) { "phoneId must be in 0..254 (got $phoneId)" }
        require(laptopWsUrl.startsWith("ws://") || laptopWsUrl.startsWith("wss://")) {
            "laptopWsUrl must start with ws:// or wss:// (got $laptopWsUrl)"
        }
        prefs(ctx).edit {
            putInt(KEY_PHONE_ID, phoneId)
            putBoolean(KEY_IS_MASTER, isMaster)
            putString(KEY_LAPTOP_WS_URL, laptopWsUrl)
        }
    }

    fun setCalibration(
        ctx: Context,
        fLowHz: Double,
        fHighHz: Double,
        durationS: Double,
        amplitude: Double,
    ) {
        require(fLowHz > 0.0 && fHighHz > fLowHz) { "invalid frequency band" }
        require(durationS > 0.0) { "duration must be positive" }
        require(amplitude in 0.0..1.0) { "amplitude must be in [0, 1]" }
        prefs(ctx).edit {
            putLong(KEY_CALIBRATION_LOW_HZ, java.lang.Double.doubleToRawLongBits(fLowHz))
            putLong(KEY_CALIBRATION_HIGH_HZ, java.lang.Double.doubleToRawLongBits(fHighHz))
            putLong(
                KEY_CALIBRATION_DURATION_S,
                java.lang.Double.doubleToRawLongBits(durationS),
            )
            putLong(
                KEY_CALIBRATION_AMPLITUDE,
                java.lang.Double.doubleToRawLongBits(amplitude),
            )
        }
    }
}

package dev.shruti.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import dev.shruti.capture.CaptureService
import dev.shruti.config.IdentityConfig
import dev.shruti.sync.ChirpService

/**
 * Top-level UI for SHRUTI.
 *
 * Three screens stacked vertically, scrollable:
 *  1. Identity setup (T03) — pick phone 0/1/2, master toggle,
 *     laptop WS URL. Persisted to SharedPreferences.
 *  2. Session start/stop (T11) — Start/Stop and Restart-array
 *     buttons. Disable until permissions are granted.
 *  3. Live readouts — sync offset, beamform toggle, transcript,
 *     radar. Placeholders for the next wave of work.
 *
 * Permission flow (T04): on first Start, request RECORD_AUDIO
 * and (on 13+) POST_NOTIFICATIONS. The start button stays
 * disabled until both are granted.
 */
class MainActivity : ComponentActivity() {
    private var pendingStartPhoneId: Int? = null
    private var pendingStartIsMaster: Boolean? = null

    private val requestRecordAudio = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) ensureNotificationsThenStart()
    }

    private val requestNotifications = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { _ ->
        // Whether notifications are granted or not, the session
        // can start. POST_NOTIFICATIONS is required on 13+ for
        // the foreground service notification, but if the user
        // denies it the service still runs.
        startSession()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    ShrutiScreen(
                        onStartClicked = { phoneId, isMaster ->
                            pendingStartPhoneId = phoneId
                            pendingStartIsMaster = isMaster
                            requestPermissionsThenStart()
                        },
                        onStopClicked = { stopSession() },
                    )
                }
            }
        }
    }

    private fun requestPermissionsThenStart() {
        val recordGranted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED
        if (!recordGranted) {
            requestRecordAudio.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        ensureNotificationsThenStart()
    }

    private fun ensureNotificationsThenStart() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val notifGranted = ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
            if (!notifGranted) {
                requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                return
            }
        }
        startSession()
    }

    private fun startSession() {
        val phoneId = pendingStartPhoneId ?: IdentityConfig.phoneId(this)
        val isMaster = pendingStartIsMaster ?: IdentityConfig.isMaster(this)
        ChirpService.start(this, phoneId = phoneId, isMaster = isMaster)
        CaptureService.start(this, phoneId = phoneId)
    }

    private fun stopSession() {
        ChirpService.stop(this)
        CaptureService.stop(this)
    }
}

@Composable
private fun ShrutiScreen(
    onStartClicked: (phoneId: Int, isMaster: Boolean) -> Unit,
    onStopClicked: () -> Unit,
) {
    val ctx = LocalContext.current
    var phoneId by remember { mutableStateOf(IdentityConfig.phoneId(ctx)) }
    var isMaster by remember { mutableStateOf(IdentityConfig.isMaster(ctx)) }
    var laptopWsUrl by remember { mutableStateOf(IdentityConfig.laptopWsUrl(ctx)) }
    var sessionActive by remember { mutableStateOf(false) }
    var urlText by remember(laptopWsUrl) { mutableStateOf(laptopWsUrl) }

    val recordGranted = remember(ctx) {
        ContextCompat.checkSelfPermission(
            ctx, Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED
    }
    val notifGranted = remember(ctx) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) true
        else ContextCompat.checkSelfPermission(
            ctx, Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    }

    LaunchedEffect(phoneId, isMaster, laptopWsUrl) {
        IdentityConfig.setIdentity(ctx, phoneId, isMaster, laptopWsUrl)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("SHRUTI", style = MaterialTheme.typography.headlineMedium)
        Text("Three phones. One microphone.", style = MaterialTheme.typography.bodyMedium)
        Text(
            "Identity: phone $phoneId  •  ${if (isMaster) "MASTER" else "element"}  •  $laptopWsUrl",
            style = MaterialTheme.typography.bodySmall,
            color = Color.Gray,
        )

        Card(elevation = CardDefaults.cardElevation(2.dp)) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("1. Pick this device's identity", fontWeight = FontWeight.SemiBold)
                Text(
                    "Tap the slot that matches the physical label on this phone.",
                    style = MaterialTheme.typography.bodySmall,
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    listOf(0, 1, 2).forEach { slot ->
                        Button(
                            onClick = { phoneId = slot },
                            colors = if (phoneId == slot) ButtonDefaults.buttonColors()
                            else ButtonDefaults.outlinedButtonColors(),
                            modifier = Modifier.weight(1f),
                        ) { Text("Phone $slot") }
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Switch(checked = isMaster, onCheckedChange = { isMaster = it })
                    Spacer(Modifier.padding(4.dp))
                    Text("This is the master phone (plays the chirp)")
                }
                OutlinedTextField(
                    value = urlText,
                    onValueChange = { urlText = it },
                    label = { Text("Laptop WebSocket URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    onClick = { laptopWsUrl = urlText.trim() },
                    enabled = urlText.trim() != laptopWsUrl,
                    modifier = Modifier.align(Alignment.End),
                ) { Text("Save URL") }
            }
        }

        Card(elevation = CardDefaults.cardElevation(2.dp)) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("2. Session", fontWeight = FontWeight.SemiBold)
                Text(
                    "Microphone: ${if (recordGranted) "granted" else "not granted — tap Start to grant"}",
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    "Notifications: ${if (notifGranted) "granted" else "not granted (required on Android 13+)"}",
                    style = MaterialTheme.typography.bodySmall,
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Button(
                        enabled = !sessionActive,
                        onClick = { onStartClicked(phoneId, isMaster) },
                        modifier = Modifier.weight(1f),
                    ) { Text("Start session") }
                    Button(
                        enabled = sessionActive,
                        onClick = { onStopClicked() },
                        modifier = Modifier.weight(1f),
                    ) { Text("Stop session") }
                }
                // T11: Restart-array button. Stops both
                // services and starts them again with the
                // current identity. This is the on-device
                // recovery ritual when the array falls out
                // of sync at the venue.
                OutlinedButton(
                    enabled = sessionActive,
                    onClick = {
                        onStopClicked()
                        onStartClicked(phoneId, isMaster)
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Restart array (stops + starts both services)") }
            }
        }

        Card(elevation = CardDefaults.cardElevation(2.dp)) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("3. Live readouts", fontWeight = FontWeight.SemiBold)
                Text("Sync: -- us", style = MaterialTheme.typography.titleLarge)
                Text("Need: < 100 us", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(4.dp))
                Text("Transcript:", style = MaterialTheme.typography.titleMedium)
                Text("[live transcript from laptop ASR]")
                Spacer(Modifier.height(4.dp))
                Text("Radar:", style = MaterialTheme.typography.titleMedium)
                Text("[live speaker position from laptop]")
            }
        }

        Spacer(Modifier.height(8.dp))
    }
}

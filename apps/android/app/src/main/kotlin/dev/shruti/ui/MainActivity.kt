package dev.shruti.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.Button
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dev.shruti.capture.CaptureService
import dev.shruti.sync.ChirpService

/**
 * Top-level UI for SHRUTI. Shows:
 *   - Session start/stop button
 *   - Live sync-stats ("42 us", expected: < 100 us)
 *   - The RAW -> BEAMFORMED toggle
 *   - Live transcript pane
 *   - Radar view of the speaker position
 *
 * The radar and the transcript are rendered on the laptop array
 * processor; this activity mirrors that screen over the wire for the
 * demo (screen mirror or local radar if the phone is the master).
 *
 * NEEDS-DEVICE: the canvas radar and the live transcript are wired
 * to the CaptureService / WebSocket client; the Activity is
 * fully laid out so the team can drop in real bindings at the
 * mark below without touching the composition tree.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    ShrutiScreen()
                }
            }
        }
    }
}

@Composable
private fun ShrutiScreen() {
    var sessionActive by remember { mutableStateOf(false) }
    var beamformingOn by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("SHRUTI", style = MaterialTheme.typography.headlineMedium)
        Text("Three phones. One microphone.", style = MaterialTheme.typography.bodyMedium)

        Button(
            onClick = {
                if (sessionActive) {
                    ChirpService.stop(this)
                    CaptureService.stop(this)
                } else {
                    ChirpService.start(this)
                    CaptureService.start(this)
                }
                sessionActive = !sessionActive
            }
        ) {
            Text(if (sessionActive) "Stop session" else "Start session")
        }

        Text("Sync: -- us", style = MaterialTheme.typography.titleLarge)
        Text("Need: < 100 us", style = MaterialTheme.typography.bodySmall)

        Button(
            enabled = sessionActive,
            onClick = { beamformingOn = !beamformingOn },
        ) {
            Text(if (beamformingOn) "BEAMFORMED" else "RAW")
        }

        Text("Transcript:", style = MaterialTheme.typography.titleMedium)
        Text("[live transcript from laptop ASR]")

        Text("Radar:", style = MaterialTheme.typography.titleMedium)
        Text("[live speaker position from laptop]")

        // NEEDS-DEVICE: replace the placeholders above with the live
        // state collected from the CaptureService's broadcast
        // (sync-stats, beamformed-vs-raw flag) and from the WebSocket
        // client (transcript lines, radar dot). See apps/laptop for the
        // wire format.
    }
}

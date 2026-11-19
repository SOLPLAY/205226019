# DEN Android node

This is a native Android client for the repository's monitor API:

- `POST /api/v1/enroll` with `node_id`, `node_name`, and `enrollment_code`
- `POST /api/v1/heartbeat` with the monitor's node report fields and a Bearer credential

It requires an HTTPS monitor URL and a PEM-encoded X.509 CA certificate. The client builds a private trust store from that certificate input only; it does not add the certificate to Android's system trust store or fall back to public/system CAs. HTTPS hostname verification remains enabled, redirects are not followed, and cleartext traffic is disabled.

The node UUID and returned credential are AES-GCM encrypted with an AES key held by Android Keystore. The enrollment code is not saved. Reports run every 5 seconds (matching the monitor's default interval) in a user-started foreground service, with a persistent notification and the most recent service/report status shown in the app. Android may still restrict background work under vendor battery policies.

## Build

Requirements: JDK 17, Android SDK Platform 35, and Android Build Tools installed. The project uses Gradle 8.9 with Android Gradle Plugin 8.7.3, which support the repository CI's JDK 17 Android SDK setup. From this directory:

```sh
./gradlew testDebugUnitTest
./gradlew assembleDebug
```

The APK is written to `app/build/outputs/apk/debug/app-debug.apk`. The first Gradle run downloads the Android Gradle Plugin and dependencies.

## Run

Install the debug APK on Android 8.0 (API 26) or newer. Enter a node name and either scan the coordinator's DEN pairing QR or manually enter the monitor HTTPS origin (for example `https://monitor.example:8443`), one-time enrollment code, and monitor CA certificate PEM. The scanner accepts JSON shaped as `{"type":"den-pairing-v1","monitor_url":"https://host:8443","enrollment_code":"...","ca_certificate_pem":"-----BEGIN CERTIFICATE-----..."}`; scanning fills those fields and immediately begins enrollment. QR contents are parsed locally; the app does not fetch URLs from the payload. Camera permission is requested only when scanning, and manual entry remains available if permission is denied. On Android 13 and later, allow notifications to see the foreground-service notification. Use **Stop reporting** to stop subsequent reports; the saved node identity and credential are retained for later starts.

The monitor's TLS certificate must chain to the provided CA and match the monitor URL hostname. This app does not configure or permit HTTP.

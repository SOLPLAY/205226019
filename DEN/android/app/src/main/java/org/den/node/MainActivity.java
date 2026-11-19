package org.den.node;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.google.zxing.integration.android.IntentIntegrator;
import com.google.zxing.integration.android.IntentResult;

import java.net.URI;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final int CAMERA_PERMISSION_REQUEST = 101;
    private SecureStore store;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private EditText nameInput;
    private EditText urlInput;
    private EditText codeInput;
    private EditText caInput;
    private TextView statusView;
    private TextView identityView;
    private Button primaryButton;
    private Button stopButton;
    private NodeProfile savedProfile;
    private final Runnable statusRefresh = new Runnable() {
        @Override public void run() {
            refreshStatus();
            handler.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        store = new SecureStore(this);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 100);
        }
        buildScreen();
        try {
            savedProfile = store.loadProfile();
            if (savedProfile != null) showSavedProfile();
        } catch (Exception exception) {
            setStatus("Could not read the saved node profile: " + message(exception));
        }
        handler.post(statusRefresh);
    }

    private void buildScreen() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = dp(20);
        layout.setPadding(padding, padding, padding, padding);
        scroll.addView(layout);

        TextView title = new TextView(this);
        title.setText("DEN monitor node");
        title.setTextSize(24);
        layout.addView(title);
        TextView help = new TextView(this);
        help.setText("Enroll once with your monitor's HTTPS address, one-time code, and PEM CA certificate.");
        help.setPadding(0, dp(8), 0, dp(16));
        layout.addView(help);

        Button scanButton = new Button(this);
        scanButton.setText("Scan pairing QR");
        scanButton.setOnClickListener(view -> scanPairingQr());
        layout.addView(scanButton);

        nameInput = addField(layout, "Node name", "This Android device", false);
        urlInput = addField(layout, "HTTPS monitor URL (origin only)", "https://monitor.example:8443", false);
        codeInput = addField(layout, "One-time enrollment code", "", false);
        caInput = addField(layout, "PEM CA certificate", "", true);
        caInput.setMinLines(6);
        caInput.setGravity(android.view.Gravity.TOP | android.view.Gravity.START);

        identityView = new TextView(this);
        identityView.setPadding(0, dp(10), 0, dp(4));
        layout.addView(identityView);
        statusView = new TextView(this);
        statusView.setTextSize(16);
        statusView.setPadding(0, dp(8), 0, dp(12));
        layout.addView(statusView);

        primaryButton = new Button(this);
        primaryButton.setText("Enroll and start reporting");
        primaryButton.setOnClickListener(view -> enrollAndStart());
        layout.addView(primaryButton);
        stopButton = new Button(this);
        stopButton.setText("Stop reporting");
        stopButton.setOnClickListener(view -> stopReporting());
        layout.addView(stopButton);
        setContentView(scroll);
        updateButtons();
    }

    private EditText addField(LinearLayout parent, String label, String hint, boolean multiline) {
        TextView title = new TextView(this);
        title.setText(label);
        title.setPadding(0, dp(8), 0, dp(4));
        parent.addView(title);
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setSingleLine(!multiline);
        input.setInputType(multiline
                ? android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
                : android.text.InputType.TYPE_CLASS_TEXT);
        parent.addView(input);
        return input;
    }

    private void enrollAndStart() {
        if (savedProfile != null) {
            startReporting();
            return;
        }

        private void scanPairingQr() {
            if (savedProfile != null) {
                setStatus("This node is already enrolled. Stop reporting before pairing another node.");
                return;
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                    && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQUEST);
                return;
            }
            new IntentIntegrator(this)
                    .setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
                    .setPrompt("Scan DEN pairing QR")
                    .setBeepEnabled(false)
                    .setOrientationLocked(false)
                    .initiateScan();
        }

        @Override
        protected void onActivityResult(int requestCode, int resultCode, Intent data) {
            IntentResult result = IntentIntegrator.parseActivityResult(requestCode, resultCode, data);
            if (result != null) {
                String contents = result.getContents();
                if (contents == null) {
                    setStatus("Pairing scan cancelled.");
                } else {
                    applyPairingPayload(contents);
                }
                return;
            }
            super.onActivityResult(requestCode, resultCode, data);
        }

        private void applyPairingPayload(String contents) {
            try {
                JSONObject payload = new JSONObject(contents);
                if (!"den-pairing-v1".equals(payload.optString("type"))) {
                    throw new IllegalArgumentException("QR code is not a supported DEN pairing payload.");
                }
                String monitorUrl = payload.getString("monitor_url").trim();
                String enrollmentCode = payload.getString("enrollment_code").trim();
                String caPem = payload.getString("ca_certificate_pem").trim();
                URI uri = URI.create(monitorUrl);
                if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                        || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                        || !(uri.getPath().isEmpty() || "/".equals(uri.getPath()))) {
                    throw new IllegalArgumentException("Pairing monitor_url must be an HTTPS origin.");
                }
                if (enrollmentCode.isEmpty() || caPem.isEmpty()) {
                    throw new IllegalArgumentException("Pairing code or CA certificate is empty.");
                }
                urlInput.setText(monitorUrl);
                codeInput.setText(enrollmentCode);
                caInput.setText(caPem);
                setStatus("Pairing details scanned. Enrolling…");
                enrollAndStart();
            } catch (Exception exception) {
                setStatus("Pairing scan failed: " + message(exception));
            }
        }

        @Override
        public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
            super.onRequestPermissionsResult(requestCode, permissions, grantResults);
            if (requestCode == CAMERA_PERMISSION_REQUEST) {
                if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                    scanPairingQr();
                } else {
                    setStatus("Camera permission is needed to scan a pairing QR. Manual entry is still available.");
                }
            }
        }
        String nodeName = nameInput.getText().toString().trim();
        String monitorUrl = urlInput.getText().toString().trim();
        String enrollmentCode = codeInput.getText().toString().trim();
        String caPem = caInput.getText().toString().trim();
        if (nodeName.isEmpty() || nodeName.length() > 128) {
            setStatus("Node name is required and must be at most 128 characters.");
            return;
        }
        if (enrollmentCode.isEmpty()) {
            setStatus("Enter the one-time enrollment code.");
            return;
        }
        hideKeyboard();
        primaryButton.setEnabled(false);
        setStatus("Validating certificate and enrolling…");
        executor.execute(() -> {
            try {
                String nodeId = store.getOrCreateNodeId();
                MonitorClient client = new MonitorClient(monitorUrl, caPem);
                org.json.JSONObject response = client.enroll(nodeId, nodeName, enrollmentCode);
                NodeProfile profile = new NodeProfile(
                        nodeId, nodeName, normalizeUrl(monitorUrl), caPem, response.getString("credential"));
                store.saveProfile(profile);
                runOnUiThread(() -> {
                    savedProfile = profile;
                    codeInput.setText("");
                    showSavedProfile();
                    startReporting();
                });
            } catch (Exception exception) {
                runOnUiThread(() -> {
                    primaryButton.setEnabled(true);
                    setStatus("Enrollment failed: " + message(exception));
                });
            }
        });
    }

    private static String normalizeUrl(String value) {
        URI uri = URI.create(value.trim());
        return "https://" + uri.getRawAuthority();
    }

    private void showSavedProfile() {
        nameInput.setText(savedProfile.nodeName);
        urlInput.setText(savedProfile.monitorUrl);
        caInput.setText(savedProfile.caPem);
        codeInput.setVisibility(View.GONE);
        setEditable(nameInput, false);
        setEditable(urlInput, false);
        setEditable(caInput, false);
        primaryButton.setText("Start reporting");
        identityView.setText("Node ID: " + savedProfile.nodeId);
        updateButtons();
    }

    private static void setEditable(EditText input, boolean enabled) {
        input.setEnabled(enabled);
        input.setFocusable(enabled);
        input.setFocusableInTouchMode(enabled);
    }

    private void startReporting() {
        Intent service = new Intent(this, HeartbeatService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(service);
        else startService(service);
        setStatus("Starting report service…");
        updateButtons();
    }

    private void stopReporting() {
        stopService(new Intent(this, HeartbeatService.class));
        setStatus("Stopped");
        updateButtons();
    }

    private void refreshStatus() {
        String status = getSharedPreferences(HeartbeatService.STATUS_PREFS, MODE_PRIVATE)
                .getString(HeartbeatService.STATUS_KEY, "Not reporting");
        if (!HeartbeatService.isRunning() && (status.startsWith("Active") || status.startsWith("Starting"))) {
            status = "Not reporting";
        }
        if (statusView != null && !"Starting".equals(status)) statusView.setText(status);
        updateButtons();
    }

    private void updateButtons() {
        if (primaryButton == null || stopButton == null) return;
        boolean reporting = HeartbeatService.isRunning();
        boolean profileExists = savedProfile != null;
        primaryButton.setVisibility(profileExists && reporting ? View.GONE : View.VISIBLE);
        primaryButton.setText(profileExists ? "Start reporting" : "Enroll and start reporting");
        stopButton.setVisibility(profileExists && !reporting ? View.GONE : View.VISIBLE);
    }

    private void setStatus(String status) {
        if (statusView != null) statusView.setText(status);
    }

    private void hideKeyboard() {
        InputMethodManager inputManager = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (inputManager != null) inputManager.hideSoftInputFromWindow(caInput.getWindowToken(), 0);
    }

    private static String message(Exception exception) {
        return exception.getMessage() == null ? exception.getClass().getSimpleName() : exception.getMessage();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(statusRefresh);
        executor.shutdownNow();
        super.onDestroy();
    }
}

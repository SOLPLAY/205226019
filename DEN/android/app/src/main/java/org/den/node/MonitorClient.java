package org.den.node;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.util.Collection;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;

final class MonitorClient {
    private static final int TIMEOUT_MILLIS = 15000;
    private final String baseUrl;
    private final SSLContext sslContext;

    MonitorClient(String monitorUrl, String caPem) throws Exception {
        URI uri = URI.create(monitorUrl.trim());
        if (!"https".equalsIgnoreCase(uri.getScheme())
                || uri.getHost() == null
                || uri.getUserInfo() != null
                || uri.getQuery() != null
                || uri.getFragment() != null
                || !(uri.getPath().isEmpty() || "/".equals(uri.getPath()))) {
            throw new IllegalArgumentException("Monitor URL must be an HTTPS origin, such as https://monitor.example:8443.");
        }
        baseUrl = "https://" + uri.getRawAuthority();

        CertificateFactory factory = CertificateFactory.getInstance("X.509");
        Collection<? extends Certificate> certificates = factory.generateCertificates(
                new ByteArrayInputStream(caPem.getBytes(StandardCharsets.US_ASCII)));
        if (certificates.isEmpty()) throw new IllegalArgumentException("Enter at least one PEM X.509 CA certificate.");
        KeyStore anchors = KeyStore.getInstance(KeyStore.getDefaultType());
        anchors.load(null);
        int index = 0;
        for (Certificate certificate : certificates) anchors.setCertificateEntry("user-ca-" + index++, certificate);
        TrustManagerFactory trustManagers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        trustManagers.init(anchors);
        sslContext = SSLContext.getInstance("TLS");
        sslContext.init(null, trustManagers.getTrustManagers(), null);
    }

    JSONObject enroll(String nodeId, String nodeName, String enrollmentCode) throws Exception {
        JSONObject body = new JSONObject()
                .put("node_id", nodeId)
                .put("node_name", nodeName)
                .put("enrollment_code", enrollmentCode);
        JSONObject response = post("/api/v1/enroll", body, null);
        if (!nodeId.equals(response.optString("node_id")) || response.optString("credential").isEmpty()) {
            throw new IOException("Monitor returned an invalid enrollment credential.");
        }
        return response;
    }

    void heartbeat(NodeProfile profile, double uptimeSeconds) throws Exception {
        String platform = android.os.Build.MODEL == null
                ? "Android " + android.os.Build.VERSION.RELEASE
                : "Android " + android.os.Build.VERSION.RELEASE + " (" + android.os.Build.MODEL + ")";
        JSONObject body = new JSONObject(HeartbeatPayload.create(
                profile.nodeId, profile.nodeName, uptimeSeconds, platform, "1.0.0"));
        post("/api/v1/heartbeat", body, profile.credential);
    }

    private JSONObject post(String endpoint, JSONObject body, String credential) throws Exception {
        URL url = new URL(baseUrl + endpoint);
        HttpsURLConnection connection = (HttpsURLConnection) url.openConnection();
        connection.setSSLSocketFactory(sslContext.getSocketFactory());
        connection.setConnectTimeout(TIMEOUT_MILLIS);
        connection.setReadTimeout(TIMEOUT_MILLIS);
        connection.setRequestMethod("POST");
        connection.setInstanceFollowRedirects(false);
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        connection.setRequestProperty("Accept", "application/json");
        if (credential != null) connection.setRequestProperty("Authorization", "Bearer " + credential);
        byte[] request = body.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(request.length);
        try {
            try (OutputStream output = connection.getOutputStream()) {
                output.write(request);
            }
            int status = connection.getResponseCode();
            InputStream responseStream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            String responseText = responseStream == null ? "" : readText(responseStream);
            if (status < 200 || status >= 300) {
                String detail = responseText;
                try {
                    detail = new JSONObject(responseText).optString("error", responseText);
                } catch (JSONException ignored) {
                }
                throw new IOException("Monitor returned HTTP " + status + (detail.isEmpty() ? "" : ": " + detail));
            }
            return new JSONObject(responseText);
        } finally {
            connection.disconnect();
        }
    }

    private static String readText(InputStream input) throws IOException {
        try (InputStream stream = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int length;
            while ((length = stream.read(buffer)) != -1) output.write(buffer, 0, length);
            return output.toString(StandardCharsets.UTF_8.name());
        }
    }
}

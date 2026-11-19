package org.den.node;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;

final class HeartbeatPayload {
    private HeartbeatPayload() {}

    static Map<String, Object> create(
            String nodeId, String nodeName, double uptimeSeconds, String platform, String version) {
        if (nodeId == null || nodeId.isEmpty() || nodeId.length() > 128) {
            throw new IllegalArgumentException("node_id must contain 1 to 128 characters.");
        }
        if (nodeName == null || nodeName.isEmpty() || nodeName.length() > 128) {
            throw new IllegalArgumentException("node_name must contain 1 to 128 characters.");
        }
        if (Double.isNaN(uptimeSeconds) || Double.isInfinite(uptimeSeconds) || uptimeSeconds < 0) {
            throw new IllegalArgumentException("uptime_seconds must be a non-negative number.");
        }
        if (platform == null || platform.length() > 256) {
            throw new IllegalArgumentException("platform must contain at most 256 characters.");
        }
        if (version == null || version.length() > 64) {
            throw new IllegalArgumentException("version must contain at most 64 characters.");
        }
        Map<String, Object> report = new LinkedHashMap<>();
        report.put("node_id", nodeId);
        report.put("node_name", nodeName);
        report.put("uptime_seconds", uptimeSeconds);
        report.put("platform", platform);
        report.put("version", version);
        report.put("peers", new ArrayList<>());
        return report;
    }
}

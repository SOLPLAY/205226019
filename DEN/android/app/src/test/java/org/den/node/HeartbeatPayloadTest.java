package org.den.node;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class HeartbeatPayloadTest {
    @Test
    public void createsReportWithMonitorSchema() {
        Map<String, Object> report = HeartbeatPayload.create(
                "node-1", "Phone", 12.5, "Android 15", "1.0.0");

        assertEquals(Arrays.asList("node_id", "node_name", "uptime_seconds", "platform", "version", "peers"),
                new ArrayList<>(report.keySet()));
        assertEquals("node-1", report.get("node_id"));
        assertEquals("Phone", report.get("node_name"));
        assertEquals(12.5, (Double) report.get("uptime_seconds"), 0.0);
        assertTrue(((java.util.List<?>) report.get("peers")).isEmpty());
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsNegativeUptime() {
        HeartbeatPayload.create("node-1", "Phone", -1, "Android", "1.0.0");
    }
}

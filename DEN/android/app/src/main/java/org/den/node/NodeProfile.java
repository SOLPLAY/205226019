package org.den.node;

import org.json.JSONException;
import org.json.JSONObject;

final class NodeProfile {
    final String nodeId;
    final String nodeName;
    final String monitorUrl;
    final String caPem;
    final String credential;

    NodeProfile(String nodeId, String nodeName, String monitorUrl, String caPem, String credential) {
        this.nodeId = nodeId;
        this.nodeName = nodeName;
        this.monitorUrl = monitorUrl;
        this.caPem = caPem;
        this.credential = credential;
    }

    JSONObject toJson() throws JSONException {
        return new JSONObject()
                .put("node_id", nodeId)
                .put("node_name", nodeName)
                .put("monitor_url", monitorUrl)
                .put("ca_pem", caPem)
                .put("credential", credential);
    }

    static NodeProfile fromJson(JSONObject json) throws JSONException {
        return new NodeProfile(
                json.getString("node_id"),
                json.getString("node_name"),
                json.getString("monitor_url"),
                json.getString("ca_pem"),
                json.getString("credential"));
    }
}

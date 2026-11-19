package org.den.node;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.UUID;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class SecureStore {
    private static final String KEY_ALIAS = "den.node.profile.v1";
    private static final String STORE = "den_secure";
    private static final String PROFILE = "profile";
    private static final String NODE_ID = "node_id";

    private final SharedPreferences preferences;

    SecureStore(Context context) {
        preferences = context.getSharedPreferences(STORE, Context.MODE_PRIVATE);
    }

    synchronized String getOrCreateNodeId() throws Exception {
        String nodeId = readSecret(NODE_ID);
        if (nodeId == null) {
            nodeId = UUID.randomUUID().toString();
            writeSecret(NODE_ID, nodeId);
        }
        return nodeId;
    }

    synchronized NodeProfile loadProfile() throws Exception {
        String encoded = readSecret(PROFILE);
        if (encoded == null) return null;
        try {
            return NodeProfile.fromJson(new JSONObject(encoded));
        } catch (JSONException exception) {
            throw new IllegalStateException("Saved node profile is invalid.", exception);
        }
    }

    synchronized void saveProfile(NodeProfile profile) throws Exception {
        writeSecret(PROFILE, profile.toJson().toString());
    }

    private String readSecret(String name) throws Exception {
        String stored = preferences.getString(name, null);
        if (stored == null) return null;
        byte[] combined = Base64.decode(stored, Base64.NO_WRAP);
        if (combined.length <= 12) throw new IllegalStateException("Saved secure data is invalid.");
        byte[] iv = new byte[12];
        byte[] ciphertext = new byte[combined.length - iv.length];
        System.arraycopy(combined, 0, iv, 0, iv.length);
        System.arraycopy(combined, iv.length, ciphertext, 0, ciphertext.length);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getKey(), new GCMParameterSpec(128, iv));
        return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
    }

    private void writeSecret(String name, String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getKey());
        byte[] iv = cipher.getIV();
        byte[] ciphertext = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
        byte[] combined = new byte[iv.length + ciphertext.length];
        System.arraycopy(iv, 0, combined, 0, iv.length);
        System.arraycopy(ciphertext, 0, combined, iv.length, ciphertext.length);
        if (!preferences.edit().putString(name, Base64.encodeToString(combined, Base64.NO_WRAP)).commit()) {
            throw new IllegalStateException("Could not save secure node data.");
        }
    }

    private SecretKey getKey() throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        if (keyStore.containsAlias(KEY_ALIAS)) {
            return (SecretKey) keyStore.getKey(KEY_ALIAS, null);
        }
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build());
        return generator.generateKey();
    }
}

package org.den.node;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.IBinder;
import android.os.SystemClock;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class HeartbeatService extends Service {
    static final String ACTION_STOP = "org.den.node.STOP_REPORTING";
    static final String STATUS_PREFS = "den_status";
    static final String STATUS_KEY = "status";
    private static final String CHANNEL_ID = "den_reporting";
    private static final int NOTIFICATION_ID = 2052;
    private static volatile boolean running;
    private ExecutorService worker;
    private volatile boolean stopping;
    private boolean workerStarted;

    @Override
    public void onCreate() {
        super.onCreate();
        running = true;
        createNotificationChannel();
        worker = Executors.newSingleThreadExecutor();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopping = true;
            stopForeground(true);
            stopSelf();
            return START_NOT_STICKY;
        }
        startForeground(NOTIFICATION_ID, notification("Starting"));
        publishStatus("Starting");
        if (!workerStarted && !worker.isShutdown() && !worker.isTerminated()) {
            workerStarted = true;
            worker.execute(this::reportLoop);
        }
        return START_STICKY;
    }

    private void reportLoop() {
        final long startedAt = SystemClock.elapsedRealtime();
        try {
            NodeProfile profile = new SecureStore(this).loadProfile();
            if (profile == null) throw new IllegalStateException("Enroll this node before starting reports.");
            MonitorClient client = new MonitorClient(profile.monitorUrl, profile.caPem);
            while (!stopping) {
                try {
                    client.heartbeat(profile, (SystemClock.elapsedRealtime() - startedAt) / 1000.0);
                    publishStatus("Active · last report accepted");
                    updateNotification("Active · last report accepted");
                } catch (Exception exception) {
                    String message = exception.getMessage();
                    String status = "Report error: " + (message == null ? exception.getClass().getSimpleName() : message);
                    publishStatus(status);
                    updateNotification(status);
                }
                if (!stopping) Thread.sleep(5000);
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        } catch (Exception exception) {
            String message = exception.getMessage();
            String status = "Stopped: " + (message == null ? exception.getClass().getSimpleName() : message);
            publishStatus(status);
            updateNotification(status);
            stopping = true;
            stopSelf();
        }
    }

    private void publishStatus(String status) {
        getSharedPreferences(STATUS_PREFS, MODE_PRIVATE).edit()
                .putString(STATUS_KEY, status)
                .apply();
    }

    private Notification notification(String status) {
        Intent activityIntent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this, 0, activityIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("DEN Node")
                .setContentText(status)
                .setContentIntent(pendingIntent)
                .setOngoing(!stopping)
                .build();
    }

    private void updateNotification(String status) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.notify(NOTIFICATION_ID, notification(status));
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "DEN node reporting", NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
    }

    @Override
    public void onDestroy() {
        stopping = true;
        running = false;
        if (worker != null) worker.shutdownNow();
        getSharedPreferences(STATUS_PREFS, MODE_PRIVATE).edit()
                .putString(STATUS_KEY, "Stopped")
                .apply();
        super.onDestroy();
    }

    static boolean isRunning() {
        return running;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}

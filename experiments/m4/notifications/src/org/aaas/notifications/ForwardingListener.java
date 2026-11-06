package org.aaas.notifications;

import android.app.Notification;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import android.util.Base64;
import android.util.Log;

import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.nio.charset.Charset;
import java.util.UUID;

/** User-authorized Android listener; forwards only bounded display metadata. */
public final class ForwardingListener extends NotificationListenerService {
    private static final String TAG = "AaasNotificationListener";
    private static final String IPC = "/dev/aaas/notifications";
    private static final int MAX_FRAME = 32 * 1024;

    @Override public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null || sbn.getNotification() == null) return;
        Notification notification = sbn.getNotification();
        if (notification.visibility == Notification.VISIBILITY_SECRET) return;
        String title = notification.extras == null ? "" :
                text(notification.extras.getCharSequence(Notification.EXTRA_TITLE), 1024);
        String body = notification.extras == null ? "" :
                text(notification.extras.getCharSequence(Notification.EXTRA_TEXT), 8192);
        String label = sbn.getPackageName();
        try {
            CharSequence app = getPackageManager().getApplicationLabel(
                    getPackageManager().getApplicationInfo(sbn.getPackageName(), 0));
            if (app != null) label = text(app, 256);
        } catch (Exception ignored) { }
        publish('P', sbn.getPackageName(),
                Integer.toString(sbn.getUser().getIdentifier()), sbn.getKey(),
                label, title, body);
    }

    @Override public void onNotificationRemoved(StatusBarNotification sbn) {
        if (sbn == null) return;
        publish('R', sbn.getPackageName(),
                Integer.toString(sbn.getUser().getIdentifier()), sbn.getKey());
    }

    private static String text(CharSequence value, int maxBytes) {
        if (value == null) return "";
        String result = value.toString();
        if (result.getBytes(Charset.forName("UTF-8")).length > maxBytes) return "";
        return result.indexOf('\0') >= 0 ? "" : result;
    }

    private static String field(String value) {
        return Base64.encodeToString(value.getBytes(Charset.forName("UTF-8")),
                Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    private synchronized void publish(char kind, String... fields) {
        File directory = new File(IPC);
        if (!directory.isDirectory()) {
            Log.w(TAG, "notification event transport directory unavailable");
            return;
        }
        String stage = "encode";
        try {
            StringBuilder frame = new StringBuilder("AASN1\n").append(kind).append('\n');
            for (String value : fields) frame.append(field(value)).append('\n');
            byte[] bytes = frame.toString().getBytes(Charset.forName("US-ASCII"));
            if (bytes.length > MAX_FRAME) return;
            String id = UUID.randomUUID().toString().replace("-", "");
            File temporary = new File(directory, ".event-" + id + ".tmp");
            File destination = new File(directory, "event-" + id + ".frame");
            stage = "open";
            FileDescriptor fd = android.system.Os.open(temporary.getAbsolutePath(),
                    android.system.OsConstants.O_WRONLY | android.system.OsConstants.O_CREAT |
                            android.system.OsConstants.O_EXCL, 0640);
            FileOutputStream output = new FileOutputStream(fd);
            try {
                stage = "write";
                output.write(bytes);
                stage = "sync";
                output.getFD().sync();
            } finally { output.close(); }
            stage = "rename";
            if (!temporary.renameTo(destination)) temporary.delete();
        } catch (android.system.ErrnoException error) {
            Log.w(TAG, "notification event transport failed stage=" + stage +
                    " errno=" + error.errno);
        } catch (Exception error) {
            // Do not log notification content or exception messages that may include it.
            Log.w(TAG, "notification event transport failed stage=" + stage +
                    " type=" + error.getClass().getSimpleName());
        }
    }
}

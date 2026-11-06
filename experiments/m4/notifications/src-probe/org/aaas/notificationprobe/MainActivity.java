package org.aaas.notificationprobe;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Small ordinary-app probe; all notifications are posted via NotificationManager. */
public final class MainActivity extends Activity {
    private static final int REQUEST_POST = 8;
    private static final String CHANNEL = "aaas_acceptance";
    private NotificationManager manager;
    private String pending = "post";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,
                "AaaS acceptance", NotificationManager.IMPORTANCE_DEFAULT));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        TextView title = new TextView(this);
        title.setText("AaaS notification integration probe");
        root.addView(title);
        addButton(root, "Post", "post");
        addButton(root, "Update", "update");
        addButton(root, "Cancel", "cancel");
        setContentView(root);
        perform(getIntent());
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        perform(intent);
    }

    private void addButton(LinearLayout root, String label, final String action) {
        Button button = new Button(this);
        button.setText(label);
        button.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { runAction(action); }
        });
        root.addView(button);
    }

    private void perform(Intent intent) {
        String action = intent == null ? null : intent.getStringExtra("action");
        runAction(action == null ? "post" : action);
    }

    private void runAction(String action) {
        if (!(action.equals("post") || action.equals("update") || action.equals("cancel"))) return;
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            pending = action;
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQUEST_POST);
            return;
        }
        if (action.equals("cancel")) {
            manager.cancel("aaas-test", 7);
            return;
        }
        String suffix = action.equals("update") ? "updated" : "initial";
        Notification notification = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(getPackageName() + " " + suffix)
                .setContentText("AaaS notification test " + suffix)
                .setAutoCancel(false).build();
        manager.notify("aaas-test", 7, notification);
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions,
                                                      int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == REQUEST_POST && results.length > 0 &&
                results[0] == PackageManager.PERMISSION_GRANTED) runAction(pending);
    }
}

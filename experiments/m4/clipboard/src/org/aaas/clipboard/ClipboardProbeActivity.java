package org.aaas.clipboard;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.View;
import android.widget.EditText;

import java.nio.charset.Charset;
import java.security.MessageDigest;

/** Disposable live acceptance probe: real ClipboardManager and EditText paste. */
public final class ClipboardProbeActivity extends Activity {
    private static final String TAG = "AaasClipboardProbe";
    private static final String ANDROID_FIXTURE = "AaaS Android → Linux\nनमस्ते 你好\n punctuation: !?  ";
    private EditText field;
    private ClipboardManager clipboard;
    private Handler handler;
    private ClipboardManager.OnPrimaryClipChangedListener listener;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        field = new EditText(this);
        field.setSingleLine(false);
        field.setText("");
        setContentView(field);
        clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
        handler = new Handler(Looper.getMainLooper());
        listener = new ClipboardManager.OnPrimaryClipChangedListener() {
            @Override public void onPrimaryClipChanged() {
                Log.i(TAG, "primary clipboard callback");
                // Defer clipboard reads until the system clipboard callback and
                // any setPrimaryClip() transaction that caused it have returned.
                handler.postDelayed(new Runnable() {
                    @Override public void run() { pasteHostClip(); }
                }, 50);
            }
        };
        clipboard.addPrimaryClipChangedListener(listener);
    }

    @Override public void onResume() {
        super.onResume();
        applyMode(getIntent());
    }

    @Override public void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        applyMode(intent);
    }

    private void applyMode(android.content.Intent intent) {
        String mode = intent == null ? null : intent.getStringExtra("mode");
        if ("android-copy".equals(mode)) {
            field.setText(ANDROID_FIXTURE);
            field.selectAll();
            boolean copied = field.onTextContextMenuItem(android.R.id.copy);
            Log.i(TAG, "ANDROID_EDITTEXT_COPY action=" + copied +
                    " sha256=" + digest(ANDROID_FIXTURE));
        } else {
            Log.i(TAG, "READY_FOR_HOST_PASTE");
            pasteHostClip();
        }
    }

    private void pasteHostClip() {
        if (field == null || clipboard == null) return;
        ClipData clip;
        try {
            clip = clipboard.getPrimaryClip();
        } catch (SecurityException denied) {
            Log.i(TAG, "clipboard paste read denied by Android policy");
            return;
        }
        if (clip == null || clip.getDescription() == null ||
                !ClipboardImeService.HOST_LABEL.contentEquals(
                        clip.getDescription().getLabel())) {
            Log.i(TAG, "clipboard probe found no host-labelled clip");
            return;
        }
        field.setText("");
        field.requestFocus();
        boolean pasteAction = field.onTextContextMenuItem(android.R.id.paste);
        String pasted = field.getText().toString();
        Log.i(TAG, "ANDROID_EDITTEXT_PASTE action=" + pasteAction +
                " sha256=" + digest(pasted));
    }

    @Override public void onDestroy() {
        if (clipboard != null && listener != null)
            clipboard.removePrimaryClipChangedListener(listener);
        listener = null;
        handler = null;
        clipboard = null;
        field = null;
        super.onDestroy();
    }

    private static String digest(String value) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(Charset.forName("UTF-8")));
            StringBuilder out = new StringBuilder(bytes.length * 2);
            for (byte item : bytes) out.append(String.format("%02x", item & 0xff));
            return out.toString();
        } catch (Exception error) { return "digest-error"; }
    }
}

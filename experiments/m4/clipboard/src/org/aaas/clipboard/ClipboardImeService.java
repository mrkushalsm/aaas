package org.aaas.clipboard;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.inputmethodservice.InputMethodService;
import android.system.Os;
import android.system.OsConstants;
import android.view.inputmethod.EditorInfo;

import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.nio.charset.Charset;
import java.util.UUID;

/** User-selected Android default IME; Android grants the default IME clipboard access. */
public final class ClipboardImeService extends InputMethodService {
    static final String HOST_LABEL = "AaaS Linux clipboard";
    private static final String IPC_PATH = "/dev/aaas/clipboard";
    private static final int MAX_TEXT_BYTES = 64 * 1024;
    private ClipboardManager clipboard;
    private ClipboardManager.OnPrimaryClipChangedListener listener;

    @Override
    public void onCreate() {
        super.onCreate();
        clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
        listener = new ClipboardManager.OnPrimaryClipChangedListener() {
            @Override public void onPrimaryClipChanged() { exportPrimaryClip(); }
        };
        if (clipboard != null) clipboard.addPrimaryClipChangedListener(listener);
    }

    @Override
    public void onStartInput(EditorInfo attribute, boolean restarting) {
        super.onStartInput(attribute, restarting);
        // Registration is scoped to the user-selected default IME. This also
        // catches a clip already present when an editor becomes active.
        exportPrimaryClip();
    }

    @Override
    public void onDestroy() {
        if (clipboard != null && listener != null)
            clipboard.removePrimaryClipChangedListener(listener);
        listener = null;
        clipboard = null;
        super.onDestroy();
    }

    private void exportPrimaryClip() {
        ClipboardManager manager = clipboard;
        if (manager == null) return;
        try {
            ClipData clip = manager.getPrimaryClip();
            if (clip != null && clip.getDescription() != null) {
                CharSequence label = clip.getDescription().getLabel();
                if (label != null && HOST_LABEL.contentEquals(label)) return;
            }
            String text = null;
            if (clip != null && clip.getItemCount() > 0) {
                CharSequence value = clip.getItemAt(0).getText();
                if (value == null) return; // Do not turn URI/image clips into empty text.
                text = value.toString();
            }
            byte[] payload = text == null ? new byte[0]
                    : text.getBytes(Charset.forName("UTF-8"));
            if (payload.length > MAX_TEXT_BYTES) return;
            publish(payload, text == null || payload.length == 0 ? 'C' : 'T');
        } catch (SecurityException ignored) {
            // Android may revoke the default-IME role while this callback is in flight.
        } catch (Exception ignored) {
            // Clipboard contents must not be written to logcat.
        }
    }

    private synchronized void publish(byte[] payload, char kind) throws Exception {
        File directory = new File(IPC_PATH);
        if (!directory.isDirectory()) return;
        String id = UUID.randomUUID().toString();
        File temporary = new File(directory, ".android-" + id + ".tmp");
        File destination = new File(directory, "android-" + id + ".frame");
        FileDescriptor descriptor = Os.open(temporary.getAbsolutePath(),
                OsConstants.O_WRONLY | OsConstants.O_CREAT | OsConstants.O_EXCL,
                0600);
        FileOutputStream stream = new FileOutputStream(descriptor);
        try {
            stream.write("AASCLIP1\n".getBytes(Charset.forName("US-ASCII")));
            stream.write((kind + "\n").getBytes(Charset.forName("US-ASCII")));
            if (payload.length != 0) stream.write(payload);
            stream.getFD().sync();
        } finally {
            stream.close();
        }
        // The package owns a private, unpredictable file in a sticky, non-listable
        // directory. Other apps cannot read or remove it. The host bridge accepts
        // files only from the selected IME's UID and unlinks each consumed frame.
        if (!temporary.renameTo(destination)) temporary.delete();
    }
}

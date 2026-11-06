package org.aaas.clipboard;

import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;

import java.io.File;
import java.io.FileInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.Charset;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;

/** Receives a payload-free shell signal and reads a package-UID-only ACL file. */
public final class HostClipboardReceiver extends BroadcastReceiver {
    public static final String ACTION = "org.aaas.clipboard.SET";
    private static final String IPC_FILE = "/dev/aaas/clipboard_host_to_android";
    private static final int MAX_TEXT_BYTES = 64 * 1024;

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION.equals(intent.getAction())) return;
        byte[] bytes = readBounded(new File(IPC_FILE));
        if (bytes == null) return;
        try {
            String header = "AASCLIP1\n";
            if (bytes.length < header.length() + 2 ||
                    !startsWith(bytes, header.getBytes(Charset.forName("US-ASCII")))) return;
            int offset = header.length();
            char kind = (char) bytes[offset];
            if (bytes[offset + 1] != '\n' || (kind != 'T' && kind != 'C')) return;
            int count = bytes.length - offset - 2;
            if (count < 0 || count > MAX_TEXT_BYTES || (kind == 'C' && count != 0)) return;
            ClipboardManager manager = (ClipboardManager)
                    context.getSystemService(Context.CLIPBOARD_SERVICE);
            if (manager == null) return;
            if (kind == 'C') {
                manager.clearPrimaryClip();
                return;
            }
            String text = Charset.forName("UTF-8").newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes, offset + 2, count)).toString();
            manager.setPrimaryClip(ClipData.newPlainText(ClipboardImeService.HOST_LABEL, text));
        } catch (CharacterCodingException ignored) {
            // Reject malformed UTF-8 without exposing payload bytes in logs.
        } catch (SecurityException ignored) {
            // The bridge never changes Android's clipboard authorization policy.
        } catch (Exception ignored) {
            // Clipboard payloads are intentionally never logged.
        }
    }

    private static byte[] readBounded(File file) {
        try {
            FileInputStream input = new FileInputStream(file);
            try {
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                byte[] buffer = new byte[4096];
                int count;
                while ((count = input.read(buffer)) >= 0) {
                    if (output.size() + count > MAX_TEXT_BYTES + 11) return null;
                    output.write(buffer, 0, count);
                }
                return output.toByteArray();
            } finally { input.close(); }
        } catch (Exception ignored) { return null; }
    }

    private static boolean startsWith(byte[] value, byte[] prefix) {
        if (value.length < prefix.length) return false;
        for (int i = 0; i < prefix.length; i++) if (value[i] != prefix[i]) return false;
        return true;
    }
}

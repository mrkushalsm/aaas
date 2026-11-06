package org.aaas.storagescan;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;
import android.util.Base64;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** One-shot, permission-protected PackageManager catalog export. */
public final class CatalogReceiver extends BroadcastReceiver {
    public static final String ACTION = "org.aaas.storagescan.CATALOG";
    private static final String TAG = "AaaasAppCatalog";
    private static final int ICON_SIZE = 96;
    private static final int MAX_ACTIVITIES = 512;

    @Override
    public void onReceive(Context context, Intent intent) {
        String requestId = intent.getStringExtra("requestId");
        if (!isRequestId(requestId)) {
            Log.e(TAG, "AAAS_CATALOG_REJECTED invalid_request");
            return;
        }
        FileOutputStream stream = null;
        try {
            PackageManager manager = context.getPackageManager();
            Intent query = new Intent(Intent.ACTION_MAIN);
            query.addCategory(Intent.CATEGORY_LAUNCHER);
            List<ResolveInfo> resolved = manager.queryIntentActivities(query, 0);
            StringBuilder catalog = new StringBuilder();
            catalog.append("AAAS-CATALOG\t1\t").append(requestId).append('\t')
                    .append(resolved.size() > MAX_ACTIVITIES ? "1" : "0").append('\n');
            Set<String> packages = new HashSet<String>();
            int count = 0;
            int limit = Math.min(resolved.size(), MAX_ACTIVITIES);
            for (int index = 0; index < limit; index++) {
                ResolveInfo item = resolved.get(index);
                ActivityInfo activity = item.activityInfo;
                if (activity == null || activity.packageName == null || activity.name == null
                        || !activity.enabled || activity.applicationInfo == null
                        || !activity.applicationInfo.enabled
                        || packages.contains(activity.packageName)) {
                    continue;
                }
                CharSequence loadedLabel = activity.loadLabel(manager);
                if (loadedLabel == null || activity.name.equals(loadedLabel.toString())) {
                    loadedLabel = activity.applicationInfo.loadLabel(manager);
                }
                String label = loadedLabel == null ? activity.packageName
                        : loadedLabel.toString().replace('\n', ' ').replace('\r', ' ');
                if (label.length() == 0) {
                    label = activity.packageName;
                }
                PackageInfo packageInfo = manager.getPackageInfo(activity.packageName, 0);
                String icon = "";
                try {
                    icon = renderIcon(item.loadIcon(manager));
                } catch (Exception iconError) {
                    Log.e(TAG, "AAAS_CATALOG_ICON_FALLBACK package="
                            + activity.packageName, iconError);
                }
                catalog.append(encode(activity.packageName)).append('\t')
                        .append(encode(activity.name)).append('\t')
                        .append(encode(label)).append('\t')
                        .append(packageInfo.versionCode).append('\t')
                        .append(encode(packageInfo.versionName == null
                                ? "" : packageInfo.versionName)).append('\t')
                        .append("1\t").append(icon)
                        .append('\n');
                packages.add(activity.packageName);
                count++;
            }

            // The host pre-creates a one-shot file with a random request name and
            // write permission. The receiver derives the only permitted path.
            stream = new FileOutputStream("/dev/aaas/catalog-" + requestId + ".tsv", false);
            OutputStreamWriter writer = new OutputStreamWriter(stream, "UTF-8");
            writer.write(catalog.toString());
            writer.flush();
            writer.close();
            stream = null;
            Log.i(TAG, "AAAS_CATALOG_COMPLETE id=" + requestId
                    + " applications=" + count);
        } catch (Exception error) {
            if (stream != null) {
                try {
                    stream.close();
                } catch (Exception ignored) {
                }
            }
            Log.e(TAG, "AAAS_CATALOG_FAILED id=" + requestId, error);
        }
    }

    private static String encode(String value) throws Exception {
        return Base64.encodeToString(value.getBytes("UTF-8"), Base64.NO_WRAP);
    }

    private static boolean isRequestId(String value) {
        if (value == null || value.length() != 32) {
            return false;
        }
        for (int index = 0; index < value.length(); index++) {
            char ch = value.charAt(index);
            if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) {
                return false;
            }
        }
        return true;
    }

    private static String renderIcon(Drawable drawable) throws Exception {
        if (drawable == null) {
            return "";
        }
        Bitmap bitmap = Bitmap.createBitmap(ICON_SIZE, ICON_SIZE, Bitmap.Config.ARGB_8888);
        try {
            Canvas canvas = new Canvas(bitmap);
            drawable.setBounds(0, 0, ICON_SIZE, ICON_SIZE);
            drawable.draw(canvas);
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, output);
            return Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP);
        } finally {
            bitmap.recycle();
        }
    }
}

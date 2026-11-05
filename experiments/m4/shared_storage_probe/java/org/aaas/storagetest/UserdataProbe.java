package org.aaas.storagetest;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Process;
import android.system.Os;
import android.system.StructStat;
import android.util.Base64;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

/** Runs bounded, ordinary-app userdata checks when the controlled probe launches. */
public final class UserdataProbe {
    private static final String TAG = "AaasUserdataProbe";
    private static final String PRIVATE_CONTENT = "aaas-private-persistence-v1\n";
    private static final String PERMISSION_TEST_IMAGE = "aaas-permission-probe.png";
    private static final boolean REQUEST_MEDIA_PERMISSION = false;
    private static final boolean RELEASE_PERSISTED_GRANTS = false;
    private static final String ISOLATION_TARGET_PACKAGE = "";

    private UserdataProbe() {}

    public static void run(Context context) {
        try {
            PackageInfo packageInfo = context.getPackageManager().getPackageInfo(
                    context.getPackageName(), 0);
            Log.i(TAG, "PACKAGE=" + context.getPackageName()
                    + " version=" + packageInfo.versionCode
                    + " uid=" + Process.myUid());
            record("PACKAGE=" + context.getPackageName() + " version="
                    + packageInfo.versionCode + " uid=" + Process.myUid());
            recordMediaPermissionState(context, "activity_start");
            queryPermissionTestImage(context, "activity_start");

            File dataDir = context.getDataDir();
            File filesDir = context.getFilesDir();
            File cacheDir = context.getCacheDir();
            File database = context.getDatabasePath("aaas-lifecycle.db");
            File external = context.getExternalFilesDir(null);
            logPath("context.dataDir", dataDir);
            logPath("context.filesDir", filesDir);
            logPath("context.cacheDir", cacheDir);
            logPath("context.database", database);
            logPath("context.externalFilesDir", external);
            logPath("/data/data/package", new File("/data/data/"
                    + context.getPackageName()));
            logPath("/data/user/0/package", new File("/data/user/0/"
                    + context.getPackageName()));
            logMountInfo();
            logExternalStorageState(context, "activity_start");
            scheduleExternalStorageChecks(context);

            verifyAndWrite(new File(filesDir, "aaas-persistence.txt"),
                    PRIVATE_CONTENT, "internalFile");
            verifyAndWrite(new File(cacheDir, "aaas-cache.txt"),
                    "aaas-cache-v1\n", "cacheFile");
            verifyExternalFiles(context, "activity_start");

            Context deviceProtected = context.createDeviceProtectedStorageContext();
            logPath("deviceProtected.dataDir", deviceProtected.getDataDir());
            verifyAndWrite(new File(deviceProtected.getFilesDir(),
                    "aaas-device-protected.txt"), "aaas-device-protected-v1\n",
                    "deviceProtectedFile");

            verifyDatabase(context, packageInfo.versionCode);
            logStorageStats(context, packageInfo.packageName);
            if (!ISOLATION_TARGET_PACKAGE.isEmpty()) {
                probeOtherPackagePrivateData(ISOLATION_TARGET_PACKAGE);
            }
            if (RELEASE_PERSISTED_GRANTS) {
                releasePersistedGrants(context);
            }
            if (REQUEST_MEDIA_PERMISSION) {
                requestReadMediaImages(context);
            }
        } catch (Throwable error) {
            Log.e(TAG, "USERDATA_PROBE_FAILED", error);
        }
    }

    private static void scheduleExternalStorageChecks(final Context context) {
        try {
            Class<?> looperClass = Class.forName("android.os.Looper");
            Object looper = looperClass.getMethod("getMainLooper").invoke(null);
            Class<?> handlerClass = Class.forName("android.os.Handler");
            Object handler = handlerClass.getConstructor(looperClass).newInstance(looper);
            Method postDelayed = handlerClass.getMethod("postDelayed", Runnable.class, long.class);
            for (final long delay : new long[]{3000L, 15000L}) {
                postDelayed.invoke(handler, new Runnable() {
                    @Override public void run() {
                        String checkpoint = "after_" + delay + "ms";
                        logExternalStorageState(context, checkpoint);
                        verifyExternalFiles(context, checkpoint);
                    }
                }, delay);
            }
        } catch (Throwable error) {
            Log.e(TAG, "EXTERNAL_STORAGE_CHECK_SCHEDULING_FAILED", error);
        }
    }

    private static void logExternalStorageState(Context context, String checkpoint) {
        try {
            Class<?> environment = Class.forName("android.os.Environment");
            String state = (String) environment.getMethod("getExternalStorageState")
                    .invoke(null);
            record("EXTERNAL_STATE checkpoint=" + checkpoint + " state=" + state);
        } catch (Throwable error) {
            record("EXTERNAL_STATE checkpoint=" + checkpoint + " error="
                    + error.getClass().getSimpleName() + ":" + error.getMessage());
        }
        try {
            Method getDirs = context.getClass().getMethod("getExternalFilesDirs", String.class);
            File[] directories = (File[]) getDirs.invoke(context, new Object[]{null});
            record("EXTERNAL_FILES_DIRS checkpoint=" + checkpoint + " count="
                    + (directories == null ? -1 : directories.length));
            if (directories != null) {
                for (int index = 0; index < directories.length; index++) {
                    logPath("externalFilesDirs[" + index + "]", directories[index]);
                }
            }
        } catch (Throwable error) {
            record("EXTERNAL_FILES_DIRS checkpoint=" + checkpoint + " error="
                    + error.getClass().getSimpleName() + ":" + error.getMessage());
        }
        try {
            Object manager = context.getClass().getMethod("getSystemService", String.class)
                    .invoke(context, "storage");
            Object volumes = manager.getClass().getMethod("getStorageVolumes").invoke(manager);
            for (Object volume : (Iterable<?>) volumes) {
                String state = String.valueOf(volume.getClass().getMethod("getState")
                        .invoke(volume));
                boolean primary = (Boolean) volume.getClass().getMethod("isPrimary")
                        .invoke(volume);
                boolean emulated = (Boolean) volume.getClass().getMethod("isEmulated")
                        .invoke(volume);
                Object directory = volume.getClass().getMethod("getDirectory").invoke(volume);
                record("STORAGE_VOLUME checkpoint=" + checkpoint + " state=" + state
                        + " primary=" + primary + " emulated=" + emulated
                        + " directory=" + directory);
            }
        } catch (Throwable error) {
            Throwable cause = error instanceof InvocationTargetException
                    ? ((InvocationTargetException) error).getCause() : error;
            record("STORAGE_VOLUMES checkpoint=" + checkpoint + " error="
                    + cause.getClass().getSimpleName() + ":" + cause.getMessage());
        }
    }

    private static void verifyExternalFiles(Context context, String checkpoint) {
        try {
            File external = context.getExternalFilesDir(null);
            if (external == null) {
                record("EXTERNAL_FILES_RESULT checkpoint=" + checkpoint + " path=null");
                return;
            }
            logPath("externalFilesDir." + checkpoint, external);
            verifyAndWrite(new File(external, "aaas-external.txt"),
                    "aaas-app-external-v1\n", "externalFile." + checkpoint);
            record("EXTERNAL_FILES_RESULT checkpoint=" + checkpoint + " writable=true");
        } catch (Throwable error) {
            record("EXTERNAL_FILES_RESULT checkpoint=" + checkpoint + " error="
                    + error.getClass().getSimpleName() + ":" + error.getMessage());
        }
    }

    private static synchronized void record(String line) {
        Log.i(TAG, line);
    }

    private static void logStorageStats(Context context, String packageName) {
        try {
            Class<?> statFsClass = Class.forName("android.os.StatFs");
            Object statFs = statFsClass.getConstructor(String.class)
                    .newInstance("/storage/emulated/0");
            long available = (Long) statFsClass.getMethod("getAvailableBytes").invoke(statFs);
            long total = (Long) statFsClass.getMethod("getTotalBytes").invoke(statFs);
            Log.i(TAG, "STATFS_SHARED total=" + total + " available=" + available);
        } catch (Throwable error) {
            Log.e(TAG, "STATFS_SHARED_FAILED", error);
        }
        try {
            Object statsManager = context.getClass()
                    .getMethod("getSystemService", String.class)
                    .invoke(context, "storagestats");
            Class<?> storageManagerClass = Class.forName("android.os.storage.StorageManager");
            Object storageManager = context.getClass()
                    .getMethod("getSystemService", String.class)
                    .invoke(context, "storage");
            Object uuid = storageManagerClass.getMethod("getUuidForPath", File.class)
                    .invoke(storageManager, context.getDataDir());
            Class<?> userHandleClass = Class.forName("android.os.UserHandle");
            Object user = userHandleClass.getMethod("getUserHandleForUid", int.class)
                    .invoke(null, Process.myUid());
            Class<?> statsManagerClass = Class.forName("android.app.usage.StorageStatsManager");
            Object packageStats = statsManagerClass.getMethod("queryStatsForPackage",
                    Class.forName("java.util.UUID"), String.class, userHandleClass)
                    .invoke(statsManager, uuid, packageName, user);
            Class<?> statsClass = Class.forName("android.app.usage.StorageStats");
            long app = (Long) statsClass.getMethod("getAppBytes").invoke(packageStats);
            long data = (Long) statsClass.getMethod("getDataBytes").invoke(packageStats);
            long cache = (Long) statsClass.getMethod("getCacheBytes").invoke(packageStats);
            record("STORAGE_STATS_PACKAGE app=" + app + " data=" + data
                    + " cache=" + cache + " uuid=" + uuid);
        } catch (Throwable error) {
            Throwable cause = error instanceof InvocationTargetException
                    ? ((InvocationTargetException) error).getCause() : error;
            Log.i(TAG, "STORAGE_STATS_PACKAGE_UNAVAILABLE="
                    + cause.getClass().getSimpleName() + ":" + cause.getMessage());
        }
    }

    private static void requestReadMediaImages(Context context) {
        try {
            Method check = context.getClass().getMethod("checkSelfPermission", String.class);
            int state = (Integer) check.invoke(context,
                    "android.permission.READ_MEDIA_IMAGES");
            record("RUNTIME_PERMISSION_READ_MEDIA_IMAGES="
                    + (state == 0 ? "GRANTED" : "DENIED"));
            if (state != 0) {
                Method request = context.getClass().getMethod(
                        "requestPermissions", String[].class, int.class);
                request.invoke(context, new String[]{"android.permission.READ_MEDIA_IMAGES"},
                        0x33);
            }
        } catch (Throwable error) {
            Log.e(TAG, "RUNTIME_PERMISSION_REQUEST_FAILED", error);
        }
    }

    public static void reportMediaPermissionResult(Context context, int[] grantResults) {
        String result = grantResults != null && grantResults.length > 0
                && grantResults[0] == 0 ? "GRANTED" : "DENIED";
        try {
            int state = (Integer) context.getClass()
                    .getMethod("checkSelfPermission", String.class)
                    .invoke(context, "android.permission.READ_MEDIA_IMAGES");
            result = state == 0 ? "GRANTED" : "DENIED";
        } catch (Throwable error) {
            record("RUNTIME_PERMISSION_STATE_QUERY_FAILED="
                    + error.getClass().getSimpleName() + ":" + error.getMessage());
        }
        record("RUNTIME_PERMISSION_CALLBACK_READ_MEDIA_IMAGES=" + result);
        queryPermissionTestImage(context, "permission_callback");
    }

    private static void recordMediaPermissionState(Context context, String checkpoint) {
        try {
            int state = (Integer) context.getClass()
                    .getMethod("checkSelfPermission", String.class)
                    .invoke(context, "android.permission.READ_MEDIA_IMAGES");
            record("RUNTIME_PERMISSION_READ_MEDIA_IMAGES checkpoint=" + checkpoint + " state="
                    + (state == 0 ? "GRANTED" : "DENIED"));
        } catch (Throwable error) {
            record("RUNTIME_PERMISSION_STATE_QUERY_FAILED checkpoint=" + checkpoint + " error="
                    + error.getClass().getSimpleName() + ":" + error.getMessage());
        }
    }

    private static void queryPermissionTestImage(Context context, String checkpoint) {
        try {
            Object resolver = context.getClass().getMethod("getContentResolver").invoke(context);
            Class<?> uriClass = Class.forName("android.net.Uri");
            Object uri = uriClass.getMethod("parse", String.class).invoke(null,
                    "content://media/external_primary/images/media");
            String[] projection = {"_id", "_display_name"};
            String[] args = {PERMISSION_TEST_IMAGE};
            Object cursor = resolver.getClass().getMethod("query", uriClass, String[].class,
                    String.class, String[].class, String.class).invoke(resolver, uri,
                    projection, "_display_name=?", args, null);
            if (cursor == null) {
                record("MEDIA_IMAGE_QUERY checkpoint=" + checkpoint + " cursor=null");
                return;
            }
            int count = (Integer) cursor.getClass().getMethod("getCount").invoke(cursor);
            cursor.getClass().getMethod("close").invoke(cursor);
            record("MEDIA_IMAGE_QUERY checkpoint=" + checkpoint + " fixture="
                    + PERMISSION_TEST_IMAGE + " rows=" + count);
        } catch (Throwable error) {
            Throwable cause = error instanceof InvocationTargetException
                    ? ((InvocationTargetException) error).getCause() : error;
            record("MEDIA_IMAGE_QUERY checkpoint=" + checkpoint + " error="
                    + cause.getClass().getSimpleName() + ":" + cause.getMessage());
        }
    }

    private static void releasePersistedGrants(Context context) {
        try {
            Object resolver = Context.class.getMethod("getContentResolver").invoke(context);
            Method listMethod = resolver.getClass().getMethod("getPersistedUriPermissions");
            Iterable<?> grants = (Iterable<?>) listMethod.invoke(resolver);
            Class<?> uriClass = Class.forName("android.net.Uri");
            Method release = resolver.getClass().getMethod(
                    "releasePersistableUriPermission", uriClass, int.class);
            Method parse = uriClass.getMethod("parse", String.class);
            File uriRecord = new File(context.getFilesDir(), "aaas-saf-revocation-uri.txt");
            String recordedUri = readRecordedUri(uriRecord);
            int count = 0;
            for (Object grant : grants) {
                Object uri = grant.getClass().getMethod("getUri").invoke(grant);
                count++;
                if (recordedUri != null) {
                    continue;
                }
                boolean read = (Boolean) grant.getClass().getMethod("isReadPermission")
                        .invoke(grant);
                boolean write = (Boolean) grant.getClass().getMethod("isWritePermission")
                        .invoke(grant);
                int flags = (read ? 1 : 0) | (write ? 2 : 0);
                recordedUri = String.valueOf(uri);
                try (FileOutputStream output = new FileOutputStream(uriRecord)) {
                    output.write(recordedUri.getBytes(StandardCharsets.UTF_8));
                }
                release.invoke(resolver, uri, flags);
                Log.i(TAG, "PERSISTED_GRANT_RELEASED uri=" + recordedUri + " flags=" + flags);
                attemptRevokedUriRead(resolver, uriClass, parse, recordedUri,
                        "PERSISTED_GRANT_READ_AFTER_RELEASE");
                break;
            }
            if (recordedUri != null && count > 0) {
                attemptRevokedUriRead(resolver, uriClass, parse, recordedUri,
                        "PERSISTED_GRANT_READ_AFTER_RELEASE_RECHECK");
            } else if (recordedUri != null) {
                attemptRevokedUriRead(resolver, uriClass, parse, recordedUri,
                        "PERSISTED_GRANT_READ_AFTER_RUNTIME_RESTART");
            }
            Log.i(TAG, "PERSISTED_GRANT_COUNT=" + count);
        } catch (Throwable error) {
            Log.e(TAG, "PERSISTED_GRANT_RELEASE_FAILED", error);
        }
    }

    private static String readRecordedUri(File uriRecord) throws Exception {
        if (!uriRecord.isFile()) {
            return null;
        }
        byte[] bytes;
        try (FileInputStream input = new FileInputStream(uriRecord)) {
            bytes = new byte[(int) uriRecord.length()];
            int read = input.read(bytes);
            if (read != bytes.length) {
                throw new IllegalStateException("short read from persisted URI record");
            }
        }
        return new String(bytes, StandardCharsets.UTF_8);
    }

    private static void attemptRevokedUriRead(Object resolver, Class<?> uriClass,
            Method parse, String uriText, String label) {
        try {
            Object parsed = parse.invoke(null, uriText);
            Object stream = resolver.getClass().getMethod("openInputStream", uriClass)
                    .invoke(resolver, parsed);
            if (stream instanceof java.io.Closeable) {
                ((java.io.Closeable) stream).close();
            }
            Log.e(TAG, label + "_UNEXPECTED uri=" + uriText);
        } catch (InvocationTargetException denied) {
            Throwable cause = denied.getCause();
            Log.i(TAG, label + "_DENIED=" + cause.getClass().getSimpleName()
                    + " uri=" + uriText);
        } catch (Throwable error) {
            Log.e(TAG, label + "_FAILED", error);
        }
    }

    private static void probeOtherPackagePrivateData(String packageName) {
        String[] paths = {
                "/data/user/0/" + packageName + "/files/aaas-persistence.txt",
                "/data/data/" + packageName + "/files/aaas-persistence.txt",
                "/data/user/0/" + packageName + "/databases/aaas-lifecycle.db",
                "/data/user_de/0/" + packageName + "/files/aaas-device-protected.txt"
        };
        for (String path : paths) {
            try (FileInputStream input = new FileInputStream(path)) {
                int value = input.read();
                Log.e(TAG, "CROSS_APP_PRIVATE_READ_UNEXPECTED path=" + path
                        + " firstByte=" + value);
            } catch (Throwable error) {
                Log.i(TAG, "CROSS_APP_PRIVATE_READ_DENIED path=" + path
                        + " error=" + error.getClass().getSimpleName()
                        + " message=" + error.getMessage());
            }
        }
    }

    private static void logPath(String label, File file) {
        if (file == null) {
            Log.i(TAG, label + "=null");
            return;
        }
        StringBuilder line = new StringBuilder(label)
                .append(" path=").append(file.getAbsolutePath());
        try {
            line.append(" canonical=").append(file.getCanonicalPath());
        } catch (Exception error) {
            line.append(" canonicalError=").append(error.getClass().getSimpleName());
        }
        try {
            StructStat stat = Os.stat(file.getAbsolutePath());
            line.append(" dev=").append(stat.st_dev)
                    .append(" ino=").append(stat.st_ino)
                    .append(" uid=").append(stat.st_uid)
                    .append(" gid=").append(stat.st_gid)
                    .append(" mode=").append(String.format(Locale.ROOT, "%o", stat.st_mode));
        } catch (Exception error) {
            line.append(" statError=").append(error.getClass().getSimpleName());
        }
        record(line.toString());
    }

    private static void logMountInfo() {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                new FileInputStream("/proc/self/mountinfo"), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.contains("/data") && (line.contains("/data/user")
                        || line.contains("/data/data") || line.contains("/data "))) {
                    Log.i(TAG, "MOUNTINFO " + line);
                }
            }
        } catch (Exception error) {
            Log.e(TAG, "MOUNTINFO_READ_FAILED", error);
        }
    }

    private static void verifyAndWrite(File file, String expected, String label)
            throws Exception {
        File parent = file.getParentFile();
        if (!parent.exists() && !parent.mkdirs()) {
            throw new IllegalStateException("cannot create " + parent);
        }
        boolean existed = file.isFile();
        if (existed) {
            byte[] prior;
            try (FileInputStream input = new FileInputStream(file)) {
                prior = new byte[(int) file.length()];
                int count = input.read(prior);
                if (count != prior.length) {
                    throw new IllegalStateException("short read " + label);
                }
            }
            boolean match = expected.equals(new String(prior, StandardCharsets.UTF_8));
            record(label + (match ? "_PERSISTED_MATCH" : "_PERSISTED_MISMATCH")
                    + " sha256=" + digest(prior));
            if (!match) {
                throw new IllegalStateException("unexpected prior contents " + label);
            }
        }
        byte[] bytes = expected.getBytes(StandardCharsets.UTF_8);
        try (FileOutputStream output = new FileOutputStream(file, false)) {
            output.write(bytes);
            output.getFD().sync();
        }
        record(label + (existed ? "_WRITE_OK" : "_CREATED")
                + " sha256=" + digest(bytes));
    }

    private static void verifyDatabase(Context context, int versionCode) {
        SQLiteDatabase database = null;
        boolean transaction = false;
        try {
            database = context.openOrCreateDatabase("aaas-lifecycle.db",
                    Context.MODE_PRIVATE, null);
            boolean wal = database.enableWriteAheadLogging();
            database.execSQL("CREATE TABLE IF NOT EXISTS records ("
                    + "id INTEGER PRIMARY KEY, value TEXT NOT NULL)");
            if (database.getVersion() == 0) {
                database.setVersion(1);
            }
            database.beginTransaction();
            transaction = true;
            for (int index = 1; index <= 100; index++) {
                database.execSQL("INSERT OR IGNORE INTO records(id,value) VALUES ("
                        + index + ",'record-" + index + "')");
            }
            int versionRecord = 1000 + versionCode;
            database.execSQL("INSERT OR IGNORE INTO records(id,value) VALUES ("
                    + versionRecord + ",'package-version-" + versionCode + "')");
            database.setTransactionSuccessful();
            database.endTransaction();
            transaction = false;

            int count = 0;
            StringBuilder canonical = new StringBuilder();
            try (Cursor rows = database.rawQuery(
                    "SELECT id,value FROM records ORDER BY id", null)) {
                while (rows.moveToNext()) {
                    count++;
                    canonical.append(rows.getInt(0)).append(':')
                            .append(rows.getString(1)).append('\n');
                }
            }
            String integrity;
            try (Cursor result = database.rawQuery("PRAGMA integrity_check", null)) {
                integrity = result.moveToFirst() ? result.getString(0) : "no_result";
            }
            int schemaVersion = database.getVersion();
            String digest = digest(canonical.toString().getBytes(StandardCharsets.UTF_8));
            File walFile = new File(database.getPath() + "-wal");
            Log.i(TAG, "DATABASE_OK rows=" + count + " schema=" + schemaVersion
                    + " version=" + versionCode + " walEnabled="
                    + database.isWriteAheadLoggingEnabled() + " walEnableResult=" + wal
                    + " walBytes=" + (walFile.isFile() ? walFile.length() : 0)
                    + " integrity=" + integrity + " rowsSha256=" + digest);
            if (count < 101 || schemaVersion != 1 || !"ok".equals(integrity)) {
                throw new IllegalStateException("database state validation failed");
            }
            if (wal) {
                try (Cursor checkpoint = database.rawQuery(
                        "PRAGMA wal_checkpoint(PASSIVE)", null)) {
                    if (checkpoint.moveToFirst()) {
                        Log.i(TAG, "DATABASE_WAL_CHECKPOINT busy=" + checkpoint.getInt(0)
                                + " log=" + checkpoint.getInt(1)
                                + " checkpointed=" + checkpoint.getInt(2));
                    }
                }
            }
        } catch (Throwable error) {
            Log.e(TAG, "DATABASE_FAILED", error);
        } finally {
            if (transaction && database != null) {
                try {
                    database.endTransaction();
                } catch (Throwable ignored) {
                    Log.e(TAG, "DATABASE_END_TRANSACTION_FAILED", ignored);
                }
            }
            if (database != null) {
                database.close();
            }
        }
    }

    private static String digest(byte[] bytes) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(bytes);
        return Base64.encodeToString(hash, Base64.NO_WRAP);
    }
}

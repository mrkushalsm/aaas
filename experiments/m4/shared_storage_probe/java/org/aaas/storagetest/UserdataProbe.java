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

/** Runs bounded, ordinary-app userdata checks when the controlled probe launches. */
public final class UserdataProbe {
    private static final String TAG = "AaasUserdataProbe";
    private static final String PRIVATE_CONTENT = "aaas-private-persistence-v1\n";

    private UserdataProbe() {}

    public static void run(Context context) {
        try {
            PackageInfo packageInfo = context.getPackageManager().getPackageInfo(
                    context.getPackageName(), 0);
            Log.i(TAG, "PACKAGE=" + context.getPackageName()
                    + " version=" + packageInfo.versionCode
                    + " uid=" + Process.myUid());

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

            verifyAndWrite(new File(filesDir, "aaas-persistence.txt"),
                    PRIVATE_CONTENT, "internalFile");
            verifyAndWrite(new File(cacheDir, "aaas-cache.txt"),
                    "aaas-cache-v1\n", "cacheFile");
            if (external != null) {
                verifyAndWrite(new File(external, "aaas-external.txt"),
                        "aaas-app-external-v1\n", "externalFile");
            } else {
                Log.i(TAG, "externalFilesDir=null");
            }

            Context deviceProtected = context.createDeviceProtectedStorageContext();
            logPath("deviceProtected.dataDir", deviceProtected.getDataDir());
            verifyAndWrite(new File(deviceProtected.getFilesDir(),
                    "aaas-device-protected.txt"), "aaas-device-protected-v1\n",
                    "deviceProtectedFile");

            verifyDatabase(context, packageInfo.versionCode);
        } catch (Throwable error) {
            Log.e(TAG, "USERDATA_PROBE_FAILED", error);
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
        Log.i(TAG, line.toString());
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
            Log.i(TAG, label + (match ? "_PERSISTED_MATCH" : "_PERSISTED_MISMATCH")
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
        Log.i(TAG, label + (existed ? "_WRITE_OK" : "_CREATED")
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

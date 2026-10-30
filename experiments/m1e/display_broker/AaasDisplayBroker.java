package com.aaas.display;

import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;

/** Narrow system-UID broker for up to two trusted, own-content AaaS displays. */
public final class AaasDisplayBroker {
    private static FileOutputStream diagnosticLog;

    private static final class ImageDrain implements InvocationHandler {
        public Object invoke(Object proxy, Method method, Object[] methodArgs) throws Throwable {
            if ("onImageAvailable".equals(method.getName())) {
                Object source = methodArgs[0];
                Object image = call(source, "acquireLatestImage", new Class<?>[0]);
                if (image != null) call(image, "close", new Class<?>[0]);
            }
            return null;
        }
    }

    private static final class DisplayHandle {
        Object reader;
        Object surface;
        Object listener;
        Object virtualDisplay;
        Object handler;
        Class<?> listenerClass;
        int index;
        int displayId;
        int width;
        int height;
        int density;
        long resizeGeneration;
        boolean released;
        String uniqueId;
        String idPath;
    }

    private static void log(String message) {
        System.out.println("AAAS_DISPLAY_BROKER " + message);
        System.out.flush();
        if (diagnosticLog != null) {
            try {
                diagnosticLog.write((message + "\n").getBytes("UTF-8"));
                diagnosticLog.flush();
            } catch (Throwable ignored) {
                // Diagnostic output is best-effort and contains no app data.
            }
        }
        try {
            Class<?> androidLog = Class.forName("android.util.Log");
            androidLog.getMethod("i", String.class, String.class)
                    .invoke(null, "AaaSDisplayBroker", message);
        } catch (Throwable ignored) {
            // stdout remains available in init's service output if logd is unavailable.
        }
    }

    private static Object call(Object target, String name, Class<?>[] types, Object... args)
            throws Exception {
        return target.getClass().getMethod(name, types).invoke(target, args);
    }

    private static DisplayHandle createDisplay(Object context, Object displayManager,
            Object handler, Class<?> looperClass, int index, int width, int height, int density,
            String idPath) throws Exception {
        DisplayHandle handle = new DisplayHandle();
        handle.index = index;
        handle.handler = handler;
        handle.idPath = idPath;
        handle.width = width;
        handle.height = height;
        handle.density = density;
        createReader(handle, width, height);
        Object surface = handle.surface;

        Class<?> displayManagerClass = Class.forName("android.hardware.display.DisplayManager");
        int trusted = displayManagerClass.getField("VIRTUAL_DISPLAY_FLAG_TRUSTED").getInt(null);
        int ownContent = displayManagerClass.getField("VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY").getInt(null);
        Class<?> configClass = Class.forName("android.hardware.display.VirtualDisplayConfig");
        Class<?> builderClass = Class.forName("android.hardware.display.VirtualDisplayConfig$Builder");
        Constructor<?> builderCtor = builderClass.getConstructor(String.class, int.class,
                int.class, int.class);
        Object builder = builderCtor.newInstance("AaaS application output " + (index + 1),
                width, height, density);
        call(builder, "setFlags", new Class<?>[] {int.class}, trusted | ownContent);
        call(builder, "setSurface", new Class<?>[] {Class.forName("android.view.Surface")}, surface);
        call(builder, "setHomeSupported", new Class<?>[] {boolean.class}, false);
        Object config = call(builder, "build", new Class<?>[0]);
        int configuredFlags = (Integer) call(config, "getFlags", new Class<?>[0]);
        log("stage=create_virtual_display index=" + index + " flags=" + configuredFlags);
        try {
            handle.virtualDisplay = displayManagerClass.getMethod("createVirtualDisplay", configClass)
                    .invoke(displayManager, config);
        } catch (Exception error) {
            try { call(handle.reader, "close", new Class<?>[0]); } catch (Exception ignored) { }
            throw error;
        }
        if (handle.virtualDisplay == null) {
            call(handle.reader, "close", new Class<?>[0]);
            throw new IllegalStateException("DisplayManager returned null for output " + index);
        }
        Object display = call(handle.virtualDisplay, "getDisplay", new Class<?>[0]);
        handle.displayId = (Integer) call(display, "getDisplayId", new Class<?>[0]);
        handle.uniqueId = (String) call(display, "getUniqueId", new Class<?>[0]);
        log("created index=" + index + " displayId=" + handle.displayId + " uniqueId="
                + handle.uniqueId + " size=" + width + "x" + height + " density=" + density
                + " flags=" + configuredFlags + " home=false");
        try (FileOutputStream output = new FileOutputStream(idPath, false)) {
            output.write((Integer.toString(handle.displayId) + "\n").getBytes("US-ASCII"));
            output.flush();
        }
        Thread.sleep(1500);
        String canHostTasks;
        try {
            canHostTasks = String.valueOf(call(display, "canHostTasks", new Class<?>[0]));
        } catch (ReflectiveOperationException unavailable) {
            canHostTasks = "unavailable:" + unavailable.getClass().getSimpleName();
        }
        log("display_state index=" + index + " displayId=" + handle.displayId
                + " flags=" + call(display, "getFlags", new Class<?>[0])
                + " canHostTasks=" + canHostTasks);
        return handle;
    }

    private static void createReader(DisplayHandle handle, int width, int height)
            throws Exception {
        Class<?> imageReaderClass = Class.forName("android.media.ImageReader");
        Object reader = imageReaderClass.getMethod("newInstance", int.class, int.class,
                int.class, int.class).invoke(null, width, height, 1, 3);
        Class<?> listenerClass = Class.forName(
                "android.media.ImageReader$OnImageAvailableListener");
        Object listener = Proxy.newProxyInstance(listenerClass.getClassLoader(),
                new Class<?>[] {listenerClass}, new ImageDrain());
        imageReaderClass.getMethod("setOnImageAvailableListener", listenerClass,
                Class.forName("android.os.Handler")).invoke(reader, listener, handle.handler);
        handle.reader = reader;
        handle.listenerClass = listenerClass;
        handle.listener = listener;
        handle.surface = call(reader, "getSurface", new Class<?>[0]);
    }

    private static void resizeDisplay(DisplayHandle handle, int width, int height,
            long generation) throws Exception {
        if (handle.released || width < 64 || height < 64 || width > 4096 || height > 4096) {
            throw new IllegalArgumentException("invalid resize request");
        }
        Object oldReader = handle.reader;
        Object oldSurface = handle.surface;
        Object oldListener = handle.listener;
        Class<?> oldListenerClass = handle.listenerClass;
        int oldWidth = handle.width;
        int oldHeight = handle.height;
        createReader(handle, width, height);
        try {
            call(handle.virtualDisplay, "setSurface",
                    new Class<?>[] {Class.forName("android.view.Surface")}, handle.surface);
            call(handle.virtualDisplay, "resize",
                    new Class<?>[] {int.class, int.class, int.class},
                    width, height, handle.density);
        } catch (Exception error) {
            try {
                call(handle.virtualDisplay, "setSurface",
                        new Class<?>[] {Class.forName("android.view.Surface")}, oldSurface);
                call(handle.virtualDisplay, "resize",
                        new Class<?>[] {int.class, int.class, int.class},
                        oldWidth, oldHeight, handle.density);
            } catch (Exception rollbackError) {
                log("resize_rollback_failed index=" + handle.index + " displayId="
                        + handle.displayId + " error="
                        + rollbackError.getClass().getSimpleName());
            }
            try {
                call(handle.reader, "setOnImageAvailableListener",
                        new Class<?>[] {handle.listenerClass,
                                Class.forName("android.os.Handler")}, null, null);
                call(handle.reader, "close", new Class<?>[0]);
                call(handle.surface, "release", new Class<?>[0]);
            } catch (Exception ignored) { }
            handle.reader = oldReader;
            handle.surface = oldSurface;
            handle.listener = oldListener;
            handle.listenerClass = oldListenerClass;
            throw error;
        }
        try {
            call(oldReader, "setOnImageAvailableListener",
                    new Class<?>[] {oldListenerClass, Class.forName("android.os.Handler")},
                    null, null);
        } catch (Exception ignored) { }
        call(oldReader, "close", new Class<?>[0]);
        call(oldSurface, "release", new Class<?>[0]);
        handle.width = width;
        handle.height = height;
        handle.resizeGeneration = generation;
        log("resized index=" + handle.index + " displayId=" + handle.displayId
                + " generation=" + generation + " size=" + width + "x" + height
                + " density=" + handle.density);
        final long expectedGeneration = generation;
        Runnable reportResizedMetrics = new Runnable() {
            @Override public void run() {
                if (!handle.released && handle.resizeGeneration == expectedGeneration) {
                    logDisplayMetrics(handle, expectedGeneration);
                }
            }
        };
        try {
            handle.handler.getClass().getMethod("postDelayed", Runnable.class, long.class)
                    .invoke(handle.handler, reportResizedMetrics, 500L);
        } catch (Exception error) {
            log("display_metrics_schedule_failed index=" + handle.index + " displayId="
                    + handle.displayId + " generation=" + generation + " error="
                    + error.getClass().getSimpleName());
        }
    }

    private static void logDisplayMetrics(DisplayHandle handle, long generation) {
        try {
            Object display = call(handle.virtualDisplay, "getDisplay", new Class<?>[0]);
            Class<?> metricsClass = Class.forName("android.util.DisplayMetrics");
            Object metrics = metricsClass.getConstructor().newInstance();
            call(display, "getRealMetrics", new Class<?>[] {metricsClass}, metrics);
            log("display_metrics index=" + handle.index + " displayId=" + handle.displayId
                    + " generation=" + generation + " requested=" + handle.width + "x"
                    + handle.height
                    + " widthPixels=" + metricsClass.getField("widthPixels").getInt(metrics)
                    + " heightPixels=" + metricsClass.getField("heightPixels").getInt(metrics)
                    + " densityDpi=" + metricsClass.getField("densityDpi").getInt(metrics));
        } catch (Exception error) {
            log("display_metrics_unavailable index=" + handle.index + " displayId="
                    + handle.displayId + " error=" + error.getClass().getSimpleName());
        }
    }

    private static String readControl(String path) {
        try (FileInputStream input = new FileInputStream(path)) {
            byte[] bytes = new byte[128];
            int n = input.read(bytes);
            return n <= 0 ? "" : new String(bytes, 0, n, "US-ASCII").trim();
        } catch (Exception ignored) {
            return "";
        }
    }

    private static void writeControl(String path, String value) {
        try (FileOutputStream output = new FileOutputStream(path, false)) {
            output.write((value + "\n").getBytes("US-ASCII"));
            output.flush();
        } catch (Exception error) {
            log("control_write_failed path=" + path + " error="
                    + error.getClass().getSimpleName());
        }
    }

    private static void pollDisplayControl(DisplayHandle handle) {
        if (handle.released) return;
        String suffix = Integer.toString(handle.index + 1);
        String closePath = "/dev/aaas/vdisplay_close_" + suffix;
        String resizePath = "/dev/aaas/vdisplay_resize_" + suffix;
        String ackPath = "/dev/aaas/vdisplay_control_ack_" + suffix;
        String close = readControl(closePath);
        if (close.startsWith("close")) {
            try {
                releaseDisplay(handle);
                handle.released = true;
                writeControl(ackPath, "released " + handle.displayId);
            } catch (Exception error) {
                writeControl(ackPath, "failed " + handle.displayId);
                log("release_failed displayId=" + handle.displayId + " error="
                        + error.getClass().getSimpleName());
            }
            return;
        }
        String request = readControl(resizePath);
        if (request.isEmpty()) return;
        String[] fields = request.split("\\s+");
        try {
            if (fields.length != 3) throw new IllegalArgumentException("field_count");
            long generation = Long.parseLong(fields[0]);
            int width = Integer.parseInt(fields[1]);
            int height = Integer.parseInt(fields[2]);
            if (generation <= handle.resizeGeneration) return;
            resizeDisplay(handle, width, height, generation);
            writeControl(ackPath, "resized " + generation + " " + width + " " + height);
        } catch (Exception error) {
            writeControl(ackPath, "resize_failed " + fields[0] + " "
                    + error.getClass().getSimpleName());
            log("resize_failed index=" + handle.index + " displayId=" + handle.displayId
                    + " request=" + request.replace(' ', '_') + " error="
                    + error.getClass().getSimpleName());
        }
    }

    private static void releaseDisplay(DisplayHandle handle) throws Exception {
        if (handle.released) return;
        Exception failure = null;
        try {
            handle.reader.getClass().getMethod("setOnImageAvailableListener",
                    handle.listenerClass, Class.forName("android.os.Handler"))
                    .invoke(handle.reader, null, null);
        } catch (Exception error) { failure = error; }
        try {
            call(handle.virtualDisplay, "setSurface",
                    new Class<?>[] {Class.forName("android.view.Surface")}, new Object[] {null});
        } catch (Exception error) { if (failure == null) failure = error; }
        try {
            call(handle.virtualDisplay, "release", new Class<?>[0]);
        } catch (Exception error) { if (failure == null) failure = error; }
        try {
            call(handle.reader, "close", new Class<?>[0]);
        } catch (Exception error) { if (failure == null) failure = error; }
        try {
            call(handle.surface, "release", new Class<?>[0]);
        } catch (Exception error) { if (failure == null) failure = error; }
        try (FileOutputStream output = new FileOutputStream(handle.idPath, false)) {
            output.flush();
        } catch (Exception error) { if (failure == null) failure = error; }
        if (failure != null) throw failure;
        handle.released = true;
        log("released displayId=" + handle.displayId + " reason=host_request");
    }

    private static boolean secondDisplayEnabled(String path) {
        if (path.isEmpty()) return false;
        try (FileInputStream input = new FileInputStream(path)) {
            return input.read() == 'e';
        } catch (Exception error) {
            return false;
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 4) diagnosticLog = new FileOutputStream(args[4], true);
        log("stage=main_entry");
        int width = args.length > 0 ? Integer.parseInt(args[0]) : 720;
        int height = args.length > 1 ? Integer.parseInt(args[1]) : 1280;
        int density = args.length > 2 ? Integer.parseInt(args[2]) : 240;
        String idPath = args.length > 3 ? args[3] : "/dev/aaas/vdisplay_id";
        String shutdownPath = args.length > 5 ? args[5] : "/dev/aaas/display_broker_shutdown";
        String secondIdPath = args.length > 6 ? args[6] : "";
        boolean createSecondDisplay = secondDisplayEnabled(secondIdPath);
        if (width < 1 || height < 1 || width > 4096 || height > 4096 || density < 1 || density > 1000) {
            throw new IllegalArgumentException("display size/density out of range");
        }

        Class<?> looperClass = Class.forName("android.os.Looper");
        log("stage=before_main_looper");
        looperClass.getMethod("prepareMainLooper").invoke(null);
        Object handler = Class.forName("android.os.Handler")
                .getConstructor(looperClass).newInstance(looperClass.getMethod("myLooper").invoke(null));
        log("stage=looper_ready");

        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        log("stage=system_context_start");
        Object context = activityThread.getMethod("getSystemContext").invoke(thread);
        Object displayManager = call(context, "getSystemService",
                new Class<?>[] {String.class}, "display");
        log("stage=display_manager_ready manager=" + (displayManager != null));

        List<DisplayHandle> displays = new ArrayList<DisplayHandle>();
        DisplayHandle first = createDisplay(context, displayManager, handler, looperClass,
                0, width, height, density, idPath);
        displays.add(first);
        if (createSecondDisplay) {
            try {
                DisplayHandle second = createDisplay(context, displayManager, handler, looperClass,
                        1, width, height, density, secondIdPath);
                displays.add(second);
            } catch (Exception error) {
                try { releaseDisplay(first); } catch (Exception releaseError) {
                    log("rollback_failed displayId=" + first.displayId + " error="
                            + releaseError.getClass().getSimpleName());
                }
                throw error;
            }
        }
        log("stage=displays_ready count=" + displays.size());

        Runnable shutdownPoll = new Runnable() {
            @Override public void run() {
                for (DisplayHandle display : displays) pollDisplayControl(display);
                boolean requested = false;
                try (FileInputStream input = new FileInputStream(shutdownPath)) {
                    requested = input.read() == 's';
                } catch (Exception ignored) {
                    // The host pre-creates this private session control file.
                }
                if (!requested) {
                    try {
                        handler.getClass().getMethod("postDelayed", Runnable.class, long.class)
                                .invoke(handler, this, 100L);
                    } catch (Exception error) {
                        log("shutdown_poll_failed error=" + error.getClass().getSimpleName());
                    }
                    return;
                }
                boolean success = true;
                for (int i = displays.size() - 1; i >= 0; --i) {
                    DisplayHandle display = displays.get(i);
                    try {
                        releaseDisplay(display);
                    } catch (Exception error) {
                        success = false;
                        log("release_failed displayId=" + display.displayId + " error="
                                + error.getClass().getSimpleName());
                    }
                }
                try (FileOutputStream output = new FileOutputStream(shutdownPath, false)) {
                    output.write((success ? "released\n" : "failed\n").getBytes("US-ASCII"));
                    output.flush();
                } catch (Exception error) {
                    log("shutdown_ack_failed error=" + error.getClass().getSimpleName());
                }
            }
        };
        handler.getClass().getMethod("postDelayed", Runnable.class, long.class)
                .invoke(handler, shutdownPoll, 100L);
        looperClass.getMethod("loop").invoke(null);
        log("stage=looper_stopped");
    }
}

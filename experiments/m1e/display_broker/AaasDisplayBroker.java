package com.aaas.display;

import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

/** Narrow system-UID broker for one trusted, own-content AaaS display. */
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

    public static void main(String[] args) throws Exception {
        if (args.length > 4) diagnosticLog = new FileOutputStream(args[4], true);
        log("stage=main_entry");
        int width = args.length > 0 ? Integer.parseInt(args[0]) : 720;
        int height = args.length > 1 ? Integer.parseInt(args[1]) : 1280;
        int density = args.length > 2 ? Integer.parseInt(args[2]) : 240;
        String idPath = args.length > 3 ? args[3] : "/dev/aaas/vdisplay_id";
        String shutdownPath = args.length > 5 ? args[5] : "/dev/aaas/display_broker_shutdown";
        if (width < 1 || height < 1 || width > 4096 || height > 4096 || density < 1 || density > 1000) {
            throw new IllegalArgumentException("display size/density out of range");
        }

        Class<?> looperClass = Class.forName("android.os.Looper");
        log("stage=before_main_looper");
        looperClass.getMethod("prepareMainLooper").invoke(null);
        Object looper = looperClass.getMethod("myLooper").invoke(null);
        Object handler = Class.forName("android.os.Handler")
                .getConstructor(looperClass).newInstance(looper);
        log("stage=looper_ready");

        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        log("stage=system_context_start");
        Object context = activityThread.getMethod("getSystemContext").invoke(thread);
        Object displayManager = call(context, "getSystemService",
                new Class<?>[] {String.class}, "display");
        log("stage=display_manager_ready manager=" + (displayManager != null));

        Class<?> imageReaderClass = Class.forName("android.media.ImageReader");
        Object reader = imageReaderClass.getMethod("newInstance", int.class, int.class,
                int.class, int.class).invoke(null, width, height, 1, 3);
        log("stage=image_reader_ready");
        Class<?> listenerClass = Class.forName("android.media.ImageReader$OnImageAvailableListener");
        Object listener = Proxy.newProxyInstance(listenerClass.getClassLoader(),
                new Class<?>[] {listenerClass}, new ImageDrain());
        imageReaderClass.getMethod("setOnImageAvailableListener", listenerClass,
                Class.forName("android.os.Handler")).invoke(reader, listener, handler);
        Object surface = call(reader, "getSurface", new Class<?>[0]);

        Class<?> displayManagerClass = Class.forName("android.hardware.display.DisplayManager");
        int trusted = displayManagerClass.getField("VIRTUAL_DISPLAY_FLAG_TRUSTED").getInt(null);
        int ownContent = displayManagerClass.getField("VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY").getInt(null);
        Class<?> configClass = Class.forName("android.hardware.display.VirtualDisplayConfig");
        Class<?> builderClass = Class.forName("android.hardware.display.VirtualDisplayConfig$Builder");
        Constructor<?> builderCtor = builderClass.getConstructor(String.class, int.class,
                int.class, int.class);
        Object builder = builderCtor.newInstance("AaaS application output", width, height, density);
        call(builder, "setFlags", new Class<?>[] {int.class}, trusted | ownContent);
        call(builder, "setSurface", new Class<?>[] {Class.forName("android.view.Surface")}, surface);
        call(builder, "setHomeSupported", new Class<?>[] {boolean.class}, false);
        Object config = call(builder, "build", new Class<?>[0]);
        int configuredFlags = (Integer) call(config, "getFlags", new Class<?>[0]);
        log("stage=create_virtual_display flags=" + configuredFlags);
        Object virtualDisplay = displayManagerClass.getMethod("createVirtualDisplay", configClass)
                .invoke(displayManager, config);
        log("stage=create_virtual_display_returned");
        if (virtualDisplay == null) throw new IllegalStateException("DisplayManager returned null");
        Object display = call(virtualDisplay, "getDisplay", new Class<?>[0]);
        int displayId = (Integer) call(display, "getDisplayId", new Class<?>[0]);
        String uniqueId = (String) call(display, "getUniqueId", new Class<?>[0]);
        log("created displayId=" + displayId + " uniqueId=" + uniqueId + " size=" + width + "x" + height
                + " density=" + density + " flags=" + configuredFlags + " home=false");
        try (FileOutputStream output = new FileOutputStream(idPath, false)) {
            output.write((Integer.toString(displayId) + "\n").getBytes("US-ASCII"));
            output.flush();
        }
        // Let DisplayManager's display-added callback and WindowManager's display
        // initialization settle before reporting the host-task eligibility snapshot.
        Thread.sleep(1500);
        String canHostTasks;
        try {
            canHostTasks = String.valueOf(call(display, "canHostTasks", new Class<?>[0]));
        } catch (ReflectiveOperationException unavailable) {
            canHostTasks = "unavailable:" + unavailable.getClass().getSimpleName();
        }
        log("display_state displayId=" + displayId + " flags="
                + call(display, "getFlags", new Class<?>[0]) + " canHostTasks=" + canHostTasks);
        final Object ownedDisplay = virtualDisplay;
        final Object ownedReader = reader;
        final String ownedIdPath = idPath;
        final String ownedShutdownPath = shutdownPath;
        final Object ownedHandler = handler;
        Runnable shutdownPoll = new Runnable() {
            @Override public void run() {
                boolean requested = false;
                try (FileInputStream input = new FileInputStream(ownedShutdownPath)) {
                    requested = input.read() == 's';
                } catch (Exception ignored) {
                    // The host pre-creates this private session control file.
                }
                if (!requested) {
                    try {
                        ownedHandler.getClass().getMethod("postDelayed", Runnable.class, long.class)
                                .invoke(ownedHandler, this, 100L);
                    } catch (Exception error) {
                        log("shutdown_poll_failed error=" + error.getClass().getSimpleName());
                    }
                    return;
                }
                try {
                    call(ownedDisplay, "release", new Class<?>[0]);
                    call(ownedReader, "close", new Class<?>[0]);
                    try (FileOutputStream output = new FileOutputStream(ownedIdPath, false)) {
                        output.flush();
                    }
                    try (FileOutputStream output = new FileOutputStream(ownedShutdownPath, false)) {
                        output.write("released\n".getBytes("US-ASCII"));
                        output.flush();
                    }
                    log("released displayId=" + displayId + " reason=host_shutdown");
                } catch (Exception error) {
                    log("release_failed displayId=" + displayId + " error="
                            + error.getClass().getSimpleName());
                    try (FileOutputStream output = new FileOutputStream(ownedShutdownPath, false)) {
                        output.write("failed\n".getBytes("US-ASCII"));
                    } catch (Exception ignored) { }
                }
            }
        };
        handler.getClass().getMethod("postDelayed", Runnable.class, long.class)
                .invoke(handler, shutdownPoll, 100L);
        looperClass.getMethod("loop").invoke(null);
        log("stage=looper_stopped");
    }
}

package org.aaas.netprobe;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;
import java.io.OutputStream;
import java.lang.reflect.Method;
import java.net.InetAddress;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;

public final class MainActivity extends Activity {
    private static final String TAG = "AaasNetworkProbe";
    private TextView view;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        view = new TextView(this);
        view.setText("AaaS network probe running");
        setContentView(view);
        new Thread(new Runnable() {
            @Override public void run() { verifyNetwork(); }
        }, "aaas-network-probe").start();
    }

    private void verifyNetwork() {
        String result;
        try {
            Object manager = getSystemService("connectivity");
            Object network = manager.getClass().getMethod("getActiveNetwork").invoke(manager);
            if (network == null) throw new IllegalStateException("no active Android network");
            Method capabilitiesMethod = manager.getClass().getMethod(
                    "getNetworkCapabilities", network.getClass());
            Object capabilities = capabilitiesMethod.invoke(manager, network);
            if (capabilities == null) throw new IllegalStateException("no active capabilities");
            Method hasCapability = capabilities.getClass().getMethod("hasCapability", int.class);
            boolean internet = (Boolean)hasCapability.invoke(capabilities, 12);
            boolean validated = (Boolean)hasCapability.invoke(capabilities, 16);
            Object links = manager.getClass().getMethod("getLinkProperties", network.getClass())
                    .invoke(manager, network);
            String iface = String.valueOf(links.getClass().getMethod("getInterfaceName")
                    .invoke(links));
            String dnsServers = String.valueOf(links.getClass().getMethod("getDnsServers")
                    .invoke(links));
            String routes = String.valueOf(links.getClass().getMethod("getRoutes")
                    .invoke(links));
            String address = InetAddress.getByName("connectivitycheck.gstatic.com")
                    .getHostAddress();
            HttpsURLConnection connection = (HttpsURLConnection)new URL(
                    "https://www.google.com/generate_204").openConnection();
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(8000);
            connection.setInstanceFollowRedirects(false);
            int code = connection.getResponseCode();
            String cipher = connection.getCipherSuite();
            connection.disconnect();
            if (!internet || code != 204 || cipher == null) {
                throw new IllegalStateException("internet=" + internet + " https=" + code);
            }
            result = "PASS network=" + network + " internet=" + internet
                    + " validated=" + validated + " iface=" + iface + " dns=" + dnsServers
                    + " routes=" + routes + " resolved=" + address + " https=" + code
                    + " tls=" + cipher;
        } catch (Throwable error) {
            result = "FAIL " + error.getClass().getSimpleName() + ": " + error.getMessage();
        }
        Log.i(TAG, result);
        try {
            String uri = storeInDownloads(result + "\n");
            result += " output=" + uri;
        } catch (Throwable error) {
            result += " output_error=" + error.getClass().getSimpleName()
                    + ":" + error.getMessage();
            Log.e(TAG, result, error);
        }
        final String display = result;
        runOnUiThread(new Runnable() {
            @Override public void run() { view.setText(display); }
        });
    }

    private String storeInDownloads(String contents) throws Exception {
        Class<?> valuesType = Class.forName("android.content.ContentValues");
        Object values = valuesType.newInstance();
        Method put = valuesType.getMethod("put", String.class, String.class);
        put.invoke(values, "display_name", "AaasNetworkProbe.txt");
        put.invoke(values, "mime_type", "text/plain");
        put.invoke(values, "relative_path", "Download/");
        Class<?> uriType = Class.forName("android.net.Uri");
        Object collection = uriType.getMethod("parse", String.class).invoke(null,
                "content://media/external/downloads");
        Object resolver = getClass().getMethod("getContentResolver").invoke(this);
        Object item = resolver.getClass().getMethod("insert", uriType, valuesType)
                .invoke(resolver, collection, values);
        if (item == null) throw new IllegalStateException("Downloads insertion failed");
        OutputStream stream = (OutputStream)resolver.getClass()
                .getMethod("openOutputStream", uriType).invoke(resolver, item);
        if (stream == null) throw new IllegalStateException("Downloads stream unavailable");
        try {
            stream.write(contents.getBytes("UTF-8"));
            stream.flush();
        } finally {
            stream.close();
        }
        return String.valueOf(item);
    }
}

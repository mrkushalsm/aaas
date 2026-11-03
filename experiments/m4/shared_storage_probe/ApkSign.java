import com.android.apksig.ApkSigner;
import java.io.File;
import java.io.FileInputStream;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.X509Certificate;
import java.util.Collections;

/** Signs a diagnostic APK using v1/v2/v3 schemes through Android apksig. */
public final class ApkSign {
    private ApkSign() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 5) {
            throw new IllegalArgumentException(
                    "usage: ApkSign <keystore> <password> <alias> <input> <output>");
        }
        String alias = args[2];
        KeyStore keyStore = KeyStore.getInstance(KeyStore.getDefaultType());
        try (FileInputStream input = new FileInputStream(args[0])) {
            keyStore.load(input, args[1].toCharArray());
        }
        PrivateKey key = (PrivateKey) keyStore.getKey(alias, args[1].toCharArray());
        X509Certificate certificate = (X509Certificate) keyStore.getCertificate(alias);
        ApkSigner.SignerConfig signer = new ApkSigner.SignerConfig.Builder(
                alias, key, Collections.singletonList(certificate)).build();
        new ApkSigner.Builder(Collections.singletonList(signer))
                .setInputApk(new File(args[3]))
                .setOutputApk(new File(args[4]))
                .setMinSdkVersion(28)
                .setV1SigningEnabled(true)
                .setV2SigningEnabled(true)
                .setV3SigningEnabled(true)
                .build()
                .sign();
    }
}

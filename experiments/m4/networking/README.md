# Android networking probe

This local diagnostic APK exercises the installed Android runtime's
`ConnectivityManager`, DNS resolver, HTTPS/TLS stack, and network link
properties. It is not part of the AaaS release bundle.

Build it with the pinned tools and the isolated installation's development
signing key:

```sh
python experiments/m4/networking/build_probe.py \
  --apktool "$APKTOOL_JAR" --framework-res "$ANDROID_ROOT/system/framework/framework-res.apk" \
  --apksig "$APKSIG_JAR" --dx "$DX" --zipalign "$ZIPALIGN" \
  --keystore "$AAAS_TEST_KEYSTORE" --output "$AAAS_TEST_WORKSPACE/tmp/AaasNetworkProbe.apk"
```

Install and run only in a disposable AaaS profile:

```sh
aaas apps install "$AAAS_TEST_WORKSPACE/tmp/AaasNetworkProbe.apk"
aaas apps launch org.aaas.netprobe
```

The activity checks Android's active network and INTERNET/VALIDATED
capabilities, LinkProperties, DNS resolution, and a TLS-verified HTTPS
`204` response. It attempts to write the result into the Android Downloads
collection so the existing AaaS storage scanner can collect it without broad
filesystem access. On the tested image, that optional export failed through
MediaStore reflection; the result remained visible in the app window and was
preserved as a cropped screenshot. Process launch or network-interface
counters alone are not application-level acceptance.

The probe uses `connectivitycheck.gstatic.com` and
`www.google.com/generate_204`; a blocked endpoint is an environmental failure
and must be distinguished from the Android networking implementation.

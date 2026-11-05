.class public Lorg/aaas/latencyprobe/ProbeActivity;
.super Landroid/app/Activity;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 5
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V
    invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;
    move-result-object v0
    const-string v1, "aaas.scan"
    const/4 v2, 0x0
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->getBooleanExtra(Ljava/lang/String;Z)Z
    move-result v1
    if-eqz v1, :check_uri
    invoke-direct {p0}, Lorg/aaas/latencyprobe/ProbeActivity;->scanExternalVolume()V
    return-void
    :check_uri
    const-string v1, "aaas.scanPath"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    if-eqz v1, :check_query
    invoke-direct {p0, v1}, Lorg/aaas/latencyprobe/ProbeActivity;->scanFile(Ljava/lang/String;)V
    return-void
    :check_query
    const-string v1, "aaas.queryName"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    if-eqz v1, :check_uri_extra
    const-string v2, "android.permission.READ_MEDIA_IMAGES"
    invoke-virtual {p0, v2}, Landroid/app/Activity;->checkSelfPermission(Ljava/lang/String;)I
    move-result v2
    if-nez v2, :request_media_permission
    invoke-direct {p0, v1}, Lorg/aaas/latencyprobe/ProbeActivity;->queryMediaStore(Ljava/lang/String;)V
    return-void
    :request_media_permission
    const/4 v2, 0x1
    new-array v2, v2, [Ljava/lang/String;
    const-string v3, "android.permission.READ_MEDIA_IMAGES"
    const/4 v4, 0x0
    aput-object v3, v2, v4
    const/16 v3, 0x33
    invoke-virtual {p0, v2, v3}, Landroid/app/Activity;->requestPermissions([Ljava/lang/String;I)V
    return-void
    :check_uri_extra
    const-string v1, "aaas.uri"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    if-eqz v1, :load_persisted_uri
    invoke-direct {p0, v1}, Lorg/aaas/latencyprobe/ProbeActivity;->verifyPersistedUri(Ljava/lang/String;)V
    return-void
    :load_persisted_uri
    invoke-direct {p0}, Lorg/aaas/latencyprobe/ProbeActivity;->loadPersistedUri()Ljava/lang/String;
    move-result-object v1
    if-eqz v1, :open_picker
    invoke-direct {p0, v1}, Lorg/aaas/latencyprobe/ProbeActivity;->verifyPersistedUri(Ljava/lang/String;)V
    return-void
    :open_picker
    new-instance v0, Landroid/widget/TextView;
    invoke-direct {v0, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V
    const-string v1, "Select 000-host-read.txt to verify host-to-Android SAF read"
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V
    invoke-virtual {p0, v0}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V
    new-instance v0, Landroid/content/Intent;
    const-string v1, "android.intent.action.OPEN_DOCUMENT"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V
    const-string v1, "text/plain"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->setType(Ljava/lang/String;)Landroid/content/Intent;
    const-string v1, "android.provider.extra.INITIAL_URI"
    const-string v2, "content://com.android.externalstorage.documents/document/primary%3ADownload"
    invoke-static {v2}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v2
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Landroid/os/Parcelable;)Landroid/content/Intent;
    const/16 v1, 0x38
    invoke-virtual {p0, v0, v1}, Landroid/app/Activity;->startActivityForResult(Landroid/content/Intent;I)V
    return-void
.end method

.method private savePersistedUri(Ljava/lang/String;)V
    .locals 3
    const-string v0, "aaas-storage"
    const/4 v1, 0x0
    invoke-virtual {p0, v0, v1}, Landroid/content/Context;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;
    move-result-object v0
    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;
    move-result-object v0
    const-string v1, "persisted-uri"
    invoke-interface {v0, v1, p1}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;
    move-result-object v0
    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->apply()V
    return-void
.end method

.method private loadPersistedUri()Ljava/lang/String;
    .locals 3
    const-string v0, "aaas-storage"
    const/4 v1, 0x0
    invoke-virtual {p0, v0, v1}, Landroid/content/Context;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;
    move-result-object v0
    const-string v1, "persisted-uri"
    const/4 v2, 0x0
    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    return-object v0
.end method

.method private scanFile(Ljava/lang/String;)V
    .locals 5
    const/4 v0, 0x1
    new-array v1, v0, [Ljava/lang/String;
    const/4 v0, 0x0
    aput-object p1, v1, v0
    new-instance v2, Lorg/aaas/latencyprobe/ScanListener;
    invoke-direct {v2}, Lorg/aaas/latencyprobe/ScanListener;-><init>()V
    const/4 v3, 0x0
    invoke-static {p0, v1, v3, v2}, Landroid/media/MediaScannerConnection;->scanFile(Landroid/content/Context;[Ljava/lang/String;[Ljava/lang/String;Landroid/media/MediaScannerConnection$OnScanCompletedListener;)V
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_FILE_SCAN_REQUESTED"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public onRequestPermissionsResult(I[Ljava/lang/String;[I)V
    .locals 3
    invoke-super {p0, p1, p2, p3}, Landroid/app/Activity;->onRequestPermissionsResult(I[Ljava/lang/String;[I)V
    const/16 v0, 0x33
    if-ne p1, v0, :permission_result_done
    invoke-static {p0, p3}, Lorg/aaas/latencyprobe/UserdataProbe;->reportMediaPermissionResult(Landroid/content/Context;[I)V
    array-length v0, p3
    if-lez v0, :permission_denied
    const/4 v0, 0x0
    aget v1, p3, v0
    if-nez v1, :permission_denied
    invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;
    move-result-object v0
    const-string v1, "aaas.queryName"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :permission_result_done
    invoke-direct {p0, v0}, Lorg/aaas/latencyprobe/ProbeActivity;->queryMediaStore(Ljava/lang/String;)V
    return-void
    :permission_denied
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_MEDIASTORE_PERMISSION_DENIED"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :permission_result_done
    return-void
.end method

.method private queryMediaStore(Ljava/lang/String;)V
    .locals 7
    :try_start_query
    invoke-virtual {p0}, Landroid/app/Activity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0
    const-string v1, "content://media/external_primary/file"
    invoke-static {v1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v1
    const/4 v2, 0x1
    new-array v2, v2, [Ljava/lang/String;
    const-string v3, "_display_name"
    const/4 v5, 0x0
    aput-object v3, v2, v5
    const-string v3, "_display_name=?"
    const/4 v4, 0x1
    new-array v4, v4, [Ljava/lang/String;
    aput-object p1, v4, v5
    const/4 v5, 0x0
    invoke-virtual/range {v0 .. v5}, Landroid/content/ContentResolver;->query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;
    move-result-object v6
    invoke-interface {v6}, Landroid/database/Cursor;->getCount()I
    move-result v1
    invoke-interface {v6}, Landroid/database/Cursor;->close()V
    const-string v2, "AaasStorageProbe"
    new-instance v3, Ljava/lang/StringBuilder;
    invoke-direct {v3}, Ljava/lang/StringBuilder;-><init>()V
    const-string v4, "ANDROID_MEDIASTORE_MATCHES="
    invoke-virtual {v3, v4}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v3
    invoke-virtual {v3, v1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    move-result-object v3
    invoke-virtual {v3}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v3
    invoke-static {v2, v3}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :try_end_query
    .catch Ljava/lang/Exception; {:try_start_query .. :try_end_query} :query_failed
    :query_failed
    move-exception v0
    const-string v1, "AaasStorageProbe"
    const-string v2, "ANDROID_MEDIASTORE_QUERY_FAILED"
    invoke-static {v1, v2, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-void
.end method

.method private scanExternalVolume()V
    .locals 5
    :try_start_scan
    invoke-virtual {p0}, Landroid/app/Activity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v0
    const-string v1, "content://media"
    invoke-static {v1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v1
    const-string v2, "scan_volume"
    const-string v3, "external_primary"
    const/4 v4, 0x0
    invoke-virtual {v0, v1, v2, v3, v4}, Landroid/content/ContentResolver;->call(Landroid/net/Uri;Ljava/lang/String;Ljava/lang/String;Landroid/os/Bundle;)Landroid/os/Bundle;
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_VOLUME_SCAN_COMPLETE"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :try_end_scan
    .catch Ljava/lang/Exception; {:try_start_scan .. :try_end_scan} :scan_failed
    :scan_failed
    move-exception v0
    const-string v1, "AaasStorageProbe"
    const-string v2, "ANDROID_VOLUME_SCAN_FAILED"
    invoke-static {v1, v2, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-void
.end method

.method private verifyPersistedUri(Ljava/lang/String;)V
    .locals 5
    :try_start_persisted
    invoke-static {p1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {p0}, Landroid/app/Activity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v1
    invoke-virtual {v1, v0}, Landroid/content/ContentResolver;->openInputStream(Landroid/net/Uri;)Ljava/io/InputStream;
    move-result-object v1
    const/16 v2, 0x100
    new-array v2, v2, [B
    invoke-virtual {v1, v2}, Ljava/io/InputStream;->read([B)I
    move-result v3
    invoke-virtual {v1}, Ljava/io/InputStream;->close()V
    new-instance v4, Ljava/lang/String;
    const-string v0, "UTF-8"
    const/4 v1, 0x0
    invoke-direct {v4, v2, v1, v3, v0}, Ljava/lang/String;-><init>([BIILjava/lang/String;)V
    const-string v0, "host-to-android fixture v2\n"
    invoke-virtual {v0, v4}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v1
    if-eqz v1, :persisted_mismatch
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_PERSISTED_URI_READ_OK"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :persisted_mismatch
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_PERSISTED_URI_READ_MISMATCH"
    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :try_end_persisted
    .catch Ljava/lang/Exception; {:try_start_persisted .. :try_end_persisted} :persisted_failed
    :persisted_failed
    move-exception v0
    const-string v1, "AaasStorageProbe"
    const-string v2, "ANDROID_PERSISTED_URI_READ_FAILED"
    invoke-static {v1, v2, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-void
.end method

.method protected onActivityResult(IILandroid/content/Intent;)V
    .locals 8
    invoke-super {p0, p1, p2, p3}, Landroid/app/Activity;->onActivityResult(IILandroid/content/Intent;)V
    const/16 v0, 0x38
    if-ne p1, v0, :read_done
    const/4 v0, -0x1
    if-ne p2, v0, :read_cancelled
    :try_start
    invoke-virtual {p3}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {p3}, Landroid/content/Intent;->getFlags()I
    move-result v6
    and-int/lit8 v7, v6, 0x40
    if-eqz v7, :persistable_done
    and-int/lit8 v6, v6, 0x3
    if-eqz v6, :persistable_done
    invoke-virtual {p0}, Landroid/app/Activity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v7
    invoke-virtual {v7, v0, v6}, Landroid/content/ContentResolver;->takePersistableUriPermission(Landroid/net/Uri;I)V
    const-string v4, "AaasStorageProbe"
    const-string v5, "ANDROID_PERSISTED_GRANT_OK"
    invoke-static {v4, v5}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :persistable_done
    invoke-virtual {v0}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v5
    invoke-direct {p0, v5}, Lorg/aaas/latencyprobe/ProbeActivity;->savePersistedUri(Ljava/lang/String;)V
    const-string v4, "AaasStorageProbe"
    invoke-static {v4, v5}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    invoke-virtual {p3}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {p0}, Landroid/app/Activity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v1
    invoke-virtual {v1, v0}, Landroid/content/ContentResolver;->openInputStream(Landroid/net/Uri;)Ljava/io/InputStream;
    move-result-object v1
    const/16 v2, 0x100
    new-array v2, v2, [B
    invoke-virtual {v1, v2}, Ljava/io/InputStream;->read([B)I
    move-result v3
    invoke-virtual {v1}, Ljava/io/InputStream;->close()V
    new-instance v4, Ljava/lang/String;
    const-string v5, "UTF-8"
    const/4 v0, 0x0
    invoke-direct {v4, v2, v0, v3, v5}, Ljava/lang/String;-><init>([BIILjava/lang/String;)V
    const-string v5, "host-to-android fixture v2\n"
    invoke-virtual {v5, v4}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2
    if-eqz v2, :read_mismatch
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_SAF_READ_OK"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :read_mismatch
    const-string v0, "AaasStorageProbe"
    move-object v1, v4
    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :try_end
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :read_failed
    :read_failed
    move-exception v2
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_SAF_READ_FAILED"
    invoke-static {v0, v1, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-void
    :read_cancelled
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_SAF_READ_CANCELLED"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :read_done
    return-void
.end method

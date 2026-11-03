.class public Lorg/aaas/latencyprobe/ProbeActivity;
.super Landroid/app/Activity;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 3
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V
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
    const-string v2, "content://com.android.providers.downloads.documents/root/downloads"
    invoke-static {v2}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v2
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Landroid/os/Parcelable;)Landroid/content/Intent;
    const/16 v1, 0x38
    invoke-virtual {p0, v0, v1}, Landroid/app/Activity;->startActivityForResult(Landroid/content/Intent;I)V
    return-void
.end method

.method protected onActivityResult(IILandroid/content/Intent;)V
    .locals 6
    invoke-super {p0, p1, p2, p3}, Landroid/app/Activity;->onActivityResult(IILandroid/content/Intent;)V
    const/16 v0, 0x38
    if-ne p1, v0, :read_done
    const/4 v0, -0x1
    if-ne p2, v0, :read_cancelled
    :try_start
    invoke-virtual {p3}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {v0}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v5
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

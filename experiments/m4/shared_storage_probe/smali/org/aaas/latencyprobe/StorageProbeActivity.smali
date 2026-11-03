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
    const-string v1, "AaaS shared storage probe: choose Documents and save"
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V
    invoke-virtual {p0, v0}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V
    new-instance v0, Landroid/content/Intent;
    const-string v1, "android.intent.action.CREATE_DOCUMENT"
    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V
    const-string v1, "text/plain"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->setType(Ljava/lang/String;)Landroid/content/Intent;
    const-string v1, "android.intent.extra.TITLE"
    const-string v2, "aaas-storage-android-to-host.txt"
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    const/16 v1, 0x37
    invoke-virtual {p0, v0, v1}, Landroid/app/Activity;->startActivityForResult(Landroid/content/Intent;I)V
    return-void
.end method

.method protected onActivityResult(IILandroid/content/Intent;)V
    .locals 4
    invoke-super {p0, p1, p2, p3}, Landroid/app/Activity;->onActivityResult(IILandroid/content/Intent;)V
    const/16 v0, 0x37
    if-ne p1, v0, :result_done
    const/4 v0, -0x1
    if-ne p2, v0, :result_cancelled
    :try_start
    invoke-virtual {p3}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {p0}, Landroid/app/Activity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v1
    invoke-virtual {v1, v0}, Landroid/content/ContentResolver;->openOutputStream(Landroid/net/Uri;)Ljava/io/OutputStream;
    move-result-object v1
    const-string v2, "android-app-to-host fixture v1\n"
    const-string v3, "UTF-8"
    invoke-virtual {v2, v3}, Ljava/lang/String;->getBytes(Ljava/lang/String;)[B
    move-result-object v2
    invoke-virtual {v1, v2}, Ljava/io/OutputStream;->write([B)V
    invoke-virtual {v1}, Ljava/io/OutputStream;->close()V
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_SAF_WRITE_OK"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
    :try_end
    .catch Ljava/lang/Exception; {:try_start .. :try_end} :write_failed
    :write_failed
    move-exception v2
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_SAF_WRITE_FAILED"
    invoke-static {v0, v1, v2}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)I
    return-void
    :result_cancelled
    const-string v0, "AaasStorageProbe"
    const-string v1, "ANDROID_SAF_CREATE_CANCELLED"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    :result_done
    return-void
.end method

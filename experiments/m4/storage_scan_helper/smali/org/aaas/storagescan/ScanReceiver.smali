.class public Lorg/aaas/storagescan/ScanReceiver;
.super Landroid/content/BroadcastReceiver;
.implements Landroid/media/MediaScannerConnection$OnScanCompletedListener;

.field private pending:Landroid/content/BroadcastReceiver$PendingResult;
.field private requestId:Ljava/lang/String;
.field private sourcePath:Ljava/lang/String;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/content/BroadcastReceiver;-><init>()V
    return-void
.end method

.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .locals 5
    const-string v0, "path"
    invoke-virtual {p2, v0}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0
    const-string v1, "requestId"
    invoke-virtual {p2, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    if-eqz v0, :invalid_request
    if-eqz v1, :invalid_request
    iput-object v0, p0, Lorg/aaas/storagescan/ScanReceiver;->sourcePath:Ljava/lang/String;
    iput-object v1, p0, Lorg/aaas/storagescan/ScanReceiver;->requestId:Ljava/lang/String;
    invoke-virtual {p0}, Landroid/content/BroadcastReceiver;->goAsync()Landroid/content/BroadcastReceiver$PendingResult;
    move-result-object v2
    iput-object v2, p0, Lorg/aaas/storagescan/ScanReceiver;->pending:Landroid/content/BroadcastReceiver$PendingResult;
    const/4 v2, 0x1
    new-array v2, v2, [Ljava/lang/String;
    const/4 v3, 0x0
    aput-object v0, v2, v3
    const/4 v3, 0x0
    invoke-static {p1, v2, v3, p0}, Landroid/media/MediaScannerConnection;->scanFile(Landroid/content/Context;[Ljava/lang/String;[Ljava/lang/String;Landroid/media/MediaScannerConnection$OnScanCompletedListener;)V
    return-void
    :invalid_request
    const-string v0, "AaaSStorageScan"
    const-string v1, "ANDROID_FILE_SCAN_REJECTED invalid_request"
    invoke-static {v0, v1}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public onScanCompleted(Ljava/lang/String;Landroid/net/Uri;)V
    .locals 5
    const-string v0, "AaaSStorageScan"
    new-instance v1, Ljava/lang/StringBuilder;
    invoke-direct {v1}, Ljava/lang/StringBuilder;-><init>()V
    const-string v2, "ANDROID_FILE_SCAN_COMPLETE id="
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    iget-object v2, p0, Lorg/aaas/storagescan/ScanReceiver;->requestId:Ljava/lang/String;
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    const-string v2, " path="
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    invoke-virtual {v1, p1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    const-string v2, " uri="
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    if-eqz p2, :uri_null
    invoke-virtual {p2}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v2
    goto :uri_ready
    :uri_null
    const-string v2, "null"
    :uri_ready
    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-result-object v1
    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    iget-object v0, p0, Lorg/aaas/storagescan/ScanReceiver;->pending:Landroid/content/BroadcastReceiver$PendingResult;
    if-eqz v0, :done
    invoke-virtual {v0}, Landroid/content/BroadcastReceiver$PendingResult;->finish()V
    :done
    return-void
.end method

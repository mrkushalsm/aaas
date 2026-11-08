package org.aaas.audioprobe;

import android.app.Activity;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;
import java.security.MessageDigest;
import java.util.Locale;

public final class MainActivity extends Activity {
    private static final String TAG = "AaasAudioProbe";
    private static final int RECORD_PERMISSION_REQUEST = 41;
    private TextView statusView;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        statusView = new TextView(this);
        final boolean record = getIntent().getBooleanExtra("record", false);
        statusView.setText(record ? "AaaS audio probe: request microphone permission to record"
                : "AaaS audio probe: playing a quiet 440 Hz stereo tone");
        setContentView(statusView);
        if (record) {
            if (checkSelfPermission("android.permission.RECORD_AUDIO")
                    != PackageManager.PERMISSION_GRANTED) {
                requestCapturePermission();
            } else {
                Log.i(TAG, "RECORD_PERMISSION_ALREADY_GRANTED");
                startCapture();
            }
            return;
        }
        startPlayback();
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions,
            int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == RECORD_PERMISSION_REQUEST && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            Log.i(TAG, "RECORD_PERMISSION_GRANTED");
            startCapture();
        } else if (requestCode == RECORD_PERMISSION_REQUEST) {
            Log.i(TAG, "RECORD_PERMISSION_DENIED");
            statusView.setText("Microphone denied; tap to request again");
            statusView.setOnClickListener(new android.view.View.OnClickListener() {
                @Override public void onClick(android.view.View v) {
                    requestCapturePermission();
                }
            });
        }
    }

    private void requestCapturePermission() {
        requestPermissions(new String[] {"android.permission.RECORD_AUDIO"},
                RECORD_PERMISSION_REQUEST);
    }

    private void startPlayback() {
        new Thread(new Runnable() {
            @Override public void run() {
                AudioTrack track = null;
                try {
                    int rate = 48000;
                    int frames = rate * 4;
                    short[] pcm = new short[frames * 2];
                    for (int i = 0; i < frames; i++) {
                        short sample = (short)(3000.0 * Math.sin(2.0 * Math.PI * 440.0 * i / rate));
                        pcm[i * 2] = sample;
                        pcm[i * 2 + 1] = sample;
                    }
                    int bufferBytes = Math.max(4096,
                            AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_STEREO,
                                    AudioFormat.ENCODING_PCM_16BIT));
                    track = new AudioTrack(AudioManager.STREAM_MUSIC, rate,
                            AudioFormat.CHANNEL_OUT_STEREO, AudioFormat.ENCODING_PCM_16BIT,
                            bufferBytes, AudioTrack.MODE_STREAM);
                    track.play();
                    int written = writeSegment(track, pcm, 0, pcm.length / 4);
                    awaitPlaybackHead(track, written / 2);
                    track.pause();
                    Log.i(TAG, "PLAYBACK_PAUSE_OK frames=" + (written / 2));
                    Thread.sleep(1500);
                    track.play();
                    Log.i(TAG, "PLAYBACK_RESUME_OK");
                    written += writeSegment(track, pcm, written, pcm.length / 2);
                    awaitPlaybackHead(track, written / 2);
                    track.setVolume(0.0f);
                    written += writeSegment(track, pcm, written, pcm.length * 3 / 4);
                    awaitPlaybackHead(track, written / 2);
                    track.setVolume(1.0f);
                    written += writeSegment(track, pcm, written, pcm.length);
                    awaitPlaybackHead(track, written / 2);
                    Log.i(TAG, "PLAYBACK_OK rate=" + rate + " channels=2 frames=" + (written / 2)
                            + " pause_resume=ok mute=ok");
                    Thread.sleep(1000);
                } catch (Throwable error) {
                    Log.e(TAG, "PLAYBACK_FAILED " + error.getClass().getSimpleName(), error);
                } finally {
                    if (track != null) {
                        try { track.stop(); } catch (Throwable ignored) {}
                        track.release();
                    }
                }
                startMonoPlayback();
            }
        }, "aaas-audio-probe").start();
    }

    private static void startMonoPlayback() {
        AudioTrack track = null;
        try {
            final int rate = 44100;
            final int frames = rate;
            short[] pcm = new short[frames];
            for (int i = 0; i < frames; i++) {
                pcm[i] = (short)(1500.0 * Math.sin(2.0 * Math.PI * 660.0 * i / rate));
            }
            int bufferBytes = Math.max(4096,
                    AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO,
                            AudioFormat.ENCODING_PCM_16BIT));
            track = new AudioTrack(AudioManager.STREAM_MUSIC, rate,
                    AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    bufferBytes, AudioTrack.MODE_STREAM);
            track.play();
            writeSegment(track, pcm, 0, pcm.length);
            awaitPlaybackHead(track, frames);
            Log.i(TAG, "MONO_PLAYBACK_OK rate=" + rate + " channels=1 frames=" + frames);
        } catch (Throwable error) {
            Log.e(TAG, "MONO_PLAYBACK_FAILED " + error.getClass().getSimpleName(), error);
        } finally {
            if (track != null) {
                try { track.stop(); } catch (Throwable ignored) {}
                track.release();
            }
        }
    }

    private static int writeSegment(AudioTrack track, short[] pcm, int start, int end) {
        int written = start;
        while (written < end) {
            int count = track.write(pcm, written, end - written);
            if (count <= 0) throw new IllegalStateException("AudioTrack.write=" + count);
            written += count;
        }
        return written - start;
    }

    private static void awaitPlaybackHead(AudioTrack track, int targetFrames) throws Exception {
        long deadline = android.os.SystemClock.elapsedRealtime() + 10000;
        while (Integer.toUnsignedLong(track.getPlaybackHeadPosition()) < targetFrames) {
            if (android.os.SystemClock.elapsedRealtime() >= deadline) {
                throw new IllegalStateException("AudioTrack playback head timeout at "
                        + track.getPlaybackHeadPosition() + " of " + targetFrames);
            }
            Thread.sleep(20);
        }
    }

    private void startCapture() {
        new Thread(new Runnable() {
            @Override public void run() {
                AudioRecord record = null;
                try {
                    final int rate = 48000;
                    final int requestedBytes = Math.max(4096,
                            AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO,
                                    AudioFormat.ENCODING_PCM_16BIT));
                    record = new AudioRecord(MediaRecorder.AudioSource.MIC, rate,
                            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                            requestedBytes);
                    if (record.getState() != AudioRecord.STATE_INITIALIZED) {
                        throw new IllegalStateException("AudioRecord state=" + record.getState());
                    }
                    short[] pcm = new short[rate * 3];
                    record.startRecording();
                    int total = 0;
                    while (total < pcm.length) {
                        int count = record.read(pcm, total, pcm.length - total,
                                AudioRecord.READ_BLOCKING);
                        if (count <= 0) throw new IllegalStateException("AudioRecord.read=" + count);
                        total += count;
                    }
                    record.stop();
                    MessageDigest digest = MessageDigest.getInstance("SHA-256");
                    long sumSquares = 0;
                    long sum = 0;
                    short previous = 0;
                    int crossings = 0;
                    byte[] bytes = new byte[pcm.length * 2];
                    for (int i = 0; i < pcm.length; i++) {
                        short sample = pcm[i];
                        bytes[i * 2] = (byte)(sample & 0xff);
                        bytes[i * 2 + 1] = (byte)((sample >>> 8) & 0xff);
                        sumSquares += (long)sample * sample;
                        sum += sample;
                        if (i > 0 && ((previous < 0 && sample >= 0)
                                || (previous >= 0 && sample < 0))) crossings++;
                        previous = sample;
                    }
                    byte[] hash = digest.digest(bytes);
                    StringBuilder hex = new StringBuilder();
                    for (byte value : hash) hex.append(String.format(Locale.ROOT, "%02x", value & 0xff));
                    int tailFrames = Math.min(rate, pcm.length);
                    long tailSumSquares = 0;
                    long tailSum = 0;
                    for (int i = pcm.length - tailFrames; i < pcm.length; i++) {
                        tailSumSquares += (long)pcm[i] * pcm[i];
                        tailSum += pcm[i];
                    }
                    double mean = (double)tailSum / tailFrames;
                    double rms = Math.sqrt((double)tailSumSquares / tailFrames - mean * mean);
                    if (rms < 1.0) {
                        Log.e(TAG, "CAPTURE_FAILED silent PCM frames=" + pcm.length
                                + " tail_frames=" + tailFrames);
                        return;
                    }
                    int dominantHz = 0;
                    double dominantPower = -1.0;
                    for (int frequency = 300; frequency <= 600; frequency += 5) {
                        double coefficient = 2.0 * Math.cos(2.0 * Math.PI * frequency / rate);
                        double s1 = 0.0, s2 = 0.0;
                        for (short sample : pcm) {
                            double s0 = (sample - mean) + coefficient * s1 - s2;
                            s2 = s1;
                            s1 = s0;
                        }
                        double power = s1 * s1 + s2 * s2 - coefficient * s1 * s2;
                        if (power > dominantPower) {
                            dominantPower = power;
                            dominantHz = frequency;
                        }
                    }
                    Log.i(TAG, "CAPTURE_OK rate=" + rate + " channels=1 frames=" + pcm.length
                            + " rms=" + String.format(Locale.ROOT, "%.2f", rms)
                            + " zero_crossings=" + crossings + " dominant_hz=" + dominantHz
                            + " sha256=" + hex);
                } catch (Throwable error) {
                    Log.e(TAG, "CAPTURE_FAILED " + error.getClass().getSimpleName(), error);
                } finally {
                    if (record != null) {
                        try { if (record.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) record.stop(); }
                        catch (Throwable ignored) {}
                        record.release();
                    }
                }
            }
        }, "aaas-audio-capture-probe").start();
    }
}

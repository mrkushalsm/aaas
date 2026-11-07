#!/usr/bin/env python3
"""Run a controlled live session test of run_aaas.py, capturing diagnostics."""

import glob
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = Path('/run/media/mrkus/Aaas/aaas-workspace')
TMP = WORKSPACE / 'tmp'
DUMP_DIR = TMP / 'm1b84_gemini_repro_frames'
OUT_SUMMARY = ROOT / 'results/m1b84/gemini_session_summary.json'


def get_pids_for(name):
    try:
        out = subprocess.check_output(['pgrep', '-f', name], text=True)
        return [int(p) for p in out.strip().split() if p]
    except subprocess.CalledProcessError:
        return []


def get_fd_count(pid):
    try:
        return len(os.listdir(f'/proc/{pid}/fd'))
    except (PermissionError, FileNotFoundError, ProcessLookupError):
        return None


def get_rss_kib(pid):
    try:
        with open(f'/proc/{pid}/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1])
    except (PermissionError, FileNotFoundError, ProcessLookupError):
        return None
    return None


def main():
    print('=== STEP 1: PRE-CHECK ===')
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    for old_frame in DUMP_DIR.glob('frame_*.ppm'):
        old_frame.unlink()

    env = os.environ.copy()
    env['AAAS_FRAME_DUMP_DIR'] = str(DUMP_DIR)
    env['AAAS_FRAME_DUMP_EVERY'] = '1'  # capture every frame to inspect exact Settings first-draw

    print('=== STEP 2: LAUNCHING FOREGROUND SESSION ===')
    start_time = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / 'scripts/run_aaas.py'), '--startup-timeout', '90'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    session_dir = None
    states = []
    running_reached = False
    startup_duration = 0.0

    # Read output lines until RUNNING or exit
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        line_str = line.strip()
        print(f'[run_aaas] {line_str}')

        if 'AaaS: ' in line_str and '(' in line_str and ')' in line_str:
            parts = line_str.split('AaaS: ')[1].split(' (')
            st = parts[0].strip()
            sdir = parts[1].split(')')[0].strip()
            states.append(st)
            if not session_dir and sdir:
                session_dir = Path(sdir)

        if 'Settings process started.' in line_str or 'AaaS: RUNNING' in line_str:
            running_reached = True
            startup_duration = time.monotonic() - start_time
            print(f'=== STEP 3: SESSION REACHED RUNNING IN {startup_duration:.2f}s ===')
            break

        if proc.poll() is not None:
            break

    if not running_reached:
        print('ERROR: Session failed to reach RUNNING state!', file=sys.stderr)
        rem, _ = proc.communicate(timeout=10)
        print(rem, file=sys.stderr)
        sys.exit(1)

    # Let the session run for 20 seconds while monitoring
    print('=== STEP 4: MONITORING RUNNING SESSION FOR 20 SECONDS ===')
    time.sleep(5)

    # Sample resource snapshots
    settings_pids = get_pids_for('com.android.settings')
    sf_pids = get_pids_for('surfaceflinger')
    ss_pids = get_pids_for('system_server')
    presenter_pids = get_pids_for('wayland-host-presenter')

    resource_snapshot = {
        'timestamp': time.time(),
        'settings': [{'pid': p, 'rss_kib': get_rss_kib(p), 'fds': get_fd_count(p)} for p in settings_pids],
        'surfaceflinger': [{'pid': p, 'rss_kib': get_rss_kib(p), 'fds': get_fd_count(p)} for p in sf_pids],
        'system_server': [{'pid': p, 'rss_kib': get_rss_kib(p), 'fds': get_fd_count(p)} for p in ss_pids],
        'presenter': [{'pid': p, 'rss_kib': get_rss_kib(p), 'fds': get_fd_count(p)} for p in presenter_pids],
    }
    print(f'Resource snapshot: {json.dumps(resource_snapshot, indent=2)}')

    time.sleep(15)

    total_running_time = time.monotonic() - start_time
    print(f'Session alive for {total_running_time:.2f}s total. Stopping via SIGINT...')

    # Send SIGINT (Ctrl+C equivalent)
    print('=== STEP 5: SENDING SIGINT (CTRL+C) ===')
    proc.send_signal(signal.SIGINT)

    # Read remaining stdout until completion
    remaining_out, _ = proc.communicate(timeout=20)
    for l in remaining_out.splitlines():
        print(f'[run_aaas] {l}')
        if 'AaaS: ' in l and '(' in l and ')' in l:
            parts = l.split('AaaS: ')[1].split(' (')
            states.append(parts[0].strip())

    returncode = proc.returncode
    print(f'run_aaas exit code: {returncode}')

    # Verify cleanup
    print('=== STEP 6: VERIFYING CLEANUP ===')
    time.sleep(2)
    leftover_bwrap = get_pids_for('bwrap')
    leftover_presenter = get_pids_for('wayland-host-presenter')
    leftover_zygote = get_pids_for('test_zygote')
    print(f'Leftover bwrap: {leftover_bwrap}')
    print(f'Leftover presenter: {leftover_presenter}')
    print(f'Leftover zygote: {leftover_zygote}')

    sock_exists = (session_dir / 'ipc/wayland.sock').exists() if session_dir else False
    print(f'Socket exists after stop: {sock_exists}')

    # Frame dump analysis
    dumped_frames = sorted(DUMP_DIR.glob('frame_*.ppm'), key=lambda p: int(p.stem.split('_')[1]))
    print(f'Total dumped frames: {len(dumped_frames)}')

    latest_ppm = None
    latest_png = None
    if dumped_frames:
        latest_ppm = dumped_frames[-1]
        print(f'Latest dumped frame: {latest_ppm}')
        # Convert to PNG using ffmpeg or convert or python PIL
        png_path = ROOT / 'artifacts/m1b84_gemini_settings_repro.png'
        try:
            subprocess.run(['ffmpeg', '-y', '-i', str(latest_ppm), str(png_path)], check=True, capture_output=True)
            print(f'Converted latest frame to {png_path}')
            latest_png = str(png_path)
        except Exception as e:
            print(f'Warning: failed to convert PPM to PNG: {e}')

    # Read presenter log summary
    presenter_summary = None
    if session_dir and (session_dir / 'presenter.log').exists():
        for line in (session_dir / 'presenter.log').read_text(errors='replace').splitlines():
            if '"event":"summary"' in line:
                try:
                    presenter_summary = json.loads(line)
                except Exception:
                    pass

    # Read LMKD logcat entries
    lmkd_logs = []
    if session_dir and (session_dir / 'logcat.log').exists():
        for line in (session_dir / 'logcat.log').read_text(errors='replace').splitlines():
            if 'lowmemorykiller' in line or 'lmkd' in line.lower():
                lmkd_logs.append(line)

    results = {
        'session_dir': str(session_dir) if session_dir else None,
        'startup_duration_seconds': startup_duration,
        'total_duration_seconds': total_running_time,
        'states': states,
        'exit_code': returncode,
        'socket_removed': not sock_exists,
        'leftover_processes': {
            'bwrap': leftover_bwrap,
            'presenter': leftover_presenter,
            'zygote': leftover_zygote,
        },
        'frames_dumped_count': len(dumped_frames),
        'latest_frame_ppm': str(latest_ppm) if latest_ppm else None,
        'latest_frame_png': latest_png,
        'resource_snapshot': resource_snapshot,
        'presenter_summary': presenter_summary,
        'lmkd_log_sample': lmkd_logs[:25],
    }

    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text(json.dumps(results, indent=2))
    print(f'Summary written to {OUT_SUMMARY}')


if __name__ == '__main__':
    main()

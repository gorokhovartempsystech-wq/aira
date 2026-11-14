"""Check installed release startup in a disposable Windows runner profile."""
import argparse
import json
import os
import subprocess
import shutil
import sys
from uuid import uuid4
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument('installation', type=Path)
    parser.add_argument('--runs', type=int, choices=[1,2], default=1)
    args = parser.parse_args()
    app = args.installation.resolve(strict=True)
    # Match the inherited ACL of a real LOCALAPPDATA parent. A private mkdtemp
    # parent can prevent PostgreSQL's restricted Windows token from traversing it.
    profile = Path(os.environ['LOCALAPPDATA']) / ('aira-release-smoke-' + uuid4().hex)
    profile.mkdir()
    child_env = dict(os.environ, AIRA_SELFTEST='12', LOCALAPPDATA=str(profile))
    log = profile / 'AIRA/logs/aira.log'
    assert not log.exists(), 'Smoke requires a fresh disposable runner profile'
    command = [str(app/'python/python.exe'), '-s', '-E', str(app/'launcher/aira_launcher.pyw')]
    succeeded = False
    try:
        for attempt in range(args.runs):
            offset = log.stat().st_size if log.exists() else 0
            child = subprocess.Popen(command, env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                code = child.wait(timeout=120)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                raise RuntimeError('Desktop smoke timed out') from None
            assert code == 0
            lines = log.read_bytes()[offset:].decode('utf-8').splitlines()
            records = [json.loads(line.split('selftest page:',1)[1].strip()) for line in lines if 'selftest page:' in line]
            print('Native page observations:', json.dumps(records), flush=True)
            if len(records) != 1 or not records[0].get('activation') or not records[0].get('bridge'):
                # This is a fresh synthetic runner profile; no license key was entered.
                print('Synthetic startup log tail:', '\n'.join(lines[-70:]), flush=True)
            assert len(records) == 1 and records[0]['activation'] is True and records[0]['bridge'] is True
            assert records[0]['licence'] is True and records[0]['app'] is False
            print('Installed Windows release started native WebView and activation screen.')
        succeeded = True
    finally:
        subprocess.run(command+['--stop-db'], env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        if log.exists():
            if not succeeded:
                print('Synthetic startup diagnostic tail:', '\n'.join(log.read_text(encoding='utf-8').splitlines()[-100:]), flush=True)
            destination = Path(os.environ['RUNNER_TEMP']) / 'AIRA-smoke.log'
            with destination.open('ab') as output: output.write(log.read_bytes())
        shutil.rmtree(profile)


if __name__ == '__main__':main()

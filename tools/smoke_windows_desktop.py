"""Check installed release startup in a disposable Windows runner profile."""
import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('installation', type=Path)
    args = parser.parse_args()
    app = args.installation.resolve(strict=True)
    child_env = dict(os.environ, AIRA_SELFTEST='12')
    log = Path(os.environ['LOCALAPPDATA']) / 'AIRA/logs/aira.log'
    assert not log.exists(), 'Smoke requires a fresh disposable runner profile'
    command = [str(app/'python/python.exe'), '-s', '-E', str(app/'launcher/aira_launcher.pyw')]
    child = subprocess.Popen(command, env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        try:
            code = child.wait(timeout=120)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            raise RuntimeError('Desktop smoke timed out') from None
        assert code == 0
        lines = log.read_text(encoding='utf-8').splitlines()
        records = [json.loads(line.split('selftest page:',1)[1].strip()) for line in lines if 'selftest page:' in line]
        assert len(records) == 1 and records[0]['activation'] is True and records[0]['bridge'] is True
        assert records[0]['licence'] is True and records[0]['app'] is False
        print('Installed Windows release started native WebView and activation screen.')
    finally:
        subprocess.run(command+['--stop-db'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)


if __name__ == '__main__':main()

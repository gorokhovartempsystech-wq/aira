"""Disposable Windows owner diagnostics; numbers only, no operator data."""
import ctypes as c
import gc
import json
import runpy
import tempfile
from pathlib import Path

from ara.docx_analysis_worker import windows as w
from ara.docx_analysis_worker.windows._paths import _load_filesystem


def main():
    helper = runpy.run_path(str(Path(__file__).parents[1] / 'app/backend/tests/acceptance/test_docx_analysis_windows_primitives.py'))
    records = []
    with tempfile.TemporaryDirectory(prefix='aira-native-probe-') as temp:
        root = helper['native_root'].__wrapped__(None, Path(temp))
        kernel = _load_filesystem().native.kernel
        read = kernel.GetProcessHandleCount
        read.argtypes, read.restype = [c.c_void_p, c.POINTER(c.c_uint32)], c.c_int32
        def record(phase):
            count = c.c_uint32();assert read(kernel.GetCurrentProcess(), c.byref(count))
            records.append({'phase': phase, 'handles': count.value})
        record('baseline')
        for cycle in range(3):
            owner = w.acquire_owner(root);record(f'owner-{cycle}')
            try:
                try:w.acquire_owner(root)
                except w.WindowsRuntimeError as error:assert error.code == 'runtime_busy'
                record(f'conflict-{cycle}')
                w.WindowsClock().now_ns();record(f'clock-{cycle}')
                for _ in range(100):assert owner.release_slot(owner.reserve_slot())
                record(f'slots-{cycle}')
            finally:owner.close()
            gc.collect();record(f'closed-{cycle}')
    print(json.dumps(records))


if __name__ == '__main__':main()

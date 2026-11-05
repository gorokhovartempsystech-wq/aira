"""Private fixed-role entry boundary. Integers are never a parent-facing factory."""

import ctypes as c
import json
import sys
from pathlib import Path
from uuid import UUID

from ..wire import WireBinding
from ._abi import DWORD
from ._errors import WindowsRuntimeError
from ._handles import OwnedHandle, valid_handle
from ._pipes import _ISSUE, PipeEndpoint

MODES = frozenset(
    (
        "success",
        "review",
        "review2",
        "local_model",
        "wait",
        "native_hang",
        "result_hang",
        "nonzero",
        "tail",
        "error",
        "diagnostic_flood",
        "early_exit",
        "prepared_missing",
        "prepared_extra",
        "exit_259",
        "exit_ntstatus",
    )
)
G_ROLES = {
    "control": "read",
    "status": "write",
    "armed": "write",
    "request": "read",
    "events": "write",
    "slot": "disk",
    "ordinary": "event",
    "hard": "event",
    "stdin": "char",
    "stdout": "char",
}
M_ROLES = {
    "request": "read",
    "events": "write",
    "slot": "disk",
    "prepared": "write",
    "gate": "read",
    "diagnostics": "sync",
    "stdin": "char",
}


def config(role, binding, deadline, lease, mode, handles):
    return {
        "role": role,
        "run": str(binding.run_id),
        "attempt": str(binding.attempt_id),
        "deadline": str(deadline),
        "lease": str(lease),
        "mode": mode,
        "handles": handles,
    }


def launch_config(role, binding, deadline, lease, mode, handles, api):
    entry = Path(__file__).with_name("_guardian_entry.py" if role == "G" else "_child_entry.py")
    location = str(entry.parent)
    system = api.windows_directory()
    payload = json.dumps(
        config(role, binding, deadline, lease, mode, handles), separators=(",", ":")
    )
    return (
        str(Path(sys.executable).resolve()),
        [str(Path(sys.executable).resolve()), "-I", "-B", str(entry.resolve()), payload],
        location,
        {"SystemRoot": system, "WINDIR": system},
    )


def parse(raw, role):
    try:
        if type(raw) is not str or len(raw) > 16384:
            raise ValueError()

        def unique(pairs):
            result = {}
            for k, v in pairs:
                if k in result:
                    raise ValueError()
                result[k] = v
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        if type(value) is not dict or set(value) != {
            "role",
            "run",
            "attempt",
            "deadline",
            "lease",
            "mode",
            "handles",
        }:
            raise ValueError()
        if value["role"] != role or value["mode"] not in MODES:
            raise ValueError()
        binding = WireBinding(UUID(value["run"]), UUID(value["attempt"]))
        if str(binding.run_id) != value["run"] or str(binding.attempt_id) != value["attempt"]:
            raise ValueError()
        d, lease_value = int(value["deadline"]), int(value["lease"])
        if (
            str(d) != value["deadline"]
            or str(lease_value) != value["lease"]
            or not 0 < lease_value <= d < 2**63
        ):
            raise ValueError()
        roles, handles = G_ROLES if role == "G" else M_ROLES, value["handles"]
        if type(handles) is not dict or handles.keys() != roles.keys():
            raise ValueError()
        if not all(valid_handle(h) and h < 2**63 for h in handles.values()):
            raise ValueError()
        if len(set(handles.values())) != len(handles):
            raise ValueError()
        return binding, d, lease_value, value["mode"], handles
    except Exception:
        raise WindowsRuntimeError("runtime_unavailable") from None


def adopt(api, handles, role):
    roles = G_ROLES if role == "G" else M_ROLES
    result = {}
    # Fixed table was fully validated before taking ownership of any integer.
    for name, kind in roles.items():
        handle = handles[name]
        flags = DWORD()
        api.require(api.kernel.GetHandleInformation(handle, c.byref(flags)))
        api.clear_inherit(handle)
        expected = {"read": 3, "write": 3, "sync": 3, "disk": 1, "char": 2}.get(kind)
        if expected is not None:
            api.require(api.kernel.GetFileType(handle) == expected)
        if kind in ("read", "write", "sync"):
            pipe = DWORD()
            api.require(api.kernel.GetNamedPipeInfo(handle, c.byref(pipe), None, None, None))
            api.require(bool(pipe.value & 1) == (kind == "read") and not pipe.value & 4)
        owned = OwnedHandle(api, handle)
        result[name] = (
            PipeEndpoint(
                _ISSUE, api.io, owned, "read" if kind == "read" else "write", kind == "sync"
            )
            if kind in ("read", "write", "sync")
            else owned
        )
    return result


def entry(role, raw):
    from ._process_abi import _load_api

    binding, d, lease_value, mode, handles = parse(raw, role)
    api = _load_api()
    inherited = adopt(api, handles, role)
    if role == "G":
        from ._guardian import run
    else:
        from ._child_bootstrap import run
    code = run(api, inherited, binding, d, lease_value, mode)
    # Process exit is the final safety net for entry-owned handles on a failed path.
    # No payload or native exception text is written to diagnostics.
    return code

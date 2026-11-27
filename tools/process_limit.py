"""Run a subprocess with a watchdog memory ceiling and timeout."""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes


if os.name == "nt":
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def working_set(process) -> int:
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(process._handle, ctypes.byref(counters), counters.cb):
        raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
    return counters.WorkingSetSize


def kill_tree(process):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                   capture_output=True, timeout=10)


def run(args, timeout: int, memory_mb: int = 8192) -> subprocess.CompletedProcess:
    if os.name != "nt":
        return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace")
    started = time.monotonic()
    limited = False
    try:
        while process.poll() is None:
            if working_set(process) > memory_mb * 1024 * 1024:
                limited = True
                kill_tree(process)
                break
            if time.monotonic() - started > timeout:
                kill_tree(process)
                stdout, stderr = process.communicate()
                stderr = (stderr or "") + f"\ntimeout {timeout}s"
                return subprocess.CompletedProcess(args, -9, stdout, stderr)
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                if limited:
                    stderr = (stderr or "") + f"\nmemory limit {memory_mb} MiB exceeded"
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                pass
        stdout, stderr = process.communicate()
        if limited:
            stderr = (stderr or "") + f"\nmemory limit {memory_mb} MiB exceeded"
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    finally:
        if process.poll() is None:
            kill_tree(process)

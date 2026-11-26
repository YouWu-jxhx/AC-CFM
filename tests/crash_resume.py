"""Force-stop a disposable MATLAB batch, then verify resume on Windows."""

import argparse
import csv
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def launch(matlab, output, name):
    target = str(output).replace("'", "''")
    expression = (
        f"fid=fopen(fullfile('{target}','{name}.pid'),'w');"
        "fprintf(fid,'%d',feature('getpid'));fclose(fid);"
        "cfg=accfmlab.config();"
        f"cfg.output_dir='{target}';"
        "faults=[accfmlab.fault(),accfmlab.fault(9),accfmlab.fault(1)];"
        "accfmlab.batch(cfg,accfmlab.scenarios(faults,cfg.seed));"
    )
    # -wait keeps the launcher alive as the parent of the MATLAB worker.
    with (output / name).open("wb") as log:
        return subprocess.Popen(
            [matlab, "-wait", "-sd", str(ROOT), "-batch", expression],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def terminate(process, pid_file, matlab):
    if process.poll() is not None:
        raise RuntimeError("The test launcher already exited.")
    if not pid_file.is_file():
        process.terminate()
        return process.wait(timeout=30)
    pid = int(pid_file.read_text(encoding="ascii"))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    )
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000 | 0x0001, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        executable = Path(image.value).resolve()
        bin_dir = Path(matlab).resolve().parent
        checked(executable.name.lower() == "matlab.exe" and executable.is_relative_to(bin_dir),
                f"The self-reported test PID has an unexpected executable: {executable}")
        if not kernel.TerminateProcess(handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)
    return process.wait(timeout=30)


def hashes(folder):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.iterdir() if path.is_file()}


def checked(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(matlab, output):
    output.mkdir(parents=True, exist_ok=False)
    first = output / "scenario_000001"
    second = output / "scenario_000002"
    third = output / "scenario_000003"
    interrupted = launch(matlab, output, "interrupted-matlab.log")
    try:
        deadline = time.monotonic() + 240
        while not first.is_dir():
            checked(interrupted.poll() is None, "MATLAB exited before the first commit.")
            checked(time.monotonic() < deadline, "Timed out waiting for the first commit.")
            time.sleep(0.05)
        checked(not second.exists(), "Second scenario had already committed before interruption.")
        original = hashes(first)
        code = terminate(interrupted, output / "interrupted-matlab.log.pid", matlab)
        checked(code != 0, "The interrupted process returned a success status.")
        checked(not second.exists() and not third.exists(), "The kill did not leave a partial batch.")
        checked(hashes(first) == original and len(original) == 6, "First commit changed after the kill.")
        print("PASS forced termination of the dedicated MATLAB worker left one complete scenario", flush=True)
    finally:
        if interrupted.poll() is None:
            terminate(interrupted, output / "interrupted-matlab.log.pid", matlab)

    resumed = launch(matlab, output, "resumed-matlab.log")
    try:
        checked(resumed.wait(timeout=240) == 0, "MATLAB resume failed. See resumed-matlab.log.")
    finally:
        if resumed.poll() is None:
            terminate(resumed, output / "resumed-matlab.log.pid", matlab)
    checked(hashes(first) == original, "Resume rewrote the committed scenario.")
    with (output / "summary.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    checked([int(row["scenario_id"]) for row in rows] == [1, 2, 3], "Missing or repeated rows.")
    checked(all(row["status"] == "completed_model" for row in rows), "Unexpected run status.")
    for row, expected in zip(rows, [0, 0.554525932526224, 0]):
        checked(abs(float(row["ls_total"]) - expected) < 1e-7, "Changed reference loss fraction.")
    subprocess.run([sys.executable, str(ROOT / "python/read_run.py"), first, second, third],
                   check=True)
    print("ACCFMLAB_CRASH_RESUME_PASSED", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="A new directory for this test.")
    parser.add_argument("--matlab", required=True, help="Absolute path to bin/matlab.exe.")
    args = parser.parse_args()
    checked(os.name == "nt", "This process-tree test requires Windows.")
    run(args.matlab, args.output.resolve())


if __name__ == "__main__":
    main()

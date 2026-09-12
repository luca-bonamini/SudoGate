import pathlib
import subprocess

LIST_FORMAT = "#{session_name}\t#{session_path}"


def tmux_sessions(runner=None):
    runner = runner or subprocess.run
    try:
        completed = runner(
            ["tmux", "list-sessions", "-F", LIST_FORMAT],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0:
        return {}
    found = {}
    for line in (completed.stdout or "").splitlines():
        if "\t" not in line:
            continue
        name, path = line.split("\t", 1)
        if name and path:
            found[name] = path
    return found


def label_for_cwd(cwd, sessions):
    current = pathlib.PurePosixPath(cwd)
    best_name = None
    best_len = -1
    for name, path in sessions.items():
        candidate = pathlib.PurePosixPath(path)
        if current == candidate or candidate in current.parents:
            if len(str(candidate)) > best_len:
                best_name, best_len = name, len(str(candidate))
    if best_name:
        return best_name.removeprefix("rc-")
    return current.name

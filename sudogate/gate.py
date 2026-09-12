"""Command classification for the gate.

contains_sudo spots privilege escalation in command position, ignoring the
sudogate shim itself and the word used as an argument. is_destructive decides
whether a command needs the TOTP second factor. compose_command turns the
shim's argv back into the command that will be recorded and run.
"""
import re
import shlex


def compose_command(argv):
    """Join argv into a shell command, preserving quoting.

    A plain " ".join drops the quotes, so `sudogate bash -c 'a; b'` would be
    recorded as `bash -c a; b`: the wrapper shell would then run the tail as
    a separate command, and what runs would not be what was approved.
    """
    return shlex.join(argv).strip()

# Escalation at the start of the command or after a shell separator, but not
# the sudogate shim (preceded by "-") nor the bare word used as an argument.
_SUDO_RE = re.compile(r"(^|[;&|(\n]\s*)sudo\b")

# Body of a heredoc: <<EOF ... EOF, <<'EOF' ... EOF, <<-"EOF" ... EOF.
_HEREDOC_RE = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1.*?^\s*\2\s*$",
    re.DOTALL | re.MULTILINE,
)


def strip_heredocs(command):
    """Strip heredoc bodies from a shell command.

    The hook payload carries the whole command, heredocs included. Without
    this, writing a file that merely *mentions* a privileged command would be
    mistaken for an attempt to run one. The opening delimiter is kept, so the
    structure of the line that opens the heredoc is not lost.
    """
    return _HEREDOC_RE.sub("<<STRIPPED", command or "")


def contains_sudo(command):
    return _SUDO_RE.search(strip_heredocs(command)) is not None


def is_destructive(command, patterns):
    command = strip_heredocs(command)
    for pattern in patterns:
        if re.search(pattern, command):
            return True
    return False

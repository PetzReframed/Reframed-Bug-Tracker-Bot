"""The game server's report folder, read only.

The server (Petz5Reframed, server/shared/crash_reports.py) stores each accepted report under a receipt name,
<UTC time>-<code>-<24 hex digits>, where the code is RF-XXXXXXXX for a crash report and BUG-XXXXXXXX for a bug report
a player wrote:

- a report without attachments is one file, <receipt>.log;
- a report with attachments is a folder <receipt>/ holding <receipt>.log and, when sent, <receipt>.png (a screenshot)
  and <receipt>.zip (the player's saved data). The folder appears complete, by one rename.

The text ends with the lines "Server receipt: <receipt>" and "Server build: <id>", written last; a .log without them
is still being written. Nothing here writes to the folder: the server refuses new reports when it finds an entry it
does not know.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re

RECEIPT = re.compile(r'(\d{8}T\d{6}\.\d{6}Z)-((RF|BUG)-[0-9A-F]{8})-[0-9a-f]{24}')
KINDS = {'RF': 'Crash report', 'BUG': 'Bug report'}
# The server's own ceiling for a report's text (PETZ_CRASH_REPORT_MAX_BYTES) plus its two closing lines.
MAX_TEXT_BYTES = 262144 + 512


@dataclass(frozen=True)
class Report:
    receipt: str
    code: str
    kind: str
    received: datetime
    text: str
    log: Path
    screenshot: Path | None
    saved_data: Path | None


def receipts(directory: Path) -> list[str]:
    """The receipts present in the folder, oldest first (a receipt starts with its time)."""
    found = []
    with os.scandir(directory) as entries:
        for entry in entries:
            name = entry.name[:-4] if entry.name.endswith('.log') else entry.name
            if RECEIPT.fullmatch(name) and (entry.is_file(follow_symlinks=False) if entry.name.endswith('.log')
                                            else entry.is_dir(follow_symlinks=False)):
                found.append(name)
    return sorted(found)


def read_report(directory: Path, receipt: str) -> Report | None:
    """The stored report, or None while its text is incomplete or it has gone. Links are never followed."""
    match = RECEIPT.fullmatch(receipt)
    if not match:
        return None
    folder = directory / receipt
    bundle = folder.is_dir() and not folder.is_symlink()
    base = folder if bundle else directory
    log = base / (receipt + '.log')

    def regular(path):
        return path if path.is_file() and not path.is_symlink() else None

    if regular(log) is None:
        return None
    try:
        if log.stat().st_size > MAX_TEXT_BYTES:
            return None
        text = log.read_bytes().decode('utf-8', 'replace')
    except OSError:
        return None
    lines = text.rstrip('\n').split('\n')
    if len(lines) < 2 or lines[-2] != 'Server receipt: ' + receipt or not lines[-1].startswith('Server build: '):
        return None
    received = datetime.strptime(match[1], '%Y%m%dT%H%M%S.%fZ').replace(tzinfo=timezone.utc)
    return Report(receipt, match[2], KINDS[match[3]], received, text, log,
                  regular(base / (receipt + '.png')) if bundle else None,
                  regular(base / (receipt + '.zip')) if bundle else None)

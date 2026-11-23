"""Posts each report of the game server's folder once, and remembers which were posted."""
import json
import logging
import os
from pathlib import Path
import time

from .config import Config
from .discord import MESSAGE_LIMIT, DiscordError, post_message
from .reports import Report, read_report, receipts

LOG = logging.getLogger('bug-tracker-bot')
STATE_FILE = 'posted.json'


def load_posted(state_dir: Path) -> set[str] | None:
    """The receipts already posted; None when nothing was ever recorded (a first start)."""
    try:
        return set(json.loads((state_dir / STATE_FILE).read_text(encoding='utf-8'))['posted'])
    except FileNotFoundError:
        return None


def save_posted(state_dir: Path, posted: set[str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    pending = state_dir / (STATE_FILE + '.tmp')
    pending.write_text(json.dumps({'posted': sorted(posted)}), encoding='utf-8')
    os.replace(pending, state_dir / STATE_FILE)


def message_text(report: Report, notes: list[str]) -> str:
    """The message: what it is, when the server received it, and the start of its text in a code block."""
    head = f'**{report.kind}** `{report.code}` received <t:{int(report.received.timestamp())}:f>'
    for note in notes:
        head += '\n' + note
    # The report's first line is its title and the second its code, both said above. A code block cannot be
    # closed from inside: its three-backtick marker is broken up.
    excerpt = '\n'.join(report.text.split('\n')[2:]).strip().replace('```', "'''")
    room = MESSAGE_LIMIT - len(head) - len('\n```\n\n```')
    if len(excerpt) > room:
        excerpt = excerpt[:room - 2].rstrip() + '\n…'
    return head + '\n```\n' + excerpt + '\n```' if excerpt else head


def attachments(report: Report, config: Config) -> tuple[list[tuple[str, bytes]], list[str]]:
    """The files to upload (the full text first) and a line for each stored file that is left out."""
    files, notes = [(report.code + '.log', report.log.read_bytes())], []
    for path, wanted, name, label in ((report.screenshot, config.attach_screenshot, report.code + '.png', 'screenshot'),
                                      (report.saved_data, config.attach_saved_data, report.code + '-saved-data.zip', 'saved data')):
        if path is None:
            continue
        if not wanted:
            notes.append(f'A {label} file is kept on the server.')
        elif path.stat().st_size > config.max_file_bytes:
            notes.append(f'The {label} file is too large to upload; it is kept on the server.')
        else:
            files.append((name, path.read_bytes()))
    return files, notes


def post_report(report: Report, config: Config, send=post_message) -> None:
    files, notes = attachments(report, config)
    try:
        send(config.token, config.channel_id, message_text(report, notes), files)
    except DiscordError as error:
        if not error.too_large or len(files) == 1:
            raise
        # Discord refused the upload's size: the text alone, and a line saying what stayed behind.
        notes.append('The attached files are too large for this channel; they are kept on the server.')
        send(config.token, config.channel_id, message_text(report, notes), files[:1])


def run_once(config: Config, posted: set[str] | None, send=post_message) -> set[str]:
    """One pass over the folder. Answers the receipts posted so far, limited to those still stored."""
    present = receipts(config.reports_dir)
    if posted is None:
        # A first start: reports stored before the bot existed are not announced unless asked for.
        posted = set() if config.post_existing else set(present)
        if not config.post_existing and present:
            LOG.info('First start: %d stored reports are taken as known and not posted', len(present))
        save_posted(config.state_dir, posted)
    posted &= set(present)
    for receipt in present:
        if receipt in posted:
            continue
        try:
            report = read_report(config.reports_dir, receipt)
            if report is None:
                continue  # Still being written; the next pass looks again.
            post_report(report, config, send)
        except OSError as error:
            LOG.warning('Report %s could not be read: %s', receipt, error.strerror or type(error).__name__)
            continue
        except DiscordError as error:
            LOG.warning('Report %s was not posted: %s', receipt, error)
            if error.retry_after:
                time.sleep(min(error.retry_after, 60))
            break  # Keep the order: this report is tried again on the next pass.
        posted.add(receipt)
        save_posted(config.state_dir, posted)
        LOG.info('Posted %s', receipt)
    return posted


def run(config: Config) -> None:
    LOG.info('Watching %s every %d seconds', config.reports_dir, config.poll_seconds)
    posted = load_posted(config.state_dir)
    warned = False
    while True:
        try:
            posted = run_once(config, posted)
            warned = False
        except OSError as error:
            if not warned:
                LOG.warning('The report folder %s cannot be read: %s', config.reports_dir, error.strerror or type(error).__name__)
                warned = True
        time.sleep(config.poll_seconds)

"""Settings, read from the process environment (Docker's env_file supplies them from .env)."""
from dataclasses import dataclass
import os
from pathlib import Path
import re

# Discord accepts files up to this size from a bot in a server without boosts.
DISCORD_FILE_LIMIT = 10 * 1024 * 1024


@dataclass(frozen=True)
class Config:
    token: str
    channel_id: str
    reports_dir: Path
    state_dir: Path
    poll_seconds: int
    post_existing: bool
    attach_screenshot: bool
    attach_saved_data: bool
    max_file_bytes: int


def load_config(environ=None) -> Config:
    """The settings, or ValueError naming the first one that is missing or invalid. The token is never echoed."""
    values = os.environ if environ is None else environ

    def text(key, default=''):
        return values.get(key, default).strip()

    def boolean(key, default):
        value = text(key, default).lower()
        if value not in ('true', 'false'):
            raise ValueError(f'{key} must be true or false')
        return value == 'true'

    def integer(key, default, low, high):
        value = text(key, str(default))
        if not re.fullmatch(r'[0-9]{1,10}', value) or not low <= int(value) <= high:
            raise ValueError(f'{key} must be an integer from {low} to {high}')
        return int(value)

    token = text('DISCORD_BOT_TOKEN')
    if not token or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('DISCORD_BOT_TOKEN must be set to the bot token of the Discord application')
    channel_id = text('DISCORD_CHANNEL_ID')
    if not re.fullmatch(r'[0-9]{15,22}', channel_id):
        raise ValueError('DISCORD_CHANNEL_ID must be the numeric ID of the channel to post in')
    return Config(
        token, channel_id,
        Path(text('REPORTS_DIR', '/reports')), Path(text('STATE_DIR', '/state')),
        integer('POLL_SECONDS', 15, 5, 3600),
        boolean('POST_EXISTING', 'false'),
        boolean('ATTACH_SCREENSHOT', 'true'), boolean('ATTACH_SAVED_DATA', 'true'),
        integer('MAX_FILE_BYTES', DISCORD_FILE_LIMIT, 1024, 524288000))

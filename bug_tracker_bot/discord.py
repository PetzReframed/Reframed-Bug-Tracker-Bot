"""One call of Discord's HTTP API: create a message with files in a channel. No gateway connection is needed."""
import json
import secrets
import urllib.error
import urllib.request

API = 'https://discord.com/api/v10'
USER_AGENT = 'DiscordBot (https://github.com/PetzReframed/Reframed-Bug-Tracker-Bot, 1.0)'
MESSAGE_LIMIT = 2000


class DiscordError(Exception):
    """status: the HTTP status (0: no answer). retry_after: seconds to wait first, when Discord said so."""
    def __init__(self, status, message, retry_after=None):
        self.status, self.retry_after = status, retry_after
        super().__init__(message)

    @property
    def too_large(self):
        return self.status == 413

    @property
    def permanent(self):
        # The token, the channel or the bot's permissions are wrong: sending again as it is cannot succeed.
        return self.status in (400, 401, 403, 404)


def multipart(payload: dict, files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """The request body and its Content-Type: payload_json, then files[n] in order."""
    boundary = 'bug-tracker-' + secrets.token_hex(16)
    payload = {**payload, 'attachments': [{'id': index, 'filename': name} for index, (name, _) in enumerate(files)]}
    parts = [b'--' + boundary.encode() + b'\r\nContent-Disposition: form-data; name="payload_json"\r\n'
             b'Content-Type: application/json\r\n\r\n' + json.dumps(payload).encode('utf-8') + b'\r\n']
    for index, (name, data) in enumerate(files):
        parts.append(b'--' + boundary.encode() + b'\r\nContent-Disposition: form-data; name="files[%d]"; filename="%s"\r\n'
                     b'Content-Type: application/octet-stream\r\n\r\n' % (index, name.encode('ascii')) + data + b'\r\n')
    parts.append(b'--' + boundary.encode() + b'--\r\n')
    return b''.join(parts), 'multipart/form-data; boundary=' + boundary


def post_message(token: str, channel_id: str, content: str, files: list[tuple[str, bytes]], *,
                 opener=urllib.request.urlopen, timeout=60) -> str:
    """Posts the message and answers its ID. The text can mention nobody, whatever it contains."""
    body, content_type = multipart({'content': content[:MESSAGE_LIMIT], 'allowed_mentions': {'parse': []}}, files)
    request = urllib.request.Request(f'{API}/channels/{channel_id}/messages', data=body, method='POST', headers={
        'Authorization': 'Bot ' + token, 'Content-Type': content_type, 'User-Agent': USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            return str(json.loads(response.read()).get('id', ''))
    except urllib.error.HTTPError as error:
        retry_after = None
        try:
            answer = json.loads(error.read(65536))
            message = str(answer.get('message', ''))[:200]
            if error.code == 429:
                retry_after = float(answer.get('retry_after', 5))
        except (ValueError, OSError, AttributeError):
            message = ''
        raise DiscordError(error.code, f'Discord answered {error.code}' + (': ' + message if message else ''), retry_after) from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise DiscordError(0, 'Discord could not be reached: ' + type(error).__name__) from None

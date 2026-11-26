"""The bot against a report folder made here, as the game server writes one, and a stand-in for Discord."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from bug_tracker_bot.config import load_config
from bug_tracker_bot.discord import DiscordError, multipart, post_message
from bug_tracker_bot.reports import read_report, receipts
from bug_tracker_bot.tracker import load_posted, message_text, run_once

ENV = {'DISCORD_BOT_TOKEN': 'token.for-tests', 'DISCORD_CHANNEL_ID': '123456789012345678'}
CRASH = '20261123T101500.000001Z-RF-1A2B3C4D-0123456789abcdef01234567'
BUG = '20261123T101600.000002Z-BUG-00C0FFEE-89abcdef0123456789abcdef'
RECOVERED = '20261123T101700.000003Z-ERR-0BADF00D-456789abcdef0123456789ab'
TITLES = {'RF': 'Petz 5 Reframed error report', 'BUG': 'Petz 5 Reframed bug report', 'ERR': 'Petz 5 Reframed recovered error report'}


def text_of(receipt, body='Area: Family Room\nMessage: something failed'):
    code = receipt.split('Z-', 1)[1].rsplit('-', 1)[0]
    return f'{TITLES[code.split("-")[0]]}\nCode: {code}\n{body}\n\nServer receipt: {receipt}\nServer build: 0123456789abcdef0123\n'


def store(folder, receipt, *, screenshot=None, saved=None, text=None):
    """One report as the server stores it: a .log file, or a folder when it has attachments."""
    text = text_of(receipt) if text is None else text
    if screenshot is None and saved is None:
        (folder / (receipt + '.log')).write_text(text, encoding='utf-8', newline='\n')
        return
    bundle = folder / receipt
    bundle.mkdir()
    (bundle / (receipt + '.log')).write_text(text, encoding='utf-8', newline='\n')
    if screenshot is not None:
        (bundle / (receipt + '.png')).write_bytes(screenshot)
    if saved is not None:
        (bundle / (receipt + '.zip')).write_bytes(saved)


class Folder(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.reports, self.state = Path(temp.name) / 'reports', Path(temp.name) / 'state'
        self.reports.mkdir()
        self.sent = []

    def config(self, **extra):
        return load_config({**ENV, 'REPORTS_DIR': str(self.reports), 'STATE_DIR': str(self.state), **extra})

    def send(self, token, channel, content, files):
        self.sent.append((channel, content, [(name, len(data)) for name, data in files]))
        return '1'


class ConfigTests(unittest.TestCase):
    def test_the_token_and_the_channel_are_required_and_the_rest_has_defaults(self):
        config = load_config(ENV)
        self.assertEqual((config.reports_dir, config.state_dir, config.poll_seconds, config.post_existing,
                          config.attach_screenshot, config.attach_saved_data, config.max_file_bytes),
                         (Path('/reports'), Path('/state'), 15, False, True, True, 10485760))
        for changed, word in (({'DISCORD_BOT_TOKEN': ''}, 'DISCORD_BOT_TOKEN'), ({'DISCORD_CHANNEL_ID': 'general'}, 'DISCORD_CHANNEL_ID'),
                              ({'POLL_SECONDS': '1'}, 'POLL_SECONDS'), ({'POST_EXISTING': 'yes'}, 'POST_EXISTING')):
            with self.subTest(changed=changed), self.assertRaises(ValueError) as raised:
                load_config({**ENV, **changed})
            self.assertIn(word, str(raised.exception))
            self.assertNotIn(ENV['DISCORD_BOT_TOKEN'], str(raised.exception))


class ReportTests(Folder):
    def test_reports_are_found_oldest_first_and_everything_else_in_the_folder_is_ignored(self):
        store(self.reports, BUG, screenshot=b'png')
        store(self.reports, CRASH)
        (self.reports / '.reports.lock').write_bytes(b'\0')
        (self.reports / ('.pending-' + BUG + '-abc123')).mkdir()
        (self.reports / 'notes.txt').write_text('not a report')
        self.assertEqual(receipts(self.reports), [CRASH, BUG])
        crash, bug = read_report(self.reports, CRASH), read_report(self.reports, BUG)
        self.assertEqual((crash.code, crash.kind, crash.screenshot, crash.saved_data), ('RF-1A2B3C4D', 'Crash report', None, None))
        self.assertEqual(crash.received, datetime(2026, 11, 23, 10, 15, 0, 1, tzinfo=timezone.utc))
        self.assertEqual((bug.code, bug.kind, bug.screenshot.name, bug.saved_data), ('BUG-00C0FFEE', 'Bug report', BUG + '.png', None))

    def test_a_recovered_error_report_is_read_and_posted_with_its_own_kind(self):
        store(self.reports, RECOVERED, saved=b'zip')
        self.assertEqual(receipts(self.reports), [RECOVERED])
        report = read_report(self.reports, RECOVERED)
        self.assertEqual((report.code, report.kind, report.screenshot, report.saved_data.name),
                         ('ERR-0BADF00D', 'Recovered error report', None, RECOVERED + '.zip'))
        self.assertTrue(message_text(report, []).startswith('**Recovered error report** `ERR-0BADF00D` received <t:'))

    def test_a_text_without_the_servers_closing_lines_is_not_a_report_yet(self):
        whole = text_of(CRASH)
        for partial in ('', whole[:40], whole.replace(CRASH, BUG), whole.rsplit('Server build', 1)[0]):
            with self.subTest(length=len(partial)):
                store(self.reports, CRASH, text=partial)
                self.assertIsNone(read_report(self.reports, CRASH))
        store(self.reports, CRASH)
        self.assertIsNotNone(read_report(self.reports, CRASH))
        self.assertIsNone(read_report(self.reports, 'missing'))


class TrackerTests(Folder):
    def test_a_first_start_takes_stored_reports_as_known_and_posts_only_later_ones(self):
        store(self.reports, CRASH)
        posted = run_once(self.config(), load_posted(self.state), self.send)
        self.assertEqual((self.sent, posted, load_posted(self.state)), ([], {CRASH}, {CRASH}))
        store(self.reports, BUG, screenshot=b'p' * 10, saved=b'z' * 20)
        posted = run_once(self.config(), posted, self.send)
        self.assertEqual(posted, {CRASH, BUG})
        (channel, content, files), = self.sent
        self.assertEqual(channel, ENV['DISCORD_CHANNEL_ID'])
        self.assertTrue(content.startswith('**Bug report** `BUG-00C0FFEE` received <t:1795428960:f>\n```\nArea: Family Room'), content)
        self.assertEqual([name for name, _ in files], ['BUG-00C0FFEE.log', 'BUG-00C0FFEE.png', 'BUG-00C0FFEE-saved-data.zip'])
        self.assertEqual([size for _, size in files][1:], [10, 20])
        # Nothing is posted twice, also after a restart; a report deleted on the server is forgotten.
        self.assertEqual(run_once(self.config(), load_posted(self.state), self.send), {CRASH, BUG})
        self.assertEqual(len(self.sent), 1)
        (self.reports / (CRASH + '.log')).unlink()
        self.assertEqual(run_once(self.config(), load_posted(self.state), self.send), {BUG})
        # The bot leaves the report folder as it found it.
        self.assertEqual(sorted(p.name for p in self.reports.iterdir()), [BUG])

    def test_stored_reports_are_posted_at_a_first_start_when_asked_for(self):
        store(self.reports, BUG)
        store(self.reports, CRASH)
        run_once(self.config(POST_EXISTING='true'), load_posted(self.state), self.send)
        self.assertEqual([content.split('`')[1] for _, content, _ in self.sent], ['RF-1A2B3C4D', 'BUG-00C0FFEE'])

    def test_a_report_discord_did_not_take_is_tried_again_and_later_ones_wait_behind_it(self):
        save = self.config(POST_EXISTING='true')
        store(self.reports, CRASH)
        store(self.reports, BUG)
        def refuse(*_):
            raise DiscordError(0, 'Discord could not be reached')
        with self.assertLogs('bug-tracker-bot', 'WARNING'):
            self.assertEqual(run_once(save, load_posted(self.state), refuse), set())
        self.assertEqual(run_once(save, load_posted(self.state), self.send), {CRASH, BUG})
        self.assertEqual(len(self.sent), 2)

    def test_files_left_out_are_named_in_the_message(self):
        store(self.reports, CRASH, screenshot=b'p' * 10, saved=b'z' * 5000)
        run_once(self.config(POST_EXISTING='true', ATTACH_SCREENSHOT='false', MAX_FILE_BYTES='1024'), None, self.send)
        (_, content, files), = self.sent
        self.assertEqual([name for name, _ in files], ['RF-1A2B3C4D.log'])
        self.assertIn('A screenshot file is kept on the server.', content)
        self.assertIn('The saved data file is too large to upload; it is kept on the server.', content)

    def test_an_upload_discord_calls_too_large_is_posted_again_as_text_alone(self):
        store(self.reports, CRASH, saved=b'z' * 100)
        calls = []
        def send(token, channel, content, files):
            calls.append((content, len(files)))
            if len(files) > 1:
                raise DiscordError(413, 'Discord answered 413')
        self.assertEqual(run_once(self.config(POST_EXISTING='true'), None, send), {CRASH})
        self.assertEqual([count for _, count in calls], [2, 1])
        self.assertIn('too large for this channel', calls[1][0])

    def test_the_message_fits_discords_limit_and_its_code_block_cannot_be_closed_by_the_text(self):
        store(self.reports, BUG, text=text_of(BUG, 'What happened: ```@everyone``` ' + 'x' * 5000))
        message = message_text(read_report(self.reports, BUG), [])
        self.assertLessEqual(len(message), 2000)
        self.assertEqual(message.count('```'), 2)
        self.assertTrue(message.endswith('\n…\n```'))


class DiscordTests(unittest.TestCase):
    def test_the_request_is_one_message_with_its_files_and_can_mention_nobody(self):
        seen = {}
        class Answer(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): return False
        def opener(request, timeout):
            seen.update(url=request.full_url, headers=dict(request.header_items()), body=request.data, method=request.get_method())
            return Answer(b'{"id": "42"}')
        self.assertEqual(post_message('secret-token', '123456789012345678', '@everyone hello', [('a.log', b'text'), ('a.png', b'\x89PNG')], opener=opener), '42')
        self.assertEqual((seen['method'], seen['url']), ('POST', 'https://discord.com/api/v10/channels/123456789012345678/messages'))
        self.assertEqual(seen['headers']['Authorization'], 'Bot secret-token')
        boundary = seen['headers']['Content-type'].split('boundary=')[1].encode()
        parts = seen['body'].split(b'--' + boundary)
        self.assertEqual(len(parts), 5)
        payload = json.loads(parts[1].split(b'\r\n\r\n', 1)[1])
        self.assertEqual(payload, {'content': '@everyone hello', 'allowed_mentions': {'parse': []},
                                   'attachments': [{'id': 0, 'filename': 'a.log'}, {'id': 1, 'filename': 'a.png'}]})
        self.assertIn(b'name="files[1]"; filename="a.png"', parts[3])
        self.assertTrue(parts[3].endswith(b'\r\n\r\n\x89PNG\r\n'))

    def test_a_refusal_carries_its_status_and_never_the_token(self):
        def refuse(status, body):
            def opener(request, timeout):
                raise urllib.error.HTTPError(request.full_url, status, 'refused', {}, io.BytesIO(body))
            return opener
        for status, body, check in ((429, b'{"message": "You are being rate limited.", "retry_after": 1.5}', lambda e: e.retry_after == 1.5),
                                    (413, b'{"message": "Request entity too large"}', lambda e: e.too_large),
                                    (401, b'not json', lambda e: e.permanent)):
            with self.subTest(status=status), self.assertRaises(DiscordError) as raised:
                post_message('secret-token', '1', 'x', [], opener=refuse(status, body))
            self.assertEqual(raised.exception.status, status)
            self.assertTrue(check(raised.exception))
            self.assertNotIn('secret-token', str(raised.exception))
        def unreachable(request, timeout):
            raise urllib.error.URLError('no route')
        with self.assertRaises(DiscordError) as raised:
            post_message('secret-token', '1', 'x', [], opener=unreachable)
        self.assertEqual(raised.exception.status, 0)

    def test_the_body_has_one_part_for_the_payload_and_one_for_each_file(self):
        body, content_type = multipart({'content': 'x'}, [])
        self.assertTrue(content_type.startswith('multipart/form-data; boundary=bug-tracker-'))
        self.assertEqual(body.count(b'Content-Disposition'), 1)


if __name__ == '__main__':
    unittest.main()

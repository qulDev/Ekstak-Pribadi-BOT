import io
import json
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from unittest.mock import patch

from bot import APIError, Bot, Job, TelegramAPI, allowed_cache_file


class FakeAPI:
    def __init__(self, source=None):
        self.calls = []
        self.source = source

    def call(self, method, **kw):
        self.calls.append((method, kw))
        if method == 'getFile':
            return {'file_path': str(self.source)}
        return True


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / 'cache'
        self.source = self.cache / '123' / 'documents' / 'file_1.zip'
        self.source.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.source, 'w') as z:
            z.writestr('folder/a.txt', b'hello')
        self.api = FakeAPI(self.source)
        self.bot = Bot(self.api, 42, self.root / 'work', self.cache)

    def tearDown(self):
        if self.bot.job and self.bot.job.thread:
            self.bot.job.cancel.set()
            self.bot.job.thread.join(5)
        self.tmp.cleanup()

    def msg(self, user=42, private=True, text=None, size=100):
        m = {'from': {'id': user}, 'chat': {'id': user, 'type': 'private' if private else 'group'}}
        if text is not None:
            m['text'] = text
        else:
            m['document'] = {'file_id': 'abc', 'file_name': 'input.zip', 'file_size': size}
        return m

    def test_unauthorized_and_group_messages_have_no_side_effects(self):
        for m in [self.msg(user=99), self.msg(private=False)]:
            self.bot.handle(m)
        self.assertEqual(self.api.calls, [])
        self.assertIsNone(self.bot.job)

    def test_oversize_is_rejected_before_download(self):
        self.bot.handle(self.msg(size=2_000_000_001))
        self.assertFalse(any(m == 'getFile' for m, _ in self.api.calls))
        self.assertIsNone(self.bot.job)

    def test_missing_size_is_rejected(self):
        m = self.msg()
        del m['document']['file_size']
        self.bot.handle(m)
        self.assertIsNone(self.bot.job)

    def test_busy_does_not_enqueue_another_archive(self):
        self.bot.job = Job('older')
        self.bot.handle(self.msg())
        self.assertEqual(self.bot.job.name, 'older')
        self.assertFalse(any(m == 'getFile' for m, _ in self.api.calls))

    def test_status_and_cancel(self):
        self.bot.job = Job('older')
        self.bot.handle(self.msg(text='/status'))
        self.assertIn('older', self.api.calls[-1][1]['text'])
        self.bot.handle(self.msg(text='/cancel'))
        self.assertTrue(self.bot.job.cancel.is_set())

    def test_cancel_captures_job_once_when_worker_finishes_concurrently(self):
        job = Job('finishing')
        job_reads = iter([job, None])

        class RaceBot(Bot):
            @property
            def job(self):
                return next(job_reads)

        raced = object.__new__(RaceBot)
        raced.api, raced.owner = self.api, 42
        raced.handle(self.msg(text='/cancel'))
        self.assertTrue(job.cancel.is_set())

    def test_full_job_sends_contents_and_cleans_source_and_output(self):
        self.bot.job = Job('input.zip')
        with patch('bot.MIN_FREE', 0):
            self.bot.work(self.bot.job, self.msg())
        sent = [kw for method, kw in self.api.calls if method == 'sendDocument']
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0]['document'].startswith('file:///'))
        self.assertIn('folder/a.txt', sent[0]['caption'])
        self.assertFalse(self.source.exists())
        self.assertFalse(list((self.bot.workdir / 'jobs').iterdir()))
        self.assertIsNone(self.bot.job)

    def test_large_archive_uses_one_upload_and_returns_a_zip(self):
        expected = {f'folder-{i}/file.txt': f'isi {i}'.encode() for i in range(301)}
        with zipfile.ZipFile(self.source, 'w') as archive:
            for i in range(3001):
                archive.writestr(f'folder-{i}/', b'')
            for name, data in expected.items():
                archive.writestr(name, data)

        calls = self.api.call
        packages = []

        def capture(method, **params):
            if method == 'sendDocument':
                path = Path(url2pathname(urlparse(params['document']).path))
                with zipfile.ZipFile(path) as package:
                    packages.append({name: package.read(name) for name in package.namelist()})
            return calls(method, **params)

        self.bot.job = Job('large.zip')
        with patch.object(self.api, 'call', side_effect=capture), patch('bot.MIN_FREE', 0):
            self.bot.work(self.bot.job, self.msg())
        self.assertEqual(packages, [expected])
        self.assertEqual(sum(method == 'getFile' for method, _ in self.api.calls), 1)
        self.assertFalse(self.source.exists())
        self.assertFalse(list(self.bot.jobsdir.iterdir()))

    def test_failed_progress_messages_do_not_abort_file_delivery(self):
        original_call = self.api.call

        def call(method, **params):
            if method == 'sendMessage' and params['text'].startswith(
                ('Mengunduh ', 'Mengekstrak ', 'Ekstraksi selesai.')
            ):
                raise APIError('Koneksi Telegram terputus.')
            return original_call(method, **params)

        self.bot.job = Job('input.zip')
        with patch.object(self.api, 'call', side_effect=call), patch('bot.MIN_FREE', 0):
            self.bot.work(self.bot.job, self.msg())
        sent = [kw for method, kw in self.api.calls if method == 'sendDocument']
        self.assertEqual(len(sent), 1)
        self.assertIn('folder/a.txt', sent[0]['caption'])

    def test_cache_paths_cannot_target_api_database_or_other_bot(self):
        for bad in [self.cache / '123' / 'binlog', self.root / 'outside', self.cache / '999' / 'documents' / 'file_1.zip']:
            self.assertFalse(allowed_cache_file(bad, self.cache, 123))
        self.assertTrue(allowed_cache_file(self.source, self.cache, 123))

    def test_failed_extraction_sends_no_partial_files(self):
        with zipfile.ZipFile(self.source, 'w') as z:
            z.writestr('okay.txt', b'ok')
            z.writestr('../escape.txt', b'bad')
        self.bot.job = Job('input.zip')
        with patch('bot.MIN_FREE', 0):
            self.bot.work(self.bot.job, self.msg())
        self.assertFalse(any(method == 'sendDocument' for method, _ in self.api.calls))
        self.assertFalse(self.source.exists())
        self.assertFalse((self.bot.workdir / 'escape.txt').exists())

    def test_upload_uri_preserves_spaces_percent_hash_and_unicode(self):
        name = 'folder/a %# ü.txt'
        with zipfile.ZipFile(self.source, 'w') as z:
            z.writestr(name, b'content')
        self.bot.job = Job('input.zip')
        with patch('bot.MIN_FREE', 0):
            self.bot.work(self.bot.job, self.msg())
        sent = [kw for method, kw in self.api.calls if method == 'sendDocument'][0]
        uri = sent['document']
        self.assertTrue(uri.startswith('file:///'))
        self.assertIn('%25%23', uri)
        self.assertTrue(unquote(urlparse(uri).path).endswith(name))

    def test_restart_loads_offset_and_cleans_interrupted_job(self):
        self.bot.save_state(1234, active=True)
        abandoned = self.bot.workdir / 'jobs' / 'abandoned'
        abandoned.mkdir()
        (abandoned / 'file').write_text('partial')
        restarted = Bot(self.api, 42, self.bot.workdir, self.cache)
        self.assertEqual(restarted.offset, 1234)
        self.assertTrue(restarted.interrupted)
        self.assertFalse(abandoned.exists())


class APITransportTests(unittest.TestCase):
    def test_rate_limit_in_bad_request_retries_same_upload(self):
        payload = {'ok': False, 'error_code': 400,
                   'description': 'Bad Request: too Many Requests: retry after 8'}
        rejection = HTTPError(None, 400, 'Bad Request', {}, io.BytesIO(json.dumps(payload).encode()))
        success = io.BytesIO(b'{"ok": true, "result": {"message_id": 17}}')
        with patch('bot.urllib.request.urlopen', side_effect=[rejection, success]) as open_url, \
                patch('bot.time.sleep') as wait:
            result = TelegramAPI('123:SECRET').call('sendPhoto', photo='file:///work/next.jpg')
        self.assertEqual(result, {'message_id': 17})
        wait.assert_called_once_with(8)
        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(open_url.call_args_list[0], open_url.call_args_list[1])

    def test_api_post_form_and_server_error_never_expose_token(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.rfile.read(int(self.headers['Content-Length']))))
                result = {'ok': False, 'error_code': 400, 'description': 'bad request'} if self.path.endswith('fail') else {'ok': True, 'result': {'id': 123}}
                self.send_response(400 if not result['ok'] else 200)
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = TelegramAPI('123:SECRET', f'http://127.0.0.1:{server.server_port}')
            self.assertEqual(api.call('getMe'), {'id': 123})
            api.call('sendDocument', document='/work/a b.txt', caption='hello')
            self.assertIn(b'document=%2Fwork%2Fa+b.txt', received[-1][1])
            with self.assertRaises(APIError) as caught:
                api.call('fail')
            self.assertNotIn('SECRET', str(caught.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()

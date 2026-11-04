import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import py7zr
from bot import Bot


class ChatAPI:
    def __init__(self, source):
        self.source, self.calls = source, []

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == 'getFile':
            return {'file_path': str(self.source)}
        return {'message_id': len(self.calls)}


class PasswordDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'cache' / '123' / 'documents' / 'file_1.7z'
        self.source.parent.mkdir(parents=True)
        with py7zr.SevenZipFile(self.source, 'w', password=' correct password ', header_encryption=True) as archive:
            archive.writestr(b'hello', 'folder/a.txt')
        self.api = ChatAPI(self.source)
        self.bot = Bot(self.api, 42, self.root / 'work', self.root / 'cache')
        self.free = patch('bot.MIN_FREE', 0)
        self.free.start()
        self.thread = None

    def tearDown(self):
        job = self.bot.job
        if job:
            job.cancel.set()
        if self.thread:
            self.thread.join(5)
        self.free.stop()
        self.temp.cleanup()

    def message(self, text=None, user=42, private=True):
        m = {'from': {'id': user}, 'chat': {'id': user, 'type': 'private' if private else 'group'}}
        if text is None:
            m['document'] = {'file_id': 'protected', 'file_size': self.source.stat().st_size, 'file_name': 'protected.7z'}
        else:
            m['text'] = text
        return m

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail('Expected password/job state not reached')

    def start(self):
        self.bot.handle(self.message())
        self.thread = self.bot.job.thread
        self.wait(lambda: self.bot.job and getattr(self.bot.job, 'waiting_password', False))

    def finish(self):
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())
        self.assertIsNone(self.bot.job)
        self.assertFalse(self.source.exists())
        self.assertFalse(list(self.bot.jobsdir.iterdir()))

    def test_wrong_password_prompts_retry_without_downloading_again_then_succeeds(self):
        self.start()
        self.assertTrue(self.source.exists())
        self.assertFalse(list(self.bot.jobsdir.glob('*/output')))
        self.assertFalse(any(m.startswith('send') and m != 'sendMessage' for m, _ in self.api.calls))
        self.bot.handle(self.message('wrong'))
        self.wait(lambda: any('belum cocok' in p.get('text', '').lower() for m, p in self.api.calls if m == 'sendMessage'))
        self.assertFalse(list(self.bot.jobsdir.glob('*/output')))
        self.bot.handle(self.message(' correct password '))
        self.finish()
        self.assertEqual(sum(m == 'getFile' for m, _ in self.api.calls), 1)
        self.assertEqual(sum(m == 'sendDocument' for m, _ in self.api.calls), 1)
        texts = '\n'.join(p.get('text', '') for m, p in self.api.calls if m == 'sendMessage')
        self.assertNotIn(' correct password ', texts)
        self.assertNotIn('wrong', texts)
        self.assertNotIn('password', (self.bot.workdir / 'state.json').read_text().lower())

    def test_owner_only_and_status_remain_available_during_password_wait(self):
        self.start()
        before = len(self.api.calls)
        self.bot.handle(self.message(' correct password ', user=99))
        self.bot.handle(self.message(' correct password ', private=False))
        self.assertEqual(len(self.api.calls), before)
        self.assertTrue(self.bot.job.waiting_password)
        self.bot.handle(self.message('/status'))
        self.assertIn('password', self.api.calls[-1][1]['text'].lower())
        self.bot.handle(self.message('/cancel'))
        self.finish()

    def test_cancel_while_waiting_cleans_archive_and_partial_output(self):
        self.start()
        self.bot.handle(self.message('/cancel'))
        self.finish()
        self.assertFalse(any(m == 'sendDocument' for m, _ in self.api.calls))

    def test_password_wait_timeout_cleans_archive(self):
        with patch('bot.PASSWORD_TIMEOUT', 0.5):
            self.start()
            self.finish()
        self.assertTrue(any('waktu' in p.get('text', '').lower() for m, p in self.api.calls if m == 'sendMessage'))

    def test_another_archive_is_not_interpreted_as_a_password(self):
        self.start()
        self.bot.handle(self.message())
        self.assertTrue(self.bot.job.waiting_password)
        self.assertEqual(sum(m == 'getFile' for m, _ in self.api.calls), 1)
        self.bot.handle(self.message('/cancel'))
        self.finish()

    def test_shutdown_while_waiting_cleans_archive(self):
        self.start()
        self.bot.stopping.set()
        self.finish()

    def test_wrong_caption_password_can_be_corrected_in_chat(self):
        message = self.message()
        message['caption'] = 'password: wrong'
        self.bot.handle(message)
        self.thread = self.bot.job.thread
        self.wait(lambda: self.bot.job and getattr(self.bot.job, 'waiting_password', False))
        self.assertTrue(any('belum cocok' in p.get('text', '').lower() for m, p in self.api.calls if m == 'sendMessage'))
        self.bot.handle(self.message(' correct password '))
        self.finish()
        self.assertEqual(sum(m == 'getFile' for m, _ in self.api.calls), 1)


if __name__ == '__main__':
    unittest.main()

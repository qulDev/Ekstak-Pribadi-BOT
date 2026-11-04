import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bot import APIError, Bot, Job


class MediaAPI:
    def __init__(self, error=None, source=None):
        self.calls = []
        self.error, self.source = error, source

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == 'getFile':
            return {'file_path': str(self.source)}
        if method in ('sendPhoto', 'sendVideo') and self.error:
            raise self.error
        return True


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.api = MediaAPI()
        self.bot = Bot(self.api, 42, self.root / 'work', self.root / 'cache')

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, name, size=4):
        path = self.root / name
        with path.open('wb') as f:
            f.truncate(size)
        return path

    def test_photo_extensions_use_photo_parameter_and_caption(self):
        for name in ['photo.jpg', 'photo.JPEG', 'photo.PNG', 'photo.webp', 'a %# ü.jpg']:
            with self.subTest(name=name):
                path = self.file(name)
                self.bot.send_file(path, 'folder/' + name)
                method, params = self.api.calls[-1]
                self.assertEqual(method, 'sendPhoto')
                self.assertEqual(params['photo'], path.as_uri())
                self.assertEqual(params['caption'], 'folder/' + name)
                self.assertEqual(params['chat_id'], 42)
                self.assertNotIn('document', params)

    def test_video_extensions_use_video_parameter(self):
        for name in ['clip.mp4', 'clip.M4V', 'clip.MOV']:
            with self.subTest(name=name):
                path = self.file(name)
                self.bot.send_file(path, name)
                method, params = self.api.calls[-1]
                self.assertEqual(method, 'sendVideo')
                self.assertEqual(params['video'], path.as_uri())
                self.assertEqual(params['request_timeout'], 3600)
                self.assertNotIn('supports_streaming', params)

    def test_other_files_and_binary_parts_remain_documents(self):
        for name in ['report.pdf', 'clip.mkv', 'clip.avi', 'animation.gif', 'image.jpg.part001', 'movie.mp4.part002', 'unknown']:
            with self.subTest(name=name):
                path = self.file(name)
                self.bot.send_file(path, name)
                self.assertEqual(self.api.calls[-1][0], 'sendDocument')
                self.assertEqual(self.api.calls[-1][1]['document'], path.as_uri())

    def test_large_photos_go_directly_to_documents(self):
        self.bot.send_file(self.file('large.jpg', 10_000_001), 'large')
        self.assertEqual([method for method, _ in self.api.calls], ['sendDocument'])

    def test_photo_at_size_boundary_is_candidate_for_preview(self):
        self.bot.send_file(self.file('boundary.jpg', 10_000_000), 'boundary')
        self.assertEqual(self.api.calls[-1][0], 'sendPhoto')

    def test_empty_media_is_not_sent_as_photo_or_video(self):
        for name in ['empty.jpg', 'empty.mp4']:
            self.bot.send_file(self.file(name, 0), name)
            self.assertEqual(self.api.calls[-1][0], 'sendDocument')

    def test_explicit_media_rejection_falls_back_once(self):
        for name, method in [('bad.jpg', 'sendPhoto'), ('bad.mp4', 'sendVideo')]:
            for code in [400, 413]:
                with self.subTest(name=name, code=code):
                    self.api.calls.clear()
                    self.api.error = APIError('Bad Request: invalid media', code=code)
                    path = self.file(name)
                    self.bot.send_file(path, 'original caption')
                    self.assertEqual([m for m, _ in self.api.calls], [method, 'sendDocument'])
                    self.assertEqual(self.api.calls[-1][1]['document'], path.as_uri())
                    self.assertEqual(self.api.calls[-1][1]['caption'], 'original caption')

    def test_transport_access_rate_and_server_errors_do_not_trigger_fallback(self):
        for code in [0, 401, 403, 429, 500]:
            with self.subTest(code=code):
                self.api.calls.clear()
                self.api.error = APIError('Request failed', code=code)
                with self.assertRaises(APIError):
                    self.bot.send_file(self.file('photo.jpg'), 'photo')
                self.assertEqual([m for m, _ in self.api.calls], ['sendPhoto'])

    def test_document_errors_are_not_retried(self):
        with patch.object(self.api, 'call', side_effect=APIError('Document failed', code=400)) as call:
            with self.assertRaises(APIError):
                self.bot.send_file(self.file('file.pdf'), 'pdf')
            self.assertEqual(call.call_count, 1)

    def test_mixed_archive_sends_media_and_document_then_cleans_up(self):
        source = self.root / 'cache' / '123' / 'documents' / 'file_1.zip'
        source.parent.mkdir(parents=True)
        with zipfile.ZipFile(source, 'w') as archive:
            # Payload validation belongs to Telegram; this test checks extraction/routing integration.
            archive.writestr('a/photo.jpg', b'photo payload')
            archive.writestr('b/clip.mp4', b'video payload')
            archive.writestr('c/readme.txt', b'text')
        self.api.source = source
        self.bot.job = Job('mixed.zip')
        with patch('bot.MIN_FREE', 0):
            self.bot.work(self.bot.job, {'document': {'file_id': 'archive'}})
        sent = [(m, p) for m, p in self.api.calls if m in ('sendPhoto', 'sendVideo', 'sendDocument')]
        self.assertEqual([m for m, _ in sent], ['sendPhoto', 'sendVideo', 'sendDocument'])
        self.assertEqual([p['caption'] for _, p in sent], ['a/photo.jpg', 'b/clip.mp4', 'c/readme.txt'])
        self.assertFalse(source.exists())
        self.assertFalse(list(self.bot.jobsdir.iterdir()))
        self.assertIsNone(self.bot.job)
        self.assertTrue(any('Selesai. 3 file' in p.get('text', '')
                            for m, p in self.api.calls if m == 'sendMessage'))


if __name__ == '__main__':
    unittest.main()

import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from extractor import ArchiveRejected, Limits, extract_archive, iter_send_files, safe_path


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / 'output'

    def tearDown(self):
        self.tmp.cleanup()

    def zip(self, entries):
        p = self.root / 'input.zip'
        with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, content in entries:
                z.writestr(name, content)
        return p

    def limits(self, **kw):
        return Limits(min_free=0, **kw)

    def test_zip_preserves_folder_names_and_bytes(self):
        p = self.zip([('folder/a.txt', b'hello'), ('other/a.txt', b'world')])
        files = extract_archive(p, self.out, limits=self.limits())
        self.assertEqual([f.read_bytes() for f in files], [b'hello', b'world'])
        self.assertEqual(files[0].relative_to(self.out).as_posix(), 'folder/a.txt')

    def test_paths_cannot_escape_output(self):
        for name in ['../secret', '/etc/passwd', 'C:/x', 'a/../../x', '..\\secret', '\\\\server\\x', 'a\x00b']:
            with self.subTest(name=name), self.assertRaises(ArchiveRejected):
                safe_path(self.out, name)

    def test_tar_rejects_links_and_devices(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE]:
            with self.subTest(kind=kind):
                p = self.root / 'input.tar'
                with tarfile.open(p, 'w') as t:
                    entry = tarfile.TarInfo('link')
                    entry.type = kind
                    entry.linkname = '/etc/passwd'
                    t.addfile(entry)
                with self.assertRaises(ArchiveRejected):
                    extract_archive(p, self.out, limits=self.limits())

    def test_expanded_size_limit(self):
        p = self.zip([('bomb.txt', b'0' * 100_000)])
        with self.assertRaises(ArchiveRejected):
            extract_archive(p, self.out, limits=self.limits(max_total=999))

    def test_file_count_limit(self):
        p = self.zip([('a', b'a'), ('b', b'b')])
        with self.assertRaises(ArchiveRejected):
            extract_archive(p, self.out, limits=self.limits(max_files=1))

    def test_duplicates_cannot_overwrite(self):
        p = self.zip([('a.txt', b'one'), ('./a.txt', b'two')])
        with self.assertRaises(ArchiveRejected):
            extract_archive(p, self.out, limits=self.limits())

    def test_corrupt_archive_fails(self):
        p = self.root / 'bad.zip'
        p.write_bytes(b'not an archive')
        with self.assertRaises(ArchiveRejected):
            extract_archive(p, self.out, limits=self.limits())

    def test_split_is_lossless_bounded_and_cleans_parts(self):
        p = self.root / 'large.bin'
        p.write_bytes(bytes(range(31)))
        sent = []
        names = []
        for part, suffix in iter_send_files(p, self.root / 'parts', limit=10, part_size=8):
            self.assertLessEqual(part.stat().st_size, 8)
            sent.append(part.read_bytes())
            names.append(part.name)
        self.assertEqual(b''.join(sent), p.read_bytes())
        self.assertEqual(names[0], 'large.bin.part001')
        self.assertFalse(list((self.root / 'parts').glob('*')))

    def test_small_file_is_sent_unchanged(self):
        p = self.root / 'small.txt'
        p.write_bytes(b'ok')
        self.assertEqual(list(iter_send_files(p, self.root / 'parts', limit=10, part_size=8)), [(p, '')])

    def test_tar_root_directory_entry_is_allowed(self):
        p = self.root / 'a.tar.gz'
        with tarfile.open(p, 'w:gz') as t:
            root = tarfile.TarInfo('.')
            root.type = tarfile.DIRTYPE
            t.addfile(root)
            entry = tarfile.TarInfo('./a.txt')
            entry.size = 2
            t.addfile(entry, io.BytesIO(b'ok'))
        files = extract_archive(p, self.out, limits=self.limits())
        self.assertEqual(files[0].read_bytes(), b'ok')

    def test_real_7zip_content(self):
        import libarchive
        p = self.root / 'input.7z'
        with libarchive.file_writer(str(p), '7zip') as archive:
            archive.add_file_from_memory('folder/test.txt', 2, b'ok')
        files = extract_archive(p, self.out, limits=self.limits())
        self.assertEqual(files[0].read_bytes(), b'ok')

    def test_actual_block_limit_even_when_header_is_small(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch

        @contextmanager
        def reader(*args, **kwargs):
            yield [SimpleNamespace(issym=False, islnk=False, isdir=False, isreg=True,
                                   pathname='lying.txt', size=1,
                                   get_blocks=lambda **kw: iter([b'abc', b'def']))]

        with patch('libarchive.file_reader', reader), self.assertRaises(ArchiveRejected):
            extract_archive(self.root / 'unused', self.out, limits=self.limits(max_total=4))
        self.assertEqual((self.out / 'lying.txt').read_bytes(), b'abc')

    def test_split_cleanup_on_upload_failure(self):
        p = self.root / 'large.bin'
        p.write_bytes(b'0123456789')
        generator = iter_send_files(p, self.root / 'parts', limit=5, part_size=4)
        part, _ = next(generator)
        self.assertTrue(part.exists())
        generator.close()
        self.assertFalse(part.exists())

    def test_splitting_preserves_free_disk_reserve(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        p = self.root / 'large.bin'
        p.write_bytes(b'0123456789')
        with patch('extractor.shutil.disk_usage', return_value=SimpleNamespace(free=9)), self.assertRaises(ArchiveRejected):
            list(iter_send_files(p, self.root / 'parts', limit=5, part_size=4, min_free=8))
        self.assertFalse(list((self.root / 'parts').glob('*')))


if __name__ == '__main__':
    unittest.main()

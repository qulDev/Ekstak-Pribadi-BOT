"""Stream archive contents; never ask the archive library to create filesystem objects."""
import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class ArchiveRejected(Exception):
    pass


class PasswordNeeded(ArchiveRejected):
    """Retryable encrypted archive error; never includes the supplied password."""


@dataclass(frozen=True)
class Limits:
    max_total: int = 20_000_000_000
    max_files: int = 10_000
    max_entries: int = 30_000
    min_free: int = 10_000_000_000


def safe_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or len(name) > 1000 or '\x00' in name:
        raise ArchiveRejected('Nama file tidak valid atau terlalu panjang.')
    normalized = name.replace('\\', '/')
    p = PurePosixPath(normalized)
    if p.is_absolute() or '..' in p.parts or ':' in normalized or len(p.parts) > 64:
        raise ArchiveRejected('Arsip berisi jalur file yang tidak aman.')
    target = root.joinpath(*p.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ArchiveRejected('Arsip mencoba menulis di luar folder ekstraksi.')
    return target


def extract_archive(source: Path, output: Path, password=None, limits=Limits()) -> list[Path]:
    import libarchive
    from libarchive.exception import ArchiveError

    output.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as stream:
        is_sevenzip = stream.read(6) == b'7z\xbc\xaf\x27\x1c'
    if is_sevenzip:
        result = extract_encrypted_7z(source, output, password, limits)
        if result is not None:
            return result
    files, total, seen = [], 0, set()
    try:
        with libarchive.file_reader(str(source), passphrase=password) as archive:
            for count, entry in enumerate(archive, 1):
                if count > limits.max_entries:
                    raise ArchiveRejected(f'Arsip melebihi {limits.max_entries} entri (file dan folder). '
                                          'Bagi isinya menjadi beberapa arsip terpisah.')
                if entry.issym or entry.islnk or not (entry.isdir or entry.isreg):
                    raise ArchiveRejected('Link dan file khusus tidak diperbolehkan.')
                path = safe_path(output, entry.pathname)
                if path == output:
                    if entry.isdir:
                        continue
                    raise ArchiveRejected('Nama file kosong dalam arsip.')
                if entry.isdir:
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                if path in seen or path.exists():
                    raise ArchiveRejected('Arsip memiliki nama file yang bertabrakan.')
                seen.add(path)
                if len(files) >= limits.max_files:
                    raise ArchiveRejected(f'Batas jumlah file adalah {limits.max_files}.')
                if entry.size is not None and (entry.size < 0 or total + entry.size > limits.max_total):
                    raise ArchiveRejected('Total hasil ekstraksi melewati batas 20 GB.')
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as target:
                    for block in entry.get_blocks(block_size=1024 * 1024):
                        if total + len(block) > limits.max_total:
                            raise ArchiveRejected('Total hasil ekstraksi melewati batas 20 GB.')
                        if shutil.disk_usage(output).free < limits.min_free + len(block):
                            raise ArchiveRejected('Ruang penyimpanan bebas tidak mencukupi.')
                        target.write(block)
                        total += len(block)
                files.append(path)
    except ArchiveError as exc:
        detail = str(exc).lower()
        if ('passphrase' in detail or 'password' in detail) and not any(
                word in detail for word in ['unsupported', 'not supported', 'not support']):
            raise PasswordNeeded('Arsip memerlukan password atau password belum cocok.') from None
        raise ArchiveRejected('Arsip rusak, password keliru, atau format/enkripsinya belum didukung.') from exc
    return files


def extract_encrypted_7z(source, output, password, limits):
    import lzma
    import zlib
    import py7zr
    from py7zr import compressor
    from py7zr import exceptions as seven_errors
    from py7zr.io import Py7zIO, WriterFactory

    class Writer(Py7zIO):
        def __init__(self, path, factory):
            path.parent.mkdir(parents=True, exist_ok=True)
            self.file = path.open('x+b')
            self.factory, self.high_water = factory, 0

        def write(self, data):
            growth = max(0, self.file.tell() + len(data) - self.high_water)
            if self.factory.total + growth > limits.max_total:
                raise ArchiveRejected('Total hasil ekstraksi melewati batas 20 GB.')
            if shutil.disk_usage(output).free < limits.min_free + growth:
                raise ArchiveRejected('Ruang penyimpanan bebas tidak mencukupi.')
            written = self.file.write(data)
            self.factory.total += growth
            self.high_water = max(self.high_water, self.file.tell())
            return written

        def read(self, size=None):
            return self.file.read(-1 if size is None else size)

        def seek(self, offset, whence=0):
            target = offset if whence == 0 else (self.file.tell() if whence == 1 else self.high_water) + offset
            if not 0 <= target <= self.high_water:
                raise ArchiveRejected('Posisi tulis arsip tidak valid.')
            return self.file.seek(offset, whence)

        def flush(self):
            if not self.file.closed:
                self.file.flush()

        def size(self):
            return self.high_water

        def close(self):
            self.file.close()

    class Factory(WriterFactory):
        def __init__(self, allowed):
            self.allowed, self.total, self.writers = allowed, 0, []

        def create(self, filename):
            path = safe_path(output, filename)
            if path not in self.allowed:
                raise ArchiveRejected('Arsip mencoba membuat file yang tidak terdaftar.')
            writer = Writer(path, self)
            self.writers.append(writer)
            return writer

        def close(self):
            for writer in self.writers:
                writer.close()

    factory, encrypted = None, False
    try:
        # needs_password() is also set merely by supplying a password to py7zr.
        # Probe without one so a caption cannot turn a plain/corrupt archive into
        # a password retry loop.
        try:
            with py7zr.SevenZipFile(source, max_extract_size=limits.max_total) as probe:
                encrypted = probe.needs_password()
        except seven_errors.PasswordRequired:
            encrypted = True
        if not encrypted:
            return None
        if password is None:
            raise PasswordNeeded('Arsip ini dilindungi password.')
        with py7zr.SevenZipFile(source, password=password, max_extract_size=limits.max_total) as archive:
            entries = archive.list()
            if len(entries) > limits.max_entries:
                raise ArchiveRejected(f'Arsip melebihi {limits.max_entries} entri (file dan folder). '
                                      'Bagi isinya menjadi beberapa arsip terpisah.')
            files, seen, declared = [], set(), 0
            for entry in entries:
                if entry.is_symlink or not (entry.is_directory or entry.is_file):
                    raise ArchiveRejected('Link dan file khusus tidak diperbolehkan.')
                path = safe_path(output, entry.filename)
                if entry.is_directory:
                    continue
                if path == output or path in seen or path.exists():
                    raise ArchiveRejected('Arsip memiliki nama file yang bertabrakan.')
                seen.add(path)
                files.append(path)
                declared += entry.uncompressed
                if len(files) > limits.max_files or entry.uncompressed < 0 or declared > limits.max_total:
                    raise ArchiveRejected('Ukuran atau jumlah file hasil melewati batas.')
            factory = Factory(seen)
            archive.extractall(factory=factory)
            return files
    except seven_errors.PasswordRequired:
        raise PasswordNeeded('Arsip ini dilindungi password.') from None
    except seven_errors.UnsupportedCompressionMethodError:
        raise ArchiveRejected('Metode kompresi atau enkripsi 7z ini belum didukung.') from None
    except seven_errors.DecompressionBombError:
        raise ArchiveRejected('Total hasil ekstraksi melewati batas 20 GB.') from None
    except OSError as exc:
        # BZIP2 reports invalid decrypted bytes as a bare OSError. Real disk and
        # permission errors must stay fatal rather than ask for another password.
        if exc.errno is None and str(exc) == 'Invalid data stream':
            if encrypted and password is not None:
                raise PasswordNeeded('Password belum cocok atau arsip terenkripsi rusak.') from None
            raise ArchiveRejected('Arsip 7z rusak atau formatnya belum didukung.') from None
        raise
    except (seven_errors.Bad7zFile, seven_errors.CrcError, seven_errors.DecompressionError,
            lzma.LZMAError, zlib.error, compressor.zstd.ZstdError, compressor.brotli.error,
            EOFError, TypeError, ValueError):
        if encrypted and password is not None:
            raise PasswordNeeded('Password belum cocok atau arsip terenkripsi rusak.') from None
        raise ArchiveRejected('Arsip 7z rusak atau formatnya belum didukung.') from None
    finally:
        if factory:
            factory.close()


def iter_zip_packages(files, root: Path, scratch: Path, limit=1_900_000_000,
                      min_free=Limits().min_free, cancelled=lambda: False):
    """Yield one complete ZIP at a time, then files too large for a ZIP."""
    batches, oversized = [], []
    batch, budget = [], 128
    for path in files:
        name = path.relative_to(root).as_posix()
        # Stored ZIP entries use a local and central header, each with the UTF-8 name.
        # Leave extra room for metadata and the archive footer.
        cost = path.stat().st_size + 2 * len(name.encode('utf-8')) + 256
        if cost + 128 > limit:
            oversized.append((path, name))
            continue
        if budget + cost > limit:
            batches.append((batch, budget))
            batch, budget = [], 128
        batch.append((path, name))
        budget += cost
    if batch:
        batches.append((batch, budget))

    scratch.mkdir(parents=True, exist_ok=True)
    for index, (members, budget) in enumerate(batches, 1):
        if cancelled():
            raise ArchiveRejected('Proses dibatalkan.')
        if shutil.disk_usage(scratch).free < min_free + budget:
            raise ArchiveRejected('Ruang bebas tidak cukup untuk membuat paket ZIP hasil.')
        package = scratch / f'hasil-{index:03}.zip'
        try:
            with zipfile.ZipFile(package, 'x', zipfile.ZIP_STORED, allowZip64=False) as archive:
                for path, name in members:
                    if cancelled():
                        raise ArchiveRejected('Proses dibatalkan.')
                    entry = zipfile.ZipInfo.from_file(path, name, strict_timestamps=False)
                    with path.open('rb') as source, archive.open(entry, 'w') as target:
                        while block := source.read(1024 * 1024):
                            if cancelled():
                                raise ArchiveRejected('Proses dibatalkan.')
                            if shutil.disk_usage(scratch).free < min_free + len(block):
                                raise ArchiveRejected('Ruang bebas tidak cukup untuk membuat paket ZIP hasil.')
                            target.write(block)
            if package.stat().st_size > limit:
                raise ArchiveRejected('Paket ZIP hasil melewati batas ukuran.')
            yield package, f'Paket ZIP {index}/{len(batches)}'
        finally:
            package.unlink(missing_ok=True)
    yield from oversized


def iter_send_files(path: Path, scratch: Path, limit=2_000_000_000, part_size=1_900_000_000,
                    min_free=Limits().min_free):
    if path.stat().st_size <= limit:
        yield path, ''
        return
    scratch.mkdir(parents=True, exist_ok=True)
    with path.open('rb') as source:
        for index in range(1, (path.stat().st_size + part_size - 1) // part_size + 1):
            part = scratch / (path.name + f'.part{index:03}')
            try:
                with part.open('xb') as target:
                    remaining = part_size
                    while remaining:
                        block = source.read(min(1024 * 1024, remaining))
                        if not block:
                            break
                        if shutil.disk_usage(scratch).free < min_free + len(block):
                            raise ArchiveRejected('Ruang bebas tidak cukup untuk membagi file hasil.')
                        target.write(block)
                        remaining -= len(block)
                yield part, f' — bagian {index}'
            finally:
                part.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    # Password travels via stdin, not a process argument or environment variable.
    payload = json.loads(sys.stdin.readline())
    password = payload.get('password')
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (4_000_000_000, 4_000_000_000))
        resource.setrlimit(resource.RLIMIT_CPU, (3600, 3600))
    try:
        extract_archive(args.source, args.output, password=password,
                        limits=Limits(min_free=int(payload.get('min_free', Limits().min_free))))
    except PasswordNeeded as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ArchiveRejected, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ArchiveRejected) else 'Gagal menulis hasil ekstraksi.'
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

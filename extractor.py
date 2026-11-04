"""Stream archive contents; never ask the archive library to create filesystem objects."""
import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class ArchiveRejected(Exception):
    pass


@dataclass(frozen=True)
class Limits:
    max_total: int = 20_000_000_000
    max_files: int = 300
    max_entries: int = 3000
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
    files, total, seen = [], 0, set()
    try:
        with libarchive.file_reader(str(source), passphrase=password) as archive:
            for count, entry in enumerate(archive, 1):
                if count > limits.max_entries:
                    raise ArchiveRejected('Terlalu banyak entri dalam arsip.')
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
        raise ArchiveRejected('Arsip rusak, password keliru, atau format/enkripsinya belum didukung.') from exc
    return files


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
    except (ArchiveRejected, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ArchiveRejected) else 'Gagal menulis hasil ekstraksi.'
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

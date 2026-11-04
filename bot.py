"""Private long-polling archive bot. Secrets never appear in log messages."""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from extractor import ArchiveRejected, iter_send_files

MAX_INPUT = 2_000_000_000
MIN_FREE = 10_000_000_000
EXTRACT_TIMEOUT = 3600
HELP = ('Kirim ZIP, 7z, RAR, TAR atau arsip terkompresi (maks. 2.000 MB).\n'
        'Batas hasil: 20 GB dan 300 file. Arsip di dalam arsip tidak diekstrak ulang.\n'
        'Untuk arsip berpassword, gunakan caption: password: KATA_SANDI\n'
        'Beberapa enkripsi 7z/RAR belum didukung.\n'
        '/status — lihat proses\n/cancel — hentikan proses\n'
        'Hasil di atas 2.000 MB dibagi menjadi file .part001 dan seterusnya.')


class APIError(Exception):
    def __init__(self, message, code=0, retry_after=0):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class TelegramAPI:
    def __init__(self, token, base='http://api:8081'):
        self.token = token
        self.base = base.rstrip('/')

    def call(self, method, request_timeout=65, **params):
        data = urllib.parse.urlencode({k: json.dumps(v) if isinstance(v, (list, dict, bool)) else v
                                       for k, v in params.items()}).encode()
        request = urllib.request.Request(f'{self.base}/bot{self.token}/{method}', data=data)
        for attempt in range(4):
            try:
                try:
                    with urllib.request.urlopen(request, timeout=request_timeout) as response:
                        raw = response.read(2_000_000)
                except urllib.error.HTTPError as exc:
                    raw = exc.read(100_000)
                result = json.loads(raw)
            except (OSError, ValueError, urllib.error.URLError) as exc:
                # Do not retry ambiguous transfers: Telegram may already have accepted them.
                raise APIError('Koneksi Telegram terputus atau respons tidak valid.') from None
            if result.get('ok'):
                return result.get('result')
            retry = int(result.get('parameters', {}).get('retry_after', 0))
            if result.get('error_code') == 429 and 0 < retry <= 60 and attempt < 3:
                time.sleep(retry)
                continue
            description = str(result.get('description', 'Permintaan Telegram ditolak.'))
            description = description.replace(self.token, '[token]')[:300]
            raise APIError(description, result.get('error_code', 0), retry)


def allowed_cache_file(path: Path, cache: Path, bot_key) -> bool:
    # Local Bot API uses the full bot token as its directory name. Never log this path.
    roots = [cache / str(bot_key), cache / str(bot_key).replace(':', '~')]
    return (path.is_absolute() and not path.is_symlink() and path.name.startswith('file_')
            and any(path.parent.resolve() == (root / 'documents').resolve() for root in roots))


@dataclass
class Job:
    name: str
    cancel: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.monotonic)
    phase: str = 'Menunggu unduhan'
    thread: threading.Thread | None = None


class Bot:
    def __init__(self, api, owner, workdir=Path('/work'), cache=Path('/var/lib/telegram-bot-api')):
        self.api, self.owner = api, int(owner)
        self.workdir, self.cache = Path(workdir), Path(cache)
        self.bot_key = getattr(api, 'token', '123')
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.jobsdir = self.workdir / 'jobs'
        self.jobsdir.mkdir(exist_ok=True)
        self.state_lock = threading.RLock()
        self.state_path = self.workdir / 'state.json'
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.offset = int(state.get('offset', 0))
        self.interrupted = bool(state.get('active'))
        self.job = None
        self.stopping = threading.Event()
        for child in self.jobsdir.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    def save_state(self, offset=None, active=None):
        with self.state_lock:
            if offset is not None:
                self.offset = offset
            state = {'offset': self.offset, 'active': bool(self.job) if active is None else active}
            temporary = self.state_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(state))
            os.replace(temporary, self.state_path)

    def say(self, text):
        return self.api.call('sendMessage', chat_id=self.owner, text=str(text)[:3800])

    def notify(self, text):
        try:
            self.say(text)
        except APIError:
            print('Notifikasi tidak terkirim; periksa koneksi Telegram.', flush=True)

    def clean_cache(self, max_age=4 * 3600):
        for root in [self.cache / str(self.bot_key), self.cache / str(self.bot_key).replace(':', '~')]:
            folder = root / 'documents'
            if not folder.is_dir() or folder.is_symlink():
                continue
            for path in folder.iterdir():
                if allowed_cache_file(path, self.cache, self.bot_key) and path.is_file():
                    if time.time() - path.stat().st_mtime > max_age:
                        path.unlink(missing_ok=True)

    def handle(self, message):
        sender, chat = message.get('from', {}), message.get('chat', {})
        if sender.get('id') != self.owner or chat.get('id') != self.owner or chat.get('type') != 'private':
            return
        text = message.get('text', '').strip()
        command = text.split(maxsplit=1)[0].split('@')[0] if text else ''
        if command in ['/start', '/help']:
            self.say(HELP)
            return
        if command == '/status':
            job = self.job
            self.say(f'{job.name}\n{job.phase}\nBerjalan {int(time.monotonic()-job.started)} detik.'
                     if job else 'Tidak ada proses. Kirim arsip untuk mulai.')
            return
        if command == '/cancel':
            job = self.job
            if job:
                job.cancel.set()
                self.say('Pembatalan diminta. Transfer yang sedang berjalan perlu selesai dahulu.')
            else:
                self.say('Tidak ada proses yang perlu dibatalkan.')
            return
        document = message.get('document')
        if not document:
            self.say(HELP)
            return
        if self.job:
            self.say('Masih ada arsip yang diproses. Kirim ulang setelah selesai atau gunakan /cancel.')
            return
        size = document.get('file_size')
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_INPUT:
            self.say('Ukuran arsip harus diketahui dan maksimal 2.000 MB per file.')
            return
        name = str(document.get('file_name', 'arsip'))[:150].replace('\n', ' ')
        job = Job(name)
        self.job = job
        self.save_state()
        job.thread = threading.Thread(target=self.work, args=(job, message), daemon=True)
        job.thread.start()

    def work(self, job, message):
        directory = self.jobsdir / uuid.uuid4().hex
        output, parts = directory / 'output', directory / 'parts'
        source, child, sent = None, None, 0
        try:
            directory.mkdir()
            if shutil.disk_usage(self.workdir).free < MIN_FREE + MAX_INPUT:
                raise APIError('Ruang penyimpanan bebas perlu minimal 12 GB untuk mulai.')
            self.say(f'Mengunduh {job.name}…')
            info = self.api.call('getFile', file_id=message['document']['file_id'], request_timeout=1800)
            candidate = Path(info.get('file_path', ''))
            if not allowed_cache_file(candidate, self.cache, self.bot_key):
                raise APIError('Lokasi unduhan tidak sesuai. Periksa pengaturan Local Bot API.')
            source = candidate
            if not source.is_file() or source.stat().st_size > MAX_INPUT:
                raise APIError('Arsip tidak tersedia atau ukurannya melampaui batas.')
            if job.cancel.is_set():
                raise APIError('Proses dibatalkan.')
            job.phase = 'Mengekstrak'
            self.say('Mengekstrak arsip…')
            caption = message.get('caption', '')
            password = caption[9:].strip() if caption.lower().startswith('password:') else None
            # No token/API hash passed to the extraction subprocess.
            env = {'PATH': os.environ.get('PATH', ''), 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
            with (directory / 'error.txt').open('wb') as error_log:
                child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('extractor.py')),
                                          str(source), str(output)], stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL, stderr=error_log, env=env)
                child.stdin.write(json.dumps({'password': password, 'min_free': MIN_FREE}).encode() + b'\n')
                child.stdin.close()
                deadline = time.monotonic() + EXTRACT_TIMEOUT
                while child.poll() is None:
                    if job.cancel.is_set() or self.stopping.is_set() or time.monotonic() > deadline:
                        child.kill()
                        child.wait()
                        raise APIError('Proses dibatalkan atau melewati batas waktu satu jam.')
                    job.cancel.wait(0.25)
            if child.returncode:
                detail = (directory / 'error.txt').read_text(errors='replace').strip()
                # Worker prints controlled errors; never echo unexpected traceback or secret paths.
                if 'Traceback' in detail or len(detail) > 350:
                    detail = 'Arsip rusak atau format/enkripsinya belum didukung.'
                raise APIError(detail or 'Ekstraksi gagal.')
            files = sorted(p for p in output.rglob('*') if p.is_file())
            if not files:
                raise APIError('Arsip tidak berisi file biasa yang dapat dikirim.')
            job.phase = f'Mengirim {len(files)} file'
            self.say(f'Ekstraksi selesai. Mengirim {len(files)} file.\n'
                     'File di atas 2.000 MB akan dikirim sebagai beberapa bagian.')
            for index, path in enumerate(files, 1):
                for send_path, suffix in iter_send_files(path, parts, min_free=MIN_FREE):
                    if job.cancel.is_set() or self.stopping.is_set():
                        raise APIError('Proses dibatalkan.')
                    job.phase = f'Mengirim file {index}/{len(files)}{suffix}'
                    self.api.call('sendDocument', chat_id=self.owner, document=send_path.as_uri(),
                                  caption=(path.relative_to(output).as_posix() + suffix)[:900],
                                  request_timeout=3600)
                    sent += 1
                    job.cancel.wait(1)
            self.notify(f'Selesai. {sent} dokumen terkirim. File sementara dibersihkan.')
        except (APIError, ArchiveRejected) as exc:
            self.notify(f'{exc}\nSudah terkirim: {sent} dokumen. Anda dapat mengirim ulang arsip.')
        except Exception:
            # Exception text can include paths containing bot tokens; keep logs generic.
            self.notify(f'Proses gagal. Sudah terkirim: {sent} dokumen. Kirim ulang arsip untuk mencoba lagi.')
            print('Pekerjaan gagal; rincian yang dapat memuat rahasia tidak dicatat.', flush=True)
        finally:
            if child and child.poll() is None:
                child.kill()
                child.wait()
            shutil.rmtree(directory, ignore_errors=True)
            if source and allowed_cache_file(source, self.cache, self.bot_key):
                try:
                    source.unlink(missing_ok=True)
                except OSError:
                    pass
            self.job = None
            self.save_state()

    def run(self):
        for attempt in range(30):
            try:
                self.api.call('getMe')
                self.api.call('deleteWebhook')
                break
            except APIError:
                if attempt == 29:
                    raise
                self.stopping.wait(2)
        self.clean_cache()
        self.notify('Bot siap.\n' + ('Proses sebelum restart terhenti; kirim ulang arsip.\n' if self.interrupted else '') + HELP)
        self.save_state()
        next_cleanup = time.monotonic() + 3600
        while not self.stopping.is_set():
            try:
                updates = self.api.call('getUpdates', offset=self.offset, timeout=25,
                                        allowed_updates=['message'], request_timeout=35)
                for update in updates:
                    if update['update_id'] < self.offset:
                        continue
                    # Persist acceptance before starting work; a restart asks the owner to resend.
                    self.save_state(offset=update['update_id'] + 1)
                    self.handle(update.get('message', {}))
                if self.job is None and time.monotonic() >= next_cleanup:
                    self.clean_cache()
                    next_cleanup = time.monotonic() + 3600
            except APIError as exc:
                print(f'Koneksi Telegram perlu dicoba kembali (kode {exc.code}).', flush=True)
                self.stopping.wait(5)
        job = self.job
        if job:
            job.cancel.set()
            if job.thread:
                job.thread.join(20)


def main():
    token = os.environ.get('BOT_TOKEN', '')
    owner = os.environ.get('OWNER_ID', '')
    if not token or not owner.isdigit():
        raise SystemExit('Konfigurasi belum lengkap. Jalankan panduan setup terlebih dahulu.')
    bot = Bot(TelegramAPI(token), int(owner))
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: bot.stopping.set())
    try:
        bot.run()
    except Exception:
        raise SystemExit('Bot berhenti. Periksa konfigurasi, ruang disk, dan layanan Local Bot API.') from None


if __name__ == '__main__':
    main()

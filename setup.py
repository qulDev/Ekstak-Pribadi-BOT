"""Interactive VPS configuration; run in a terminal, never pass secrets as arguments."""
import getpass
import os
import re
import secrets
import sys
import time
from pathlib import Path

from bot import APIError, TelegramAPI


def save_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())


def configure(folder=Path('/config'), read_secret=getpass.getpass, read_input=input, api_factory=TelegramAPI):
    folder = Path(folder)
    envfile, marker = folder / '.env', folder / '.setup-complete'
    if envfile.exists() and marker.exists():
        print('Konfigurasi yang sudah ada dipakai kembali.')
        return
    if envfile.exists():
        values = dict(line.split('=', 1) for line in envfile.read_text().splitlines() if '=' in line)
        token = values['BOT_TOKEN']
        api = api_factory(token, 'https://api.telegram.org')
        print('Melanjutkan pemindahan bot ke Local Bot API.')
    else:
        print('Masukkan rahasia di terminal ini. Token dan hash tidak ditampilkan saat diketik.')
        token = read_secret('Token dari BotFather: ').strip()
        api_id = read_input('App api_id (angka): ').strip()
        api_hash = read_secret('App api_hash: ').strip()
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{24,}', token):
            raise ValueError('Format token BotFather tidak sesuai.')
        if not api_id.isdigit() or int(api_id) <= 0 or not re.fullmatch(r'[a-fA-F0-9]{32}', api_hash):
            raise ValueError('Format api_id atau api_hash tidak sesuai.')
        api = api_factory(token, 'https://api.telegram.org')
        identity = api.call('getMe')
        api.call('deleteWebhook')
        nonce = secrets.token_urlsafe(18)
        print(f"\nBuka https://t.me/{identity['username']} dari akun Telegram Anda.")
        print('Kirim pesan ini ke bot melalui CHAT PRIBADI (jangan ke grup):')
        print(f'\n/setup {nonce}\n')
        print('Menunggu pesan Anda, maksimal 10 menit…')
        offset, owner = 0, None
        deadline = time.monotonic() + 600
        while owner is None and time.monotonic() < deadline:
            updates = api.call('getUpdates', offset=offset, timeout=20, allowed_updates=['message'], request_timeout=30)
            for update in updates:
                offset = max(offset, update['update_id'] + 1)
                message = update.get('message', {})
                user, chat = message.get('from', {}), message.get('chat', {})
                if (message.get('text', '').strip() == f'/setup {nonce}'
                        and chat.get('type') == 'private' and not user.get('is_bot')
                        and user.get('id') == chat.get('id') and isinstance(user.get('id'), int)):
                    owner = user['id']
                    break
        if owner is None:
            raise ValueError('Pesan pendaftaran belum diterima. Jalankan setup kembali.')
        content = f'BOT_TOKEN={token}\nTELEGRAM_API_ID={api_id}\nTELEGRAM_API_HASH={api_hash}\nOWNER_ID={owner}\n'
        save_private(envfile, content)
        api.call('sendMessage', chat_id=owner, text='Akun Anda terdaftar sebagai pemilik. Lanjutkan pemasangan di terminal VPS.')
        print(f'Akun pemilik terdaftar: {owner}')
    # Official migration: cloud logout must precede local server usage.
    api.call('logOut')
    save_private(marker, 'Local Bot API migration ready.\n')
    print('Konfigurasi tersimpan dengan izin akses pribadi. Bot siap dijalankan di VPS.')


if __name__ == '__main__':
    try:
        configure()
    except (APIError, ValueError, KeyError, OSError) as exc:
        message = str(exc) if isinstance(exc, (APIError, ValueError)) else 'Gagal menyimpan konfigurasi.'
        raise SystemExit(message + '\nSetup belum selesai. Jangan bagikan isi file .env.') from None

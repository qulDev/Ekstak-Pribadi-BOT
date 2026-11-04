# Ekstrak Pribadi

Bot Telegram untuk mengekstrak arsip melalui chat pribadi. Kirim arsip ke bot,
lalu bot mengunduh, mengekstrak, dan mengirim kembali file hasilnya.
Akses dibatasi untuk satu akun pemilik.

**Status: implementasi awal, telah diuji lokal.** Belum ada pengujian lengkap
dengan Telegram nyata, transfer arsip 2 GB, atau pemasangan pada AlmaLinux 10.2.
Repository ini belum merupakan rilis produksi yang terverifikasi.

## Fitur

- Arsip masuk maksimal **2.000 MB** (2.000.000.000 byte, bukan 2 GiB).
- Ekstraksi ZIP, 7z, TAR, TAR.GZ, RAR, dan format yang didukung libarchive.
  ZIP, 7z, dan TAR.GZ sudah diuji dengan arsip nyata secara lokal; RAR belum diuji.
- Foto/video yang didukung dikirim sebagai media dengan preview; file lain sebagai
  dokumen. Jalur folder tetap dicantumkan pada caption.
- File hasil di atas 2.000 MB dibagi menjadi bagian maksimal 1.900 MB.
- Pendaftaran pemilik melalui pesan sekali pakai ke bot sendiri.
- Perintah bantuan, status proses, dan pembatalan.
- Pembatasan ukuran hasil, jumlah file, waktu ekstraksi, serta ruang disk.
- Pembersihan file sementara dan cache dokumen yang tertinggal.
- Docker Compose untuk bot dan Local Bot API, tanpa port yang dipublikasikan.

## Alur kerja

```text
Chat pribadi pemilik
        |
        v
Pemeriksaan akses dan ukuran arsip
        |
        v
Local Bot API mengunduh arsip ke volume bersama
        |
        v
Proses terpisah mengekstrak dan membatasi hasil
        |
        v
Bot mengirim foto, video, dokumen / bagian file besar
        |
        v
File sementara dibersihkan
```

Local Bot API digunakan karena batas unduh Bot API standar tidak mencukupi untuk
arsip 2 GB. Lihat [dokumentasi Telegram](https://core.telegram.org/bots/api#using-a-local-bot-api-server).

## Batas awal

| Pengaturan | Nilai |
| --- | --- |
| Ukuran arsip masuk | 2.000.000.000 byte |
| Total hasil ekstraksi | 20.000.000.000 byte |
| Jumlah file biasa | 300 per arsip |
| Jumlah entri, termasuk folder | 3.000 per arsip |
| Pekerjaan bersamaan | 1, tanpa antrean |
| Waktu ekstraksi | Maksimal 1 jam |
| Cadangan disk saat menulis hasil/bagian | 10.000.000.000 byte |
| Ukuran bagian file besar | 1.900.000.000 byte |
| Pembersihan cache dokumen tertinggal | Saat idle, umur lebih dari 4 jam |

Batas ditetapkan di `bot.py` dan `extractor.py`; belum bisa diubah melalui Telegram
atau `.env`. Cadangan disk diperiksa program, bukan kuota filesystem yang membatasi
seluruh penggunaan disk server.

## Persyaratan

- Bot khusus dari [@BotFather](https://t.me/BotFather).
- `api_id` dan `api_hash` sendiri dari [my.telegram.org](https://my.telegram.org),
  sesuai [panduan aplikasi Telegram](https://core.telegram.org/api/obtaining_api_id).
- Docker Engine dan plugin Docker Compose.
- Koneksi keluar ke Telegram dan registry paket/image.
- Minimal **35 GB ruang kosong** untuk lolos pemeriksaan pemasang otomatis.
- RAM 16 GB direkomendasikan untuk host. Batas memori bot dan API masing-masing
  6 GB dan 4 GB; kebutuhan aktual bergantung arsip dan penggunaan server lainnya.

`bootstrap.sh` khusus **AlmaLinux 10** dan memerlukan root. Image bot memakai
Linux/Python 3.13. Pengujian lokal menggunakan Docker Desktop Linux; paket dan
SELinux pada AlmaLinux masih perlu diverifikasi.

## Pengujian lokal

Tes tidak memerlukan token, `.env`, pendaftaran pemilik, atau VPS. Jalankan dari
folder repository:

```bash
docker build -t ekstrak-pribadi:local .
docker run --rm --network none ekstrak-pribadi:local python -m unittest discover -s tests -v
```

**Pemeriksaan terakhir: 38 tes lulus.** Cakupan meliputi ekstraksi ZIP/TAR.GZ/7z,
penolakan traversal/link, batas byte aktual, pemecahan file, akses pemilik,
pembatalan, pembersihan, pemilihan media/fallback, HTTP simulasi, dan wizard. Lihat bukti serta batas
verifikasi di [docs/verification.md](docs/verification.md).

Pemeriksaan sintaks pemasang:

```bash
docker run --rm --network none ekstrak-pribadi:local bash -n /app/bootstrap.sh
```

## Pemasangan pada AlmaLinux 10

Bagian ini dipakai saat sudah siap memasang. Tidak perlu dijalankan untuk membaca
kode, mengunggah repository, atau menjalankan tes lokal.

1. Clone repository ke server:

   ```bash
   git clone https://github.com/qulDev/Ekstak-Pribadi-BOT.git ekstrak-pribadi
   cd ekstrak-pribadi
   ```

   Jika Git belum tersedia, salin source melalui SCP atau gunakan arsip source
   layanan Git. Pemasang tidak menginstal Git.

2. Dari sesi root AlmaLinux, jalankan:

   ```bash
   bash bootstrap.sh
   ```

   Skrip memeriksa OS, ruang disk, dan konflik `podman-docker`; memasang Docker CE
   dari repositori RHEL; membangun image; menjalankan tes; membuka wizard; kemudian
   menjalankan layanan. Skrip tidak mematikan SELinux/firewall atau menghapus paket
   konflik otomatis. Kompatibilitas repo Docker harus diperiksa saat pemasangan.

3. Masukkan token BotFather, App `api_id`, dan App `api_hash` langsung di terminal.
   Token/hash tidak terlihat saat diketik. Buka tautan bot dari wizard, lalu kirim
   pesan `/setup ...` persis seperti instruksi melalui chat pribadi akun pemilik.

4. Wizard menyimpan `.env` dengan izin `600` dan penanda `.setup-complete`, lalu
   memindahkan bot dari cloud Bot API ke Local Bot API menggunakan `logOut`.
   Gunakan bot khusus karena setup juga menghapus webhook yang sudah ada.

5. Tunggu pesan **Bot siap**. Uji ZIP kecil terlebih dahulu, periksa hasilnya,
   kemudian naikkan ukuran pengujian secara bertahap.

Tidak perlu domain atau membuka port 8081 ke internet.

### Konfigurasi

[.env.example](.env.example) hanya menjelaskan nama variabel. Gunakan wizard;
mengisi `.env` manual saja tidak mendaftarkan pemilik atau memindahkan Bot API.

| Variabel | Kegunaan |
| --- | --- |
| `BOT_TOKEN` | Token bot dari BotFather |
| `TELEGRAM_API_ID` | ID aplikasi untuk Local Bot API |
| `TELEGRAM_API_HASH` | Hash aplikasi untuk Local Bot API |
| `OWNER_ID` | ID numerik pemilik yang didaftarkan wizard |

## Penggunaan

| Perintah / tindakan | Hasil |
| --- | --- |
| `/start` atau `/help` | Petunjuk penggunaan |
| Kirim arsip sebagai dokumen | Unduh, ekstrak, dan kirim hasil |
| `/status` | Tahap proses dan waktu berjalan |
| `/cancel` | Meminta pembatalan pekerjaan |

### Foto dan video dengan preview

Bot memilih cara kirim berdasarkan ekstensi, tanpa mengonversi file terlebih dahulu:

| File hasil | Cara kirim |
| --- | --- |
| `.jpg`, `.jpeg`, `.png`, `.webp` sampai 10.000.000 byte | Foto (`sendPhoto`) |
| `.mp4`, `.m4v`, `.mov` | Video (`sendVideo`) |
| Foto di atas batas tersebut, format lain, atau bagian `.part001` | Dokumen (`sendDocument`) |

Ekstensi tidak menjamin isinya valid. Telegram memeriksa isi, dimensi foto, dan
dukungan format video. Jika percobaan media ditolak dengan respons API `400` atau
`413`, bot mencoba sekali lagi sebagai dokumen, dengan caption yang sama.
Error koneksi, akses, rate limit, atau server tidak memicu fallback ini. Khusus
koneksi yang terputus, bot tidak tahu apakah media sudah diterima, sehingga tidak
langsung mengulang pengiriman sebagai dokumen.

Foto yang dikirim sebagai media dapat diproses ulang oleh Telegram; hasil yang
diterima tidak dijamin identik byte demi byte dengan gambar dalam arsip. Video
tidak dikonversi atau diberi thumbnail buatan bot. Preview/thumbnail dan kemampuan
pemutaran akhirnya bergantung Telegram, format, dan aplikasi penerima. Video yang
terpecah karena terlalu besar tetap perlu digabungkan dahulu.

Untuk arsip berpassword, gunakan caption berikut saat mengirim dokumen:

```text
password: KATA_SANDI_ARSIP
```

Opsi diteruskan ke libarchive; tidak semua enkripsi didukung. Encrypted 7z dan
beberapa varian RAR tidak dapat dibuka. Alur password belum diuji dengan arsip
terenkripsi nyata. Caption password tetap menjadi bagian pesan Telegram dan tidak
dihapus otomatis oleh bot.

Jalur folder dicantumkan pada caption; Telegram tidak membangun kembali struktur
folder secara otomatis. Folder kosong tidak dikirim. Arsip di dalam arsip dikirim
sebagai file tanpa ekstraksi rekursif.

### Menggabungkan file besar

Bagian `.part001`, `.part002`, dan seterusnya adalah potongan biner. Simpan semua
bagian dari pekerjaan yang sama dalam satu folder, lalu gabungkan sesuai urutan.

Linux:

```bash
cat -- video.mkv.part* > video.mkv
```

Command Prompt Windows, contoh dua bagian:

```bat
copy /b video.mkv.part001+video.mkv.part002 video.mkv
```

Tambahkan nama bagian lain jika ada.

## Mengelola layanan

Jalankan dari folder repository yang memiliki konfigurasi `.env`:

```bash
docker compose ps
docker compose logs --tail 50 bot
docker compose restart bot
docker compose stop
```

`stop` mempertahankan volume. Pekerjaan yang terhenti tidak dilanjutkan otomatis;
kirim ulang arsip setelah bot aktif. Jika gagal di tengah pengiriman, pengiriman
ulang dapat menghasilkan dokumen duplikat untuk hasil yang sebelumnya sudah masuk.

## Keamanan dan privasi

- Hanya ID pemilik di chat pribadi yang bisa memakai bot. Pengguna lain/grup diabaikan.
- Ekstraksi menerima file biasa/folder; menolak link, perangkat, jalur absolut,
  traversal `..`, dan nama file bertabrakan. Byte hasil dibatasi saat ditulis.
- Proses ekstraksi memiliki batas memori/waktu dan tidak menerima token melalui
  argumen atau environment.
- Bot/API berjalan sebagai UID `101`, filesystem utama read-only, tanpa Docker
  socket/capabilities. Layanan `init` sesaat memakai root untuk kepemilikan volume.
- Bot/API berbagi UID dan volume. Ekstraksi bukan sandbox container tersendiri;
  ini tidak menjamin isolasi terhadap celah pustaka pembaca arsip.
- File sementara dibersihkan setelah sukses/gagal/pembatalan. Pesan asli dan hasil
  yang sudah terkirim tetap berada di Telegram.
- Tidak ada pemindaian antivirus. Jangan menjalankan file hasil yang tidak dikenal.
- `.env`, `.setup-complete`, log, dan arsip paket dikecualikan dari Git/build.
  Output `docker compose config` tanpa `--quiet` mengandung rahasia; jangan bagikan.

## Kekurangan dan pekerjaan berikutnya

1. Belum ada pengujian dari Telegram asli sampai hasil diterima, termasuk transfer 2 GB.
2. Pemasangan Docker dan SELinux AlmaLinux 10.2 belum diuji di VPS nyata.
3. Belum ada antrean, resume setelah restart, atau retry pengiriman per file.
4. Pembatalan menunggu permintaan Telegram yang sudah berjalan. Timeout unduh/unggah
   masing-masing 30/60 menit; retry dapat menambah waktu tunggu.
5. Status belum menampilkan persentase, kecepatan transfer, atau estimasi selesai.
6. RAR dan skema enkripsi belum diuji; dukungan bergantung libarchive.
7. Batas operasi belum bisa dikonfigurasi. Pemulihan setup setelah `logOut`, rotasi
   token, dan penggantian pemilik belum diotomatisasi.
8. Cadangan disk dan pembersihan cache belum diverifikasi pada server nyata.
9. Lisensi belum ditentukan; berkas `LICENSE` belum tersedia.
10. Preview media belum diuji langsung di Telegram; tidak semua format video/foto
    dapat ditampilkan. Belum ada konversi video, thumbnail khusus, atau pilihan
    mengirim foto sebagai file asli tanpa pemrosesan Telegram.

## Struktur repository

```text
bot.py                    Telegram dan pengelolaan pekerjaan
extractor.py              Ekstraksi bertahap dan pemecahan hasil
setup.py                  Wizard kredensial dan pendaftaran pemilik
bootstrap.sh              Pemasang AlmaLinux 10
compose.yaml              Layanan, volume, dan batas sumber daya
Dockerfile                Image Python + libarchive
requirements.txt          Dependensi Python
.env.example              Nama konfigurasi tanpa kredensial
tests/                    Pengujian otomatis
docs/verification.md      Bukti dan batas pengujian
docs/design.md            Rancangan awal
docs/plan.md              Catatan implementasi awal
docs/media-preview.md     Rancangan dan pengujian pengiriman media
```

Image Local Bot API memakai kemasan pihak ketiga aiogram, dikunci ke digest;
versi yang diperiksa adalah Bot API 10.3. Image Python mengikuti tag
`python:3.13-slim-trixie`, sehingga hasil build dapat berubah mengikuti pembaruan
tag/paket sistem. Dependensi Python dikunci ke `libarchive-c==5.3`.

## Mengunggah ke Git

Unggah source dan dokumentasi. `.env.example` boleh disertakan karena kosong.
`ekstrak-pribadi.tar.gz` adalah hasil pengemasan lokal dan tidak perlu masuk Git.
Penanda `.setup-complete` harus dibuat kembali di setiap pemasangan.

Sebelum commit, periksa daftar dan isi perubahan:

```bash
git status --short
git diff --cached
```

Alamat remote, visibilitas repository, dan lisensi ditentukan pemilik proyek.

## Referensi

- [Telegram Local Bot API](https://core.telegram.org/bots/api#using-a-local-bot-api-server)
- [Source Telegram Bot API](https://github.com/tdlib/telegram-bot-api)
- [Docker Engine untuk RHEL](https://docs.docker.com/engine/install/rhel/)
- [Image aiogram/telegram-bot-api](https://github.com/aiogram/telegram-bot-api)
- [libarchive-c](https://github.com/Changaco/python-libarchive-c)

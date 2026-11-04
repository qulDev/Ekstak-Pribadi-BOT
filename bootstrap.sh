#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
umask 077

if [[ ${EUID} -ne 0 ]]; then
    printf '%s\n' 'Jalankan skrip ini dari sesi root VPS.' >&2
    exit 1
fi
source /etc/os-release
if [[ ${ID:-} != almalinux || ${VERSION_ID%%.*} != 10 ]]; then
    printf '%s\n' 'Paket ini disiapkan untuk AlmaLinux 10. Periksa OS sebelum melanjutkan.' >&2
    exit 1
fi
if [[ $(df -PB1 . | awk 'NR==2 {print $4}') -lt 35000000000 ]]; then
    printf '%s\n' 'Sediakan minimal 35 GB ruang kosong sebelum pemasangan.' >&2
    exit 1
fi
if rpm -q podman-docker >/dev/null 2>&1; then
    printf '%s\n' 'Ada paket podman-docker. Periksa konflik paket sebelum memasang Docker CE.' >&2
    exit 1
fi
if ! rpm -q docker-ce >/dev/null 2>&1; then
    dnf install -y dnf-plugins-core
    dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
    dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker compose version
docker build -t ekstrak-pribadi:local .
docker run --rm --network none ekstrak-pribadi:local python -m unittest discover -s tests -q

if [[ ! -f .setup-complete ]]; then
    docker run --rm -it --user 0:0 -v "$PWD:/config:Z" ekstrak-pribadi:local python setup.py
fi
chmod 600 .env
docker compose config --quiet
docker compose up -d
docker compose ps
printf '\n%s\n' 'Pemasangan dijalankan. Tunggu pesan "Bot siap" di Telegram, lalu coba arsip kecil dahulu.'

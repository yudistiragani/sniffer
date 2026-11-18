# Device baru dengan Magisk

## Tidak mengubah device existing

`android01` dan `android02` menggunakan `redroid/redroid:9.0.0_houdini`.
Nama tag itu tidak menyatakan Magisk. Tidak ada migrasi atau pemasangan Magisk
in-place pada dua device ini dalam scope awal.

Command create menerima image Magisk **yang sudah diaudit dan ada secara lokal**,
dari `--image` atau `redroid.image`. Tidak ada tag Magisk resmi yang diasumsikan
tersedia; image tidak otomatis di-pull/dibangun. Mekanisme build image otomatis
ditunda agar tidak menjalankan kode pihak ketiga tanpa review.

Referensi:
- Redroid upstream: https://github.com/remote-android/redroid-doc
- Build tooling pihak ketiga: https://github.com/ayasa520/redroid-script

Tooling kedua mendukung menambahkan Magisk, tetapi bukan jaminan kompatibilitas
semua kernel/Android/Houdini/Zygisk. Audit sumber dan pin commit/dependency;
verifikasi provenance APK/binary Magisk, jangan mengandalkan mutable tag.

## Checklist image

1. Cocokkan host amd64/arm64, kernel binder, Android version, native translation.
2. Pilih/build image dalam environment terisolasi; catat source commit dan checksum.
3. Masukkan tag lokal/digest ke `config/local.yaml`.
4. Buat device baru dengan nama, port, dan direktori data baru.
5. Start terpisah; tunggu boot, jalankan doctor, verifikasi Magisk/root secara manual.
6. Uji kompatibilitas app dan Appium. Jangan memindahkan data device lama sebagai tes.

```bash
uv run sniffer device create android03 --image your-audited-redroid-magisk:tag --adb-port 5557 --system-port 8203 --proxy-port 8083
uv run sniffer device start android03
uv run --all-extras sniffer doctor --device android03
```

`your-audited-redroid-magisk:tag` adalah placeholder, bukan image publik rekomendasi.
Create memakai `docker create` (stopped), loopback ADB, bind mount `/data`, ownership
label dan immutable container ID. Redroid membutuhkan privilege host yang besar;
jalankan hanya image terpercaya pada server yang memang disediakan untuk itu.
Konfigurasi default `boot_args` hanya resolusi/DPI: tambahkan argumen native bridge,
GPU, atau memfd yang memang dibutuhkan image yang diuji melalui YAML.

Tidak ada `--rm`, auto-recreate, data sharing antar-device, atau volume cleanup.
Jika create/register gagal sebagian, container stopped/data dapat tertinggal secara
sengaja agar tidak menghapus data. Inspeksi manual sebelum mencoba lagi. Batch juga
tidak melakukan destructive rollback. Setelah destroy, direktori data tetap ada dan
create dengan nama sama ditolak sampai operator memutuskan lokasi baru secara sadar.

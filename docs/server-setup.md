# Setup server

## 1. Inventory dahulu

Existing: STF, android01 (5555), android02 (5556), Android 9 Houdini berdasarkan
output Docker pengguna. Jangan recreate atau mengganti mount/data existing.
Periksa `docker inspect`, versi kernel/CPU, port, mount `/data`, label Compose,
dan akses ADB terlebih dahulu. Jalankan tool ini dari server Linux; koneksi lokal
Windows tidak otomatis dapat mencapai loopback server.

`doctor` memeriksa executable, package Python opsional, Appium `/status`, TCP
Beanstalk, port, Android boot/version/ABI, serta `magisk -v` jika tersedia.
Hasil Magisk "not verified" tidak membuktikan Magisk tidak ada: akses root mungkin
diperlukan. Doctor tidak menginstal CA, mereservasi job, atau mengubah trust.
ADB dapat memulai daemon lokalnya sendiri jika belum ada; tool tidak menjalankan
`adb kill-server` dan tidak mengganti ADB milik STF.

## 2. Appium

Instal Node LTS dan Appium server serta UiAutomator2 secara terpisah sesuai
compatibility matrix. **Existing Android 9 adalah API 28**; jangan otomatis
memasang driver terbaru yang mungkin membutuhkan Android lebih baru.

Referensi:
- https://appium.io/docs/en/latest/quickstart/
- https://github.com/appium/appium-uiautomator2-driver#requirements

Jalankan foreground melalui `sniffer appium start`, atau pakai server existing.
Default URL `http://127.0.0.1:4723`, tanpa legacy `/wd/hub`.
Gunakan systemPort berbeda per device. Appium `noReset=true`, `autoLaunch=false`,
`shouldTerminateApp=false`; tidak menghapus data akun. Verifikasi dengan Inspector.

## 3. Proxy dan CA

Default proxy listen host adalah loopback executor. Untuk Redroid, koneksi
`127.0.0.1` di Android bukan loopback Linux. Salah satu opsi adalah ADB reverse
per device, yang dapat diterapkan secara eksplisit:

```bash
uv run --all-extras sniffer provision --device android01 --reverse-port 8081 --proxy 127.0.0.1:8081
```

Command mengubah global proxy Android dan mapping ADB reverse yang disebut.
Tanpa opsi, provision hanya menghubungkan/check device, tidak memasang dependency.
Ini belum full provisioning image. Menghapus global proxy:

```bash
uv run --all-extras sniffer provision --device android01 --clear-proxy
```

Perintah clear tidak menghapus reverse mapping; mapping dapat diperiksa/dihapus
terpisah dengan ADB untuk serial/port yang tepat. Tidak ada reset seluruh forward.

Jika memilih proxy via Docker gateway, atur alamat yang benar-benar dapat dicapai
emulator. Membuka proxy di `0.0.0.0` membutuhkan firewall; jangan membuat open proxy.

mitmdump memakai `mitm_confdir`, default `.state/mitmproxy`, sehingga tidak
mengganti CA proxy existing secara diam-diam. Untuk memakai CA existing, arahkan
confdir ke direktori yang benar secara eksplisit. Backup dan lindungi key-nya.
Instal/trust CA pada emulator adalah langkah manual terotorisasi, **bukan bagian
Frida script atau efek otomatis command**. User CA belum tentu dipercaya app;
certificate pinning dan transport yang tidak memakai proxy dapat menghalangi
capture HTTPS. Jangan mengklaim sukses sebelum response nyata tertangkap.

## 4. Frida (opsional)

Siapkan frida-server yang kompatibel dengan versi client dan ABI aktual Android.
Houdini menerjemahkan ABI aplikasi; jangan menentukan frida-server dari ABI APK saja.
Frida root/server, port forwarding, dan startup server tidak dilakukan otomatis.

Pilih salah satu `frida_endpoint` (host:port reachable dari executor) atau
`frida_device_id`. Adapter tidak memakai `get_usb_device()` dan tidak menganggap
ADB serial sama dengan Frida ID. Pilih script resource lewat config, misalnya
`shared/observe.js` untuk smoke loader. Script contoh hanya mengirim PID/arch,
tidak menginstal CA atau mengubah validasi TLS.

Attach ke aplikasi running, atau spawn jika belum running; load script lalu resume
sebelum automation. Session dilepas saat selesai, aplikasi existing tidak di-kill.

## 5. Instagram dan Beanstalk

Login dilakukan manual. Periksa locator search dan results pada versi/bahasa app
yang dipakai. Default results element bukan bukti tipe data search tertentu.
Gunakan `--no-capture` untuk tes UI, kemudian capture terpisah, baru gabungkan.

Beanstalk default server loopback 11300, tube `sniffer.instagram`.
Override host/port via YAML atau `SNIFFER_BEANSTALK_HOST`/`SNIFFER_BEANSTALK_PORT`.
Beanstalk tidak menyediakan autentikasi/TLS dalam adapter ini: pakai jaringan
terpercaya atau tunnel, jangan publish ke internet. Jangan kirim credential di job.

Sebelum worker produksi, cocokkan producer dengan `examples/jobs/instagram.json`,
gunakan TTR >=120 detik, dan pastikan retry/bury dipantau operator.

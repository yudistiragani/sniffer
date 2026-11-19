# Media Sniffer

Base executor **Instagram keyword search** untuk Android/Redroid, dengan Appium,
capture mitmproxy, Frida opsional, dan worker Beanstalk. TikTok baru extension point.
Tidak ada API atau database server. Semua operasi device nyata dijalankan di server Linux.

**Baseline UI dan capture search sudah dibuktikan operator:** respons native
`TopSerpQuery` dengan keyword yang cocok terbaca di proxy remote melalui trial
TLS terarah yang disetujui, bukan bypass default. Parser lokal kini mendukung
struktur tersebut dan patch bertahapnya; integrasi recorder remote/worker dan
stabilitas berulang belum diterima. Trial tetap terpisah, opt-in dan 30 detik.
Integrasi tetap opt-in; tidak otomatis menghapus binary, menghentikan service,
atau mengubah CA existing.
Tim melaporkan Instagram 379 bermasalah pada search dan 416 bekerja tanpa proxy;
catat versi aktual sebelum menyimpulkan masalah selector atau mengganti APK.

## Quick start lokal

Python 3.12 dikelola oleh uv. Jalankan dari root repo:

```bash
uv sync --locked
uv run sniffer --help
uv run sniffer device list
uv run sniffer automation instagram search --device android01 --keyword "kopi lokal" --dry-run
uv run pytest -q
uv run ruff check .
```

`uv sync` menyediakan CLI, worker, dan tooling development. Untuk integrasi lengkap:

```bash
uv sync --locked --all-extras
uv run --all-extras sniffer --help
uv run --all-extras pytest -q
```

Extra terpisah: `automation` (Python Appium client), `capture` (mitmproxy),
`frida` (binding Python). Node/Appium server, driver UiAutomator2, ADB, Docker,
dan frida-server **tidak dipasang oleh uv**.

## Development lokal, execution server

Push/pull kode melalui Git seperti biasa. Repo ini tidak melakukan Git push,
deployment, SSH, atau operasi server secara otomatis.

1. Di server, jalankan `uv sync --locked --all-extras`.
2. Salin `config/example.yaml` menjadi `config/local.yaml`, lalu sesuaikan.
3. Jalankan `uv run --all-extras sniffer doctor --device android01`.
4. Ikuti [setup server](docs/server-setup.md) sebelum live capture/automation.

CLI memilih `config/local.yaml` jika ada, selain itu `config/example.yaml`.
Override eksplisit: `sniffer --config /path/config.yaml ...` atau `SNIFFER_CONFIG`.
Semua path relatif dalam YAML mengikuti **working directory**, bukan lokasi YAML.
Gunakan root repo sebagai working directory, atau path absolut.

Device contoh sudah terdaftar sebagai **adopted**:

| Device | ADB server-host endpoint | Appium systemPort | Proxy port |
| --- | --- | --- | --- |
| android01 | 127.0.0.1:5555 | 8201 | 8081 |
| android02 | 127.0.0.1:5556 | 8202 | 8082 |

Contoh tersebut berasal dari informasi pengguna, bukan hasil inspeksi live.
Jangan expose ADB ke internet. `localhost` server bukan `localhost` laptop.

## Command utama

### Instagram Search

```bash
uv run --all-extras sniffer automation instagram search --device android01 --keyword "kopi lokal" --scroll-count 5
```

Harus sudah login manual. Default: Appium existing, capture baru per job, tanpa
Frida. `--no-capture` untuk menguji UI saja; `--frida` memerlukan target dan script
di konfigurasi. `--dry-run` tidak menghubungi service atau membuat runtime output.

Selector Search/input/results adalah kandidat awal, **belum diverifikasi** terhadap
versi Instagram pengguna. Sesuaikan `platforms.instagram.selectors` lewat Appium
Inspector. Flow mengetik keyword, menekan Enter, menunggu elemen hasil, lalu scroll;
tidak memaksa kategori akun/hashtag/post tertentu.

**Parser `TopSerpQuery`** mencocokkan keyword request, menggabungkan patch bertahap,
dan menulis `posts.jsonl` tanpa duplikasi parent post per keyword. Endpoint lain
tetap `unmapped_json`. Capture kosong membuat job gagal. Flag verifikasi semantik
hanya true untuk respons search lengkap, HTTP 2xx, keyword cocok, dan post nonempty;
traffic background atau respons parsial tidak cukup.

Untuk body yang diekspor dari proxy remote, tersedia parsing offline tanpa
Appium/Frida/network. Lihat [format input, command, dan batas parser](docs/instagram-search-parsing.md).
Ini belum menghubungkan mitmweb remote ke worker.

### Satu run otomatis: 10 scroll → hasil ke Beanstalk

Mode opt-in baru `automation instagram collect --targeted-trial --publish` memakai
API mitmweb existing **read-only**, bukan ekspor manual/addon/restart proxy.
Perlu URL WEB API dan IP client Android yang terlihat oleh proxy, bukan hanya
alamat proxy Android. Trial terarah maksimum120s telah disetujui untuk mode ini;
default script standalone tetap30s dan worker lama tidak otomatis mengaktifkannya.

Satu message per post dikirim ke tube hasil terpisah. Outbox lokal menyimpan
receipt agar publish bisa dilanjutkan tanpa mengulang search. Consumer wajib
dedup `(job_id, keyword, id)` (at-least-once). Mode collect tidak membuat
`posts.jsonl`; payload adalah seluruh record post terstruktur tanpa wrapper. Lihat
[konfigurasi, command dan batas uji](docs/automated-collection.md).

### Capture saja / proxy independen

```bash
uv run --all-extras sniffer capture instagram --device android01 --duration 60
uv run --all-extras sniffer mitmproxy start instagram --device android01 --duration 3600
```

Tidak membuka aplikasi atau menjalankan Appium. `--raw` opt-in menyimpan traffic
**tanpa redaksi** ke `traffic.mitm`. Jangan menjalankan proxy standalone bersamaan
dengan automation capture pada device yang sama: keduanya memiliki lock.

Proxy existing boleh dipakai oleh device, tetapi recorder addon perlu dimuat saat
startup proxy; executor tidak dapat memasang addon ke proses arbitrary yang hidup.
MVP command di atas mengelola proses proxy-nya sendiri dan menolak port occupied.

### Worker Beanstalk

**Flow terbaru: engine mengirim keyword, proxy existing mengirim hasil.** Pakai
`worker-keywords` dengan input `{"keyword":"prabowo"}`. Frida trial hanya aktif
saat job berlangsung, kemudian dilepas; worker tidak membaca mitmweb API atau
mengirim hasil. Konfigurasi input tube/host harus mengikuti engine producer.
Detail, command first-run, ACK dan retry:
[worker keyword + proxy existing](docs/keyword-worker.md).

Worker berikut adalah mode legacy dengan kontrak dan capture lokal berbeda:

```bash
uv run --all-extras sniffer worker instagram --device android01
```

Satu worker per device; tube default `sniffer.instagram`. Payload:
[examples/jobs/instagram.json](examples/jobs/instagram.json).
Producer tidak disertakan; kontrak producer existing perlu dikonfirmasi.
Gunakan TTR **120 detik** atau lebih; worker melakukan `touch` lewat koneksi yang
memegang reservation. Payload invalid/TTR terlalu pendek di-bury. Error sementara
di-release dengan delay, maksimum tiga reserve default. `--once` untuk uji satu
reserve tanpa loop terus-menerus. SIGTERM/Ctrl+C membersihkan sesi; job unfinished
di-release jika koneksi masih memiliki reservation.

`job_id` wajib unik. Completion marker lokal ditulis setelah output selesai, sebelum
ACK. Redelivery payload sama menggunakan marker; ID sama dengan payload/options
berbeda di-bury. Ini **bukan exactly-once**: crash, restore state, atau multi-host
masih bisa menghasilkan pekerjaan/capture parsial atau duplikat.

### Device dan STF

```bash
uv run sniffer stf status
uv run sniffer stf start --yes
uv run sniffer device create android03 --image your-audited-redroid-magisk:tag --adb-port 5557 --system-port 8203 --proxy-port 8083
uv run sniffer device start android03
```

Image di atas **placeholder milik operator**, bukan tag publik yang dijamin ada.
Lihat [Redroid/Magisk](docs/redroid-magisk.md). `create` tidak pull image, tidak
start, tidak provision, dan menolak existing container/data path. `start` tidak
menjamin Android sudah boot atau Magisk berfungsi; verifikasi dengan `doctor`.

Batch stopped devices: gunakan `device create --prefix lab --count 2 --image ...`
dengan base port yang belum dipakai. Batch tidak transaksional: jika item berikutnya
gagal, item yang sudah dibuat dipertahankan, bukan dihapus sebagai rollback.

`device stop`, `device destroy --yes` hanya untuk device managed yang dibuat
project. Destroy memerlukan container sudah stopped, mempertahankan data, dan tidak
menghapus volume. **android01/android02 adopted tidak dapat di-destroy/start/stop
melalui lifecycle ini.** `device adopt` hanya mencatat metadata; `device forget`
hanya menghapus registrasi lokal adopted. Device adopted yang ada di YAML diubah
melalui konfigurasi lokal, bukan `forget`.

Untuk device baru di registry lokal, `device configure NAME --frida-endpoint ...`
atau `--appium-url ...` mengubah metadata koneksi tanpa mengganti ownership/container
ID. Jangan menduplikasi nama managed device ke YAML. Device baru belum otomatis
terdaftar ke STF; koneksi melalui ADB milik STF perlu disesuaikan dengan topologi
network server secara terpisah.

STF start hanya menyalakan existing container berlabel Compose project yang dipilih;
tidak menjalankan `compose up`, membuat stack, atau menghapus data.

## Output dan keamanan

Output per sesi: `session.json`, `events.jsonl`, `requests.jsonl` jika ada traffic,
`posts.jsonl` jika search dikenali,
`proxy.log`, optional `frida.jsonl`, `result.json` atau `failure.json`.
Standalone capture juga memiliki readiness/stop marker; raw capture hanya opt-in.

Redaksi field credential bersifat best-effort, bukan jaminan anonimisasi seluruh
body. JSON, URL path, keyword, log proxy/Appium, dan event script dapat mengandung
data pribadi. Batasi permission dan retention. Jangan commit:
`config/local.yaml`, `.state/`, `output/`, `data/`, CA/key, APK, atau akun.
`.state/mitmproxy` berisi CA yang dibuat mitmproxy, **bukan CA yang otomatis
dipercaya emulator**. Gunakan `mitm_confdir` yang konsisten.

File lock hanya melindungi proses pada host/state directory yang sama, bukan user
yang mengklik STF, aplikasi eksternal, atau worker di host lain.

## Dokumentasi

- [Setup server/proxy/Appium/Frida](docs/server-setup.md)
- [Operasi dan lifecycle](docs/operations.md)
- [Redroid dengan Magisk](docs/redroid-magisk.md)
- [Diagnostik TLS dengan Frida (tanpa bypass)](docs/frida-diagnostics.md)
- [Parsing hasil search GraphQL / offline export](docs/instagram-search-parsing.md)
- [Otomasi 10 scroll dan outgoing Beanstalk results](docs/automated-collection.md)
- [Worker keyword dan proxy existing](docs/keyword-worker.md)
- [Konteks dan aturan agent](.ai/AI_CONTEXT.md)
- [Arsitektur](.ai/ARCHITECTURE.md)
- [Task lanjutan](.ai/TASKS.md)

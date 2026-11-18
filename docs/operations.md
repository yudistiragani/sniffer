# Operational contract

## Independent modules

- STF status/start: hanya existing Compose project.
- Device adopt: catat metadata, tidak menghubungi runtime.
- Device create/start/stop/destroy: resource managed saja.
- Provision: opt-in ADB reverse/global proxy; tidak otomatis memasang CA/Magisk.
- Appium start: foreground server; tidak menjalankan Frida.
- mitmproxy start / capture: foreground recorder; tidak memerlukan UI automation.
- Automation: one-shot search; dapat menonaktifkan capture.
- Worker: loop Beanstalk memakai executor yang sama.

Stop foreground service menggunakan Ctrl+C atau SIGTERM. Service existing tidak
ikut dibunuh. Appium foreground wrapper hanya mengelola proses yang dimulainya.
Tidak ada background daemon/PID registry atau service manager baru dalam MVP.

## Locks and ports

Worker memegang device lock sepanjang hidupnya; executor menggunakan lease yang
sama (reentrant dalam thread yang sama). Standalone capture/provision/lifecycle
juga memakai device lock. Proxy/Appium memiliki lock port terpisah.
Semua command untuk satu host harus berbagi state_dir; menjalankan worker di
host/state_dir lain menghindari lock dan tidak didukung untuk device yang sama.
STF user/external automation tidak tercakup lock ini.

Port checks mencegah penggunaan port occupied; tidak otomatis mengambil alih
service yang tidak dikenal. Ada race inheren antara check dan bind terhadap proses
eksternal; readiness child tetap diverifikasi. Registry JSON ditulis atomically
di bawah file lock, bukan database server.

## Worker semantics

Reserved job divalidasi secara ketat. Fields tambahan/aksi selain search ditolak.
Hanya nama job aman yang dapat menjadi path completion marker.
Device, script, package, dan alamat infrastruktur tidak diterima dari job.

Heartbeat thread adalah satu-satunya pemakai reserving client selama eksekusi;
main thread tidak mengirim command client sampai thread berhenti.
Memakai koneksi kedua untuk touch salah karena bukan owner reservation.
Socket operations bounded; touch interval <= TTR/3. Reservation loss menghentikan
pekerjaan di checkpoint berikutnya dan tidak mengirim ACK. Blocking Appium calls
tidak dapat dibatalkan seketika; jangan menganggap ini fencing/distributed lock.

SIGTERM/Ctrl+C akan cleanup; forced kill tidak menjamin cleanup. Gunakan grace
period cukup untuk Appium/ADB/socket timeouts. Queue disconnect menutup koneksi
dan reconnect; reservation dilepas oleh server menurut protokol/TTR.

## Acceptance limits

Local/mock tests dapat memverifikasi schema, lifecycle protections, locks,
retry/ACK order, dan recorder. Local HTTP smoke bukan bukti HTTPS decryption,
Instagram API schema, selector UI, Magisk, Appium, atau STF live sudah berfungsi.
Semantic extraction dan TikTok search tetap follow-up eksplisit.

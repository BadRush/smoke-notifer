# 🔔 smoke-notifier

**SmokePing RRD Monitor → Telegram Alert with Graph**

Script sederhana yang berjalan di VPS SmokePing untuk memonitor file RRD,
mengevaluasi threshold (RTT, packet loss, jitter), dan mengirim alert otomatis
ke Telegram — lengkap dengan graph PNG 3 jam terakhir.

---

## ✨ Features

| Feature | Keterangan |
|---------|-----------|
| 📊 **RRD Monitoring** | Baca data SmokePing langsung dari file `.rrd` via `rrdtool` |
| 🔔 **Multi-level Alert** | OK → WARN → CRIT → DOWN, alert hanya saat status berubah |
| 📈 **Graph PNG** | Setiap alert disertai graph PNG (default 3 jam terakhir) |
| 📐 **Jitter Detection** | Monitoring jitter/standard deviation dari probe values |
| 🟢 **Recovery Alert** | Notif saat link recover + durasi downtime |
| ⚠️ **Flapping Detection** | Suppress alert jika link oscilating terlalu cepat |
| 💓 **Daily Heartbeat** | Summary harian jam 07:00 + graph 24h per link |
| 💾 **State Persistence** | Status tersimpan di JSON, aman saat restart service |
| 🔄 **Retry & Rate Limit** | 3x retry + max 20 msg/menit ke Telegram |
| 📝 **Log Rotation** | Auto rotate log file (5MB × 3 backup) |
| ⚙️ **YAML Config** | Konfigurasi rapi, environment variable untuk secrets |
| 🛡️ **Systemd Service** | Auto-start, auto-restart on failure |

---

## 📋 Prerequisites

- **OS**: Ubuntu/Debian (atau Linux dengan `apt`)
- **SmokePing**: sudah terinstall dan berjalan
- **Python**: >= 3.8
- **rrdtool**: CLI (`apt install rrdtool`)
- **Telegram Bot**: buat via [@BotFather](https://t.me/BotFather)

---

## 🚀 Quick Install

```bash
# 1. Clone / copy files ke VPS
git clone https://github.com/your-repo/smoke-notifier.git
cd smoke-notifier

# 2. Jalankan installer
sudo bash setup.sh
```

Installer akan:
1. ✅ Cek & install dependencies (Python3, pip3, rrdtool)
2. ✅ Install pip packages
3. ✅ Copy files ke `/opt/smoke-notifier/`
4. ✅ Tanya Telegram Bot Token & Chat ID
5. ✅ Test koneksi Telegram
6. ✅ Register & start systemd service

---

## ⚙️ Configuration

Edit `/opt/smoke-notifier/config.yaml`:

```yaml
# Telegram
telegram:
  bot_token: "123456:ABC..."    # dari @BotFather
  chat_id: "-1001234567890"     # group/channel ID
  # message_thread_id: 123     # (opsional) kirim ke thread/topic tertentu

# SmokePing
smokeping:
  rrd_base_path: "/var/lib/smokeping"
  check_interval: 60            # cek tiap 60 detik

# Graph
graph:
  enabled: true
  duration: "3h"                # 1h, 3h, 6h, 12h, 24h
  width: 800
  height: 250

# Link definitions
links:
  - label: "Upstream-A (Telkom)"
    rrd_path: "Upstream/TelkomA.rrd"    # relatif dari rrd_base_path
    warn_rtt: 30      # ms → WARNING
    crit_rtt: 80      # ms → CRITICAL
    warn_loss: 5      # %  → WARNING
    crit_loss: 20     # %  → CRITICAL
    warn_jitter: 10   # ms → WARNING (opsional)
    crit_jitter: 30   # ms → CRITICAL (opsional)
    num_probes: 20
```

### Kirim ke Thread/Topic Grup (opsional)

Jika grup Telegram kamu punya **Topics** (thread terpisah), bisa arahkan alert ke topic tertentu:

```yaml
telegram:
  bot_token: "123456:ABC..."
  chat_id: "-1001234567890"
  message_thread_id: 456       # ← ID topic di grup
```

**Cara dapat `message_thread_id`:**
1. Buka grup di **Telegram Desktop** atau **Web**
2. Klik topic yang diinginkan
3. Lihat URL: `https://t.me/c/1234567890/456` — angka terakhir (`456`) = thread ID
4. Atau forward pesan dari topic ke [@RawDataBot](https://t.me/RawDataBot), cari `message_thread_id`

> **Tip:** Kosongkan / hapus `message_thread_id` jika ingin kirim ke **General** topic atau chat biasa (bukan grup dengan Topics).

### Environment Variables (opsional)

Sensitive values bisa di-override via env var (berguna untuk CI/CD):

```bash
export SMOKE_TG_TOKEN="123456:ABC..."
export SMOKE_TG_CHAT_ID="-1001234567890"
export SMOKE_TG_THREAD_ID="456"        # opsional, untuk group topic
```

---

## 📡 Menambahkan Link Target

smoke-notifier **TIDAK** auto-detect semua target SmokePing.
Kamu harus **define manual** link mana saja yang mau di-monitor dan alert-nya.
Ini by design karena setiap link punya threshold berbeda.

### Step 1: Cari File RRD SmokePing

```bash
# List semua file .rrd yang ada
find /var/lib/smokeping -name "*.rrd" | sort

# Contoh output:
# /var/lib/smokeping/Backbone/Core01.rrd
# /var/lib/smokeping/Backbone/PWT-JKT.rrd
# /var/lib/smokeping/Backbone/PWT-SMG.rrd
# /var/lib/smokeping/Upstream/BiznetA.rrd
# /var/lib/smokeping/Upstream/TelkomA.rrd
# /var/lib/smokeping/Customer/ClientABC.rrd
```

> **Tip:** Struktur folder di RRD mengikuti hierarki target di `Targets` config SmokePing.
> Misal target `+ Backbone` → `++ PWT-JKT` menjadi `/var/lib/smokeping/Backbone/PWT-JKT.rrd`

### Step 2: Cek Data RRD (opsional)

Sebelum menambahkan, cek dulu data RTT normal link tersebut:

```bash
# Cek data 5 menit terakhir
rrdtool fetch /var/lib/smokeping/Backbone/PWT-JKT.rrd AVERAGE --start -300

# Output contoh:
#            median         loss    ping1    ping2 ...
# 1745789400: 3.456e-03  0.000e+00  2.1e-03  3.0e-03 ...
#              ↑ 3.456ms     ↑ 0 loss

# Cek statistik 24 jam terakhir untuk tentukan threshold
rrdtool graph /dev/null \
  --start -24h \
  DEF:m=/var/lib/smokeping/Backbone/PWT-JKT.rrd:median:AVERAGE \
  CDEF:ms=m,1000,* \
  VDEF:avg=ms,AVERAGE \
  VDEF:max=ms,MAXIMUM \
  PRINT:avg:"Avg RTT\: %6.2lf ms" \
  PRINT:max:"Max RTT\: %6.2lf ms" 2>&1 | tail -2
```

### Step 3: Tentukan Threshold

Gunakan panduan berikut untuk menentukan threshold:

| Jenis Link | warn_rtt | crit_rtt | warn_loss | crit_loss | Catatan |
|------------|----------|----------|-----------|-----------|---------|
| **Backbone internal** | 3-5 ms | 10-15 ms | 1-2% | 5-10% | Harus sangat ketat |
| **Upstream ISP lokal** | 10-30 ms | 50-80 ms | 3-5% | 15-20% | Tergantung SLA ISP |
| **Upstream internasional** | 50-100 ms | 150-200 ms | 5% | 20% | RTT tinggi itu normal |
| **VPN / tunnel** | 20-50 ms | 80-150 ms | 3-5% | 15% | Overhead enkripsi |
| **Customer link** | 5-15 ms | 30-50 ms | 2-3% | 10% | Sesuaikan SLA |

> **Rule of thumb:** `warn_rtt` = 2× RTT normal, `crit_rtt` = 5× RTT normal

### Step 4: Tambahkan ke config.yaml

```bash
sudo nano /opt/smoke-notifier/config.yaml
```

Tambahkan di bagian `links:`:

```yaml
links:
  # ─── Backbone ──────────────────────────────
  - label: "Backbone PWT-JKT"
    rrd_path: "Backbone/PWT-JKT.rrd"     # relatif dari rrd_base_path
    warn_rtt: 5
    crit_rtt: 15
    warn_loss: 2
    crit_loss: 10
    num_probes: 20

  - label: "Backbone PWT-SMG"
    rrd_path: "Backbone/PWT-SMG.rrd"
    warn_rtt: 5
    crit_rtt: 15
    warn_loss: 2
    crit_loss: 10
    num_probes: 20

  # ─── Upstream ──────────────────────────────
  - label: "Upstream Telkom"
    rrd_path: "Upstream/TelkomA.rrd"
    warn_rtt: 30
    crit_rtt: 80
    warn_loss: 5
    crit_loss: 20
    warn_jitter: 10        # opsional
    crit_jitter: 30        # opsional
    num_probes: 20

  # ─── Quick-add template (copy-paste) ───────
  # - label: "NAMA LINK"
  #   rrd_path: "Folder/NamaFile.rrd"
  #   warn_rtt: 20
  #   crit_rtt: 60
  #   warn_loss: 5
  #   crit_loss: 20
  #   num_probes: 20
```

### Step 5: Restart Service

```bash
# Validasi config dulu (dry-run)
python3 /opt/smoke-notifier/smokeping_monitor.py --config /opt/smoke-notifier/config.yaml --dry-run

# Kalau OK, restart service
sudo systemctl restart smoke-notifier

# Cek log
journalctl -u smoke-notifier -f
```

---

## 🔍 Cara Kerja

```
SmokePing → simpan data ke .rrd setiap 5 menit
                    ↓
smoke-notifier → baca .rrd tiap 60 detik via rrdtool
                    ↓
            evaluasi threshold per link
                    ↓
        status berubah? ── NO ──→ skip (tidak kirim)
              │ YES
              ↓
     generate graph PNG (3h)
              ↓
     kirim ke Telegram (photo + caption)
```

### Status Level

| Status | Kondisi | Emoji |
|--------|---------|-------|
| OK | Semua di bawah warning threshold | 🟢 |
| WARN | RTT ≥ warn_rtt ATAU loss ≥ warn_loss | 🟡 |
| CRIT | RTT ≥ crit_rtt ATAU loss ≥ crit_loss | 🟠 |
| DOWN | Tidak ada data / semua NaN | 🔴 |
| FLAPPING | Status berubah >4x dalam 10 menit | ⚠️ |

### Kapan Alert Dikirim?

- ✅ Status **berubah** (OK→WARN, WARN→CRIT, CRIT→OK, dll)
- ✅ **Recovery** (CRIT/DOWN→OK) — dengan durasi downtime
- ✅ **Flapping** — 1x alert lalu suppress
- ❌ Status **sama** — tidak kirim (anti spam)
- ❌ Dalam **cooldown** — tunggu 5 menit setelah alert terakhir

---

## 📱 Contoh Alert di Telegram

### Warning Alert
```
🟡 [WARN] Backbone PWT-JKT
─────────────────────
📊 RTT Median : 8.5 ms  (warn≥5 / crit≥15)
📉 Packet Loss: 0%   (warn≥2% / crit≥10%)
📐 Jitter     : 4.2 ms
🔄 Status    : 🟢OK → 🟡WARN
🕐 Waktu     : 2026-04-27 20:30:00
📎 [graph_3h.png]
```

### Recovery Alert
```
🟢 [RECOVERED] Backbone PWT-JKT
─────────────────────
📊 RTT Median : 2.1 ms  (warn≥5 / crit≥15)
📉 Packet Loss: 0%   (warn≥2% / crit≥10%)
⏱️ Durasi     : 45 menit
🔄 Status    : 🟠CRIT → 🟢OK
🕐 Waktu     : 2026-04-27 21:15:00
📎 [graph_3h.png]
```

---

## 🛠️ Commands

```bash
# Service management
systemctl status smoke-notifier       # cek status
systemctl restart smoke-notifier      # restart setelah edit config
systemctl stop smoke-notifier         # stop monitoring

# Logs
journalctl -u smoke-notifier -f       # live log
cat /opt/smoke-notifier/smoke-notifier.log

# Testing
python3 /opt/smoke-notifier/smokeping_monitor.py --test        # test kirim ke Telegram
python3 /opt/smoke-notifier/smokeping_monitor.py --dry-run     # test tanpa kirim alert

# Uninstall
sudo bash uninstall.sh
```

---

## 📁 File Locations

| File | Path |
|------|------|
| Script | `/opt/smoke-notifier/smokeping_monitor.py` |
| Config | `/opt/smoke-notifier/config.yaml` |
| State | `/opt/smoke-notifier/state.json` |
| Log | `/opt/smoke-notifier/smoke-notifier.log` |
| Graph temp | `/tmp/smoke-notifier/` |
| Service | `/etc/systemd/system/smoke-notifier.service` |

---

## 🗑️ Uninstall

```bash
sudo bash uninstall.sh
```

Uninstaller akan:
1. Konfirmasi
2. Backup config & state (opsional)
3. Stop & disable service
4. Hapus semua files
5. Cleanup pip packages (opsional)

---

## 🐛 Troubleshooting

### Alert tidak terkirim
```bash
# Cek log
journalctl -u smoke-notifier -f

# Test Telegram manual
python3 /opt/smoke-notifier/smokeping_monitor.py --test
```

### "rrdtool not found"
```bash
apt install rrdtool
```

### "RRD file tidak ditemukan"
```bash
# Cek path RRD smokeping
find /var/lib/smokeping -name "*.rrd" | head -20

# Sesuaikan rrd_base_path dan rrd_path di config.yaml
```

### Service crash loop
```bash
# Cek error
systemctl status smoke-notifier
journalctl -u smoke-notifier --no-pager -n 50

# Fix config lalu restart
nano /opt/smoke-notifier/config.yaml
systemctl restart smoke-notifier
```

---

## 📝 Changelog

### v1.0.0
- Initial release
- RRD monitoring with multi-level thresholds
- Telegram alerts with PNG graph attachment
- Flapping detection & cooldown
- Daily heartbeat summary
- State persistence
- Systemd service
- Interactive setup/uninstall scripts

---

## 📜 License

[MIT License](LICENSE)

Copyright (c) 2026 BadRush

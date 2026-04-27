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

### Environment Variables (opsional)

Sensitive values bisa di-override via env var (berguna untuk CI/CD):

```bash
export SMOKE_TG_TOKEN="123456:ABC..."
export SMOKE_TG_CHAT_ID="-1001234567890"
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

MIT

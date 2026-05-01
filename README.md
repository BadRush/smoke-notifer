# 🔔 smoke-notifier

**SmokePing RRD Monitor → Telegram Alert with Graph**

Script yang berjalan di VPS SmokePing untuk memonitor file RRD,
mengevaluasi threshold (RTT, packet loss, jitter), dan mengirim alert otomatis
ke Telegram — lengkap dengan graph PNG 3 jam terakhir.

---

## ✨ Features

| Feature                   | Keterangan                                                                    |
| ------------------------- | ----------------------------------------------------------------------------- |
| 📊 **RRD Monitoring**     | Baca data SmokePing langsung dari file `.rrd` via `rrdtool`                   |
| 🔔 **Multi-level Alert**  | OK → WARN → CRIT → DOWN, alert hanya saat status berubah                      |
| 🤖 **Interactive Bot**    | Fitur NOC! Mendukung command `/smoke-status` & Mute per-link via chat         |
| 🎛️ **Inline Keyboards**   | Alert otomatis menyertakan tombol interaktif untuk _Mute_ atau _Graph_ instan |
| 📈 **Graph PNG**          | Setiap alert disertai graph PNG (default 3 jam terakhir)                      |
| 📐 **Jitter Detection**   | Monitoring jitter/standard deviation dari probe values                        |
| 🟢 **Recovery Alert**     | Notif saat link recover + durasi downtime                                     |
| ⚠️ **Flapping Detection** | Suppress alert jika link oscilating terlalu cepat                             |
| 💓 **Daily Heartbeat**    | Summary harian jam 07:00 + graph 24h per link                                 |
| 💾 **State Persistence**  | Status tersimpan di JSON, aman saat restart service                           |
| 🔄 **Retry & Rate Limit** | 3x retry + max 20 msg/menit ke Telegram                                       |
| 📝 **Log Rotation**       | Auto rotate log file (5MB × 3 backup)                                         |
| 🔐 **`.env` Secrets**     | Sensitive config via `.env` file, YAML untuk operational config               |
| ⚙️ **Modular Package**    | Python package terstruktur, mudah di-maintain                                 |
| 🛡️ **Systemd Service**    | Auto-start, auto-restart on failure                                           |

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
git clone https://github.com/BadRush/smoke-notifer.git
cd smoke-notifer

# 2. Jalankan installer
sudo bash setup.sh
```

Installer akan:

1. ✅ Cek & install dependencies (Python3, pip3, rrdtool)
2. ✅ Install pip packages (requests, PyYAML, python-dotenv)
3. ✅ Copy package ke `/opt/smoke-notifier/`
4. ✅ Generate `.env` file (Telegram secrets)
5. ✅ Generate `config.yaml` (operational config)
6. ✅ Test koneksi Telegram
7. ✅ Register & start systemd service

---

## ⚙️ Configuration

### Secrets (`.env`)

Buat `.env` file dari template:

```bash
cp .env.example .env
nano .env
```

```env
# Telegram Bot — WAJIB diisi
SMOKE_TG_TOKEN=123456:ABC-DEF...
SMOKE_TG_CHAT_ID=-1001234567890

# Opsional
# SMOKE_TG_THREAD_ID=456
# SMOKE_RRD_BASE_PATH=/var/lib/smokeping
# SMOKE_CHECK_INTERVAL=60
```

> **Semua environment variables** di `.env` akan override nilai di `config.yaml`.

### Operational Config (`config.yaml`)

Edit `/opt/smoke-notifier/config.yaml`:

```yaml
# SmokePing
smokeping:
  rrd_base_path: "/var/lib/smokeping"
  check_interval: 60

# Graph
graph:
  enabled: true
  duration: "3h"
  width: 800
  height: 250

# Link definitions
links:
  - label: "Upstream-A (ISP-1)"
    rrd_path: "Upstream/ISP-1.rrd"
    warn_rtt: 30
    crit_rtt: 80
    warn_loss: 5
    crit_loss: 20
    warn_jitter: 10
    crit_jitter: 30
    num_probes: 20
```

### Environment Variable Reference

| Env Variable           | Config YAML Path             | Default                                  |
| ---------------------- | ---------------------------- | ---------------------------------------- |
| `SMOKE_TG_TOKEN`       | `telegram.bot_token`         | —                                        |
| `SMOKE_TG_CHAT_ID`     | `telegram.chat_id`           | —                                        |
| `SMOKE_TG_THREAD_ID`   | `telegram.message_thread_id` | `null`                                   |
| `SMOKE_RRD_BASE_PATH`  | `smokeping.rrd_base_path`    | `/var/lib/smokeping`                     |
| `SMOKE_CHECK_INTERVAL` | `smokeping.check_interval`   | `60`                                     |
| `SMOKE_GRAPH_ENABLED`  | `graph.enabled`              | `true`                                   |
| `SMOKE_GRAPH_DURATION` | `graph.duration`             | `3h`                                     |
| `SMOKE_STATE_FILE`     | `state_file`                 | `/opt/smoke-notifier/state.json`         |
| `SMOKE_LOG_FILE`       | `logging.file`               | `/opt/smoke-notifier/smoke-notifier.log` |

### Kirim ke Thread/Topic Grup (opsional)

```yaml
links:
  - label: "Cust-VIP"
    rrd_path: "Customer/Cust-VIP.rrd"
    chat_id: "-123456789" # Override kirim ke grup/user lain
    message_thread_id: 999 # Override kirim ke thread lain
```

### 🔗 Dependency (Mencegah Alert Storm)

Jika sebuah link bergantung pada link lain (misal: link customer di bawah link backbone), Anda bisa menambahkan `depends_on` agar tidak membanjiri notifikasi saat backbone bermasalah.

```yaml
links:
  - label: "Backbone Utama"
    rrd_path: "Backbone/Utama.rrd"

  - label: "Customer A"
    rrd_path: "Cust/A.rrd"
    depends_on: "Backbone Utama" # Alert akan di-suppress (UNREACHABLE) jika Backbone Utama DOWN/WARN
```

---

## 🤖 Interactive NOC Commands

Telegram bot bisa merespons chat di grup jika `listen_commands: true`:

| Command                       | Fungsi                                          |
| ----------------------------- | ----------------------------------------------- |
| `/smokestatus`                | Summary semua link, prioritaskan yang DOWN/WARN |
| `/smokemaint <durasi> [link]` | Mute alert selama durasi (contoh: `3h`, `30m`)  |
| `/smokemaint off`             | Matikan mode maintenance                        |
| `/smoke <durasi> <link>`      | Kirim graph instan ke grup                      |

Alert `DOWN`/`WARN` dilengkapi **tombol inline** untuk Mute atau Graph langsung!

---

## 📡 Menambahkan Link Target

### Step 1: Cari File RRD SmokePing

```bash
find /var/lib/smokeping -name "*.rrd" | sort
```

### Step 2: Cek Data RTT Normal

```bash
rrdtool fetch /var/lib/smokeping/Backbone/JKT-SBY.rrd AVERAGE --start -300
```

### Step 3: Tentukan Threshold

| Jenis Link                 | warn_rtt  | crit_rtt   | warn_loss | crit_loss |
| -------------------------- | --------- | ---------- | --------- | --------- |
| **Backbone internal**      | 3-5 ms    | 10-15 ms   | 1-2%      | 5-10%     |
| **Upstream ISP lokal**     | 10-30 ms  | 50-80 ms   | 3-5%      | 15-20%    |
| **Upstream internasional** | 50-100 ms | 150-200 ms | 5%        | 20%       |

### Step 4: Tambahkan ke config.yaml & Restart

```bash
nano /opt/smoke-notifier/config.yaml
python3 -m smoke_notifier --config /opt/smoke-notifier/config.yaml --dry-run
sudo systemctl restart smoke-notifier
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

| Status   | Kondisi                              | Emoji |
| -------- | ------------------------------------ | ----- |
| OK       | Semua di bawah warning threshold     | 🟢    |
| WARN     | RTT ≥ warn_rtt ATAU loss ≥ warn_loss | 🟡    |
| CRIT     | RTT ≥ crit_rtt ATAU loss ≥ crit_loss | 🟠    |
| DOWN     | Tidak ada data / semua NaN           | 🔴    |
| FLAPPING | Status berubah >4x dalam 10 menit    | ⚠️    |

---

## 🛠️ Commands

```bash
# Service management
systemctl status smoke-notifier
systemctl restart smoke-notifier
systemctl stop smoke-notifier

# Logs
journalctl -u smoke-notifier -f

# Testing
python3 -m smoke_notifier --test
python3 -m smoke_notifier --dry-run

# Uninstall
sudo bash uninstall.sh
```

---

## 📁 Project Structure

```
smoke-notifier/
├── .env.example              # Template environment variables
├── .gitignore
├── config.example.yaml       # Template operational config
├── pyproject.toml            # Python project metadata
├── requirements.txt
├── setup.sh                  # Interactive installer
├── uninstall.sh              # Uninstaller
├── smoke-notifier.service    # Systemd service
├── README.md
├── LICENSE
│
└── smoke_notifier/           # Python package
    ├── __init__.py            # Version & app name
    ├── __main__.py            # Entry point
    ├── config.py              # Config + .env loader
    ├── constants.py           # Status constants & emoji
    ├── state.py               # State persistence
    ├── rrd.py                 # RRD file reader
    ├── graph.py               # Graph generator
    ├── telegram.py            # Telegram notifier
    ├── alerts.py              # Alert builder & evaluator
    ├── commands.py            # Telegram commands
    ├── monitor.py             # Main monitor loop
    └── logging_setup.py       # Logging config
```

### Installed File Locations

| File       | Path                                         |
| ---------- | -------------------------------------------- |
| Package    | `/opt/smoke-notifier/smoke_notifier/`        |
| Config     | `/opt/smoke-notifier/config.yaml`            |
| Secrets    | `/opt/smoke-notifier/.env`                   |
| State      | `/opt/smoke-notifier/state.json`             |
| Log        | `/opt/smoke-notifier/smoke-notifier.log`     |
| Graph temp | `/tmp/smoke-notifier/`                       |
| Service    | `/etc/systemd/system/smoke-notifier.service` |

---

## 🗑️ Uninstall

```bash
sudo bash uninstall.sh
```

---

## 🐛 Troubleshooting

### Alert tidak terkirim

```bash
journalctl -u smoke-notifier -f
python3 -m smoke_notifier --test
```

### "rrdtool not found"

```bash
apt install rrdtool
```

### "RRD file tidak ditemukan"

```bash
find /var/lib/smokeping -name "*.rrd" | head -20
```

---

## 📝 Changelog

### v2.0.0

- **Modular package structure** — split monolith ke 12 modul terpisah
- **`.env` file support** — secrets via python-dotenv
- **Extended env override** — 17+ environment variables support
- **`pyproject.toml`** — modern Python project metadata
- **Entry point** — `python -m smoke_notifier` atau `smoke-notifier` CLI
- **Secure .env** — setup.sh generates `.env` with `chmod 600`
- **Updated systemd** — `EnvironmentFile` enabled

### v1.1.0

- Interactive NOC commands (`/smokestatus`, `/smokemaint`, `/smoke`)
- Inline keyboard buttons on alerts
- Maintenance/mute mode

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

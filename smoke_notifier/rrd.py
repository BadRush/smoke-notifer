"""
RRD Reader — fetch data from SmokePing RRD files via rrdtool CLI.
"""

import logging
import subprocess
from typing import Optional, Dict

log = logging.getLogger("smoke-notifier")


class RRDReader:
    """Read SmokePing RRD files via rrdtool CLI."""

    @staticmethod
    def fetch(rrd_file: str, num_probes: int = 20) -> Optional[dict]:
        """
        Fetch latest data from a SmokePing RRD file.

        SmokePing DS layout:
          - median : median RTT in seconds
          - loss   : number of lost packets (NOT percentage)
          - ping1..pingN : individual sorted probe RTTs in seconds

        Returns:
            {"median_rtt": float(ms), "loss_pct": float(%), "jitter": float(ms)}
            None on failure.
        """
        try:
            result = subprocess.run(
                [
                    "rrdtool", "fetch", rrd_file, "AVERAGE",
                    "--start", "-900", "--end", "now",
                ],
                capture_output=True, text=True, timeout=10,
            )

            if result.returncode != 0:
                log.error(f"rrdtool fetch error [{rrd_file}]: {result.stderr.strip()}")
                return None

            lines = result.stdout.strip().splitlines()
            if len(lines) < 3:
                log.warning(f"rrdtool returned too few lines for {rrd_file}")
                return None

            # Header line = DS names
            ds_names = lines[0].split()

            # Find last row with at least one non-NaN value
            data_rows = []
            for line in lines[2:]:
                stripped = line.strip()
                if not stripped or ":" not in stripped:
                    continue
                raw_vals = stripped.split(":")[1].strip().split()
                # Use .strip("-") to handle "-nan" values accurately
                if any(v.lower().strip("-") != "nan" for v in raw_vals):
                    data_rows.append(stripped)

            if not data_rows:
                log.warning(f"All NaN for {rrd_file} — link likely down")
                return {"median_rtt": None, "loss_pct": 100.0, "jitter": None}

            # Parse the most recent valid row
            last_row = data_rows[-1]
            raw_values = last_row.split(":")[1].strip().split()
            values: Dict[str, Optional[float]] = {}
            for name, val in zip(ds_names, raw_values):
                try:
                    # Strip leading sign for "nan" detection
                    is_nan = val.lower().strip("-") == "nan"
                    values[name] = float(val) if not is_nan else None
                except ValueError:
                    values[name] = None

            median_sec = values.get("median")
            loss_raw   = values.get("loss")

            if median_sec is None:
                return {"median_rtt": None, "loss_pct": 100.0, "jitter": None}

            median_ms = median_sec * 1000.0
            loss_pct  = (loss_raw / num_probes * 100.0) if loss_raw is not None else 0.0

            # Jitter = standard deviation of individual probe RTTs
            probe_ms = []
            for i in range(1, num_probes + 1):
                val = values.get(f"ping{i}")
                if val is not None and val > 0:
                    probe_ms.append(val * 1000.0)

            jitter = None
            if len(probe_ms) >= 2:
                mean = sum(probe_ms) / len(probe_ms)
                variance = sum((x - mean) ** 2 for x in probe_ms) / len(probe_ms)
                jitter = round(variance ** 0.5, 2)

            return {
                "median_rtt": round(median_ms, 2),
                "loss_pct":   round(loss_pct, 1),
                "jitter":     jitter,
            }

        except FileNotFoundError:
            log.error("rrdtool binary not found. Install: apt install rrdtool")
            return None
        except subprocess.TimeoutExpired:
            log.error(f"rrdtool fetch timeout for {rrd_file}")
            return None
        except Exception as e:
            log.error(f"Failed to read RRD {rrd_file}: {e}")
            return None

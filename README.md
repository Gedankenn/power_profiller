<p align="center">
  <img src="docs/block-diagram.svg" alt="Power Profiler" width="720">
</p>

<p align="center">
  <a href="https://github.com/espressif/esp-idf"><img src="https://img.shields.io/badge/ESP--IDF-v5.5-blue?logo=espressif" alt="ESP-IDF"></a>
  <a href="#"><img src="https://img.shields.io/badge/MCU-ESP32-red?logo=espressif" alt="ESP32"></a>
  <a href="https://github.com/Gedankenn/power_profiller/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
</p>

# Power Profiler

**Power Profiler** is a real-time voltage, current, and power monitoring tool built on ESP32 and the
INA226 precision current/power sensor. It streams CSV data over serial *and* serves a live Chart.js
web dashboard via WiFi — no external hosting, no cloud, no dependencies beyond the ESP32 itself.

Designed for profiling battery-powered devices, embedded circuits, and low-power electronics in the
0–36 V / 0–800 mA range.

<br>

## Table of Contents

- [Features](#features)
- [Hardware](#hardware)
  - [Bill of Materials](#bill-of-materials)
  - [Wiring — INA226 module to ESP32](#wiring--ina226-module-to-esp32)
  - [Shunt & load connections](#shunt--load-connections)
  - [Schematic](#schematic)
- [Build & Flash](#build--flash)
- [Web Dashboard](#web-dashboard)
- [Serial Output](#serial-output)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [License](#license)

<br>

## Features

| | | |
|---|---|---|
| **Current sensing** | INA226 (I2C, 16-bit ADC) with 0.1 Ω shunt — ~24 µA resolution, up to ±800 mA |
| **Voltage sensing** | INA226 VBUS pin — 0–36 V range, 1.25 mV LSB (also: ADC + resistive divider on GPIO34) |
| **Power calculation** | Hardware-computed by INA226 (VBUS × Current), 25× Current-LSB resolution |
| **Serial CSV** | `timestamp_ms,voltage_v,current_ma,power_mw` at 10 samples/s |
| **Web dashboard** | Real-time Chart.js graphs of voltage, current, power + accumulated energy (mWh) |
| **WiFi** | Connects to your home network, serves dashboard on port 80 |
| **Alert pin** | Configurable over-voltage/current/power alert via GPIO19 ISR |
| **Device verification** | Startup check of INA226 Manufacturer ID (0x5449) and Die ID (0x2260) |
| **I²C scan** | Scans bus on boot — auto-detects INA226 address (0x40, 0x41, 0x44, 0x45) |
| **Fully configurable** | Shunt value, voltage divider ratio, sample rate, WiFi — all `#define` |

<br>

## Hardware

### Bill of Materials

| Qty | Part | Notes |
|---:|---|---|
| 1× | ESP32 dev board | Any ESP32 with USB-UART |
| 1× | INA226 module | I²C current/power monitor (AliExpress modules: VCC, GND, SDA, SCL, ALE, VBS, IN+, IN-) |
| 1× | 0.1 Ω shunt resistor | Only if your INA226 module doesn't include one (most modules have it onboard) |
| 2× | 10 kΩ resistors | Voltage divider (optional — INA226 VBUS already measures voltage) |
| 1× | Breadboard + wires | |

### Wiring — INA226 module to ESP32

```
      INA226 Module                  ESP32 Dev Board
    ┌──────────────┐             ┌──────────────────┐
    │ VCC  ────────────────────── 3.3 V (or 5 V)    │
    │ GND  ────────────────────── GND                │
    │ SDA  ────────────────────── GPIO 21            │
    │ SCL  ────────────────────── GPIO 22            │
    │ ALE  ────────────────────── GPIO 19  (optional)│
    │ VBS  ──┐                                       │
    │ IN+  ──┤  (see shunt diagram below)            │
    │ IN-  ──┘                                       │
    └──────────────┘             └──────────────────┘
```

> **Note on VCC**: most INA226 modules from AliExpress/Amazon work with either 3.3 V or 5 V.
> If the I²C scan shows no device, try 5 V (VIN pin on the ESP32).

### Pinout table

| ESP32 | Signal | INA226 pin | Notes |
|------:|--------|-----------|-------|
| 3.3 V | Power | VCC | May also use 5 V |
| GND | Ground | GND | Common ground with DUT |
| GPIO 21 | I²C SDA | SDA | Internal pull-up enabled |
| GPIO 22 | I²C SCL | SCL | Internal pull-up enabled |
| GPIO 19 | Alert | ALE | Active-low, negative-edge ISR |
| GPIO 34 | ADC | *(divider tap)* | Input-only, no pull. Optional: external 10k/10k divider |

### Shunt & load connections

The INA226 measures current through a shunt resistor placed **in series** with the positive power
rail. The VBUS pin measures the voltage at the load side.

```
Power Source (5 V) ──[ 0.1 Ω shunt ]──┬── LOAD V+
                                      │
                    INA226            │
                    ┌────────┐        │
              IN+ ──┤        ├─ IN- ──┘
              VBS ──┤        │         (same node as IN-)
                    └────────┘

Power Source GND ──────────────────── LOAD V- (GND)
```

> **IN+** = source side of shunt · **IN-** = load side of shunt · **VBS** = same node as IN- (load side)

### Schematic

<p align="center">
  <img src="docs/schematic.svg" alt="Circuit schematic" width="780">
</p>

<br>

## Build & Flash

Requires [ESP-IDF](https://github.com/espressif/esp-idf) v5.x.

```bash
# One-time setup
. $IDF_PATH/export.sh
idf.py set-target esp32

# Build, flash & monitor
idf.py -p /dev/ttyUSB0 flash monitor
```

| | |
|---|---|
| Baud rate | 115200 |
| Exit monitor | `Ctrl+]` |
| Flash size | 1 MB app partition (19% free) |

### First boot

1. Edit `WIFI_SSID` / `WIFI_PASS` in `main/main.c:24-25`
2. `idf.py build && idf.py -p /dev/ttyUSB0 flash monitor`
3. Watch the serial output for the IP address
4. Open `http://<esp32-ip>/` in your browser

```text
I (5308) profiler: WiFi connected — IP: 192.168.5.98
I (2016) profiler: I2C bus scan:
I (2016) profiler:   Device found at 0x44
I (2024) profiler: INA226 ready at 0x44
```

<br>

## Web Dashboard

Point your browser to `http://<esp32-ip>/`. The dashboard updates automatically every second.

**What you see:**
- Three metric cards showing the latest **voltage (V)**, **current (mA)**, and **power (mW)**
- Three rolling line charts (30-second history) for voltage, current, and power
- Accumulated **energy (mWh)** — integral of power over time

**Technology**: HTML/CSS/JS served inline from `main/web_page.h` — no SPIFFS, no external files.
Chart.js loaded from CDN. Charts rendered client-side in the browser.

<p align="center">
  <em>Dashboard screenshot (coming soon)</em>
</p>

### API endpoints

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/` | Full HTML dashboard |
| `GET` | `/api/data` | `{"t":[...], "v":[...], "c":[...], "p":[...], "e":1.23}` — 300 samples |
| `GET` | `/api/latest` | `{"t":14237, "v":4.987, "c":8.37, "p":41.72, "e":0.05, "ip":"192.168.5.98"}` |

<br>

## Serial Output

CSV stream at **10 samples/second**:

```
timestamp_ms,voltage_v,current_ma,power_mw
1423,4.987,8.374,41.725
1523,4.985,8.350,41.520
```

| Column | Source | Description |
|--------|--------|-------------|
| `timestamp_ms` | FreeRTOS tick | Milliseconds since boot |
| `voltage_v` | INA226 VBUS | Bus voltage at the load |
| `current_ma` | INA226 Current Register | Current through shunt |
| `power_mw` | INA226 Power Register | Calculated power (VBUS × I) |

Pipe to a file or plot live:

```bash
idf.py -p /dev/ttyUSB0 monitor > data.csv
```

<br>

## Configuration

All parameters are `#define` at the top of `main/main.c`:

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `WIFI_SSID` | `"Stella"` | WiFi network name |
| `WIFI_PASS` | `"laedevoltaoutravez"` | WiFi password |
| `INA226_ADDR` | `0x44` | I²C address (auto-detected at boot) |
| `SHUNT_OHM` | `0.1` | Shunt resistor value (Ω) |
| `MAX_CURRENT_A` | `0.8` | Full-scale expected current |
| `DIVIDER_R1` | `10000.0` | Top resistor of external divider (Ω) |
| `DIVIDER_R2` | `10000.0` | Bottom resistor of external divider (Ω) |
| `SAMPLE_INTERVAL_MS` | `100` | Sampling period (10 Hz) |
| `INA226_ALERT_GPIO` | `19` | Alert interrupt pin |
| `INA226_ALERT_MASK` | `INA226_ALERT_POL` | Power over-limit alert |
| `INA226_ALERT_LIMIT` | `10000` | Alert threshold (power LSBs) |

<br>

## Project Structure

```
power_profiller/
├── main/
│   ├── main.c               # App entry: WiFi, HTTP server, sensor task, CSV
│   ├── web_page.h           # Inline HTML/JS dashboard (Chart.js, dark theme)
│   ├── bsp/
│   │   ├── ina226_bsp.h     # INA226 BSP — enums, config struct, full API
│   │   └── ina226_bsp.c     # INA226 driver — all 10 registers, alert ISR, verify
│   └── CMakeLists.txt
├── docs/
│   ├── schematic.svg        # Circuit schematic
│   ├── block-diagram.svg    # System architecture diagram
│   └── ina226.pdf           # TI INA226 datasheet
├── .gitignore
├── CMakeLists.txt            # Root ESP-IDF project
├── sdkconfig.defaults        # FreeRTOS 1000 Hz, WiFi STA, INFO log
├── AGENTS.md                 # OpenCode agent instructions
└── README.md
```

<br>

## License

MIT — see [LICENSE](LICENSE) for details.

# AGENTS.md

ESP32 firmware project for a power profiler — reads voltage and current from hardware sensors and generates consumption graphs.

## Build & Flash

Uses **ESP-IDF** (CMake-based).

```bash
. $IDF_PATH/export.sh         # or path to your esp-idf install
idf.py set-target esp32        # one-time
idf.py build                   # compile
idf.py -p /dev/ttyUSB0 flash   # flash
idf.py -p /dev/ttyUSB0 monitor # serial monitor (Ctrl+] to exit)
```

- **Baud rate**: 115200 (default)
- To build/flash/monitor in one shot: `idf.py -p /dev/ttyUSB0 flash monitor`

## Hardware

- **MCU**: ESP32
- **Current sensor**: INA226 (I2C addr 0x40) with 0.1 Ω shunt, handles up to ~500 mA with ~1.9 µA effective resolution (64-sample HW averaging)
- **Voltage sensing**: resistive voltage divider (10 kΩ / 10 kΩ, ratio 0.5) into ADC — reads 0–5 V range scaled to 0–2.5 V at the pin

### Pinout (editable in `main/main.c`)

| Signal   | GPIO | Notes                        |
| -------- | ---- | ---------------------------- |
| I2C SDA  | 21   | INA226 data                  |
| I2C SCL  | 22   | INA226 clock                 |
| Alert    | 19   | INA226 alert pin (active low, ISR) |
| V-div in | 34   | ADC1_CH6, input-only (no pull)|

## Output format

CSV over serial at ~36 samples/s **and** real-time web dashboard via WiFi:

```
timestamp_ms,voltage_v,current_ma,power_mw
```

- **Serial**: feed into `scripts/plot.py` (burst analysis + battery estimate) or any serial plotter.
- **Web**: connect to the ESP32's IP address on port 80 — live Chart.js dashboard with voltage/current/power graphs and accumulated energy (mWh).
- Web page is served inline from `main/web_page.h` (no SPIFFS needed).

## WiFi

Credentials are hardcoded `#define` at the top of `main/main.c`. Edit `WIFI_SSID` and `WIFI_PASS` before flashing.
WiFi init blocks up to 30 s; HTTP server starts only after connection.

## Conventions

- C99, ESP-IDF logging (`ESP_LOGI` / `ESP_ERROR_CHECK`), no Arduino layer.
- Pin assignments, shunt value, divider ratio, sample rate are `#define` at the top of `main/main.c`.
- INA226 driver lives in `main/bsp/ina226_bsp.h`/`.c` — full register coverage, alert ISR, private I2C helpers.
- Config enums and structs (`ina226_config_t`) match datasheet bit fields exactly.
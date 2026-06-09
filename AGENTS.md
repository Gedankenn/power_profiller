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
- **Current sensor**: INA226 (I2C addr 0x40) with 0.1 Ω shunt, handles up to ~800 mA with ~24 µA resolution
- **Voltage sensing**: resistive voltage divider (10 kΩ / 10 kΩ, ratio 0.5) into ADC — reads 0–5 V range scaled to 0–2.5 V at the pin

### Pinout (editable in `main/main.c`)

| Signal   | GPIO | Notes                        |
| -------- | ---- | ---------------------------- |
| I2C SDA  | 21   | INA226 data                  |
| I2C SCL  | 22   | INA226 clock                 |
| V-div in | 34   | ADC1_CH6, input-only (no pull)|

## Output format

CSV over serial at 10 samples/s:

```
timestamp_ms,voltage_v,current_ma,power_mw
```

Feed this into the companion plot script (`scripts/plot.py` – TODO) or pipe into the serial plotter of your choice.

## Conventions

- C99, ESP-IDF logging (`ESP_LOGI` / `ESP_ERROR_CHECK`), no Arduino layer.
- Pin assignments, shunt value, divider ratio, sample rate are `#define` at the top of `main/main.c`.
- `ina226.c` is a standalone driver; keep I2C routines private to it.

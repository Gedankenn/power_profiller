#pragma once

#include <stdint.h>
#include "driver/i2c.h"

typedef struct {
    i2c_port_t i2c_port;
    uint8_t i2c_addr;
    float shunt_resistance;   // ohms
    float max_expected_current; // amps
    float current_lsb;          // amps per LSB (computed)
} ina226_t;

esp_err_t ina226_init(ina226_t *dev, i2c_port_t port, uint8_t addr,
                       float shunt_resistance, float max_expected_current);

esp_err_t ina226_read_bus_voltage(ina226_t *dev, float *voltage_v);
esp_err_t ina226_read_shunt_voltage(ina226_t *dev, float *voltage_mv);
esp_err_t ina226_read_current(ina226_t *dev, float *current_a);
esp_err_t ina226_read_power(ina226_t *dev, float *power_w);

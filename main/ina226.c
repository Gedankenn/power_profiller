#include "ina226.h"
#include <math.h>

#define INA226_REG_CONFIG      0x00
#define INA226_REG_SHUNT_V     0x01
#define INA226_REG_BUS_V       0x02
#define INA226_REG_POWER       0x03
#define INA226_REG_CURRENT     0x04
#define INA226_REG_CALIBRATION 0x05

#define INA226_CONFIG_DEFAULT  0x4127

#define INA226_SHUNT_LSB_UV    2.5f   // 2.5 µV per LSB
#define INA226_BUS_LSB_MV      1.25f  // 1.25 mV per LSB

static esp_err_t write_reg(ina226_t *dev, uint8_t reg, uint16_t value) {
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev->i2c_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    i2c_master_write_byte(cmd, (value >> 8) & 0xFF, true);
    i2c_master_write_byte(cmd, value & 0xFF, true);
    i2c_master_stop(cmd);
    esp_err_t ret = i2c_master_cmd_begin(dev->i2c_port, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    return ret;
}

static esp_err_t read_reg(ina226_t *dev, uint8_t reg, uint16_t *value) {
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev->i2c_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev->i2c_addr << 1) | I2C_MASTER_READ, true);
    uint8_t hi = 0, lo = 0;
    i2c_master_read_byte(cmd, &hi, I2C_MASTER_ACK);
    i2c_master_read_byte(cmd, &lo, I2C_MASTER_NACK);
    i2c_master_stop(cmd);
    esp_err_t ret = i2c_master_cmd_begin(dev->i2c_port, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    *value = ((uint16_t)hi << 8) | lo;
    return ret;
}

esp_err_t ina226_init(ina226_t *dev, i2c_port_t port, uint8_t addr,
                       float shunt_resistance, float max_expected_current) {
    dev->i2c_port = port;
    dev->i2c_addr = addr;
    dev->shunt_resistance = shunt_resistance;
    dev->max_expected_current = max_expected_current;

    dev->current_lsb = max_expected_current / 32768.0f;

    uint16_t cal = (uint16_t)(0.00512f / (dev->current_lsb * shunt_resistance));
    if (cal < 1) cal = 1;
    if (cal > 0x7FFF) cal = 0x7FFF;

    esp_err_t ret;
    ret = write_reg(dev, INA226_REG_CONFIG, INA226_CONFIG_DEFAULT);
    if (ret != ESP_OK) return ret;
    ret = write_reg(dev, INA226_REG_CALIBRATION, cal);
    return ret;
}

esp_err_t ina226_read_bus_voltage(ina226_t *dev, float *voltage_v) {
    uint16_t raw;
    esp_err_t ret = read_reg(dev, INA226_REG_BUS_V, &raw);
    if (ret != ESP_OK) return ret;
    *voltage_v = ((raw >> 3) * INA226_BUS_LSB_MV) / 1000.0f;
    return ESP_OK;
}

esp_err_t ina226_read_shunt_voltage(ina226_t *dev, float *voltage_mv) {
    uint16_t raw;
    esp_err_t ret = read_reg(dev, INA226_REG_SHUNT_V, &raw);
    if (ret != ESP_OK) return ret;
    int16_t signed_raw = (int16_t)raw;
    *voltage_mv = signed_raw * INA226_SHUNT_LSB_UV / 1000.0f;
    return ESP_OK;
}

esp_err_t ina226_read_current(ina226_t *dev, float *current_a) {
    uint16_t raw;
    esp_err_t ret = read_reg(dev, INA226_REG_CURRENT, &raw);
    if (ret != ESP_OK) return ret;
    *current_a = (int16_t)raw * dev->current_lsb;
    return ESP_OK;
}

esp_err_t ina226_read_power(ina226_t *dev, float *power_w) {
    uint16_t raw;
    esp_err_t ret = read_reg(dev, INA226_REG_POWER, &raw);
    if (ret != ESP_OK) return ret;
    *power_w = raw * 25.0f * dev->current_lsb;
    return ESP_OK;
}

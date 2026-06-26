#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "driver/i2c.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ================================================================
 *  Configuration enums — matching datasheet bit field values
 * ================================================================ */

typedef enum {
    INA226_AVG_1    = 0b000,
    INA226_AVG_4    = 0b001,
    INA226_AVG_16   = 0b010,
    INA226_AVG_64   = 0b011,
    INA226_AVG_128  = 0b100,
    INA226_AVG_256  = 0b101,
    INA226_AVG_512  = 0b110,
    INA226_AVG_1024 = 0b111,
} ina226_avg_t;

typedef enum {
    INA226_CT_140us  = 0b000,
    INA226_CT_204us  = 0b001,
    INA226_CT_332us  = 0b010,
    INA226_CT_588us  = 0b011,
    INA226_CT_1100us = 0b100,
    INA226_CT_2116us = 0b101,
    INA226_CT_4156us = 0b110,
    INA226_CT_8244us = 0b111,
} ina226_conv_time_t;

typedef enum {
    INA226_MODE_PWRDOWN        = 0b000,
    INA226_MODE_SHUNT_TRIG     = 0b001,
    INA226_MODE_BUS_TRIG       = 0b010,
    INA226_MODE_SHUNT_BUS_TRIG = 0b011,
    INA226_MODE_PWRDOWN_ALT    = 0b100,
    INA226_MODE_SHUNT_CONT     = 0b101,
    INA226_MODE_BUS_CONT       = 0b110,
    INA226_MODE_SHUNT_BUS_CONT = 0b111,
} ina226_mode_t;

typedef struct {
    ina226_avg_t       avg;
    ina226_conv_time_t bus_ct;
    ina226_conv_time_t shunt_ct;
    ina226_mode_t      mode;
    float              shunt_resistance;
    float              max_expected_current;
} ina226_config_t;

/* ================================================================
 *  Alert event bit masks (Mask/Enable Register 06h)
 * ================================================================ */

#define INA226_ALERT_SOL   (1U << 15)   /* Shunt Overvoltage  */
#define INA226_ALERT_SUL   (1U << 14)   /* Shunt Undervoltage */
#define INA226_ALERT_BOL   (1U << 13)   /* Bus Overvoltage    */
#define INA226_ALERT_BUL   (1U << 12)   /* Bus Undervoltage   */
#define INA226_ALERT_POL   (1U << 11)   /* Power Overlimit    */
#define INA226_ALERT_CNVR  (1U << 10)   /* Conversion Ready   */

/* Read-only status flags in Mask/Enable Register */
#define INA226_FLAG_AFF    (1U << 4)    /* Alert Function Flag    */
#define INA226_FLAG_CVRF   (1U << 3)    /* Conversion Ready Flag  */
#define INA226_FLAG_OVF    (1U << 2)    /* Math Overflow Flag     */

/* Control bits in Mask/Enable Register */
#define INA226_CTRL_APOL   (1U << 1)    /* Alert Polarity (1=inverted) */
#define INA226_CTRL_LEN    (1U << 0)    /* Alert Latch Enable           */

/* Device identification (read-only) */
#define INA226_MANUFACTURER_ID  0x5449
#define INA226_DIE_ID           0x2260

/* ================================================================
 *  Handle
 * ================================================================ */

typedef struct {
    i2c_port_t       i2c_port;
    uint8_t          i2c_addr;
    float            current_lsb;
    ina226_config_t  config;
    /* Alert */
    gpio_num_t       alert_pin;
    TaskHandle_t      alert_task;
} ina226_handle_t;

/* ================================================================
 *  Core API
 * ================================================================ */

esp_err_t ina226_bsp_init(ina226_handle_t *h, i2c_port_t port, uint8_t addr,
                           const ina226_config_t *cfg);

esp_err_t ina226_bsp_deinit(ina226_handle_t *h);

esp_err_t ina226_bsp_reset(ina226_handle_t *h);

esp_err_t ina226_bsp_verify(ina226_handle_t *h);

esp_err_t ina226_bsp_read_bus_voltage(ina226_handle_t *h, float *voltage_v);

esp_err_t ina226_bsp_read_shunt_voltage(ina226_handle_t *h, float *voltage_mv);

esp_err_t ina226_bsp_read_current(ina226_handle_t *h, float *current_a);

esp_err_t ina226_bsp_read_power(ina226_handle_t *h, float *power_w);

esp_err_t ina226_bsp_set_config(ina226_handle_t *h, const ina226_config_t *cfg);

esp_err_t ina226_bsp_get_config(ina226_handle_t *h, ina226_config_t *cfg);

esp_err_t ina226_bsp_calibrate(ina226_handle_t *h, float shunt_ohm,
                                float max_current_a);

/* ================================================================
 *  Alert API (ISR-based)
 * ================================================================ */

esp_err_t ina226_bsp_alert_setup(ina226_handle_t *h, gpio_num_t alert_pin,
                                  uint16_t mask, uint16_t limit, bool latch);

esp_err_t ina226_bsp_alert_wait(ina226_handle_t *h, uint16_t *flags,
                                 TickType_t timeout);

esp_err_t ina226_bsp_alert_clear(ina226_handle_t *h);

esp_err_t ina226_bsp_alert_get_flags(ina226_handle_t *h, uint16_t *flags);

#ifdef __cplusplus
}
#endif

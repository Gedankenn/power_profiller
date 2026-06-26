#include "ina226_bsp.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "ina226_bsp";

/* ================================================================
 *  Register map
 * ================================================================ */

#define INA226_REG_CONFIG       0x00
#define INA226_REG_SHUNT_VOLT   0x01
#define INA226_REG_BUS_VOLT     0x02
#define INA226_REG_POWER        0x03
#define INA226_REG_CURRENT      0x04
#define INA226_REG_CALIBRATION  0x05
#define INA226_REG_MASK_ENABLE  0x06
#define INA226_REG_ALERT_LIMIT  0x07
#define INA226_REG_MANUFACT_ID  0xFE
#define INA226_REG_DIE_ID       0xFF

/* ================================================================
 *  Fixed LSB values (datasheet 7.1.2, 7.1.3)
 * ================================================================ */

#define INA226_SHUNT_LSB_UV    2.5f
#define INA226_BUS_LSB_MV      1.25f
#define INA226_POWER_LSB_FACTOR 25.0f

/* ================================================================
 *  Configuration register bit positions (datasheet 7.1.1)
 * ================================================================ */

#define INA226_CONFIG_RST       (1U << 15)
#define INA226_CONFIG_AVG_SHIFT  9
#define INA226_CONFIG_VBUSCT_SHIFT 6
#define INA226_CONFIG_VSHCT_SHIFT  3
#define INA226_CONFIG_MODE_SHIFT   0

/* ================================================================
 *  Private I2C helpers
 * ================================================================ */

static esp_err_t write_reg(ina226_handle_t *h, uint8_t reg, uint16_t value)
{
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (h->i2c_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    i2c_master_write_byte(cmd, (value >> 8) & 0xFF, true);
    i2c_master_write_byte(cmd, value & 0xFF, true);
    i2c_master_stop(cmd);
    esp_err_t ret = i2c_master_cmd_begin(h->i2c_port, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    return ret;
}

static esp_err_t read_reg(ina226_handle_t *h, uint8_t reg, uint16_t *value)
{
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (h->i2c_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (h->i2c_addr << 1) | I2C_MASTER_READ, true);
    uint8_t hi = 0, lo = 0;
    i2c_master_read_byte(cmd, &hi, I2C_MASTER_ACK);
    i2c_master_read_byte(cmd, &lo, I2C_MASTER_NACK);
    i2c_master_stop(cmd);
    esp_err_t ret = i2c_master_cmd_begin(h->i2c_port, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    *value = ((uint16_t)hi << 8) | lo;
    return ret;
}

/* ================================================================
 *  Build / parse configuration register value
 * ================================================================ */

static uint16_t config_to_reg(const ina226_config_t *cfg)
{
    return ((uint16_t)cfg->avg      << INA226_CONFIG_AVG_SHIFT)
         | ((uint16_t)cfg->bus_ct   << INA226_CONFIG_VBUSCT_SHIFT)
         | ((uint16_t)cfg->shunt_ct << INA226_CONFIG_VSHCT_SHIFT)
         | ((uint16_t)cfg->mode     << INA226_CONFIG_MODE_SHIFT);
}

static void reg_to_config(uint16_t raw, ina226_config_t *cfg)
{
    cfg->avg      = (raw >> INA226_CONFIG_AVG_SHIFT)   & 0x7;
    cfg->bus_ct   = (raw >> INA226_CONFIG_VBUSCT_SHIFT) & 0x7;
    cfg->shunt_ct = (raw >> INA226_CONFIG_VSHCT_SHIFT)  & 0x7;
    cfg->mode     = (raw >> INA226_CONFIG_MODE_SHIFT)   & 0x7;
}

/* ================================================================
 *  Alert ISR — wakes blocked task via binary semaphore
 * ================================================================ */

static void IRAM_ATTR alert_isr_handler(void *arg)
{
    ina226_handle_t *h = (ina226_handle_t *)arg;
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR(h->alert_sem, &woken);
    portYIELD_FROM_ISR(woken);
}

static bool gpio_isr_installed = false;

static esp_err_t alert_install_isr(ina226_handle_t *h)
{
    if (!gpio_isr_installed) {
        esp_err_t ret = gpio_install_isr_service(0);
        if (ret != ESP_OK) return ret;
        gpio_isr_installed = true;
    }
    return gpio_isr_handler_add(h->alert_pin, alert_isr_handler, h);
}

static esp_err_t alert_remove_isr(ina226_handle_t *h)
{
    return gpio_isr_handler_remove(h->alert_pin);
}

/* ================================================================
 *  Public API
 * ================================================================ */

esp_err_t ina226_bsp_init(ina226_handle_t *h, i2c_port_t port, uint8_t addr,
                           const ina226_config_t *cfg)
{
    if (!h || !cfg) return ESP_ERR_INVALID_ARG;

    if (cfg->shunt_resistance <= 0.0f || cfg->max_expected_current <= 0.0f)
        return ESP_ERR_INVALID_ARG;

    memset(h, 0, sizeof(*h));
    h->i2c_port = port;
    h->i2c_addr = addr;
    h->alert_pin = GPIO_NUM_NC;
    h->alert_sem = NULL;
    memcpy(&h->config, cfg, sizeof(*cfg));

    esp_err_t ret = write_reg(h, INA226_REG_CONFIG, config_to_reg(cfg));
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to write config register: %s", esp_err_to_name(ret));
        return ret;
    }

    h->current_lsb = cfg->max_expected_current / 32768.0f;

    uint16_t cal = (uint16_t)(0.00512f /
        (h->current_lsb * cfg->shunt_resistance));

    if (cal == 0) cal = 1;

    ret = write_reg(h, INA226_REG_CALIBRATION, cal);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to write calibration register: %s", esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "Initialized at 0x%02X, shunt=%.3f Ω, I_LSB=%.3f µA, CAL=%u",
             addr, cfg->shunt_resistance, h->current_lsb * 1e6f, cal);

    return ESP_OK;
}

esp_err_t ina226_bsp_deinit(ina226_handle_t *h)
{
    if (!h) return ESP_ERR_INVALID_ARG;

    if (h->alert_sem) {
        alert_remove_isr(h);
        vSemaphoreDelete(h->alert_sem);
        h->alert_sem = NULL;
    }
    return ESP_OK;
}

esp_err_t ina226_bsp_reset(ina226_handle_t *h)
{
    if (!h) return ESP_ERR_INVALID_ARG;

    esp_err_t ret = write_reg(h, INA226_REG_CONFIG, INA226_CONFIG_RST);
    if (ret != ESP_OK) return ret;

    /* Datasheet: RST bit self-clears; wait for reset to complete */
    vTaskDelay(pdMS_TO_TICKS(1));

    return ESP_OK;
}

esp_err_t ina226_bsp_verify(ina226_handle_t *h)
{
    if (!h) return ESP_ERR_INVALID_ARG;

    uint16_t mfr_id = 0, die_id = 0;
    esp_err_t ret;

    ret = read_reg(h, INA226_REG_MANUFACT_ID, &mfr_id);
    if (ret != ESP_OK) return ret;
    if (mfr_id != INA226_MANUFACTURER_ID) {
        ESP_LOGE(TAG, "Manufacturer ID mismatch: 0x%04X (expected 0x%04X)",
                 mfr_id, INA226_MANUFACTURER_ID);
        return ESP_ERR_NOT_FOUND;
    }

    ret = read_reg(h, INA226_REG_DIE_ID, &die_id);
    if (ret != ESP_OK) return ret;
    if (die_id != INA226_DIE_ID) {
        ESP_LOGE(TAG, "Die ID mismatch: 0x%04X (expected 0x%04X)",
                 die_id, INA226_DIE_ID);
        return ESP_ERR_NOT_FOUND;
    }

    ESP_LOGI(TAG, "Device verified: MFG=0x%04X DIE=0x%04X", mfr_id, die_id);
    return ESP_OK;
}

/* ---- Data reads ---- */

esp_err_t ina226_bsp_read_bus_voltage(ina226_handle_t *h, float *voltage_v)
{
    if (!h || !voltage_v) return ESP_ERR_INVALID_ARG;

    uint16_t raw = 0;
    esp_err_t ret = read_reg(h, INA226_REG_BUS_VOLT, &raw);
    if (ret != ESP_OK) return ret;

    *voltage_v = ((raw >> 3) * INA226_BUS_LSB_MV) / 1000.0f;
    return ESP_OK;
}

esp_err_t ina226_bsp_read_shunt_voltage(ina226_handle_t *h, float *voltage_mv)
{
    if (!h || !voltage_mv) return ESP_ERR_INVALID_ARG;

    uint16_t raw = 0;
    esp_err_t ret = read_reg(h, INA226_REG_SHUNT_VOLT, &raw);
    if (ret != ESP_OK) return ret;

    *voltage_mv = (int16_t)raw * INA226_SHUNT_LSB_UV / 1000.0f;
    return ESP_OK;
}

esp_err_t ina226_bsp_read_current(ina226_handle_t *h, float *current_a)
{
    if (!h || !current_a) return ESP_ERR_INVALID_ARG;

    uint16_t raw = 0;
    esp_err_t ret = read_reg(h, INA226_REG_CURRENT, &raw);
    if (ret != ESP_OK) return ret;

    *current_a = (int16_t)raw * h->current_lsb;
    return ESP_OK;
}

esp_err_t ina226_bsp_read_power(ina226_handle_t *h, float *power_w)
{
    if (!h || !power_w) return ESP_ERR_INVALID_ARG;

    uint16_t raw = 0;
    esp_err_t ret = read_reg(h, INA226_REG_POWER, &raw);
    if (ret != ESP_OK) return ret;

    *power_w = raw * INA226_POWER_LSB_FACTOR * h->current_lsb;
    return ESP_OK;
}

/* ---- Configuration ---- */

esp_err_t ina226_bsp_set_config(ina226_handle_t *h, const ina226_config_t *cfg)
{
    if (!h || !cfg) return ESP_ERR_INVALID_ARG;

    memcpy(&h->config, cfg, sizeof(*cfg));
    esp_err_t ret = write_reg(h, INA226_REG_CONFIG, config_to_reg(cfg));
    if (ret != ESP_OK) return ret;

    /* Recalculate current LSB if shunt or max current changed */
    h->current_lsb = cfg->max_expected_current / 32768.0f;

    return ESP_OK;
}

esp_err_t ina226_bsp_get_config(ina226_handle_t *h, ina226_config_t *cfg)
{
    if (!h || !cfg) return ESP_ERR_INVALID_ARG;

    uint16_t raw = 0;
    esp_err_t ret = read_reg(h, INA226_REG_CONFIG, &raw);
    if (ret != ESP_OK) return ret;

    reg_to_config(raw, cfg);
    return ESP_OK;
}

esp_err_t ina226_bsp_calibrate(ina226_handle_t *h, float shunt_ohm,
                                float max_current_a)
{
    if (!h) return ESP_ERR_INVALID_ARG;
    if (shunt_ohm <= 0.0f || max_current_a <= 0.0f)
        return ESP_ERR_INVALID_ARG;

    h->current_lsb = max_current_a / 32768.0f;
    h->config.shunt_resistance = shunt_ohm;
    h->config.max_expected_current = max_current_a;

    uint16_t cal = (uint16_t)(0.00512f /
        (h->current_lsb * shunt_ohm));
    if (cal == 0) cal = 1;

    return write_reg(h, INA226_REG_CALIBRATION, cal);
}

/* ---- Alert ---- */

esp_err_t ina226_bsp_alert_setup(ina226_handle_t *h, gpio_num_t alert_pin,
                                  uint16_t mask, uint16_t limit, bool latch)
{
    if (!h) return ESP_ERR_INVALID_ARG;

    /* Remove previous ISR if any */
    if (h->alert_sem) {
        alert_remove_isr(h);
        vSemaphoreDelete(h->alert_sem);
        h->alert_sem = NULL;
    }

    h->alert_sem = xSemaphoreCreateBinary();
    if (!h->alert_sem) return ESP_ERR_NO_MEM;

    h->alert_pin = alert_pin;

    uint16_t mask_val = mask;

    if (latch) mask_val |= INA226_CTRL_LEN;

    esp_err_t ret = write_reg(h, INA226_REG_ALERT_LIMIT, limit);
    if (ret != ESP_OK) goto fail;

    ret = write_reg(h, INA226_REG_MASK_ENABLE, mask_val);
    if (ret != ESP_OK) goto fail;

    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << alert_pin),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_NEGEDGE,
    };
    ret = gpio_config(&io_conf);
    if (ret != ESP_OK) goto fail;

    ret = alert_install_isr(h);
    if (ret != ESP_OK) goto fail;

    return ESP_OK;

fail:
    if (h->alert_sem) {
        vSemaphoreDelete(h->alert_sem);
        h->alert_sem = NULL;
    }
    return ret;
}

esp_err_t ina226_bsp_alert_wait(ina226_handle_t *h, uint16_t *flags,
                                 TickType_t timeout)
{
    if (!h || !h->alert_sem || !flags) return ESP_ERR_INVALID_ARG;

    if (xSemaphoreTake(h->alert_sem, timeout) != pdTRUE)
        return ESP_ERR_TIMEOUT;

    return ina226_bsp_alert_get_flags(h, flags);
}

esp_err_t ina226_bsp_alert_clear(ina226_handle_t *h)
{
    if (!h) return ESP_ERR_INVALID_ARG;

    uint16_t dummy;
    /* Reading Mask/Enable clears latched alert (datasheet 6.4.2) */
    return read_reg(h, INA226_REG_MASK_ENABLE, &dummy);
}

esp_err_t ina226_bsp_alert_get_flags(ina226_handle_t *h, uint16_t *flags)
{
    if (!h || !flags) return ESP_ERR_INVALID_ARG;

    uint16_t raw = 0;
    esp_err_t ret = read_reg(h, INA226_REG_MASK_ENABLE, &raw);
    if (ret != ESP_OK) return ret;

    *flags = raw & (INA226_FLAG_AFF | INA226_FLAG_CVRF | INA226_FLAG_OVF);
    return ESP_OK;
}

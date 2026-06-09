#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c.h"
#include "driver/adc.h"
#include "esp_adc_cal.h"
#include "esp_log.h"
#include "ina226.h"

static const char *TAG = "profiler";

/* ---- I2C (INA226) ---- */
#define I2C_PORT        I2C_NUM_0
#define I2C_SDA_GPIO    21
#define I2C_SCL_GPIO    22
#define I2C_FREQ_HZ     100000
#define INA226_ADDR     0x40
#define SHUNT_OHM       0.1f
#define MAX_CURRENT_A   0.8f

/* ---- ADC (voltage divider) ---- */
#define ADC_CHANNEL     ADC1_CHANNEL_6   // GPIO34
#define ADC_ATTEN       ADC_ATTEN_DB_11  // ~0–3.3 V range
#define ADC_WIDTH       ADC_WIDTH_BIT_12
#define DIVIDER_R1      10000.0f  // top resistor (ohms)
#define DIVIDER_R2      10000.0f  // bottom resistor (ohms)

/* ---- Sample interval ---- */
#define SAMPLE_INTERVAL_MS  100

static esp_adc_cal_characteristics_t adc_chars;

static void i2c_init(void) {
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_SDA_GPIO,
        .scl_io_num = I2C_SCL_GPIO,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_FREQ_HZ,
    };
    ESP_ERROR_CHECK(i2c_param_config(I2C_PORT, &conf));
    ESP_ERROR_CHECK(i2c_driver_install(I2C_PORT, conf.mode, 0, 0, 0));
}

static void adc_init(void) {
    adc1_config_width(ADC_WIDTH);
    adc1_config_channel_atten(ADC_CHANNEL, ADC_ATTEN);
    esp_adc_cal_characterize(ADC_UNIT_1, ADC_ATTEN, ADC_WIDTH, 1100, &adc_chars);
}

static float read_voltage_divider(void) {
    uint32_t sum = 0;
    for (int i = 0; i < 16; i++) {
        sum += adc1_get_raw(ADC_CHANNEL);
    }
    uint32_t avg = sum / 16;
    uint32_t mv = esp_adc_cal_raw_to_voltage(avg, &adc_chars);
    return (mv / 1000.0f) * ((DIVIDER_R1 + DIVIDER_R2) / DIVIDER_R2);
}

void app_main(void) {
    ESP_LOGI(TAG, "Power profiler starting");

    i2c_init();
    adc_init();

    ina226_t ina;
    ESP_ERROR_CHECK(ina226_init(&ina, I2C_PORT, INA226_ADDR, SHUNT_OHM, MAX_CURRENT_A));

    printf("timestamp_ms,voltage_v,current_ma,power_mw\n");

    while (1) {
        float v_shunt_mv = 0, v_bus = 0, current_a = 0, power_w = 0;
        float v_ext = 0;

        ina226_read_shunt_voltage(&ina, &v_shunt_mv);
        ina226_read_bus_voltage(&ina, &v_bus);
        ina226_read_current(&ina, &current_a);
        ina226_read_power(&ina, &power_w);
        v_ext = read_voltage_divider();

        uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
        printf("%lu,%.3f,%.3f,%.3f\n",
               now, v_ext, current_a * 1000.0f, power_w * 1000.0f);

        vTaskDelay(pdMS_TO_TICKS(SAMPLE_INTERVAL_MS));
    }
}

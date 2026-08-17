#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "driver/i2c.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "lwip/sockets.h"
#include "bsp/ina226_bsp.h"
#include "web_page.h"

static const char *TAG = "profiler";

/* ---- WiFi ---- */
#define WIFI_SSID   "Stella"
#define WIFI_PASS   "laedevoltaoutravez"
#define WIFI_CONNECTED_BIT  BIT0
#define WIFI_FAIL_BIT       BIT1

/* ---- I2C (INA226) ---- */
#define I2C_PORT        I2C_NUM_0
#define I2C_SDA_GPIO    21
#define I2C_SCL_GPIO    22
#define I2C_FREQ_HZ     100000
#define INA226_ADDR     0x44
#define SHUNT_OHM       0.1f
#define MAX_CURRENT_A   0.5f

/* ---- Alert ---- */
#define INA226_ALERT_GPIO    GPIO_NUM_19
#define INA226_ALERT_MASK    (INA226_ALERT_POL)
#define INA226_ALERT_LIMIT   10000
#define INA226_ALERT_LATCH   true

/* ---- ADC (voltage divider) ---- */
#define ADC_UNIT        ADC_UNIT_1
#define ADC_CHANNEL     ADC_CHANNEL_6   // GPIO34
#define ADC_ATTEN       ADC_ATTEN_DB_12
#define ADC_BITWIDTH    ADC_BITWIDTH_12
#define DIVIDER_R1      10000.0f
#define DIVIDER_R2      10000.0f

/* ---- Sample interval ---- */
#define SAMPLE_INTERVAL_MS  28   // ~36 Hz

/* ---- Ring buffer ---- */
#define HISTORY_SIZE  300

typedef struct {
    float    voltage_v;
    float    current_ma;
    float    power_mw;
    uint32_t timestamp_ms;
} sample_t;

static sample_t history[HISTORY_SIZE];
static int      history_write;     // next slot to write
static int      history_count;     // valid entries (≤ HISTORY_SIZE)
static float    energy_mwh;
static SemaphoreHandle_t history_mutex;
static bool ina_present = false;

static adc_oneshot_unit_handle_t adc_handle;
static adc_cali_handle_t        adc_cali;
static EventGroupHandle_t wifi_event_group;

/* ================================================================
 *  Hardware init
 * ================================================================ */

static void i2c_init(void)
{
    i2c_config_t conf = {
        .mode          = I2C_MODE_MASTER,
        .sda_io_num    = I2C_SDA_GPIO,
        .scl_io_num    = I2C_SCL_GPIO,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_FREQ_HZ,
    };
    ESP_ERROR_CHECK(i2c_param_config(I2C_PORT, &conf));
    ESP_ERROR_CHECK(i2c_driver_install(I2C_PORT, conf.mode, 0, 0, 0));
}

static void i2c_scan(void)
{
    ESP_LOGI(TAG, "I2C bus scan:");
    for (uint8_t addr = 1; addr < 127; addr++) {
        i2c_cmd_handle_t cmd = i2c_cmd_link_create();
        i2c_master_start(cmd);
        i2c_master_write_byte(cmd, (addr << 1) | I2C_MASTER_WRITE, true);
        i2c_master_stop(cmd);
        esp_err_t ret = i2c_master_cmd_begin(I2C_PORT, cmd, pdMS_TO_TICKS(50));
        i2c_cmd_link_delete(cmd);
        if (ret == ESP_OK) {
            ESP_LOGI(TAG, "  Device found at 0x%02X", addr);
        }
    }
    ESP_LOGI(TAG, "I2C scan complete");
}

static void adc_init(void)
{
    adc_oneshot_unit_init_cfg_t unit_cfg = {
        .unit_id = ADC_UNIT,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_cfg, &adc_handle));

    adc_oneshot_chan_cfg_t chan_cfg = {
        .atten   = ADC_ATTEN,
        .bitwidth = ADC_BITWIDTH,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc_handle, ADC_CHANNEL, &chan_cfg));

    adc_cali_line_fitting_config_t cali_cfg = {
        .unit_id      = ADC_UNIT,
        .atten        = ADC_ATTEN,
        .bitwidth     = ADC_BITWIDTH,
        .default_vref = 1100,
    };
    ESP_ERROR_CHECK(adc_cali_create_scheme_line_fitting(&cali_cfg, &adc_cali));
}

static float read_voltage_divider(void)
{
    int sum = 0, raw = 0;
    for (int i = 0; i < 16; i++) {
        adc_oneshot_read(adc_handle, ADC_CHANNEL, &raw);
        sum += raw;
    }
    int avg = sum / 16;
    int mv  = 0;
    adc_cali_raw_to_voltage(adc_cali, avg, &mv);
    return (mv / 1000.0f) * ((DIVIDER_R1 + DIVIDER_R2) / DIVIDER_R2);
}

/* ================================================================
 *  WiFi
 * ================================================================ */

static void wifi_event_handler(void *arg, esp_event_base_t base,
                                int32_t id, void *event_data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi disconnected, reconnecting...");
        esp_wifi_connect();
        xEventGroupClearBits(wifi_event_group, WIFI_CONNECTED_BIT);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "WiFi connected — IP: " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init_sta(void)
{
    wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                            &wifi_event_handler, NULL,
                                                            &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                            &wifi_event_handler, NULL,
                                                            &instance_got_ip));

    wifi_config_t wifi_cfg = { .sta = { .ssid = WIFI_SSID, .password = WIFI_PASS } };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t bits = xEventGroupWaitBits(wifi_event_group,
                                            WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                                            pdFALSE, pdFALSE,
                                            pdMS_TO_TICKS(30000));
    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "WiFi ready");
    } else {
        ESP_LOGE(TAG, "WiFi connection failed after 30 s");
    }
}

/* ================================================================
 *  HTTP handlers
 * ================================================================ */

static esp_err_t root_handler(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    httpd_resp_send(req, INDEX_HTML, strlen(INDEX_HTML));
    return ESP_OK;
}

static esp_err_t api_latest_handler(httpd_req_t *req)
{
    xSemaphoreTake(history_mutex, pdMS_TO_TICKS(200));

    int n = history_count;
    int idx = (n > 0) ? ((history_write - 1 + HISTORY_SIZE) % HISTORY_SIZE) : 0;
    sample_t s = {0};
    float e = energy_mwh;
    if (n > 0) s = history[idx];

    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_ip_info_t ip;
    char ip_str[16] = "--";
    if (netif && esp_netif_get_ip_info(netif, &ip) == ESP_OK) {
        snprintf(ip_str, sizeof(ip_str), IPSTR, IP2STR(&ip.ip));
    }

    xSemaphoreGive(history_mutex);

    char buf[256];
    int len = snprintf(buf, sizeof(buf),
        "{\"t\":%lu,\"v\":%.3f,\"c\":%.3f,\"p\":%.3f,\"e\":%.3f,\"ip\":\"%s\"}",
        s.timestamp_ms, s.voltage_v, s.current_ma, s.power_mw, e, ip_str);

    httpd_resp_set_type(req, "application/json");
    httpd_resp_send(req, buf, len);
    return ESP_OK;
}

static esp_err_t api_data_handler(httpd_req_t *req)
{
    if (history_count == 0) {
        httpd_resp_set_type(req, "application/json");
        httpd_resp_sendstr(req, "{\"t\":[],\"v\":[],\"c\":[],\"p\":[],\"e\":0.0}");
        return ESP_OK;
    }

    xSemaphoreTake(history_mutex, pdMS_TO_TICKS(200));

    int n = history_count;
    int start = (n < HISTORY_SIZE) ? 0 : history_write;
    float e = energy_mwh;

    /* Allocate buffer large enough for ~300 samples × 4 arrays */
    char *buf = malloc(16384);
    if (!buf) {
        xSemaphoreGive(history_mutex);
        httpd_resp_send_500(req);
        return ESP_ERR_NO_MEM;
    }

    int pos = 0;
#define APPEND(...) pos += snprintf(buf + pos, 16384 - pos, __VA_ARGS__)

    APPEND("{\"t\":[");
    for (int i = 0; i < n; i++) {
        APPEND("%s%lu", i > 0 ? "," : "",
               history[(start + i) % HISTORY_SIZE].timestamp_ms);
    }

    APPEND("],\"v\":[");
    for (int i = 0; i < n; i++) {
        APPEND("%s%.3f", i > 0 ? "," : "",
               history[(start + i) % HISTORY_SIZE].voltage_v);
    }

    APPEND("],\"c\":[");
    for (int i = 0; i < n; i++) {
        APPEND("%s%.3f", i > 0 ? "," : "",
               history[(start + i) % HISTORY_SIZE].current_ma);
    }

    APPEND("],\"p\":[");
    for (int i = 0; i < n; i++) {
        APPEND("%s%.3f", i > 0 ? "," : "",
               history[(start + i) % HISTORY_SIZE].power_mw);
    }

    APPEND("],\"e\":%.3f}", e);
#undef APPEND

    xSemaphoreGive(history_mutex);

    httpd_resp_set_type(req, "application/json");
    httpd_resp_send(req, buf, pos);
    free(buf);
    return ESP_OK;
}

/* ================================================================
 *  HTTP server
 * ================================================================ */

static httpd_handle_t start_http_server(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 8;

    httpd_handle_t server = NULL;
    if (httpd_start(&server, &config) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server");
        return NULL;
    }

    httpd_uri_t uri_root   = { .uri = "/",          .method = HTTP_GET, .handler = root_handler };
    httpd_uri_t uri_data   = { .uri = "/api/data",  .method = HTTP_GET, .handler = api_data_handler };
    httpd_uri_t uri_latest = { .uri = "/api/latest",.method = HTTP_GET, .handler = api_latest_handler };

    httpd_register_uri_handler(server, &uri_root);
    httpd_register_uri_handler(server, &uri_data);
    httpd_register_uri_handler(server, &uri_latest);

    ESP_LOGI(TAG, "HTTP server started on port 80");
    return server;
}

/* ================================================================
 *  Sensor task (10 Hz)
 * ================================================================ */

static void sensor_task(void *arg)
{
    ina226_handle_t *ina = (ina226_handle_t *)arg;

    printf("timestamp_ms,voltage_v,current_ma,power_mw\n");

    while (1) {
        float current_a = 0, power_w = 0, v_bus = 0, v_adc = 0;
        uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;

        v_adc = read_voltage_divider();

        if (ina_present) {
            ina226_bsp_read_bus_voltage(ina, &v_bus);
            ina226_bsp_read_current(ina, &current_a);
            ina226_bsp_read_power(ina, &power_w);
        } else {
            v_bus = v_adc;
        }

        float current_ma = current_a * 1000.0f;
        float power_mw   = power_w * 1000.0f;

        printf("%lu,%.3f,%.3f,%.3f\n", now, v_bus, current_ma, power_mw);

        xSemaphoreTake(history_mutex, portMAX_DELAY);
        {
            history[history_write] = (sample_t){
                .voltage_v    = v_bus,
                .current_ma   = current_ma,
                .power_mw     = power_mw,
                .timestamp_ms = now,
            };
            history_write = (history_write + 1) % HISTORY_SIZE;
            if (history_count < HISTORY_SIZE) history_count++;

            energy_mwh += power_mw * ((float)SAMPLE_INTERVAL_MS / 3600000.0f);
        }
        xSemaphoreGive(history_mutex);

        if (ina_present) {
            uint16_t flags = 0;
            if (ina226_bsp_alert_wait(ina, &flags, 0) == ESP_OK) {
                if (flags & INA226_FLAG_AFF) {
                    ESP_LOGW(TAG, "Alert: power limit exceeded (flags=0x%04X)", flags);
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(SAMPLE_INTERVAL_MS));
    }
}

/* ================================================================
 *  app_main
 * ================================================================ */

void app_main(void)
{
    ESP_LOGI(TAG, "Power profiler v2 — WiFi + web dashboard");

    /* Init hardware (I2C needed before WiFi to avoid contention) */
    i2c_init();
    adc_init();

    /* Init ring buffer */
    history_mutex = xSemaphoreCreateMutex();
    history_write = 0;
    history_count = 0;
    energy_mwh    = 0.0f;

    /* Init NVS + WiFi */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }
    wifi_init_sta();

    /* Start HTTP server */
    start_http_server();

    /* I2C bus scan for diagnostics */
    i2c_scan();

    /* Init INA226 (non-fatal — works without sensor connected)
     * Try common addresses: 0x40 (default), 0x41, 0x44, 0x45 */
    static const uint8_t addrs[] = {0x40, 0x41, 0x44, 0x45};
    ina226_config_t cfg = {
        .avg        = INA226_AVG_64,    // 64 samples avg (high sensitivity)
        .bus_ct     = INA226_CT_204us,  // 204 µs conversion (fast)
        .shunt_ct   = INA226_CT_204us,
        .mode       = INA226_MODE_SHUNT_BUS_CONT,
        .shunt_resistance     = SHUNT_OHM,
        .max_expected_current = MAX_CURRENT_A,
    };

    ina226_handle_t ina;
    int addr_idx;
    for (addr_idx = 0; addr_idx < 4; addr_idx++) {
        ret = ina226_bsp_init(&ina, I2C_PORT, addrs[addr_idx], &cfg);
        if (ret == ESP_OK) {
            ret = ina226_bsp_verify(&ina);
            if (ret == ESP_OK) break;
        }
    }
    if (addr_idx < 4) {
        ina_present = true;
        ESP_LOGI(TAG, "INA226 ready at 0x%02X", addrs[addr_idx]);
        ret = ina226_bsp_alert_setup(&ina, INA226_ALERT_GPIO,
                     INA226_ALERT_MASK, INA226_ALERT_LIMIT, INA226_ALERT_LATCH);
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "Alert setup failed (continuing)");
        }
    } else {
        ESP_LOGW(TAG, "INA226 not found on any I2C address — running without current sensor");
    }

    /* Launch sensor task */
    xTaskCreate(sensor_task, "sensor", 4096, &ina, 5, NULL);

    /* Main task sleeps forever */
    while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}

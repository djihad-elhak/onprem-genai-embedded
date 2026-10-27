#include "task.h"

#include <stdbool.h>
#include <stddef.h>

enum { FREQ_MIN_KHZ = 400000, FREQ_MAX_KHZ = 470000, FREQ_STEP_KHZ = 25 };
enum { SF_MIN = 7, SF_MAX = 12, SF_MAX_WIDE = 10, WIDE_BW_KHZ = 500 };
enum { POWER_MIN_DBM = -4, POWER_MAX_DBM = 20, HIGH_POWER_DBM = 14, HIGH_POWER_DUTY_MAX = 10 };
enum { DUTY_MIN = 1, DUTY_MAX = 100 };

typedef bool (*rule_t)(const radio_cfg_t *c);

static bool in_range(long v, long lo, long hi) { return v >= lo && v <= hi; }

static bool freq_in_band(const radio_cfg_t *c) { return in_range((long)c->frequency_khz, FREQ_MIN_KHZ, FREQ_MAX_KHZ); }
static bool freq_on_grid(const radio_cfg_t *c) { return c->frequency_khz % FREQ_STEP_KHZ == 0u; }
static bool bandwidth_ok(const radio_cfg_t *c)
{
    return c->bandwidth_khz == 125u || c->bandwidth_khz == 250u || c->bandwidth_khz == 500u;
}
static bool sf_ok(const radio_cfg_t *c) { return in_range(c->spreading_factor, SF_MIN, SF_MAX); }
static bool power_ok(const radio_cfg_t *c) { return in_range(c->tx_power_dbm, POWER_MIN_DBM, POWER_MAX_DBM); }
static bool wide_band_sf_ok(const radio_cfg_t *c)
{
    return c->bandwidth_khz != WIDE_BW_KHZ || c->spreading_factor <= SF_MAX_WIDE;
}
static bool high_power_duty_ok(const radio_cfg_t *c)
{
    return c->tx_power_dbm <= HIGH_POWER_DBM || c->duty_cycle_pct <= HIGH_POWER_DUTY_MAX;
}
static bool duty_ok(const radio_cfg_t *c) { return in_range(c->duty_cycle_pct, DUTY_MIN, DUTY_MAX); }

/* Rule i failing yields error code i + 1. */
static const rule_t RULES[] = {freq_in_band, freq_on_grid, bandwidth_ok, sf_ok,
                               power_ok, wide_band_sf_ok, high_power_duty_ok, duty_ok};

int radio_cfg_validate(const radio_cfg_t *c)
{
    for (size_t i = 0u; i < sizeof RULES / sizeof RULES[0]; ++i) {
        if (!RULES[i](c)) {
            return (int)i + 1;
        }
    }
    return 0;
}

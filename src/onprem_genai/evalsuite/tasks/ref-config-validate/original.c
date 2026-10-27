#include "task.h"

int radio_cfg_validate(const radio_cfg_t *c)
{
    if (c->frequency_khz < 400000 || c->frequency_khz > 470000) {
        return 1;
    } else if (c->frequency_khz % 25 != 0) {
        return 2;
    } else if (c->bandwidth_khz != 125 && c->bandwidth_khz != 250 && c->bandwidth_khz != 500) {
        return 3;
    } else if (c->spreading_factor < 7 || c->spreading_factor > 12) {
        return 4;
    } else if (c->tx_power_dbm < -4 || c->tx_power_dbm > 20) {
        return 5;
    } else if (c->bandwidth_khz == 500 && c->spreading_factor > 10) {
        return 6;
    } else if (c->tx_power_dbm > 14 && c->duty_cycle_pct > 10) {
        return 7;
    } else if (c->duty_cycle_pct < 1 || c->duty_cycle_pct > 100) {
        return 8;
    } else {
        return 0;
    }
}

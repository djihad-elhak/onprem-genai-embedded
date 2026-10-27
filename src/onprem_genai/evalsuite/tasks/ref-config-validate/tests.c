#include "task.h"
#include "oge_test.h"

int main(void)
{
    radio_cfg_t ok = {433175, 125, 9, 10, 50};
    radio_cfg_t c;
    CHECK_EQ_I(radio_cfg_validate(&ok), 0);
    c = ok; c.frequency_khz = 399975; CHECK_EQ_I(radio_cfg_validate(&c), 1);
    c = ok; c.frequency_khz = 470025; CHECK_EQ_I(radio_cfg_validate(&c), 1);
    c = ok; c.frequency_khz = 433180; CHECK_EQ_I(radio_cfg_validate(&c), 2);
    c = ok; c.bandwidth_khz = 200; CHECK_EQ_I(radio_cfg_validate(&c), 3);
    c = ok; c.spreading_factor = 6; CHECK_EQ_I(radio_cfg_validate(&c), 4);
    c = ok; c.spreading_factor = 13; CHECK_EQ_I(radio_cfg_validate(&c), 4);
    c = ok; c.tx_power_dbm = -5; CHECK_EQ_I(radio_cfg_validate(&c), 5);
    c = ok; c.tx_power_dbm = 21; CHECK_EQ_I(radio_cfg_validate(&c), 5);
    c = ok; c.bandwidth_khz = 500; c.spreading_factor = 11; CHECK_EQ_I(radio_cfg_validate(&c), 6);
    c = ok; c.bandwidth_khz = 500; c.spreading_factor = 10; CHECK_EQ_I(radio_cfg_validate(&c), 0);
    c = ok; c.tx_power_dbm = 15; c.duty_cycle_pct = 11; CHECK_EQ_I(radio_cfg_validate(&c), 7);
    c = ok; c.tx_power_dbm = 14; c.duty_cycle_pct = 100; CHECK_EQ_I(radio_cfg_validate(&c), 0);
    c = ok; c.duty_cycle_pct = 0; CHECK_EQ_I(radio_cfg_validate(&c), 8);
    c = ok; c.duty_cycle_pct = 101; CHECK_EQ_I(radio_cfg_validate(&c), 8);
    c = ok; c.frequency_khz = 1; c.bandwidth_khz = 7; CHECK_EQ_I(radio_cfg_validate(&c), 1);
    c = ok; c.spreading_factor = 3; c.tx_power_dbm = 99; CHECK_EQ_I(radio_cfg_validate(&c), 4);
    return OGE_REPORT();
}

#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Radio configuration validation. Rules, checked in this order (first failure wins):
   1 frequency_khz in [400000, 470000]          -> error 1
   2 frequency_khz multiple of 25                -> error 2
   3 bandwidth_khz in {125, 250, 500}            -> error 3
   4 spreading_factor in [7, 12]                 -> error 4
   5 tx_power_dbm in [-4, 20]                    -> error 5
   6 if bandwidth_khz == 500, spreading_factor <= 10   -> error 6
   7 if tx_power_dbm > 14, duty_cycle_pct <= 10        -> error 7
   8 duty_cycle_pct in [1, 100]                  -> error 8
   Returns 0 when valid. */
typedef struct {
    uint32_t frequency_khz;
    uint16_t bandwidth_khz;
    uint8_t spreading_factor;
    int8_t tx_power_dbm;
    uint8_t duty_cycle_pct;
} radio_cfg_t;

int radio_cfg_validate(const radio_cfg_t *c);

#endif

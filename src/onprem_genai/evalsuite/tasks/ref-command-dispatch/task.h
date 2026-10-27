#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Command dispatcher of a payload controller.
   Commands: 0x01 SET_MODE (arg 0..3), 0x02 SET_GAIN (arg 0..63), 0x03 SET_CHANNEL (arg 1..15),
             0x04 RESET (arg must be 0xA5), 0x05 PING (arg ignored).
   Returns 0 on success, -1 unknown opcode, -2 argument out of range, -3 command not allowed in current mode
   (SET_GAIN and SET_CHANNEL require mode != 0). RESET restores mode 0, gain 10, channel 1.
   Every successfully executed command increments cmd_count; every rejected command increments err_count. */
typedef struct {
    uint8_t mode;
    uint8_t gain;
    uint8_t channel;
    uint16_t cmd_count;
    uint16_t err_count;
} payload_state_t;

void payload_init(payload_state_t *s);
int payload_dispatch(payload_state_t *s, uint8_t opcode, uint8_t arg);

#endif

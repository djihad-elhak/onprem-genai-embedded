#include "task.h"

void payload_init(payload_state_t *s)
{
    s->mode = 0;
    s->gain = 10;
    s->channel = 1;
    s->cmd_count = 0;
    s->err_count = 0;
}

int payload_dispatch(payload_state_t *s, uint8_t opcode, uint8_t arg)
{
    switch (opcode) {
    case 1:
        if (arg <= 3) {
            s->mode = arg;
            s->cmd_count++;
            return 0;
        } else {
            s->err_count++;
            return -2;
        }
    case 2:
        if (s->mode != 0) {
            if (arg <= 63) {
                s->gain = arg;
                s->cmd_count++;
                return 0;
            } else {
                s->err_count++;
                return -2;
            }
        } else {
            s->err_count++;
            return -3;
        }
    case 3:
        if (s->mode != 0) {
            if (arg >= 1 && arg <= 15) {
                s->channel = arg;
                s->cmd_count++;
                return 0;
            } else {
                s->err_count++;
                return -2;
            }
        } else {
            s->err_count++;
            return -3;
        }
    case 4:
        if (arg == 0xA5) {
            s->mode = 0;
            s->gain = 10;
            s->channel = 1;
            s->cmd_count++;
            return 0;
        } else {
            s->err_count++;
            return -2;
        }
    case 5:
        s->cmd_count++;
        return 0;
    default:
        s->err_count++;
        return -1;
    }
}

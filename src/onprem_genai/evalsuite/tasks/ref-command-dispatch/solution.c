#include "task.h"

#include <stdbool.h>
#include <stddef.h>

enum { MODE_SAFE = 0u, MODE_MAX = 3u, GAIN_MAX = 63u, CHANNEL_MIN = 1u, CHANNEL_MAX = 15u };
enum { DEFAULT_GAIN = 10u, DEFAULT_CHANNEL = 1u, RESET_KEY = 0xA5u };
enum { OK = 0, ERR_OPCODE = -1, ERR_RANGE = -2, ERR_MODE = -3 };

typedef int (*handler_t)(payload_state_t *s, uint8_t arg);

static void apply_defaults(payload_state_t *s)
{
    s->mode = MODE_SAFE;
    s->gain = DEFAULT_GAIN;
    s->channel = DEFAULT_CHANNEL;
}

static int set_mode(payload_state_t *s, uint8_t arg)
{
    if (arg > MODE_MAX) {
        return ERR_RANGE;
    }
    s->mode = arg;
    return OK;
}

static int set_gain(payload_state_t *s, uint8_t arg)
{
    if (arg > GAIN_MAX) {
        return ERR_RANGE;
    }
    s->gain = arg;
    return OK;
}

static int set_channel(payload_state_t *s, uint8_t arg)
{
    if (arg < CHANNEL_MIN || arg > CHANNEL_MAX) {
        return ERR_RANGE;
    }
    s->channel = arg;
    return OK;
}

static int reset(payload_state_t *s, uint8_t arg)
{
    if (arg != RESET_KEY) {
        return ERR_RANGE;
    }
    apply_defaults(s);
    return OK;
}

static int ping(payload_state_t *s, uint8_t arg)
{
    (void)s;
    (void)arg;
    return OK;
}

typedef struct {
    handler_t handler;
    bool needs_active_mode;
} command_t;

static const command_t COMMANDS[] = {
    {NULL, false}, {set_mode, false}, {set_gain, true}, {set_channel, true}, {reset, false}, {ping, false},
};

void payload_init(payload_state_t *s)
{
    apply_defaults(s);
    s->cmd_count = 0u;
    s->err_count = 0u;
}

static int execute(payload_state_t *s, uint8_t opcode, uint8_t arg)
{
    if (opcode == 0u || opcode >= sizeof COMMANDS / sizeof COMMANDS[0]) {
        return ERR_OPCODE;
    }
    if (COMMANDS[opcode].needs_active_mode && s->mode == MODE_SAFE) {
        return ERR_MODE;
    }
    return COMMANDS[opcode].handler(s, arg);
}

int payload_dispatch(payload_state_t *s, uint8_t opcode, uint8_t arg)
{
    int status = execute(s, opcode, arg);
    if (status == OK) {
        s->cmd_count++;
    } else {
        s->err_count++;
    }
    return status;
}

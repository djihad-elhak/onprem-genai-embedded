#include "task.h"

enum { OFF = 0u, STANDBY = 1u, OPERATE = 2u, FAULT = 3u, MODE_COUNT = 4u };
enum { POWER_ON = 0u, POWER_OFF = 1u, START = 2u, STOP = 3u, ERROR = 4u, CLEAR = 5u, EVENT_COUNT = 6u };
enum { REJECT = 0xFFu };

/* NEXT[mode][event]: target mode, or REJECT. */
static const uint8_t NEXT[MODE_COUNT][EVENT_COUNT] = {
    /*            POWER_ON POWER_OFF START    STOP     ERROR   CLEAR  */
    /* OFF     */ {STANDBY, OFF,     REJECT,  REJECT,  REJECT, REJECT},
    /* STANDBY */ {REJECT,  OFF,     OPERATE, REJECT,  FAULT,  REJECT},
    /* OPERATE */ {REJECT,  OFF,     REJECT,  STANDBY, FAULT,  REJECT},
    /* FAULT   */ {REJECT,  OFF,     REJECT,  REJECT,  FAULT,  STANDBY},
};

void mode_init(mode_mgr_t *m)
{
    m->mode = OFF;
    m->transitions = 0u;
}

int mode_handle(mode_mgr_t *m, uint8_t event)
{
    if (m->mode >= MODE_COUNT || event >= EVENT_COUNT || NEXT[m->mode][event] == REJECT) {
        return 0;
    }
    m->mode = NEXT[m->mode][event];
    m->transitions++;
    return 1;
}

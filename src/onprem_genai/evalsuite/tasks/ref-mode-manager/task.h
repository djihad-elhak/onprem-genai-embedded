#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Mode manager of an instrument. Modes: 0 OFF, 1 STANDBY, 2 OPERATE, 3 FAULT.
   Events: 0 POWER_ON, 1 POWER_OFF, 2 START, 3 STOP, 4 ERROR, 5 CLEAR.
   Transitions: OFF --POWER_ON--> STANDBY; STANDBY --START--> OPERATE; OPERATE --STOP--> STANDBY;
   any mode except OFF --ERROR--> FAULT; FAULT --CLEAR--> STANDBY; any mode --POWER_OFF--> OFF.
   Any other (mode, event) pair is rejected and leaves the mode unchanged.
   mode_handle returns 1 if the event caused a transition, 0 if rejected; transitions counts accepted events. */
typedef struct {
    uint8_t mode;
    uint16_t transitions;
} mode_mgr_t;

void mode_init(mode_mgr_t *m);
int mode_handle(mode_mgr_t *m, uint8_t event);

#endif

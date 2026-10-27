#include "task.h"

bool tick_elapsed(uint32_t now, uint32_t start, uint32_t timeout_ms)
{
    return (uint32_t)(now - start) >= timeout_ms;
}

uint32_t tick_remaining(uint32_t now, uint32_t start, uint32_t timeout_ms)
{
    uint32_t elapsed = (uint32_t)(now - start);
    return timeout_ms - elapsed;
}

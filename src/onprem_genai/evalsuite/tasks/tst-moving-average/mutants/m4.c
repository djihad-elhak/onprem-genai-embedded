#include "task.h"

void mavg_reset(mavg_t *m)
{
    for (uint32_t i = 0u; i < MAVG_WINDOW; ++i) {
        m->samples[i] = 0;
    }
    m->next = 0u;
    m->count = 0u;
    m->sum = 0;
}

int32_t mavg_push(mavg_t *m, int32_t sample)
{
    if (m->count == MAVG_WINDOW) {
        m->sum -= m->samples[(m->next + 1u) % MAVG_WINDOW];
    } else {
        m->count++;
    }
    m->samples[m->next] = sample;
    m->sum += sample;
    m->next = (m->next + 1u) % MAVG_WINDOW;
    return m->sum / (int32_t)m->count;
}

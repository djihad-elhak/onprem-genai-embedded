#include "task.h"

void mode_init(mode_mgr_t *m)
{
    m->mode = 0;
    m->transitions = 0;
}

int mode_handle(mode_mgr_t *m, uint8_t event)
{
    int ok = 0;
    if (event == 1) {
        m->mode = 0;
        ok = 1;
    } else if (m->mode == 0) {
        if (event == 0) {
            m->mode = 1;
            ok = 1;
        }
    } else if (m->mode == 1) {
        if (event == 2) {
            m->mode = 2;
            ok = 1;
        } else if (event == 4) {
            m->mode = 3;
            ok = 1;
        }
    } else if (m->mode == 2) {
        if (event == 3) {
            m->mode = 1;
            ok = 1;
        } else if (event == 4) {
            m->mode = 3;
            ok = 1;
        }
    } else if (m->mode == 3) {
        if (event == 5) {
            m->mode = 1;
            ok = 1;
        } else if (event == 4) {
            m->mode = 3;
            ok = 1;
        }
    }
    if (ok) {
        m->transitions++;
    }
    return ok;
}

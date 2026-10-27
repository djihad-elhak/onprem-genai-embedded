#include "task.h"
#include "oge_test.h"

static void feed(debounce_t *d, const char *raw, const char *expected)
{
    for (unsigned i = 0; raw[i] != '\0'; ++i) {
        bool out = debounce_update(d, raw[i] == '1');
        CHECK_EQ_U(out, expected[i] == '1');
    }
}

int main(void)
{
    debounce_t d;
    debounce_init(&d, false);
    feed(&d, "1110111100", "0000000111");
    debounce_init(&d, true);
    feed(&d, "0001000010000", "1111111000000");
    debounce_init(&d, false);
    feed(&d, "10101010101111", "00000000000001");
    debounce_init(&d, false);
    feed(&d, "111100001111", "000111100001");
    debounce_init(&d, true);
    feed(&d, "0000", "1110");
    return OGE_REPORT();
}

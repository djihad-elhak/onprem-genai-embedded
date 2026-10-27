#include "task.h"
#include "oge_test.h"

int main(void)
{
    ring_buffer_t rb;
    uint8_t v = 0xAA;
    rb_init(&rb);
    CHECK_EQ_U(rb_count(&rb), 0);
    CHECK(!rb_is_full(&rb));
    CHECK(!rb_pop(&rb, &v));
    CHECK_EQ_U(v, 0xAA);
    for (unsigned i = 0; i < RB_CAPACITY; ++i) {
        CHECK(rb_push(&rb, (uint8_t)(10 + i)));
    }
    CHECK(rb_is_full(&rb));
    CHECK(!rb_push(&rb, 99));
    CHECK_EQ_U(rb_count(&rb), RB_CAPACITY);
    for (unsigned i = 0; i < RB_CAPACITY; ++i) {
        CHECK(rb_pop(&rb, &v));
        CHECK_EQ_U(v, 10 + i);
    }
    CHECK(!rb_pop(&rb, &v));
    /* wrap around many times with an interleaved pattern */
    unsigned next_in = 0, next_out = 0;
    for (unsigned round = 0; round < 50; ++round) {
        for (unsigned k = 0; k < (round % 5) + 1; ++k) {
            if (rb_push(&rb, (uint8_t)next_in)) {
                next_in++;
            }
        }
        for (unsigned k = 0; k < (round % 3) + 1; ++k) {
            if (rb_pop(&rb, &v)) {
                CHECK_EQ_U(v, (uint8_t)next_out);
                next_out++;
            }
        }
        CHECK_EQ_U(rb_count(&rb), next_in - next_out);
    }
    rb_init(&rb);
    {
        const uint8_t src[10] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
        CHECK(rb_push(&rb, 0));
        CHECK_EQ_U(rb_push_many(&rb, src, 10), RB_CAPACITY - 1);
        CHECK(rb_is_full(&rb));
        CHECK_EQ_U(rb_push_many(&rb, src, 3), 0);
        CHECK(rb_pop(&rb, &v));
        CHECK_EQ_U(v, 0);
        CHECK(rb_pop(&rb, &v));
        CHECK_EQ_U(v, 1);
    }
    return OGE_REPORT();
}

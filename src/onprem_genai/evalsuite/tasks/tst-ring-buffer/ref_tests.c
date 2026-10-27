#include "task.h"
#include "oge_test.h"

int main(void)
{
    ring_buffer_t rb;
    uint8_t v = 0x5A;
    const uint8_t src[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    rb_init(&rb);
    CHECK(!rb_pop(&rb, &v));
    CHECK_EQ_U(v, 0x5A);
    for (unsigned i = 0; i < RB_CAPACITY; ++i) {
        CHECK(rb_push(&rb, (uint8_t)i));
    }
    CHECK(!rb_push(&rb, 99));
    CHECK_EQ_U(rb_count(&rb), RB_CAPACITY);
    for (unsigned i = 0; i < RB_CAPACITY; ++i) {
        CHECK(rb_pop(&rb, &v));
        CHECK_EQ_U(v, i);
    }
    CHECK_EQ_U(rb_count(&rb), 0);
    for (unsigned r = 0; r < 12; ++r) {
        CHECK(rb_push(&rb, (uint8_t)(100 + r)));
        CHECK(rb_pop(&rb, &v));
        CHECK_EQ_U(v, 100 + r);
    }
    CHECK_EQ_U(rb_push_many(&rb, src, 8), RB_CAPACITY);
    CHECK_EQ_U(rb_push_many(&rb, src, 8), 0);
    CHECK(rb_pop(&rb, &v));
    CHECK_EQ_U(v, 1);
    return OGE_REPORT();
}

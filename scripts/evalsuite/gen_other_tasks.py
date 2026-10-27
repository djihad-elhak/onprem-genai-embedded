"""Author the testgen / refactor / document tasks of the evaluation suite.

The validator (`oge eval validate`) checks that every reference passes, that reference tests kill every mutant,
that originals of refactor/document tasks pass their hidden tests without already counting as a pass.

    python scripts/evalsuite/gen_other_tasks.py
"""

from __future__ import annotations

import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "onprem_genai" / "evalsuite" / "tasks"


def d(s: str) -> str:
    return textwrap.dedent(s).lstrip()


def write(tid: str, files: dict[str, str]) -> None:
    root = ROOT / tid
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(d(text))


def mutate(src: str, old: str, new: str) -> str:
    assert src.count(old) == 1, f"mutation anchor not unique: {old!r}"
    return src.replace(old, new)


# ============================================================================================ testgen
SAT_H = """
#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Saturating 16-bit signed arithmetic: results are clamped to [INT16_MIN, INT16_MAX]. */
int16_t sat_add16(int16_t a, int16_t b);
int16_t sat_sub16(int16_t a, int16_t b);
int16_t sat_abs16(int16_t a);   /* sat_abs16(INT16_MIN) == INT16_MAX */

#endif
"""
SAT_IMPL = """
#include "task.h"

static int16_t clamp16(int32_t v)
{
    if (v > INT16_MAX) {
        return INT16_MAX;
    }
    if (v < INT16_MIN) {
        return INT16_MIN;
    }
    return (int16_t)v;
}

int16_t sat_add16(int16_t a, int16_t b) { return clamp16((int32_t)a + (int32_t)b); }

int16_t sat_sub16(int16_t a, int16_t b) { return clamp16((int32_t)a - (int32_t)b); }

int16_t sat_abs16(int16_t a) { return clamp16(a < 0 ? -(int32_t)a : (int32_t)a); }
"""
SAT_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    CHECK_EQ_I(sat_add16(1000, 2000), 3000);
    CHECK_EQ_I(sat_add16(32000, 1000), 32767);
    CHECK_EQ_I(sat_add16(32767, 0), 32767);
    CHECK_EQ_I(sat_add16(32766, 1), 32767);
    CHECK_EQ_I(sat_add16(-32000, -1000), -32768);
    CHECK_EQ_I(sat_add16(-32767, -1), -32768);
    CHECK_EQ_I(sat_add16(-5, 3), -2);
    CHECK_EQ_I(sat_add16(-5, -3), -8);
    CHECK_EQ_I(sat_sub16(-32000, 1000), -32768);
    CHECK_EQ_I(sat_sub16(32000, -1000), 32767);
    CHECK_EQ_I(sat_sub16(5, 7), -2);
    CHECK_EQ_I(sat_sub16(0, -32768), 32767);
    CHECK_EQ_I(sat_abs16(-32768), 32767);
    CHECK_EQ_I(sat_abs16(-5), 5);
    CHECK_EQ_I(sat_abs16(7), 7);
    CHECK_EQ_I(sat_abs16(0), 0);
    return OGE_REPORT();
}
"""

FLETCHER_H = """
#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* Fletcher-16 checksum: sum1 = sum1 + byte (mod 255), sum2 = sum2 + sum1 (mod 255), both start at 0.
   Result = (sum2 << 8) | sum1. */
uint16_t fletcher16(const uint8_t *data, size_t len);

/* Verifies a frame whose last two bytes hold check bytes c0, c1 computed so that the Fletcher-16 of the whole
   frame is 0: returns 1 if valid, 0 otherwise (also 0 when len < 2). */
int fletcher16_frame_ok(const uint8_t *frame, size_t len);

#endif
"""
FLETCHER_IMPL = """
#include "task.h"

uint16_t fletcher16(const uint8_t *data, size_t len)
{
    uint16_t sum1 = 0u;
    uint16_t sum2 = 0u;
    for (size_t i = 0u; i < len; ++i) {
        sum1 = (uint16_t)((sum1 + data[i]) % 255u);
        sum2 = (uint16_t)((sum2 + sum1) % 255u);
    }
    return (uint16_t)((sum2 << 8) | sum1);
}

int fletcher16_frame_ok(const uint8_t *frame, size_t len)
{
    if (len < 2u) {
        return 0;
    }
    return fletcher16(frame, len) == 0u;
}
"""
FLETCHER_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    const uint8_t abcde[] = {'a', 'b', 'c', 'd', 'e'};
    const uint8_t abcdef[] = {'a', 'b', 'c', 'd', 'e', 'f'};
    const uint8_t abcdefgh[] = {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'};
    uint8_t ff[300];
    for (int i = 0; i < 300; ++i) {
        ff[i] = 0xFF;
    }
    CHECK_EQ_U(fletcher16(abcde, 5), 0xC8F0);
    CHECK_EQ_U(fletcher16(abcdef, 6), 0x2057);
    CHECK_EQ_U(fletcher16(abcdefgh, 8), 0x0627);
    CHECK_EQ_U(fletcher16(abcde, 0), 0x0000);
    CHECK_EQ_U(fletcher16(ff, 300), 0x0000);
    {
        /* frame with check bytes: c0 = 255 - ((sum1 + sum2) % 255), c1 = 255 - ((sum1 + c0) % 255) */
        uint8_t frame[7] = {'a', 'b', 'c', 'd', 'e', 0, 0};
        uint16_t f = fletcher16(frame, 5);
        uint8_t s1 = (uint8_t)(f & 0xFF), s2 = (uint8_t)(f >> 8);
        frame[5] = (uint8_t)(255 - ((s1 + s2) % 255));
        frame[6] = (uint8_t)(255 - ((s1 + frame[5]) % 255));
        CHECK_EQ_I(fletcher16_frame_ok(frame, 7), 1);
        frame[2] ^= 0x01;
        CHECK_EQ_I(fletcher16_frame_ok(frame, 7), 0);
        CHECK_EQ_I(fletcher16_frame_ok(frame, 1), 0);
        frame[0] = 0x00;
        CHECK_EQ_I(fletcher16_frame_ok(frame, 1), 0);
    }
    return OGE_REPORT();
}
"""

TICK_H = """
#ifndef TASK_H
#define TASK_H
#include <stdbool.h>
#include <stdint.h>

/* 32-bit free-running millisecond tick (wraps around). Elapsed times are assumed < 2^31 ms. */
bool tick_elapsed(uint32_t now, uint32_t start, uint32_t timeout_ms);
uint32_t tick_remaining(uint32_t now, uint32_t start, uint32_t timeout_ms);

#endif
"""
TICK_IMPL = """
#include "task.h"

bool tick_elapsed(uint32_t now, uint32_t start, uint32_t timeout_ms)
{
    return (uint32_t)(now - start) >= timeout_ms;
}

uint32_t tick_remaining(uint32_t now, uint32_t start, uint32_t timeout_ms)
{
    uint32_t elapsed = (uint32_t)(now - start);
    return elapsed >= timeout_ms ? 0u : timeout_ms - elapsed;
}
"""
TICK_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    CHECK(tick_elapsed(200u, 100u, 100u));
    CHECK(!tick_elapsed(199u, 100u, 100u));
    CHECK(tick_elapsed(0x10u, 0xFFFFFFF0u, 0x20u));
    CHECK(!tick_elapsed(0x0Fu, 0xFFFFFFF0u, 0x20u));
    CHECK(!tick_elapsed(0xFFFFFFF8u, 0xFFFFFFF0u, 0x20u));
    CHECK(tick_elapsed(5u, 5u, 0u));
    CHECK_EQ_U(tick_remaining(150u, 100u, 100u), 50u);
    CHECK_EQ_U(tick_remaining(300u, 100u, 100u), 0u);
    CHECK_EQ_U(tick_remaining(0x0Fu, 0xFFFFFFF0u, 0x20u), 1u);
    CHECK_EQ_U(tick_remaining(0x30u, 0xFFFFFFF0u, 0x20u), 0u);
    return OGE_REPORT();
}
"""

MAVG_H = """
#ifndef TASK_H
#define TASK_H
#include <stdint.h>

#define MAVG_WINDOW 4u

/* Integer moving average over the last MAVG_WINDOW samples. Until the window is full, the average is taken
   over the samples received so far. The average rounds toward zero (C integer division). */
typedef struct {
    int32_t samples[MAVG_WINDOW];
    uint32_t next;   /* index where the next sample is written */
    uint32_t count;  /* number of valid samples (<= MAVG_WINDOW) */
    int32_t sum;
} mavg_t;

void mavg_reset(mavg_t *m);
int32_t mavg_push(mavg_t *m, int32_t sample);  /* returns the average after adding sample */

#endif
"""
MAVG_IMPL = """
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
        m->sum -= m->samples[m->next];
    } else {
        m->count++;
    }
    m->samples[m->next] = sample;
    m->sum += sample;
    m->next = (m->next + 1u) % MAVG_WINDOW;
    return m->sum / (int32_t)m->count;
}
"""
MAVG_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    mavg_t m;
    mavg_reset(&m);
    CHECK_EQ_I(mavg_push(&m, 10), 10);
    CHECK_EQ_I(mavg_push(&m, 20), 15);
    CHECK_EQ_I(mavg_push(&m, 30), 20);
    CHECK_EQ_I(mavg_push(&m, 40), 25);
    CHECK_EQ_I(mavg_push(&m, 50), 35);
    CHECK_EQ_I(mavg_push(&m, 60), 45);
    CHECK_EQ_I(mavg_push(&m, 70), 55);
    CHECK_EQ_I(mavg_push(&m, 80), 65);
    CHECK_EQ_I(mavg_push(&m, 81), 72);
    mavg_reset(&m);
    CHECK_EQ_I(mavg_push(&m, -7), -7);
    CHECK_EQ_I(mavg_push(&m, 0), -3);
    CHECK_EQ_I(mavg_push(&m, 2), -1);
    mavg_reset(&m);
    CHECK_EQ_I(mavg_push(&m, 5), 5);
    CHECK_EQ_U(m.count, 1u);
    return OGE_REPORT();
}
"""

RB_H = """
#ifndef TASK_H
#define TASK_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RB_CAPACITY 5u

typedef struct {
    uint8_t data[RB_CAPACITY];
    size_t head;
    size_t tail;
    size_t count;
} ring_buffer_t;

void rb_init(ring_buffer_t *rb);
bool rb_push(ring_buffer_t *rb, uint8_t byte);      /* false when full (nothing stored) */
bool rb_pop(ring_buffer_t *rb, uint8_t *out);       /* false when empty (*out untouched) */
size_t rb_count(const ring_buffer_t *rb);
size_t rb_push_many(ring_buffer_t *rb, const uint8_t *src, size_t n); /* stores as many as fit */

#endif
"""
RB_IMPL = """
#include "task.h"

void rb_init(ring_buffer_t *rb)
{
    rb->head = 0u;
    rb->tail = 0u;
    rb->count = 0u;
}

bool rb_push(ring_buffer_t *rb, uint8_t byte)
{
    if (rb->count >= RB_CAPACITY) {
        return false;
    }
    rb->data[rb->head] = byte;
    rb->head = (rb->head + 1u) % RB_CAPACITY;
    rb->count++;
    return true;
}

bool rb_pop(ring_buffer_t *rb, uint8_t *out)
{
    if (rb->count == 0u) {
        return false;
    }
    *out = rb->data[rb->tail];
    rb->tail = (rb->tail + 1u) % RB_CAPACITY;
    rb->count--;
    return true;
}

size_t rb_count(const ring_buffer_t *rb) { return rb->count; }

size_t rb_push_many(ring_buffer_t *rb, const uint8_t *src, size_t n)
{
    size_t stored = 0u;
    while (stored < n && rb_push(rb, src[stored])) {
        stored++;
    }
    return stored;
}
"""
RB_TESTS = """
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
"""

CCSDS_H = """
#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* CCSDS Space Packet primary header (6 bytes, big-endian bit fields):
   version (3) | type (1) | sec_hdr (1) | apid (11) | seq_flags (2) | seq_count (14) | data_length (16). */
typedef struct {
    uint8_t version;
    uint8_t type;
    uint8_t sec_hdr;
    uint16_t apid;
    uint8_t seq_flags;
    uint16_t seq_count;
    uint16_t data_length;
} ccsds_primary_header_t;

/* 0 on success, -1 if buf/hdr NULL or len < 6, -2 if version != 0. */
int ccsds_parse_primary(const uint8_t *buf, size_t len, ccsds_primary_header_t *hdr);

/* 6 + data_length + 1 */
size_t ccsds_packet_length(const ccsds_primary_header_t *hdr);

#endif
"""
CCSDS_IMPL = """
#include "task.h"

int ccsds_parse_primary(const uint8_t *buf, size_t len, ccsds_primary_header_t *hdr)
{
    if (buf == NULL || hdr == NULL || len < 6u) {
        return -1;
    }
    uint16_t w0 = (uint16_t)(((uint16_t)buf[0] << 8) | buf[1]);
    uint16_t w1 = (uint16_t)(((uint16_t)buf[2] << 8) | buf[3]);
    hdr->version = (uint8_t)(w0 >> 13);
    hdr->type = (uint8_t)((w0 >> 12) & 1u);
    hdr->sec_hdr = (uint8_t)((w0 >> 11) & 1u);
    hdr->apid = (uint16_t)(w0 & 0x7FFu);
    hdr->seq_flags = (uint8_t)(w1 >> 14);
    hdr->seq_count = (uint16_t)(w1 & 0x3FFFu);
    hdr->data_length = (uint16_t)(((uint16_t)buf[4] << 8) | buf[5]);
    return hdr->version == 0u ? 0 : -2;
}

size_t ccsds_packet_length(const ccsds_primary_header_t *hdr) { return 6u + (size_t)hdr->data_length + 1u; }
"""
CCSDS_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    ccsds_primary_header_t h;
    const uint8_t a[6] = {0x1F, 0xFF, 0xFF, 0xFF, 0x12, 0x34};
    const uint8_t b[6] = {0x08, 0x2A, 0x40, 0x07, 0x00, 0x00};
    const uint8_t v[6] = {0x20, 0x00, 0x00, 0x00, 0x00, 0x00};
    CHECK_EQ_I(ccsds_parse_primary(a, 6, &h), 0);
    CHECK_EQ_U(h.version, 0);
    CHECK_EQ_U(h.type, 1);
    CHECK_EQ_U(h.sec_hdr, 1);
    CHECK_EQ_U(h.apid, 0x7FF);
    CHECK_EQ_U(h.seq_flags, 3);
    CHECK_EQ_U(h.seq_count, 0x3FFF);
    CHECK_EQ_U(h.data_length, 0x1234);
    CHECK_EQ_U(ccsds_packet_length(&h), 6 + 0x1234 + 1);
    CHECK_EQ_I(ccsds_parse_primary(b, 6, &h), 0);
    CHECK_EQ_U(h.type, 0);
    CHECK_EQ_U(h.sec_hdr, 1);
    CHECK_EQ_U(h.apid, 0x02A);
    CHECK_EQ_U(h.seq_flags, 1);
    CHECK_EQ_U(h.seq_count, 7);
    CHECK_EQ_U(ccsds_packet_length(&h), 7);
    CHECK_EQ_I(ccsds_parse_primary(v, 6, &h), -2);
    CHECK_EQ_I(ccsds_parse_primary(a, 5, &h), -1);
    CHECK_EQ_I(ccsds_parse_primary(a, 6, NULL), -1);
    CHECK_EQ_I(ccsds_parse_primary(NULL, 6, &h), -1);
    return OGE_REPORT();
}
"""


def testgen_task(
    tid: str,
    title: str,
    domain: str,
    desc: str,
    header: str,
    impl: str,
    tests: str,
    mutants: list[tuple[str, str]],
) -> None:
    files = {
        "task.yaml": f"""
            id: {tid}
            category: testgen
            title: {title}
            domain: {domain}
            difficulty: medium
            description: |
              {desc}
            """,
        "task.h": header,
        "impl.c": impl,
        "ref_tests.c": tests,
    }
    for i, (old, new) in enumerate(mutants, 1):
        files[f"mutants/m{i}.c"] = mutate(d(impl), old, new)
    write(tid, files)


def all_testgen() -> None:
    common = (
        "Write a complete unit-test program (tests.c with a main function) for the implementation below, "
        "using the CHECK macros of oge_test.h and returning OGE_REPORT(). Tests must pass on this "
        "implementation and should detect any deviation from the specification in task.h."
    )
    testgen_task(
        "tst-saturating-arith",
        "Unit tests for saturating 16-bit arithmetic",
        "fixed-point DSP",
        common,
        SAT_H,
        SAT_IMPL,
        SAT_TESTS,
        [
            (
                "    if (v > INT16_MAX) {\n        return INT16_MAX;\n    }\n",
                "    if (v > INT16_MAX + 1) {\n        return INT16_MAX;\n    }\n",
            ),
            (
                "    if (v < INT16_MIN) {\n        return INT16_MIN;\n    }\n",
                "    if (v < INT16_MIN) {\n        return INT16_MIN + 1;\n    }\n",
            ),
            ("clamp16(a < 0 ? -(int32_t)a : (int32_t)a)", "(int16_t)(a < 0 ? -a : a)"),
            ("clamp16((int32_t)a - (int32_t)b)", "(int16_t)((int32_t)a - (int32_t)b)"),
            ("clamp16((int32_t)a + (int32_t)b)", "clamp16((int32_t)a + (int32_t)b - (a < 0 && b < 0))"),
        ],
    )
    testgen_task(
        "tst-fletcher16",
        "Unit tests for Fletcher-16 checksum and frame check",
        "integrity checks",
        common,
        FLETCHER_H,
        FLETCHER_IMPL,
        FLETCHER_TESTS,
        [
            ("sum1 = (uint16_t)((sum1 + data[i]) % 255u);", "sum1 = (uint16_t)((sum1 + data[i]) % 256u);"),
            ("return (uint16_t)((sum2 << 8) | sum1);", "return (uint16_t)((sum1 << 8) | sum2);"),
            ("for (size_t i = 0u; i < len; ++i) {", "for (size_t i = 0u; i + 1u < len; ++i) {"),
            (
                "    if (len < 2u) {\n        return 0;\n    }\n",
                "    if (len < 1u) {\n        return 0;\n    }\n",
            ),
            ("sum2 = (uint16_t)((sum2 + sum1) % 255u);", "sum2 = (uint16_t)((sum2 + data[i]) % 255u);"),
        ],
    )
    testgen_task(
        "tst-tick-elapsed",
        "Unit tests for wraparound-safe timeouts",
        "RTOS timers",
        common,
        TICK_H,
        TICK_IMPL,
        TICK_TESTS,
        [
            ("return (uint32_t)(now - start) >= timeout_ms;", "return now >= start + timeout_ms;"),
            ("return (uint32_t)(now - start) >= timeout_ms;", "return (uint32_t)(now - start) > timeout_ms;"),
            ("return elapsed >= timeout_ms ? 0u : timeout_ms - elapsed;", "return timeout_ms - elapsed;"),
            (
                "uint32_t elapsed = (uint32_t)(now - start);",
                "uint32_t elapsed = now > start ? now - start : 0u;",
            ),
        ],
    )
    testgen_task(
        "tst-moving-average",
        "Unit tests for an integer moving-average filter",
        "signal conditioning",
        common,
        MAVG_H,
        MAVG_IMPL,
        MAVG_TESTS,
        [
            ("return m->sum / (int32_t)m->count;", "return m->sum / (int32_t)MAVG_WINDOW;"),
            ("m->next = (m->next + 1u) % MAVG_WINDOW;", "m->next = (m->next + 1u) % (MAVG_WINDOW - 1u);"),
            ("    m->count = 0u;\n    m->sum = 0;", "    m->count = 0u;"),
            (
                "        m->sum -= m->samples[m->next];\n",
                "        m->sum -= m->samples[(m->next + 1u) % MAVG_WINDOW];\n",
            ),
            (
                "return m->sum / (int32_t)m->count;",
                "return (m->sum + (int32_t)m->count / 2) / (int32_t)m->count;",
            ),
        ],
    )
    testgen_task(
        "tst-ring-buffer",
        "Unit tests for a byte ring buffer",
        "driver buffering",
        common,
        RB_H,
        RB_IMPL,
        RB_TESTS,
        [
            (
                "    if (rb->count >= RB_CAPACITY) {\n        return false;\n    }\n    rb->data[rb->head] = byte;",
                "    if (rb->count >= RB_CAPACITY - 1u) {\n        return false;\n    }\n    rb->data[rb->head] = byte;",
            ),
            (
                "    rb->tail = (rb->tail + 1u) % RB_CAPACITY;\n    rb->count--;",
                "    rb->tail = (rb->tail + 1u) % RB_CAPACITY;",
            ),
            (
                "    if (rb->count == 0u) {\n        return false;\n    }\n    *out = rb->data[rb->tail];",
                "    *out = rb->data[rb->tail];\n    if (rb->count == 0u) {\n        return false;\n    }",
            ),
            ("    return stored;", "    return n;"),
            ("    rb->tail = (rb->tail + 1u) % RB_CAPACITY;\n    rb->count--;", "    rb->count--;"),
        ],
    )
    testgen_task(
        "tst-ccsds-parse",
        "Unit tests for a CCSDS primary-header parser",
        "space telemetry",
        common,
        CCSDS_H,
        CCSDS_IMPL,
        CCSDS_TESTS,
        [
            ("hdr->apid = (uint16_t)(w0 & 0x7FFu);", "hdr->apid = (uint16_t)(w0 & 0x3FFu);"),
            ("hdr->seq_count = (uint16_t)(w1 & 0x3FFFu);", "hdr->seq_count = (uint16_t)(w1 & 0x7FFFu);"),
            ("return hdr->version == 0u ? 0 : -2;", "return 0;"),
            (
                "if (buf == NULL || hdr == NULL || len < 6u) {",
                "if (buf == NULL || hdr == NULL || len < 5u) {",
            ),
            (
                "hdr->data_length = (uint16_t)(((uint16_t)buf[4] << 8) | buf[5]);",
                "hdr->data_length = (uint16_t)(((uint16_t)buf[5] << 8) | buf[4]);",
            ),
            ("return 6u + (size_t)hdr->data_length + 1u;", "return 6u + (size_t)hdr->data_length;"),
        ],
    )


# ============================================================================================ refactor
REFACTOR_RULES = (
    "Refactor the code for readability and maintainability without changing its behaviour: replace "
    "magic numbers with named constants, remove duplication, reduce nesting and cyclomatic "
    "complexity (split into small static functions or use tables), never use goto. The public "
    "functions of task.h must keep their exact signatures and behaviour; hidden tests check it."
)

DISPATCH_H = """
#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Command dispatcher of a payload controller.
   Commands: 0x01 SET_MODE (arg 0..3), 0x02 SET_GAIN (arg 0..63), 0x03 SET_CHANNEL (arg 1..15),
             0x04 RESET (arg must be 0xA5), 0x05 PING (arg ignored).
   Returns 0 on success, -1 unknown opcode, -2 argument out of range, -3 command not allowed in current mode
   (SET_GAIN and SET_CHANNEL require mode != 0). RESET restores mode 0, gain 10, channel 1.
   Every successfully executed command increments cmd_count; every rejected command increments err_count. */
typedef struct {
    uint8_t mode;
    uint8_t gain;
    uint8_t channel;
    uint16_t cmd_count;
    uint16_t err_count;
} payload_state_t;

void payload_init(payload_state_t *s);
int payload_dispatch(payload_state_t *s, uint8_t opcode, uint8_t arg);

#endif
"""
DISPATCH_ORIG = """
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
"""
DISPATCH_REF = """
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
"""
DISPATCH_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    payload_state_t s;
    payload_init(&s);
    CHECK_EQ_U(s.mode, 0); CHECK_EQ_U(s.gain, 10); CHECK_EQ_U(s.channel, 1);
    CHECK_EQ_I(payload_dispatch(&s, 2, 5), -3);
    CHECK_EQ_I(payload_dispatch(&s, 3, 5), -3);
    CHECK_EQ_I(payload_dispatch(&s, 1, 4), -2);
    CHECK_EQ_I(payload_dispatch(&s, 1, 2), 0);
    CHECK_EQ_U(s.mode, 2);
    CHECK_EQ_I(payload_dispatch(&s, 2, 63), 0);
    CHECK_EQ_I(payload_dispatch(&s, 2, 64), -2);
    CHECK_EQ_U(s.gain, 63);
    CHECK_EQ_I(payload_dispatch(&s, 3, 0), -2);
    CHECK_EQ_I(payload_dispatch(&s, 3, 16), -2);
    CHECK_EQ_I(payload_dispatch(&s, 3, 15), 0);
    CHECK_EQ_U(s.channel, 15);
    CHECK_EQ_I(payload_dispatch(&s, 5, 77), 0);
    CHECK_EQ_I(payload_dispatch(&s, 4, 0), -2);
    CHECK_EQ_I(payload_dispatch(&s, 4, 0xA5), 0);
    CHECK_EQ_U(s.mode, 0); CHECK_EQ_U(s.gain, 10); CHECK_EQ_U(s.channel, 1);
    CHECK_EQ_I(payload_dispatch(&s, 0, 0), -1);
    CHECK_EQ_I(payload_dispatch(&s, 6, 0), -1);
    CHECK_EQ_I(payload_dispatch(&s, 0xFF, 0), -1);
    CHECK_EQ_U(s.cmd_count, 5);
    CHECK_EQ_U(s.err_count, 10);
    return OGE_REPORT();
}
"""

FRAME_H = """
#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* Frame: SYNC (0xEB 0x90) | LEN (1 byte, payload length 1..32) | TYPE (1 byte, 0x10..0x1F) | PAYLOAD | XOR
   where XOR is the XOR of LEN, TYPE and every payload byte.
   frame_parse copies the payload to out (capacity >= 32) and returns its length, or:
   -1 too short / NULL, -2 bad sync, -3 bad length (0, > 32, or not matching the buffer size exactly),
   -4 bad type, -5 bad checksum. */
int frame_parse(const uint8_t *buf, size_t len, uint8_t *type, uint8_t *out);

#endif
"""
FRAME_ORIG = """
#include "task.h"

int frame_parse(const uint8_t *buf, size_t len, uint8_t *type, uint8_t *out)
{
    int rc = 0;
    uint8_t x = 0;
    size_t i;
    if (buf == 0 || type == 0 || out == 0) {
        rc = -1;
        goto done;
    }
    if (len < 5) {
        rc = -1;
        goto done;
    }
    if (buf[0] != 0xEB || buf[1] != 0x90) {
        rc = -2;
        goto done;
    }
    if (buf[2] == 0 || buf[2] > 32) {
        rc = -3;
        goto done;
    } else {
        if ((size_t)buf[2] + 5 != len) {
            rc = -3;
            goto done;
        }
    }
    if (buf[3] < 0x10 || buf[3] > 0x1F) {
        rc = -4;
        goto done;
    }
    x = buf[2] ^ buf[3];
    for (i = 0; i < buf[2]; i++) {
        x ^= buf[4 + i];
    }
    if (x != buf[4 + buf[2]]) {
        rc = -5;
        goto done;
    }
    *type = buf[3];
    for (i = 0; i < buf[2]; i++) {
        out[i] = buf[4 + i];
    }
    rc = buf[2];
done:
    return rc;
}
"""
FRAME_REF = """
#include "task.h"

#include <string.h>

enum { SYNC0 = 0xEB, SYNC1 = 0x90, HEADER_LEN = 4u, OVERHEAD = 5u, MAX_PAYLOAD = 32u };
enum { TYPE_MIN = 0x10, TYPE_MAX = 0x1F };
enum { ERR_SHORT = -1, ERR_SYNC = -2, ERR_LENGTH = -3, ERR_TYPE = -4, ERR_CHECKSUM = -5 };

static uint8_t checksum(const uint8_t *buf, uint8_t payload_len)
{
    uint8_t x = (uint8_t)(buf[2] ^ buf[3]);
    for (uint8_t i = 0u; i < payload_len; ++i) {
        x ^= buf[HEADER_LEN + i];
    }
    return x;
}

static int check_header(const uint8_t *buf, size_t len)
{
    uint8_t payload_len = buf[2];
    if (buf[0] != SYNC0 || buf[1] != SYNC1) {
        return ERR_SYNC;
    }
    if (payload_len == 0u || payload_len > MAX_PAYLOAD || (size_t)payload_len + OVERHEAD != len) {
        return ERR_LENGTH;
    }
    if (buf[3] < TYPE_MIN || buf[3] > TYPE_MAX) {
        return ERR_TYPE;
    }
    return 0;
}

int frame_parse(const uint8_t *buf, size_t len, uint8_t *type, uint8_t *out)
{
    if (buf == NULL || type == NULL || out == NULL || len < OVERHEAD) {
        return ERR_SHORT;
    }
    int status = check_header(buf, len);
    if (status != 0) {
        return status;
    }
    uint8_t payload_len = buf[2];
    if (checksum(buf, payload_len) != buf[HEADER_LEN + payload_len]) {
        return ERR_CHECKSUM;
    }
    *type = buf[3];
    memcpy(out, &buf[HEADER_LEN], payload_len);
    return payload_len;
}
"""
FRAME_TESTS = """
#include "task.h"
#include "oge_test.h"

static size_t make(uint8_t *f, uint8_t len, uint8_t type)
{
    uint8_t x = len ^ type;
    f[0] = 0xEB; f[1] = 0x90; f[2] = len; f[3] = type;
    for (uint8_t i = 0; i < len; ++i) {
        f[4 + i] = (uint8_t)(i * 7 + 1);
        x ^= f[4 + i];
    }
    f[4 + len] = x;
    return (size_t)len + 5;
}

int main(void)
{
    uint8_t f[64], out[32], type = 0;
    size_t n = make(f, 3, 0x12);
    CHECK_EQ_I(frame_parse(f, n, &type, out), 3);
    CHECK_EQ_U(type, 0x12);
    CHECK_EQ_U(out[0], 1); CHECK_EQ_U(out[1], 8); CHECK_EQ_U(out[2], 15);
    n = make(f, 32, 0x1F);
    CHECK_EQ_I(frame_parse(f, n, &type, out), 32);
    CHECK_EQ_I(frame_parse(f, n - 1, &type, out), -3);
    CHECK_EQ_I(frame_parse(f, 4, &type, out), -1);
    CHECK_EQ_I(frame_parse(NULL, n, &type, out), -1);
    CHECK_EQ_I(frame_parse(f, n, NULL, out), -1);
    n = make(f, 2, 0x10); f[1] = 0x91;
    CHECK_EQ_I(frame_parse(f, n, &type, out), -2);
    n = make(f, 2, 0x20);
    CHECK_EQ_I(frame_parse(f, n, &type, out), -4);
    n = make(f, 2, 0x0F);
    CHECK_EQ_I(frame_parse(f, n, &type, out), -4);
    n = make(f, 2, 0x11); f[5] ^= 0x40;
    CHECK_EQ_I(frame_parse(f, n, &type, out), -5);
    f[0] = 0xEB; f[1] = 0x90; f[2] = 0; f[3] = 0x11; f[4] = 0x11;
    CHECK_EQ_I(frame_parse(f, 5, &type, out), -3);
    n = make(f, 33, 0x11);
    CHECK_EQ_I(frame_parse(f, n, &type, out), -3);
    return OGE_REPORT();
}
"""

MODE_H = """
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
"""
MODE_ORIG = """
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
"""
MODE_REF = """
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
"""
MODE_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    mode_mgr_t m;
    mode_init(&m);
    CHECK_EQ_I(mode_handle(&m, 2), 0);  CHECK_EQ_U(m.mode, 0);
    CHECK_EQ_I(mode_handle(&m, 4), 0);  CHECK_EQ_U(m.mode, 0);
    CHECK_EQ_I(mode_handle(&m, 0), 1);  CHECK_EQ_U(m.mode, 1);
    CHECK_EQ_I(mode_handle(&m, 0), 0);  CHECK_EQ_U(m.mode, 1);
    CHECK_EQ_I(mode_handle(&m, 3), 0);
    CHECK_EQ_I(mode_handle(&m, 2), 1);  CHECK_EQ_U(m.mode, 2);
    CHECK_EQ_I(mode_handle(&m, 5), 0);
    CHECK_EQ_I(mode_handle(&m, 3), 1);  CHECK_EQ_U(m.mode, 1);
    CHECK_EQ_I(mode_handle(&m, 4), 1);  CHECK_EQ_U(m.mode, 3);
    CHECK_EQ_I(mode_handle(&m, 2), 0);  CHECK_EQ_U(m.mode, 3);
    CHECK_EQ_I(mode_handle(&m, 4), 1);  CHECK_EQ_U(m.mode, 3);
    CHECK_EQ_I(mode_handle(&m, 5), 1);  CHECK_EQ_U(m.mode, 1);
    CHECK_EQ_I(mode_handle(&m, 2), 1);
    CHECK_EQ_I(mode_handle(&m, 4), 1);  CHECK_EQ_U(m.mode, 3);
    CHECK_EQ_I(mode_handle(&m, 1), 1);  CHECK_EQ_U(m.mode, 0);
    CHECK_EQ_I(mode_handle(&m, 1), 1);  CHECK_EQ_U(m.mode, 0);
    CHECK_EQ_I(mode_handle(&m, 9), 0);
    CHECK_EQ_U(m.transitions, 10);
    return OGE_REPORT();
}
"""

TLM_H = """
#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Housekeeping telemetry packed into 8 bytes, MSB first:
   byte 0: mode (2 bits) | heater on (1) | fault (1) | channel (4)
   bytes 1-2: temperature in 0.1 degC, signed 16-bit, clamped to [-1000, 1500]
   bytes 3-4: bus voltage in mV, unsigned 16-bit, clamped to [0, 40000]
   byte 5: gain (0..63, upper 2 bits = 0; values above 63 are clamped to 63)
   bytes 6-7: packet counter, big endian.
   Fields wider than their bit width are masked (mode & 3, channel & 15, flags != 0 -> 1). */
typedef struct {
    uint8_t mode;
    uint8_t heater_on;
    uint8_t fault;
    uint8_t channel;
    int32_t temp_decic;
    int32_t bus_mv;
    uint8_t gain;
    uint16_t counter;
} hk_t;

void hk_pack(const hk_t *hk, uint8_t out[8]);

#endif
"""
TLM_ORIG = """
#include "task.h"

void hk_pack(const hk_t *hk, uint8_t out[8])
{
    int32_t t;
    int32_t v;
    uint8_t g;
    uint8_t b0 = 0;
    b0 = b0 | (uint8_t)((hk->mode & 3) << 6);
    if (hk->heater_on != 0) {
        b0 = b0 | (1 << 5);
    }
    if (hk->fault != 0) {
        b0 = b0 | (1 << 4);
    }
    b0 = b0 | (uint8_t)(hk->channel & 15);
    out[0] = b0;
    t = hk->temp_decic;
    if (t < -1000) {
        t = -1000;
    }
    if (t > 1500) {
        t = 1500;
    }
    out[1] = (uint8_t)(((uint16_t)(int16_t)t >> 8) & 0xFF);
    out[2] = (uint8_t)((uint16_t)(int16_t)t & 0xFF);
    v = hk->bus_mv;
    if (v < 0) {
        v = 0;
    }
    if (v > 40000) {
        v = 40000;
    }
    out[3] = (uint8_t)(((uint32_t)v >> 8) & 0xFF);
    out[4] = (uint8_t)((uint32_t)v & 0xFF);
    g = hk->gain;
    if (g > 63) {
        g = 63;
    }
    out[5] = g;
    out[6] = (uint8_t)((hk->counter >> 8) & 0xFF);
    out[7] = (uint8_t)(hk->counter & 0xFF);
}
"""
TLM_REF = """
#include "task.h"

enum { MODE_MASK = 0x3u, CHANNEL_MASK = 0xFu, MODE_SHIFT = 6u, HEATER_BIT = 5u, FAULT_BIT = 4u };
enum { TEMP_MIN = -1000, TEMP_MAX = 1500, BUS_MIN = 0, BUS_MAX = 40000, GAIN_MAX = 63u };

static int32_t clamp(int32_t v, int32_t lo, int32_t hi) { return v < lo ? lo : (v > hi ? hi : v); }

static void put_be16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)v;
}

static uint8_t status_byte(const hk_t *hk)
{
    return (uint8_t)(((hk->mode & MODE_MASK) << MODE_SHIFT) | ((hk->heater_on != 0u) << HEATER_BIT) |
                     ((hk->fault != 0u) << FAULT_BIT) | (hk->channel & CHANNEL_MASK));
}

void hk_pack(const hk_t *hk, uint8_t out[8])
{
    out[0] = status_byte(hk);
    put_be16(&out[1], (uint16_t)(int16_t)clamp(hk->temp_decic, TEMP_MIN, TEMP_MAX));
    put_be16(&out[3], (uint16_t)clamp(hk->bus_mv, BUS_MIN, BUS_MAX));
    out[5] = hk->gain > GAIN_MAX ? (uint8_t)GAIN_MAX : hk->gain;
    put_be16(&out[6], hk->counter);
}
"""
TLM_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    uint8_t out[8];
    hk_t hk = {2, 1, 0, 9, 235, 28123, 17, 0x1234};
    const uint8_t e1[8] = {0xA9, 0x00, 0xEB, 0x6D, 0xDB, 0x11, 0x12, 0x34};
    hk_pack(&hk, out);
    CHECK_MEM(out, e1, 8);
    hk.mode = 7; hk.heater_on = 0; hk.fault = 5; hk.channel = 0x1F;
    hk.temp_decic = -2000; hk.bus_mv = -5; hk.gain = 200; hk.counter = 0xFFFF;
    {
        const uint8_t e2[8] = {0xDF, 0xFC, 0x18, 0x00, 0x00, 0x3F, 0xFF, 0xFF};
        hk_pack(&hk, out);
        CHECK_MEM(out, e2, 8);
    }
    hk.temp_decic = 99999; hk.bus_mv = 99999; hk.gain = 63;
    {
        const uint8_t e3[8] = {0xDF, 0x05, 0xDC, 0x9C, 0x40, 0x3F, 0xFF, 0xFF};
        hk_pack(&hk, out);
        CHECK_MEM(out, e3, 8);
    }
    return OGE_REPORT();
}
"""

CFG_H = """
#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Radio configuration validation. Rules, checked in this order (first failure wins):
   1 frequency_khz in [400000, 470000]          -> error 1
   2 frequency_khz multiple of 25                -> error 2
   3 bandwidth_khz in {125, 250, 500}            -> error 3
   4 spreading_factor in [7, 12]                 -> error 4
   5 tx_power_dbm in [-4, 20]                    -> error 5
   6 if bandwidth_khz == 500, spreading_factor <= 10   -> error 6
   7 if tx_power_dbm > 14, duty_cycle_pct <= 10        -> error 7
   8 duty_cycle_pct in [1, 100]                  -> error 8
   Returns 0 when valid. */
typedef struct {
    uint32_t frequency_khz;
    uint16_t bandwidth_khz;
    uint8_t spreading_factor;
    int8_t tx_power_dbm;
    uint8_t duty_cycle_pct;
} radio_cfg_t;

int radio_cfg_validate(const radio_cfg_t *c);

#endif
"""
CFG_ORIG = """
#include "task.h"

int radio_cfg_validate(const radio_cfg_t *c)
{
    if (c->frequency_khz < 400000 || c->frequency_khz > 470000) {
        return 1;
    } else if (c->frequency_khz % 25 != 0) {
        return 2;
    } else if (c->bandwidth_khz != 125 && c->bandwidth_khz != 250 && c->bandwidth_khz != 500) {
        return 3;
    } else if (c->spreading_factor < 7 || c->spreading_factor > 12) {
        return 4;
    } else if (c->tx_power_dbm < -4 || c->tx_power_dbm > 20) {
        return 5;
    } else if (c->bandwidth_khz == 500 && c->spreading_factor > 10) {
        return 6;
    } else if (c->tx_power_dbm > 14 && c->duty_cycle_pct > 10) {
        return 7;
    } else if (c->duty_cycle_pct < 1 || c->duty_cycle_pct > 100) {
        return 8;
    } else {
        return 0;
    }
}
"""
CFG_REF = """
#include "task.h"

#include <stdbool.h>
#include <stddef.h>

enum { FREQ_MIN_KHZ = 400000, FREQ_MAX_KHZ = 470000, FREQ_STEP_KHZ = 25 };
enum { SF_MIN = 7, SF_MAX = 12, SF_MAX_WIDE = 10, WIDE_BW_KHZ = 500 };
enum { POWER_MIN_DBM = -4, POWER_MAX_DBM = 20, HIGH_POWER_DBM = 14, HIGH_POWER_DUTY_MAX = 10 };
enum { DUTY_MIN = 1, DUTY_MAX = 100 };

typedef bool (*rule_t)(const radio_cfg_t *c);

static bool in_range(long v, long lo, long hi) { return v >= lo && v <= hi; }

static bool freq_in_band(const radio_cfg_t *c) { return in_range((long)c->frequency_khz, FREQ_MIN_KHZ, FREQ_MAX_KHZ); }
static bool freq_on_grid(const radio_cfg_t *c) { return c->frequency_khz % FREQ_STEP_KHZ == 0u; }
static bool bandwidth_ok(const radio_cfg_t *c)
{
    return c->bandwidth_khz == 125u || c->bandwidth_khz == 250u || c->bandwidth_khz == 500u;
}
static bool sf_ok(const radio_cfg_t *c) { return in_range(c->spreading_factor, SF_MIN, SF_MAX); }
static bool power_ok(const radio_cfg_t *c) { return in_range(c->tx_power_dbm, POWER_MIN_DBM, POWER_MAX_DBM); }
static bool wide_band_sf_ok(const radio_cfg_t *c)
{
    return c->bandwidth_khz != WIDE_BW_KHZ || c->spreading_factor <= SF_MAX_WIDE;
}
static bool high_power_duty_ok(const radio_cfg_t *c)
{
    return c->tx_power_dbm <= HIGH_POWER_DBM || c->duty_cycle_pct <= HIGH_POWER_DUTY_MAX;
}
static bool duty_ok(const radio_cfg_t *c) { return in_range(c->duty_cycle_pct, DUTY_MIN, DUTY_MAX); }

/* Rule i failing yields error code i + 1. */
static const rule_t RULES[] = {freq_in_band, freq_on_grid, bandwidth_ok, sf_ok,
                               power_ok, wide_band_sf_ok, high_power_duty_ok, duty_ok};

int radio_cfg_validate(const radio_cfg_t *c)
{
    for (size_t i = 0u; i < sizeof RULES / sizeof RULES[0]; ++i) {
        if (!RULES[i](c)) {
            return (int)i + 1;
        }
    }
    return 0;
}
"""
CFG_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    radio_cfg_t ok = {433175, 125, 9, 10, 50};
    radio_cfg_t c;
    CHECK_EQ_I(radio_cfg_validate(&ok), 0);
    c = ok; c.frequency_khz = 399975; CHECK_EQ_I(radio_cfg_validate(&c), 1);
    c = ok; c.frequency_khz = 470025; CHECK_EQ_I(radio_cfg_validate(&c), 1);
    c = ok; c.frequency_khz = 433180; CHECK_EQ_I(radio_cfg_validate(&c), 2);
    c = ok; c.bandwidth_khz = 200; CHECK_EQ_I(radio_cfg_validate(&c), 3);
    c = ok; c.spreading_factor = 6; CHECK_EQ_I(radio_cfg_validate(&c), 4);
    c = ok; c.spreading_factor = 13; CHECK_EQ_I(radio_cfg_validate(&c), 4);
    c = ok; c.tx_power_dbm = -5; CHECK_EQ_I(radio_cfg_validate(&c), 5);
    c = ok; c.tx_power_dbm = 21; CHECK_EQ_I(radio_cfg_validate(&c), 5);
    c = ok; c.bandwidth_khz = 500; c.spreading_factor = 11; CHECK_EQ_I(radio_cfg_validate(&c), 6);
    c = ok; c.bandwidth_khz = 500; c.spreading_factor = 10; CHECK_EQ_I(radio_cfg_validate(&c), 0);
    c = ok; c.tx_power_dbm = 15; c.duty_cycle_pct = 11; CHECK_EQ_I(radio_cfg_validate(&c), 7);
    c = ok; c.tx_power_dbm = 14; c.duty_cycle_pct = 100; CHECK_EQ_I(radio_cfg_validate(&c), 0);
    c = ok; c.duty_cycle_pct = 0; CHECK_EQ_I(radio_cfg_validate(&c), 8);
    c = ok; c.duty_cycle_pct = 101; CHECK_EQ_I(radio_cfg_validate(&c), 8);
    c = ok; c.frequency_khz = 1; c.bandwidth_khz = 7; CHECK_EQ_I(radio_cfg_validate(&c), 1);
    c = ok; c.spreading_factor = 3; c.tx_power_dbm = 99; CHECK_EQ_I(radio_cfg_validate(&c), 4);
    return OGE_REPORT();
}
"""


def refactor_task(tid: str, title: str, domain: str, header: str, orig: str, ref: str, tests: str) -> None:
    write(
        tid,
        {
            "task.yaml": f"""
            id: {tid}
            category: refactor
            title: {title}
            domain: {domain}
            difficulty: medium
            description: |
              {REFACTOR_RULES}
            """,
            "task.h": header,
            "original.c": orig,
            "solution.c": ref,
            "tests.c": tests,
        },
    )


def all_refactor() -> None:
    refactor_task(
        "ref-command-dispatch",
        "Refactor a nested command dispatcher",
        "payload command handling",
        DISPATCH_H,
        DISPATCH_ORIG,
        DISPATCH_REF,
        DISPATCH_TESTS,
    )
    refactor_task(
        "ref-frame-parser",
        "Refactor a goto-based frame parser",
        "link-layer framing",
        FRAME_H,
        FRAME_ORIG,
        FRAME_REF,
        FRAME_TESTS,
    )
    refactor_task(
        "ref-mode-manager",
        "Refactor a flag-soup mode manager into a state table",
        "instrument modes",
        MODE_H,
        MODE_ORIG,
        MODE_REF,
        MODE_TESTS,
    )
    refactor_task(
        "ref-telemetry-pack",
        "Refactor repetitive telemetry packing",
        "housekeeping telemetry",
        TLM_H,
        TLM_ORIG,
        TLM_REF,
        TLM_TESTS,
    )
    refactor_task(
        "ref-config-validate",
        "Refactor a long validation if-chain into rules",
        "radio configuration",
        CFG_H,
        CFG_ORIG,
        CFG_REF,
        CFG_TESTS,
    )


# ============================================================================================ document
DOC_RULES = (
    "Add Doxygen documentation to every function of the code below: a block comment `/** ... */` "
    "immediately above each function with @brief, one @param per parameter (using the exact parameter "
    "name) and @return for non-void functions; describe units, ranges, error codes and preconditions. "
    "Do not change any code: only comments may be added."
)

PID_H = """
#ifndef TASK_H
#define TASK_H
#include <stdint.h>

typedef struct {
    int32_t kp_q8;
    int32_t ki_q8;
    int32_t kd_q8;
    int32_t integral;
    int32_t integral_limit;
    int32_t prev_error;
    int32_t out_min;
    int32_t out_max;
} pid_t_;

void pid_init(pid_t_ *p, int32_t kp_q8, int32_t ki_q8, int32_t kd_q8, int32_t out_min, int32_t out_max);
int32_t pid_step(pid_t_ *p, int32_t setpoint, int32_t measurement);

#endif
"""
PID_ORIG = """
#include "task.h"

static int32_t clamp(int32_t v, int32_t lo, int32_t hi)
{
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

void pid_init(pid_t_ *p, int32_t kp_q8, int32_t ki_q8, int32_t kd_q8, int32_t out_min, int32_t out_max)
{
    p->kp_q8 = kp_q8;
    p->ki_q8 = ki_q8;
    p->kd_q8 = kd_q8;
    p->integral = 0;
    p->integral_limit = 100000;
    p->prev_error = 0;
    p->out_min = out_min;
    p->out_max = out_max;
}

int32_t pid_step(pid_t_ *p, int32_t setpoint, int32_t measurement)
{
    int32_t error = setpoint - measurement;
    int32_t derivative = error - p->prev_error;
    p->integral = clamp(p->integral + error, -p->integral_limit, p->integral_limit);
    p->prev_error = error;
    int32_t out = (p->kp_q8 * error + p->ki_q8 * p->integral + p->kd_q8 * derivative) / 256;
    return clamp(out, p->out_min, p->out_max);
}
"""
PID_DOC = """
#include "task.h"

/**
 * @brief Clamp a value to an inclusive range.
 * @param v  Value to clamp.
 * @param lo Lower bound (inclusive).
 * @param hi Upper bound (inclusive), must be >= lo.
 * @return v limited to [lo, hi].
 */
static int32_t clamp(int32_t v, int32_t lo, int32_t hi)
{
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

/**
 * @brief Initialise a fixed-point PID controller.
 * @param p       Controller state to initialise (non-NULL).
 * @param kp_q8   Proportional gain in Q8 (256 = 1.0).
 * @param ki_q8   Integral gain in Q8.
 * @param kd_q8   Derivative gain in Q8.
 * @param out_min Lowest allowed controller output.
 * @param out_max Highest allowed controller output (>= out_min).
 */
void pid_init(pid_t_ *p, int32_t kp_q8, int32_t ki_q8, int32_t kd_q8, int32_t out_min, int32_t out_max)
{
    p->kp_q8 = kp_q8;
    p->ki_q8 = ki_q8;
    p->kd_q8 = kd_q8;
    p->integral = 0;
    p->integral_limit = 100000;
    p->prev_error = 0;
    p->out_min = out_min;
    p->out_max = out_max;
}

/**
 * @brief Run one control step (anti-windup by clamping the integral to +/- integral_limit).
 * @param p           Controller state (updated: integral and previous error).
 * @param setpoint    Desired value, same unit as measurement.
 * @param measurement Measured value.
 * @return Control output (Q8 gains applied, divided by 256), clamped to [out_min, out_max].
 */
int32_t pid_step(pid_t_ *p, int32_t setpoint, int32_t measurement)
{
    int32_t error = setpoint - measurement;
    int32_t derivative = error - p->prev_error;
    p->integral = clamp(p->integral + error, -p->integral_limit, p->integral_limit);
    p->prev_error = error;
    int32_t out = (p->kp_q8 * error + p->ki_q8 * p->integral + p->kd_q8 * derivative) / 256;
    return clamp(out, p->out_min, p->out_max);
}
"""
PID_TESTS = """
#include "task.h"
#include "oge_test.h"

int main(void)
{
    pid_t_ p;
    pid_init(&p, 512, 0, 0, -1000, 1000);
    CHECK_EQ_I(pid_step(&p, 100, 40), 120);
    CHECK_EQ_I(pid_step(&p, 1000, 0), 1000);
    pid_init(&p, 0, 256, 0, -50, 50);
    CHECK_EQ_I(pid_step(&p, 10, 0), 10);
    CHECK_EQ_I(pid_step(&p, 10, 0), 20);
    CHECK_EQ_I(pid_step(&p, -100, 0), -50);
    pid_init(&p, 0, 0, 256, -500, 500);
    CHECK_EQ_I(pid_step(&p, 5, 0), 5);
    CHECK_EQ_I(pid_step(&p, 5, 0), 0);
    return OGE_REPORT();
}
"""

DOC_SOURCES = {
    "doc-ring-buffer": ("Document a ring-buffer API", "driver buffering", RB_H, RB_IMPL, RB_TESTS),
    "doc-saturating-arith": (
        "Document saturating arithmetic helpers",
        "fixed-point DSP",
        SAT_H,
        SAT_IMPL,
        SAT_TESTS,
    ),
    "doc-ccsds-parse": (
        "Document a CCSDS header parser",
        "space telemetry",
        CCSDS_H,
        CCSDS_IMPL,
        CCSDS_TESTS,
    ),
    "doc-pid": ("Document a fixed-point PID controller", "control loops", PID_H, PID_ORIG, PID_TESTS),
}


def auto_document(code: str) -> str:
    """Reference documentation for the simple sources: generated from signatures, then checked by the scorer."""
    import re  # noqa: PLC0415

    out = []
    for line in d(code).splitlines():
        m = re.match(r"^(static\s+)?([\w\s\*]+?)\s+\**(\w+)\((.*)\)\s*(\{.*)?$", line)
        if m and not line.startswith((" ", "#", "}")) and "=" not in line:
            ret, name, params = m.group(2).strip(), m.group(3), m.group(4)
            names = [
                re.split(r"[\s*]+", p.strip())[-1].split("[")[0]
                for p in params.split(",")
                if p.strip() not in ("", "void")
            ]
            doc = ["/**", f" * @brief {name.replace('_', ' ')}."]
            doc += [f" * @param {n} Input `{n}`." for n in names]
            if ret != "void":
                doc.append(" * @return Result, see task.h for ranges and error codes.")
            doc.append(" */")
            out.extend(doc)
        out.append(line)
    return "\n".join(out) + "\n"


def all_document() -> None:
    for tid, (title, domain, header, orig, tests) in DOC_SOURCES.items():
        ref = PID_DOC if tid == "doc-pid" else auto_document(orig)
        write(
            tid,
            {
                "task.yaml": f"""
                id: {tid}
                category: document
                title: {title}
                domain: {domain}
                difficulty: easy
                description: |
                  {DOC_RULES}
                """,
                "task.h": header,
                "original.c": orig,
                "solution.c": ref,
                "tests.c": tests,
            },
        )


def main() -> None:
    all_testgen()
    all_refactor()
    all_document()
    print(f"testgen / refactor / document tasks written to {ROOT}")


if __name__ == "__main__":
    main()

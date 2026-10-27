"""Author the 'generate' tasks of the evaluation suite.

Expected values in the hidden tests are computed here by independent Python reference implementations (or the
standard library, e.g. zlib for CRC-32), never typed by hand. Re-run to regenerate:

    python scripts/evalsuite/gen_generate_tasks.py
"""

from __future__ import annotations

import random
import textwrap
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "onprem_genai" / "evalsuite" / "tasks"


def c_bytes(data: bytes) -> str:
    return "{" + ", ".join(f"0x{b:02X}" for b in data) + "}" if data else "{0}"


def write_task(tid: str, meta: str, header: str, solution: str, tests: str) -> None:
    d = ROOT / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.yaml").write_text(textwrap.dedent(meta).lstrip())
    (d / "task.h").write_text(textwrap.dedent(header).lstrip())
    (d / "solution.c").write_text(textwrap.dedent(solution).lstrip())
    (d / "tests.c").write_text(textwrap.dedent(tests).lstrip())


TEST_PRELUDE = '#include "task.h"\n#include "oge_test.h"\n'


# --------------------------------------------------------------------------------------------- references
def crc16_ccitt_false(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def cobs_encode(data: bytes) -> bytes:
    """Canonical COBS (Cheshire & Baker; reference encoder on Wikipedia): no trailing code byte when the input
    ends exactly on a 254-byte block boundary."""
    out = bytearray([0])
    code_idx: int | None = 0
    code = 1
    for i, b in enumerate(data):
        remaining = len(data) - i - 1
        if b != 0:
            out.append(b)
            code += 1
        if b == 0 or code == 0xFF:
            assert code_idx is not None
            out[code_idx] = code
            code = 1
            if b == 0 or remaining:
                code_idx = len(out)
                out.append(0)
            else:
                code_idx = None
    if code_idx is not None:
        out[code_idx] = code
    return bytes(out)


def debounce(initial: bool, raw: str, samples: int = 4) -> str:
    state, count, out = initial, 0, []
    for ch in raw:
        r = ch == "1"
        if r == state:
            count = 0
        else:
            count += 1
            if count >= samples:
                state, count = r, 0
        out.append("1" if state else "0")
    return "".join(out)


def q15_mul(a: int, b: int) -> int:
    r = (a * b + (1 << 14)) >> 15
    return max(-32768, min(32767, r))


def q15_add_sat(a: int, b: int) -> int:
    return max(-32768, min(32767, a + b))


def scramble(seed: int, data: bytes) -> bytes:
    s = seed & 0x7F or 0x7F
    out = bytearray()
    for byte in data:
        o = 0
        for i in range(8):
            bit = (byte >> i) & 1
            fb = ((s >> 6) ^ (s >> 3)) & 1
            o |= (bit ^ fb) << i
            s = ((s << 1) | fb) & 0x7F
        out.append(o)
    return bytes(out)


def conv_encode(data: bytes, nbits: int) -> bytes:
    p1 = p2 = 0
    bits = []
    for k in range(nbits):
        u = (data[k // 8] >> (7 - k % 8)) & 1
        bits += [u ^ p1 ^ p2, u ^ p2]
        p2, p1 = p1, u
    out = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        out[i // 8] |= b << (7 - i % 8)
    return bytes(out)


def ccsds_bytes(version: int, ptype: int, sec: int, apid: int, flags: int, count: int, length: int) -> bytes:
    w0 = (version << 13) | (ptype << 12) | (sec << 11) | apid
    w1 = (flags << 14) | count
    return bytes([w0 >> 8, w0 & 0xFF, w1 >> 8, w1 & 0xFF, length >> 8, length & 0xFF])


# --------------------------------------------------------------------------------------------- tasks
def task_crc16() -> None:
    vec = [b"123456789", b"", b"\x00", b"\xff\xff\xff\xff", bytes(range(32)), b"FLIGHT SOFTWARE"]
    checks = "\n".join(
        f"    {{ const uint8_t d[] = {c_bytes(v)}; CHECK_EQ_U(crc16_ccitt_false(d, {len(v)}), 0x{crc16_ccitt_false(v):04X}); }}"
        for v in vec
    )
    write_task(
        "gen-crc16-ccitt",
        """
        id: gen-crc16-ccitt
        category: generate
        title: CRC-16/CCITT-FALSE with incremental update
        domain: integrity checks (telecommand / telemetry frames)
        difficulty: easy
        description: |
          Implement the two functions declared in task.h: CRC-16/CCITT-FALSE (polynomial 0x1021, initial value
          0xFFFF, no input/output reflection, final XOR 0x0000), computed bitwise or with a table, plus an
          incremental variant that continues a CRC over additional data. `data` may be NULL when `len` is 0.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stddef.h>
        #include <stdint.h>

        /* CRC-16/CCITT-FALSE of data[0..len): poly 0x1021, init 0xFFFF, no reflection, xorout 0x0000. */
        uint16_t crc16_ccitt_false(const uint8_t *data, size_t len);

        /* Continue a CRC: crc16_ccitt_update(crc16_ccitt_false(a, n), b, m) == CRC of a followed by b.
           crc16_ccitt_update(0xFFFF, d, n) == crc16_ccitt_false(d, n). data may be NULL when len == 0. */
        uint16_t crc16_ccitt_update(uint16_t crc, const uint8_t *data, size_t len);

        #endif
        """,
        """
        #include "task.h"

        uint16_t crc16_ccitt_update(uint16_t crc, const uint8_t *data, size_t len)
        {
            for (size_t i = 0; i < len; ++i) {
                crc ^= (uint16_t)((uint16_t)data[i] << 8);
                for (int b = 0; b < 8; ++b) {
                    crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
                }
            }
            return crc;
        }

        uint16_t crc16_ccitt_false(const uint8_t *data, size_t len)
        {
            return crc16_ccitt_update(0xFFFFu, data, len);
        }
        """,
        TEST_PRELUDE
        + f"""
int main(void)
{{
{checks}
    CHECK_EQ_U(crc16_ccitt_false(NULL, 0), 0xFFFF);
    {{
        const uint8_t d[] = "123456789";
        uint16_t c = crc16_ccitt_false(d, 4);
        c = crc16_ccitt_update(c, d + 4, 5);
        CHECK_EQ_U(c, 0x29B1);
        CHECK_EQ_U(crc16_ccitt_update(0xFFFF, d, 9), crc16_ccitt_false(d, 9));
        CHECK_EQ_U(crc16_ccitt_update(0x1234, NULL, 0), 0x1234);
    }}
    return OGE_REPORT();
}}
""",
    )


def task_crc32() -> None:
    vec = [b"123456789", b"", b"a", b"The quick brown fox jumps over the lazy dog", bytes(range(256))]
    checks = "\n".join(
        f"    {{ static const uint8_t d[] = {c_bytes(v)}; CHECK_EQ_U(crc32_ieee(d, {len(v)}), 0x{zlib.crc32(v):08X}u); }}"
        for v in vec
    )
    write_task(
        "gen-crc32",
        """
        id: gen-crc32
        category: generate
        title: CRC-32 (ISO-HDLC / IEEE 802.3)
        domain: integrity checks (file transfer, Ethernet)
        difficulty: easy
        description: |
          Implement CRC-32/ISO-HDLC as used by Ethernet and zlib: reflected polynomial 0xEDB88320, initial value
          0xFFFFFFFF, reflected input and output, final XOR 0xFFFFFFFF. Also implement the incremental update
          declared in task.h. A 256-entry table is allowed but must be computed or written statically (no heap).
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stddef.h>
        #include <stdint.h>

        /* CRC-32/ISO-HDLC of data[0..len). crc32_ieee("123456789", 9) == 0xCBF43926. */
        uint32_t crc32_ieee(const uint8_t *data, size_t len);

        /* Incremental: crc32_ieee_update(crc32_ieee(a, n), b, m) == CRC-32 of a followed by b;
           crc32_ieee_update(0, d, n) == crc32_ieee(d, n). data may be NULL when len == 0. */
        uint32_t crc32_ieee_update(uint32_t crc, const uint8_t *data, size_t len);

        #endif
        """,
        """
        #include "task.h"

        uint32_t crc32_ieee_update(uint32_t crc, const uint8_t *data, size_t len)
        {
            crc = ~crc;
            for (size_t i = 0; i < len; ++i) {
                crc ^= data[i];
                for (int b = 0; b < 8; ++b) {
                    crc = (crc & 1u) ? (crc >> 1) ^ 0xEDB88320u : crc >> 1;
                }
            }
            return ~crc;
        }

        uint32_t crc32_ieee(const uint8_t *data, size_t len)
        {
            return crc32_ieee_update(0u, data, len);
        }
        """,
        TEST_PRELUDE
        + f"""
int main(void)
{{
{checks}
    {{
        const uint8_t d[] = "123456789";
        uint32_t c = crc32_ieee(d, 3);
        c = crc32_ieee_update(c, d + 3, 6);
        CHECK_EQ_U(c, 0xCBF43926u);
        CHECK_EQ_U(crc32_ieee_update(0, d, 9), 0xCBF43926u);
        CHECK_EQ_U(crc32_ieee(NULL, 0), 0u);
    }}
    return OGE_REPORT();
}}
""",
    )


def task_ring_buffer() -> None:
    write_task(
        "gen-ring-buffer",
        """
        id: gen-ring-buffer
        category: generate
        title: Fixed-capacity byte ring buffer
        domain: UART / radio driver buffering
        difficulty: easy
        description: |
          Implement the FIFO byte ring buffer declared in task.h using only the fields of ring_buffer_t (no heap,
          capacity RB_CAPACITY, not necessarily a power of two). A push on a full buffer must fail without
          overwriting; a pop on an empty buffer must fail without writing *out.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stdbool.h>
        #include <stddef.h>
        #include <stdint.h>

        #define RB_CAPACITY 7u

        typedef struct {
            uint8_t data[RB_CAPACITY];
            size_t head;  /* next write index */
            size_t tail;  /* next read index */
            size_t count; /* number of stored bytes */
        } ring_buffer_t;

        void rb_init(ring_buffer_t *rb);
        bool rb_push(ring_buffer_t *rb, uint8_t byte);      /* false when full (nothing stored) */
        bool rb_pop(ring_buffer_t *rb, uint8_t *out);       /* false when empty (*out untouched) */
        size_t rb_count(const ring_buffer_t *rb);
        bool rb_is_full(const ring_buffer_t *rb);
        size_t rb_push_many(ring_buffer_t *rb, const uint8_t *src, size_t n); /* stores as many as fit, returns count */

        #endif
        """,
        """
        #include "task.h"

        void rb_init(ring_buffer_t *rb)
        {
            rb->head = 0u;
            rb->tail = 0u;
            rb->count = 0u;
        }

        bool rb_push(ring_buffer_t *rb, uint8_t byte)
        {
            if (rb->count == RB_CAPACITY) {
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

        bool rb_is_full(const ring_buffer_t *rb) { return rb->count == RB_CAPACITY; }

        size_t rb_push_many(ring_buffer_t *rb, const uint8_t *src, size_t n)
        {
            size_t stored = 0u;
            while (stored < n && rb_push(rb, src[stored])) {
                stored++;
            }
            return stored;
        }
        """,
        TEST_PRELUDE
        + """
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
""",
    )


def task_cobs() -> None:
    cases = [
        b"",
        b"\x00",
        b"\x00\x00",
        b"\x00\x11\x00",
        b"\x11\x22\x00\x33",
        b"\x11\x22\x33\x44",
        b"\x11\x00\x00\x00",
        bytes(range(1, 255)),
        bytes(range(0, 255)),
        bytes(range(1, 256)),
        bytes(range(2, 256)) + b"\x00",
    ]
    lines = []
    for i, c in enumerate(cases):
        enc = cobs_encode(c)
        lines.append(
            f"    {{ static const uint8_t in{i}[] = {c_bytes(c)}; static const uint8_t ex{i}[] = {c_bytes(enc)};\n"
            f"      uint8_t enc[600]; uint8_t dec[600];\n"
            f"      size_t n = cobs_encode(in{i}, {len(c)}, enc); CHECK_EQ_U(n, {len(enc)}); CHECK_MEM(enc, ex{i}, {len(enc)});\n"
            f"      CHECK_EQ_U(cobs_decode(enc, n, dec), {len(c)});"
            + (f" CHECK_MEM(dec, in{i}, {len(c)});" if c else "")
            + " }"
        )
    write_task(
        "gen-cobs",
        """
        id: gen-cobs
        category: generate
        title: COBS framing (Consistent Overhead Byte Stuffing)
        domain: serial / radio link framing
        difficulty: medium
        description: |
          Implement COBS encoding and decoding as specified by Cheshire & Baker (the variant used by most embedded
          stacks, without a trailing 0x00 delimiter in the output). Encoding never emits a zero byte; a block of
          254 non-zero bytes is emitted with code 0xFF. Decoding returns 0 for malformed input: empty input, a
          zero byte inside the frame, or a code byte pointing past the end of the input.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stddef.h>
        #include <stdint.h>

        /* Encode src[0..len) into dst. dst must hold at least len + len / 254 + 1 bytes.
           Returns the encoded length (always >= 1; the encoding of an empty input is {0x01}). */
        size_t cobs_encode(const uint8_t *src, size_t len, uint8_t *dst);

        /* Decode src[0..len) into dst (capacity >= len). Returns the decoded length, or 0 when the input is
           malformed (len == 0, a 0x00 byte inside src, or a code byte that points past the end). */
        size_t cobs_decode(const uint8_t *src, size_t len, uint8_t *dst);

        #endif
        """,
        """
        #include "task.h"
        #include <stdbool.h>

        size_t cobs_encode(const uint8_t *src, size_t len, uint8_t *dst)
        {
            size_t out = 1u;
            size_t code_idx = 0u;
            uint8_t code = 1u;
            bool open = true;
            for (size_t i = 0u; i < len; ++i) {
                if (src[i] != 0u) {
                    dst[out++] = src[i];
                    code++;
                }
                if (src[i] == 0u || code == 0xFFu) {
                    dst[code_idx] = code;
                    code = 1u;
                    if (src[i] == 0u || i + 1u < len) {
                        code_idx = out++;
                    } else {
                        open = false;
                    }
                }
            }
            if (open) {
                dst[code_idx] = code;
            }
            return out;
        }

        size_t cobs_decode(const uint8_t *src, size_t len, uint8_t *dst)
        {
            size_t in = 0u;
            size_t out = 0u;
            if (len == 0u) {
                return 0u;
            }
            while (in < len) {
                uint8_t code = src[in];
                if (code == 0u || in + code > len) {
                    return 0u;
                }
                in++;
                for (uint8_t k = 1u; k < code; ++k) {
                    if (src[in] == 0u) {
                        return 0u;
                    }
                    dst[out++] = src[in++];
                }
                if (code != 0xFFu && in < len) {
                    dst[out++] = 0u;
                }
            }
            return out;
        }
        """,
        TEST_PRELUDE
        + "\nint main(void)\n{\n"
        + "\n".join(lines)
        + """
    {
        uint8_t dec[16];
        static const uint8_t bad_zero[] = {0x03, 0x11, 0x00};
        static const uint8_t bad_len[] = {0x05, 0x11, 0x22};
        CHECK_EQ_U(cobs_decode(bad_zero, 3, dec), 0);
        CHECK_EQ_U(cobs_decode(bad_len, 3, dec), 0);
        CHECK_EQ_U(cobs_decode(bad_len, 0, dec), 0);
    }
    {
        /* deterministic pseudo-random round trips */
        uint32_t x = 12345u;
        uint8_t in[300], enc[310], dec[310];
        for (int t = 0; t < 200; ++t) {
            size_t n = (size_t)(t * 7 % 300) + 1u;
            for (size_t i = 0; i < n; ++i) {
                x = x * 1103515245u + 12345u;
                in[i] = (uint8_t)((x >> 16) % 4u == 0u ? 0u : (x >> 8));
            }
            size_t e = cobs_encode(in, n, enc);
            int has_zero = 0;
            for (size_t i = 0; i < e; ++i) {
                has_zero |= enc[i] == 0u;
            }
            CHECK(!has_zero);
            CHECK_EQ_U(cobs_decode(enc, e, dec), n);
            CHECK_MEM(dec, in, n);
        }
    }
    return OGE_REPORT();
}
""",
    )


def task_hamming() -> None:
    write_task(
        "gen-hamming74",
        """
        id: gen-hamming74
        category: generate
        title: Hamming(7,4) encoder / single-error-correcting decoder
        domain: forward error correction
        difficulty: medium
        description: |
          Implement Hamming(7,4) with the bit layout documented in task.h (classic positions 1..7 =
          p1 p2 d1 p3 d2 d3 d4, position 1 stored in bit 6). The decoder corrects any single-bit error and reports
          whether it corrected one.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stdint.h>

        /* Codeword layout, bit 6 .. bit 0 = positions 1..7 = p1 p2 d1 p3 d2 d3 d4.
           The data nibble is d1 d2 d3 d4 with d1 its most significant bit.
           Parity (even): p1 covers positions 1,3,5,7; p2 covers 2,3,6,7; p3 covers 4,5,6,7. */
        uint8_t hamming74_encode(uint8_t nibble);                 /* uses the low 4 bits of nibble */

        /* Decodes the low 7 bits of codeword into *nibble (0..15).
           Returns 0 if the codeword was valid, 1 if a single-bit error was corrected. */
        int hamming74_decode(uint8_t codeword, uint8_t *nibble);

        #endif
        """,
        """
        #include "task.h"

        static uint8_t bit_at(uint8_t cw, unsigned pos) { return (uint8_t)((cw >> (7u - pos)) & 1u); }

        uint8_t hamming74_encode(uint8_t nibble)
        {
            uint8_t d1 = (nibble >> 3) & 1u, d2 = (nibble >> 2) & 1u, d3 = (nibble >> 1) & 1u, d4 = nibble & 1u;
            uint8_t p1 = d1 ^ d2 ^ d4, p2 = d1 ^ d3 ^ d4, p3 = d2 ^ d3 ^ d4;
            return (uint8_t)((p1 << 6) | (p2 << 5) | (d1 << 4) | (p3 << 3) | (d2 << 2) | (d3 << 1) | d4);
        }

        int hamming74_decode(uint8_t codeword, uint8_t *nibble)
        {
            uint8_t cw = codeword & 0x7Fu;
            unsigned s1 = bit_at(cw, 1) ^ bit_at(cw, 3) ^ bit_at(cw, 5) ^ bit_at(cw, 7);
            unsigned s2 = bit_at(cw, 2) ^ bit_at(cw, 3) ^ bit_at(cw, 6) ^ bit_at(cw, 7);
            unsigned s3 = bit_at(cw, 4) ^ bit_at(cw, 5) ^ bit_at(cw, 6) ^ bit_at(cw, 7);
            unsigned syndrome = s1 | (s2 << 1) | (s3 << 2);
            if (syndrome != 0u) {
                cw ^= (uint8_t)(1u << (7u - syndrome));
            }
            *nibble = (uint8_t)((bit_at(cw, 3) << 3) | (bit_at(cw, 5) << 2) | (bit_at(cw, 6) << 1) | bit_at(cw, 7));
            return syndrome != 0u;
        }
        """,
        TEST_PRELUDE
        + """
int main(void)
{
    static const uint8_t expected[16] = {0x00, 0x69, 0x2A, 0x43, 0x4C, 0x25, 0x66, 0x0F,
                                         0x70, 0x19, 0x5A, 0x33, 0x3C, 0x55, 0x16, 0x7F};
    for (uint8_t n = 0; n < 16; ++n) {
        uint8_t cw = hamming74_encode(n);
        uint8_t out = 0xFF;
        CHECK_EQ_U(cw, expected[n]);
        CHECK_EQ_U(hamming74_decode(cw, &out), 0);
        CHECK_EQ_U(out, n);
        for (unsigned bit = 0; bit < 7; ++bit) {
            out = 0xFF;
            CHECK_EQ_U(hamming74_decode((uint8_t)(cw ^ (1u << bit)), &out), 1);
            CHECK_EQ_U(out, n);
        }
    }
    {
        uint8_t out = 0;
        CHECK_EQ_U(hamming74_encode(0xF3), hamming74_encode(0x03));
        CHECK_EQ_U(hamming74_decode((uint8_t)(0x80 | expected[5]), &out), 0);
        CHECK_EQ_U(out, 5);
    }
    return OGE_REPORT();
}
""",
    )


def hamming_expected() -> list[int]:
    out = []
    for n in range(16):
        d1, d2, d3, d4 = (n >> 3) & 1, (n >> 2) & 1, (n >> 1) & 1, n & 1
        p1, p2, p3 = d1 ^ d2 ^ d4, d1 ^ d3 ^ d4, d2 ^ d3 ^ d4
        out.append((p1 << 6) | (p2 << 5) | (d1 << 4) | (p3 << 3) | (d2 << 2) | (d3 << 1) | d4)
    return out


def task_q15() -> None:
    rng = random.Random(7)
    pairs = [
        (-32768, -32768),
        (32767, 32767),
        (-32768, 32767),
        (16384, 16384),
        (-16384, 16384),
        (1, 1),
        (-1, 1),
        (12345, -23456),
        (100, -100),
        (0, -32768),
    ]
    pairs += [(rng.randint(-32768, 32767), rng.randint(-32768, 32767)) for _ in range(40)]
    mul = "\n".join(f"    CHECK_EQ_I(q15_mul({a}, {b}), {q15_mul(a, b)});" for a, b in pairs)
    add = "\n".join(f"    CHECK_EQ_I(q15_add_sat({a}, {b}), {q15_add_sat(a, b)});" for a, b in pairs[:25])
    write_task(
        "gen-q15-arith",
        """
        id: gen-q15-arith
        category: generate
        title: Q15 fixed-point multiply and saturating add
        domain: fixed-point DSP (filters, AGC)
        difficulty: medium
        description: |
          Implement saturating Q15 addition and Q15 multiplication with round-half-up and saturation, exactly as
          specified in task.h. Avoid undefined behaviour (signed overflow) in every case, including
          -32768 * -32768.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stdint.h>

        typedef int16_t q15_t; /* value = raw / 32768, range [-1, 1 - 2^-15] */

        /* a + b clamped to [-32768, 32767]. */
        q15_t q15_add_sat(q15_t a, q15_t b);

        /* floor((a * b + 2^14) / 2^15) computed exactly in integer arithmetic, then clamped to
           [-32768, 32767] (so -1.0 * -1.0 saturates to 32767). */
        q15_t q15_mul(q15_t a, q15_t b);

        #endif
        """,
        """
        #include "task.h"

        static q15_t clamp(int32_t v)
        {
            if (v > INT16_MAX) {
                return INT16_MAX;
            }
            if (v < INT16_MIN) {
                return INT16_MIN;
            }
            return (q15_t)v;
        }

        q15_t q15_add_sat(q15_t a, q15_t b) { return clamp((int32_t)a + (int32_t)b); }

        q15_t q15_mul(q15_t a, q15_t b)
        {
            int32_t p = (int32_t)a * (int32_t)b + (1 << 14);
            /* floor division by 2^15 without relying on implementation-defined right shifts */
            int32_t q = p / 32768;
            if ((p % 32768) != 0 && p < 0) {
                q -= 1;
            }
            return clamp(q);
        }
        """,
        TEST_PRELUDE + f"\nint main(void)\n{{\n{mul}\n{add}\n    return OGE_REPORT();\n}}\n",
    )


def task_tick() -> None:
    write_task(
        "gen-tick-elapsed",
        """
        id: gen-tick-elapsed
        category: generate
        title: Wraparound-safe timeout on a 32-bit tick counter
        domain: RTOS timers / watchdogs
        difficulty: easy
        description: |
          A free-running 32-bit millisecond counter wraps around every ~49.7 days. Implement the timeout helpers in
          task.h so they stay correct across wraparound (assume the true elapsed time is always < 2^31 ms).
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stdbool.h>
        #include <stdint.h>

        /* true iff at least timeout_ms milliseconds have passed between start and now (modulo 2^32). */
        bool tick_elapsed(uint32_t now, uint32_t start, uint32_t timeout_ms);

        /* milliseconds remaining before the timeout expires, 0 if already elapsed. */
        uint32_t tick_remaining(uint32_t now, uint32_t start, uint32_t timeout_ms);

        #endif
        """,
        """
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
        """,
        TEST_PRELUDE
        + """
int main(void)
{
    CHECK(!tick_elapsed(100, 0, 101));
    CHECK(tick_elapsed(101, 0, 101));
    CHECK(tick_elapsed(5000, 1000, 4000));
    CHECK(!tick_elapsed(4999, 1000, 4000));
    CHECK(tick_elapsed(0x10u, 0xFFFFFFF0u, 0x20u));
    CHECK(!tick_elapsed(0x0Fu, 0xFFFFFFF0u, 0x20u));
    CHECK(tick_elapsed(0x00000005u, 0xFFFFFFFBu, 10u));
    CHECK(!tick_elapsed(0x00000004u, 0xFFFFFFFBu, 10u));
    CHECK(tick_elapsed(123u, 123u, 0u));
    CHECK_EQ_U(tick_remaining(0x0Fu, 0xFFFFFFF0u, 0x20u), 1u);
    CHECK_EQ_U(tick_remaining(0x10u, 0xFFFFFFF0u, 0x20u), 0u);
    CHECK_EQ_U(tick_remaining(1000u, 1000u, 250u), 250u);
    CHECK_EQ_U(tick_remaining(0x7FFFFFFFu, 0u, 0xFFFFFFFFu), 0x80000000u);
    CHECK_EQ_U(tick_remaining(0xFFFFFFFFu, 0xFFFFFFFFu, 7u), 7u);
    return OGE_REPORT();
}
""",
    )


def task_scrambler() -> None:
    rng = random.Random(11)
    zeros = bytes(16)
    data = bytes(rng.randrange(256) for _ in range(40))
    seeds = [0x7F, 0x5D, 0x01, 0x00]
    lines = []
    for i, s in enumerate(seeds):
        for j, d in enumerate([zeros, data]):
            exp = scramble(s, d)
            lines.append(
                f"    {{ static const uint8_t in[] = {c_bytes(d)}; static const uint8_t ex[] = {c_bytes(exp)};\n"
                f"      uint8_t out[64]; scrambler_t s; scrambler_init(&s, 0x{s:02X});\n"
                f"      scrambler_apply(&s, in, out, {len(d)}); CHECK_MEM(out, ex, {len(d)}); }}  /* seed {i} data {j} */"
            )
    chunked_exp = scramble(0x5D, data)
    write_task(
        "gen-lfsr-scrambler",
        """
        id: gen-lfsr-scrambler
        category: generate
        title: Additive scrambler x^7 + x^4 + 1 (IEEE 802.11 style)
        domain: radio physical layer
        difficulty: medium
        description: |
          Implement the 7-bit additive scrambler exactly as defined in task.h (state layout, feedback taps, bit
          order). The scrambler keeps state across calls, so scrambling a buffer in several chunks must give the
          same output as in one call; applying it twice with the same seed restores the input. in and out may be
          the same buffer.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stddef.h>
        #include <stdint.h>

        /* State: bits x1..x7 of the shift register stored in bits 0..6 of `state` (bit 0 = x1, most recent).
           For each input bit b (bytes processed least-significant bit first):
               fb  = x7 XOR x4          (state bit 6 XOR state bit 3)
               out = b XOR fb
               state = ((state << 1) | fb) & 0x7F */
        typedef struct {
            uint8_t state;
        } scrambler_t;

        /* seed uses the low 7 bits; a zero seed is replaced by 0x7F (the all-zero state would lock up). */
        void scrambler_init(scrambler_t *s, uint8_t seed);

        /* Scrambles len bytes from in to out (in and out may alias); updates the state. */
        void scrambler_apply(scrambler_t *s, const uint8_t *in, uint8_t *out, size_t len);

        #endif
        """,
        """
        #include "task.h"

        void scrambler_init(scrambler_t *s, uint8_t seed)
        {
            s->state = (uint8_t)(seed & 0x7Fu);
            if (s->state == 0u) {
                s->state = 0x7Fu;
            }
        }

        void scrambler_apply(scrambler_t *s, const uint8_t *in, uint8_t *out, size_t len)
        {
            for (size_t i = 0u; i < len; ++i) {
                uint8_t byte = in[i];
                uint8_t res = 0u;
                for (unsigned b = 0u; b < 8u; ++b) {
                    uint8_t fb = (uint8_t)(((s->state >> 6) ^ (s->state >> 3)) & 1u);
                    res |= (uint8_t)((((byte >> b) & 1u) ^ fb) << b);
                    s->state = (uint8_t)(((s->state << 1) | fb) & 0x7Fu);
                }
                out[i] = res;
            }
        }
        """,
        TEST_PRELUDE
        + "\nint main(void)\n{\n"
        + "\n".join(lines)
        + f"""
    {{
        static const uint8_t in[] = {c_bytes(data)};
        static const uint8_t ex[] = {c_bytes(chunked_exp)};
        uint8_t buf[64];
        scrambler_t s;
        memcpy(buf, in, sizeof in);
        scrambler_init(&s, 0x5D);
        scrambler_apply(&s, buf, buf, 7);
        scrambler_apply(&s, buf + 7, buf + 7, sizeof in - 7);
        CHECK_MEM(buf, ex, sizeof in);
        scrambler_init(&s, 0x5D);
        scrambler_apply(&s, buf, buf, sizeof in);
        CHECK_MEM(buf, in, sizeof in);
    }}
    {{
        /* maximal-length sequence: state returns to the seed after exactly 127 bits */
        scrambler_t s;
        uint8_t zero = 0, tmp;
        unsigned period = 0;
        scrambler_init(&s, 0x2A);
        do {{
            /* advance one byte at a time and count bits until the state repeats at a byte boundary */
            scrambler_apply(&s, &zero, &tmp, 1);
            period += 8;
        }} while (s.state != 0x2A && period < 8 * 127 + 8);
        CHECK_EQ_U(period, 8 * 127);
    }}
    return OGE_REPORT();
}}
""",
    )


def task_endian() -> None:
    write_task(
        "gen-endian-codec",
        """
        id: gen-endian-codec
        category: generate
        title: Portable big/little-endian field codec
        domain: protocol encoding
        difficulty: easy
        description: |
          Implement byte-order helpers that work on any host endianness and on unaligned pointers, without
          undefined behaviour (beware integer promotion of uint8_t << 24).
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stdint.h>

        uint16_t read_be16(const uint8_t *p);
        uint32_t read_be32(const uint8_t *p);
        uint16_t read_le16(const uint8_t *p);
        uint32_t read_le32(const uint8_t *p);
        void write_be16(uint8_t *p, uint16_t v);
        void write_be32(uint8_t *p, uint32_t v);
        void write_le32(uint8_t *p, uint32_t v);

        #endif
        """,
        """
        #include "task.h"

        uint16_t read_be16(const uint8_t *p) { return (uint16_t)(((uint16_t)p[0] << 8) | p[1]); }
        uint32_t read_be32(const uint8_t *p)
        {
            return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | (uint32_t)p[3];
        }
        uint16_t read_le16(const uint8_t *p) { return (uint16_t)(((uint16_t)p[1] << 8) | p[0]); }
        uint32_t read_le32(const uint8_t *p)
        {
            return ((uint32_t)p[3] << 24) | ((uint32_t)p[2] << 16) | ((uint32_t)p[1] << 8) | (uint32_t)p[0];
        }
        void write_be16(uint8_t *p, uint16_t v)
        {
            p[0] = (uint8_t)(v >> 8);
            p[1] = (uint8_t)v;
        }
        void write_be32(uint8_t *p, uint32_t v)
        {
            p[0] = (uint8_t)(v >> 24);
            p[1] = (uint8_t)(v >> 16);
            p[2] = (uint8_t)(v >> 8);
            p[3] = (uint8_t)v;
        }
        void write_le32(uint8_t *p, uint32_t v)
        {
            p[0] = (uint8_t)v;
            p[1] = (uint8_t)(v >> 8);
            p[2] = (uint8_t)(v >> 16);
            p[3] = (uint8_t)(v >> 24);
        }
        """,
        TEST_PRELUDE
        + """
int main(void)
{
    uint8_t buf[11] = {0x00, 0xFE, 0xDC, 0xBA, 0x98, 0x80, 0x01, 0x02, 0x03, 0x04, 0xFF};
    CHECK_EQ_U(read_be16(buf + 1), 0xFEDC);
    CHECK_EQ_U(read_le16(buf + 1), 0xDCFE);
    CHECK_EQ_U(read_be32(buf + 1), 0xFEDCBA98u);
    CHECK_EQ_U(read_le32(buf + 1), 0x98BADCFEu);
    CHECK_EQ_U(read_be32(buf + 5), 0x80010203u);
    CHECK_EQ_U(read_le32(buf + 7), 0xFF040302u);
    write_be16(buf + 3, 0xA55A);
    CHECK_EQ_U(buf[3], 0xA5);
    CHECK_EQ_U(buf[4], 0x5A);
    write_be32(buf + 1, 0x89ABCDEFu);
    CHECK_EQ_U(read_be32(buf + 1), 0x89ABCDEFu);
    CHECK_EQ_U(buf[1], 0x89);
    write_le32(buf + 6, 0xDEADBEEFu);
    CHECK_EQ_U(buf[6], 0xEF);
    CHECK_EQ_U(buf[9], 0xDE);
    CHECK_EQ_U(read_le32(buf + 6), 0xDEADBEEFu);
    CHECK_EQ_U(buf[0], 0x00);
    CHECK_EQ_U(buf[10], 0xFF);
    return OGE_REPORT();
}
""",
    )


def task_conv() -> None:
    rng = random.Random(5)
    cases = [
        (b"\x80", 1),
        (b"\xb4", 6),
        (b"\xff\x00", 16),
        (bytes(rng.randrange(256) for _ in range(9)), 69),
        (b"\x00", 8),
    ]
    lines = []
    for i, (d, n) in enumerate(cases):
        exp = conv_encode(d, n)
        lines.append(
            f"    {{ static const uint8_t in[] = {c_bytes(d)}; static const uint8_t ex[] = {c_bytes(exp)};\n"
            f"      uint8_t out[32]; memset(out, 0xA5, sizeof out);\n"
            f"      CHECK_EQ_U(conv_encode(in, {n}, out), {2 * n}); CHECK_MEM(out, ex, {len(exp)}); }} /* case {i} */"
        )
    write_task(
        "gen-conv-encoder",
        """
        id: gen-conv-encoder
        category: generate
        title: Rate-1/2, K=3 convolutional encoder (generators 7, 5 octal)
        domain: radio channel coding
        difficulty: medium
        description: |
          Implement the convolutional encoder exactly as specified in task.h: bit order of input and output,
          generator polynomials, zero initial state, no tail bits. Unused bits of the last output byte must be 0.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stddef.h>
        #include <stdint.h>

        /* Rate 1/2, constraint length 3. Input bits are read MSB first from in[] (bit k is
           (in[k / 8] >> (7 - k % 8)) & 1). With u the current input bit and p1, p2 the previous two input bits
           (both 0 at start):
               out0 = u ^ p1 ^ p2    (generator 7 = 111b)
               out1 = u ^ p2         (generator 5 = 101b)
           For each input bit, out0 then out1 are appended to the output, packed MSB first into out[].
           Unused low bits of the last output byte are set to 0. No tail bits are appended.
           Returns the number of output bits (2 * nbits). out must hold (2 * nbits + 7) / 8 bytes. */
        size_t conv_encode(const uint8_t *in, size_t nbits, uint8_t *out);

        #endif
        """,
        """
        #include "task.h"
        #include <string.h>

        size_t conv_encode(const uint8_t *in, size_t nbits, uint8_t *out)
        {
            unsigned p1 = 0u, p2 = 0u;
            size_t o = 0u;
            memset(out, 0, (2u * nbits + 7u) / 8u);
            for (size_t k = 0u; k < nbits; ++k) {
                unsigned u = (in[k / 8u] >> (7u - k % 8u)) & 1u;
                unsigned b0 = u ^ p1 ^ p2;
                unsigned b1 = u ^ p2;
                out[o / 8u] |= (uint8_t)(b0 << (7u - o % 8u));
                o++;
                out[o / 8u] |= (uint8_t)(b1 << (7u - o % 8u));
                o++;
                p2 = p1;
                p1 = u;
            }
            return o;
        }
        """,
        TEST_PRELUDE
        + "#include <string.h>\n\nint main(void)\n{\n"
        + "\n".join(lines)
        + "\n    return OGE_REPORT();\n}\n",
    )


def task_debounce() -> None:
    write_task(
        "gen-debounce",
        """
        id: gen-debounce
        category: generate
        title: Switch / discrete-input debouncer
        domain: discrete I/O
        difficulty: easy
        description: |
          Implement a sample-based debouncer: the debounced output only changes after DEBOUNCE_SAMPLES
          consecutive raw samples that all differ from the current output. Any sample equal to the current output
          resets the count.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stdbool.h>
        #include <stdint.h>

        #define DEBOUNCE_SAMPLES 4u

        typedef struct {
            bool state;      /* current debounced output */
            uint8_t count;   /* consecutive raw samples different from state */
        } debounce_t;

        void debounce_init(debounce_t *d, bool initial);

        /* Feed one raw sample; returns the debounced output after this sample. */
        bool debounce_update(debounce_t *d, bool raw);

        #endif
        """,
        """
        #include "task.h"

        void debounce_init(debounce_t *d, bool initial)
        {
            d->state = initial;
            d->count = 0u;
        }

        bool debounce_update(debounce_t *d, bool raw)
        {
            if (raw == d->state) {
                d->count = 0u;
            } else if (++d->count >= DEBOUNCE_SAMPLES) {
                d->state = raw;
                d->count = 0u;
            }
            return d->state;
        }
        """,
        TEST_PRELUDE
        + """
static void feed(debounce_t *d, const char *raw, const char *expected)
{
    for (unsigned i = 0; raw[i] != '\\0'; ++i) {
        bool out = debounce_update(d, raw[i] == '1');
        CHECK_EQ_U(out, expected[i] == '1');
    }
}

int main(void)
{
    debounce_t d;
"""
        + "".join(
            f'    debounce_init(&d, {"true" if init else "false"});\n    feed(&d, "{raw}", "{debounce(init, raw)}");\n'
            for init, raw in [
                (False, "1110111100"),
                (True, "0001000010000"),
                (False, "10101010101111"),
                (False, "111100001111"),
                (True, "0000"),
            ]
        )
        + """    return OGE_REPORT();
}
""",
    )


def task_ccsds() -> None:
    cases = [
        (0, 0, 0, 0, 3, 0, 0),
        (0, 1, 1, 0x7FF, 3, 0x3FFF, 0xFFFF),
        (0, 0, 1, 0x123, 1, 0x2A5, 42),
        (0, 1, 0, 0x05A, 2, 0x1001, 6),
    ]
    lines = []
    for i, c in enumerate(cases):
        raw = ccsds_bytes(*c)
        v, t, s, apid, fl, cnt, ln = c
        lines.append(
            f"    {{ static const uint8_t raw[] = {c_bytes(raw)}; ccsds_primary_header_t h; uint8_t back[6];\n"
            f"      CHECK_EQ_I(ccsds_parse_primary(raw, 6, &h), 0);\n"
            f"      CHECK_EQ_U(h.version, {v}); CHECK_EQ_U(h.type, {t}); CHECK_EQ_U(h.sec_hdr, {s});\n"
            f"      CHECK_EQ_U(h.apid, {apid}); CHECK_EQ_U(h.seq_flags, {fl}); CHECK_EQ_U(h.seq_count, {cnt});\n"
            f"      CHECK_EQ_U(h.data_length, {ln}); CHECK_EQ_U(ccsds_packet_length(&h), {6 + ln + 1});\n"
            f"      CHECK_EQ_I(ccsds_build_primary(&h, back), 0); CHECK_MEM(back, raw, 6); }} /* case {i} */"
        )
    write_task(
        "gen-ccsds-header",
        """
        id: gen-ccsds-header
        category: generate
        title: CCSDS Space Packet primary header parse / build
        domain: space telemetry and telecommand
        difficulty: medium
        description: |
          Parse and build the 6-byte CCSDS Space Packet primary header (CCSDS 133.0-B) as specified in task.h,
          with the documented error codes.
        """,
        """
        #ifndef TASK_H
        #define TASK_H
        #include <stddef.h>
        #include <stdint.h>

        /* Primary header, big-endian bit fields in this order:
           version (3 bits) | type (1) | secondary header flag (1) | APID (11) |
           sequence flags (2) | sequence count (14) | packet data length (16).
           data_length is the length of the packet data field minus 1. */
        typedef struct {
            uint8_t version;
            uint8_t type;
            uint8_t sec_hdr;
            uint16_t apid;
            uint8_t seq_flags;
            uint16_t seq_count;
            uint16_t data_length;
        } ccsds_primary_header_t;

        /* Returns 0 on success, -1 if buf or hdr is NULL or len < 6, -2 if the version field is not 0. */
        int ccsds_parse_primary(const uint8_t *buf, size_t len, ccsds_primary_header_t *hdr);

        /* Total packet length in bytes: 6 + data_length + 1. */
        size_t ccsds_packet_length(const ccsds_primary_header_t *hdr);

        /* Serialises hdr into out[0..6). Returns 0, or -1 if any field exceeds its bit width
           (version > 7, type > 1, sec_hdr > 1, apid > 2047, seq_flags > 3, seq_count > 16383). */
        int ccsds_build_primary(const ccsds_primary_header_t *hdr, uint8_t out[6]);

        #endif
        """,
        """
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

        int ccsds_build_primary(const ccsds_primary_header_t *hdr, uint8_t out[6])
        {
            if (hdr->version > 7u || hdr->type > 1u || hdr->sec_hdr > 1u || hdr->apid > 2047u ||
                hdr->seq_flags > 3u || hdr->seq_count > 16383u) {
                return -1;
            }
            uint16_t w0 = (uint16_t)((hdr->version << 13) | (hdr->type << 12) | (hdr->sec_hdr << 11) | hdr->apid);
            uint16_t w1 = (uint16_t)((hdr->seq_flags << 14) | hdr->seq_count);
            out[0] = (uint8_t)(w0 >> 8);
            out[1] = (uint8_t)w0;
            out[2] = (uint8_t)(w1 >> 8);
            out[3] = (uint8_t)w1;
            out[4] = (uint8_t)(hdr->data_length >> 8);
            out[5] = (uint8_t)hdr->data_length;
            return 0;
        }
        """,
        TEST_PRELUDE
        + "\nint main(void)\n{\n"
        + "\n".join(lines)
        + """
    {
        ccsds_primary_header_t h;
        uint8_t out[6];
        static const uint8_t v1[6] = {0x20, 0x00, 0xC0, 0x00, 0x00, 0x00};
        CHECK_EQ_I(ccsds_parse_primary(v1, 6, &h), -2);
        CHECK_EQ_I(ccsds_parse_primary(v1, 5, &h), -1);
        CHECK_EQ_I(ccsds_parse_primary(NULL, 6, &h), -1);
        CHECK_EQ_I(ccsds_parse_primary(v1, 6, NULL), -1);
        h.version = 0; h.type = 0; h.sec_hdr = 0; h.apid = 2048; h.seq_flags = 0; h.seq_count = 0; h.data_length = 0;
        CHECK_EQ_I(ccsds_build_primary(&h, out), -1);
        h.apid = 1; h.seq_count = 16384;
        CHECK_EQ_I(ccsds_build_primary(&h, out), -1);
        h.seq_count = 1; h.seq_flags = 4;
        CHECK_EQ_I(ccsds_build_primary(&h, out), -1);
    }
    return OGE_REPORT();
}
""",
    )


def main() -> None:
    assert hamming_expected() == [
        0x00,
        0x69,
        0x2A,
        0x43,
        0x4C,
        0x25,
        0x66,
        0x0F,
        0x70,
        0x19,
        0x5A,
        0x33,
        0x3C,
        0x55,
        0x16,
        0x7F,
    ]
    for fn in (
        task_crc16,
        task_crc32,
        task_ring_buffer,
        task_cobs,
        task_hamming,
        task_q15,
        task_tick,
        task_scrambler,
        task_endian,
        task_conv,
        task_debounce,
        task_ccsds,
    ):
        fn()
    print(f"generate tasks written to {ROOT}")


if __name__ == "__main__":
    main()

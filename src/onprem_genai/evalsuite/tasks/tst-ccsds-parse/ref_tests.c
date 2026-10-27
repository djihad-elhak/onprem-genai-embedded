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

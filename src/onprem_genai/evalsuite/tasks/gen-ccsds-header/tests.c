#include "task.h"
#include "oge_test.h"

int main(void)
{
    { static const uint8_t raw[] = {0x00, 0x00, 0xC0, 0x00, 0x00, 0x00}; ccsds_primary_header_t h; uint8_t back[6];
      CHECK_EQ_I(ccsds_parse_primary(raw, 6, &h), 0);
      CHECK_EQ_U(h.version, 0); CHECK_EQ_U(h.type, 0); CHECK_EQ_U(h.sec_hdr, 0);
      CHECK_EQ_U(h.apid, 0); CHECK_EQ_U(h.seq_flags, 3); CHECK_EQ_U(h.seq_count, 0);
      CHECK_EQ_U(h.data_length, 0); CHECK_EQ_U(ccsds_packet_length(&h), 7);
      CHECK_EQ_I(ccsds_build_primary(&h, back), 0); CHECK_MEM(back, raw, 6); } /* case 0 */
    { static const uint8_t raw[] = {0x1F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}; ccsds_primary_header_t h; uint8_t back[6];
      CHECK_EQ_I(ccsds_parse_primary(raw, 6, &h), 0);
      CHECK_EQ_U(h.version, 0); CHECK_EQ_U(h.type, 1); CHECK_EQ_U(h.sec_hdr, 1);
      CHECK_EQ_U(h.apid, 2047); CHECK_EQ_U(h.seq_flags, 3); CHECK_EQ_U(h.seq_count, 16383);
      CHECK_EQ_U(h.data_length, 65535); CHECK_EQ_U(ccsds_packet_length(&h), 65542);
      CHECK_EQ_I(ccsds_build_primary(&h, back), 0); CHECK_MEM(back, raw, 6); } /* case 1 */
    { static const uint8_t raw[] = {0x09, 0x23, 0x42, 0xA5, 0x00, 0x2A}; ccsds_primary_header_t h; uint8_t back[6];
      CHECK_EQ_I(ccsds_parse_primary(raw, 6, &h), 0);
      CHECK_EQ_U(h.version, 0); CHECK_EQ_U(h.type, 0); CHECK_EQ_U(h.sec_hdr, 1);
      CHECK_EQ_U(h.apid, 291); CHECK_EQ_U(h.seq_flags, 1); CHECK_EQ_U(h.seq_count, 677);
      CHECK_EQ_U(h.data_length, 42); CHECK_EQ_U(ccsds_packet_length(&h), 49);
      CHECK_EQ_I(ccsds_build_primary(&h, back), 0); CHECK_MEM(back, raw, 6); } /* case 2 */
    { static const uint8_t raw[] = {0x10, 0x5A, 0x90, 0x01, 0x00, 0x06}; ccsds_primary_header_t h; uint8_t back[6];
      CHECK_EQ_I(ccsds_parse_primary(raw, 6, &h), 0);
      CHECK_EQ_U(h.version, 0); CHECK_EQ_U(h.type, 1); CHECK_EQ_U(h.sec_hdr, 0);
      CHECK_EQ_U(h.apid, 90); CHECK_EQ_U(h.seq_flags, 2); CHECK_EQ_U(h.seq_count, 4097);
      CHECK_EQ_U(h.data_length, 6); CHECK_EQ_U(ccsds_packet_length(&h), 13);
      CHECK_EQ_I(ccsds_build_primary(&h, back), 0); CHECK_MEM(back, raw, 6); } /* case 3 */
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

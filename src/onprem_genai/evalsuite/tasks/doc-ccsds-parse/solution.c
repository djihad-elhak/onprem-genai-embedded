#include "task.h"

/**
 * @brief ccsds parse primary.
 * @param buf Input `buf`.
 * @param len Input `len`.
 * @param hdr Input `hdr`.
 * @return Result, see task.h for ranges and error codes.
 */
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

/**
 * @brief ccsds packet length.
 * @param hdr Input `hdr`.
 * @return Result, see task.h for ranges and error codes.
 */
size_t ccsds_packet_length(const ccsds_primary_header_t *hdr) { return 6u + (size_t)hdr->data_length + 1u; }

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

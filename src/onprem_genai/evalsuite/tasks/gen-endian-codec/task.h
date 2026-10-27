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

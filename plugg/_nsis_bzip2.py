# Adapted from KokerZhou/NSISExtractor commit 8644b63d79a35bf002ba75f42375a9e4dafbbe74.
# Altered: retained bounded in-memory decoding only; removed codec adapter.
# License and third-party notices: assets/nsis-extractor-license.txt.
"""Pure-Python decoder for the modified bzip2 stream used by NSIS.

NSIS removes the normal ``BZh`` header, block magic, CRC fields, randomization
bit, and end magic.  Its Source/bzip2/compress.c writes 0x31 + origPtr for each
block and 0x17 at end of stream.  The Huffman/MTF/BWT core remains bzip2.
"""

from __future__ import annotations

from typing import BinaryIO



# NSIS Source/exehead/config.h defaults NSIS_COMPRESS_BZIP2_LEVEL to 9;
# Source/bzip2/decompress.c defines nblockMAX as that level * 100000.
NSIS_BZIP2_LEVEL = 9
BZIP2_BLOCK_SIZE_UNIT = 100_000
MAX_BLOCK_SIZE = NSIS_BZIP2_LEVEL * BZIP2_BLOCK_SIZE_UNIT
MAX_BUFFERED_NSIS_BZIP2_ITEM = 64 * 1024 * 1024

class NSISBzip2Error(ValueError):
    pass


class _Bits:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.bit = 0

    def read(self, count: int) -> int:
        if count < 0 or self.bit + count > len(self.data) * 8:
            raise NSISBzip2Error("Truncated NSIS bzip2 bitstream.")
        value = 0
        for _ in range(count):
            byte = self.data[self.bit >> 3]
            value = (value << 1) | ((byte >> (7 - (self.bit & 7))) & 1)
            self.bit += 1
        return value


def _decode_tables(
    bits: _Bits, group_count: int, alphabet_size: int
) -> list[tuple[dict[tuple[int, int], int], int]]:
    tables: list[tuple[dict[tuple[int, int], int], int]] = []
    for _ in range(group_count):
        length = bits.read(5)
        lengths: list[int] = []
        for _symbol in range(alphabet_size):
            while bits.read(1):
                length += -1 if bits.read(1) else 1
                if length < 1 or length > 20:
                    raise NSISBzip2Error("Invalid NSIS bzip2 Huffman code length.")
            lengths.append(length)

        maximum = max(lengths)
        counts = [0] * (maximum + 1)
        for item in lengths:
            counts[item] += 1
        next_code = [0] * (maximum + 1)
        code = 0
        for width in range(1, maximum + 1):
            code = (code + counts[width - 1]) << 1
            next_code[width] = code

        lookup: dict[tuple[int, int], int] = {}
        for symbol, width in enumerate(lengths):
            lookup[(width, next_code[width])] = symbol
            next_code[width] += 1
        tables.append((lookup, maximum))
    return tables


def _huffman_symbol(
    bits: _Bits, table: tuple[dict[tuple[int, int], int], int]
) -> int:
    lookup, maximum = table
    code = 0
    for width in range(1, maximum + 1):
        code = (code << 1) | bits.read(1)
        symbol = lookup.get((width, code))
        if symbol is not None:
            return symbol
    raise NSISBzip2Error("Invalid NSIS bzip2 Huffman code.")


def _inverse_bwt(last_column: bytes, original_pointer: int) -> bytes:
    size = len(last_column)
    if original_pointer >= size:
        raise NSISBzip2Error("NSIS bzip2 original pointer is outside the block.")

    counts = [0] * 257
    for value in last_column:
        counts[value + 1] += 1
    for index in range(1, 257):
        counts[index] += counts[index - 1]

    occurrence = counts[:-1].copy()
    transform = [0] * size
    for index, value in enumerate(last_column):
        transform[occurrence[value]] = index
        occurrence[value] += 1

    output = bytearray(size)
    position = original_pointer
    for index in range(size):
        position = transform[position]
        output[index] = last_column[position]
    return bytes(output)


def _decode_rle1(
    data: bytes,
    max_output_size: int | None = None,
    output_file: BinaryIO | None = None,
) -> bytes | int:
    output = bytearray() if output_file is None else None
    written = 0
    index = 0
    while index < len(data):
        value = data[index]
        index += 1
        run = 1
        while run < 4 and index < len(data) and data[index] == value:
            run += 1
            index += 1
        if max_output_size is not None and written + run > max_output_size:
            raise NSISBzip2Error("NSIS bzip2 output exceeds the configured limit.")
        decoded = bytes((value,)) * run
        if output_file is None:
            assert output is not None
            output.extend(decoded)
        else:
            output_file.write(decoded)
        written += run
        if run == 4:
            if index >= len(data):
                raise NSISBzip2Error("Truncated NSIS bzip2 RLE run.")
            extra = data[index]
            index += 1
            if max_output_size is not None and written + extra > max_output_size:
                raise NSISBzip2Error(
                    "NSIS bzip2 output exceeds the configured limit."
                )
            decoded = bytes((value,)) * extra
            if output_file is None:
                assert output is not None
                output.extend(decoded)
            else:
                output_file.write(decoded)
            written += extra
    return bytes(output) if output is not None else written


def _decode_block(
    bits: _Bits,
    original_pointer: int,
    max_output_size: int | None = None,
    output_file: BinaryIO | None = None,
) -> bytes | int:
    in_use_16 = [bool(bits.read(1)) for _ in range(16)]
    symbols: list[int] = []
    for high, used in enumerate(in_use_16):
        if used:
            for low in range(16):
                if bits.read(1):
                    symbols.append(high * 16 + low)
    if not symbols:
        raise NSISBzip2Error("NSIS bzip2 block has an empty symbol map.")

    alphabet_size = len(symbols) + 2
    group_count = bits.read(3)
    selector_count = bits.read(15)
    if not 2 <= group_count <= 6 or selector_count < 1:
        raise NSISBzip2Error("Invalid NSIS bzip2 Huffman group metadata.")

    selector_mtf: list[int] = []
    for _ in range(selector_count):
        value = 0
        while bits.read(1):
            value += 1
            if value >= group_count:
                raise NSISBzip2Error("Invalid NSIS bzip2 selector.")
        selector_mtf.append(value)

    group_order = list(range(group_count))
    selectors: list[int] = []
    for value in selector_mtf:
        selected = group_order.pop(value)
        group_order.insert(0, selected)
        selectors.append(selected)

    tables = _decode_tables(bits, group_count, alphabet_size)
    mtf = symbols.copy()
    last_column = bytearray()
    selector_index = 0
    group_remaining = 0
    current_table = tables[0]
    end_symbol = len(symbols) + 1

    def next_symbol() -> int:
        nonlocal selector_index, group_remaining, current_table
        if group_remaining == 0:
            if selector_index >= len(selectors):
                raise NSISBzip2Error("NSIS bzip2 selector list ended early.")
            current_table = tables[selectors[selector_index]]
            selector_index += 1
            group_remaining = 50
        group_remaining -= 1
        return _huffman_symbol(bits, current_table)

    symbol = next_symbol()
    while symbol != end_symbol:
        if symbol in (0, 1):
            run = -1
            weight = 1
            remaining_capacity = MAX_BLOCK_SIZE - len(last_column)
            while symbol in (0, 1):
                addition = weight if symbol == 0 else weight * 2
                if addition > remaining_capacity - (run + 1):
                    raise NSISBzip2Error(
                        "NSIS bzip2 block exceeds the format's "
                        f"{MAX_BLOCK_SIZE}-byte limit."
                    )
                run += addition
                weight <<= 1
                symbol = next_symbol()
            run_size = run + 1
            last_column.extend(bytes((mtf[0],)) * run_size)
            if symbol == end_symbol:
                break

        mtf_index = symbol - 1
        if not 0 <= mtf_index < len(mtf):
            raise NSISBzip2Error("Invalid NSIS bzip2 MTF index.")
        value = mtf.pop(mtf_index)
        mtf.insert(0, value)
        if len(last_column) >= MAX_BLOCK_SIZE:
            raise NSISBzip2Error(
                "NSIS bzip2 block exceeds the format's "
                f"{MAX_BLOCK_SIZE}-byte limit."
            )
        last_column.append(value)
        symbol = next_symbol()

    return _decode_rle1(
        _inverse_bwt(bytes(last_column), original_pointer),
        max_output_size,
        output_file,
    )


def _decompress_mode(
    data: bytes,
    legacy_randomized_flag: bool,
    max_output_size: int | None = None,
    output_file: BinaryIO | None = None,
) -> bytes | int:
    bits = _Bits(data)
    output = bytearray()
    written = 0
    while True:
        marker = bits.read(8)
        if marker == 0x17:
            return bytes(output) if output_file is None else written
        if marker != 0x31:
            raise NSISBzip2Error(f"Unexpected NSIS bzip2 marker 0x{marker:02x}.")
        if legacy_randomized_flag and bits.read(1):
            raise NSISBzip2Error(
                "Randomized legacy bzip2 blocks are not supported."
            )
        original_pointer = bits.read(24)
        remaining = (
            None
            if max_output_size is None
            else max_output_size - written
        )
        decoded = _decode_block(
            bits, original_pointer, remaining, output_file
        )
        if output_file is None:
            assert isinstance(decoded, bytes)
            output.extend(decoded)
            written += len(decoded)
        else:
            assert isinstance(decoded, int)
            written += decoded


def decompress_with_framing(
    data: bytes, *, max_output_size: int | None = None
) -> tuple[bytes, str]:
    """Decode NSIS modified-bzip2 and report its block-header generation."""
    errors: list[str] = []
    for legacy_randomized_flag in (False, True):
        try:
            output = _decompress_mode(
                data, legacy_randomized_flag, max_output_size
            )
            assert isinstance(output, bytes)
            return output, ("legacy-random-bit" if legacy_randomized_flag else "current")
        except NSISBzip2Error as exc:
            errors.append(str(exc))
    raise NSISBzip2Error("; legacy retry: ".join(errors))



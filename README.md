# csv

Buffered, deterministic RFC 4180-oriented CSV parsing and serialization for
Nift. The package has no package dependencies, resources, process backend,
type inference, coercion, streaming, or locale-sensitive behavior.

Version 0.1 limits each buffered CSV input and serialized output to 65,536
UTF-8 bytes. This is a deterministic safety boundary for the current
interpreter's CPU and memory costs, not a claim of support for unbounded CSV.
It also limits a CSV to 4,096 physical records, each record to 4,096 fields,
and a supplied or parsed header to 4,096 fields. At most 16,384 physical field
cells may occur across the complete CSV.

## Install

```text
nift add /path/to/csv
```

```nift
@import("csv")

rows := csv.parse("name,notes\r\nAda,\"one,two\"")
text := csv.stringify(rows)
document := csv.parse_document(text, csv.options())
```

Only `csv` is exported. Its public methods are:

- `options()` returns a new default options object.
- `parse(text)` and `parse_bytes(bytes)` return rows using defaults.
- `parse_document(data, options)` returns a diagnostic document.
- `stringify(rows)` and `stringify_document(document, options)` return text.
- `read(path)` and `read_document(path, options)` read a caller-provided path.
- `write(path, rows)` and `write_document(path, document, options)` write a
  caller-provided path and return `true`.

Rows are arrays of string fields. Serialization also accepts object rows when
headers are supplied; object values must be strings and missing keys become
empty fields. Every object key must occur in the headers; extra keys are
rejected rather than discarded. Explicit empty headers permit only an empty
object row, represented as a zero-field record. There is no value inference or
coercion.

## Options

Defaults are:

```json
{"delimiter":",","quote":"\"","newline":"\r\n","accept_lf":true,"bom":false,"header":false,"strict_widths":false}
```

`delimiter` and `quote` must be distinct single characters and cannot be CR or
LF. `newline` controls output and is either `"\r\n"` or `"\n"`;
`line_ending` is an exact alias. CRLF is always accepted on input. A bare LF is
accepted as a record separator only when `accept_lf` is true. CR, LF, and CRLF
inside quoted fields are always valid field content. Bare CR outside a quoted
field is diagnosed. `newline: "\n"` with `accept_lf: false` is invalid because
serializer output must parse under the same options.

When `bom` is true, a leading UTF-8 BOM is stripped during parsing and emitted
during serialization. With `bom` false, an input BOM is stripped but reported
as an error. `header` is `false`, `true` (consume/emit the document header), or
an array of externally supplied header strings that is not itself consumed or
emitted as a record. Duplicate headers produce warnings. With
`strict_widths`, records whose field counts differ from the header or first
record produce errors. The same width rule is enforced before serialization;
malformed rows raise a contract error.

Unknown options and invalid API value types fail. CSV syntax failures are
reported by `parse_document`; the convenience parsers fail when such a result
is not `ok`.

## Buffered limits

`parse_document` measures the original UTF-8 input before BOM processing or
character splitting. Inputs through 65,536 bytes are admitted; larger inputs
return an `input_too_large` error diagnostic with empty rows and headers.
Record, field, and header limits are enforced incrementally and return
`too_many_records`, `too_many_fields`, or `too_many_headers` diagnostics with
empty rows and headers. More than 16,384 parsed field cells returns
`too_many_cells`. Blank zero-field records contribute no cells; every explicit
field, including an empty field, contributes one. A consumed physical header
record is counted once as part of the input, while an externally supplied
header schema is not input data and is not counted. The exact structural
boundaries are admitted.
`read_document` returns the same structured size result before decoding once
the file bytes have been loaded. The convenience `parse`, `parse_bytes`, and
`read` methods fail when that result is not `ok`, consistent with their existing
malformed-input contract. Invalid in-limit UTF-8 fails at the decode boundary.

Before serialization performs quoting or output construction, it validates
all row values and accounts for the UTF-8 bytes in document headers, supplied
schema headers, and fields. Their aggregate source content cannot exceed
65,536 bytes. The exact estimated output, including delimiters, quotes, doubled
quotes, line endings, BOM, and preserved terminal newline, must also fit within
65,536 bytes. Record, field, and header collection sizes are checked before
their contents are traversed. Delimiter and newline bytes are charged as each
record is preflighted. Violations raise the documented serialization contract
error. Serialization permits at most 16,384 emitted cells: every array row
element counts once, each object row counts the effective schema width after
normalization, and headers count only when `header: true` emits them as a
physical record. Schema headers used only for object ordering or validation are
not counted again, and cached normalized rows are not double counted.

## Document model

Parsing returns an object containing `ok`, `rows`, `headers`, `diagnostics`,
`empty_input`, and `terminal_newline`. Diagnostics contain `code`, `message`,
`record`, `field`, and `level`. Empty input is distinct from a blank record.
An unquoted blank physical record is represented as `[]`, while an explicitly
quoted empty field is `[""]`. A trailing delimiter retains its empty field.
Serialization quotes a sole empty field and emits a physical line ending for a
final zero-field row so these representations round-trip.

`parse_bytes` and file reads decode strict UTF-8. Invalid UTF-8 fails at the
decode boundary. `parse_bytes` checks byte length before decoding. File reads
also check loaded byte length before decoding, but Nift's current `open_bytes`
API has no size query or bounded-read primitive, so a caller-selected file is
necessarily loaded into memory before the package can reject its size. File
methods use Nift's current `open_bytes` and managed `file` APIs; paths are
supplied by and remain the responsibility of the caller.

## Test

```text
python3 tests/run.py /path/to/nift /path/to/csv
```

The offline suite covers direct import, fresh `nift add`, exact facade/privacy,
`--no-process`, malformed and adversarial CSV, UTF-8 rejection, headers,
widths, deterministic repetition, round trips, exact 65,536-byte admission and
65,537-byte rejection, exact structural and 16,384-cell boundaries, boundary+1
array/object/parse rejection, 8K headers, 100K-element prompt-rejection probes,
bounded wide/record-heavy inputs, unique temporary paths, and cleanup.

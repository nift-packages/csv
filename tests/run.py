#!/usr/bin/env python3
"""Offline initial certification for the csv Nift package."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


NIFT = Path(sys.argv[1] if len(sys.argv) > 1 else "nift").resolve()
PACKAGE = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent.parent).resolve()
TESTS = PACKAGE / "tests"
EXPECTED_METHODS = [
    "options", "parse", "parse_bytes", "parse_document", "stringify",
    "stringify_document", "read", "read_document", "write", "write_document",
]


def run(args, cwd, timeout=60):
    return subprocess.run(
        [str(NIFT), *args], cwd=cwd, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def require(condition, message, result=None):
    if condition:
        return
    if result is not None:
        message += f"\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}\nreturn code: {result.returncode}"
    raise SystemExit("FAIL " + message)


manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
require(manifest == {
    "name": "csv", "version": "0.1.0", "entry": "src/csv.f",
    "description": "Buffered RFC 4180-oriented CSV parsing and serialization",
}, "unexpected manifest")
require(not manifest.get("dependencies") and not manifest.get("resources"), "package must have zero dependencies/resources")

source = (PACKAGE / "src" / "csv.f").read_text(encoding="utf-8")
exports = re.findall(r"^export\(([^)]+)\)$", source, re.MULTILINE)
public = re.findall(r"^    fn\(([A-Za-z_][A-Za-z0-9_]*)\(", source, re.MULTILINE)
private = re.findall(r"^    private fn\(([A-Za-z_][A-Za-z0-9_]*)\(", source, re.MULTILINE)
require(exports == ["csv"], f"unexpected exports: {exports!r}")
require(public == EXPECTED_METHODS, f"unexpected public methods: {public!r}")
require(private, "implementation helpers must be private")

direct = run(["direct.f"], TESTS)
require(direct.returncode == 0, "direct import failed", direct)
require(direct.stdout.splitlines() == ['[["a","b"],["c","d"]]', '"a,b","x""y"'], "direct import output", direct)
print("PASS direct import and manifest")

work = Path(tempfile.mkdtemp(prefix=".csv-cert-", dir=TESTS))
try:
    (work / ".nift").mkdir()
    added = run(["add", str(PACKAGE)], work)
    require(added.returncode == 0, "fresh nift add failed", added)
    shutil.copyfile(TESTS / "contract.f", work / "contract.f")

    contract = run(["contract.f"], work, 120)
    require(contract.returncode == 0 and contract.stdout.strip() == "PASS csv package contract", "installed contract failed", contract)
    restricted = run(["contract.f", "--no-process"], work, 120)
    require(restricted.returncode == 0 and restricted.stdout == contract.stdout and restricted.stderr == contract.stderr, "--no-process contract failed", restricted)
    repeated = run(["contract.f"], work, 120)
    require((repeated.returncode, repeated.stdout, repeated.stderr) == (contract.returncode, contract.stdout, contract.stderr), "repeat execution differs", repeated)
    require(not (work / "csv-contract-output.csv").exists(), "contract did not clean its output")
    print("PASS installed, --no-process, scale, repeat, and cleanup")

    for helper in private:
        probe = work / "private.f"
        probe.write_text(f'@import("csv")\ncsv.{helper}()\n', encoding="utf-8")
        hidden = run([probe.name], work)
        require(hidden.returncode != 0 and f"private struct method: {helper}" in hidden.stderr, f"private helper leaked: {helper}", hidden)
    (work / "global.f").write_text('@import("csv")\nprint(parse)\n', encoding="utf-8")
    require(run(["global.f"], work).returncode != 0, "unexported global leaked")
    print("PASS exact facade and privacy")

    malformed = [
        'csv.parse(1)', 'csv.parse_bytes("x")', 'csv.parse_document("x", [])',
        'csv.parse_document("x", {"unknown":true})',
        'csv.parse_document("x", {"delimiter":"," ,"quote":","})',
        'csv.parse_document("x", {"newline":"\\r"})',
        'csv.parse_document("x", {"newline":"\\n","accept_lf":false})',
        'csv.stringify([1])', 'csv.stringify([[1]])',
        'csv.stringify_document({"rows":[]}, {"header":[1]})',
        'csv.stringify_document({"headers":["a","b"],"rows":[["1"]]}, {"strict_widths":true})',
        'csv.stringify_document({"rows":[["1"],["2","3"]]}, {"strict_widths":true})',
        'csv.stringify_document({"headers":["a"],"rows":[{"a":"1","extra":"2"}]}, {})',
        'csv.stringify_document({"headers":["a"],"rows":[{"a":1}]}, {})',
        'csv.stringify_document({"headers":[],"rows":[{"extra":"2"}]}, {})',
        'csv.write(1, [])',
    ]
    for index, expression in enumerate(malformed):
        name = f"malformed-{index}.f"
        (work / name).write_text('@import("csv")\n' + expression + '\n', encoding="utf-8")
        rejected = run([name], work)
        require(rejected.returncode != 0, f"malformed call succeeded: {expression}", rejected)

    oversize_serialization = {
        "oversize-field.f": '''@import("csv")
large := "x"
i := 0
while(i < 16) { large += large; i += 1 }
csv.stringify([[large + "x"]])
''',
        "oversize-header.f": '''@import("csv")
large := "x"
i := 0
while(i < 16) { large += large; i += 1 }
csv.stringify_document({"headers":[large + "x"],"rows":[]}, {})
''',
        "oversize-output.f": '''@import("csv")
large := bytes([34]).decode("utf-8")
i := 0
while(i < 15) { large += large; i += 1 }
csv.stringify([[large]])
''',
    }
    for name, script in oversize_serialization.items():
        (work / name).write_text(script, encoding="utf-8")
        rejected = run([name], work, 30)
        require(rejected.returncode != 0, f"serialization limit was not enforced for {name}", rejected)

    structural_probes = {
        "hundred-thousand-rows.f": '''@import("csv")
rows := []
i := 0
while(i < 100000) { rows.push([]); i += 1 }
csv.stringify(rows)
''',
        "hundred-thousand-fields.f": '''@import("csv")
fields := []
i := 0
while(i < 100000) { fields.push(""); i += 1 }
csv.stringify([fields])
''',
        "eight-thousand-headers-stringify.f": '''@import("csv")
headers := []
i := 0
while(i < 8192) { headers.push(""); i += 1 }
csv.stringify_document({"headers":headers,"rows":[]}, {})
''',
        "array-cell-boundary-plus-one.f": '''@import("csv")
fields := []
i := 0
while(i < 4096) { fields.push(""); i += 1 }
csv.stringify([fields, fields, fields, fields, ["x"]])
''',
        "object-cell-boundary-plus-one.f": '''@import("csv")
headers := []
row := {}
i := 0
while(i < 3277) {
    key := i.to_string()
    headers.push(key)
    row[key] = ""
    i += 1
}
csv.stringify_document({"headers":headers,"rows":[row,row,row,row,row]}, {})
''',
    }
    for name, script in structural_probes.items():
        (work / name).write_text(script, encoding="utf-8")
        rejected = run([name], work, 15)
        require(rejected.returncode != 0, f"structural limit was not enforced promptly for {name}", rejected)

    (work / "wide-object-timing.f").write_text('''@import("csv")
headers := []
row := {}
i := 0
while(i < 4096) {
    key := i.to_string()
    headers.push(key)
    row[key] = ""
    i += 1
}
rows := [row, row, row, row]
text := csv.stringify_document({"headers":headers,"rows":rows}, {"strict_widths":true})
print(text.length() == 16386)
''', encoding="utf-8")
    timing_started = time.monotonic()
    wide_objects = run(["wide-object-timing.f"], work, 20)
    timing_elapsed = time.monotonic() - timing_started
    require(wide_objects.returncode == 0 and wide_objects.stdout.strip() == "true", "valid 4096-column object rows failed", wide_objects)
    require(timing_elapsed < 15.0, f"valid 4096-column object rows exceeded 15s timing limit ({timing_elapsed:.2f}s)", wide_objects)
    print(f"PASS 4096-column object timing ({timing_elapsed:.2f}s)")

    (work / "eight-thousand-headers-parse.f").write_text('''@import("csv")
headers := []
i := 0
while(i < 8192) { headers.push(""); i += 1 }
document := csv.parse_document("", {"header":headers})
print(!document.ok && document.diagnostics[0].code == "too_many_headers")
''', encoding="utf-8")
    header_parse = run(["eight-thousand-headers-parse.f"], work, 15)
    require(header_parse.returncode == 0 and header_parse.stdout.strip() == "true", "8K parse header limit was not structured or prompt", header_parse)

    invalid_utf8 = work / "invalid-utf8.csv"
    invalid_utf8.write_bytes(b"a,\xff")
    (work / "invalid-utf8.f").write_text('@import("csv")\ncsv.read("invalid-utf8.csv")\n', encoding="utf-8")
    require(run(["invalid-utf8.f"], work).returncode != 0, "invalid UTF-8 file was accepted")
    invalid_utf8.unlink()
    oversized_invalid = work / "oversized-invalid-utf8.csv"
    oversized_invalid.write_bytes(b"\xff" * 65537)
    (work / "oversized-read-document.f").write_text('@import("csv")\ndocument := csv.read_document("oversized-invalid-utf8.csv", {})\nprint(!document.ok && document.diagnostics[0].code == "input_too_large")\n', encoding="utf-8")
    oversized_document = run(["oversized-read-document.f"], work)
    require(oversized_document.returncode == 0 and oversized_document.stdout.strip() == "true", "read_document decoded before its byte limit check", oversized_document)
    (work / "oversized-parse-bytes.f").write_text('@import("csv")\ncsv.parse_bytes(open_bytes("oversized-invalid-utf8.csv"))\n', encoding="utf-8")
    oversized_bytes = run(["oversized-parse-bytes.f"], work)
    require(oversized_bytes.returncode != 0 and "decode" not in oversized_bytes.stderr, "parse_bytes decoded before its byte limit check", oversized_bytes)
    oversized_invalid.unlink()
    print("PASS malformed/adversarial and strict UTF-8")
finally:
    shutil.rmtree(work, ignore_errors=True)

require(not work.exists(), "owned temporary certification directory remains")
print("PASS csv initial certification")

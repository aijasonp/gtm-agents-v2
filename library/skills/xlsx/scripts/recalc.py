#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
from openpyxl import load_workbook

ERROR_PREFIXES = {
    '#REF!': '#REF!',
    '#DIV/0!': '#DIV/0!',
    '#VALUE!': '#VALUE!',
    '#NAME?': '#NAME?',
    '#N/A': '#N/A',
    '#NUM!': '#NUM!'
}


def fail(message):
    print(json.dumps({
        'status': 'error',
        'message': message
    }))
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        fail('Usage: recalc.py <excel_file> [timeout_seconds]')

    file_path = os.path.abspath(sys.argv[1])
    if not os.path.exists(file_path):
        fail(f'File not found: {file_path}')

    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 120

    soffice = shutil.which('soffice')
    if soffice is None:
        fail('LibreOffice (soffice) is not installed or not in PATH')

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            soffice,
            '--headless',
            '--calc',
            '--convert-to',
            'xlsx',
            '--outdir',
            tmpdir,
            file_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            fail('LibreOffice conversion timed out')

        if result.returncode != 0:
            fail(f'LibreOffice conversion failed: {result.stderr.strip()}')

        converted = os.path.join(tmpdir, os.path.basename(file_path))
        if not os.path.exists(converted):
            fail('LibreOffice did not produce a converted file')

        shutil.move(converted, file_path)

    total_errors = 0
    error_summary = {}

    wb_values = load_workbook(file_path, data_only=True)
    for sheet_name in wb_values.sheetnames:
        ws = wb_values[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str):
                    for err in ERROR_PREFIXES:
                        if value.startswith(err):
                            total_errors += 1
                            error_summary.setdefault(err, []).append(f"{sheet_name}!{cell.coordinate}")
                            break

    wb_formulas = load_workbook(file_path, data_only=False)
    total_formulas = 0
    for sheet_name in wb_formulas.sheetnames:
        ws = wb_formulas[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == 'f' or (isinstance(cell.value, str) and cell.value.startswith('=')):
                    total_formulas += 1

    status = 'success' if total_errors == 0 else 'errors_found'
    output = {
        'status': status,
        'file': file_path,
        'total_formulas': total_formulas,
        'total_errors': total_errors
    }

    if error_summary:
        output['error_summary'] = error_summary

    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()

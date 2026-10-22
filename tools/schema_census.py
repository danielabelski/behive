#!/usr/bin/env python3
"""Offline BeHive SQL writer census. This program never opens a database.

Examples:
  python3 tools/schema_census.py --repo . --output /owned/census/scan.json \
      --metadata /owned/census/live_metadata.json --snapshot /owned/census/sources

AST string extraction retains f-string templates, resolves only module-level
literal string constants, and never evaluates/imports application code. Generic
SQL builders and dynamic expressions deliberately require a recorded manual
review. SQL parsing is lexical, not a general PostgreSQL parser.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

IDENTIFIER = r'(?:"[^"\n]+"|\{[^}\n]+\}|[A-Za-z_][A-Za-z_0-9$]*)'
WRITE_RE = re.compile(
    rf'\b(?P<operation>INSERT\s+(?:OR\s+\w+\s+)?INTO|COPY)\s+'
    rf'(?P<table>{IDENTIFIER}(?:\s*\.\s*{IDENTIFIER})?)', re.I,
)


def split_top_level(text):
    """Split an SQL argument list without splitting literals/function calls."""
    pieces, begin, depth, quote, i = [], 0, 0, None, 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == ',' and depth == 0:
            pieces.append(text[begin:i].strip())
            begin = i + 1
        i += 1
    pieces.append(text[begin:].strip())
    return pieces


def parenthesized(text, start):
    """Return contents and end offset of a parenthesized SQL list."""
    assert text[start] == '('
    depth, quote, i = 0, None, start
    while i < len(text):
        char = text[i]
        if quote:
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    raise ValueError('Unbalanced SQL parentheses')


def _render(node, constants):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, []
    if isinstance(node, ast.JoinedStr):
        parts, dynamic = [], []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                expression = ast.unparse(part.value)
                if isinstance(part.value, ast.Name) and expression in constants:
                    parts.append(constants[expression])
                else:
                    parts.append('{' + expression + '}')
                    dynamic.append(expression)
        return ''.join(parts), dynamic
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, ld = _render(node.left, constants)
        right, rd = _render(node.right, constants)
        return left + right, ld + rd
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id], []
    expression = ast.unparse(node)
    return '{' + expression + '}', [expression]


def parse_statement(sql, match):
    operation = 'COPY' if match['operation'].upper() == 'COPY' else 'INSERT'
    table = match['table'].replace('"', '').strip()
    if '.' in table:
        table = table.rsplit('.', 1)[1].strip()
    tail = sql[match.end():].lstrip()
    columns, positional, values, error = None, False, [], None
    try:
        if tail.startswith('('):
            col_text, end = parenthesized(tail, 0)
            cols = split_top_level(col_text)
            if all(re.fullmatch(IDENTIFIER, c) and '{' not in c for c in cols):
                columns = [c.strip('"').lower() for c in cols]
            tail = tail[end:].lstrip()
        elif operation == 'INSERT':
            positional = not bool(re.match(r'DEFAULT\s+VALUES\b', tail, re.I))
            if not positional:
                columns = []
        if operation == 'COPY' and not re.match(r'FROM\b', tail, re.I):
            return None
        value_match = re.search(r'\bVALUES\s*\(', tail, re.I)
        if value_match:
            value_text, _ = parenthesized(tail, value_match.end() - 1)
            values = split_top_level(value_text)
    except ValueError as exc:
        error = str(exc)
    return {
        'operation': operation, 'table': table, 'columns': columns,
        'positional': positional, 'values': values,
        'id_supplied': ('id' in columns) if columns is not None else None,
        'parse_error': error,
    }


def scan_source(source, filename):
    """Extract each SQL write literal/template once; retain exact provenance."""
    tree = ast.parse(source, filename=filename)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                docstrings.add(node.body[0].value)
    writers = []
    file_hash = hashlib.sha256(source.encode()).hexdigest()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)) or node in docstrings:
            continue
        if isinstance(node, ast.Constant) and not isinstance(node.value, str):
            continue
        if isinstance(node, ast.BinOp) and not isinstance(node.op, ast.Add):
            continue
        ancestor = parents.get(node)
        if isinstance(ancestor, (ast.JoinedStr, ast.BinOp, ast.FormattedValue)):
            continue
        sql, dynamic = _render(node, constants)
        matches = list(WRITE_RE.finditer(sql))
        if not matches:
            continue
        raw = ast.get_source_segment(source, node) or ''
        raw_matches = list(WRITE_RE.finditer(raw))
        scopes, sink = [], None
        ancestor = parents.get(node)
        while ancestor is not None:
            if isinstance(ancestor, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes.append(ancestor.name)
            if sink is None and isinstance(ancestor, ast.Call):
                sink = ast.unparse(ancestor.func)
            ancestor = parents.get(ancestor)
        for index, match in enumerate(matches):
            record = parse_statement(sql, match)
            if record is None:
                continue
            offset = raw_matches[index].start() if index < len(raw_matches) else 0
            record.update({
                'file': filename, 'line': node.lineno + raw[:offset].count('\n'),
                'literal_line': node.lineno, 'scope': '.'.join(reversed(scopes)),
                'sink': sink, 'sql': sql, 'source_expression': raw,
                'dynamic_expressions': list(dict.fromkeys(dynamic)),
                'file_sha256': file_hash,
                'sql_sha256': hashlib.sha256(sql.encode()).hexdigest(),
            })
            writers.append(record)
    writers.sort(key=lambda w: (w['line'], w['table']))
    nonliteral_calls = []
    apis = {'execute', 'executemany', 'executescript', 'copy', 'copy_from', 'copy_expert',
            'copy_records_to_table', 'copy_to_table', 'execute_batch', 'execute_values',
            'insert_batch', 'upsert_batch'}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        api = call.func.attr if isinstance(call.func, ast.Attribute) else (
            call.func.id if isinstance(call.func, ast.Name) else '')
        if api not in apis:
            continue
        sql_index = 1 if api in {'execute_batch', 'execute_values'} else 0
        argument = call.args[sql_index] if len(call.args) > sql_index else None
        if api in {'execute', 'executemany', 'executescript', 'execute_batch', 'execute_values'}:
            if isinstance(argument, (ast.Constant, ast.JoinedStr)):
                continue
        nonliteral_calls.append({'file': filename, 'line': call.lineno, 'api': api,
                                 'call': ast.get_source_segment(source, call),
                                 'sql_expression': ast.unparse(argument) if argument is not None else None})
    nonliteral_calls.sort(key=lambda c: c['line'])
    return {'writers': writers, 'constants': constants, 'nonliteral_sql_calls': nonliteral_calls}


def required_columns(metadata):
    return [column for column in metadata['columns'] if column['is_nullable'] == 'NO'
            and column['column_default'] is None and column['is_identity'] == 'NO']


def attach_schema(writers, metadata):
    """Record omitted required columns; no guesses for dynamic column lists."""
    tables = {}
    for column in metadata['columns']:
        tables.setdefault(column['table_name'], []).append(column)
    required = {}
    for column in required_columns(metadata):
        required.setdefault(column['table_name'], []).append(column['column_name'])
    for writer in writers:
        table = writer['table']
        columns = writer['columns']
        writer['live_table_exists'] = table in tables
        writer['required_no_default'] = required.get(table, [])
        if writer['positional'] and table in tables and writer['values']:
            ordered = sorted(tables[table], key=lambda c: c['ordinal_position'])
            columns = [c['column_name'] for c in ordered[:len(writer['values'])]]
            writer['resolved_positional_columns'] = columns
            writer['id_supplied'] = 'id' in columns
        writer['omitted_required_columns'] = (
            [column for column in required.get(table, []) if column not in columns]
            if columns is not None else None
        )
        writer['explicit_default_columns'] = (
            [column for column, value in zip(columns, writer['values']) if value.upper() == 'DEFAULT']
            if columns is not None else []
        )
    return writers


def scan_repository(repo, metadata=None, snapshot=None, include_scripts=()):
    repo = Path(repo).resolve()
    paths = sorted((repo / 'src/behive').rglob('*.py'))
    paths += [repo / name for name in include_scripts]
    writers, files, errors, nonliteral_calls = [], [], [], []
    for path in paths:
        relative = path.relative_to(repo).as_posix()
        source = path.read_text()
        files.append({'file': relative, 'sha256': hashlib.sha256(source.encode()).hexdigest()})
        if snapshot is not None:
            target = Path(snapshot) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        try:
            extracted = scan_source(source, relative)
            writers.extend(extracted['writers'])
            nonliteral_calls.extend(extracted['nonliteral_sql_calls'])
        except SyntaxError as exc:
            errors.append({'file': relative, 'line': exc.lineno, 'error': str(exc)})
    # Package SQL assets are inventoried separately; init-db.sql contains DDL only.
    sql_assets = []
    for path in sorted((repo / 'src/behive').rglob('*.sql')):
        source = path.read_text()
        relative = path.relative_to(repo).as_posix()
        sql_assets.append({'file': relative, 'sha256': hashlib.sha256(source.encode()).hexdigest(),
                           'write_keyword_matches': len(list(WRITE_RE.finditer(source)))})
        if snapshot is not None:
            target = Path(snapshot) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        for match in WRITE_RE.finditer(source):
            writer = parse_statement(source, match)
            if writer:
                writer.update(file=relative, line=source[:match.start()].count('\n') + 1,
                              sql=source, dynamic_expressions=[])
                writers.append(writer)
    if metadata is not None:
        attach_schema(writers, metadata)
    writers.sort(key=lambda w: (w['table'], w['file'], w['line']))
    return {'repo': str(repo), 'files': files, 'sql_assets': sql_assets,
            'writers': writers, 'nonliteral_sql_calls': nonliteral_calls, 'parse_errors': errors,
            'counts': {'python_files': len(files), 'sql_assets': len(sql_assets),
                       'writers': len(writers), 'parse_errors': len(errors),
                       'nonliteral_sql_calls': len(nonliteral_calls)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--runtime-script', action='append', default=[])
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text()) if args.metadata else None
    result = scan_repository(args.repo, metadata, args.snapshot, args.runtime_script)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), **result['counts']}))
    return 1 if result['parse_errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

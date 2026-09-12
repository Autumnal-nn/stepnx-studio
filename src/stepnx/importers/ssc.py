"""Import StepMania SSC charts into the canonical NX20 authoring model.

The importer accepts ordinary SM5 SSC, the PMOD/Sanity extensions observed in
the PumpSanity/XSanity corpus, and StepF2/StepP1 note syntax. Unsupported or
ambiguous semantics are reported instead of silently guessed.
"""
from __future__ import annotations
import math
import re
import struct
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import gcd
from pathlib import Path
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.errors import ParseError
from stepnx.importers.andamiro import AndamiroChartResult, AndamiroImportResult

@dataclass(frozen=True, slots=True)
class SscImportDiagnostic:
    code: str
    message: str
    occurrences: int = 1

class _Diagnostics:

    def __init__(self):
        self._order = []
        self._items = {}

    def add(self, code, message):
        key = (code, message)
        if key in self._items:
            old = self._items[key]
            self._items[key] = SscImportDiagnostic(code, message, old.occurrences + 1)
        else:
            self._order.append(key)
            self._items[key] = SscImportDiagnostic(code, message)

    def tuple(self):
        return tuple((self._items[k] for k in self._order))

@dataclass(frozen=True, slots=True)
class _Tag:
    name: str
    value: str
    offset: int

@dataclass(frozen=True, slots=True)
class _Cell:
    raw: bytes
    hold_start: bool = False
    hold_end: bool = False
_STEPSTYPES = {'pump-single': (5, 0), 'pump-single-p': (5, 0), 'pump-couple': (5, 0), 'pump-halfdouble': (6, 2), 'pump-double': (10, 0), 'pump-double-p': (10, 0), 'pump-double-dp': (5, 0), 'pump-routine': (10, 0)}
_LAYER_NORMAL = {0: '3', 1: '1', 2: '2', 3: '0', 4: 'd', 5: 's', 19: 'y'}
_LAYER_BONUS = {0: '7', 1: '5', 2: '6', 3: '4', 4: 'j', 5: 'h', 19: 'k'}
_LAYER_FAKE = {1: '9', 2: 'a', 3: '8', 4: 'w', 5: 'q', 18: 't'}
_NOTE_CLASS_FAKE = 32
_NOTE_CLASS_NORMAL = 64
_NOTE_CLASS_BONUS = 96
_LAYER_DECODE = {}
for cls, tab in ((_NOTE_CLASS_NORMAL, _LAYER_NORMAL), (_NOTE_CLASS_BONUS, _LAYER_BONUS), (_NOTE_CLASS_FAKE, _LAYER_FAKE)):
    for layer, char in tab.items():
        _LAYER_DECODE[char] = (cls, layer)
_BANK_CHAR_TO_SLOT = {'0': 0, '1': 1, '2': 2, '3': 3, '4': 4, 'k': 5}
_ITEM_CHARS = {0: 'z', 1: 'x', 2: 'c', 3: 'y', 4: 'k', 5: 'M', 6: 'M', 7: 'l', 8: 'm', 9: 'h', 10: 's', 11: 'b', 12: 'd', 13: 'f', 14: 'g', 15: 'a', 16: 'p', 17: 'e', 18: 'r', 19: 'w', 20: 'q', 21: 'i'}
_ITEM_CHAR_TO_SLOT = {v: k for k, v in _ITEM_CHARS.items()}
_ITEM_CHAR_TO_SLOT['M'] = 5
_SPECIAL_CHAR_TO_SLOT = {'G': 0, 'W': 1, 'z': 2, 'x': 3, 'c': 4}

def _scan_tags(text: str):
    out = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find('#', i)
        if j < 0:
            break
        line_start = text.rfind('\n', 0, j) + 1
        comment = text.find('//', line_start, j)
        if comment >= 0:
            nl = text.find('\n', j)
            i = n if nl < 0 else nl + 1
            continue
        colon = text.find(':', j + 1)
        if colon < 0:
            break
        name = text[j + 1:colon].strip()
        if not name or any((c in name for c in '\r\n;#')):
            i = j + 1
            continue
        semi = text.find(';', colon + 1)
        next_tag_match = re.search('\\n\\s*#', text[colon + 1:])
        next_tag = colon + 1 + next_tag_match.start() if next_tag_match else -1
        if next_tag >= 0 and (semi < 0 or next_tag < semi):
            out.append(_Tag(name.upper(), text[colon + 1:next_tag], j))
            i = next_tag + 1
            continue
        if semi < 0:
            value = text[colon + 1:]
            out.append(_Tag(name.upper(), value, j))
            break
        out.append(_Tag(name.upper(), text[colon + 1:semi], j))
        i = semi + 1
    return out

def _split_sections(tags):
    global_fields = {}
    sections = []
    current = None
    for tag in tags:
        if tag.name == 'NOTEDATA':
            if current is not None:
                sections.append(current)
            current = {}
            continue
        target = global_fields if current is None else current
        target[tag.name] = tag.value
    if current is not None:
        sections.append(current)
    if not sections and 'NOTES' in global_fields:
        sections = [dict(global_fields)]
    return (global_fields, sections)

def _field(section, global_fields, name, default=''):
    value = section.get(name)
    if value is None or not value.strip():
        value = global_fields.get(name, default)
    return value.strip() if isinstance(value, str) else default

def _number(text, default=None):
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return default

def _beat_fraction(text):
    try:
        exact = Fraction(Decimal(text.strip()))
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None
    snapped = exact.limit_denominator(192)
    if abs(float(exact - snapped)) <= 0.00051:
        return snapped
    return exact.limit_denominator(1000000)

def _parse_pairs(raw, diag, tag):
    out = []
    for entry in raw.replace('\r', '').replace('\n', '').split(','):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split('=')]
        if len(parts) < 2:
            diag.add('ssc.timing.invalid', f'{tag} entry {entry!r} has no value and was ignored')
            continue
        beat = _beat_fraction(parts[0])
        value = _number(parts[1])
        if beat is None or value is None or (not math.isfinite(value)):
            diag.add('ssc.timing.invalid', f'{tag} entry {entry!r} is invalid and was ignored')
            continue
        out.append((beat, value, parts[2:]))
    out.sort(key=lambda x: x[0])
    return out

def _strip_row_comment(line):
    pos = line.find('//')
    return line if pos < 0 else line[:pos]

def _split_measures(raw):
    parts = []
    cur = []
    depth = 0
    for ch in raw.replace('\r', ''):
        if ch == '{':
            depth += 1
        elif ch == '}' and depth:
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
        if ch == '\n' and depth:
            depth = 0
    parts.append(''.join(cur))
    return parts

def _tokenize_row(line, diag):
    line = _strip_row_comment(line).strip()
    tokens = []
    i = 0
    while i < len(line):
        c = line[i]
        if c.isspace():
            i += 1
            continue
        if c == '{':
            j = line.find('}', i + 1)
            if j < 0:
                diag.add('ssc.note.brace-unclosed', 'unterminated note brace was dropped')
                break
            tokens.append(line[i:j + 1])
            i = j + 1
        else:
            tokens.append(c)
            i += 1
    return tokens

def _measure_rows(raw, columns, diag):
    result = []
    for mi, measure in enumerate(_split_measures(raw)):
        rows = []
        for physical in measure.splitlines():
            line = _strip_row_comment(physical).strip()
            if not line:
                continue
            tokens = _tokenize_row(line, diag)
            if not tokens:
                continue
            if len(tokens) != columns:
                diag.add('ssc.note.row-width', f'measure {mi + 1} has row width {len(tokens)}, expected {columns}; row was padded or truncated')
                tokens = (tokens + ['0'] * columns)[:columns]
            rows.append(tokens)
        if not rows:
            rows = [['0'] * columns]
        result.append(rows)
    return result

def _raw_for_head(head, cls=_NOTE_CLASS_NORMAL, layer=3, bank=0):
    kinds = {(_NOTE_CLASS_NORMAL, '1'): 67, (_NOTE_CLASS_NORMAL, '2'): 87, (_NOTE_CLASS_NORMAL, '3'): 95, (_NOTE_CLASS_NORMAL, '4'): 71, (_NOTE_CLASS_BONUS, '1'): 99, (_NOTE_CLASS_BONUS, '2'): 119, (_NOTE_CLASS_BONUS, '3'): 127, (_NOTE_CLASS_BONUS, '4'): 103, (_NOTE_CLASS_FAKE, '1'): 35, (_NOTE_CLASS_FAKE, '2'): 55, (_NOTE_CLASS_FAKE, '3'): 63, (_NOTE_CLASS_FAKE, '4'): 39}
    kind = kinds.get((cls, head), 67)
    bank_in_player = kind in {35, 55, 63, 67, 87, 95, 99}
    return bytes((kind, layer, bank if bank_in_player else 0, 0 if bank_in_player else bank))

def _body_for(head_raw):
    k = head_raw[0]
    return bytes((k & 112 | 11, 0, 0, 0))

def _tail_for(head_raw):
    k = head_raw[0]
    return bytes((k & 112 | 15, head_raw[1], head_raw[2], head_raw[3]))

def _apply_attr(raw, attr, fake, diag):
    if raw[0] not in {67, 87, 71, 95, 99, 119, 103, 127, 35, 55, 39, 63}:
        return raw
    layer = {'n': 3, 'v': 1, 's': 2, 'h': 0}.get(attr.lower())
    if layer is None:
        diag.add('ssc.stepf2.attribute', f'unknown StepF2 attribute {attr!r}; treated as normal')
        layer = 3
    kind = raw[0]
    head = {3: '1', 7: '2', 15: '3'}.get(kind & 15, '4' if kind & 15 == 7 and (not kind & 16) else None)
    if kind in {67, 99, 35}:
        head = '1'
    elif kind in {87, 119, 55}:
        head = '2'
    elif kind in {95, 127, 63}:
        head = '3'
    elif kind in {71, 103, 39}:
        head = '4'
    cls = _NOTE_CLASS_FAKE if fake else _NOTE_CLASS_NORMAL
    if fake and layer == 0:
        layer = 3
    return _raw_for_head(head, cls, layer, 0)

def _decode_xsanity(payload, diag):
    if len(payload) < 2:
        diag.add('ssc.xsanity.brace', f'brace {{{payload}}} is too short and was dropped')
        return _Cell(b'\x00\x00\x00\x00')
    head = payload[0]
    bank_char = payload[1] if len(payload) > 1 else '0'
    layer_code = payload[2:] if len(payload) > 2 else '0'
    if head in '+-':
        return _Cell(bytes((66, 0, 0, 199 if head == '+' else 198)))
    if head in _SPECIAL_CHAR_TO_SLOT and layer_code.endswith('7'):
        return _Cell(bytes((66, 0, _SPECIAL_CHAR_TO_SLOT[head], 192)))
    if head in _ITEM_CHAR_TO_SLOT and head not in {'1', '2', '3', '4'}:
        slot = _ITEM_CHAR_TO_SLOT[head]
        if layer_code == '41f':
            kind, layer = (65, 17)
        elif layer_code == '82f':
            kind, layer = (65, 18)
        else:
            decoded = _LAYER_DECODE.get(layer_code[-1:] if layer_code else '')
            if decoded is None:
                diag.add('ssc.xsanity.item-layer', f'item layer {layer_code!r} is unknown; imported as a Bonus item')
                kind, layer = (65, 3)
            else:
                cls, layer = decoded
                kind = 33 if cls == _NOTE_CLASS_FAKE else 65
        return _Cell(bytes((kind, layer, slot, 192)))
    decoded = _LAYER_DECODE.get(layer_code)
    if head in '1234' and decoded is not None:
        cls, layer = decoded
        bank = _BANK_CHAR_TO_SLOT.get(bank_char)
        if bank is None:
            diag.add('ssc.xsanity.noteskin', f'noteskin bank {bank_char!r} has no verified NX20 slot; default bank used')
            bank = 0
        raw = _raw_for_head(head, cls, layer, bank)
        return _Cell(raw, hold_start=head in '24', hold_end=head == '3')
    if head in '1234':
        diag.add('ssc.xsanity.layer', f'brace {{{payload}}} has an unknown layer encoding; note shape was retained')
        raw = _raw_for_head(head, _NOTE_CLASS_NORMAL, 3, 0)
        return _Cell(raw, hold_start=head in '24', hold_end=head == '3')
    diag.add('ssc.note.unknown-brace', f'brace {{{payload}}} has no NX20 mapping and was dropped')
    return _Cell(b'\x00\x00\x00\x00')

def _decode_token(token, diag, force_fake=False):
    if token == '0':
        return _Cell(b'\x00\x00\x00\x00')
    if token.startswith('{') and token.endswith('}'):
        payload = token[1:-1]
        if '|' in payload:
            parts = payload.split('|')
            if len(parts) != 4:
                diag.add('ssc.stepf2.brace', f'StepF2 brace {token!r} is malformed; note shape was retained where possible')
                parts = (parts + ['n', '0', '0'])[:4]
            nt, attr, fake, reserved = parts
            nt = nt.strip()
            attr = attr.strip() or 'n'
            fake = fake.strip() == '1'
            if reserved.strip() not in {'', '0'}:
                diag.add('ssc.stepf2.reserved', f'StepF2 reserved flag {reserved.strip()!r} is ignored')
            owner = None
            base = nt
            if nt in 'XYZxyz':
                owner = nt.upper()
                base = '2' if nt.islower() else '1'
                diag.add('ssc.stepf2.player-ownership', 'StepF2 CO-OP player ownership has no verified NX20 equivalent and is dropped')
            if base in {'S', 'V', 'H'}:
                attr = {'S': 's', 'V': 'v', 'H': 'h'}[base]
                base = '1'
            if base == 'F':
                raw = _raw_for_head('1', _NOTE_CLASS_FAKE, 3, 0)
                return _Cell(raw)
            if base == 'L':
                diag.add('ssc.note.lift', 'StepMania Lift has no NX20 judgment equivalent; imported as a tap')
                base = '1'
            if base == 'K':
                diag.add('ssc.note.autokeysound', 'AutoKeysound has no NX20 note equivalent and is dropped')
                return _Cell(b'\x00\x00\x00\x00')
            if base in '1234':
                raw = _raw_for_head(base)
                raw = _apply_attr(raw, attr, fake or force_fake, diag)
                return _Cell(raw, hold_start=base in '24', hold_end=base == '3')
            diag.add('ssc.stepf2.note', f'unknown StepF2 note type {nt!r} was dropped')
            return _Cell(b'\x00\x00\x00\x00')
        cell = _decode_xsanity(payload, diag)
        if force_fake and cell.raw[0] in {67, 87, 71, 95}:
            head = {67: '1', 87: '2', 95: '3', 71: '4'}[cell.raw[0]]
            raw = _raw_for_head(head, _NOTE_CLASS_FAKE, 3, 0)
            return _Cell(raw, cell.hold_start, cell.hold_end)
        return cell
    if token == '1':
        return _Cell(_raw_for_head('1', _NOTE_CLASS_FAKE if force_fake else _NOTE_CLASS_NORMAL, 3, 0))
    if token == '2':
        return _Cell(_raw_for_head('2', _NOTE_CLASS_FAKE if force_fake else _NOTE_CLASS_NORMAL, 3, 0), hold_start=True)
    if token == '3':
        return _Cell(_raw_for_head('3', _NOTE_CLASS_FAKE if force_fake else _NOTE_CLASS_NORMAL, 3, 0), hold_end=True)
    if token == '4':
        return _Cell(_raw_for_head('4', _NOTE_CLASS_FAKE if force_fake else _NOTE_CLASS_NORMAL, 3, 0), hold_start=True)
    if token == 'M':
        return _Cell(bytes((1, 0, 0, 0)))
    if token == 'F':
        return _Cell(_raw_for_head('1', _NOTE_CLASS_FAKE, 3, 0))
    if token == 'L':
        diag.add('ssc.note.lift', 'StepMania Lift has no NX20 judgment equivalent; imported as a tap')
        return _Cell(_raw_for_head('1'))
    if token == 'K':
        diag.add('ssc.note.autokeysound', 'AutoKeysound has no NX20 note equivalent and is dropped')
        return _Cell(b'\x00\x00\x00\x00')
    if token in 'XYZ':
        diag.add('ssc.stepf2.player-ownership', 'StepF2 CO-OP player ownership has no verified NX20 equivalent and is dropped')
        return _Cell(_raw_for_head('1'))
    if token in 'xyz':
        diag.add('ssc.stepf2.player-ownership', 'StepF2 CO-OP player ownership has no verified NX20 equivalent and is dropped')
        return _Cell(_raw_for_head('2'), hold_start=True)
    if token in {'S', 'V', 'H'}:
        layer = {'S': 2, 'V': 1, 'H': 0}[token]
        return _Cell(_raw_for_head('1', _NOTE_CLASS_NORMAL, layer, 0))
    if token in _ITEM_CHAR_TO_SLOT and token != 'M':
        return _Cell(bytes((65, 3, _ITEM_CHAR_TO_SLOT[token], 192)))
    diag.add('ssc.note.unknown', f'note symbol {token!r} has no verified NX20 mapping and was dropped')
    return _Cell(b'\x00\x00\x00\x00')

def _lcm(a, b):
    return a // gcd(a, b) * b

def _active(events, beat, default):
    value = default
    for b, v, *_ in events:
        if b > beat:
            break
        value = v
    return value

def _events_at(events, beat):
    return [e for e in events if e[0] == beat]

def _in_fake(fake_events, beat):
    for b, length, _ in fake_events:
        if b <= beat < b + Fraction(str(length)):
            return True
    return False

def _make_filename(description, stepstype, meter, index, used):
    stem = description.strip()
    if stem.lower().endswith('.nx'):
        stem = stem[:-3]
    if not stem:
        prefix = 'HD' if 'halfdouble' in stepstype else 'D' if 'double' in stepstype or 'routine' in stepstype else 'S'
        stem = f'{prefix}{meter or index + 1}'
    stem = ''.join(('_' if ord(c) < 32 or c in '<>:"/\\|?*' else c for c in stem)).strip(' .')
    if not stem:
        stem = f'chart_{index + 1}'
    base = stem
    suffix = 1
    candidate = f'{base}.NX'
    while candidate.casefold() in used:
        suffix += 1
        candidate = f'{base}_{suffix}.NX'
    used.add(candidate.casefold())
    return candidate

def _build_chart(section, globals_, source, index, used, profile):
    diag = _Diagnostics()
    stepstype = _field(section, globals_, 'STEPSTYPE').casefold()
    geometry = _STEPSTYPES.get(stepstype)
    notes = _field(section, globals_, 'NOTES')
    if stepstype == 'pump-couple':
        first_width = None
        probe = _Diagnostics()
        for meas in _split_measures(notes):
            for line in meas.splitlines():
                toks = _tokenize_row(line, probe)
                if toks:
                    first_width = len(toks)
                    break
            if first_width:
                break
        if first_width in (5, 10):
            geometry = (first_width, 0)
    if geometry is None:
        first = None
        for meas in _split_measures(notes):
            for line in meas.splitlines():
                toks = _tokenize_row(line, diag)
                if toks:
                    first = len(toks)
                    break
            if first:
                break
        if first in (5, 6, 10):
            geometry = (first, 2 if first == 6 else 0)
            diag.add('ssc.stepstype.inferred', f'unsupported StepsType {stepstype!r}; inferred {first}-lane Pump geometry')
        else:
            raise ValueError(f'unsupported SSC StepsType {stepstype!r}')
    columns, start_column = geometry
    if stepstype in {'pump-couple', 'pump-routine', 'pump-double-dp'} or stepstype.endswith('-p'):
        diag.add('ssc.style.projection', f'{stepstype} is imported by lane geometry; player/style ownership is not represented in NX20')
    measures = _measure_rows(notes, columns, diag)
    meter = int(_number(_field(section, globals_, 'METER'), 0) or 0)
    description = _field(section, globals_, 'DESCRIPTION') or _field(section, globals_, 'CHARTNAME') or f'Chart {index + 1}'
    filename = _make_filename(description, stepstype, meter, index, used)
    bpms = _parse_pairs(_field(section, globals_, 'BPMS'), diag, 'BPMS')
    if not bpms:
        bpms = [(Fraction(0), 120.0, [])]
        diag.add('ssc.timing.bpm-default', 'chart has no usable BPM; 120 BPM was assumed')
    scrolls = _parse_pairs(_field(section, globals_, 'SCROLLS'), diag, 'SCROLLS') or [(Fraction(0), 1.0, [])]
    speeds = _parse_pairs(_field(section, globals_, 'SPEEDS'), diag, 'SPEEDS') or [(Fraction(0), 1.0, ['0', '0'])]
    stops = _parse_pairs(_field(section, globals_, 'STOPS'), diag, 'STOPS')
    delays = _parse_pairs(_field(section, globals_, 'DELAYS'), diag, 'DELAYS')
    warps = _parse_pairs(_field(section, globals_, 'WARPS'), diag, 'WARPS')
    fake_pairs = _parse_pairs(_field(section, globals_, 'FAKES'), diag, 'FAKES')
    fake_events = [(b, v, x) for b, v, x in fake_pairs if v > 0]
    for tag in ('ATTACKS', 'COMBOS', 'TICKCOUNTS'):
        raw = _field(section, globals_, tag)
        if raw and raw.strip().strip(','):
            normalized = ''.join(raw.split()).strip(',')
            defaults = {'COMBOS': {'0.000000=1', '0.000=1', '0=1'}, 'TICKCOUNTS': {'0.000000=4', '0.000=4', '0=4'}, 'ATTACKS': set()}
            if normalized not in defaults.get(tag, set()):
                diag.add('ssc.control.not-projected', f'{tag} has no direct NX20 projection and is ignored')
    for tag in ('DIVISION', 'SPECIALDIVISION'):
        raw = _field(section, globals_, tag)
        if raw and raw.strip().strip(','):
            diag.add('ssc.pmod.not-projected', f'{tag} metadata is accepted but not reconstructed as NX split routing')
    offset = _number(_field(section, globals_, 'OFFSET'), 0.0) or 0.0
    measure_data = []
    timing_events = [e[0] for seq in (bpms, scrolls, speeds, stops, delays, warps) for e in seq]
    for mi, rows in enumerate(measures):
        mstart = Fraction(4 * mi)
        mend = mstart + 4
        n = len(rows)
        base_split = n // gcd(n, 4)
        split = base_split
        interior = [b for b in timing_events if mstart < b < mend]
        for b in interior:
            local = b - mstart
            candidate = _lcm(split, local.denominator)
            if candidate <= 255:
                split = candidate
            else:
                diag.add('ssc.timing.quantized', f'timing event at beat {float(b):g} exceeds NX Beat Split 255 and was quantized within its measure')
        if split > 255:
            split = 240
            diag.add('ssc.notes.quantized', f'measure {mi + 1} requires Beat Split {base_split}; rows were quantized to 240')
        slots = 4 * split
        token_rows = [None] * slots
        for ri, tokens in enumerate(rows):
            pos = Fraction(4 * ri, n)
            exact = pos * split
            idx = int(exact) if exact.denominator == 1 else int(round(float(exact)))
            idx = max(0, min(slots - 1, idx))
            if token_rows[idx] is not None and any((t != '0' for t in tokens)):
                diag.add('ssc.notes.collision', f'measure {mi + 1} has multiple source rows quantized onto NX row {idx}')
                old = token_rows[idx]
                merged = []
                for a, b in zip(old, tokens):
                    merged.append(a if a != '0' else b)
                token_rows[idx] = merged
            else:
                token_rows[idx] = tokens
        boundaries = {0, slots}
        for b in interior:
            idx = round(float((b - mstart) * split))
            boundaries.add(max(0, min(slots, idx)))
        measure_data.append((mstart, split, token_rows, sorted(boundaries)))
    meta = []
    if meter > 0:
        meta.append((1001, meter))
    blocks = []
    base_time = -offset * 1000.0
    holds = [None] * columns
    for mstart, split, token_rows, bounds in measure_data:
        for a, b in zip(bounds, bounds[1:]):
            if b <= a:
                continue
            beat = mstart + Fraction(a, split)
            bpm = float(_active(bpms, beat, 120.0))
            if not math.isfinite(bpm) or bpm <= 0:
                diag.add('ssc.timing.bpm-invalid', f'non-positive BPM at beat {float(beat):g}; 120 BPM was used')
                bpm = 120.0
            scroll = float(_active(scrolls, beat, 1.0))
            speed_event = None
            for e in speeds:
                if e[0] <= beat:
                    speed_event = e
                else:
                    break
            speed = float(speed_event[1]) if speed_event else 1.0
            smooth = 0
            if speed_event and speed_event[2]:
                duration = _number(speed_event[2][0], 0.0) or 0.0
                if duration > 0:
                    smooth = 1
            offset_ms = 0.0
            sign = 1.0
            stop_here = _events_at(stops, beat)
            delay_here = _events_at(delays, beat)
            warp_here = _events_at(warps, beat)
            kinds = sum((bool(x) for x in (stop_here, delay_here, warp_here)))
            if kinds > 1:
                diag.add('ssc.timing.collision', f'multiple stop/delay/warp events at beat {float(beat):g}; one NX offset field cannot preserve all of them')
            if warp_here:
                warp = sum((max(0.0, e[1]) for e in warp_here))
                offset_ms = -warp * 60000.0 / bpm
            elif delay_here:
                offset_ms = sum((e[1] for e in delay_here)) * 1000.0
                sign = -1.0
            elif stop_here:
                offset_ms = sum((e[1] for e in stop_here)) * 1000.0
            start_time = base_time + offset_ms
            raw_rows = []
            for idx in range(a, b):
                row_beat = mstart + Fraction(idx, split)
                tokens = token_rows[idx]
                cells = []
                for lane in range(columns):
                    token = '0' if tokens is None else tokens[lane]
                    cell = _decode_token(token, diag, force_fake=_in_fake(fake_events, row_beat)) if token != '0' else _Cell(b'\x00\x00\x00\x00')
                    if cell.hold_end:
                        state = holds[lane]
                        raw = _tail_for(state) if state is not None else cell.raw
                        holds[lane] = None
                        cells.append(raw)
                        continue
                    if cell.hold_start:
                        holds[lane] = cell.raw
                        cells.append(cell.raw)
                        continue
                    if cell.raw == b'\x00\x00\x00\x00' and holds[lane] is not None:
                        cells.append(_body_for(holds[lane]))
                        continue
                    cells.append(cell.raw)
                raw_rows.append(tuple(cells))
            blocks.append((start_time, bpm, scroll / split, offset_ms, abs(speed) * sign, split, 4, smooth, raw_rows))
            base_time = start_time + (b - a) * 60000.0 / (bpm * split)
    if any(holds):
        diag.add('ssc.hold.unclosed', 'one or more hold heads have no matching tail; hold bodies were retained through chart end')
    if not blocks:
        blocks = [(-offset * 1000.0, 120.0, 1.0, 0.0, 1.0, 1, 4, 0, [tuple((b'\x00\x00\x00\x00' for _ in range(columns)))])]
    output = bytearray(b'NX20')
    output += struct.pack('<III', start_column, columns, 0)
    output += struct.pack('<I', len(meta))
    for mid, val in meta:
        output += struct.pack('<II', mid, val)
    output += struct.pack('<I', len(blocks))
    for start, bpm, scroll, delay, speed, split, measure, smooth, rows in blocks:
        output += b'\x00\x00\x00\x00'
        output += struct.pack('<I', 0)
        output += struct.pack('<I', 1)
        output += struct.pack('<fffff', float(start), float(bpm), float(scroll), float(delay), float(speed))
        output += bytes((split & 255, measure & 255, smooth & 255, 0))
        output += struct.pack('<I', 0)
        output += struct.pack('<I', len(rows))
        for cells in rows:
            if not any((any(c) for c in cells)):
                output += b'\x80\x00\x00\x00'
            else:
                for c in cells:
                    output += c
    document = parse_bytes(bytes(output), source=f"{source or 'SSC'} [{description}]", profile=profile)
    diagnostic_strings = tuple((f'{item.code}: {item.message}' + (f' (x{item.occurrences})' if item.occurrences > 1 else '') for item in diag.tuple()))
    return AndamiroChartResult(key=f'ssc-{index}', label=f"SSC {stepstype or 'Pump'} — {description}", source_format='ssc', document=document, default_filename=filename, diagnostics=diagnostic_strings, semantically_lossless=not diagnostic_strings)

def parse_ssc(data: bytes, *, source: str | None=None, profile: str='nxa-native') -> AndamiroImportResult:
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = data.decode('cp1252')
        except UnicodeDecodeError as exc:
            raise ParseError(exc.start, 'SSC', 'file is not decodable as UTF-8 or CP1252', source) from exc
    tags = _scan_tags(text)
    global_fields, sections = _split_sections(tags)
    if not sections:
        raise ParseError(0, 'SSC', 'file contains no #NOTEDATA chart sections', source)
    used: set[str] = set()
    charts: list[AndamiroChartResult] = []
    for index, section in enumerate(sections):
        if not _field(section, global_fields, 'NOTES'):
            continue
        try:
            charts.append(_build_chart(section, global_fields, source, index, used, profile))
        except ValueError as exc:
            raise ParseError(0, f'SSC chart {index + 1}', str(exc), source) from exc
    if not charts:
        raise ParseError(0, 'SSC', 'file contains no importable #NOTES data', source)
    return AndamiroImportResult(tuple(charts), data, source)

def load(path: str | Path, *, profile: str='nxa-native') -> AndamiroImportResult:
    source = Path(path)
    return parse_ssc(source.read_bytes(), source=str(source), profile=profile)

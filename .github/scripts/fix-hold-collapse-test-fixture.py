from pathlib import Path

path = Path('tests/unit/test_qt_viewport.py')
text = path.read_text(encoding='utf-8')
old = '''        rows = list(block.rows)
        next_id = document.next_stable_id
        for index, note_type in enumerate((0x07, 0x0B, 0x0F)):
'''
new = '''        rows = list(block.rows)
        next_id = document.next_stable_id
        while len(rows) < 3:
            row_id = next_id
            next_id += 1
            cells = []
            for lane in range(int(document.columns.value)):
                cells.append(NoteCell(next_id, bytes(4), None))
                next_id += 1
            rows.append(NoteRow(row_id, tuple(cells), None))
        for index, note_type in enumerate((0x07, 0x0B, 0x0F)):
'''
if old not in text:
    raise SystemExit('generated collapsed-hold fixture anchor not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')

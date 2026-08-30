from pathlib import Path

path = Path('.github/scripts/fix-gameplay-hold-terminals.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    'end = text.index("    def _sync_scrollbars(\\n", start)',
    'end = text.index("    def _sync_scrollbars(self) -> None:\\n", start)',
)
path.write_text(text, encoding='utf-8')

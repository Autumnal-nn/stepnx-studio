from __future__ import annotations

import re
import unittest
from pathlib import Path


NON_ENGLISH_PROSE = re.compile(
    r"\b(?:não|também|decisão|consequências|licença|próximo|implementação|"
    r"armazenamento|visualização|contribuindo|análise|núcleo|código|padrão|"
    r"ainda|apenas|nenhum|nenhuma|arquivo|pasta|salvar|edição)\b",
    re.IGNORECASE,
)


class DocumentationLanguageTests(unittest.TestCase):
    def test_public_markdown_is_english(self) -> None:
        root = Path(__file__).resolve().parents[2]
        files = [root / "README.md", root / "CONTRIBUTING.md"]
        files.extend(sorted((root / "docs").rglob("*.md")))
        offenders = []
        for path in files:
            match = NON_ENGLISH_PROSE.search(path.read_text(encoding="utf-8"))
            if match:
                offenders.append(f"{path.relative_to(root)}: {match.group(0)!r}")
        self.assertEqual(offenders, [], "non-English prose found in public documentation")


if __name__ == "__main__":
    unittest.main()

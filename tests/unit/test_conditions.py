from __future__ import annotations

import unittest

from stepnx.authoring.conditions import (
    ConditionBinary,
    analyze_condition,
    evaluate_condition,
    parse_condition,
)


class MissionConditionTests(unittest.TestCase):
    def test_precedence_parentheses_boolean_and_arithmetic(self) -> None:
        expression = parse_condition("(100<=Life&&Life<=200)||(20<=Great&&Great<=30)")
        self.assertIsInstance(expression, ConditionBinary)
        self.assertEqual(evaluate_condition(expression, {"Life": 150, "Great": 0}), 1)
        self.assertEqual(evaluate_condition(expression, {"Life": 250, "Great": 25}), 1)
        self.assertEqual(evaluate_condition(expression, {"Life": 250, "Great": 40}), 0)
        arithmetic = parse_condition("4<=Mine&&Mine*2<=Heart")
        self.assertEqual(evaluate_condition(arithmetic, {"Mine": 5, "Heart": 10}), 1)

    def test_rank_constants_and_case_variants_are_known(self) -> None:
        analysis = analyze_condition("A<=Rank&&500<=maxcombo&&Miss<=5")
        self.assertTrue(analysis.is_valid)
        self.assertEqual(analysis.unknown_variables, ())
        self.assertEqual(
            evaluate_condition(
                analysis.expression, {"Rank": 4, "MaxCombo": 600, "Miss": 2}
            ),
            1,
        )

    def test_patched_variables_are_profile_gated(self) -> None:
        native = analyze_condition("correct>=5&&accuracy>=9500&&minlife>0")
        self.assertEqual(native.unknown_variables, ("correct", "accuracy", "minlife"))
        patched = analyze_condition(
            "correct>=5&&accuracy>=9500&&minlife>0", "nxa-step5-patched"
        )
        self.assertEqual(patched.unknown_variables, ())

    def test_invalid_text_reports_offset_without_executing_python(self) -> None:
        analysis = analyze_condition("Score>=1;__import__('os')")
        self.assertFalse(analysis.is_valid)
        self.assertIn("character", analysis.error)

    def test_empty_and_trailing_whitespace_are_accepted(self) -> None:
        self.assertIsNone(parse_condition(" \t "))
        expression = parse_condition("Life >= 1   ")
        self.assertEqual(evaluate_condition(expression, {"Life": 1}), 1)


if __name__ == "__main__":
    unittest.main()

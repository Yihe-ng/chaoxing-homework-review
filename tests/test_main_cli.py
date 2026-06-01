import unittest
from pathlib import Path
from unittest.mock import patch

import main


class MainCliTests(unittest.TestCase):
    def test_confirm_prompt_shows_yes_default_value(self):
        prompts = []

        def fake_input(prompt):
            prompts.append(prompt)
            return ""

        with patch("builtins.input", fake_input):
            self.assertTrue(main.confirm("是否立即生成复习资料？", default=True))

        self.assertIn("[Y/n](y)", prompts[0])

    def test_confirm_prompt_shows_no_default_value(self):
        prompts = []

        def fake_input(prompt):
            prompts.append(prompt)
            return ""

        with patch("builtins.input", fake_input):
            self.assertFalse(main.confirm("是否立即生成复习资料？", default=False))

        self.assertIn("[y/N](n)", prompts[0])

    def test_run_review_defaults_to_current_selected_files(self):
        captured = {}

        def fake_load_questions(input_source):
            captured["input_source"] = input_source
            return []

        with (
            patch("main.homework_review.load_questions", fake_load_questions),
            patch("main.homework_review.load_cache", return_value={}),
            patch("main.homework_review.enrich_questions", return_value=[]),
            patch("main.homework_review.update_cache", return_value={}),
            patch("main.homework_review.save_json"),
            patch("pathlib.Path.write_text"),
            patch("main.homework_review.write_docx"),
            patch("main.homework_review.print_run_summary"),
        ):
            main.run_review_for_course(
                Path("output"),
                "人工智能基础",
                input_paths=[Path("output/人工智能基础/raw/混合智能.json")],
                review_all=False,
                verify_answers=False,
            )

        self.assertEqual(
            captured["input_source"],
            [Path("output/人工智能基础/raw/混合智能.json")],
        )

    def test_run_review_all_reads_course_raw_directory(self):
        captured = {}

        def fake_load_questions(input_source):
            captured["input_source"] = input_source
            return []

        with (
            patch("main.homework_review.load_questions", fake_load_questions),
            patch("main.homework_review.load_cache", return_value={}),
            patch("main.homework_review.enrich_questions", return_value=[]),
            patch("main.homework_review.update_cache", return_value={}),
            patch("main.homework_review.save_json"),
            patch("pathlib.Path.write_text"),
            patch("main.homework_review.write_docx"),
            patch("main.homework_review.print_run_summary"),
        ):
            main.run_review_for_course(
                Path("output"),
                "人工智能基础",
                input_paths=[Path("output/人工智能基础/raw/混合智能.json")],
                review_all=True,
                verify_answers=False,
            )

        self.assertEqual(captured["input_source"], Path("output/人工智能基础/raw"))


if __name__ == "__main__":
    unittest.main()

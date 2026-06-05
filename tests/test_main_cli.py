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

    def test_run_review_uses_dynamic_title_and_unique_output_stem(self):
        captured = {}

        def fake_render_markdown(_, title):
            captured["markdown_title"] = title
            return "markdown"

        def fake_write_docx(_, title, output_path):
            captured["docx_title"] = title
            captured["docx_path"] = output_path

        def fake_print_run_summary(_, __, title, **kwargs):
            captured["summary_title"] = title
            captured["review_needed_path"] = kwargs.get("review_needed_path")

        with (
            patch("main.homework_review.load_questions", return_value=[]),
            patch("main.homework_review.load_cache", return_value={}),
            patch("main.homework_review.enrich_questions", return_value=[]),
            patch("main.homework_review.update_cache", return_value={}),
            patch("main.homework_review.save_json"),
            patch("main.review_naming.load_homework_titles", return_value=["混合智能"]),
            patch(
                "main.review_naming.build_review_title",
                return_value="人工智能基础-混合智能-复习资料",
            ),
            patch(
                "main.review_naming.unique_output_stem",
                return_value="人工智能基础-混合智能-复习资料-2",
            ),
            patch("main.homework_review.render_markdown", fake_render_markdown),
            patch("pathlib.Path.write_text"),
            patch("main.homework_review.write_docx", fake_write_docx),
            patch("main.homework_review.print_run_summary", fake_print_run_summary),
        ):
            main.run_review_for_course(
                Path("output"),
                "人工智能基础",
                input_paths=[Path("output/人工智能基础/raw/混合智能.json")],
                review_all=False,
                verify_answers=False,
            )

        self.assertEqual(captured["markdown_title"], "人工智能基础-混合智能-复习资料")
        self.assertEqual(captured["docx_title"], "人工智能基础-混合智能-复习资料")
        self.assertEqual(
            captured["docx_path"],
            Path("output/人工智能基础/review/人工智能基础-混合智能-复习资料-2.docx"),
        )
        self.assertEqual(captured["summary_title"], "人工智能基础-混合智能-复习资料-2")
        self.assertEqual(
            captured["review_needed_path"],
            Path("output/人工智能基础/review/人工智能基础-混合智能-复习资料-2-复核清单.md"),
        )

    def test_run_review_all_keeps_complete_review_title(self):
        captured = {}

        def fake_write_docx(_, title, output_path):
            captured["docx_title"] = title
            captured["docx_path"] = output_path

        with (
            patch("main.homework_review.load_questions", return_value=[]),
            patch("main.homework_review.load_cache", return_value={}),
            patch("main.homework_review.enrich_questions", return_value=[]),
            patch("main.homework_review.update_cache", return_value={}),
            patch("main.homework_review.save_json"),
            patch("main.review_naming.unique_output_stem", return_value="人工智能基础-完整复习资料"),
            patch("pathlib.Path.write_text"),
            patch("main.homework_review.write_docx", fake_write_docx),
            patch("main.homework_review.print_run_summary"),
        ):
            main.run_review_for_course(
                Path("output"),
                "人工智能基础",
                input_paths=[],
                review_all=True,
                verify_answers=False,
            )

        self.assertEqual(captured["docx_title"], "人工智能基础-完整复习资料")
        self.assertEqual(
            captured["docx_path"],
            Path("output/人工智能基础/review/人工智能基础-完整复习资料.docx"),
        )


if __name__ == "__main__":
    unittest.main()

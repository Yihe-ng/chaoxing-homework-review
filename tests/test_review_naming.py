import json
import tempfile
import unittest
from pathlib import Path

from scripts import review_naming


class ReviewNamingTests(unittest.TestCase):
    def test_build_review_title_uses_complete_title_for_review_all(self):
        title = review_naming.build_review_title(
            "计算机组成与结构",
            ["第一章作业", "第二章作业"],
            review_all=True,
        )

        self.assertEqual(title, "计算机组成与结构-完整复习资料")

    def test_build_review_title_summarizes_contiguous_chapters(self):
        title = review_naming.build_review_title(
            "计算机组成与结构",
            ["第一章作业", "第二章作业", "第三章 总线作业"],
        )

        self.assertEqual(title, "计算机组成与结构-第一至三章-复习资料")

    def test_build_review_title_summarizes_non_contiguous_chapters(self):
        title = review_naming.build_review_title(
            "计算机组成与结构",
            ["第一章作业", "第三章 总线作业"],
        )

        self.assertEqual(title, "计算机组成与结构-第一章_第三章-复习资料")

    def test_build_review_title_summarizes_assignment_rounds(self):
        title = review_naming.build_review_title(
            "人工智能基础",
            ["《人工智能基础》第一次作业", "《人工智能基础》第二次作业"],
        )

        self.assertEqual(title, "人工智能基础-第一次_第二次作业-复习资料")

    def test_build_review_title_keeps_mixed_titles_readable(self):
        title = review_naming.build_review_title(
            "人工智能基础",
            [
                "混合智能",
                "《人工智能基础》--行为智能",
                "《人工智能基础》第一次作业",
                "《人工智能基础》第二次作业",
            ],
        )

        self.assertEqual(
            title,
            "人工智能基础-混合智能_行为智能_第一次_第二次作业-复习资料",
        )

    def test_build_review_title_falls_back_when_titles_are_missing(self):
        title = review_naming.build_review_title("人工智能基础", ["", "   "])

        self.assertEqual(title, "人工智能基础-本轮2个作业-复习资料")

    def test_build_review_title_shortens_long_titles_with_stable_hash(self):
        long_titles = [
            "这是一个非常非常长的综合训练作业标题需要被截断一",
            "这是另一个非常非常长的综合训练作业标题需要被截断二",
            "这是第三个非常非常长的综合训练作业标题需要被截断三",
            "这是第四个非常非常长的综合训练作业标题需要被截断四",
            "这是第五个非常非常长的综合训练作业标题需要被截断五",
        ]

        title = review_naming.build_review_title("人工智能基础", long_titles, max_length=60)

        self.assertLessEqual(len(title), 60)
        self.assertRegex(title, r"人工智能基础-.+等5个作业-[0-9a-f]{6}-复习资料")

    def test_unique_output_stem_uses_same_suffix_for_related_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_dir = Path(tmp)
            (review_dir / "人工智能基础-第一次作业-复习资料.docx").write_text("", encoding="utf-8")

            stem = review_naming.unique_output_stem(
                review_dir,
                "人工智能基础-第一次作业-复习资料",
                suffixes=[".docx", ".md", "-复核清单.md"],
            )

            self.assertEqual(stem, "人工智能基础-第一次作业-复习资料-2")

    def test_load_homework_titles_reads_meta_titles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "work.json"
            path.write_text(
                json.dumps({"meta": {"homeworkTitle": "第一章作业"}}, ensure_ascii=False),
                encoding="utf-8",
            )

            titles = review_naming.load_homework_titles([path])

            self.assertEqual(titles, ["第一章作业"])


if __name__ == "__main__":
    unittest.main()

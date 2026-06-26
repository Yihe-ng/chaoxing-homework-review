import argparse
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import homework_review


class HomeworkReviewTests(unittest.TestCase):
    def test_loads_chaoxing_json_files_and_deduplicates_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = {
                "meta": {"courseName": "人工智能理论"},
                "questions": [
                    {
                        "courseName": "人工智能理论",
                        "type": "单选题",
                        "question": "1. 人工智能的英文缩写是？",
                        "options": ["A. AI ", " B. BI"],
                        "answer": "AI",
                        "score": 5,
                    }
                ],
            }
            second = {
                "meta": {"courseName": "人工智能理论"},
                "questions": [
                    {
                        "courseName": "人工智能理论",
                        "type": "单选题",
                        "question": "人工智能的英文缩写是？",
                        "options": ["A. AI", "B. BI"],
                        "answer": "AI",
                        "score": 5,
                    },
                    {
                        "courseName": "人工智能理论",
                        "type": "判断题",
                        "question": "机器学习是人工智能的重要分支。",
                        "options": [],
                        "answer": "正确",
                    },
                ],
            }
            (root / "first.json").write_text(
                json.dumps(first, ensure_ascii=False), encoding="utf-8"
            )
            (root / "second.json").write_text(
                json.dumps(second, ensure_ascii=False), encoding="utf-8"
            )

            questions = homework_review.load_questions(root)

            self.assertEqual(len(questions), 2)
            self.assertEqual(questions[0]["question"], "人工智能的英文缩写是？")
            self.assertEqual(questions[0]["options"], ["A. AI", "B. BI"])

    def test_load_questions_skips_generated_output_json_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = {
                "meta": {"courseName": "课程"},
                "questions": [{"type": "判断题", "question": "原始题", "answer": "正确"}],
            }
            generated = [{"question": "生成题", "answer": "错误"}]
            (root / "export.json").write_text(
                json.dumps(export, ensure_ascii=False), encoding="utf-8"
            )
            output = root / "output"
            output.mkdir()
            (output / "questions.enriched.json").write_text(
                json.dumps(generated, ensure_ascii=False), encoding="utf-8"
            )
            (output / "questions.partial.json").write_text(
                json.dumps(generated, ensure_ascii=False), encoding="utf-8"
            )

            questions = homework_review.load_questions(root)

            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["question"], "原始题")

    def test_load_questions_reads_collected_raw_json_under_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "output" / "人工智能基础" / "raw"
            raw.mkdir(parents=True)
            (raw / "混合智能.json").write_text(
                json.dumps(
                    {
                        "meta": {"courseName": "人工智能基础"},
                        "questions": [
                            {"type": "单选题", "question": "机器人最基本的定义是？", "answer": "C"}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            questions = homework_review.load_questions(raw)

            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["courseName"], "人工智能基础")

    def test_load_questions_accepts_explicit_file_list_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected = root / "selected.json"
            other = root / "other.json"
            selected.write_text(
                json.dumps(
                    {
                        "meta": {"courseName": "课程"},
                        "questions": [{"type": "判断题", "question": "本轮题", "answer": "正确"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            other.write_text(
                json.dumps(
                    {
                        "meta": {"courseName": "课程"},
                        "questions": [{"type": "判断题", "question": "历史题", "answer": "错误"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            questions = homework_review.load_questions([selected])

            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["question"], "本轮题")

    def test_normalize_question_text_strips_inline_options_and_answers(self):
        text = (
            "机器人最基本的定义是（ ） A. 一种机械设备 B. 一种只能执行固定程序的机器 "
            "C. 一种能够自主或半自主执行任务的系统 D. 一种人工智能算法 "
            "C :一种能够自主或半自主执行任务的系统; 10 分"
        )

        self.assertEqual(
            homework_review.normalize_question_text(text),
            "机器人最基本的定义是（ ）",
        )

    def test_normalize_question_text_strips_trailing_option_label(self):
        self.assertEqual(
            homework_review.normalize_question_text("下列关于深度学习的描述，正确的是： A."),
            "下列关于深度学习的描述，正确的是：",
        )

    def test_load_questions_sorts_files_by_chapter_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["第七章作业.json", "第一章作业.json", "第三章 总线作业.json"]:
                data = {
                    "meta": {"courseName": Path(name).stem},
                    "questions": [{"type": "判断题", "question": Path(name).stem, "answer": "正确"}],
                }
                (root / name).write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )

            questions = homework_review.load_questions(root)

            self.assertEqual(
                [question["question"] for question in questions],
                ["第一章作业", "第三章 总线作业", "第七章作业"],
            )

    def test_extracts_chapter_number_from_chinese_or_arabic_numerals(self):
        self.assertEqual(homework_review.extract_chapter_number("第十二章作业.json"), 12)
        self.assertEqual(homework_review.extract_chapter_number("第20章作业.json"), 20)
        self.assertIsNone(homework_review.extract_chapter_number("总线作业.json"))

    def test_generates_markdown_with_ai_explanation_marker(self):
        question = {
            "courseName": "人工智能理论",
            "type": "单选题",
            "question": "人工智能的英文缩写是？",
            "options": ["A. AI", "B. BI"],
            "answer": "AI",
            "explanation": {
                "correct_reason": "AI 是 Artificial Intelligence 的缩写。",
                "wrong_options": [
                    {"option": "B. BI", "reason": "BI 通常指商业智能，不是人工智能。"}
                ],
                "review_tip": "看到 Artificial Intelligence 就对应 AI。",
                "knowledge_points": ["人工智能英文缩写"],
                "principles": ["缩写题需要对应中英文概念。"],
            },
            "explanation_source": "ai",
        }

        with patch.dict(os.environ, {"AI_MODEL": "deepseek-v4-flash"}, clear=False):
            markdown = homework_review.render_markdown([question], "复习资料")

        self.assertIn("# 复习资料", markdown)
        self.assertIn("题型：单选题", markdown)
        self.assertIn("**答案：AI**", markdown)
        self.assertIn("A. AI", markdown)
        self.assertIn("为什么选", markdown)
        self.assertIn("为什么不选", markdown)
        self.assertIn("复习抓手", markdown)
        self.assertIn("知识补充", markdown)
        self.assertIn("同类题判断法", markdown)
        self.assertIn("> **答案：AI**", markdown)
        self.assertIn("> 看到 Artificial Intelligence 就对应 AI。", markdown)
        self.assertIn("---", markdown)
        self.assertIn("- **A. AI** ✅", markdown)
        self.assertIn("解析来源：deepseek-v4-flash", markdown)
        self.assertLess(markdown.index("**答案：AI**"), markdown.index("题型：单选题"))
        self.assertLess(markdown.index("题型：单选题"), markdown.index("- **A. AI** ✅"))
        self.assertLess(markdown.index("- **A. AI** ✅"), markdown.index("**解析**"))

    def test_dry_run_adds_placeholder_without_api_call(self):
        questions = [
            {
                "courseName": "人工智能理论",
                "type": "判断题",
                "question": "机器学习是人工智能的重要分支。",
                "options": [],
                "answer": "正确",
            }
        ]

        enriched = homework_review.enrich_questions(
            questions,
            client=lambda _: (_ for _ in ()).throw(AssertionError("called API")),
            dry_run=True,
            logger=lambda _: None,
        )

        self.assertEqual(enriched[0]["explanation_source"], "missing")
        self.assertIn("待生成", enriched[0]["explanation"]["correct_reason"])

    def test_parses_structured_ai_explanation_json(self):
        raw = json.dumps(
            {
                "correct_reason": "非侵入式脑机接口通过头皮采集信号。",
                "wrong_options": [
                    {"option": "A", "reason": "侵入式需要植入电极。"}
                ],
                "review_tip": "看到头皮采集、无需手术，就优先判断为非侵入式。",
                "knowledge_points": ["脑机接口分类"],
                "principles": ["按是否植入电极区分侵入程度。"],
            },
            ensure_ascii=False,
        )

        explanation = homework_review.parse_explanation_response(raw)

        self.assertEqual(
            explanation["correct_reason"], "非侵入式脑机接口通过头皮采集信号。"
        )
        self.assertEqual(explanation["wrong_options"][0]["option"], "A")
        self.assertEqual(
            explanation["review_tip"], "看到头皮采集、无需手术，就优先判断为非侵入式。"
        )
        self.assertEqual(explanation["knowledge_points"], ["脑机接口分类"])

    def test_prompt_asks_for_student_facing_expanded_review_notes(self):
        messages = homework_review.build_prompt(
            {
                "type": "单选题",
                "question": "脑机接口按侵入程度如何分类？",
                "options": ["A. 侵入式", "B. 非侵入式"],
                "answer": "非侵入式",
            }
        )
        prompt_text = "\n".join(message["content"] for message in messages)

        self.assertIn("面向正在复习的学生", prompt_text)
        self.assertIn("不要只写标签", prompt_text)
        self.assertIn("展开说明", prompt_text)
        self.assertIn("review_tip", prompt_text)

    def test_zero_score_true_false_uses_inferred_opposite_answer_for_prompt(self):
        messages = homework_review.build_prompt(
            {
                "type": "判断题, 2分",
                "question": "现代资本主义固有矛盾正在消失。",
                "options": ["A. 对", "B. 错"],
                "answer": "对",
                "student_answer": "对",
                "correct_answer": "",
                "score": "0 分",
                "answer_visibility": "student_answer_only",
            }
        )
        prompt_text = "\n".join(message["content"] for message in messages)

        self.assertIn("已知正确答案：错", prompt_text)
        self.assertIn("由判断题 0 分反推", prompt_text)
        self.assertNotIn("已知正确答案：对", prompt_text)

    def test_zero_score_multiple_choice_uses_review_prompt_not_standard_answer(self):
        messages = homework_review.build_prompt(
            {
                "type": "多选题, 2分",
                "question": "资本主义为社会主义所代替的历史必然性表现在( )。",
                "options": ["A. 内在矛盾", "B. 生产关系调整", "C. 过渡条件", "D. 自我否定"],
                "answer": "ACD",
                "student_answer": "ACD",
                "correct_answer": "",
                "score": "0 分",
                "answer_visibility": "student_answer_only",
            }
        )
        prompt_text = "\n".join(message["content"] for message in messages)

        self.assertIn("标准答案未确认", prompt_text)
        self.assertIn("学生答案：ACD", prompt_text)
        self.assertIn("得分：0 分", prompt_text)
        self.assertIn("请不要把学生答案当作正确答案", prompt_text)
        self.assertNotIn("已知正确答案：ACD", prompt_text)

    def test_markdown_does_not_display_untrusted_student_answer_as_answer(self):
        question = {
            "courseName": "马克思主义基本原理",
            "type": "多选题, 2分",
            "question": "资本主义为社会主义所代替的历史必然性表现在( )。",
            "options": ["A. 内在矛盾", "B. 生产关系调整", "C. 过渡条件", "D. 自我否定"],
            "answer": "ACD",
            "student_answer": "ACD",
            "correct_answer": "",
            "score": "0 分",
            "answer_visibility": "student_answer_only",
            "explanation": {"correct_reason": "标准答案未确认，本题需要复核。"},
            "explanation_source": "ai_review",
        }

        markdown = homework_review.render_markdown([question], "复习资料")

        self.assertIn("> **答案：未确认**", markdown)
        self.assertIn("> 我的答案：ACD", markdown)
        self.assertIn("> 得分：0 分", markdown)
        self.assertNotIn("> **答案：ACD**", markdown)
        self.assertNotIn("- **A. 内在矛盾** ✅", markdown)

    def test_question_key_changes_when_student_answer_is_not_trusted(self):
        trusted = {
            "type": "多选题, 2分",
            "question": "资本主义为社会主义所代替的历史必然性表现在( )。",
            "options": ["A. 内在矛盾", "B. 生产关系调整", "C. 过渡条件", "D. 自我否定"],
            "answer": "ACD",
            "student_answer": "ACD",
            "score": "2 分",
            "answer_visibility": "student_answer_only",
        }
        untrusted = {
            **trusted,
            "score": "0 分",
        }

        self.assertNotEqual(homework_review.question_key(trusted), homework_review.question_key(untrusted))

    def test_parse_memory_card_json_normalizes_optional_fields(self):
        raw = json.dumps(
            {
                "one_liner": "主机 = CPU + 主存",
                "plain_explain": "主机就是计算机内部负责处理和直接存放当前数据的核心部分。",
                "points": ["主机", "CPU", "主存"],
                "cue": "看到 ALU + 控制单元 + 主存，选主机。",
                "trap": "CPU 不包含主存。",
                "self_test": "CPU、主机、外设分别包含什么？",
                "self_test_answer": "CPU 包含运算器和控制器；主机包含 CPU 和主存；外设是主机外部设备。",
                "formula": "",
                "steps": ["先找 CPU", "再看是否包含主存"],
            },
            ensure_ascii=False,
        )

        card = homework_review.parse_memory_card_response(raw)

        self.assertEqual(card["one_liner"], "主机 = CPU + 主存")
        self.assertIn("主机就是", card["plain_explain"])
        self.assertEqual(card["points"], ["主机", "CPU", "主存"])
        self.assertIn("主机包含 CPU", card["self_test_answer"])
        self.assertEqual(card["steps"], ["先找 CPU", "再看是否包含主存"])

    def test_memory_card_quality_flags_missing_beginner_fields(self):
        quality = homework_review.memory_card_quality(
            {
                "type": "单选题",
                "question": "CPU是指（ ）",
                "options": ["A. 控制器", "B. 运算器和控制器"],
                "answer": "B",
                "memory_card": {
                    "one_liner": "CPU=运算器+控制器",
                    "points": ["CPU"],
                    "cue": "看到CPU组成 -> 运算器+控制器",
                    "trap": "CPU不含主存",
                    "self_test": "CPU由哪两部分组成？",
                },
            }
        )

        self.assertFalse(quality["passed"])
        self.assertIn("missing_plain_explain", quality["issues"])
        self.assertIn("missing_self_test_answer", quality["issues"])

    def test_memory_card_quality_does_not_require_formula_for_bus_category_question(self):
        quality = homework_review.memory_card_quality(
            {
                "type": "单选题",
                "question": "系统总线中的数据线、地址线和控制线是根据（ ）来划分的。",
                "answer": "C",
                "memory_card": {
                    "one_liner": "按传输内容划分",
                    "plain_explain": "三类线分别传数据、地址和控制信号，所以按传输内容划分。",
                    "points": ["数据线", "地址线", "控制线"],
                    "cue": "看到三类线 -> 看传输内容",
                    "trap": "不要选传输方向",
                    "self_test": "三类线按什么划分？",
                    "self_test_answer": "按传输内容划分。",
                },
            }
        )

        self.assertTrue(quality["passed"])
        self.assertNotIn("calculation_missing_formula_or_steps", quality["issues"])

    def test_memory_card_quality_flags_calculation_self_test_with_new_numbers(self):
        quality = homework_review.memory_card_quality(
            {
                "type": "单选题",
                "question": "一个16Kx32位的存储器,其地址线和数据线的总和是",
                "answer": "46",
                "memory_card": {
                    "one_liner": "16K×32位：地址14+数据32=46",
                    "plain_explain": "16K 表示 2^14 个单元，所以地址线14根；字长32位，所以数据线32根。",
                    "points": ["地址线", "数据线"],
                    "steps": ["16K=2^14", "14+32=46"],
                    "cue": "看到16Kx32位 -> 14+32",
                    "trap": "不要把K当16",
                    "self_test": "一个64Kx16位的存储器，地址线和数据线总和是多少？",
                    "self_test_answer": "32",
                },
            }
        )

        self.assertFalse(quality["passed"])
        self.assertIn("self_test_introduces_new_numbers", quality["issues"])

    def test_format_math_text_uses_unicode_for_mobile_and_docx_compatibility(self):
        formatted = homework_review.format_math_text(
            "16Kx32位：log2(16K)=14，因为2^14=16384，T/m -> 启动间隔，a>=b"
        )

        self.assertEqual(
            formatted,
            "16K×32位：log₂(16K)=14，因为2¹⁴=16384，T/m → 启动间隔，a≥b",
        )

    def test_memory_card_prompt_uses_resolved_answer_and_explanation(self):
        messages = homework_review.build_memory_card_prompt(
            {
                "type": "单选题",
                "question": "ALU、控制单元及主存储器合称为（ ）",
                "options": ["A. CPU", "B. 主机"],
                "answer": "B",
                "explanation": {
                    "correct_reason": "主机包括 CPU 和主存。",
                    "knowledge_points": ["主机=CPU+主存"],
                    "principles": ["CPU 不包含主存"],
                },
            }
        )
        prompt_text = "\n".join(message["content"] for message in messages)

        self.assertIn("可信答案：B", prompt_text)
        self.assertIn("主机包括 CPU 和主存", prompt_text)
        self.assertIn("one_liner", prompt_text)
        self.assertIn("plain_explain", prompt_text)
        self.assertIn("self_test_answer", prompt_text)
        self.assertIn("formula", prompt_text)
        self.assertIn("steps", prompt_text)

    def test_enrich_memory_cards_uses_cache_and_generates_missing_cards(self):
        generated_payload = json.dumps(
            {
                "one_liner": "主机=CPU+主存",
                "plain_explain": "主机就是 CPU 加上直接参与运行的主存。",
                "points": ["主机"],
                "cue": "看到主存一起出现，选主机。",
                "trap": "CPU 不含主存。",
                "self_test": "主机包含什么？",
                "self_test_answer": "主机包含 CPU 和主存。",
            },
            ensure_ascii=False,
        )
        questions = [
            {
                "type": "单选题",
                "question": "主机包含什么？",
                "options": ["A. CPU", "B. CPU和主存"],
                "answer": "B",
                "explanation": {"correct_reason": "主机包括 CPU 和主存。"},
            }
        ]
        writes = []

        enriched = homework_review.enrich_memory_cards(
            questions,
            client=lambda messages: generated_payload,
            cache={},
            cache_writer=lambda cache, processed: writes.append((cache, processed)),
            logger=lambda _: None,
        )

        self.assertEqual(enriched[0]["memory_card"]["one_liner"], "主机=CPU+主存")
        self.assertEqual(enriched[0]["memory_card_source"], "ai")
        self.assertTrue(enriched[0]["memory_card_quality"]["passed"])
        self.assertTrue(writes)
        cached = writes[-1][0][homework_review.question_key(enriched[0])]
        self.assertEqual(cached["memory_card"]["cue"], "看到主存一起出现，选主机。")
        self.assertEqual(cached["memory_card"]["self_test_answer"], "主机包含 CPU 和主存。")

    def test_render_memory_markdown_includes_compact_cards(self):
        markdown = homework_review.render_memory_markdown(
            [
                {
                    "courseName": "计算机组成与结构",
                    "homeworkTitle": "第一章作业",
                    "type": "单选题",
                    "question": "ALU、控制单元及主存储器合称为（ ）",
                    "answer": "B",
                    "options": ["A. CPU", "B. 主机", "C. 外设"],
                    "memory_card": {
                        "one_liner": "主机=CPU+主存",
                        "plain_explain": "主机就是 CPU 加上主存，是计算机内部处理当前任务的核心。",
                        "points": ["主机", "CPU", "主存"],
                        "formula": "地址线数=log2(存储单元数)，2^14=16K",
                        "steps": ["1. ALU+控制单元=CPU", "加上主存=主机"],
                        "cue": "看到 ALU + 控制单元 + 主存，选主机。",
                        "trap": "CPU 不包含主存。",
                        "self_test": "CPU、主机、外设分别包含什么？",
                        "self_test_answer": "CPU 包含运算器和控制器；主机包含 CPU 和主存；外设在主机之外。",
                    },
                },
                {
                    "courseName": "计算机组成与结构",
                    "homeworkTitle": "第一章作业",
                    "type": "多选题",
                    "question": "CPU 通常包括哪些部件？",
                    "answer": "AC",
                    "options": ["A. 运算器", "B. 主存", "C. 控制器"],
                    "memory_card": {
                        "one_liner": "CPU=运算器+控制器",
                    },
                }
            ],
            "计组速记",
        )

        self.assertIn("# 计组速记", markdown)
        self.assertIn("## 第一章作业", markdown)
        self.assertIn("> **答案：B. 主机**", markdown)
        self.assertIn("> **答案：A. 运算器；C. 控制器**", markdown)
        self.assertIn("- **速记：** 主机=CPU+主存", markdown)
        self.assertIn("- **白话：** 主机就是 CPU 加上主存", markdown)
        self.assertIn("- **考点：** 主机；CPU；主存", markdown)
        self.assertIn("- **公式：** 地址线数=log₂(存储单元数)，2¹⁴=16K", markdown)
        self.assertIn("- **步骤：** 1. ALU+控制单元=CPU；2. 加上主存=主机", markdown)
        self.assertNotIn("1. 1.", markdown)
        self.assertIn("- **自测：** CPU、主机、外设分别包含什么？", markdown)
        self.assertIn("- **自测答案：** CPU 包含运算器和控制器", markdown)

    def test_memory_prompt_uses_generic_subject_guidance(self):
        prompt = homework_review.build_memory_card_prompt(
            {
                "courseName": "任意课程",
                "homeworkTitle": "章节练习",
                "type": "单选题",
                "question": "某实验样本容量为16Kx32位，求相关线路总数。",
                "answer": "B",
                "options": ["A. 32", "B. 46"],
                "explanation": {
                    "correct_reason": "根据题干数字和单位进行计算。",
                    "knowledge_points": ["单位换算"],
                    "principles": ["先识别数量级，再套用公式。"],
                },
            }
        )
        system_text = prompt[0]["content"]

        self.assertNotIn("计组题", system_text)
        self.assertNotIn("政治理论题", system_text)
        self.assertIn("概念类题", system_text)
        self.assertIn("计算题", system_text)

    def test_memory_quality_flags_general_calculation_without_course_keywords(self):
        source = inspect.getsource(homework_review._is_calculation_like_question)
        for term in ["KB", "MB", "GB", "MHz", "位", "字节", "容量", "带宽", "周期"]:
            self.assertNotIn(term, source)

        quality = homework_review.memory_card_quality(
            {
                "question": "某实验样本容量为16Kx32位，求相关线路总数。",
                "memory_card": {
                    "one_liner": "线路总数要先换算容量",
                    "plain_explain": "16Kx32位表示有16K个单元，每个单元宽度为32位。",
                    "points": ["容量换算", "线路总数"],
                    "cue": "看到16Kx32位，先换算16K。",
                    "trap": "不要把K直接当成16。",
                    "self_test": "16Kx32位应先换算哪一部分？",
                    "self_test_answer": "先把16K换算成2¹⁴。",
                },
            }
        )

        self.assertIn("calculation_missing_formula_or_steps", quality["issues"])

    def test_memory_quality_does_not_hardcode_sample_ocr_terms(self):
        source = inspect.getsource(homework_review.memory_card_quality)
        source += inspect.getsource(homework_review._has_possible_ocr_noise)
        source += inspect.getsource(homework_review._is_calculation_like_question)

        for term in ["RAN", "I6MB", "I28K", "苏片", "写人", "面言", "输人"]:
            self.assertNotIn(term, source)

        quality = homework_review.memory_card_quality(
            {
                "question": "某设备采用1/0方式传送数据。",
                "memory_card": {
                    "one_liner": "传送方式需辨析",
                    "plain_explain": "题干里的1/0可能是I/O识别错误，要先核对原题。",
                    "points": ["输入输出", "传送方式"],
                    "cue": "看到异常字符组合，先复核原题。",
                    "trap": "不要直接按错误字符理解题目。",
                    "self_test": "看到1/0时应该先做什么？",
                    "self_test_answer": "先核对是否为I/O的识别错误。",
                },
            }
        )

        self.assertIn("possible_ocr_noise", quality["issues"])

    def test_write_memory_docx_uses_readable_card_layout(self):
        from docx import Document

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "memory.docx"

            homework_review.write_memory_docx(
                [
                    {
                        "courseName": "计算机组成与结构",
                        "homeworkTitle": "第四章存储器作业",
                        "type": "单选题",
                        "question": "一个16Kx32位的存储器,其地址线和数据线的总和是",
                        "answer": "B",
                        "options": ["A. 36", "B. 46", "C. 48"],
                        "memory_card": {
                            "one_liner": "地址线14+数据线32=46",
                            "plain_explain": "16K 表示 2^14 个存储单元，所以地址线是14根。",
                            "points": ["地址线", "数据线"],
                            "formula": "地址线数=log2(存储单元数)",
                            "steps": ["16K=2^14", "14+32=46"],
                            "cue": "看到16Kx32位 -> 14+32",
                            "trap": "不要把K当16",
                            "self_test": "地址线和数据线总和是多少？",
                            "self_test_answer": "46",
                        },
                    }
                ],
                "计组速记",
                output_path,
            )

            document = Document(str(output_path))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            xml = document._element.xml

        self.assertIn("计组速记", text)
        self.assertIn("答案：B. 46", text)
        self.assertIn("白话：16K 表示 2¹⁴ 个存储单元", text)
        self.assertIn("公式：地址线数=log₂(存储单元数)", text)
        self.assertIn("步骤：1. 16K=2¹⁴；2. 14+32=46", text)
        self.assertNotIn("\t", text)
        self.assertIn('w:fill="E8EEF5"', xml)

        self.assertEqual(len(document.tables), 0)
        memory_paragraph = next(
            paragraph for paragraph in document.paragraphs if paragraph.text.startswith("白话：")
        )
        self.assertLessEqual(memory_paragraph.paragraph_format.left_indent.pt, 16)
        self.assertIsNone(memory_paragraph.paragraph_format.first_line_indent)
        self.assertLessEqual(memory_paragraph.paragraph_format.space_after.pt, 5)
        self.assertGreaterEqual(memory_paragraph.paragraph_format.line_spacing, 1.24)
        self_test_answer = next(
            paragraph
            for paragraph in document.paragraphs
            if paragraph.text.startswith("自测答案：")
        )
        self.assertFalse(any(run.bold for run in self_test_answer.runs[2:]))

    def test_memory_only_build_reads_enriched_json_and_writes_memory_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enriched_path = root / "questions.enriched.json"
            output_dir = root / "review"
            enriched_path.write_text(
                json.dumps(
                    [
                        {
                            "courseName": "计算机组成与结构",
                            "homeworkTitle": "第一章作业",
                            "type": "单选题",
                            "question": "主机包含什么？",
                            "options": ["A. CPU", "B. CPU和主存"],
                            "answer": "B",
                            "explanation": {"correct_reason": "主机包括 CPU 和主存。"},
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                input=str(enriched_path),
                output_dir=str(output_dir),
                cache=None,
                title="计算机组成与结构-速记刷背",
                dry_run=False,
                verify_answers=False,
                limit=None,
                memory=False,
                no_memory=False,
                memory_only=True,
            )

            result = homework_review.build_outputs(
                args,
                memory_client=lambda messages: json.dumps(
                    {
                        "one_liner": "主机=CPU+主存",
                        "points": ["主机"],
                        "cue": "看到主存一起出现，选主机。",
                        "trap": "CPU 不含主存。",
                        "self_test": "主机包含什么？",
                    },
                    ensure_ascii=False,
                ),
            )

            self.assertEqual(result[0]["memory_card"]["one_liner"], "主机=CPU+主存")
            self.assertTrue((output_dir / "计算机组成与结构-速记刷背.md").exists())
            self.assertTrue((output_dir / "计算机组成与结构-速记刷背.docx").exists())
            saved = json.loads(enriched_path.read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["memory_card"]["cue"], "看到主存一起出现，选主机。")

    def test_correct_option_matching_does_not_match_substrings(self):
        self.assertFalse(
            homework_review.is_correct_option("A. 侵入式脑机接口", "非侵入式脑机接口")
        )
        self.assertTrue(
            homework_review.is_correct_option("B. 非侵入式脑机接口", "非侵入式脑机接口")
        )
        self.assertTrue(homework_review.is_correct_option("B. 非侵入式脑机接口", "B"))

    def test_parse_answer_check_json(self):
        raw = json.dumps(
            {
                "provided_answer": "A",
                "model_answer": "B",
                "verdict": "disagree",
                "confidence": 0.82,
                "risk_level": "high",
                "reason": "题干关键词更符合 B。",
                "needs_review": True,
            },
            ensure_ascii=False,
        )

        result = homework_review.parse_answer_check_response(raw)

        self.assertEqual(result["verdict"], "disagree")
        self.assertEqual(result["risk_level"], "high")
        self.assertTrue(result["needs_review"])

    def test_review_needed_markdown_lists_flagged_questions(self):
        questions = [
            {
                "courseName": "混合智能",
                "question": "测试题？",
                "type": "单选题",
                "options": ["A. 选项一", "B. 选项二"],
                "answer": "A",
                "answer_check": {
                    "provided_answer": "A",
                    "model_answer": "B",
                    "verdict": "disagree",
                    "confidence": 0.82,
                    "risk_level": "high",
                    "reason": "题干关键词更符合 B。",
                    "needs_review": True,
                },
            }
        ]

        markdown = homework_review.render_review_needed_markdown(questions, "复核清单")

        self.assertIn("# 复核清单", markdown)
        self.assertIn("测试题？", markdown)
        self.assertIn("题型：单选题", markdown)
        self.assertIn("- A. 选项一", markdown)
        self.assertIn("- B. 选项二", markdown)
        self.assertIn("解析用答案：A", markdown)
        self.assertIn("我的答案：A", markdown)
        self.assertIn("答案来源：学习通导出答案", markdown)
        self.assertIn("模型判断：B", markdown)
        self.assertIn("风险等级：high", markdown)
        self.assertIn("判断状态：disagree", markdown)

    def test_low_risk_answer_check_is_hidden_from_review_material(self):
        lines = homework_review.render_answer_check_markdown(
            {
                "provided_answer": "A",
                "model_answer": "A",
                "verdict": "agree",
                "confidence": 0.95,
                "risk_level": "low",
                "reason": "一致。",
                "needs_review": False,
            }
        )

        self.assertEqual(lines, [])

    def test_high_risk_answer_check_is_short_warning_in_review_material(self):
        lines = homework_review.render_answer_check_markdown(
            {
                "provided_answer": "A",
                "model_answer": "B",
                "verdict": "disagree",
                "confidence": 0.82,
                "risk_level": "high",
                "reason": "题干关键词更符合 B。",
                "needs_review": True,
            }
        )

        rendered = "\n".join(lines)
        self.assertIn("答案可能需要复核", rendered)
        self.assertIn("详见对应的复核清单", rendered)
        self.assertNotIn("校验理由", rendered)
        self.assertNotIn("模型判断：B", rendered)

    def test_high_risk_answer_check_is_added_to_docx(self):
        from docx import Document

        document = Document()
        homework_review.add_answer_check_docx(
            document,
            {
                "provided_answer": "A",
                "model_answer": "B",
                "verdict": "disagree",
                "confidence": 0.82,
                "risk_level": "high",
                "reason": "题干关键词更符合 B。",
                "needs_review": True,
            },
        )

        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("答案可能需要复核", text)
        self.assertIn("详见对应的复核清单", text)

    def test_answer_visibility_risk_is_shown_as_short_warning(self):
        lines = homework_review.render_answer_source_markdown(
            {"answer_visibility": "student_answer_only"}
        )

        rendered = "\n".join(lines)
        self.assertIn("答案来源需要留意", rendered)
        self.assertIn("详见对应的复核清单", rendered)

    def test_print_run_summary_can_show_custom_review_needed_path(self):
        messages = []

        with patch("builtins.print", lambda *args, **kwargs: messages.append(" ".join(str(arg) for arg in args))):
            homework_review.print_run_summary(
                {
                    "total": 1,
                    "cache": 0,
                    "ai": 1,
                    "failed": 0,
                    "review_needed": 1,
                },
                Path("output/人工智能基础/review"),
                "人工智能基础-混合智能-复习资料",
                review_needed_path=Path(
                    "output/人工智能基础/review/人工智能基础-混合智能-复习资料-复核清单.md"
                ),
            )

        rendered = "\n".join(messages)
        self.assertIn("人工智能基础-混合智能-复习资料-复核清单.md", rendered)

    def test_review_needed_markdown_includes_answer_visibility_risk(self):
        markdown = homework_review.render_review_needed_markdown(
            [
                {
                    "courseName": "汇编语言",
                    "question": "只显示我的答案的题？",
                    "type": "判断题",
                    "options": ["A. 对", "B. 错"],
                    "answer": "对",
                    "answer_visibility": "student_answer_only",
                    "student_answer": "对",
                    "correct_answer": "",
                }
            ],
            "复核清单",
        )

        self.assertIn("只显示我的答案的题？", markdown)
        self.assertIn("解析用答案：未确认", markdown)
        self.assertIn("我的答案：对", markdown)
        self.assertIn("答案来源：未确认", markdown)

    def test_docx_body_paragraph_helper_applies_indent_and_spacing(self):
        from docx import Document

        document = Document()
        paragraph = homework_review.add_body_paragraph(document, "正文")

        self.assertEqual(paragraph.paragraph_format.left_indent.pt, 12)
        self.assertEqual(paragraph.paragraph_format.space_after.pt, 8)

    def test_docx_font_defaults_to_microsoft_yahei(self):
        old_font = os.environ.pop("DOCX_FONT", None)
        try:
            self.assertEqual(homework_review.docx_font_name(), "Microsoft YaHei")
        finally:
            if old_font is not None:
                os.environ["DOCX_FONT"] = old_font

    def test_docx_font_uses_valid_environment_value(self):
        old_font = os.environ.get("DOCX_FONT")
        os.environ["DOCX_FONT"] = "Maple Mono"
        try:
            self.assertEqual(homework_review.docx_font_name(), "Maple Mono")
        finally:
            if old_font is None:
                os.environ.pop("DOCX_FONT", None)
            else:
                os.environ["DOCX_FONT"] = old_font

    def test_docx_font_falls_back_when_environment_value_is_invalid(self):
        old_font = os.environ.get("DOCX_FONT")
        os.environ["DOCX_FONT"] = "Bad/Font<Name>"
        try:
            self.assertEqual(homework_review.docx_font_name(), "Microsoft YaHei")
        finally:
            if old_font is None:
                os.environ.pop("DOCX_FONT", None)
            else:
                os.environ["DOCX_FONT"] = old_font

    def test_applies_limit_before_processing_outputs(self):
        questions = [{"question": str(index)} for index in range(5)]

        limited = homework_review.apply_limit(questions, 2)

        self.assertEqual([item["question"] for item in limited], ["0", "1"])

    def test_log_progress_writes_stage_and_index(self):
        messages = []

        homework_review.log_progress("生成解析", 2, 10, "这是一道很长很长的题目", logger=messages.append)

        self.assertIn("[2/10] 生成解析：这是一道很长很长的题目", messages[0])

    def test_enrich_questions_writes_cache_after_each_question(self):
        cache_snapshots = []
        questions = [
            {"type": "判断题", "question": "题目一", "answer": "正确", "options": []},
            {"type": "判断题", "question": "题目二", "answer": "错误", "options": []},
        ]

        homework_review.enrich_questions(
            questions,
            client=lambda _: json.dumps(
                {
                    "correct_reason": "理由",
                    "wrong_options": [],
                    "review_tip": "抓手",
                    "knowledge_points": [],
                    "principles": [],
                },
                ensure_ascii=False,
            ),
            cache={},
            cache_writer=lambda cache, processed: cache_snapshots.append(
                (len(cache), len(processed))
            ),
            logger=lambda _: None,
        )

        self.assertEqual(cache_snapshots, [(1, 1), (2, 2)])

    def test_save_json_atomic_writes_file_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"

            homework_review.save_json_atomic(path, {"ok": True})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ok": True})
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())

    def test_enrich_questions_continues_when_one_question_fails(self):
        calls = {"count": 0}
        questions = [
            {"type": "判断题", "question": "题目一", "answer": "正确", "options": []},
            {"type": "判断题", "question": "题目二", "answer": "错误", "options": []},
        ]

        def flaky_client(_):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("api failed")
            return json.dumps(
                {
                    "correct_reason": "理由",
                    "wrong_options": [],
                    "review_tip": "抓手",
                    "knowledge_points": [],
                    "principles": [],
                },
                ensure_ascii=False,
            )

        enriched = homework_review.enrich_questions(
            questions,
            client=flaky_client,
            cache={},
            logger=lambda _: None,
        )

        self.assertEqual(enriched[0]["explanation_source"], "failed")
        self.assertIn("api failed", enriched[0]["processing_error"])
        self.assertEqual(enriched[1]["explanation_source"], "ai")

    def test_build_run_summary_counts_cache_ai_failures_and_review_needed(self):
        summary = homework_review.build_run_summary(
            [
                {"explanation_source": "cache"},
                {"explanation_source": "ai", "answer_check": {"needs_review": True}},
                {"explanation_source": "failed"},
            ]
        )

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["cache"], 1)
        self.assertEqual(summary["ai"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["review_needed"], 1)

    def test_cached_explanation_is_marked_as_cache_source(self):
        question = {"type": "判断题", "question": "题目", "answer": "正确", "options": []}
        cache = {
            homework_review.question_key(question): {
                "explanation": {"correct_reason": "缓存解析"},
                "explanation_source": "ai",
            }
        }

        enriched = homework_review.enrich_questions(
            [question],
            cache=cache,
            logger=lambda _: None,
        )

        self.assertEqual(enriched[0]["explanation_source"], "cache")
        self.assertEqual(enriched[0]["cached_explanation_source"], "ai")

    def test_cached_ai_explanation_source_shows_model_name(self):
        question = {
            "type": "判断题",
            "question": "机器学习是人工智能分支。",
            "answer": "正确",
            "options": [],
            "explanation": {"correct_reason": "缓存解析"},
            "explanation_source": "cache",
            "cached_explanation_source": "ai",
        }

        with patch.dict(os.environ, {"AI_MODEL": "deepseek-chat"}, clear=False):
            markdown = homework_review.render_markdown([question], "复习资料")

        self.assertIn("解析来源：deepseek-chat（已缓存）", markdown)

    def test_cleans_multiselect_answers_and_duplicate_option_labels(self):
        raw = {
            "type": "多选题",
            "question": "深度神经网络的训练难点包括：",
            "options": ["A. A. 梯度消失", "B. B. 参数多", " C. 训练慢"],
            "answer": "梯度消失###参数多###训练慢",
        }

        cleaned = homework_review.normalize_question(raw)

        self.assertEqual(cleaned["options"], ["A. 梯度消失", "B. 参数多", "C. 训练慢"])
        self.assertEqual(cleaned["answer"], "梯度消失；参数多；训练慢")

    def test_loads_dotenv_without_overriding_existing_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                'AI_API_KEY="from-file"\nAI_MODEL=deepseek-v4-flash\n',
                encoding="utf-8",
            )
            old_key = os.environ.get("AI_API_KEY")
            old_model = os.environ.get("AI_MODEL")
            os.environ["AI_API_KEY"] = "from-env"
            os.environ.pop("AI_MODEL", None)
            try:
                homework_review.load_dotenv(env_file)

                self.assertEqual(os.environ["AI_API_KEY"], "from-env")
                self.assertEqual(os.environ["AI_MODEL"], "deepseek-v4-flash")
            finally:
                if old_key is None:
                    os.environ.pop("AI_API_KEY", None)
                else:
                    os.environ["AI_API_KEY"] = old_key
                if old_model is None:
                    os.environ.pop("AI_MODEL", None)
                else:
                    os.environ["AI_MODEL"] = old_model


if __name__ == "__main__":
    unittest.main()

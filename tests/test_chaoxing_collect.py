import json
import tempfile
import unittest
from pathlib import Path

from scripts import chaoxing_client, chaoxing_collect, chaoxing_parser


class ChaoxingParserTests(unittest.TestCase):
    def test_parse_course_list_extracts_named_courses(self):
        html = """
        <a href="https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle?courseid=1&clazzid=2&cpi=3">
          计算机组成与结构
        </a>
        <a href="javascript:void(0)">添加课程</a>
        """

        courses = chaoxing_parser.parse_course_list(html)

        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0]["name"], "计算机组成与结构")
        self.assertEqual(courses[0]["course_id"], "1")
        self.assertEqual(courses[0]["class_id"], "2")
        self.assertEqual(courses[0]["cpi"], "3")

    def test_parse_course_list_extracts_ajax_course_cards(self):
        html = """
        <li class="course" courseId="10" clazzId="20" personId="30">
          <a href="https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle?courseid=10&clazzid=20&vc=1&cpi=30&ismooc2=1&v=2">
            <span class="course-name" title="汇编语言与接口技术"></span>
          </a>
          <p>开课时间：2026-03-04～2028-03-04</p>
        </li>
        """

        courses = chaoxing_parser.parse_course_list(html)

        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0]["name"], "汇编语言与接口技术")
        self.assertEqual(courses[0]["course_id"], "10")
        self.assertEqual(courses[0]["class_id"], "20")
        self.assertEqual(courses[0]["cpi"], "30")
        self.assertEqual(courses[0]["start_date"], "2026-03-04")
        self.assertEqual(courses[0]["end_date"], "2028-03-04")

    def test_parse_course_page_extracts_work_navigation_and_hidden_params(self):
        html = """
        <input id="courseid" value="261084738">
        <input id="clazzid" value="140767411">
        <input id="cpi" value="421135662">
        <input id="enc" value="student-enc">
        <input id="workEnc" value="work-enc">
        <input id="t" value="1779709288278">
        <ul class="nav-content">
          <li dataname="zy"><a data-url="https://mooc1.chaoxing.com/mooc2/work/list">作业</a></li>
        </ul>
        """

        result = chaoxing_parser.parse_course_page(html, "https://example.test/course")

        self.assertEqual(result["params"]["course_id"], "261084738")
        self.assertEqual(result["params"]["class_id"], "140767411")
        self.assertEqual(result["params"]["student_enc"], "student-enc")
        self.assertEqual(result["params"]["work_enc"], "work-enc")
        self.assertEqual(
            result["work_list_url"],
            "https://mooc1.chaoxing.com/mooc2/work/list?courseId=261084738&classId=140767411&cpi=421135662&ut=s&t=1779709288278&stuenc=student-enc&enc=work-enc",
        )

    def test_parse_work_list_extracts_completed_work_items(self):
        html = """
        <ul>
          <li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?courseId=1&classId=2&workId=10&answerId=20&enc=abc"
              onclick="goTask(this);">
            <p>第七章作业</p><span>已完成</span><span>作答记录</span>
          </li>
          <li data="https://example.test/unready" onclick="goTask(this);">
            <p>第八章作业</p><span>未完成</span>
          </li>
        </ul>
        """

        works = chaoxing_parser.parse_work_list(html)

        self.assertEqual(len(works), 2)
        self.assertEqual(works[0]["title"], "第七章作业")
        self.assertEqual(works[0]["status"], "已完成")
        self.assertEqual(works[0]["work_id"], "10")
        self.assertEqual(works[0]["answer_id"], "20")
        self.assertEqual(works[1]["status"], "未完成")

    def test_parse_work_detail_extracts_visible_correct_answer(self):
        html = """
        <div class="fanyaMarking_left">第七章作业 题量: 1 满分: 10</div>
        <div class="singleQuesId" id="question1">
          <div class="aiAreaContent">
            1. <span class="colorShallow">(单选题)</span>
            机器人系统中用于获取环境信息的是（ ）
            <ul>
              <li>A. 执行模块</li>
              <li>B. 感知模块</li>
            </ul>
            <div class="mark_answer">
              <span class="stuAnswerContent">B</span>
              <span class="rightAnswerContent">B</span>
            </div>
            <div class="mark_score">10分</div>
          </div>
        </div>
        """

        result = chaoxing_parser.parse_work_detail(
            html,
            course_name="人工智能基础",
            homework_title="行为智能",
            detail_url="https://example.test/detail?workId=1&answerId=2",
        )

        question = result["questions"][0]
        self.assertEqual(result["meta"]["courseName"], "人工智能基础")
        self.assertEqual(question["type"], "单选题")
        self.assertEqual(question["question"], "机器人系统中用于获取环境信息的是（ ）")
        self.assertEqual(question["options"], ["A. 执行模块", "B. 感知模块"])
        self.assertEqual(question["option_items"][1], {"label": "B", "text": "感知模块"})
        self.assertEqual(question["answer"], "B")
        self.assertEqual(question["answer_visibility"], "correct_answer_visible")

    def test_parse_work_detail_strips_inline_options_and_answers_from_question(self):
        html = """
        <div class="singleQuesId" id="question1">
          1. <span class="colorShallow">(单选题)</span>
          机器人最基本的定义是（ ） A. 一种机械设备 B. 一种只能执行固定程序的机器 C. 一种能够自主或半自主执行任务的系统 D. 一种人工智能算法 C :一种能够自主或半自主执行任务的系统; C :一种能够自主或半自主执行任务的系统; 10 分
          <ul>
            <li>A. 一种机械设备</li>
            <li>B. 一种只能执行固定程序的机器</li>
            <li>C. 一种能够自主或半自主执行任务的系统</li>
            <li>D. 一种人工智能算法</li>
          </ul>
          <div class="mark_answer"><span class="rightAnswerContent">C</span></div>
        </div>
        """

        result = chaoxing_parser.parse_work_detail(
            html,
            course_name="人工智能基础",
            homework_title="行为智能",
            detail_url="https://example.test/detail?workId=1&answerId=2",
        )

        self.assertEqual(result["questions"][0]["question"], "机器人最基本的定义是（ ）")

    def test_parse_work_detail_marks_student_answer_only_when_correct_answer_hidden(self):
        html = """
        <div class="singleQuesId" id="question2">
          1. <span class="colorShallow">(判断题)</span> P0口是双向口。
          <ul><li>A. 对</li><li>B. 错</li></ul>
          <div class="mark_answer"><span class="stuAnswerContent">对</span></div>
          <div class="mark_score">5分</div>
        </div>
        """

        result = chaoxing_parser.parse_work_detail(
            html,
            course_name="汇编语言与接口技术",
            homework_title="第七章作业",
            detail_url="https://example.test/detail?workId=3&answerId=4",
        )

        question = result["questions"][0]
        self.assertEqual(question["answer"], "对")
        self.assertEqual(question["correct_answer"], "")
        self.assertEqual(question["answer_visibility"], "student_answer_only")

    def test_write_homework_json_uses_safe_filename_and_review_contract(self):
        homework = {
            "source": "chaoxing",
            "meta": {"courseName": "计组:理论", "homeworkTitle": "第一章/作业"},
            "questions": [{"type": "判断题", "question": "测试", "answer": "对"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = chaoxing_collect.write_homework_json(Path(tmp), homework)

            self.assertEqual(path.name, "第一章_作业.json")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["meta"]["courseName"], "计组:理论")
            self.assertEqual(saved["questions"][0]["answer"], "对")


class ChaoxingReviewRiskTests(unittest.TestCase):
    def test_homework_needing_answer_source_review_is_detected(self):
        question = {
            "question": "只显示我的答案的题？",
            "answer": "A",
            "answer_visibility": "student_answer_only",
        }

        self.assertTrue(chaoxing_collect.needs_answer_source_review(question))


class ChaoxingClientTests(unittest.TestCase):
    def test_detects_login_or_permission_pages(self):
        self.assertFalse(chaoxing_client.is_logged_in_course_page("<title>登录</title>"))
        self.assertFalse(
            chaoxing_client.is_logged_in_course_page("您长时间没有操作，或没有此页面访问权限")
        )
        self.assertFalse(
            chaoxing_client.is_permission_or_login_page(
                "<title>人工智能基础</title><script src='/head/passport/all-head-new.shtml'></script>"
            )
        )
        self.assertTrue(
            chaoxing_client.is_logged_in_course_page(
                '<a href="https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle?courseid=1">课程</a>'
            )
        )
        self.assertTrue(
            chaoxing_client.is_logged_in_course_page(
                '退出登录 <a href="https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle?courseid=1">课程</a>'
            )
        )

    def test_build_course_middle_url(self):
        url = chaoxing_client.build_course_middle_url(
            {"course_id": "1", "class_id": "2", "cpi": "3"}
        )

        self.assertIn("courseid=1", url)
        self.assertIn("clazzid=2", url)
        self.assertIn("cpi=3", url)

    def test_course_list_data_payload_uses_defaults_for_async_course_api(self):
        payload = chaoxing_client.course_list_data_payload("<html></html>")

        self.assertEqual(
            payload,
            {
                "courseType": "1",
                "courseFolderId": "0",
                "baseEducation": "0",
                "superstarClass": "0",
                "courseFolderSize": "0",
            },
        )

    def test_course_list_data_payload_prefers_current_student_course_tab(self):
        html = """
        <input id="courseType" value="0">
        <div class="course-tab">
          <div class="tab-item current" courseType="1">我学的课</div>
        </div>
        """

        payload = chaoxing_client.course_list_data_payload(html)

        self.assertEqual(payload["courseType"], "1")


if __name__ == "__main__":
    unittest.main()

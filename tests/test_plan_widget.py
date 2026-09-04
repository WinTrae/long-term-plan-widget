import runpy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "plan_widget.pyw"), run_name="plan_widget_tests")


class PlanDataTests(unittest.TestCase):
    def test_valid_plan_data_is_accepted(self):
        data = {
            "updatedAt": "2026-09-04",
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Write documentation",
                    "status": "todo",
                }
            ],
        }

        self.assertEqual(MODULE["validate_plan_data"](data), data)

    def test_duplicate_ids_are_rejected(self):
        data = {
            "tasks": [
                {"id": "same", "title": "One", "status": "todo"},
                {"id": "same", "title": "Two", "status": "done"},
            ]
        }

        with self.assertRaisesRegex(ValueError, "id 重复"):
            MODULE["validate_plan_data"](data)

    def test_first_run_creates_empty_data_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            namespace = MODULE["load_plan"].__globals__
            original_paths = (
                namespace["DATA_PATH"],
                namespace["DATA_BACKUP_PATH"],
                namespace["ERROR_LOG_PATH"],
            )
            namespace["DATA_PATH"] = Path(temp_dir) / "plan_data.json"
            namespace["DATA_BACKUP_PATH"] = Path(temp_dir) / "plan_data.json.bak"
            namespace["ERROR_LOG_PATH"] = Path(temp_dir) / "plan_widget_error.log"
            try:
                result = MODULE["load_plan"]()
                self.assertEqual(result["tasks"], [])
                self.assertTrue(namespace["DATA_PATH"].exists())
            finally:
                (
                    namespace["DATA_PATH"],
                    namespace["DATA_BACKUP_PATH"],
                    namespace["ERROR_LOG_PATH"],
                ) = original_paths


class TextParsingTests(unittest.TestCase):
    def test_explicit_chinese_date_is_parsed(self):
        self.assertEqual(
            MODULE["due_date_from_text"]("请在 2030 年 5 月 2 日前完成"),
            "2030-05-02",
        )

    def test_spoken_fillers_are_cleaned(self):
        self.assertEqual(
            MODULE["clean_spoken_text"]("嗯，那个，整理项目文档。。"),
            "整理项目文档",
        )


if __name__ == "__main__":
    unittest.main()


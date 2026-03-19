import datetime
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import feishu.get_kb_files as gk
from tests._test_utils import temporary_directory


class TestGetKbFilesLogic(unittest.TestCase):
    def setUp(self):
        self._orig_use_sync_filter = gk.USE_SYNC_FILTER
        self._orig_sync_filters = gk.SYNC_FILTERS
        self._orig_space_name = gk.SPACE_NAME
        self._orig_space_list_output_file = gk.SPACE_LIST_OUTPUT_FILE

    def tearDown(self):
        gk.USE_SYNC_FILTER = self._orig_use_sync_filter
        gk.SYNC_FILTERS = self._orig_sync_filters
        gk.SPACE_NAME = self._orig_space_name
        gk.SPACE_LIST_OUTPUT_FILE = self._orig_space_list_output_file

    def test_is_blacklisted_exact_and_prefix(self):
        blacklist = ["A/B", "X"]
        self.assertTrue(gk._is_blacklisted("A/B", blacklist))
        self.assertTrue(gk._is_blacklisted("A/B/C", blacklist))
        self.assertFalse(gk._is_blacklisted("A/C", blacklist))

    def test_should_traverse_when_filter_disabled(self):
        gk.USE_SYNC_FILTER = False
        self.assertTrue(gk._should_traverse("any/path", "space"))

    def test_should_traverse_with_filter_parent_and_child(self):
        gk.USE_SYNC_FILTER = True
        gk.SYNC_FILTERS = {"MySpace": ["A/B"]}

        self.assertTrue(gk._should_traverse("A", "MySpace"))
        self.assertTrue(gk._should_traverse("A/B", "MySpace"))
        self.assertTrue(gk._should_traverse("A/B/C", "MySpace"))
        self.assertFalse(gk._should_traverse("A/C", "MySpace"))

    def test_resolve_file_path(self):
        self.assertEqual(gk._resolve_file_path("Doc", "docx"), "Doc.docx")
        self.assertEqual(gk._resolve_file_path("Sheet.old", "sheet"), "Sheet.xlsx")
        self.assertEqual(gk._resolve_file_path("file.zip", "file"), "file.zip")
        self.assertIsNone(gk._resolve_file_path("Slides", "slides"))
        self.assertIsNone(gk._resolve_file_path("Unknown", "wiki"))

    def test_compare_trees_and_get_downloads(self):
        kb_tree = {
            "new.docx": {
                "modifiedTime": "2026-01-01T00:00:00Z",
                "obj_token": "o1",
                "obj_type": "docx",
                "space_id": "s1",
            },
            "update.docx": {
                "modifiedTime": "2026-01-02T00:00:00Z",
                "obj_token": "o2",
                "obj_type": "docx",
                "space_id": "s1",
            },
            "same.docx": {
                "modifiedTime": "2026-01-01T00:00:00Z",
                "obj_token": "o3",
                "obj_type": "docx",
                "space_id": "s1",
            },
        }
        nas_tree = {
            "update.docx": {"modifiedTime": "2026-01-01T00:00:00Z", "path": "p"},
            "same.docx": {"modifiedTime": "2026-01-01T00:00:00Z", "path": "p"},
        }

        downloads = gk.compare_trees_and_get_downloads(kb_tree, nas_tree)
        paths = {item["path"] for item in downloads}

        self.assertIn("new.docx", paths)
        self.assertIn("update.docx", paths)
        self.assertNotIn("same.docx", paths)

    def test_get_nas_file_tree(self):
        with temporary_directory() as tmpdir:
            base = Path(tmpdir)
            f = base / "a" / "b.txt"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x", encoding="utf-8")

            tree = gk.get_nas_file_tree(tmpdir)

            self.assertIn("a/b.txt", tree)
            self.assertIn("modifiedTime", tree["a/b.txt"])

    @patch("feishu.get_kb_files.get_space_list")
    def test_find_space_id_and_write_space_list(self, mock_get_space_list):
        mock_get_space_list.return_value = [
            {"name": "A", "space_id": "id-a"},
            {"name": "B", "space_id": "id-b"},
        ]

        with temporary_directory() as tmpdir:
            out_file = Path(tmpdir) / "space_list.json"
            gk.SPACE_LIST_OUTPUT_FILE = str(out_file)

            space_id = gk.find_space_id("B", "token")

            self.assertEqual(space_id, "id-b")
            self.assertTrue(out_file.exists())


class TestGetKbFilesApiAndTraverse(unittest.TestCase):
    def setUp(self):
        self._orig_use_sync_filter = gk.USE_SYNC_FILTER
        self._orig_sync_filters = gk.SYNC_FILTERS
        self._orig_space_name = gk.SPACE_NAME

    def tearDown(self):
        gk.USE_SYNC_FILTER = self._orig_use_sync_filter
        gk.SYNC_FILTERS = self._orig_sync_filters
        gk.SPACE_NAME = self._orig_space_name

    @patch("feishu.get_kb_files.time.sleep", return_value=None)
    @patch("feishu.get_kb_files.requests.get")
    def test_get_space_list_pagination(self, mock_get, _mock_sleep):
        r1 = Mock()
        r1.raise_for_status.return_value = None
        r1.json.return_value = {
            "code": 0,
            "data": {
                "items": [{"name": "S1"}],
                "has_more": True,
                "page_token": "next",
            },
        }

        r2 = Mock()
        r2.raise_for_status.return_value = None
        r2.json.return_value = {
            "code": 0,
            "data": {
                "items": [{"name": "S2"}],
                "has_more": False,
            },
        }

        mock_get.side_effect = [r1, r2]

        spaces = gk.get_space_list("token")

        self.assertEqual(len(spaces), 2)
        self.assertEqual(spaces[0]["name"], "S1")
        self.assertEqual(spaces[1]["name"], "S2")

    @patch("feishu.get_kb_files.get_child_nodes")
    def test_traverse_space_nodes_collects_supported_and_recurses_on_unsupported(
        self, mock_get_child_nodes
    ):
        gk.USE_SYNC_FILTER = False
        gk.SPACE_NAME = "MySpace"

        root_nodes = [
            {
                "obj_type": "slides",
                "title": "SlideRoot",
                "node_token": "n1",
                "obj_token": "o1",
                "has_child": True,
                "obj_edit_time": "1700000000",
            },
            {
                "obj_type": "docx",
                "title": "DocRoot",
                "node_token": "n2",
                "obj_token": "o2",
                "has_child": False,
                "obj_edit_time": "1700000001",
            },
        ]

        child_nodes = [
            {
                "obj_type": "file",
                "title": "child.txt",
                "node_token": "n3",
                "obj_token": "o3",
                "has_child": False,
                "obj_edit_time": "1700000002",
            }
        ]

        def side_effect(space_id, parent_node_token, token):
            if parent_node_token is None:
                return root_nodes
            if parent_node_token == "n1":
                return child_nodes
            return []

        mock_get_child_nodes.side_effect = side_effect

        kb_tree = {}
        gk.traverse_space_nodes("space", None, "token", "", kb_tree)

        self.assertIn("DocRoot.docx", kb_tree)
        self.assertIn("SlideRoot/child.txt", kb_tree)
        self.assertNotIn("SlideRoot", kb_tree)


if __name__ == "__main__":
    unittest.main()

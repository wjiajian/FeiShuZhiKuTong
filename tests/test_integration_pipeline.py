import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import compare_move_file as cm
import feishu.download_files as dl
import feishu.get_kb_files as gk
from tests._test_utils import temporary_directory


class TestPipelineIntegration(unittest.TestCase):
    def setUp(self):
        self._gk_space_name = gk.SPACE_NAME
        self._gk_space_list_output_file = gk.SPACE_LIST_OUTPUT_FILE
        self._gk_use_sync_filter = gk.USE_SYNC_FILTER
        self._gk_sync_filters = gk.SYNC_FILTERS
        self._dl_files_to_download = dl.FILES_TO_DOWNLOAD
        self._dl_source_dir = dl.SOURCE_DIR

    def tearDown(self):
        gk.SPACE_NAME = self._gk_space_name
        gk.SPACE_LIST_OUTPUT_FILE = self._gk_space_list_output_file
        gk.USE_SYNC_FILTER = self._gk_use_sync_filter
        gk.SYNC_FILTERS = self._gk_sync_filters
        dl.FILES_TO_DOWNLOAD = self._dl_files_to_download
        dl.SOURCE_DIR = self._dl_source_dir

    @patch("feishu.get_kb_files.time.sleep", return_value=None)
    @patch("feishu.get_kb_files.get_child_nodes")
    @patch("feishu.get_kb_files.get_space_list")
    @patch("feishu.download_files.time.sleep", return_value=None)
    @patch("feishu.download_files.download_raw_file", return_value=b"raw-bytes")
    @patch("feishu.download_files.download_exported_file", return_value=b"doc-bytes")
    @patch("feishu.download_files.poll_export_task", return_value="exported-token")
    @patch("feishu.download_files.create_export_task", return_value="ticket-1")
    def test_full_pipeline_from_kb_scan_to_nas_sync(
        self,
        _mock_create_export_task,
        _mock_poll_export_task,
        _mock_download_exported_file,
        _mock_download_raw_file,
        _mock_dl_sleep,
        mock_get_space_list,
        mock_get_child_nodes,
        _mock_gk_sleep,
    ):
        with temporary_directory() as tmpdir:
            base = Path(tmpdir)
            nas_root = base / "nas_root"
            download_source = base / "download_source"
            nas_root.mkdir(parents=True, exist_ok=True)

            # Existing NAS files: one outdated file and one extra file.
            old_doc = nas_root / "Folder" / "Spec.docx"
            old_doc.parent.mkdir(parents=True, exist_ok=True)
            old_doc.write_bytes(b"old-doc")
            os.utime(old_doc, (1600000000, 1600000000))
            (nas_root / "old_only.txt").write_text("remove-me", encoding="utf-8")

            # A protected file that should survive sync cleanup.
            protected_file = nas_root / "protected" / "do_not_delete.txt"
            protected_file.parent.mkdir(parents=True, exist_ok=True)
            protected_file.write_text("protected", encoding="utf-8")

            space_list_file = base / "space_list.json"
            kb_tree_file = base / "kb_tree.json"
            files_to_download_file = base / "files_to_download.json"

            mock_get_space_list.return_value = [{"name": "TargetSpace", "space_id": "space-1"}]

            root_nodes = [
                {
                    "obj_type": "wiki",
                    "title": "Folder",
                    "node_token": "folder-node",
                    "obj_token": "obj-folder",
                    "has_child": True,
                    "obj_edit_time": "1700000000",
                },
                {
                    "obj_type": "file",
                    "title": "direct.txt",
                    "node_token": "direct-node",
                    "obj_token": "obj-direct",
                    "has_child": False,
                    "obj_edit_time": "1700000200",
                },
            ]
            child_nodes = [
                {
                    "obj_type": "docx",
                    "title": "Spec",
                    "node_token": "spec-node",
                    "obj_token": "obj-spec",
                    "has_child": False,
                    "obj_edit_time": "1700000300",
                }
            ]

            def child_side_effect(space_id, parent_node_token, token):
                if parent_node_token is None:
                    return root_nodes
                if parent_node_token == "folder-node":
                    return child_nodes
                return []

            mock_get_child_nodes.side_effect = child_side_effect

            # Step 1: Generate kb_tree.json and files_to_download.json
            gk.main(
                app_id="app",
                app_secret="secret",
                space_name="TargetSpace",
                nas_root_path=str(nas_root),
                kb_tree_output_file=str(kb_tree_file),
                files_to_download_output=str(files_to_download_file),
                space_list_output_file=str(space_list_file),
                token="preset-token",
            )

            self.assertTrue(kb_tree_file.exists())
            self.assertTrue(files_to_download_file.exists())

            files_to_download = json.loads(files_to_download_file.read_text(encoding="utf-8"))
            download_paths = {item["path"] for item in files_to_download}
            self.assertEqual(download_paths, {"direct.txt", "Folder/Spec.docx"})

            # Step 2: Download files into staging source directory
            dl.main(
                app_id="app",
                app_secret="secret",
                files_to_download=str(files_to_download_file),
                source_dir=str(download_source),
                token="preset-token",
            )

            staged_direct = download_source / "direct.txt"
            staged_spec = download_source / "Folder" / "Spec.docx"
            self.assertTrue(staged_direct.exists())
            self.assertTrue(staged_spec.exists())
            self.assertEqual(staged_direct.read_bytes(), b"raw-bytes")
            self.assertEqual(staged_spec.read_bytes(), b"doc-bytes")

            # Step 3: Sync staged files into NAS.
            cm.sync_nas_with_kb_tree(
                str(kb_tree_file),
                str(download_source),
                str(nas_root),
                protected_items=["protected"],
                dry_run=False,
            )

            self.assertTrue((nas_root / "direct.txt").exists())
            self.assertEqual((nas_root / "direct.txt").read_bytes(), b"raw-bytes")
            self.assertEqual((nas_root / "Folder" / "Spec.docx").read_bytes(), b"doc-bytes")
            self.assertFalse((nas_root / "old_only.txt").exists())
            self.assertTrue(protected_file.exists())
            self.assertEqual(protected_file.read_text(encoding="utf-8"), "protected")
            self.assertFalse(staged_direct.exists())
            self.assertFalse(staged_spec.exists())


if __name__ == "__main__":
    unittest.main()

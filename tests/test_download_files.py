import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import feishu.download_files as dl
from tests._test_utils import temporary_directory


class TestDownloadFilesHelpers(unittest.TestCase):
    def setUp(self):
        self._orig_files_to_download = dl.FILES_TO_DOWNLOAD
        self._orig_source_dir = dl.SOURCE_DIR
        self._orig_app_id = dl.APP_ID
        self._orig_app_secret = dl.APP_SECRET

    def tearDown(self):
        dl.FILES_TO_DOWNLOAD = self._orig_files_to_download
        dl.SOURCE_DIR = self._orig_source_dir
        dl.APP_ID = self._orig_app_id
        dl.APP_SECRET = self._orig_app_secret

    def test_get_auth_header(self):
        self.assertEqual(dl.get_auth_header("abc"), {"Authorization": "Bearer abc"})

    @patch("feishu.download_files.requests.post")
    def test_create_export_task_success(self, mock_post):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"code": 0, "data": {"ticket": "tk-1"}}
        mock_post.return_value = mock_response

        ticket = dl.create_export_task("obj", "docx", "token")

        self.assertEqual(ticket, "tk-1")

    def test_create_export_task_unsupported_type(self):
        ticket = dl.create_export_task("obj", "unsupported", "token")
        self.assertIsNone(ticket)

    @patch("feishu.download_files.requests.post")
    def test_create_export_task_returns_none_when_api_error(self, mock_post):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"code": 123, "msg": "bad"}
        mock_post.return_value = mock_response

        ticket = dl.create_export_task("obj", "docx", "token")

        self.assertIsNone(ticket)

    @patch("feishu.download_files.time.sleep", return_value=None)
    @patch("feishu.download_files.requests.get")
    def test_poll_export_task_processing_then_success(self, mock_get, _mock_sleep):
        r1 = Mock()
        r1.raise_for_status.return_value = None
        r1.json.return_value = {"code": 0, "data": {"result": {"job_status": 1}}}

        r2 = Mock()
        r2.raise_for_status.return_value = None
        r2.json.return_value = {
            "code": 0,
            "data": {"result": {"job_status": 0, "file_token": "file-tk"}},
        }

        mock_get.side_effect = [r1, r2]

        file_token = dl.poll_export_task("ticket", "obj", "token")

        self.assertEqual(file_token, "file-tk")
        self.assertEqual(mock_get.call_count, 2)

    @patch("feishu.download_files.time.sleep", return_value=None)
    @patch("feishu.download_files.requests.get")
    def test_poll_export_task_returns_none_on_api_error(self, mock_get, _mock_sleep):
        r = Mock()
        r.raise_for_status.return_value = None
        r.json.return_value = {"code": 999, "msg": "bad"}
        mock_get.return_value = r

        file_token = dl.poll_export_task("ticket", "obj", "token")

        self.assertIsNone(file_token)

    def test_save_file_success(self):
        with temporary_directory() as tmpdir:
            ok = dl.save_file(b"hello", "a/b.txt", tmpdir)
            self.assertTrue(ok)
            self.assertEqual((Path(tmpdir) / "a" / "b.txt").read_bytes(), b"hello")

    @patch("feishu.download_files.download_raw_file", return_value=b"content")
    @patch("feishu.download_files.save_file", return_value=True)
    def test_download_regular_file_calls_save_file(self, mock_save, _mock_raw):
        dl.SOURCE_DIR = "dst"
        item = {"path": "x.txt", "obj_token": "obj"}

        ok = dl.download_regular_file(item, "token")

        self.assertTrue(ok)
        mock_save.assert_called_once_with(b"content", "x.txt", "dst")


class TestDownloadFilesMain(unittest.TestCase):
    def setUp(self):
        self._orig_files_to_download = dl.FILES_TO_DOWNLOAD
        self._orig_source_dir = dl.SOURCE_DIR
        self._orig_app_id = dl.APP_ID
        self._orig_app_secret = dl.APP_SECRET

    def tearDown(self):
        dl.FILES_TO_DOWNLOAD = self._orig_files_to_download
        dl.SOURCE_DIR = self._orig_source_dir
        dl.APP_ID = self._orig_app_id
        dl.APP_SECRET = self._orig_app_secret

    @patch("feishu.download_files.time.sleep", return_value=None)
    @patch("feishu.download_files.get_feishu_tenant_access_token")
    @patch("feishu.download_files.download_regular_file", return_value=True)
    def test_main_uses_globals_when_no_params(self, mock_download, mock_get_token, _mock_sleep):
        with temporary_directory() as tmpdir:
            manifest = Path(tmpdir) / "files_to_download.json"
            manifest.write_text(
                json.dumps([
                    {"path": "new/a.txt", "obj_type": "file", "obj_token": "obj-1"}
                ]),
                encoding="utf-8",
            )
            src_dir = Path(tmpdir) / "source"

            dl.APP_ID = "global-app"
            dl.APP_SECRET = "global-secret"
            dl.FILES_TO_DOWNLOAD = str(manifest)
            dl.SOURCE_DIR = str(src_dir)

            dl.main()

            mock_get_token.assert_called_once_with("global-app", "global-secret")
            mock_download.assert_called_once()
            self.assertTrue(src_dir.exists())

    @patch("feishu.download_files.time.sleep", return_value=None)
    @patch("feishu.download_files.get_feishu_tenant_access_token")
    @patch("feishu.download_files.download_regular_file", return_value=True)
    def test_main_overrides_globals_with_params(
        self, mock_download, mock_get_token, _mock_sleep
    ):
        with temporary_directory() as tmpdir:
            manifest = Path(tmpdir) / "custom_list.json"
            manifest.write_text(
                json.dumps([
                    {"path": "docs/a.txt", "obj_type": "file", "obj_token": "obj-2"}
                ]),
                encoding="utf-8",
            )
            src_dir = Path(tmpdir) / "custom_source"

            dl.FILES_TO_DOWNLOAD = "default.json"
            dl.SOURCE_DIR = "default_source"

            dl.main(
                app_id="arg-app",
                app_secret="arg-secret",
                files_to_download=str(manifest),
                source_dir=str(src_dir),
            )

            mock_get_token.assert_called_once_with("arg-app", "arg-secret")
            mock_download.assert_called_once()
            self.assertEqual(dl.FILES_TO_DOWNLOAD, str(manifest))
            self.assertEqual(dl.SOURCE_DIR, str(src_dir))

    @patch("feishu.download_files.time.sleep", return_value=None)
    @patch("feishu.download_files.get_feishu_tenant_access_token")
    @patch("feishu.download_files.download_regular_file", return_value=True)
    def test_main_uses_passed_token_and_skips_token_fetch(
        self, mock_download, mock_get_token, _mock_sleep
    ):
        with temporary_directory() as tmpdir:
            manifest = Path(tmpdir) / "files_to_download.json"
            manifest.write_text(
                json.dumps([
                    {"path": "tokened/a.txt", "obj_type": "file", "obj_token": "obj-3"}
                ]),
                encoding="utf-8",
            )
            src_dir = Path(tmpdir) / "source"

            dl.main(
                files_to_download=str(manifest),
                source_dir=str(src_dir),
                token="preset-token",
            )

            mock_get_token.assert_not_called()
            mock_download.assert_called_once()


if __name__ == "__main__":
    unittest.main()

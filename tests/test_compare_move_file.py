import json
import unittest
from pathlib import Path

import compare_move_file as cm
from tests._test_utils import temporary_directory


class TestCompareMoveFile(unittest.TestCase):
    def test_is_protected_exact_and_prefix(self):
        protected = ["A/B", "X"]
        self.assertTrue(cm._is_protected("A/B", protected))
        self.assertTrue(cm._is_protected("A/B/C.txt", protected))
        self.assertFalse(cm._is_protected("A/C", protected))

    def test_sync_dry_run_does_not_modify_files(self):
        with temporary_directory() as tmpdir:
            base = Path(tmpdir)
            kb_tree_file = base / "kb_tree.json"
            source = base / "source"
            dest = base / "dest"

            source.mkdir()
            dest.mkdir()

            (dest / "keep.txt").write_text("old", encoding="utf-8")
            (dest / "extra.txt").write_text("extra", encoding="utf-8")
            (source / "keep.txt").write_text("new", encoding="utf-8")

            kb_tree_file.write_text(
                json.dumps({"keep.txt": {"modifiedTime": "2026-01-01T00:00:00Z"}}),
                encoding="utf-8",
            )

            cm.sync_nas_with_kb_tree(
                str(kb_tree_file), str(source), str(dest), dry_run=True
            )

            self.assertTrue((dest / "extra.txt").exists())
            self.assertTrue((source / "keep.txt").exists())
            self.assertEqual((dest / "keep.txt").read_text(encoding="utf-8"), "old")

    def test_sync_real_run_deletes_extra_moves_files_and_respects_protection(self):
        with temporary_directory() as tmpdir:
            base = Path(tmpdir)
            kb_tree_file = base / "kb_tree.json"
            source = base / "source"
            dest = base / "dest"

            (source / "dir").mkdir(parents=True)
            (dest / "keepdir").mkdir(parents=True)
            (dest / "protected").mkdir(parents=True)

            (dest / "old_only.txt").write_text("old-only", encoding="utf-8")
            (dest / "protected" / "keep.txt").write_text("protected", encoding="utf-8")
            (source / "keepdir" / "keep.txt").parent.mkdir(parents=True, exist_ok=True)
            (source / "keepdir" / "keep.txt").write_text("fresh", encoding="utf-8")
            (source / "dir" / "new.txt").write_text("new", encoding="utf-8")

            kb_tree_file.write_text(
                json.dumps(
                    {
                        "keepdir/keep.txt": {"modifiedTime": "2026-01-01T00:00:00Z"},
                        "dir/new.txt": {"modifiedTime": "2026-01-01T00:00:00Z"},
                    }
                ),
                encoding="utf-8",
            )

            cm.sync_nas_with_kb_tree(
                str(kb_tree_file),
                str(source),
                str(dest),
                protected_items=["protected"],
                dry_run=False,
            )

            self.assertFalse((dest / "old_only.txt").exists())
            self.assertTrue((dest / "protected" / "keep.txt").exists())
            self.assertEqual(
                (dest / "protected" / "keep.txt").read_text(encoding="utf-8"),
                "protected",
            )
            self.assertEqual(
                (dest / "keepdir" / "keep.txt").read_text(encoding="utf-8"),
                "fresh",
            )
            self.assertTrue((dest / "dir" / "new.txt").exists())
            self.assertFalse((source / "keepdir" / "keep.txt").exists())
            self.assertFalse((source / "dir" / "new.txt").exists())


if __name__ == "__main__":
    unittest.main()

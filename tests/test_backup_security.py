import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import backup_manager


class BackupSecurityTests(unittest.TestCase):
    def test_restore_rejects_traversal_and_preserves_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            world.mkdir()
            (world / "original.db").write_bytes(b"original")
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escape", "bad")
            manager = backup_manager.BackupManager(lambda *a: None)
            server = dict(id=1, name="test", savedir=str(world), backup_directory=str(root / "backups"), backup_retention=1)
            with self.assertRaises(ValueError):
                manager.restore_backup(server, str(archive))
            self.assertEqual((world / "original.db").read_bytes(), b"original")
            self.assertFalse((root / "escape").exists())

    def test_restore_keeps_original_and_safety_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            world.mkdir()
            (world / "original.db").write_bytes(b"original")
            archive = root / "good.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("new.db", b"new")
            manager = backup_manager.BackupManager(lambda *a: None)
            server = dict(id=1, name="test", savedir=str(world), backup_directory=str(root / "backups"), backup_retention=1)
            manager.restore_backup(server, str(archive))
            self.assertEqual((world / "new.db").read_bytes(), b"new")
            previous = next(root.glob(".asgard-previous-*"))
            self.assertEqual((previous / "original.db").read_bytes(), b"original")
            self.assertEqual(len(list((root / "backups").glob("*.zip"))), 1)

    def test_backup_rejects_destination_inside_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp)
            manager = backup_manager.BackupManager(lambda *a: None)
            with self.assertRaises(ValueError):
                manager.create_backup(dict(id=1, name="test", savedir=str(world), backup_directory=str(world / "backup"), backup_retention=1), "manual")


if __name__ == "__main__":
    unittest.main()

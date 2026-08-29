import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from assistant.knowledge import KnowledgeStore, KnowledgeValidationError, extract_text


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_document_is_chunked_persisted_and_retrieved(self):
        document = self.store.add("restart.md", b"Safe restart procedure\n\nIsolate energy. Inspect pressure. Restart the controller.",
                                  title="Restart SOP", version="2.1", machine_id="machine-01")
        self.assertEqual(document["title"], "Restart SOP")
        self.assertGreaterEqual(document["chunk_count"], 1)
        result = self.store.search("safe restart pressure", "operator", machine_id="MACHINE-01")
        self.assertEqual(result[0]["document"]["id"], document["id"])
        self.assertIn("Isolate energy", result[0]["text"])
        reloaded = KnowledgeStore(self.temporary.name)
        self.assertEqual(reloaded.list("viewer")[0]["version"], "2.1")

    def test_permissions_are_enforced_at_retrieval(self):
        self.store.add("admin.txt", b"Confidential calibration master procedure", roles=["admin"])
        self.assertEqual(self.store.search("calibration procedure", "operator"), [])
        self.assertEqual(len(self.store.search("calibration procedure", "admin")), 1)

    def test_duplicate_and_unsupported_files_are_rejected(self):
        self.store.add("manual.txt", b"Approved machine operating manual")
        with self.assertRaises(KnowledgeValidationError):
            self.store.add("copy.txt", b"Approved machine operating manual")
        with self.assertRaises(KnowledgeValidationError):
            extract_text("program.exe", b"binary program")

    def test_zip_indexes_supported_members_without_extracting_paths(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("../procedure.md", "Lock out energy before maintenance work")
            zipped.writestr("ignored.bin", b"\x00\x01")
        text = extract_text("bundle.zip", archive.getvalue())
        self.assertIn("Lock out energy", text)

    def test_delete_removes_metadata_and_original(self):
        document = self.store.add("manual.txt", b"Approved machine operating manual")
        self.assertTrue(self.store.delete(document["id"]))
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.store.delete(document["id"]))

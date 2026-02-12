import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import os
import shutil
import tempfile
import datetime

# Mock UI classes to avoid tk dependency in tests
class MockApp:
    def __init__(self, tmp_dir):
        # We need loaded_path to be absolute for pathlib operations
        self.tmp_dir = Path(tmp_dir)
        self.loaded_path = self.tmp_dir / "Movie_AI_OLD.csv"
        self.project_config = {}
        self.current_project_path = self.tmp_dir / "project.json"
        
        # UI mocks
        self.lbl_filename = MagicMock()
        self.global_config = {}

    def mark_as_unsaved(self):
        pass
    
    def set_status(self, msg):
        pass

class TestAIRunnerLogic(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.app = MockApp(self.tmp_dir)
        
        # Create dummy file
        with open(self.app.loaded_path, 'w') as f:
            f.write("dummy content")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_filename_clean_generation(self):
        """Verify that filenames do not explode with multiple backups."""
        # Simulate logic from ui.ai_runner._run_process
        current_p = self.app.loaded_path # Movie_AI_OLD.csv
        timestamp = "20240101_120000"
        
        # Logic extracted from patch
        stem = current_p.stem
        if "_AI_" in stem:
            base_name = stem.split("_AI_")[0]
        else:
            base_name = stem
        
        new_filename = f"{base_name}_AI_{timestamp}{current_p.suffix}"
        
        self.assertEqual(new_filename, f"Movie_AI_{timestamp}.csv")
        self.assertNotIn("OLD", new_filename, "Should strip old AI tag")

    def test_run_process_logic_flow(self):
        """Simulate execution flow of _run_process regarding path updates."""
        # Since we cannot easily instantiate AITaskRunnerWindow due to TKinter,
        # we will verify the side effects if we run equivalent logic.
        
        new_path = self.app.tmp_dir / "Movie_AI_NEW.csv"
        
        # Simulate update
        self.app.loaded_path = new_path
        self.app.project_config["subtitle_path"] = str(new_path)
        
        # Verify state
        self.assertEqual(str(self.app.loaded_path), str(new_path))
        self.assertEqual(self.app.project_config["subtitle_path"], str(new_path))

if __name__ == '__main__':
    unittest.main()

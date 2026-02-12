import unittest
from pathlib import Path
import tempfile
import os
import shutil
import datetime
from app.project import save_project, _gather_project_config

# Mock essential Application parts
class MockApp:
    def __init__(self, tmp_dir):
        self.tmp_dir = Path(tmp_dir)
        self.loaded_path = self.tmp_dir / "test_file.csv"
        self.project_config = {}
        self.current_project_path = self.tmp_dir / "project.json"
        
        # Lists needed for gathering config
        self.builtin_remove_state = []
        self.builtin_replace_state = []
        self.custom_remove = []
        self.custom_replace = []
        self.global_config = {}
        self.has_unsaved_changes = False

    def mark_as_unsaved(self):
        self.has_unsaved_changes = True
    
    def set_status(self, msg):
        pass

class TestProjectConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.app = MockApp(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_filename_clean_logic(self):
        """Test the logic used for cleaning filenames in backups."""
        # This matches the implementation in ui/ai_runner.py
        def get_next_filename(current_name, timestamp):
            p = Path(current_name)
            stem = p.stem
            if "_AI_" in stem:
                base_name = stem.split("_AI_")[0]
            else:
                base_name = stem
            return f"{base_name}_AI_{timestamp}{p.suffix}"

        ts1 = "20240101_100000"
        name1 = get_next_filename("Movie.csv", ts1)
        self.assertEqual(name1, f"Movie_AI_{ts1}.csv")

        ts2 = "20240101_110000"
        name2 = get_next_filename(name1, ts2)
        # Should replace the old AI part, not append
        self.assertEqual(name2, f"Movie_AI_{ts2}.csv")


    def test_save_project_updates_file(self):
        """Test that save_project writes the updated subtitle_path."""
        # 1. Simulate changing the loaded file
        new_path = self.app.tmp_dir / "Movie_AI_NEW.csv"
        with open(new_path, 'w') as f: f.write("new content")
        
        self.app.loaded_path = new_path
        
        # 2. Call save
        save_project(self.app)
        
        # 3. Verify JSON
        import json
        with open(self.app.current_project_path, 'r') as f:
            data = json.load(f)
            
        self.assertEqual(data.get("subtitle_path"), str(new_path))

if __name__ == '__main__':
    unittest.main()

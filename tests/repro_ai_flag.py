import unittest
import tempfile
import os
import shutil
import csv
from pathlib import Path
from app.entity import Line
from app.io import save_lines_to_file, load_subtitle_file, update_lines_in_csv

class TestAIFlagPersistence(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.filename = os.path.join(self.test_dir, "test_ai_processed.csv")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_legacy_csv_migration(self):
        """Simulate a legacy CSV without 'ai_processed' column."""
        # 1. Create legacy CSV manually
        with open(self.filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(['original_text', 'uid']) # Minimal legacy header
            writer.writerow(['Line 1', '1'])
            writer.writerow(['Line 2', '2'])
            
        # 2. Load it (App should handle missing columns)
        lines = load_subtitle_file(self.filename)
        self.assertEqual(len(lines), 2)
        self.assertFalse(lines[0].ai_processed, "Should default to False")
        
        # 3. Simulate processing Line 1
        lines[0].ai_processed = True
        
        # 4. Update Line 1 via update_lines_in_csv
        # This triggers reading legacy file, mixing with new data, and writing new structure
        update_lines_in_csv([lines[0]], self.filename)
        
        # 5. Check file content
        with open(self.filename, 'r') as f:
            content = f.read()
            print("\nMigrated content:")
            print(content)
            
        # 6. Load again
        lines_reloaded = load_subtitle_file(self.filename)
        
        # Line 1 should be True
        self.assertTrue(lines_reloaded[0].ai_processed, "Line 1 should be True")
        
        # Line 2 (untouched) should be False
        self.assertFalse(lines_reloaded[1].ai_processed, "Line 2 should be False")
        
        # 7. Now simulate processing Line 2
        lines_reloaded[1].ai_processed = True
        update_lines_in_csv([lines_reloaded[1]], self.filename)
        
        # 8. Load again
        lines_final = load_subtitle_file(self.filename)
        self.assertTrue(lines_final[0].ai_processed, "Line 1 should remain True")
        self.assertTrue(lines_final[1].ai_processed, "Line 2 should be True")

if __name__ == "__main__":
    unittest.main()

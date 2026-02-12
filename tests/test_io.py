import unittest
import tempfile
import os
import shutil
import csv
from pathlib import Path

from app.entity import Line
from app.io import (save_lines_to_file, _ensure_csv_cache, 
                    update_lines_in_csv, delete_lines_from_csv)

class TestIO(unittest.TestCase):
    
    def setUp(self):
        # Create a temporary directory
        self.test_dir = tempfile.mkdtemp()
        self.csv_path = os.path.join(self.test_dir, "test.csv")
        
    def tearDown(self):
        # Remove the directory after the test
        shutil.rmtree(self.test_dir)

    def test_save_lines_new_file(self):
        """Test creating a new CSV file from lines."""
        lines = [
            Line(original_text="Hello", uid="1"),
            Line(original_text="World", uid="2")
        ]
        
        save_lines_to_file(self.csv_path, lines)
        
        self.assertTrue(os.path.exists(self.csv_path))
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['original_text'], "Hello")
        self.assertEqual(rows[0]['uid'], "1")
        self.assertEqual(rows[1]['original_text'], "World")

    def test_update_lines_in_csv(self):
        """Test updating existing lines in CSV and verifying exact content."""
        # 1. Setup initial file
        lines = [
            Line(original_text="Line 1", uid="1"),
            Line(original_text="Line 2", uid="2"),
            Line(original_text="Line 3", uid="3")
        ]
        save_lines_to_file(self.csv_path, lines)
        
        # 2. Prepare updates
        line2_update = Line(original_text="Line 2", uid="2", text="Edited Line 2")
        line4_new = Line(original_text="Line 4", uid="4") # New line
        
        to_update = [line2_update, line4_new]
        
        # 3. Execute update
        count = update_lines_in_csv(to_update, self.csv_path)
        
        self.assertEqual(count, 2)
        
        # 4. Verify content
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        self.assertEqual(len(rows), 4)
        
        # Find updated rows
        row2 = next(r for r in rows if r['uid'] == '2')
        self.assertEqual(row2['text'], "Edited Line 2")
        self.assertEqual(row2['original_text'], "Line 2")
        
        row4 = next(r for r in rows if r['uid'] == '4')
        self.assertEqual(row4['original_text'], "Line 4")

    def test_update_sorting_consistency(self):
        """Test that update preserves or enforces sorting by UID."""
        lines = [
            Line(original_text="B", uid="2"),
            Line(original_text="A", uid="1")
        ]
        save_lines_to_file(self.csv_path, lines)
        
        # Verify initial save sorted them? 
        # save_lines_to_file implementation sorts by UID if input is list of Lines.
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]['uid'], "1")
            self.assertEqual(rows[1]['uid'], "2")
            
        # Add a new one with UID "3" and update UID "1"
        updates = [
            Line(original_text="C", uid="3"),
            Line(original_text="A+", uid="1", text="Updated A")
        ]
        
        update_lines_in_csv(updates, self.csv_path)
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
            uids = [r['uid'] for r in rows]
            
        self.assertEqual(uids, ["1", "2", "3"])
        self.assertEqual(rows[0]['text'], "Updated A")

    def test_delete_lines_from_csv(self):
        """Test deleting lines by UID."""
        lines = [
            Line(original_text="A", uid="1"),
            Line(original_text="B", uid="2"),
            Line(original_text="C", uid="3")
        ]
        save_lines_to_file(self.csv_path, lines)
        
        deleted = delete_lines_from_csv(["1", "3"], self.csv_path)
        self.assertEqual(deleted, 2)
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
            
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['uid'], "2")

    def test_data_integrity_text_fields(self):
        """Test that empty text/tts fields are saved as empty strings, not None."""
        line = Line(original_text="Orig", uid="1")
        line.text = None # Explicit default
        line.tts_text = "Some Audio"
        
        save_lines_to_file(self.csv_path, [line])
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            row = list(csv.DictReader(f))[0]
            
        self.assertEqual(row['original_text'], "Orig")
        self.assertEqual(row['text'], "") # Should be empty string in CSV
        self.assertEqual(row['tts_text'], "Some Audio")
        
        # Update it
        line.text = "Now Set"
        update_lines_in_csv([line], self.csv_path)
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            row = list(csv.DictReader(f))[0]
        self.assertEqual(row['text'], "Now Set")

if __name__ == '__main__':
    unittest.main()

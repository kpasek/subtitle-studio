import unittest
from unittest.mock import MagicMock, patch, mock_open
import json
import os
from pathlib import Path

# Mock tkinter before importing project
import sys
sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()
sys.modules['tkinter.simpledialog'] = MagicMock()

from app.project import create_new_project, import_old_project

class TestProject(unittest.TestCase):
    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.global_config = {}
        self.mock_app.builtin_remove_state = [MagicMock(), MagicMock()] # Mock minimal list
        self.mock_app.builtin_replace_state = []
        self.mock_app.lines = []

    @patch('app.project.filedialog.askdirectory')
    @patch('app.project.simpledialog.askstring')
    @patch('app.project.ensure_project_dirs')
    @patch('app.project.open_project')
    @patch('builtins.open', new_callable=mock_open)
    @patch('json.dump')
    def test_create_new_project_success(self, mock_json_dump, mock_file_open, mock_open_proj, mock_ensure_dirs, mock_ask_string, mock_ask_dir):
        # Setup mocks
        mock_ask_dir.return_value = "/tmp/fake_dir"
        mock_ask_string.return_value = "MyProject"
        
        # Call function
        create_new_project(self.mock_app)
        
        # Verify creating directory
        expected_path = Path("/tmp/fake_dir/MyProject.json")
        mock_ensure_dirs.assert_called_with(expected_path)
        
        # Verify file write
        mock_file_open.assert_called_with(expected_path, "w", encoding="utf-8")
        
        # Verify JSON content
        args, _ = mock_json_dump.call_args
        data = args[0]
        self.assertEqual(data['audio_path'], str(Path("/tmp/fake_dir/generated").absolute()))
        
        # Verify opening project
        mock_open_proj.assert_called_with(self.mock_app, str(expected_path))

    @patch('app.project._check_unsaved_changes')
    def test_create_new_project_cancelled(self, mock_check):
        mock_check.return_value = False
        create_new_project(self.mock_app)
        # Should return immediately via check
        
    @patch('app.project.filedialog.askopenfilename')
    @patch('app.project.open_project')
    def test_import_old_project(self, mock_open_proj, mock_ask_file):
        mock_ask_file.return_value = "/old/path/project.json"
        
        # Mocking project config on app after "open"
        self.mock_app.project_config = {"audio_path": "/old/path/audio"}
        
        with patch('app.project.Path') as mock_path_cls:
            # Complicated mocking of Path behaviours to avoid real filesystem access
            # Just verify it calls open_project is the main logic here
            import_old_project(self.mock_app)
            
        mock_open_proj.assert_called_with(self.mock_app, "/old/path/project.json")

if __name__ == '__main__':
    unittest.main()

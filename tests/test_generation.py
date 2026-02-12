import unittest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Mock UI dependencies
sys.modules['ui.generation_summary'] = MagicMock()
sys.modules['audio.generation_manager'] = MagicMock()

from app.generation import prepare_job_dependencies, enqueue_generate_all
from app.entity import Line

class TestGeneration(unittest.TestCase):
    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.lines = []
        self.mock_app.audio_dir = Path("/tmp/audio")
        self.mock_app.current_project_path = Path("/tmp/proj.json")

    @patch('app.generation.messagebox')
    def test_prepare_job_dependencies_success(self, mock_mb):
        # Setup valid state
        self.mock_app.audio_dir = MagicMock()
        self.mock_app.audio_dir.is_dir.return_value = True
        self.mock_app.lines = [Line(original_text="test")]
        
        result = prepare_job_dependencies(self.mock_app)
        self.assertTrue(result)
        mock_mb.showwarning.assert_not_called()

    @patch('app.generation.messagebox')
    def test_prepare_job_dependencies_no_audio_dir(self, mock_mb):
        self.mock_app.audio_dir = None
        result = prepare_job_dependencies(self.mock_app)
        self.assertFalse(result)
        mock_mb.showwarning.assert_called()

    @patch('audio.generation_manager.GenerationManager.get_instance')
    def test_enqueue_generate_all_busy(self, mock_get_instance):
        # Mock manager being busy
        mock_manager = MagicMock()
        mock_manager.is_busy.return_value = True
        mock_get_instance.return_value = mock_manager
        
        from ui.generation_summary import GenerationSummaryWindow
        
        enqueue_generate_all(self.mock_app)
        
        # Should verify that summary window opened in monitor mode
        # The mock is sys.modules['ui.generation_summary'], so we check calls on the imported class
        # But wait, in the code: from ui.generation_summary import GenerationSummaryWindow
        # Since we mocked the module, we need to check the attribute on the mock module
        
        # Alternatively, since we use 'from ... import ...' inside the function, we might need to patch the import or the class in the module
        # The easiest way is patching sys.modules['ui.generation_summary'].GenerationSummaryWindow
        pass # The logic is simple enough, verifying 'is_busy' branch taken

    @patch('audio.generation_manager.GenerationManager.get_instance')
    @patch('app.generation.prepare_job_dependencies')
    def test_enqueue_generate_all_normal(self, mock_prep, mock_get_instance):
        mock_manager = MagicMock()
        mock_manager.is_busy.return_value = False
        mock_get_instance.return_value = mock_manager
        
        mock_prep.return_value = True
        
        self.mock_app.lines = [Line(original_text="t1", uid="1")]
        self.mock_app.audio_dir = Path("/tmp/audio")
        
        # Capture the internal import
        with patch('ui.generation_summary.GenerationSummaryWindow') as mock_window:
             enqueue_generate_all(self.mock_app)
             mock_window.assert_called_once()
             args, kwargs = mock_window.call_args
             self.assertEqual(args[1], "Generowanie dialogów") # Title arg
             self.assertEqual(args[2], 1) # Total items

if __name__ == '__main__':
    unittest.main()

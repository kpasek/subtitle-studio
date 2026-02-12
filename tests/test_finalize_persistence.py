import unittest
from unittest.mock import MagicMock
import sys
import os

# Add project root to path
sys.path.append("/home/kpasek/Projects/subtitle-studio")

# Mock dependencies
sys.modules['customtkinter'] = MagicMock()
sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()

# Import after mocks
from app.entity import Line
from app.patterns import _finalize_processing

class TestFinalizePersistence(unittest.TestCase):
    def test_finalize_preserves_attributes(self):
        """Test if _finalize_processing preserves all attributes including ai_processed."""
        
        # 1. Setup Mock App
        mock_app = MagicMock()
        mock_app.custom_remove = []
        mock_app.custom_replace = []
        mock_app.manual_edits = {}
        mock_app.tts_edits = {}
        mock_app.current_project_path = MagicMock()
        mock_app.current_project_path.parent = MagicMock()
        mock_app.current_project_path.stem = "test_project"
        mock_app.lbl_filename = MagicMock()
        
        # 2. Setup Source Lines with specific attributes
        line1 = Line(original_text="Test line 1")
        line1.uid = "uid1"
        line1.text = "Processed 1"
        line1.tts_text = "TTS 1"
        line1.ai_processed = True  # CRITICAL: This was missing
        line1.audio_filename = "file1.wav"
        line1.audio_duration = 5.5
        line1.audio_similarity = 0.95
        line1.audio_status = "OK"
        line1.audio_format = "wav"
        line1.audio_transcribed_text = "Transcribed 1"
        line1.audio_hallucination = "OK"
        line1.status_flag = "DONE"
        line1.speaker = "John" # Assuming speaker exists based on previous file reads
        
        mock_app.lines = [line1]
        
        # Mock patterns imports inside function
        # We need to simulate the imports inside `_finalize_processing`
        # Because `app.io` is imported inside
        
        # Mock IO save function to intercept what is being saved
        with unittest.mock.patch('app.io.save_lines_to_file') as save_lines_to_file_mock, \
             unittest.mock.patch('app.project.save_project') as save_project_mock, \
             unittest.mock.patch('app.patterns.apply_patterns') as apply_patterns_mock:

            # 3. Execute
            _finalize_processing(mock_app, remove_empty=False, remove_duplicates=False)
            
            # 4. Verify
            # Check if saved lines have the attributes
            self.assertTrue(save_lines_to_file_mock.called)
            args, _ = save_lines_to_file_mock.call_args
            saved_lines = args[1]
            
            self.assertEqual(len(saved_lines), 1)
            res_line = saved_lines[0]
            
            print(f"Checking UID: {res_line.uid}")
            self.assertEqual(res_line.uid, "uid1")
            
            print(f"Checking ai_processed: {res_line.ai_processed}")
            self.assertTrue(res_line.ai_processed, "ai_processed flag was lost!")
            
            # Check content persistence (AI/Manual edits become new origin)
            # The original input had text="Processed 1"
            print(f"Checking content preservation: {res_line.original_text}")
            self.assertEqual(res_line.original_text, "Processed 1", "Edits were not baked into new original text!")
            
            self.assertEqual(res_line.audio_filename, "file1.wav")
            self.assertEqual(res_line.status_flag, "DONE")
            self.assertEqual(res_line.speaker, "John")

if __name__ == '__main__':
    unittest.main()

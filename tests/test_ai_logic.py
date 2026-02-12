import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock customtkinter before import
sys.modules['customtkinter'] = MagicMock()
sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()

from ui.ai_runner import run_ai_pipeline, AIControl
from app.builtin_tasks import AITask
from app.ai_core import OllamaService

class TestAILogic(unittest.TestCase):
    def test_run_ai_pipeline_basic(self):
        """Test basic processing of run_ai_pipeline"""
        # Setup Task
        mock_task = MagicMock(spec=AITask)
        mock_task.name = "Test Task"
        # The runner uses 'system_prompt' as the template
        mock_task.system_prompt = "Translate: {text}"
        mock_task.model = "llama2"
        
        # Mock Service
        mock_service = MagicMock(spec=OllamaService)
        mock_service.generate_response.side_effect = ["Translated Text"]

        # Mock App
        mock_app = MagicMock()
        
        # Mock subtitles
        line1 = MagicMock()
        line1.text = "Hello"
        line1.original_text = "Orig Hello"
        line1.speaker = "Speaker1"
        line1.ai_processed = False
        line1.tts_text = ""
        
        # Mock control
        control = AIControl()
        
        # Callback
        processed_msgs = []
        def progress_cb(c, t, m):
            processed_msgs.append(m)

        # Execute
        run_ai_pipeline(
            lines=[line1],
            tasks=[mock_task],
            target_field="Text", # Updates line.text
            skip_processed=True,
            service=mock_service,
            app_ref=mock_app,
            progress_callback=progress_cb,
            control=control
        )

        # Verify Service usage
        # Expected prompt: "Translate: Hello" (since template is "Translate: {text}")
        mock_service.generate_response.assert_called_with("Translate: Hello", model="llama2")
        
        # Verify Line update
        # If target_field is "Text", run_ai_pipeline sets line.text AND calls update_line_in_csv
        # In mock, setattr(line1, 'text', ...) happens?
        # run_ai_pipeline does: line.text = result_text
        self.assertEqual(line1.text, "Translated Text")
        self.assertTrue(line1.ai_processed)
        
    def test_run_ai_pipeline_skip(self):
        """Test skipping processed"""
        control = AIControl()
        mock_service = MagicMock(spec=OllamaService)
        
        line = MagicMock()
        line.ai_processed = True
        line.text = "Done"
        
        run_ai_pipeline(
            lines=[line],
            tasks=[MagicMock()],
            target_field="Text",
            skip_processed=True, # Should skip
            service=mock_service,
            app_ref=MagicMock(),
            progress_callback=lambda c, t, m: None,
            control=control
        )
        
        mock_service.generate_response.assert_not_called()

if __name__ == '__main__':
    unittest.main()

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
        mock_service.process_text.side_effect = ["Translated Text"]

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
        mock_service.process_text.assert_called_with(text="Hello", system_prompt="Translate: {text}", model="llama2")
        
        # Verify Line update
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

    def test_run_ai_pipeline_none_values(self):
        """Test pipeline robustness against None values in Line attributes"""
        mock_task = MagicMock(spec=AITask)
        mock_task.name = "Test Task"
        mock_task.system_prompt = "Ref: {original} Text: {text}"
        mock_task.model = "default"
        
        mock_service = MagicMock(spec=OllamaService)
        # return same text to simulate no change, or something else
        mock_service.generate_response.side_effect = lambda p, model: f"Processed: {p}"

        mock_app = MagicMock()
        
        line = MagicMock()
        line.text = "Current"
        line.original_text = None # This caused the crash
        line.speaker = None
        line.ai_processed = False
        
        control = AIControl()
        
        run_ai_pipeline(
            lines=[line],
            tasks=[mock_task],
            target_field="Text",
            skip_processed=False,
            service=mock_service,
            app_ref=mock_app,
            progress_callback=lambda c, t, m: None,
            control=control
        )
        
        # If it failed silently inside try-except and didn't update text:
        # line.text would remain "Current".
        # If it worked: line.text should be "Processed: Ref:  Text: Current" (assuming None -> empty string)
        
        # check if process_text was called at all
        self.assertTrue(mock_service.process_text.called, "Service should be called even if original_text is None")
        
        # Check if replacement handled None correctly (replaced with empty string)
        args, kwargs = mock_service.process_text.call_args
        
        # process_text(text=..., system_prompt=..., model=...)
        # From code: result_text = current_text
        # current_text = line.text or line.original_text or ""
        # So it should be called with "Current"
        
        called_text = kwargs.get('text', args[0] if args else None)
        self.assertEqual(called_text, "Current")

if __name__ == '__main__':
    unittest.main()

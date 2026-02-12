import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock customtkinter before importing ui modules
sys.modules['customtkinter'] = MagicMock()

from ui.ai_runner import run_ai_pipeline, AITask, AIControl
from app.entity import Line

class TestAILogic(unittest.TestCase):

    def setUp(self):
        self.mock_service = MagicMock()
        # Setup mock to return modified text
        # If prompt contains "translate", return "Translated"
        # else return "Processed"
        def side_effect(text, prompt):
            if "translate" in prompt.lower():
                return f"Translated {text}"
            return f"Processed {text}"
        
        self.mock_service.process_text.side_effect = side_effect

    def test_run_ai_pipeline_basic(self):
        """Test basic flow of pipeline."""
        lines = [
            Line(original_text="Hello", uid="1"),
            Line(original_text="World", uid="2")
        ]
        
        task = AITask(name="test", system_prompt="do translate")
        tasks = [task]
        
        # Test modifying 'text' field
        processed = run_ai_pipeline(
            lines=lines,
            tasks=tasks,
            target_field="text",
            service=self.mock_service,
            app_ref=None # No app ref means no CSV save, which is fine for unit test
        )
        
        self.assertEqual(processed, 2)
        self.assertEqual(lines[0].text, "Translated Hello")
        self.assertEqual(lines[1].text, "Translated World")
        self.assertTrue(lines[0].ai_processed)

    def test_run_ai_pipeline_tts_target(self):
        """Test modifying 'tts_text' field."""
        line = Line(original_text="Hello")
        task = AITask(name="test", system_prompt="process")
        
        run_ai_pipeline(
            lines=[line],
            tasks=[task],
            target_field="tts",
            service=self.mock_service,
            app_ref=None
        )
        
        self.assertEqual(line.tts_text, "Processed Hello")
        # Ensure text is not touched (or is None if implied default)
        self.assertIsNone(line.text)

    def test_skip_processed(self):
        """Test skipping already processed lines."""
        lines = [
            Line(original_text="A", ai_processed=True),
            Line(original_text="B", ai_processed=False)
        ]
        task = AITask(name="t", system_prompt="p")
        
        processed = run_ai_pipeline(
            lines=lines,
            tasks=[task],
            target_field="text",
            service=self.mock_service,
            app_ref=None,
            skip_processed=True
        )
        
        self.assertEqual(processed, 1)
        # First line untouched (mock returns "Processed A", verify it's NOT that)
        self.assertNotEqual(lines[0].text, "Processed A")
        
        # Second line processed
        self.assertEqual(lines[1].text, "Processed B")

    def test_stop_control(self):
        """Test aborting the pipeline via control."""
        lines = [Line(original_text=str(i)) for i in range(10)]
        task = AITask(name="t", system_prompt="p")
        
        control = AIControl()
        
        # Mock callback to stop after 1st item
        def progress_cb(curr, total, msg):
            if curr == 1:
                control.stop()
        
        processed = run_ai_pipeline(
            lines=lines,
            tasks=[task],
            target_field="text",
            service=self.mock_service,
            app_ref=None,
            progress_callback=progress_cb,
            control=control
        )
        
        # Should process 2 items (index 0 and 1, then stop detected at start of 2)
        # Implementation checks `control.is_stopped` at START of loop.
        # i=0 process ok. call cb(0).
        # i=1 cb(1) triggers stop. loop continues to process i=1?
        # Logic: 
        #   for i, line in enumerate:
        #      if stopped: return
        #      cb() -> triggers stop
        #      process...
        
        # So i=0: check stop(F), cb(0), process.
        # i=1: check stop(F), cb(1)->STOP set, process.
        # i=2: check stop(TRUE) -> RETURN.
        
        # Total processed should be 2.
        self.assertEqual(processed, 2)
        self.assertTrue(lines[1].ai_processed)
        self.assertFalse(lines[2].ai_processed)

if __name__ == '__main__':
    unittest.main()

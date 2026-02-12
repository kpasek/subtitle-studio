import unittest
from app.entity import Line

class TestEntityLine(unittest.TestCase):

    def test_line_defaults(self):
        line = Line()
        self.assertEqual(line.original_text, "")
        self.assertIsNone(line.text)
        self.assertIsNone(line.tts_text)
        self.assertTrue(len(line.uid) > 0)

    def test_get_text_fallback(self):
        """Test that get_text() falls back to original_text."""
        line = Line(original_text="Original")
        self.assertEqual(line.get_text(), "Original")
        
        line.text = "Modified"
        self.assertEqual(line.get_text(), "Modified")

    def test_get_tts_text_fallback(self):
        """Test that get_tts_text() falls back correctly."""
        line = Line(original_text="Original")
        
        # Case 1: All None -> Original
        self.assertEqual(line.get_tts_text(), "Original")
        
        # Case 2: Text set -> Text
        line.text = "Text"
        self.assertEqual(line.get_tts_text(), "Text")
        
        # Case 3: TTS set -> TTS
        line.tts_text = "TTS"
        self.assertEqual(line.get_tts_text(), "TTS")

    def test_set_text_logic(self):
        """Test setting text logic (reset to None if same as original)."""
        line = Line(original_text="Original")
        
        # Change to new
        line.set_text("New")
        self.assertEqual(line.text, "New")
        
        # Change back to Original
        line.set_text("Original")
        self.assertIsNone(line.text)

    def test_set_tts_text_logic(self):
        """Test setting tts_text logic (reset to None if same as parent text)."""
        line = Line(original_text="Original", text="Text")
        
        # Change to new
        line.set_tts_text("Audio")
        self.assertEqual(line.tts_text, "Audio")
        
        # Change back to Text (parent)
        line.set_tts_text("Text")
        self.assertIsNone(line.tts_text)

    def test_calculate_cps_simple(self):
        """Test simple CPS calculation."""
        line = Line(original_text="A" * 10) # 10 chars
        line.audio_duration = 1.0
        
        # 10 chars / 1 sec = 10 CPS
        self.assertAlmostEqual(line.calculate_cps(), 10.0)

    def test_calculate_cps_zero_duration(self):
        line = Line(original_text="Text")
        line.audio_duration = 0.0
        self.assertEqual(line.calculate_cps(), 0.0)

    def test_calculate_cps_with_pauses(self):
        """Test CPS with punctuation pause adjustment."""
        # "Hello, world." -> stripped to "Hello, world" (len 12)
        # short pauses: ',' (1) -> 0.4s
        # long pauses: '.' (0 - because stripped) -> 0.0s
        # total pause logic deduction: 0.4s
        
        text = "Hello, world."
        line = Line(original_text=text)
        line.audio_duration = 2.0 
        
        # denom = 2.0 - 0.4 = 1.6
        # result = 12 / 1.6 = 7.5
        expected_cps = 7.5
        
        self.assertAlmostEqual(line.calculate_cps(), expected_cps)

if __name__ == '__main__':
    unittest.main()

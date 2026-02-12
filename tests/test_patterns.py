import unittest
from app.entity import Line, PatternItem
from app.utils import apply_remove_patterns, apply_replace_patterns

class TestPatterns(unittest.TestCase):

    def test_remove_pattern(self):
        """Test simple remove pattern logic."""
        lines = [
            Line(original_text="[Sound] Hello", text=None),
            Line(original_text="Hello World")
        ]
        
        # Pattern to remove [.*] content
        pat = PatternItem(pattern=r"\[[^\]]*\]", replace="", enabled=True)
        
        result_lines = apply_remove_patterns(lines, [pat])
        
        # Check first line
        self.assertEqual(result_lines[0].text.strip(), "Hello")
        # Check untouched line (text should remain None/Original logic)
        # Note: apply_remove_patterns sets line.text even if no change?
        # Let's check implementation. Implementation: `line.set_text(s)`
        # If s == original, set_text sets it to None.
        self.assertIsNone(result_lines[1].text)
        
    def test_remove_pattern_whole_line(self):
        """Test removing a line completely prevents it from being in output if logic dictates, 
           NOTE: current logic appends updated line. If empty, what happens?"""
        # Logic says: if remove_empty and not s.strip(): continue.
        
        lines = [
            Line(original_text="[Music]", uid="1"),
            Line(original_text="Dialogue", uid="2")
        ]
        
        pat = PatternItem(pattern=r"\[.*\]", replace="", enabled=True)
        
        result_lines = apply_remove_patterns(lines, [pat], remove_empty=True)
        
        self.assertEqual(len(result_lines), 1)
        self.assertEqual(result_lines[0].uid, "2")

    def test_replace_pattern_tts(self):
        """Test replace patterns applied to TTS text."""
        line = Line(original_text="I can't do that.", tts_text=None)
        
        # Pattern: replace 'can\'t' with 'cannot'
        pat = PatternItem(pattern=r"can't", replace="cannot", enabled=True)
        
        apply_replace_patterns([line], [pat])
        
        # Now apply_replace_patterns updates the text (and tts inherits)
        self.assertEqual(line.get_tts_text(), "I cannot do that.")
        # text should update too
        self.assertEqual(line.get_text(), "I cannot do that.")

    def test_replace_pattern_chaining(self):
        """Test multiple patterns applied in order."""
        line = Line(original_text="hello world", tts_text="hello world")
        
        p1 = PatternItem(pattern=r"hello", replace="hi", enabled=True)
        p2 = PatternItem(pattern=r"world", replace="earth", enabled=True)
        
        apply_replace_patterns([line], [p1, p2])
        
        self.assertEqual(line.get_tts_text(), "hi earth")

    def test_disabled_pattern(self):
        """Test that disabled patterns are ignored."""
        line = Line(original_text="Test", tts_text="Test")
        pat = PatternItem(pattern=r"Test", replace="Passed", enabled=False)
        
        apply_replace_patterns([line], [pat])
        
        # Should remain "Test" (which might be None in .tts_text if matches parent)
        self.assertEqual(line.get_tts_text(), "Test")

if __name__ == '__main__':
    unittest.main()

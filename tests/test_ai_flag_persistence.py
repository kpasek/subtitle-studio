import unittest
from app.entity import Line, PatternItem
from app.utils import apply_remove_patterns, apply_replace_patterns

class TestAIFlagPersistence(unittest.TestCase):
    def test_flag_persistence_during_replace(self):
        # Setup line with AI flag
        line = Line(original_text="Hello World")
        line.text = "Hello AI"
        line.ai_processed = True
        
        # Setup pattern
        pat = PatternItem(pattern="AI", replace="Universe", case_sensitive=True, enabled=True)
        print(f"DEBUG: Pattern: {pat}")
        
        # Apply
        apply_replace_patterns([line], [pat])
        print(f"DEBUG: Line text after: {line.text}")
        
        # Verify text changed
        self.assertEqual(line.text, "Hello Universe")
        # Verify flag persisted
        self.assertTrue(line.ai_processed, "AI Processed flag should persist after pattern replacement")

    def test_flag_persistence_during_remove(self):
        line1 = Line(original_text="Keep me")
        line1.ai_processed = True
        
        line2 = Line(original_text="Delete me")
        line2.ai_processed = True
        
        # Pattern to make the text empty thus removing the line
        pat = PatternItem(pattern="Delete me", replace="", case_sensitive=False, enabled=True)
        
        # Apply remove (behaves as filter)
        filtered = apply_remove_patterns([line1, line2], [pat])
        
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].original_text, "Keep me")
        self.assertTrue(filtered[0].ai_processed, "AI Processed flag should persist after filtering")

if __name__ == '__main__':
    unittest.main()

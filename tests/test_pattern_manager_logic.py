import unittest
from unittest.mock import MagicMock, patch
from app.entity import PatternItem, Line
from app.patterns import gather_active_patterns, apply_patterns

class TestPatternManagerLogic(unittest.TestCase):
    def test_gather_active_patterns(self):
        """Test gathering enabled patterns only."""
        p1 = PatternItem("a", "b", True, enabled=True)
        p2 = PatternItem("c", "d", True, enabled=False)
        p3 = PatternItem("e", "f", True, enabled=True)
        
        custom_remove = [p1, p2]
        custom_replace = [p3]
        
        rem, rep = gather_active_patterns(custom_remove, custom_replace)
        
        self.assertIn(p1, rem)
        self.assertNotIn(p2, rem)
        self.assertIn(p3, rep)

    @patch('app.patterns.apply_remove_patterns')
    @patch('app.patterns.apply_replace_patterns')
    def test_apply_patterns_integration(self, mock_replace, mock_remove):
        """Test the high level function orchestration."""
        mock_app = MagicMock()
        mock_app.lines = [Line("test")]
        
        # Setup builtins
        mock_app.builtin_remove = [PatternItem("br", "", False)]
        mock_app.builtin_remove_state = [MagicMock()]
        mock_app.builtin_remove_state[0].get.return_value = True
        
        mock_app.custom_remove = [PatternItem("cr", "", False, enabled=True)]
        mock_app.custom_replace = []
        
        # Setup mocks return
        mock_remove.return_value = mock_app.lines
        
        apply_patterns(mock_app)
        
        # Verify remove called with merged lists
        mock_remove.assert_called()
        args, _ = mock_remove.call_args
        patterns_passed = args[1]
        self.assertEqual(len(patterns_passed), 2) # 1 builtin + 1 custom
        
        # Verify replace called
        mock_replace.assert_called()
        
        # Verify UI update
        mock_app._update_subtitle_panel_content.assert_called()

if __name__ == '__main__':
    unittest.main()

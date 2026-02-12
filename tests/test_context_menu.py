import unittest
from unittest.mock import MagicMock, patch
import sys
import types

# Create mocks for modules
ctk_mock = MagicMock()

# Define a dummy class for CTkFrame to avoid MagicMock inheritance issues
class DummyFrame:
    def __init__(self, *args, **kwargs):
        pass
    def pack(self, *args, **kwargs): pass
    def grid(self, *args, **kwargs): pass
    def grid_rowconfigure(self, *args, **kwargs): pass
    def grid_columnconfigure(self, *args, **kwargs): pass
    def bind(self, *args, **kwargs): pass
    def config(self, *args, **kwargs): pass
    def configure(self, *args, **kwargs): pass
    def destroy(self): pass
    def winfo_exists(self): return True
    def cget(self, key): return ""

ctk_mock.CTkFrame = DummyFrame
app_io_mock = MagicMock()
app_patterns_mock = MagicMock()
app_project_mock = MagicMock()
app_update_mock = MagicMock()
app_formatter_mock = MagicMock()
app_entity_mock = MagicMock()
audio_verification_mock = MagicMock()

# Patch sys.modules
sys.modules['customtkinter'] = ctk_mock
sys.modules['app.io'] = app_io_mock
sys.modules['app.patterns'] = app_patterns_mock
sys.modules['app.project'] = app_project_mock
sys.modules['app.update'] = app_update_mock
sys.modules['app.formatter'] = app_formatter_mock
sys.modules['app.entity'] = app_entity_mock
sys.modules['audio.verification_manager'] = audio_verification_mock

# Now we can attempt to import app.subtitles
# We might need to mock tkinter too if it's used at module level
import tkinter as tk
from tkinter import ttk

# Now import the class
from app.subtitles import SubtitlePanel

class TestContextLogic(unittest.TestCase):
    
    def test_show_context_menu(self):
        """Test _show_context_menu logic using the real class."""
        
        # Instantiate with mocks
        master = MagicMock()
        app = MagicMock()
        
        # Ensure ctk widget classes return mocks that don't fail
        ctk_mock.CTkButton.return_value = MagicMock()
        ctk_mock.CTkLabel.return_value = MagicMock()
        ctk_mock.CTkFrame.return_value = MagicMock() 
        ctk_mock.CTkEntry.return_value = MagicMock()
        ctk_mock.CTkSegmentedButton.return_value = MagicMock()
        ctk_mock.CTkScrollbar.return_value = MagicMock()
        
        # Mock treeview
        with patch('tkinter.ttk.Treeview') as mock_tree_cls:
             mock_tree = mock_tree_cls.return_value
             
             # Create instance
             panel = SubtitlePanel(master, app)
             
             # Override tree with our mock for easier assertions
             panel.tree = mock_tree
             
             # Mock tk attribute for Menu creation
             panel.tk = MagicMock()
             
             # Mock methods to avoid side effects
             panel.on_tree_select = MagicMock()
             panel.generate_selected_dialogs = MagicMock()
             panel.verify_selected_dialogs = MagicMock()
             panel.open_ai_runner_selected = MagicMock()
             panel.delete_selected_dialogs = MagicMock()
             panel.delete_selected_rows = MagicMock()
             panel.restore_selected_values = MagicMock()
             panel.set_selected_status = MagicMock()
             
             # Setup state
             panel.generate_button.cget.return_value = "normal"
             panel.app.view_mode.get.return_value = "Napisy"
             panel.app.selected_line_index = 0
             panel.tree.selection.return_value = ("item1",)
             panel.tree.identify_row.return_value = "item1"
             
             event = MagicMock()
             event.y = 100
             event.x_root = 0
             event.y_root = 0
             
             # Run method
             with patch('tkinter.Menu') as mock_menu_cls:
                 panel._show_context_menu(event)
                 
                 # 1. Verify on_tree_select called (Fix for Copy Row bug)
                 panel.on_tree_select.assert_called_with(None)
                 panel.tree.selection_set.assert_called_with("item1")
                 
                 # 2. Verify AI menu item exists
                 mock_menu = mock_menu_cls.return_value
                 # Retrieve all calls to add_command
                 calls = mock_menu.add_command.call_args_list
                 labels = [c.kwargs.get('label', '') for c in calls]
                 
                 print("Menu items found:", labels)
                 
                 ai_found = any("✨ Zadania SI" in l for l in labels)
                 self.assertTrue(ai_found, "Opcja '✨ Zadania SI' powinna być w menu")
                 
                 copy_found = any("Kopiuj linię" in l for l in labels)
                 self.assertTrue(copy_found, "Opcja 'Kopiuj linię' powinna być w menu")

if __name__ == '__main__':
    unittest.main()

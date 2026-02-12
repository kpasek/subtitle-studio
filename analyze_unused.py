import ast
import os
import re

IGNORED_DIRS = {'.git', '.venv', '__pycache__', 'tests', 'build', 'dist'}
IGNORED_FILES = {'analyze_unused.py', 'setup.py'}

def get_python_files(root_dir):
    py_files = []
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for file in files:
            if file.endswith('.py') and file not in IGNORED_FILES:
                py_files.append(os.path.join(root, file))
    return py_files

def get_defined_functions(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            tree = ast.parse(f.read(), filename=file_path)
        except SyntaxError:
            return []
    
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith('_'): # Ignore private/dunder
                functions.append(node.name)
    return functions

def check_usage(func_name, files):
    count = 0
    pattern = re.compile(r'\b' + re.escape(func_name) + r'\b')
    for file_path in files:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # This is a naive check, it counts definition as usage too usually, 
            # but we want to know if it appears *more* than the definition.
            # However, exact count is hard with regex vs AST. 
            # Let's just count matches.
            matches = len(pattern.findall(content))
            count += matches
            if count > 1: # If found more than once (assuming one is def), likely used
                return True
    return False # Found 0 or 1 time

def main():
    root = '.'
    files = get_python_files(root)
    definitions = {} # {func_name: [file_paths]}

    # Gather definitions
    all_funcs = []
    for file in files:
        funcs = get_defined_functions(file)
        for f in funcs:
            all_funcs.append((f, file))

    print(f"Checking {len(all_funcs)} functions in {len(files)} files...")

    unused_candidates = []
    for func_name, file_path in all_funcs:
        # Ignore common override methods or standard callbacks if possible, but keep simple for now
        if func_name in ['__init__', 'run', 'start', 'stop', 'setup', 'update']:
            continue
            
        if not check_usage(func_name, files):
             unused_candidates.append((file_path, func_name))

    for file, func in unused_candidates:
        print(f"Unused? {file} :: {func}")

if __name__ == '__main__':
    main()

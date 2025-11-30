import os
from git import Repo, Actor
from pathlib import Path


class GitManager:
    def __init__(self, project_dir: Path):
        self.repo_dir = project_dir
        self.txt_file = project_dir / "subtitles.txt"
        self.repo = None

    def init_or_load(self):
        if not (self.repo_dir / ".git").exists():
            self.repo = Repo.init(self.repo_dir)
            # Konfiguracja dummy user, żeby git nie krzyczał o brak emaila
            with self.repo.config_writer() as git_config:
                git_config.set_value('user', 'email', 'subtitle@studio.local')
                git_config.set_value('user', 'name', 'Subtitle Studio')
        else:
            self.repo = Repo(self.repo_dir)

    def stage_file(self, content: str):
        """Zapisuje tekst do pliku, aby git mógł wykryć zmiany."""
        with open(self.txt_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.repo.index.add([str(self.txt_file)])

    def has_changes(self):
        return self.repo.is_dirty(untracked_files=True)

    def get_diff_stats(self):
        """Zwraca statystyki zmian względem HEAD."""
        if not self.repo.head.is_valid():
            return {"insertions": len(open(self.txt_file, encoding='utf-8').readlines()), "deletions": 0}

        diff = self.repo.index.diff(self.repo.head.commit)
        # GitPython diff jest złożony, dla prostoty wyciągnijmy diff tekstowy
        try:
            # Porównanie worktree z HEAD
            t = self.repo.head.commit.tree
            diff_text = self.repo.git.diff(t, self.txt_file, stat=True)
            return diff_text  # String z podsumowaniem np. "1 file changed, 2 insertions(+)"
        except:
            return "Brak danych o różnicach."

    def get_full_diff(self):
        if not self.repo.head.is_valid(): return "Pierwszy commit (wszystko nowe)."
        return self.repo.git.diff(self.repo.head.commit, self.txt_file)

    def commit(self, message: str):
        self.repo.index.commit(message)
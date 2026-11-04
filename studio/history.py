"""Explicit cleanup of app-owned history and media, never external exports."""
from pathlib import Path
import shutil
from werkzeug.exceptions import Conflict


class History:
    def __init__(self, workspace, jobs, imports):
        self.workspace = Path(workspace).resolve()
        self.jobs, self.imports = jobs, imports

    def roots(self):
        roots = [self.workspace/name for name in ('jobs', 'imports', 'uploads')]
        for root in roots:
            if root.resolve() != root or root.parent != self.workspace:
                raise ValueError('資料目錄指向其他位置，已停止清除。')
        return roots

    def blocked(self):
        return (any(x['status'] in ('queued', 'running') for x in self.jobs.items.values())
                or any(x['status'] in ('queued', 'running') for x in self.imports.items.values())
                or bool(self.jobs.inflight or self.imports.inflight or self.jobs.processes or self.imports.processes))

    def stats(self):
        with self.jobs.lock, self.imports.lock:
            size = files = assets = 0
            for root in self.roots():
                if not root.exists():
                    continue
                if root.name == 'uploads':
                    assets = sum(1 for p in root.iterdir() if p.is_dir())
                pending = [root]
                while pending:
                    for path in pending.pop().iterdir():
                        if path.is_symlink() or not path.resolve().is_relative_to(root):
                            continue
                        if path.is_dir():
                            pending.append(path)
                        else:
                            try:
                                size += path.stat().st_size; files += 1
                            except FileNotFoundError:
                                pass
            return dict(jobs=len(self.jobs.items), imports=len(self.imports.items), assets=assets,
                        files=files, bytes=size, can_clear=not self.blocked())

    def clear(self):
        with self.jobs.lock, self.imports.lock:
            if self.blocked():
                raise Conflict('仍有生成或下載作業，請等候完成或取消後再清除。')
            before = self.stats()
            for root in self.roots():
                root.mkdir(exist_ok=True)
                for path in list(root.iterdir()):
                    # Validate each resolved target before recursive deletion.
                    target = path.resolve()
                    if target == root or not target.is_relative_to(root):
                        raise ValueError('發現目錄外的檔案連結，已停止清除。')
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                    else:
                        shutil.rmtree(path)
                    if root.name == 'jobs':
                        self.jobs.items.pop(path.name, None)
                    elif root.name == 'imports':
                        self.imports.items.pop(path.name, None)
            return dict(cleared=True, freed_bytes=before['bytes'], jobs=before['jobs'],
                        imports=before['imports'], assets=before['assets'])

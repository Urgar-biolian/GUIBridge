"""Independent verifier: Git diff scope + test commands. Trae claims are never proof."""


class Verifier:
    def verify(self, repo_path: str, allow_files: list[str], test_commands: list[str]) -> dict:
        raise NotImplementedError("S3")
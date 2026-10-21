"""Check that install-skills.sh copies the same files with and without rsync."""
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "install-skills.sh"


def path_without_rsync(directory):
    """Return a PATH whose commands match the current one, minus rsync."""
    bin_dir = Path(directory) / "bin"
    bin_dir.mkdir()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isdir(entry):
            continue
        for name in os.listdir(entry):
            link = bin_dir / name
            if name != "rsync" and not link.exists():
                link.symlink_to(Path(entry) / name)
    return str(bin_dir)


def snapshot(directory):
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(Path(directory).rglob("*"))
        if path.is_file()
    }


class CopyWithoutRsyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / "source"
        skill = self.source / "demo"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text("canonical\n")
        (skill / "references" / "guide.md").write_text("guide\n")
        self.no_rsync = path_without_rsync(root)

    def run_install(self, target, *mode, path=None):
        env = dict(os.environ)
        if path is not None:
            env["PATH"] = path
        return subprocess.run(
            ["bash", str(SCRIPT), "--source", str(self.source), "--target", str(target),
             "--skill", "demo", *mode],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
        )

    def seeded_target(self, name):
        target = Path(self.temp.name) / name / "skills"
        installed = target / "demo"
        installed.mkdir(parents=True)
        (installed / "SKILL.md").write_text("local edit\n")
        (installed / "local-only.md").write_text("local\n")
        return target

    def test_rsync_is_not_on_the_test_path(self):
        self.assertIsNone(shutil.which("rsync", path=self.no_rsync))

    def stub_command(self, name, body):
        """Inject a failure into one real filesystem command on the fallback path."""
        real_command = shutil.which(name)
        self.assertIsNotNone(real_command)
        stub = Path(self.no_rsync) / name
        stub.unlink()
        stub.write_text("#!/bin/bash\nset -eu\n" + body.replace("REAL_COMMAND", shlex.quote(real_command)))
        stub.chmod(0o755)

    def assert_original_restored(self, target, before, inode):
        self.assertEqual(snapshot(target), before)
        self.assertEqual((target / "demo").stat().st_ino, inode)
        self.assertEqual(list(target.glob(".demo.replace.*")), [])

    def test_failed_staging_copy_preserves_original_installation(self):
        target = self.seeded_target("copy-failure")
        before = snapshot(target)
        inode = (target / "demo").stat().st_ino
        self.stub_command("cp", 'printf "partial copy" > "$3/partial.md"\nexit 23\n')
        result = self.run_install(target, "--replace-existing", path=self.no_rsync)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assert_original_restored(target, before, inode)
        self.assertNotIn("Replaced", result.stdout)

    def test_failed_backup_rename_preserves_original_installation(self):
        target = self.seeded_target("backup-failure")
        before = snapshot(target)
        inode = (target / "demo").stat().st_ino
        self.stub_command("mv", 'case "$2" in */original) exit 23 ;; esac\nexec REAL_COMMAND "$@"\n')
        result = self.run_install(target, "--replace-existing", path=self.no_rsync)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assert_original_restored(target, before, inode)

    def test_failed_promotion_restores_original_installation(self):
        target = self.seeded_target("promotion-failure")
        before = snapshot(target)
        inode = (target / "demo").stat().st_ino
        self.stub_command("mv", 'case "$1" in */replacement) exit 23 ;; esac\nexec REAL_COMMAND "$@"\n')
        result = self.run_install(target, "--replace-existing", path=self.no_rsync)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assert_original_restored(target, before, inode)
        self.assertNotIn("Replaced", result.stdout)

    def test_failed_restore_retains_original_and_reports_recovery_path(self):
        target = self.seeded_target("restore-failure")
        before = snapshot(target / "demo")
        self.stub_command("mv", 'case "$1" in */replacement|*/original) exit 23 ;; esac\nexec REAL_COMMAND "$@"\n')
        result = self.run_install(target, "--replace-existing", path=self.no_rsync)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((target / "demo").exists())
        retained = list(target.glob(".demo.replace.*"))
        self.assertEqual(len(retained), 1)
        original = retained[0] / "original"
        self.assertEqual(snapshot(original), before)
        self.assertIn(str(original), result.stderr)
        self.assertNotIn("Replaced", result.stdout)

    def test_termination_after_backup_restores_original_installation(self):
        target = self.seeded_target("terminated")
        before = snapshot(target)
        inode = (target / "demo").stat().st_ino
        self.stub_command("mv", '''case "$2" in
  */original) REAL_COMMAND "$@"; kill -TERM "$PPID"; exit 0 ;;
esac
exec REAL_COMMAND "$@"
''')
        result = self.run_install(target, "--replace-existing", path=self.no_rsync)
        self.assertNotEqual(result.returncode, 0)
        self.assert_original_restored(target, before, inode)

    def test_each_mode_matches_the_expected_files_without_rsync(self):
        expected = {
            (): {"demo/SKILL.md": b"canonical\n", "demo/references/guide.md": b"guide\n"},
            ("--merge-existing",): {
                "demo/SKILL.md": b"local edit\n",
                "demo/local-only.md": b"local\n",
                "demo/references/guide.md": b"guide\n",
            },
            ("--replace-existing",): {
                "demo/SKILL.md": b"canonical\n",
                "demo/references/guide.md": b"guide\n",
            },
        }
        for mode, files in expected.items():
            with self.subTest(mode=mode):
                label = mode[0].strip("-") if mode else "install"
                target = (
                    Path(self.temp.name) / label / "skills" if not mode else self.seeded_target(label)
                )
                result = self.run_install(target, *mode, path=self.no_rsync)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(snapshot(target), files)

    def test_destination_symlinks_fail_without_external_writes(self):
        for backend, path in (("fallback", self.no_rsync), ("native", None)):
            for location in ("target", "skill", "nested", "dangling"):
                for mode in ("--merge-existing", "--replace-existing"):
                    with self.subTest(backend=backend, location=location, mode=mode):
                        root = Path(self.temp.name) / f"{backend}-{location}-{mode}"
                        root.mkdir()
                        outside = root / "outside"
                        outside.mkdir()
                        sentinel = outside / "sentinel"
                        sentinel.write_text("untouched")
                        target = root / "skills"
                        if location == "target":
                            target.symlink_to(outside, target_is_directory=True)
                        elif location == "skill":
                            target.mkdir()
                            (target / "demo").symlink_to(outside, target_is_directory=True)
                        else:
                            (target / "demo").mkdir(parents=True)
                            destination = outside if location == "nested" else outside / "missing"
                            (target / "demo" / "references").symlink_to(
                                destination, target_is_directory=True,
                            )
                        before = snapshot(outside)
                        result = self.run_install(target, mode, path=path)
                        self.assertNotEqual(result.returncode, 0, result.stdout)
                        self.assertIn("symlink", result.stderr)
                        self.assertEqual(snapshot(outside), before)
                        self.assertFalse((outside / "missing").exists())

    def test_source_destination_overlap_preserves_source(self):
        for path in (self.no_rsync, None):
            for target in (self.source, self.source / "nested", self.source.parent,
                           self.source / "missing" / ".."):
                with self.subTest(path=path, target=target):
                    before = snapshot(self.source)
                    result = self.run_install(target, "--replace-existing", path=path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("overlap", result.stderr)
                    self.assertEqual(snapshot(self.source), before)
                    self.assertFalse((self.source / "nested").exists())

    def test_target_link_with_redundant_components_preserves_external_tree(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "sentinel").write_text("unchanged")
        link = Path(self.temp.name) / "link"
        link.symlink_to(outside, target_is_directory=True)
        for path in (self.no_rsync, None):
            for suffix in ("//", "/./", "/.//."):
                with self.subTest(path=path, suffix=suffix):
                    result = self.run_install(str(link) + suffix, "--replace-existing", path=path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("symlink", result.stderr)
                    self.assertEqual(snapshot(outside), {"sentinel": b"unchanged"})

    @unittest.skipUnless(shutil.which("rsync"), "rsync is not installed")
    def test_fallback_matches_rsync(self):
        for mode in ((), ("--merge-existing",), ("--replace-existing",)):
            with self.subTest(mode=mode):
                label = mode[0].strip("-") if mode else "install"
                with_rsync = self.seeded_target(label + "-rsync") if mode else Path(self.temp.name) / (label + "-rsync")
                without = self.seeded_target(label + "-cp") if mode else Path(self.temp.name) / (label + "-cp")
                self.assertEqual(self.run_install(with_rsync, *mode).returncode, 0)
                self.assertEqual(self.run_install(without, *mode, path=self.no_rsync).returncode, 0)
                self.assertEqual(snapshot(with_rsync), snapshot(without))


if __name__ == "__main__":
    unittest.main()

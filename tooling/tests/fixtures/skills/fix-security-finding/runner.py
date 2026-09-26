import subprocess


def greet(name):
    # seeded finding: user input interpolated into a shell command
    return subprocess.run(f"echo hello {name}", shell=True, capture_output=True, text=True).stdout.strip()

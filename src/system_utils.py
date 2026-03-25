import subprocess


def execute_shell_command(command, cwd):
    process = subprocess.Popen(command.split(),
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               universal_newlines=True,
                               cwd=cwd)
    stdout, stderr = process.communicate()
    return stdout

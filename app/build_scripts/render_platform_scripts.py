"""Render Jinja2 platform scripts for the TransFS RetroNAS testbed Docker image.

Called during `docker build` to produce ready-to-execute shell scripts under
/opt/transfs/platform/retronas/ using the defaults appropriate for a testbed
container.  Runs with the system Python3 available in retronas-docker:latest
(which has Jinja2 via ansible-core).
"""

from jinja2 import Template
import os

TMPL_DIR = '/opt/retronas/ansible/templates'
DEST_DIR = '/opt/transfs/platform/retronas'

VARS = {
    'transfs_install_root': '/opt/transfs',
    'transfs_log_dir': '/var/log/transfs',
    'transfs_python_bin': '/opt/transfs/.venv/bin/python',
}

SCRIPTS = (
    'start_transfs_retronas.sh',
    'transfs_retronas_ctl.sh',
    'configure_retronas.sh',
)

for name in SCRIPTS:
    src = os.path.join(TMPL_DIR, name + '.j2')
    dest = os.path.join(DEST_DIR, name)
    with open(src) as fh:
        rendered = Template(fh.read()).render(**VARS)
    with open(dest, 'w') as fh:
        fh.write(rendered)
    os.chmod(dest, 0o755)
    print(f'Rendered {dest}')

print('All platform scripts rendered successfully.')

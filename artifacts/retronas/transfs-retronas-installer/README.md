# TransFS RetroNAS Installer Bundle

This bundle contains RetroNAS-focused installation assets from the TransFS repository.

## Included assets

- platform/linux/configure_retronas.sh
- platform/linux/start_transfs_retronas.sh
- platform/linux/transfs-retronas.service
- platform/linux/retronas/register_transfs_menu.sh
- platform/linux/retronas/ansible/install_transfs.yml
- platform/linux/retronas/ansible/inventory.example.ini
- platform/linux/retronas/ansible/templates/transfs-retronas.service.j2
- platform/linux/retronas/ansible/templates/transfs-retronas.env.j2

## Default source repository

The generated playbook defaults to:

https://github.com/GlennPegden2/TransFS.git

Override via Ansible vars if needed:

-e transfs_repo_url=<your repo>
-e transfs_repo_version=<branch or tag>

## Register TransFS in RetroNAS Install menu

After copying the playbook/templates into a RetroNAS host, register the menu item:

./platform/linux/retronas/register_transfs_menu.sh

This is idempotent and only adds `transfs` if it is not already present.

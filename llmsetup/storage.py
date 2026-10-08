"""Inspect existing disks. Never create or change a filesystem or partition table."""
from __future__ import annotations
import json
from pathlib import Path
from .core import SetupError, ensure_dir

ALLOWED_FS = {'ext4', 'xfs', 'btrfs'}
MOUNT_AT = Path('/srv/llm-data')
FSTAB = Path('/etc/fstab')
COMMENT = '# llm-postinstall managed existing filesystem (do not edit manually)'


def partition_options(blocks):
    """Only return a fully identifiable, non-root non-system-disk existing filesystem."""
    root_disks = set()
    all_items = []
    def walk(node, top):
        disk = node.get('path') if node.get('type') == 'disk' else top
        if node.get('mountpoint') == '/' or '/' in (node.get('mountpoints') or []):
            root_disks.add(disk)
        all_items.append((node, disk))
        for child in node.get('children', []):
            walk(child, disk)
    for x in blocks.get('blockdevices', []):
        walk(x, x.get('path'))
    # If disk lineage of / is ambiguous (LVM, dm-crypt, RAID), refuse proposals.
    if not root_disks or None in root_disks:
        return []
    result = []
    for node, disk in all_items:
        if (node.get('type') == 'part' and node.get('fstype') in ALLOWED_FS
                and node.get('uuid') and disk not in root_disks
                and disk and not node.get('mountpoint')
                and not any(node.get('mountpoints') or [])):
            result.append({'path': node['path'], 'uuid': node['uuid'],
                           'fs': node['fstype'], 'size': node.get('size', '?'), 'disk': disk})
    return result


def fstab_entry(partition):
    if partition['fs'] not in ALLOWED_FS:
        raise SetupError('Unsupported filesystem')
    if not partition['uuid'] or any(c.isspace() for c in partition['uuid']):
        raise SetupError('Invalid filesystem UUID')
    passno = 0 if partition['fs'] in ('xfs', 'btrfs') else 2
    return (f"UUID={partition['uuid']}\t{MOUNT_AT}\t{partition['fs']}\t"
            f'defaults,nofail,x-systemd.device-timeout=10s\t0\t{passno}')


def configure_storage(r, ask, choose):
    """Requires interactive typed UUID; deliberately no noninteractive switch."""
    if MOUNT_AT.is_mount():
        print(f'Existing mount {MOUNT_AT} left unchanged')
        return str(MOUNT_AT / 'models')
    r.apt('util-linux')
    p = r.run(['lsblk', '--json', '-o', 'NAME,PATH,TYPE,FSTYPE,UUID,MOUNTPOINT,MOUNTPOINTS,SIZE'], capture=True)
    options = partition_options(json.loads(p.stdout))
    if not options:
        print('No safe unmounted data partition found. Using system SSD; no disk modified.')
        return '/var/lib/llm-stack/models'
    print('\nExisting non-root-disk filesystems (no filesystem will be created):')
    for i, part in enumerate(options, 1):
        print(f"  {i}. {part['path']} {part['size']} {part['fs']} UUID={part['uuid']}")
    if not ask('Mount an existing filesystem for LLM models?'):
        return '/var/lib/llm-stack/models'
    index = choose(f'Select partition [1-{len(options)}]: ').strip()
    if not index.isdigit() or not 1 <= int(index) <= len(options):
        raise SetupError('Invalid partition selection')
    selected = options[int(index)-1]
    typed = choose('Type full partition UUID to authorize the fstab and mount change: ').strip()
    if typed != selected['uuid']:
        raise SetupError('UUID confirmation mismatch. No disk changed.')
    if MOUNT_AT.exists() and (MOUNT_AT.is_symlink() or any(MOUNT_AT.iterdir())):
        raise SetupError('Mount target exists and is not empty; refusing to shadow files')
    current = FSTAB.read_text()
    if f'UUID={selected["uuid"]}' in current or str(MOUNT_AT) in current:
        raise SetupError('Filesystem or destination already appears in fstab; review manually')
    ensure_dir(MOUNT_AT)
    line = fstab_entry(selected)
    new = current.rstrip('\n') + '\n' + COMMENT + '\n' + line + '\n'
    r.write(FSTAB, new, owned=False)  # backup taken by Runner
    try:
        r.run(['mount', str(MOUNT_AT)])
        if not MOUNT_AT.is_mount():
            raise SetupError('Mount did not appear after mount(8)')
    except Exception:
        r.write(FSTAB, current, owned=False)
        raise
    print(f'Mounted existing {selected["fs"]} filesystem at {MOUNT_AT}')
    return str(MOUNT_AT / 'models')

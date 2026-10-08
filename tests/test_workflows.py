import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from llmsetup import cli
from llmsetup import storage
from llmsetup.components import managed
from llmsetup.core import SetupError


class FakeRunner:
    def __init__(self, raw):
        self.raw = raw
        self.commands = []
        self.writes = []
        self.apt_packages = []
    def apt(self, *packages): self.apt_packages += list(packages)
    def run(self, args, **kwargs):
        self.commands.append(args)
        if args[0] == 'lsblk': return mock.Mock(stdout=json.dumps(self.raw))
        return mock.Mock(returncode=0, stdout='')
    def write(self, path, content, owned=True, **kwargs):
        self.writes.append((str(path), content))
        if not owned and str(path) == '/etc/fstab':
            # Test uses patched Path.read_text; do not touch /etc/fstab.
            return True
        return True


class TestStorageWorkflow(unittest.TestCase):
    def setUp(self):
        self.tree = {'blockdevices': [
            {'path':'/dev/sda','type':'disk','children':[{'path':'/dev/sda1','type':'part','fstype':'ext4','uuid':'root','mountpoint':'/'}]},
            {'path':'/dev/sdb','type':'disk','children':[{'path':'/dev/sdb1','type':'part','fstype':'ext4','uuid':'safe-uuid','mountpoint':None}]}
        ]}

    def test_declining_mount_never_writes_fstab(self):
        r = FakeRunner(self.tree)
        with mock.patch.object(storage.MOUNT_AT.__class__, 'is_mount', return_value=False):
            result = storage.configure_storage(r, lambda msg: False, lambda msg: '1')
        self.assertEqual(result, '/var/lib/llm-stack/models')
        self.assertFalse(any(x[0] == '/etc/fstab' for x in r.writes))

    def test_wrong_confirmation_prevents_fstab_modification(self):
        r = FakeRunner(self.tree)
        with mock.patch.object(storage.MOUNT_AT.__class__, 'is_mount', return_value=False):
            with self.assertRaisesRegex(SetupError, 'UUID confirmation mismatch'):
                storage.configure_storage(r, lambda msg: True, lambda msg: '1' if 'Select' in msg else 'wrong-uuid')
        self.assertFalse(any(x[0] == '/etc/fstab' for x in r.writes))
        self.assertFalse(any('mkfs' in ' '.join(c) for c in r.commands))

    def test_no_second_disk_requires_no_prompt(self):
        r = FakeRunner({'blockdevices': self.tree['blockdevices'][:1]})
        with mock.patch.object(storage.MOUNT_AT.__class__, 'is_mount', return_value=False):
            result = storage.configure_storage(r, lambda msg: self.fail('not expected'), lambda msg: self.fail('not expected'))
        self.assertEqual(result, '/var/lib/llm-stack/models')


if __name__ == '__main__': unittest.main()

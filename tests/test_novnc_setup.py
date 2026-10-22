"""Safety and idempotence coverage for noVNC auto-configuration."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from llmsetup import component_novnc_setup as n
from llmsetup.core import SetupError


class PasswordTests(unittest.TestCase):
    def test_legacy_vnc_password_length_is_exactly_eight(self):
        values = [n.generate_vnc_password() for _ in range(12)]
        for value in values:
            self.assertEqual(len(value), 8)
            self.assertTrue(value.isascii())
            self.assertTrue(value.isalnum())
        self.assertGreater(len(set(values)), 1)

    def test_encrypt_filters_invalid_password_before_running_binary(self):
        for v in ('', 'short', 'abcdefghi', 'bad\n1234', 'bad space'):
            with mock.patch.object(n.subprocess, 'run') as proc:
                with self.assertRaises(SetupError): n.encode_vnc_password(v)
                proc.assert_not_called()

    def test_filter_takes_secret_from_stdin_not_args(self):
        password = 'aBC234xy'
        with mock.patch.object(n.subprocess, 'run', return_value=mock.Mock(
            returncode=0, stdout=b'12345678', stderr=b'')) as proc:
            self.assertEqual(n.encode_vnc_password(password), b'12345678')
            args, kwargs = proc.call_args
            self.assertEqual(args[0], ['/usr/bin/tigervncpasswd', '-f'])
            self.assertEqual(kwargs['input'], (password+'\n').encode())
            self.assertNotIn(password, str(args[0]))

    def test_filter_output_invalid_or_error_is_rejected_without_secret(self):
        for returncode, stdout in ((1, b''), (0, b''), (0, b'too-long-encrypted-binary')):
            with mock.patch.object(n.subprocess, 'run', return_value=mock.Mock(
                returncode=returncode, stdout=stdout, stderr=b'ignore')):
                with self.assertRaises(SetupError) as cm:
                    n.encode_vnc_password('abcdefgh')
                self.assertNotIn('abcdefgh', str(cm.exception))

    def test_secure_file_refuses_world_readability(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'secret'
            p.write_text('abcdefgh\n')
            p.chmod(0o644)
            with self.assertRaises(SetupError):
                n._private_file(p, os.getuid(), os.getgid())
            p.chmod(0o600)
            n._private_file(p, os.getuid(), os.getgid())

    def test_secure_file_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'secret'; p.write_text('abcdefgh\n');p.chmod(0o600)
            link=Path(t)/'link';link.symlink_to(p)
            with self.assertRaises(SetupError): n._private_file(link,os.getuid(),os.getgid())

    def test_exclusive_file_never_overwrites(self):
        with tempfile.TemporaryDirectory() as t:
            file=Path(t)/'secret'
            with mock.patch.object(n.os,'fchown',return_value=None):
                n._exclusive_binary(file,b'abcdefgh\n',os.getuid(),os.getgid())
                with self.assertRaises(SetupError):
                    n._exclusive_binary(file,b'XXXXXXXX\n',os.getuid(),os.getgid())
            self.assertEqual(file.read_bytes(),b'abcdefgh\n')
            self.assertEqual(stat.S_IMODE(file.stat().st_mode),0o600)


    def test_provisioning_reuses_credentials_and_does_not_rotate_on_rerun(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            home = root / 'llmvnc'
            home.mkdir()
            clear = root / 'etc' / 'secret'
            binary = home / '.config/tigervnc/passwd'
            owner = mock.Mock(pw_uid=os.getuid(), pw_gid=os.getgid())
            def secure_directory(p, *_):
                p=Path(p)
                p.mkdir(parents=True, exist_ok=True)
                p.chmod(0o700)
            def exclusive_file(p, content, *_):
                p=Path(p)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, 'xb') as stream:
                    stream.write(content)
                p.chmod(0o600)
            with mock.patch.object(n,'VNC_HOME',home), \
                 mock.patch.object(n,'CLEAR_PASS_FILE',clear), \
                 mock.patch.object(n,'VNC_PASS_FILE',binary), \
                 mock.patch.object(n,'CONF_DIR',clear.parent), \
                 mock.patch.object(n,'_ensure_service_identity',return_value=owner), \
                 mock.patch.object(n,'_secure_dir',side_effect=secure_directory), \
                 mock.patch.object(n,'_private_file'), \
                 mock.patch.object(n,'_exclusive_binary',side_effect=exclusive_file), \
                 mock.patch.object(n,'generate_vnc_password',return_value='ABCD2345') as make, \
                 mock.patch.object(n,'encode_vnc_password',return_value=b'12345678') as encoder:
                first=n.provision_credentials(None)
                self.assertEqual(first,clear)
                self.assertEqual(clear.read_text(),'ABCD2345\n')
                self.assertEqual(binary.read_bytes(),b'12345678')
                second=n.provision_credentials(None)
                self.assertEqual(second,clear)
                self.assertEqual(make.call_count,1)
                self.assertEqual(encoder.call_count,2)
                self.assertEqual(clear.read_text(),'ABCD2345\n')


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.r=mock.Mock()
        self.r.run.return_value=mock.Mock(returncode=1)

    def test_dedicated_service_and_root_credential_not_in_units(self):
        with mock.patch.object(n,'provision_credentials',return_value=n.CLEAR_PASS_FILE), \
             mock.patch.object(n,'_preflight_ports'), \
             mock.patch.object(n.Path,'is_file',return_value=True), \
             mock.patch.object(n,'unit') as unit:
            n.configure_novnc(self.r,{},None)
        self.assertIn('tigervnc-standalone-server', self.r.apt.call_args.args)
        self.assertIn('novnc', self.r.apt.call_args.args)
        self.assertEqual(unit.call_count,2)
        vnc_name=unit.call_args_list[0].args[1]
        vnc_text=unit.call_args_list[0].args[2]
        web_name=unit.call_args_list[1].args[1]
        web_text=unit.call_args_list[1].args[2]
        self.assertEqual(vnc_name,'llm-novnc-vnc.service')
        self.assertEqual(web_name,'llm-novnc.service')
        self.assertIn('User=llmvnc',vnc_text)
        self.assertIn(' -fg :2 ',vnc_text)
        self.assertIn(' -localhost yes ',vnc_text)
        self.assertIn('-SecurityTypes VncAuth',vnc_text)
        self.assertIn('-rfbauth /var/lib/llmvnc/.config/tigervnc/passwd',vnc_text)
        self.assertIn('127.0.0.1:6080 127.0.0.1:5902',web_text)
        self.assertIn('Requires=llm-novnc-vnc.service',web_text)
        self.assertNotIn('novnc-vnc-password',vnc_text+web_text)

    def test_conflicting_proxy_port_fails_without_service_restart(self):
        self.r.run.return_value=mock.Mock(returncode=3)
        with mock.patch.object(n,'_loopback_port_busy',side_effect=lambda p:p==6080):
            with self.assertRaises(SetupError):
                n._preflight_ports(self.r)

    def test_known_active_proxy_port_allowed_on_rerun(self):
        self.r.run.return_value=mock.Mock(returncode=0)
        with mock.patch.object(n,'_loopback_port_busy',return_value=True):
            n._preflight_ports(self.r)
        self.assertEqual(self.r.run.call_count,2)


class SecureDirTests(unittest.TestCase):
    def test_own_directory_with_loose_mode_is_tightened(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'conf'
            path.mkdir(mode=0o755)
            os.chmod(path, 0o755)
            n._secure_dir(path, os.getuid(), os.getgid())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

    def test_foreign_owner_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SetupError):
                n._secure_dir(tmp, os.getuid() + 1, os.getgid())


if __name__=='__main__':
    unittest.main()

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


if __name__=='__main__':
    unittest.main()

"""Fast, offline tests for the laptop CLI:  python3 -m unittest discover cli/tests"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["BIRDLISTENER_NONINTERACTIVE"] = "1"

from birdlistener import cloudinit, geocode, prompts, site  # noqa: E402


def plan(node="wall") -> cloudinit.NodePlan:
    return cloudinit.NodePlan(
        node=node, hostname="birdwall" if node == "wall" else "birdpi", user="pi", password="pw",
        ssh_pubkey="ssh-ed25519 AAAA test", timezone="America/Los_Angeles", wifi_ssid='My "Net"',
        wifi_password="p@ss: word", country="US",
        node_env={"BL_NODE": node, "BL_MQTT_PASS": "abc"}, repo_url="https://x/y.git", repo_ref="main")


class CloudInit(unittest.TestCase):
    def test_user_data_shape(self):
        ud = cloudinit.render_user_data(plan("wall"))
        self.assertTrue(ud.startswith("#cloud-config\n"))
        self.assertIn('hostname: "birdwall"', ud)
        self.assertIn("    spi: true", ud)
        self.assertIn("path: /etc/bird-listener/node.env", ud)
        self.assertIn("      BL_MQTT_PASS=abc", ud)
        self.assertIn("install.sh", ud)
        self.assertIn("ssh_pwauth: false", ud)

    def test_window_has_no_spi(self):
        ud = cloudinit.render_user_data(plan("window"))
        self.assertNotIn("spi: true", ud)

    def test_network_config_quotes_awkward_strings(self):
        nc = cloudinit.render_network_config(plan())
        self.assertIn('"My \\"Net\\"":', nc)
        self.assertIn('password: "p@ss: word"', nc)
        self.assertIn('regulatory-domain: "US"', nc)

    def test_yaml_parses_if_pyyaml_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("no pyyaml")
        doc = yaml.safe_load(cloudinit.render_user_data(plan()))
        self.assertEqual(doc["users"][0]["name"], "pi")
        self.assertEqual(doc["rpi"]["interfaces"]["spi"], True)
        self.assertIn("BL_MQTT_PASS=abc", doc["write_files"][0]["content"])
        net = yaml.safe_load(cloudinit.render_network_config(plan()))
        self.assertEqual(net["network"]["wifis"]["wlan0"]["access-points"]['My "Net"']["password"], "p@ss: word")


class Geocode(unittest.TestCase):
    def test_parse_coords(self):
        self.assertEqual(geocode.parse_coords("37.77, -122.44"), (37.77, -122.44))
        self.assertEqual(geocode.parse_coords("37.7726;-122.4476"), (37.7726, -122.4476))
        self.assertIsNone(geocode.parse_coords("Oakland, CA"))
        self.assertIsNone(geocode.parse_coords("95, 200"))


class Prompts(unittest.TestCase):
    def test_flag_value_wins(self):
        self.assertEqual(prompts.ask("x", flag="--x", value="v", default="d"), "v")

    def test_default_used_when_noninteractive(self):
        self.assertEqual(prompts.ask("x", flag="--x", value=None, default="d"), "d")

    def test_missing_names_the_flag(self):
        with self.assertRaises(SystemExit) as cm:
            prompts.ask("WiFi name", flag="--wifi-ssid", value=None)
        self.assertIn("--wifi-ssid", str(cm.exception))

    def test_confirm_noninteractive_uses_default(self):
        self.assertFalse(prompts.confirm("erase?", default=False))
        self.assertTrue(prompts.confirm("erase?", yes=True))


class Site(unittest.TestCase):
    def test_roundtrip_and_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            site.SITE_DIR = Path(d)
            site.SITE_FILE = Path(d) / "site.json"
            data = site.load()
            data["mqtt_pass"] = "secret"
            data["wifi_ssid"] = "net"
            path = site.save(data)
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            again = site.load()
            self.assertEqual(again["mqtt_pass"], "secret")
            self.assertEqual(site.redacted(again)["mqtt_pass"], "<set>")
            self.assertEqual(site.redacted(again)["wifi_ssid"], "net")


class Parser(unittest.TestCase):
    def test_every_command_has_help(self):
        from birdlistener.cli import build_parser
        ap = build_parser()
        for cmd in ("flash", "geocode", "art", "doctor", "update", "site"):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    ap.parse_args([cmd, "--help"])
            self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()

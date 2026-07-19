#!/usr/bin/env bash
#
# Configure automatic security updates on a bird-listener node.
#
# Run ON THE PI, from inside the repo (it needs sudo, so run it interactively):
#     bash auto-updates.sh
#
# Works on both nodes and adapts to what each one's apt archives actually offer:
#
#   birdpi   (Debian trixie, arm64)  -> has a real Debian-Security suite, so we
#                                       take security + stable-updates ONLY, and
#                                       leave the Raspberry Pi archive (firmware,
#                                       raspi-utils, rpi-eeprom) for manual runs.
#   birdwall (Raspbian trixie, armv6l) -> has NO separate security suite. Raspbian
#                                       rebuilds Debian and folds security fixes
#                                       into plain `stable`, so the only way to
#                                       get patches automatically is to allow the
#                                       whole Raspbian stable archive.
#
# Idempotent: safe to re-run. Every file it writes is namespaced 52-bird-listener
# so it never fights raspi-config or a distro upgrade.
set -euo pipefail

# Reboot automatically when an update needs it (kernel, libc, systemd).
# Both nodes are headless appliances and both services come back on their own,
# so this defaults on -- without it, kernel fixes sit installed but inactive.
AUTO_REBOOT="${AUTO_REBOOT:-true}"
AUTO_REBOOT_TIME="${AUTO_REBOOT_TIME:-04:30}"

echo "==> bird-listener automatic security updates"
echo "    host:        $(hostname)"
echo "    os:          $(. /etc/os-release && echo "$PRETTY_NAME") ($(uname -m))"

# 1) Discover which origins this box actually has ----------------------------
# Matching on origin+label strings that don't exist here would silently install
# nothing, which is the worst outcome: it looks configured but isn't.
policy="$(apt-cache policy)"
ORIGINS=()
NOTES=()

if grep -q 'l=Debian-Security' <<<"$policy"; then
  ORIGINS+=('"origin=Debian,codename=${distro_codename}-security,label=Debian-Security";')
  NOTES+=("Debian-Security  -> security fixes only (the important one)")
fi
if grep -q 'a=stable-updates' <<<"$policy"; then
  ORIGINS+=('"origin=Debian,codename=${distro_codename}-updates,label=Debian";')
  NOTES+=("Debian stable-updates -> tzdata, urgent non-security fixes")
fi
if grep -q 'o=Raspbian' <<<"$policy"; then
  ORIGINS+=('"origin=Raspbian,codename=${distro_codename},label=Raspbian";')
  NOTES+=("Raspbian stable  -> ALL stable updates (no security-only suite exists)")
fi

if [ ${#ORIGINS[@]} -eq 0 ]; then
  echo "!! No recognised apt origins found. Refusing to write a config that would" >&2
  echo "   silently install nothing. Check 'apt-cache policy'." >&2
  exit 1
fi

echo "==> Origins this node will auto-upgrade from:"
printf '      - %s\n' "${NOTES[@]}"
echo "    (the Raspberry Pi Foundation archive -- firmware, rpi-eeprom, raspi-utils --"
echo "     is deliberately NOT auto-upgraded; run those by hand, see below)"

# 2) Packages ----------------------------------------------------------------
if ! dpkg -s unattended-upgrades >/dev/null 2>&1; then
  echo "==> Installing unattended-upgrades…"
  sudo apt-get update
  sudo apt-get install -y unattended-upgrades
else
  echo "==> unattended-upgrades already installed"
fi

# 3) Turn the periodic timers on ---------------------------------------------
# apt-daily.timer / apt-daily-upgrade.timer already exist on both nodes; these
# knobs are what actually make them do something.
echo "==> Writing /etc/apt/apt.conf.d/20auto-upgrades…"
sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<'EOF'
// Managed by bird-listener/auto-updates.sh
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

# 4) The policy itself -------------------------------------------------------
echo "==> Writing /etc/apt/apt.conf.d/52-bird-listener-unattended…"
{
  echo '// Managed by bird-listener/auto-updates.sh -- do not hand-edit.'
  echo 'Unattended-Upgrade::Origins-Pattern {'
  printf '        %s\n' "${ORIGINS[@]}"
  echo '};'
  echo ''
  echo '// Keep the SD card from filling with old kernels/deps.'
  echo 'Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";'
  echo 'Unattended-Upgrade::Remove-Unused-Dependencies "true";'
  echo ''
  echo '// Never let a package prompt block an unattended run; keep our edited'
  echo '// conffiles (we have hand-tuned config on these boxes).'
  echo 'Unattended-Upgrade::MinimalSteps "true";'
  echo 'Dpkg::Options {"--force-confdef";"--force-confold";};'
  echo ''
  if [ "$AUTO_REBOOT" = "true" ]; then
    echo "Unattended-Upgrade::Automatic-Reboot \"true\";"
    echo "Unattended-Upgrade::Automatic-Reboot-WithUsers \"false\";"
    echo "Unattended-Upgrade::Automatic-Reboot-Time \"${AUTO_REBOOT_TIME}\";"
  else
    echo 'Unattended-Upgrade::Automatic-Reboot "false";'
  fi
} | sudo tee /etc/apt/apt.conf.d/52-bird-listener-unattended >/dev/null

sudo systemctl enable --now apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true

# 5) Prove it parses and would actually pick things up ------------------------
# --dry-run exits non-zero on a malformed config, so this is a real check.
echo "==> Dry run (this is what it would install tonight):"
sudo unattended-upgrades --dry-run --debug 2>&1 \
  | grep -iE "^(Allowed origins|Packages that will be upgraded|Package .* upgradable)" \
  | sed 's/^/      /' || true

cat <<EOF

==> Done on $(hostname).

  Check status any time:
      systemctl list-timers apt-daily-upgrade.timer
      sudo unattended-upgrades --dry-run --debug | head -30
      cat /var/log/unattended-upgrades/unattended-upgrades.log
      ls /var/run/reboot-required 2>/dev/null && echo "reboot pending"

  NOT covered by automation, run these by hand every month or so:
      sudo apt update && sudo apt full-upgrade    # incl. Raspberry Pi firmware
EOF

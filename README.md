# NetWatch

Lightweight network monitor and auto-repair tool for Apple Silicon Macs.

Runs in the background, detects common network issues, and attempts
automated fixes — so you don't have to.

## Install

**Option 1 — Download .app**
1. Download `NetWatch-macOS-arm64.zip` from [Releases](../../releases)
2. Unzip and drag `NetWatch.app` to `/Applications`
3. Double-click to open

**Option 2 — Homebrew**
```bash
brew tap cyrillical00/netwatch
brew install --cask netwatch
```

## What It Does

| Issue | Detection | Auto-Fix |
|-------|-----------|----------|
| Wi-Fi drops | Interface + power state check | Toggle Wi-Fi power |
| DNS failure | Multi-host resolution check | Flush cache → Fallback DNS → Wi-Fi toggle |
| Gateway unreachable | Ping default gateway | DHCP renew → Wi-Fi toggle |
| Packet loss / high latency | 5-packet ping with RTT | DHCP renew → Wi-Fi toggle |
| Captive portal | HTTP check against Apple endpoint | Alerts user (manual sign-in required) |

## Privacy

- Admin password stored **in memory only** — never written to disk
- No telemetry, no cloud, no LLM
- Logs written to `~/Library/Logs/NetWatch/netwatch.log`

## Permissions

NetWatch requires admin access to:
- Flush DNS cache (`dscacheutil`, `mDNSResponder`)
- Renew DHCP lease (`ipconfig`)
- Toggle Wi-Fi power (`networksetup`)

You'll be prompted once at launch. The session clears on exit.

## Build From Source

```bash
git clone https://github.com/cyrillical00/netwatch
cd netwatch
pip3 install -r requirements.txt
./build.sh
```

## Simulated Failure Tests

```bash
# Simulate DNS failure — point to bad DNS
sudo networksetup -setdnsservers en0 192.0.2.1

# Restore DNS
sudo networksetup -setdnsservers en0 Empty
```

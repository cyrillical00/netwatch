cask "netwatch" do
  version "1.0.0"
  # Set to the SHA-256 printed by build.sh for the zip you attach to the release.
  # Until it is replaced, installation fails rather than skipping verification.
  sha256 "REPLACE_WITH_SHA256_OF_NetWatch-macOS-arm64.zip"

  url "https://github.com/cyrillical00/netwatch/releases/download/v#{version}/NetWatch-macOS-arm64.zip"
  name "NetWatch"
  desc "macOS network monitor and auto-repair tool for Apple Silicon"
  homepage "https://github.com/cyrillical00/netwatch"

  app "NetWatch.app"

  zap trash: [
    "~/Library/Logs/NetWatch",
    "~/Library/Preferences/com.cyrillical00.netwatch.plist",
  ]
end

cask "netwatch" do
  version "1.0.0"
  sha256 :no_check  # Replace with actual SHA after first release

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

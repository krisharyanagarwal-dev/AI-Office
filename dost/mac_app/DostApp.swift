import Cocoa
import AVFoundation
import WebKit

// Dost — a small native window that shows the pet page served by pet_server.py.
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    let petURL = URL(string: "http://127.0.0.1:8787/")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        let config = WKWebViewConfiguration()
        config.mediaTypesRequiringUserActionForPlayback = []
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.setValue(false, forKey: "drawsBackground")

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 680),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Dost"
        window.contentView = webView
        window.center()
        window.setFrameAutosaveName("DostWindow")
        window.makeKeyAndOrderFront(nil)
        requestMicrophone()
        load()
    }

    // Ask macOS for microphone access up front so Dost appears in
    // Privacy & Security > Microphone and the prompt shows once.
    func requestMicrophone() {
        AVCaptureDevice.requestAccess(for: .audio) { granted in
            NSLog("Dost microphone access granted: \(granted)")
        }
    }

    func load() {
        webView.load(URLRequest(url: petURL))
    }

    // Retry when the local server is not up yet (e.g. after login).
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self.load() }
    }

    // Grant the page's microphone request (macOS still asks the user once).
    @available(macOS 12.0, *)
    func webView(_ webView: WKWebView,
                 requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo,
                 type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        decisionHandler(.grant)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()

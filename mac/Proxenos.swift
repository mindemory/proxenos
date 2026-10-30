// Proxenos for the Mac: the local page in a window of its own, with a Dock icon and menus, and
// no browser around it. It shows http://127.0.0.1:4747 (scripts/install-app.sh keeps that
// running) and opens everything else where it belongs: links to other sites in the browser,
// whatsapp:, slack: and mailto: links in their apps, downloads in ~/Downloads, and the Ask
// page's file picker as the system's. It adds nothing to the page and keeps nothing of its own.
//
// Built by scripts/build-mac-app.sh with the Swift compiler from Xcode's command line tools.

import Cocoa
import WebKit

let home = URL(string: "http://127.0.0.1:4747/app")!

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate,
    WKDownloadDelegate
{
    var window: NSWindow!
    var web: WKWebView!

    func applicationDidFinishLaunching(_ note: Notification) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()  // the page's settings survive a restart
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        window.title = "Proxenos"
        // Closing only hides it, so the Dock icon can bring it back (a released window crashed the app).
        window.isReleasedWhenClosed = false
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(red: 0.055, green: 0.063, blue: 0.075, alpha: 1)
        window.contentView = web
        window.setFrameAutosaveName("Proxenos")
        if window.frame.origin == .zero { window.center() }
        window.makeKeyAndOrderFront(nil)
        NSApp.mainMenu = menu()
        load()
    }

    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { window.makeKeyAndOrderFront(nil) }
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { false }

    @objc func load() { web.load(URLRequest(url: home)) }

    @objc func reload() { web.reload() }

    // The page isn't up yet (just after login, or while it restarts): say so, and try again.
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        webView.loadHTMLString(
            """
            <body style="background:#0e1013;color:#c9ccd3;font:15px -apple-system;display:grid;place-items:center;height:100vh;margin:0">
            <div style="text-align:center">Proxenos is starting…<br><span style="color:#7d828c;font-size:13px">It runs in the background from login; this page tries again every few seconds.</span></div>
            <script>setTimeout(() => location.href = "\(home.absoluteString)", 4000)</script></body>
            """, baseURL: nil)
    }

    // Only the page itself stays in the window; anything else opens where it belongs.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload { return decisionHandler(.download) }
        guard let url = action.request.url else { return decisionHandler(.cancel) }
        if url.scheme == "about" || url.host == home.host { return decisionHandler(.allow) }
        NSWorkspace.shared.open(url)
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping @MainActor (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }

    // A link meant for a new tab (target="_blank"): open it outside, not in a second window.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    // The Ask page's "attach a screenshot".
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping @MainActor ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    // A draft downloaded as a file goes to ~/Downloads, under its own name.
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping @MainActor (URL?) -> Void) {
        let folder = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        var target = folder.appendingPathComponent(suggestedFilename)
        var n = 1
        while FileManager.default.fileExists(atPath: target.path) {
            let stem = (suggestedFilename as NSString).deletingPathExtension
            let ext = (suggestedFilename as NSString).pathExtension
            target = folder.appendingPathComponent("\(stem)-\(n)" + (ext.isEmpty ? "" : ".\(ext)"))
            n += 1
        }
        completionHandler(target)
    }

    // The menus a Mac app is expected to have, so copy, paste and ⌘R work in the page.
    func menu() -> NSMenu {
        let bar = NSMenu()
        func add(_ title: String, _ items: [NSMenuItem]) {
            let item = NSMenuItem()
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            item.submenu = menu
            bar.addItem(item)
        }
        func item(_ title: String, _ action: Selector?, _ key: String, _ target: AnyObject? = nil) -> NSMenuItem {
            let entry = NSMenuItem(title: title, action: action, keyEquivalent: key)
            entry.target = target
            return entry
        }
        add("Proxenos", [
            item("Hide Proxenos", #selector(NSApplication.hide(_:)), "h"),
            .separator(),
            item("Quit Proxenos", #selector(NSApplication.terminate(_:)), "q"),
        ])
        add("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "Z"),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ])
        add("View", [
            item("Home", #selector(load), "0", self),
            item("Reload", #selector(reload), "r", self),
        ])
        add("Window", [
            item("Minimize", #selector(NSWindow.miniaturize(_:)), "m"),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ])
        return bar
    }
}

MainActor.assumeIsolated {  // top-level code runs on the main thread
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.regular)
    app.run()
}

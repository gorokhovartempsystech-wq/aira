import AppKit
import Foundation
import Sparkle
import UniformTypeIdentifiers
import WebKit

final class Desktop: NSObject, NSApplicationDelegate, SPUUpdaterDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandlerWithReply {
    private var window: NSWindow!
    private var web: WKWebView?
    private var process: Process?
    private var origin: URL?
    private var closing = false
    private var installAfterShutdown: (() -> Void)?
    private var updater: SPUStandardUpdaterController?
    private var result: Int32 = 0
    private var dataDirectory: URL?
    private let smoke = CommandLine.arguments.contains("--smoke")

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 800),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "AIRA"
        window.delegate = self
        window.center()
        window.contentView = NSTextField(labelWithString: "Запускаем AIRA…")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        do { try launch() } catch { failed("Не удалось запустить AIRA. Проверьте настройки и журнал.") }
    }

    private func launch() throws {
        let fm = FileManager.default
        let arguments = CommandLine.arguments
        let defaultData = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("AIRA Mac Pilot", isDirectory: true)
        let data: URL
        if let index = arguments.firstIndex(of: "--data-dir"), arguments.indices.contains(index + 1) {
            data = URL(fileURLWithPath: arguments[index + 1], isDirectory: true).standardizedFileURL
        } else {
            data = defaultData
        }
        dataDirectory = data
        try fm.createDirectory(at: data, withIntermediateDirectories: true,
                               attributes: [.posixPermissions: 0o700])
        let config = Bundle.main.resourceURL!.appendingPathComponent("license-origin.txt")
        guard fm.fileExists(atPath: config.path) else {
            failed("В установщике отсутствует адрес сервера лицензий. Переустановите AIRA.")
            return
        }
        let log = data.appendingPathComponent("aira.log")
        if !fm.fileExists(atPath: log.path) {
            guard fm.createFile(atPath: log.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
                throw CocoaError(.fileWriteUnknown)
            }
        }
        let handle = try FileHandle(forWritingTo: log)
        try handle.seekToEnd()
        let payload = Bundle.main.resourceURL!.appendingPathComponent("payload", isDirectory: true)
        let process = Process()
        let pipe = Pipe()
        process.executableURL = payload.appendingPathComponent("python/bin/python3.12")
        process.arguments = ["-I", "-B", "-u", payload.appendingPathComponent("serve.py").path, data.path]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = pipe
        process.standardError = handle
        process.terminationHandler = { [weak self] child in
            DispatchQueue.main.async { self?.exited(child.terminationStatus) }
        }
        try process.run()
        self.process = process
        try pipe.fileHandleForWriting.close()
        try handle.close()
        DispatchQueue.global().async { [weak self] in
            let bytes = pipe.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async { self?.load(bytes) }
        }
    }

    private func load(_ bytes: Data) {
        guard !closing, process?.isRunning == true,
              let connection = try? JSONSerialization.jsonObject(with: bytes) as? [String: String],
              let address = connection["origin"], let base = URL(string: address),
              base.scheme == "http", base.host == "127.0.0.1", base.port != nil,
              let token = connection["sessionToken"], token.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              let json = String(data: bytes, encoding: .utf8) else {
            if !closing, process?.isRunning == true { failed("Не удалось подключиться к локальному серверу AIRA.") }
            return
        }
        origin = base
        let scripts = WKUserContentController()
        scripts.addScriptMessageHandler(self, contentWorld: .page, name: "aira")
        let source = """
        (() => {
          const connection = \(json.trimmed);
          // WebKit serializes Origin as null for same-origin POST with no-referrer.
          // Keep only the loopback origin as Referer and retain the verified Origin.
          const pageFetch = window.fetch.bind(window);
          window.fetch = (url, options) => {
            if (typeof url === 'string' && url.startsWith(connection.origin + '/') &&
                options?.mode === 'same-origin' && options.referrerPolicy === 'no-referrer') {
              return pageFetch(url, {...options, referrerPolicy: 'origin'});
            }
            return pageFetch(url, options);
          };
          const call = (op, fields = {}) => window.webkit.messageHandlers.aira.postMessage({op, ...fields});
          const decode = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
          const encode = bytes => {
            let text = '';
            for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192));
            return btoa(text);
          };
          const save = (name, bytes, kind) => call('save', {name, kind, bytes: encode(bytes)});
          window.airaHost = {
            connection: async () => connection,
            openDocx: async () => {
              const value = await call('open');
              if (!value) return null;
              return {name:value.name, bytes:decode(value.bytes), tooBig:value.tooBig};
            },
            saveDocx: (name, bytes) => save(name, bytes, 'docx'),
            saveFile: (name, bytes) => save(name, bytes, 'txt'),
            checkUpdates: () => call('updates'),
          };
        })();
        """
        scripts.addUserScript(WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let settings = WKWebViewConfiguration()
        settings.userContentController = scripts
        settings.websiteDataStore = .nonPersistent()
        let web = WKWebView(frame: .zero, configuration: settings)
        web.navigationDelegate = self
        web.uiDelegate = self
        self.web = web
        window.contentView = web
        if smoke {
            DispatchQueue.main.asyncAfter(deadline: .now() + 25) { [weak self] in
                if let self, !self.closing { self.failed("Тест загрузки окна не завершился.") }
            }
        }
        web.load(URLRequest(url: base.appendingPathComponent("aira", isDirectory: true)))
        if !smoke {
            updater = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: self, userDriverDelegate: nil)
            let item = NSMenuItem(title: "Проверить обновления…", action: #selector(checkUpdates(_:)), keyEquivalent: "")
            item.target = self
            NSApp.mainMenu?.items.first?.submenu?.insertItem(item, at: 0)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url, let origin,
              url.scheme == origin.scheme, url.host == origin.host, url.port == origin.port else {
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        failed("Не удалось загрузить окно AIRA (WebKit \((error as NSError).code)).")
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard smoke else { return }
        Task { @MainActor [weak self] in
            let value = try? await webView.callAsyncJavaScript("""
                for (let i = 0; i < 100; i++) {
                  if (document.querySelector('input[aria-label="Лицензионный ключ"]')) return true;
                  await new Promise(resolve => setTimeout(resolve, 100));
                }
                return false;
                """, arguments: [:], in: nil, contentWorld: .page)
            guard let self else { return }
            if (value as? Bool) == true { print("PASS WKWebView loaded the activation screen") }
            else { self.result = 1 }
            NSApp.terminate(nil)
        }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        guard frame.isMainFrame, frame.securityOrigin.host == "127.0.0.1",
              frame.securityOrigin.port == origin?.port else { completionHandler(nil); return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png, .jpeg]
        panel.beginSheetModal(for: window) { answer in
            completionHandler(answer == .OK ? panel.urls : nil)
        }
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let frame = message.frameInfo.securityOrigin
        guard message.frameInfo.isMainFrame, frame.protocol == "http", frame.host == "127.0.0.1",
              frame.port == origin?.port, let body = message.body as? [String: Any] else {
            replyHandler(nil, "access_denied")
            return
        }
        if body["op"] as? String == "updates" {
            guard updater != nil else { replyHandler(nil, "updater_unavailable"); return }
            updater?.checkForUpdates(nil)
            replyHandler(true, nil)
        } else if body["op"] as? String == "open" {
            let panel = NSOpenPanel()
            panel.allowedContentTypes = [UTType(filenameExtension: "docx")!]
            panel.beginSheetModal(for: window) { answer in
                guard answer == .OK, let url = panel.url else { replyHandler(NSNull(), nil); return }
                do {
                    let file = try FileHandle(forReadingFrom: url)
                    defer { try? file.close() }
                    let bytes = try file.read(upToCount: 32 * 1024 * 1024 + 1) ?? Data()
                    let tooBig = bytes.count > 32 * 1024 * 1024
                    replyHandler(["name": url.lastPathComponent,
                                  "bytes": tooBig ? "" : bytes.base64EncodedString(), "tooBig": tooBig], nil)
                } catch { replyHandler(nil, "file_read_failed") }
            }
        } else if body["op"] as? String == "save", let kind = body["kind"] as? String,
                  ["docx", "txt"].contains(kind), let name = body["name"] as? String,
                  let encoded = body["bytes"] as? String, encoded.utf8.count <= 45 * 1024 * 1024,
                  let bytes = Data(base64Encoded: encoded), bytes.count <= 32 * 1024 * 1024 {
            let panel = NSSavePanel()
            panel.allowedContentTypes = [UTType(filenameExtension: kind)!]
            panel.nameFieldStringValue = (name as NSString).lastPathComponent
            panel.beginSheetModal(for: window) { answer in
                guard answer == .OK, let url = panel.url else { replyHandler(["saved": false], nil); return }
                do {
                    try bytes.write(to: url, options: .atomic)
                    replyHandler(["saved": true, "path": url.path], nil)
                } catch { replyHandler(nil, "file_write_failed") }
            }
        } else { replyHandler(nil, "invalid_file_operation") }
    }

    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                 untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        guard process?.isRunning == true else { return false }
        installAfterShutdown = installHandler
        // Returning lets the main actor finish before the async save/close starts.
        DispatchQueue.main.async { NSApp.terminate(nil) }
        return true
    }

    @objc private func checkUpdates(_ sender: Any?) {
        updater?.checkForUpdates(sender)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        NSApp.terminate(nil)
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let process, process.isRunning else { return .terminateNow }
        guard !closing else { return .terminateCancel }
        // Startup retains its resources until the readiness handshake.
        guard let web else { return .terminateCancel }
        closing = true
        Task { @MainActor [weak self] in
            let value = try? await web.callAsyncJavaScript(
                "return await (window.AIRA?.prepareToClose() ?? true)",
                arguments: [:], in: nil, contentWorld: .page
            )
            if (value as? Bool) == true { process.interrupt() }
            else {
                self?.closing = false
            }
        }
        return .terminateCancel
    }

    private func exited(_ status: Int32) {
        process = nil
        if closing {
            if status != 0 { result = 1 }
            if status == 0, let install = installAfterShutdown {
                installAfterShutdown = nil
                install()
            } else if status != 0, installAfterShutdown != nil {
                closing = false
                let alert = NSAlert()
                alert.messageText = "Обновление отложено: AIRA не подтвердила штатное завершение работы."
                alert.runModal()
            } else { NSApp.terminate(nil) }
        } else { failed("AIRA остановилась. Подробности в aira.log.") }
    }

    private func failed(_ message: String) {
        result = 1
        if smoke { FileHandle.standardError.write(Data((message + "\n").utf8)) }
        if !smoke {
            let alert = NSAlert()
            alert.messageText = message
            alert.runModal()
        }
        if let process, process.isRunning {
            closing = true
            process.interrupt()
        } else { NSApp.terminate(nil) }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if smoke {
            if let dataDirectory {
                try? Data("\(result)\n".utf8).write(to: dataDirectory.appendingPathComponent("smoke-result.txt"), options: .atomic)
            }
            exit(result)
        }
    }
}

private extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}

let app = NSApplication.shared
let desktop = Desktop()
app.setActivationPolicy(.regular)
app.delegate = desktop
let mainMenu = NSMenu()
let rootItem = NSMenuItem()
let applicationMenu = NSMenu()
applicationMenu.addItem(withTitle: "Закрыть AIRA", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
rootItem.submenu = applicationMenu
mainMenu.addItem(rootItem)
app.mainMenu = mainMenu
app.run()

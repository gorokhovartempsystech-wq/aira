# Windows ML prototype

The local Word-review worker runs the bundled ONNX engine and adds prototype findings through the existing standalone-question extension. Each finding points to source spans validated against the current DOCX snapshot. Clicking a quote focuses that source span in the editor.

The separately staged demo installer is named `AIRA-Setup-0.2.2-ml-demo.exe`. Its SHA-256 is `7185aff1d54dded578adc8e14d5685abf29b3a27a99c775545cd9d4e1652b854`. It uses a separate installation directory and data directory. The installer was assembled using the earlier Windows demo stage and tested with a synthetic UPS DOCX. This branch ports the integration and navigation changes onto the repository baseline.

The installed demo imported the document, completed local analysis and scrolled from the UPS acceptance card to its test-mode paragraph. The original UPS specification still encounters unread parts in the Word reader. The installer and the model weights are distributed as local build artifacts.

// Dost Fleet content script (optional page integration).
// Runs on all pages at document_idle. Can be used to surface fleet status
// on the current page or relay messages between the page and the popup.

(function () {
  "use strict";

  const FLEET_API = "http://localhost:8083/metrics";

  // Minimal integration point: expose a small badge on the page when the
  // fleet is reachable. Safe to leave disabled by uncommenting below.
  //
  // async function pingFleet() {
  //   try {
  //     const res = await fetch(FLEET_API, { cache: "no-store" });
  //     if (res.ok) {
  //       const data = await res.json();
  //       console.log("[Dost Fleet] metrics:", data);
  //     }
  //   } catch (err) {
  //     // Fleet not reachable from this context; silently ignore.
  //   }
  // }
  // pingFleet();

  // Listen for messages from the popup / background (placeholder).
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === "DOST_FLEET_PING") {
      sendResponse({ ok: true });
      return true;
    }
  });
})();

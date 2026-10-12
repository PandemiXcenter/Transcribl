import { errorMessageFromPayload } from "./api.js";
import { reviewPanel, state } from "./context.js";
import { clearGlobalError, showGlobalError } from "./dom.js";
import { captureDrafts } from "./drafts.js";

export function initializeDownloads() {
  reviewPanel.addEventListener("click", async (event) => {
    const link = event.target instanceof Element ? event.target.closest(".export-menu a[download]") : null;
    if (!link) return;
    event.preventDefault();
    if (link.getAttribute("aria-busy") === "true") return;
    if (state.reviewMutationPending) {
      showGlobalError("Wait for the current save to finish before exporting.");
      return;
    }
    if (link.closest("#review-editor") && captureDrafts().size &&
        !window.confirm("This export includes saved edits only. Export without your unsaved changes?")) return;
    clearGlobalError();
    const label = link.textContent;
    link.textContent = "Preparing download…";
    link.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(link.href, { credentials: "same-origin" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(errorMessageFromPayload(payload, response.status));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const download = document.createElement("a");
      const disposition = response.headers.get("content-disposition") || "";
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
      const plainName = disposition.match(/filename="([^"]+)"/i)?.[1];
      download.href = url;
      download.download = encodedName ? decodeURIComponent(encodedName) : plainName || link.href.split("/").at(-1);
      document.body.append(download);
      download.click();
      download.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      link.closest("details").open = false;
    } catch (error) {
      showGlobalError(error.message || "The export could not be downloaded. Try again.");
    } finally {
      link.textContent = label;
      link.removeAttribute("aria-busy");
    }
  });
}

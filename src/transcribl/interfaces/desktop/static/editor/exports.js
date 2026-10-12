import {
  createElement
} from "./dom.js";

export function exportUrl(jobId, format) {
  return `/backend/api/jobs/${encodeURIComponent(jobId)}/export.${format}`;
}

export function configureExportLinks(jobId, links) {
  for (const [format, link] of Object.entries(links)) {
    if (link) {
      link.href = jobId ? exportUrl(jobId, format) : "#";
    }
  }
}

export function makeExportMenu(jobId) {
  const menu = createElement("details", "export-menu article-export-menu");
  const summary = createElement("summary", "secondary-button compact-control", "Export");
  const options = createElement("div", "export-menu-options");
  options.setAttribute("aria-label", "Export article");
  const formats = [
    ["pdf", "LaTeX PDF (.pdf)"],
    ["tex", "LaTeX source (.tex)"],
    ["md", "Markdown (.md)"],
    ["txt", "Plain text (.txt)"],
  ];
  for (const [format, label] of formats) {
    const link = createElement("a", "", label);
    link.href = exportUrl(jobId, format);
    link.download = "";
    options.append(link);
  }
  menu.append(summary, options);
  return menu;
}

export function costBreakdown(cost) {
  const text = cost.total == null
    ? "Recorded cost unavailable"
    : `Recorded cost ≈ ${Number(cost.total).toFixed(4)} ${cost.currency}`;
  const breakdown = createElement("details", "cost-breakdown");
  const summary = createElement("summary", "", text);
  summary.title = "Show token usage and pricing details";
  breakdown.append(summary);
  breakdown.append(createElement("p", "",
    `${Number(cost.input_tokens).toLocaleString()} input tokens · ` +
    `${Number(cost.output_tokens).toLocaleString()} output tokens. ` +
    `Prices checked: ${(cost.pricing_checked_on || []).join(", ")}. ` +
    (cost.notes || []).join(" ")));
  return breakdown;
}

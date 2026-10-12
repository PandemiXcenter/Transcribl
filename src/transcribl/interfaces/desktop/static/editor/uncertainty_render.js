import {
  uncertaintyGroupEmpty,
  uncertaintyGroupList
} from "./context.js";
import {
  asText,
  createElement
} from "./dom.js";

export function renderUncertaintyGroupList(groups) {
  uncertaintyGroupList.replaceChildren();
  uncertaintyGroupEmpty.hidden = groups.length > 0;
  for (const group of groups) {
    const item = createElement("article", "uncertainty-group-item");
    item.setAttribute("role", "listitem");
    const heading = createElement("div", "uncertainty-group-heading");
    heading.append(
      createElement("h3", "", asText(group.source_term, "Uncertain passage")),
      createElement(
        "span",
        "uncertainty-count",
        `${Number(group.occurrence_count) || 1} ${
          Number(group.occurrence_count) === 1 ? "occurrence" : "occurrences"
        }`,
      ),
    );
    const details = [];
    if (group.proposed_translation) {
      details.push(`Model: ${asText(group.proposed_translation)}`);
    }
    const pages = Array.isArray(group.page_numbers)
      ? group.page_numbers.map(Number).filter(Number.isInteger)
      : [];
    if (pages.length) {
      details.push(`Physical ${pages.length === 1 ? "page" : "pages"} ${pages.join(", ")}`);
    }
    const open = createElement(
      "button",
      "text-button uncertainty-group-open",
      "Review first occurrence",
    );
    open.type = "button";
    open.dataset.action = "open-uncertainty-group";
    open.dataset.uncertaintyId = asText(group.first_uncertainty_id);
    item.append(heading);
    if (details.length) {
      item.append(createElement("p", "uncertainty-group-details", details.join(" · ")));
    }
    item.append(createElement("p", "uncertainty-group-reason", asText(group.reason)), open);
    uncertaintyGroupList.append(item);
  }
}


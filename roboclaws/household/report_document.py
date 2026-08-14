from __future__ import annotations

import html

from roboclaws.core.rerun import render_rerun_panel
from roboclaws.household.report_styles import report_css


def image_lightbox_markup() -> str:
    return (
        '<div class="image-lightbox" data-image-lightbox hidden aria-hidden="true">'
        '<button type="button" class="lightbox-close" data-lightbox-close '
        'aria-label="Close image review">Close</button>'
        '<div class="lightbox-dialog" role="dialog" aria-modal="true" '
        'aria-label="Image review">'
        '<img alt="">'
        '<p class="lightbox-caption" data-lightbox-caption></p>'
        "</div></div>"
    )


def wrap_report_html(
    body: str,
    *,
    extra_css: str = "",
    rerun_command: str | None = None,
    title: str = "MolmoSpaces Cleanup Pilot",
) -> str:
    rerun_panel = render_rerun_panel(rerun_command)
    image_lightbox = image_lightbox_markup()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
{report_css(extra_css=extra_css)}  </style>
</head>
<body><main>{rerun_panel}{body}</main>{image_lightbox}<script>
(() => {{
  const buttons = Array.from(document.querySelectorAll("[data-report-tab-button]"));
  const panels = Array.from(document.querySelectorAll("[data-report-tab]"));
  if (!buttons.length || !panels.length) return;
  document.documentElement.classList.add("tabs-ready");
  const validTabs = new Set(panels.map((panel) => panel.dataset.reportTab));
  function activate(tab, options = {{}}) {{
    if (!validTabs.has(tab)) tab = panels[0].dataset.reportTab;
    for (const button of buttons) {{
      const selected = button.dataset.reportTabButton === tab;
      button.setAttribute("aria-selected", String(selected));
    }}
    let selectedPanel = panels[0];
    for (const panel of panels) {{
      const selected = panel.dataset.reportTab === tab;
      panel.hidden = !selected;
      if (selected) selectedPanel = panel;
    }}
    if (options.scroll === true && selectedPanel) {{
      requestAnimationFrame(() => {{
        selectedPanel.scrollIntoView({{ block: "start", inline: "nearest" }});
      }});
    }}
  }}
  for (const button of buttons) {{
    button.addEventListener("click", () => {{
      const tab = button.dataset.reportTabButton;
      activate(tab, {{ scroll: true }});
      history.replaceState(null, "", `#${{tab}}`);
    }});
  }}
  const hash = location.hash.replace("#", "");
  activate(validTabs.has(hash) ? hash : panels[0].dataset.reportTab);
}})();
(() => {{
  const lightbox = document.querySelector("[data-image-lightbox]");
  if (!lightbox) return;
  const lightboxImage = lightbox.querySelector("img");
  const caption = lightbox.querySelector("[data-lightbox-caption]");
  const closeButton = lightbox.querySelector("[data-lightbox-close]");
  let returnFocus = null;

  function openLightbox(link) {{
    returnFocus = link;
    lightboxImage.src = link.href;
    lightboxImage.alt = link.querySelector("img")?.alt || "";
    caption.textContent = link.dataset.lightboxCaption || lightboxImage.alt || "";
    lightbox.hidden = false;
    lightbox.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    closeButton?.focus();
  }}

  function closeLightbox() {{
    lightbox.hidden = true;
    lightbox.setAttribute("aria-hidden", "true");
    lightboxImage.removeAttribute("src");
    document.body.style.overflow = "";
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
    returnFocus = null;
  }}

  document.addEventListener("click", (event) => {{
    const link = event.target.closest?.("[data-lightbox-image]");
    if (link) {{
      event.preventDefault();
      openLightbox(link);
      return;
    }}
    if (!lightbox.hidden && event.target === lightbox) closeLightbox();
    if (!lightbox.hidden && event.target.closest?.("[data-lightbox-close]")) closeLightbox();
  }});

  document.addEventListener("keydown", (event) => {{
    if (event.key === "Escape" && !lightbox.hidden) closeLightbox();
  }});
}})();
</script></body>
</html>
"""

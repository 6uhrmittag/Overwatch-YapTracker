// Copying chat lines (#221). A selection over several lines copies one "Name: message" per
// line; time, channel chip and buttons aren't text you want. Inside one line, the browser's
// own copy is right (a word or two).

// The rule, without the page, so it can be tested (tests/test_text_select.py).
function ytCopyText(lines) {
  return lines
    .map((line) => [line.name, line.text].map((part) => (part || "").trim()).filter(Boolean).join(" "))
    .filter(Boolean)
    .join("\n");
}

// The chat lines the selection really covers (not just touches), in page order.
function ytSelectedLines() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return [];
  const range = selection.getRangeAt(0);
  return [...document.querySelectorAll(".yt-line")].filter((line) => {
    const own = document.createRange();
    own.selectNodeContents(line);
    return range.compareBoundaryPoints(Range.END_TO_START, own) < 0 &&
      range.compareBoundaryPoints(Range.START_TO_END, own) > 0;
  });
}

if (typeof document !== "undefined") {
  // Live offers "Snap these" for a selection over 2+ lines (#325): each .yt-snap-source hears
  // which of its lines are selected, once the selection has settled.
  let settle = null;
  document.addEventListener("selectionchange", () => {
    clearTimeout(settle);
    settle = setTimeout(() => {
      const lines = ytSelectedLines();
      document.querySelectorAll(".yt-snap-source").forEach((box) => {
        const ids = lines.filter((line) => box.contains(line)).map((line) => line.id);
        if (box.dataset.ytSelected === ids.join()) return;
        box.dataset.ytSelected = ids.join();
        box.dispatchEvent(new CustomEvent("ytselected", { detail: ids }));
      });
    }, 250);
  });
  document.addEventListener("copy", (event) => {
    const lines = ytSelectedLines();
    if (lines.length < 2) return;
    event.clipboardData.setData("text/plain", ytCopyText(lines.map((line) => ({
      name: line.querySelector(".yt-line-name")?.textContent,
      text: line.querySelector(".yt-line-text")?.textContent,
    }))));
    event.preventDefault();
  });
}
if (typeof module !== "undefined") module.exports = { ytCopyText };

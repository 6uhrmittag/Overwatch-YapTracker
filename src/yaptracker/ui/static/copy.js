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

if (typeof document !== "undefined") {
  document.addEventListener("copy", (event) => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    const lines = [...document.querySelectorAll(".yt-line")].filter((line) => {
      const own = document.createRange();  // really inside, not just touching its edge
      own.selectNodeContents(line);
      return range.compareBoundaryPoints(Range.END_TO_START, own) < 0 &&
        range.compareBoundaryPoints(Range.START_TO_END, own) > 0;
    });
    if (lines.length < 2) return;
    event.clipboardData.setData("text/plain", ytCopyText(lines.map((line) => ({
      name: line.querySelector(".yt-line-name")?.textContent,
      text: line.querySelector(".yt-line-text")?.textContent,
    }))));
    event.preventDefault();
  });
}
if (typeof module !== "undefined") module.exports = { ytCopyText };

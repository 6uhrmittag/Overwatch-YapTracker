// Live chat follows new yaps (#166). Runs in the browser, because only the browser knows
// whether a scroll came from you or from new lines: only *your* scrolling up stops following,
// growing content never does. Scrolled up and new yaps came in: the "New yaps" pill shows.

// The rules, without the page, so they can be tested (tests/test_follow_js.py).
function ytFollowStep(state, event) {
  const next = { ...state, scroll: false };
  if (event.type === "user-scroll") {  // wheel, touch, keys, dragging the bar
    next.on = event.atBottom;
    if (next.on) next.pill = false;
  } else if (event.type === "grew") {  // new lines, or a line got taller
    if (state.on) next.scroll = true;
    else next.pill = true;
  } else if (event.type === "cleared") {  // a new match: start at the bottom again
    next.on = true;
    next.pill = false;
    next.scroll = true;
  } else if (event.type === "pill") {
    next.on = true;
    next.pill = false;
    next.scroll = true;
  }
  return next;
}

function ytFollow(box) {
  if (box.ytFollowing) return;
  box.ytFollowing = true;
  const inner = box.firstElementChild;
  const pill = box.parentElement.querySelector(".yt-new-yaps");
  let state = { on: true, pill: false, scroll: false };
  let userUntil = 0;  // scroll events until then are the user's
  const atBottom = () => box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const apply = (event) => {
    state = ytFollowStep(state, event);
    if (pill) pill.classList.toggle("yt-hidden", !state.pill);
    if (state.scroll) requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
  };
  const byUser = () => { userUntil = Date.now() + 800; };
  for (const type of ["wheel", "touchmove", "keydown", "pointerdown"]) {
    box.addEventListener(type, byUser, { passive: true });
  }
  box.addEventListener("scroll", () => {
    if (Date.now() < userUntil) apply({ type: "user-scroll", atBottom: atBottom() });
  });
  new ResizeObserver(() => apply({ type: "grew" })).observe(inner);
  new MutationObserver(() => {
    apply({ type: inner.children.length ? "grew" : "cleared" });
  }).observe(inner, { childList: true });
  if (pill) pill.addEventListener("click", () => apply({ type: "pill" }));
  apply({ type: "cleared" });
}

if (typeof document !== "undefined") {
  const scan = () => document.querySelectorAll(".yt-follow").forEach(ytFollow);
  new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
  scan();
}
if (typeof module !== "undefined") module.exports = { ytFollowStep };

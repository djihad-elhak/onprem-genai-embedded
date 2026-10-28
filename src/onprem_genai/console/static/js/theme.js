// Applied before first paint so a dark-mode choice never flashes light.
(function () {
  try {
    var t = localStorage.getItem("oge-theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* storage unavailable: follow the system */ }
})();

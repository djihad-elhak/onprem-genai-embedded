// Applied before first paint. Light (the HDS White palette) is the default; a dark choice is remembered.
(function () {
  var t = "light";
  try { if (localStorage.getItem("oge-theme") === "dark") t = "dark"; } catch (e) { /* storage unavailable */ }
  document.documentElement.setAttribute("data-theme", t);
})();

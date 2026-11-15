// Order page (admin): ask before submitting a form that has data-confirm="question".
document.addEventListener("submit", function (event) {
  var question = event.target.getAttribute && event.target.getAttribute("data-confirm");
  if (question && !window.confirm(question)) event.preventDefault();
});

// A button with data-copy-target="id" copies that field's text.
document.addEventListener("click", function (event) {
  var button = event.target.closest && event.target.closest("[data-copy-target]");
  if (!button) return;
  var field = document.getElementById(button.getAttribute("data-copy-target"));
  if (!field) return;
  var label = button.textContent;
  var done = function () {
    button.textContent = button.getAttribute("data-copied-label") || label;
    setTimeout(function () { button.textContent = label; }, 2000);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(field.value).then(done, function () { field.select(); document.execCommand("copy"); done(); });
  } else {
    field.select();
    document.execCommand("copy");
    done();
  }
});
